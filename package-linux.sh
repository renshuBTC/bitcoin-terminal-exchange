#!/usr/bin/env bash
# package-linux.sh — build a single-download Linux/WSL bundle of BTX (Phase 3d packaging).
#
# Produces dist/btx-<ver>-linux-x86_64.tar.gz containing everything a user needs:
#   bin/bitcoind bin/bitcoin-cli bin/brk_cli           (native binaries)
#   btxd btx_wallet btx_envelope_publish         (PyInstaller-frozen, no Python needed)
#   *.html                                              (the GUI)
#   run                                                 (the launcher: node -> indexer -> GUI)
# The user then: tar xzf …; cd btx-…; ./run   -> the dashboard opens. No cargo, no pip, no manual node.
#
# RUN THIS IN WSL/Linux. Prereqs (the script checks/installs what it can):
#   - pyinstaller            (pip install pyinstaller --break-system-packages)
#   - python-bitcoinlib      (already used by the tooling)
#   - a NATIVE Linux brk_cli build: in the brk-btx repo, `cargo build --release -p brk_cli`
#   - bitcoind/bitcoin-cli   (v29.1)
# Override source paths via env: BITCOIND, BITCOINCLI, BRK_CLI, BTX_DIR, VER, OUT.
set -euo pipefail

VER=${VER:-0.1.1}  # 0.1.1: security-hardening release — btxd loopback Host: guard (DNS-rebinding),
                   # terminal innerHTML esc(), bounds-safe ByteView deserialization (no panic on corrupt store)
BTX_DIR=${BTX_DIR:-"/mnt/c/Users/Ren Shu/Documents/Claude/Projects/bitcoin-terminal-exchange"}
BRK_DIR=${BRK_DIR:-"/mnt/c/Users/Ren Shu/Documents/Claude/Projects/brk"}
BITCOIND=${BITCOIND:-$HOME/bitcoin-29.1/bin/bitcoind}
BITCOINCLI=${BITCOINCLI:-$HOME/bitcoin-29.1/bin/bitcoin-cli}
BRK_CLI=${BRK_CLI:-$BRK_DIR/target/release/brk}   # the brk_cli crate's binary is named 'brk'
ORD=${ORD:-$(command -v ord 2>/dev/null || true)}  # rune oracle/indexer (optional; enables rune trades)
OUT=${OUT:-$BTX_DIR/dist}
STAGE="$OUT/btx-$VER-linux-x86_64"

say(){ printf '\033[36m== %s\033[0m\n' "$*"; }
need(){ [ -f "$1" ] || { printf '\033[31mmissing: %s\033[0m\n' "$1"; printf '   %s\n' "$2"; exit 1; }; }

say "checking inputs"
need "$BITCOIND"   "install Bitcoin Core v29.1 or set BITCOIND="
need "$BITCOINCLI" "set BITCOINCLI="
need "$BRK_CLI"    "build it first: (cd '$BRK_DIR' && cargo build --release -p brk_cli)  or set BRK_CLI="
command -v pyinstaller >/dev/null 2>&1 || { say "installing pyinstaller"; pip install pyinstaller --break-system-packages -q; }

say "freezing python tools with PyInstaller (onefile)"
WORK="$OUT/_build"; rm -rf "$WORK" "$STAGE"; mkdir -p "$WORK" "$STAGE/bin"
cd "$BTX_DIR"
for tool in btxd btx_wallet btx_envelope_publish btx_etch; do
  # --collect-all bitcoin pulls python-bitcoinlib data; the local *.py are picked up as imports.
  pyinstaller --onefile --distpath "$STAGE" --workpath "$WORK" --specpath "$WORK" \
    --collect-all bitcoin --name "$tool" "$BTX_DIR/$tool.py"
done

say "assembling bundle"
cp "$BITCOIND" "$STAGE/bin/bitcoind"
cp "$BITCOINCLI" "$STAGE/bin/bitcoin-cli"
cp "$BRK_CLI" "$STAGE/bin/brk_cli"
if [ -n "$ORD" ] && [ -x "$ORD" ]; then
  cp "$ORD" "$STAGE/bin/ord"; say "  bundled ord: $("$ORD" --version 2>/dev/null || echo '?')"
else
  say "  (no ord binary found — rune backing/etch will be disabled in the bundle; set ORD=/path/to/ord)"
fi
cp "$BTX_DIR"/*.html "$STAGE"/ 2>/dev/null || true

cat > "$STAGE/run" <<'RUN'
#!/usr/bin/env bash
# BTX bundle launcher — starts node -> indexer -> orchestrator+GUI, then opens the browser.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
CHAIN=${CHAIN:-signet}
DATADIR=${DATADIR:-$HOME/.btx/$CHAIN}
WALLET=${WALLET:-btx}
BRKPORT=${BRKPORT:-3140}; BTXD_PORT=${BTXD_PORT:-3333}; ORDPORT=${ORDPORT:-3349}
case "$CHAIN" in
  signet)  CFLAG=-signet;  RPCPORT=38332; SUBDIR=signet;  MAGIC=0a03cf40; ORDCHAIN=signet;;
  regtest) CFLAG=-regtest; RPCPORT=18443; SUBDIR=regtest; MAGIC=fabfb5da; ORDCHAIN=regtest;;
  main)    CFLAG=-chain=main; RPCPORT=8332; SUBDIR=.;     MAGIC=f9beb4d9; ORDCHAIN=mainnet;;
  *) echo "unknown CHAIN=$CHAIN"; exit 2;;
esac
mkdir -p "$DATADIR"
CLI="$HERE/bin/bitcoin-cli $CFLAG -datadir=$DATADIR"
BLK="$DATADIR/$SUBDIR/blocks"; [ "$SUBDIR" = "." ] && BLK="$DATADIR/blocks"
COOKIE="$DATADIR/$SUBDIR/.cookie"; [ "$SUBDIR" = "." ] && COOKIE="$DATADIR/.cookie"
[ "${1:-}" = stop ] && { pkill -f "$HERE/btxd"; pkill -f "$HERE/bin/brk_cli"; pkill -f "$HERE/bin/ord"; $CLI stop 2>/dev/null; exit 0; }
echo "== node ($CHAIN)"
up=0; for i in 1 2 3; do $CLI getblockcount >/dev/null 2>&1 && { up=1; break; }; sleep 1; done
if [ "$up" = 0 ]; then
  # a just-stopped bitcoind shuts down asynchronously and holds the datadir lock until it exits;
  # wait for any lingering process to clear so a quick `./run stop` -> `./run` won't hit the lock.
  for i in $(seq 1 30); do pgrep -x bitcoind >/dev/null || break; sleep 1; done
  "$HERE/bin/bitcoind" $CFLAG -datadir="$DATADIR" -txindex=1 -datacarrier=1 -datacarriersize=240 -fallbackfee=0.0002 -dbcache=300 -server -daemon 2>/dev/null
  for i in $(seq 1 60); do $CLI getblockcount >/dev/null 2>&1 && break; sleep 1; done
fi
$CLI getblockcount >/dev/null 2>&1 && echo "  node ok (height $($CLI getblockcount))" || echo "  node not ready"
$CLI -rpcwallet="$WALLET" getwalletinfo >/dev/null 2>&1 || $CLI loadwallet "$WALLET" >/dev/null 2>&1 || $CLI createwallet "$WALLET" >/dev/null 2>&1
echo "== indexer"; curl -s "http://127.0.0.1:$BRKPORT/api/v1/btx/orders" >/dev/null 2>&1 || {
  mkdir -p "$DATADIR/brkdir"
  BRK_BLOCK_MAGIC=$MAGIC nohup "$HERE/bin/brk_cli" --brkdir "$DATADIR/brkdir" --blocksdir "$BLK" \
    --rpcconnect 127.0.0.1 --rpcport "$RPCPORT" --rpccookiefile "$DATADIR/$SUBDIR/.cookie" \
    --brkport "$BRKPORT" >>"$DATADIR/brk.log" 2>&1 & disown
  for i in $(seq 1 120); do sleep 3; curl -s "http://127.0.0.1:$BRKPORT/api/v1/btx/orders" >/dev/null 2>&1 && break; done; }
# rune oracle: bundled ord as a read-only --index-runes server (no ord wallet). Enables rune-backing
# validation + the GUI etch button. Optional — skipped cleanly if ord wasn't bundled.
ORD_ARG=""
if [ -x "$HERE/bin/ord" ]; then
  echo "== rune oracle (ord)"
  curl -s "http://127.0.0.1:$ORDPORT/status" >/dev/null 2>&1 || {
    # ord needs the chain flag (else it assumes mainnet and looks for the cookie in the wrong
    # place) and the explicit cookie path bitcoind actually writes for this chain.
    nohup "$HERE/bin/ord" --chain "$ORDCHAIN" --bitcoin-data-dir "$DATADIR" \
      --cookie-file "$COOKIE" --data-dir "$DATADIR/ord" --index-runes \
      server --http-port "$ORDPORT" >>"$DATADIR/ord.log" 2>&1 & disown
    for i in $(seq 1 60); do sleep 1; curl -s "http://127.0.0.1:$ORDPORT/status" >/dev/null 2>&1 && break; done; }
  if curl -s "http://127.0.0.1:$ORDPORT/status" >/dev/null 2>&1; then
    ORD_ARG="--ord-url http://127.0.0.1:$ORDPORT"; echo "  ord oracle ok ($ORDPORT)"
  else
    echo "  WARNING: ord did not come up — rune backing/etch disabled. See $DATADIR/ord.log"
  fi
fi
echo "== GUI"; curl -s "http://127.0.0.1:$BTXD_PORT/api/config" >/dev/null 2>&1 || {
  BTX_UI_DIR="$HERE" nohup "$HERE/btxd" --bitcoin-cli "$HERE/bin/bitcoin-cli" --chain "$CHAIN" \
    --datadir "$DATADIR" --wallet "$WALLET" --brk-url "http://127.0.0.1:$BRKPORT" $ORD_ARG --port "$BTXD_PORT" \
    >>"$DATADIR/btxd.log" 2>&1 & disown
  for i in $(seq 1 20); do sleep 1; curl -s "http://127.0.0.1:$BTXD_PORT/api/config" >/dev/null 2>&1 && break; done; }
URL="http://127.0.0.1:$BTXD_PORT/"
( command -v wslview >/dev/null 2>&1 && wslview "$URL" ) || ( command -v xdg-open >/dev/null 2>&1 && xdg-open "$URL" ) || echo "open: $URL"
echo "BTX up — $URL   (stop: ./run stop)"
RUN
chmod +x "$STAGE/run"

cat > "$STAGE/README.txt" <<TXT
BTX $VER (linux/x86_64) — one local program: full node + wallet + solo-mining + on-chain DEX.
Run:   ./run            (starts everything on signet, opens the GUI at http://127.0.0.1:3333/)
Stop:  ./run stop
Mainnet:  CHAIN=main ./run   (warning: a from-scratch mainnet sync is hundreds of GB)
No website, no relay, no server-side state. Signing goes through your own bundled Bitcoin Core wallet.
TXT

say "taring up"
cd "$OUT"; tar czf "btx-$VER-linux-x86_64.tar.gz" "btx-$VER-linux-x86_64"
rm -rf "$WORK"
say "done -> $OUT/btx-$VER-linux-x86_64.tar.gz"
echo "  contents:"; ( cd "$STAGE/.." && find "btx-$VER-linux-x86_64" -maxdepth 1 | sort | sed 's/^/    /' )
