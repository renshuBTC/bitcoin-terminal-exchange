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
# BRK_BLOCK_MAGIC, BRKPORT, BTXD_PORT). This is the launcher; turning it into a true single-file
# OS installer is the remaining packaging work — see BTX-bundle-recipe.md.
set -u

CHAIN=${CHAIN:-signet}
BIN=${BIN:-$HOME/bitcoin-29.1/bin}
BTX_DIR=${BTX_DIR:-"/mnt/c/Users/Ren Shu/Documents/Claude/Projects/bitcoin-terminal-exchange"}
BRK_DIR=${BRK_DIR:-"/mnt/c/Users/Ren Shu/Documents/Claude/Projects/brk-btx"}
WALLET=${WALLET:-btx}
BRKPORT=${BRKPORT:-3140}
BTXD_PORT=${BTXD_PORT:-3333}

# per-chain defaults
case "$CHAIN" in
  signet)  CFLAG=-signet;  RPCPORT=${RPCPORT:-38332}; SUBDIR=signet;   MAGIC_DEF=0a03cf40; ORDCHAIN=signet;;
  regtest) CFLAG=-regtest; RPCPORT=${RPCPORT:-18443}; SUBDIR=regtest;  MAGIC_DEF=fabfb5da; ORDCHAIN=regtest;;
  testnet) CFLAG=-testnet; RPCPORT=${RPCPORT:-18332}; SUBDIR=testnet3; MAGIC_DEF=0b110907; ORDCHAIN=testnet;;
  main|mainnet) CFLAG=-chain=main; RPCPORT=${RPCPORT:-8332}; SUBDIR=.; MAGIC_DEF=f9beb4d9; ORDCHAIN=mainnet;;
  *) echo "unknown CHAIN=$CHAIN"; exit 2;;
esac
DATADIR=${DATADIR:-$HOME/sig-public}
[ "$CHAIN" = regtest ] && DATADIR=${DATADIR:-$HOME/.bitcoin}
BRK_BLOCK_MAGIC=${BRK_BLOCK_MAGIC:-$MAGIC_DEF}
BLOCKSDIR="$DATADIR/$SUBDIR/blocks"; [ "$SUBDIR" = "." ] && BLOCKSDIR="$DATADIR/blocks"
COOKIE="$DATADIR/$SUBDIR/.cookie"; [ "$SUBDIR" = "." ] && COOKIE="$DATADIR/.cookie"
BRKDIR=${BRKDIR:-$HOME/brk-btx-$CHAIN}
ORDPORT=${ORDPORT:-3349}
ORD=${ORD:-$(command -v ord 2>/dev/null || true)}   # rune oracle/indexer (optional; enables rune trades)
ORDDIR=${ORDDIR:-$DATADIR/ord}
CLI="$BIN/bitcoin-cli $CFLAG -datadir=$DATADIR"

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
  if $CLI stop >/dev/null 2>&1; then
    printf '  bitcoind stopping'
    for i in $(seq 1 30); do pgrep -x bitcoind >/dev/null || break; printf '.'; sleep 1; done
    echo; ok "  bitcoind stopped"
  fi
  exit 0
}

[ "${1:-}" = "stop" ] && stop_all

# ---- 1. node ----------------------------------------------------------------
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
  ( cd "$BRK_DIR" && BRK_BLOCK_MAGIC=$BRK_BLOCK_MAGIC nohup cargo run -p brk_cli -- \
      --brkdir "$BRKDIR" --blocksdir "$BLOCKSDIR" \
      --rpcconnect 127.0.0.1 --rpcport "$RPCPORT" --rpccookiefile "$DATADIR/$SUBDIR/.cookie" \
      --brkport "$BRKPORT" >> "$HOME/btx-brk.log" 2>&1 & disown )
  echo "  starting (first run builds + indexes; tail ~/btx-brk.log). waiting up to 6 min…"
  for i in $(seq 1 120); do sleep 3; curl -s "http://127.0.0.1:$BRKPORT/api/v1/btx/orders" >/dev/null 2>&1 && break; done
  curl -s "http://127.0.0.1:$BRKPORT/api/v1/btx/orders" >/dev/null 2>&1 && ok "  serving" \
    || err "  not serving yet — still indexing? check ~/btx-brk.log (the GUI will fill in once it's up)"
fi

# ---- 2.5 rune oracle (ord) --------------------------------------------------
# Optional read-only ord --index-runes server: enables rune-backing validation + the GUI etch
# button. ord needs the chain flag (else it assumes mainnet and looks for the cookie in the wrong
# place) and the explicit cookie path bitcoind writes for this chain. Skipped cleanly if no ord.
ORD_ARG=""
if [ -n "$ORD" ] && [ -x "$ORD" ]; then
  say "rune oracle (ord :$ORDPORT, $($ORD --version 2>/dev/null || echo ord))"
  if curl -s "http://127.0.0.1:$ORDPORT/status" >/dev/null 2>&1; then
    ok "  already serving"
  else
    mkdir -p "$ORDDIR"
    nohup "$ORD" --chain "$ORDCHAIN" --bitcoin-data-dir "$DATADIR" --cookie-file "$COOKIE" \
      --data-dir "$ORDDIR" --index-runes server --http-port "$ORDPORT" >> "$HOME/btx-ord.log" 2>&1 & disown
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
  ( cd "$BTX_DIR" && nohup python3 btxd.py --bitcoin-cli "$BIN/bitcoin-cli" --chain "$CHAIN" \
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
