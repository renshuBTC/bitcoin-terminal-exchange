#!/usr/bin/env bash
# btx-launch.sh — one-command launcher for the BTX stack (Phase 3d).
#
# Brings up the whole "one local program" with a single command: full node (bitcoind) -> indexer
# (brk_cli) -> orchestrator+GUI (btxd) -> opens the browser at the dashboard. Idempotent (won't
# double-start what's already up), with per-chain defaults and readiness waits. `stop` tears it down.
#
#   bash btx-launch.sh            # start the stack on signet and open the GUI
#   bash btx-launch.sh stop       # stop btxd + brk_cli + bitcoind
#   CHAIN=regtest bash btx-launch.sh
#
# Override any default by exporting it first (CHAIN, DATADIR, WALLET, BIN, BRK_DIR, BTX_DIR,
# BRK_BLOCK_MAGIC, BRKPORT, BTXD_PORT). Set BITCOIND_HOST (+ BITCOIND_PORT, BITCOIND_USER,
# BITCOIND_PASS, BLOCKS_HOST_DATADIR) to skip starting a local bitcoind and reuse an existing
# fully-synced node — useful for mainnet to avoid a fresh IBD. This is the launcher; turning
# it into a true single-file OS installer is the remaining packaging work — see
# BTX-bundle-recipe.md.
set -u

CHAIN=${CHAIN:-signet}
BIN=${BIN:-$HOME/bitcoin-29.1/bin}
BTX_DIR=${BTX_DIR:-"/mnt/c/Users/Ren Shu/Documents/Claude/Projects/bitcoin-terminal-exchange"}
BRK_DIR=${BRK_DIR:-"/mnt/c/Users/Ren Shu/Documents/Claude/Projects/brk-btx"}
WALLET=${WALLET:-btx}
BRKPORT=${BRKPORT:-3140}
BTXD_PORT=${BTXD_PORT:-3333}

# per-chain defaults. DATADIR_DEF is per-chain so CHAIN=main can't silently
# inherit ~/sig-public — that was a bug pre-2026-05-29 (line 33 unconditionally
# defaulted DATADIR to ~/sig-public before $CHAIN was consulted).
case "$CHAIN" in
  signet)  CFLAG=-signet;  RPCPORT=${RPCPORT:-38332}; SUBDIR=signet;   MAGIC_DEF=0a03cf40; ORDCHAIN=signet;   DATADIR_DEF=$HOME/sig-public;;
  regtest) CFLAG=-regtest; RPCPORT=${RPCPORT:-18443}; SUBDIR=regtest;  MAGIC_DEF=fabfb5da; ORDCHAIN=regtest;  DATADIR_DEF=$HOME/.bitcoin;;
  testnet) CFLAG=-testnet; RPCPORT=${RPCPORT:-18332}; SUBDIR=testnet3; MAGIC_DEF=0b110907; ORDCHAIN=testnet;  DATADIR_DEF=$HOME/btc-testnet;;
  main|mainnet) CFLAG=-chain=main; RPCPORT=${RPCPORT:-8332}; SUBDIR=.; MAGIC_DEF=f9beb4d9; ORDCHAIN=mainnet;  DATADIR_DEF=$HOME/btc-main;;
  *) echo "unknown CHAIN=$CHAIN"; exit 2;;
esac
DATADIR=${DATADIR:-$DATADIR_DEF}

# External-RPC mode: when BITCOIND_HOST is set, skip starting bitcoind locally
# and point all clients (bitcoin-cli, brk_cli, ord) at the remote node. Lets
# you reuse an existing fully-synced bitcoind (e.g. on the Windows side via
# WSL bridge) without a fresh IBD into $DATADIR. $DATADIR is then just a thin
# holder for ord's index + WSL-side state — no chain data lives there.
BITCOIND_HOST=${BITCOIND_HOST:-}
EXTERNAL_RPC=0
CLIWRAP=""
if [ -n "$BITCOIND_HOST" ]; then
  EXTERNAL_RPC=1
  BITCOIND_PORT=${BITCOIND_PORT:-$RPCPORT}
  : "${BITCOIND_USER:?BITCOIND_HOST is set but BITCOIND_USER is missing}"
  : "${BITCOIND_PASS:?BITCOIND_HOST is set but BITCOIND_PASS is missing}"
  CLIWRAP="$HOME/.btx-cli-${CHAIN}-rpc.sh"
fi

BRK_BLOCK_MAGIC=${BRK_BLOCK_MAGIC:-$MAGIC_DEF}
# Where bitcoind keeps blocks + cookie on disk (read directly by ord and brk_cli).
# In external mode this is the *remote node's* datadir mounted on this machine
# (e.g. /mnt/c/.../AppData/Roaming/Bitcoin for a Windows bitcoind reached via WSL).
BLOCKS_HOST_DATADIR=${BLOCKS_HOST_DATADIR:-$DATADIR}
BLOCKSDIR="$BLOCKS_HOST_DATADIR/$SUBDIR/blocks"; [ "$SUBDIR" = "." ] && BLOCKSDIR="$BLOCKS_HOST_DATADIR/blocks"
COOKIE="$BLOCKS_HOST_DATADIR/$SUBDIR/.cookie";   [ "$SUBDIR" = "." ] && COOKIE="$BLOCKS_HOST_DATADIR/.cookie"
BRKDIR=${BRKDIR:-$HOME/brk-btx-$CHAIN}
ORDPORT=${ORDPORT:-3349}
ORD=${ORD:-$(command -v ord 2>/dev/null || true)}   # rune oracle/indexer (optional; enables rune trades)
ORDDIR=${ORDDIR:-$DATADIR/ord}

# bitcoin-cli command. In external mode we pass RPC creds inline so they
# never persist to disk for our own use; btxd gets a per-session 700-perm
# wrapper (created in section 3, wiped in stop_all) so it doesn't need to
# learn about -rpcconnect/-rpcuser/etc.
if [ "$EXTERNAL_RPC" = 1 ]; then
  CLI="$BIN/bitcoin-cli $CFLAG -rpcconnect=$BITCOIND_HOST -rpcport=$BITCOIND_PORT -rpcuser=$BITCOIND_USER -rpcpassword=$BITCOIND_PASS"
else
  CLI="$BIN/bitcoin-cli $CFLAG -datadir=$DATADIR"
fi

say(){ printf '\033[36m== %s\033[0m\n' "$*"; }
ok(){  printf '\033[32m%s\033[0m\n' "$*"; }
err(){ printf '\033[31m%s\033[0m\n' "$*"; }

open_browser(){
  local url="$1"
  if command -v wslview >/dev/null 2>&1; then wslview "$url"
  elif command -v cmd.exe >/dev/null 2>&1; then cmd.exe /c start "$url" >/dev/null 2>&1
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$url" >/dev/null 2>&1
  else echo "open this in your browser: $url"; fi
}

# Gracefully free a TCP port: SIGTERM the listener(s), wait, escalate to SIGKILL only if needed.
# The indexer's real process is the compiled binary `brk` (the cargo-run child), NOT `brk_cli`,
# so we target it by port — and SIGTERM (not -9) lets its fjall store flush, avoiding a reindex.
free_port(){
  local port="$1" pids i
  pids=$(ss -ltnpH "sport = :$port" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u)
  [ -z "$pids" ] && return 0
  kill $pids 2>/dev/null
  for i in $(seq 1 15); do
    ss -ltnH "sport = :$port" 2>/dev/null | grep -q . || return 0
    sleep 1
  done
  kill -9 $pids 2>/dev/null
}

stop_all(){
  say "stopping BTX stack"
  pkill -f "btxd.py" 2>/dev/null && ok "  btxd stopped"
  free_port "$BTXD_PORT"
  free_port "$BRKPORT"
  pkill -f "cargo run -p brk_cli" 2>/dev/null   # reap the cargo wrapper if it lingers
  ok "  brk_cli stopped"
  free_port "$ORDPORT"; pkill -f "ord .*--http-port $ORDPORT" 2>/dev/null
  ok "  ord stopped"
  if [ "$EXTERNAL_RPC" = 1 ]; then
    # Remote bitcoind is not ours to stop; just wipe the per-session CLI wrapper.
    [ -n "$CLIWRAP" ] && [ -f "$CLIWRAP" ] && rm -f "$CLIWRAP" && ok "  cli-wrapper wiped"
    ok "  bitcoind NOT touched (external RPC)"
  elif $CLI stop >/dev/null 2>&1; then
    printf '  bitcoind stopping'
    for i in $(seq 1 30); do pgrep -x bitcoind >/dev/null || break; printf '.'; sleep 1; done
    echo; ok "  bitcoind stopped"
  fi
  exit 0
}

[ "${1:-}" = "stop" ] && stop_all

# ---- 1. node ----------------------------------------------------------------
if [ "$EXTERNAL_RPC" = 1 ]; then
  say "node ($CHAIN @ $BITCOIND_HOST:$BITCOIND_PORT, EXTERNAL)"
  if $CLI getblockcount >/dev/null 2>&1; then
    ok "  reachable (height $($CLI getblockcount))"
  else
    err "  cannot reach $BITCOIND_HOST:$BITCOIND_PORT — check BITCOIND_USER/PASS + remote rpcallowip"
    exit 1
  fi
else
  say "node ($CHAIN, datadir $DATADIR)"
  if $CLI getblockcount >/dev/null 2>&1; then
    ok "  already running (height $($CLI getblockcount))"
  else
    mkdir -p "$DATADIR"
    # a just-stopped bitcoind shuts down asynchronously and holds the datadir lock until it exits;
    # wait for any lingering process to clear so we don't hit "Cannot obtain a lock on directory".
    for i in $(seq 1 30); do pgrep -x bitcoind >/dev/null || break; sleep 1; done
    "$BIN/bitcoind" $CFLAG -datadir="$DATADIR" -txindex=1 -datacarrier=1 -datacarriersize=240 \
      -fallbackfee=0.0002 -dbcache=300 -server -daemon \
      || { err "bitcoind failed to start"; exit 1; }
    for i in $(seq 1 60); do $CLI getblockcount >/dev/null 2>&1 && break; sleep 1; done
    $CLI getblockcount >/dev/null 2>&1 || { err "node RPC not ready"; exit 1; }
    ok "  started (height $($CLI getblockcount))"
  fi
fi

# wallet: load it, create on first run
if ! $CLI -rpcwallet="$WALLET" getwalletinfo >/dev/null 2>&1; then
  $CLI loadwallet "$WALLET" >/dev/null 2>&1 || $CLI createwallet "$WALLET" >/dev/null 2>&1
fi
$CLI -rpcwallet="$WALLET" getwalletinfo >/dev/null 2>&1 && ok "  wallet '$WALLET' ready" || err "  wallet '$WALLET' unavailable (continuing)"

# ---- 2. indexer (brk_cli) ---------------------------------------------------
say "indexer (brk_cli :$BRKPORT, magic $BRK_BLOCK_MAGIC)"
if curl -s "http://127.0.0.1:$BRKPORT/api/v1/btx/orders" >/dev/null 2>&1; then
  ok "  already serving"
else
  mkdir -p "$BRKDIR"
  if [ "$EXTERNAL_RPC" = 1 ]; then
    BRK_AUTH="--rpcconnect $BITCOIND_HOST --rpcport $BITCOIND_PORT --rpcuser $BITCOIND_USER --rpcpassword $BITCOIND_PASS"
  else
    BRK_AUTH="--rpcconnect 127.0.0.1 --rpcport $RPCPORT --rpccookiefile $DATADIR/$SUBDIR/.cookie"
  fi
  ( cd "$BRK_DIR" && BRK_BLOCK_MAGIC=$BRK_BLOCK_MAGIC nohup cargo run -p brk_cli -- \
      --brkdir "$BRKDIR" --blocksdir "$BLOCKSDIR" $BRK_AUTH \
      --brkport "$BRKPORT" >> "$HOME/btx-brk.log" 2>&1 & disown )
  echo "  starting (first run builds + indexes; tail ~/btx-brk.log). waiting up to 6 min…"
  for i in $(seq 1 120); do sleep 3; curl -s "http://127.0.0.1:$BRKPORT/api/v1/btx/orders" >/dev/null 2>&1 && break; done
  curl -s "http://127.0.0.1:$BRKPORT/api/v1/btx/orders" >/dev/null 2>&1 && ok "  serving" \
    || err "  not serving yet — still indexing? check ~/btx-brk.log (the GUI will fill in once it's up)"
fi

# ---- 2.5 rune oracle (ord) --------------------------------------------------
# Optional read-only ord --index-runes server: enables rune-backing validation + the GUI etch
# button. ord needs the chain flag (else it assumes mainnet and looks for the cookie in the wrong
# place). Local mode uses cookie auth; external mode passes the bitcoin-rpc-{url,username,password}
# triple and points --bitcoin-data-dir at the remote node's datadir so ord can read raw blocks.
ORD_ARG=""
if [ -n "$ORD" ] && [ -x "$ORD" ]; then
  say "rune oracle (ord :$ORDPORT, $($ORD --version 2>/dev/null || echo ord))"
  if curl -s "http://127.0.0.1:$ORDPORT/status" >/dev/null 2>&1; then
    ok "  already serving"
  else
    mkdir -p "$ORDDIR"
    if [ "$EXTERNAL_RPC" = 1 ]; then
      nohup "$ORD" --chain "$ORDCHAIN" --bitcoin-data-dir "$BLOCKS_HOST_DATADIR" \
        --bitcoin-rpc-url "http://$BITCOIND_HOST:$BITCOIND_PORT" \
        --bitcoin-rpc-username "$BITCOIND_USER" --bitcoin-rpc-password "$BITCOIND_PASS" \
        --data-dir "$ORDDIR" --index-runes server --http-port "$ORDPORT" >> "$HOME/btx-ord.log" 2>&1 & disown
    else
      nohup "$ORD" --chain "$ORDCHAIN" --bitcoin-data-dir "$DATADIR" --cookie-file "$COOKIE" \
        --data-dir "$ORDDIR" --index-runes server --http-port "$ORDPORT" >> "$HOME/btx-ord.log" 2>&1 & disown
    fi
    for i in $(seq 1 60); do sleep 1; curl -s "http://127.0.0.1:$ORDPORT/status" >/dev/null 2>&1 && break; done
  fi
  if curl -s "http://127.0.0.1:$ORDPORT/status" >/dev/null 2>&1; then
    ORD_ARG="--ord-url http://127.0.0.1:$ORDPORT"; ok "  serving"
  else
    err "  ord not up — rune backing/etch disabled (check ~/btx-ord.log)"
  fi
else
  say "rune oracle (ord): not found on PATH — rune backing/etch disabled (set ORD=/path/to/ord to enable)"
fi

# ---- 3. orchestrator + GUI (btxd) -----------------------------------------
say "orchestrator + GUI (btxd :$BTXD_PORT)"
if curl -s "http://127.0.0.1:$BTXD_PORT/api/config" >/dev/null 2>&1; then
  ok "  already running"
else
  # In external mode, write a 700-perm per-session wrapper that injects the remote
  # RPC creds, and hand THAT to btxd as --bitcoin-cli. btxd then never has to know
  # about -rpcconnect/-rpcuser/etc. Wrapper is wiped in stop_all().
  BTXD_CLI="$BIN/bitcoin-cli"
  if [ "$EXTERNAL_RPC" = 1 ]; then
    ( umask 077 && cat > "$CLIWRAP" <<EOF
#!/bin/sh
exec "$BIN/bitcoin-cli" $CFLAG -rpcconnect=$BITCOIND_HOST -rpcport=$BITCOIND_PORT -rpcuser='$BITCOIND_USER' -rpcpassword='$BITCOIND_PASS' "\$@"
EOF
    )
    chmod 700 "$CLIWRAP"
    BTXD_CLI="$CLIWRAP"
  fi
  ( cd "$BTX_DIR" && nohup python3 btxd.py --bitcoin-cli "$BTXD_CLI" --chain "$CHAIN" \
      --datadir "$DATADIR" --wallet "$WALLET" --brk-url "http://127.0.0.1:$BRKPORT" $ORD_ARG \
      --port "$BTXD_PORT" >> "$HOME/btx-btxd.log" 2>&1 & disown )
  for i in $(seq 1 20); do sleep 1; curl -s "http://127.0.0.1:$BTXD_PORT/api/config" >/dev/null 2>&1 && break; done
  curl -s "http://127.0.0.1:$BTXD_PORT/api/config" >/dev/null 2>&1 && ok "  running" || err "  btxd not up (check ~/btx-btxd.log)"
fi

URL="http://127.0.0.1:$BTXD_PORT/"
say "BTX is up — opening $URL"
open_browser "$URL"
echo
echo "  GUI:    $URL"
echo "  logs:   ~/btx-brk.log  ~/btx-btxd.log  ~/btx-ord.log"
echo "  stop:   bash btx-launch.sh stop"
