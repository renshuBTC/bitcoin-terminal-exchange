#!/usr/bin/env bash
# BTX live verify — one-shot regtest loop that proves the btx_orders book serves over HTTP.
# Scoped entirely to a throwaway datadir ($RT) and throwaway BRK dir ($BRKDIR): it CANNOT touch
# your real node/wallet. Run from anywhere:  bash btx_live_verify.sh [op_return|envelope]
# (carrier defaults to op_return; "envelope" routes publish through btx_envelope_publish.py and
#  proves the Taproot witness-envelope carrier end-to-end, including btx::extract_from_witness.)
#
# What it does, with the two evidence checkpoints called out:
#   1. start regtest bitcoind, fund a P2WPKH offer UTXO
#   2. CHECKPOINT A: gettxout(offer) must be non-null (offer healthy before publish)
#   3. maker-sign (auto-locks the offer) -> publish via $CARRIER (OP_RETURN | witness envelope) -> mine
#   4. CHECKPOINT B: gettxout(offer) must STILL be non-null (carrier funding didn't eat the offer)
#   5. start brk_cli (BRK_BLOCK_MAGIC=fabfb5da), wait until it indexes to tip
#   6. curl /api/v1/btx/orders -> expect ONE open order  => PASS
set -u

# ---- config (override by exporting before running) -------------------------
RT=${RT:-/tmp/rt-btx}
BRKDIR=${BRKDIR:-/tmp/brk-btx-verify}
BTX=${BTX:-"/mnt/c/Users/Ren Shu/Documents/Claude/Projects/bitcoin-terminal-exchange"}
BRK=${BRK:-"/mnt/c/Users/Ren Shu/Documents/Claude/Projects/brk-btx"}
RPCPORT=${RPCPORT:-18443}
BRKPORT=${BRKPORT:-3119}   # throwaway port; deliberately NOT 3110 so it can't hit a real brk_cli you have running
CARRIER=${CARRIER:-op_return}        # op_return | envelope  (envelope uses btx_envelope_publish.py)
case "${1:-}" in envelope) CARRIER=envelope;; op_return) CARRIER=op_return;; esac
# Auto-detect bitcoind/bitcoin-cli: PATH first, then the known /tmp install, then any /tmp/bitcoin-*/bin.
_find_bin() {  # $1 = binary name
  if command -v "$1" >/dev/null 2>&1; then command -v "$1"; return; fi
  for c in /tmp/bitcoin-*/bin/"$1" /usr/local/bin/"$1" "$HOME"/bitcoin*/bin/"$1"; do
    [ -x "$c" ] && { echo "$c"; return; }
  done
  echo "$1"  # fall back to bare name (will error clearly if truly missing)
}
BITCOIND=${BITCOIND:-$(_find_bin bitcoind)}
BITCOINCLI=${BITCOINCLI:-$(_find_bin bitcoin-cli)}
BCLI="$BITCOINCLI -chain=regtest -datadir=$RT -rpcport=$RPCPORT"
echo "using bitcoind   = $BITCOIND"
echo "using bitcoin-cli = $BITCOINCLI"
LOG=$BRKDIR.log

red()  { printf '\033[31m%s\033[0m\n' "$*"; }
grn()  { printf '\033[32m%s\033[0m\n' "$*"; }
say()  { printf '\033[36m== %s\033[0m\n' "$*"; }
die()  { red "FAIL: $*"; exit 1; }

# ---- clean any prior throwaway state ---------------------------------------
say "cleaning prior throwaway state (scoped to $RT / $BRKDIR)"
$BITCOINCLI -chain=regtest -datadir=$RT -rpcport=$RPCPORT stop >/dev/null 2>&1
sleep 2
pkill -9 -f -- "-datadir=$RT" 2>/dev/null
rm -rf "$RT" "$BRKDIR" "$LOG"
mkdir -p "$RT"

# ---- 1. start regtest node, mine to maturity --------------------------------
say "starting regtest bitcoind (datacarriersize=240)"
$BITCOIND -chain=regtest -datadir=$RT -rpcport=$RPCPORT -fallbackfee=0.0002 \
          -txindex=1 -datacarrier=1 -datacarriersize=240 -server -daemon || die "bitcoind start"
for i in $(seq 1 30); do $BCLI getblockchaininfo >/dev/null 2>&1 && break; sleep 1; done
$BCLI createwallet btx >/dev/null || die "createwallet"
MINER=$($BCLI getnewaddress "" bech32)
$BCLI generatetoaddress 101 "$MINER" >/dev/null

# ---- 2. fund a P2WPKH offer UTXO -------------------------------------------
say "funding P2WPKH offer UTXO (1.0 BTC)"
OFFER_ADDR=$($BCLI getnewaddress "" bech32)
OFFER_TXID=$($BCLI sendtoaddress "$OFFER_ADDR" 1.0)
$BCLI generatetoaddress 1 "$MINER" >/dev/null
# derive vout from the wallet's unspent set (no -txindex dependence; also confirms it's unspent)
OFFER_VOUT=$($BCLI listunspent 1 9999999 "[\"$OFFER_ADDR\"]" \
  | python3 -c "import sys,json;u=[x for x in json.load(sys.stdin) if x['txid']=='$OFFER_TXID'];assert u,'offer not in unspent set';print(u[0]['vout'])") \
  || die "could not locate offer vout in unspent set"
echo "offer = $OFFER_TXID:$OFFER_VOUT"

# ---- CHECKPOINT A: offer must be unspent now --------------------------------
say "CHECKPOINT A: offer UTXO must be unspent before publish"
$BCLI gettxout "$OFFER_TXID" "$OFFER_VOUT" | grep -q '"value"' \
  || die "offer UTXO already missing at checkpoint A (funding problem)"
grn "  A ok: offer is unspent"

# ---- 3. maker-sign (auto-locks offer) + publish OP_RETURN carrier ----------
say "maker-sign (auto-locks the offer) + publish carrier"
cd "$BTX" || die "cd BTX"
SIGN_JSON=$(python3 btx_wallet.py maker-sign --bitcoin-cli "$BITCOINCLI" \
              --datadir "$RT" --wallet btx \
              --offer-txid "$OFFER_TXID" --offer-vout "$OFFER_VOUT" --price-btc 0.5 \
              --carrier "$CARRIER") \
  || die "maker-sign"
echo "$SIGN_JSON" | python3 -c "import sys,json;d=json.load(sys.stdin);assert d.get('maker_sig_self_verifies'),'sig self-verify false';print('  maker_sig_self_verifies:',d['maker_sig_self_verifies'],'offer_locked:',d.get('offer_locked'))" \
  || die "maker sig did not self-verify"
ART=$(echo "$SIGN_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin)['artifact_hex'])")
echo "  artifact bytes: $(( ${#ART} / 2 ))"

if [ "$CARRIER" = "envelope" ]; then
  say "publishing via Taproot witness-envelope carrier (commit -> reveal; no OP_RETURN)"
  PUB_JSON=$(python3 btx_envelope_publish.py publish --artifact-hex "$ART" \
              --bitcoin-cli "$BITCOINCLI" --chain regtest --datadir "$RT" --wallet btx \
              --commit-amount-btc 0.0005 --fee-sats 2000 --broadcast) \
    || die "envelope publish failed (reveal rejected? check the script-path sighash / control block)"
  echo "$PUB_JSON" | python3 -c "import sys,json;d=json.load(sys.stdin);print('  commit',d['commit_txid']+':'+str(d['commit_vout']),' reveal',d['reveal_txid'])" \
    || die "envelope publish produced no reveal_txid"
  ANNOUNCE=$(echo "$PUB_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin)['reveal_txid'])")
else
  say "publishing via OP_RETURN carrier"
  RAW=$($BCLI createrawtransaction '[]' "[{\"data\":\"$ART\"}]")
  FUNDED=$($BCLI fundrawtransaction "$RAW" | python3 -c "import sys,json;print(json.load(sys.stdin)['hex'])") || die "fundrawtransaction"
  SIGNED=$($BCLI signrawtransactionwithwallet "$FUNDED" | python3 -c "import sys,json;print(json.load(sys.stdin)['hex'])")
  ANNOUNCE=$($BCLI sendrawtransaction "$SIGNED") || die "sendrawtransaction (carrier)"
fi
$BCLI generatetoaddress 1 "$MINER" >/dev/null
# +2 buffer blocks so bitcoind flushes the announce block to blk*.dat before BRK reads from disk
$BCLI generatetoaddress 2 "$MINER" >/dev/null
echo "  announce txid ($CARRIER) = $ANNOUNCE"

# ---- CHECKPOINT B: offer must STILL be unspent (carrier didn't eat it) -----
say "CHECKPOINT B: offer UTXO must still be unspent after carrier funding"
$BCLI gettxout "$OFFER_TXID" "$OFFER_VOUT" | grep -q '"value"' \
  || die "offer UTXO got spent by carrier funding (auto-lock failed) -> order would be rejected"
grn "  B ok: offer still unspent at index time"

# ---- 5. start BRK, wait for it to index to tip ------------------------------
say "starting brk_cli (background); log -> $LOG"
TIP=$($BCLI getblockcount)
mkdir -p "$BRKDIR" || die "mkdir brkdir"
cd "$BRK" || die "cd BRK"
BRK_BLOCK_MAGIC=fabfb5da cargo run -p brk_cli -- \
  --brkdir "$BRKDIR" \
  --blocksdir "$RT/regtest/blocks" \
  --rpcconnect 127.0.0.1 --rpcport "$RPCPORT" \
  --rpccookiefile "$RT/regtest/.cookie" \
  --brkport "$BRKPORT" > "$LOG" 2>&1 &
BRK_PID=$!
echo "  brk_cli pid = $BRK_PID ; chain tip = $TIP"

say "waiting for BRK to index + serve (up to 180s)"
ORDERS='[]'
for i in $(seq 1 60); do
  sleep 3
  if ! kill -0 "$BRK_PID" 2>/dev/null; then
    red "  brk_cli exited early — tail of log:"; tail -n 40 "$LOG"; die "brk_cli died"
  fi
  ORDERS=$(curl -s "http://127.0.0.1:$BRKPORT/api/v1/btx/orders" 2>/dev/null || echo '')
  if echo "$ORDERS" | grep -q 'offer_txid\|offer_vout\|"open"\|price'; then break; fi
  if grep -q 'Waiting for new blocks' "$LOG" 2>/dev/null; then sleep 2; \
     ORDERS=$(curl -s "http://127.0.0.1:$BRKPORT/api/v1/btx/orders" 2>/dev/null || echo ''); break; fi
done

# ---- 6. result --------------------------------------------------------------
say "GET /api/v1/btx/orders"
echo "$ORDERS" | python3 -m json.tool 2>/dev/null || echo "$ORDERS"

COUNT=$(echo "$ORDERS" | python3 -c "import sys,json;
try: d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else len(d.get('orders',[])))
except Exception: print(0)" 2>/dev/null)
echo
if [ "${COUNT:-0}" -ge 1 ]; then
  grn "PASS (serve): served $COUNT open order(s). btx_orders is durable + query-visible on a live node."
else
  red "EMPTY: API returned no orders. Checkpoints A+B passed (offer was unspent), so capture:"
  echo "    tail -n 60 $LOG"
  echo "  and the indexed-height log lines, and we'll localize the store path with that evidence."
fi

# ---- 7. FULL CYCLE: taker fills off the served book -> order must leave the open book (FILLED) ----
if [ "${COUNT:-0}" -ge 1 ]; then
  say "taker fills the served order (btx_wallet taker-fill --broadcast)"
  cd "$BTX" || die "cd BTX"
  FILL_JSON=$(python3 btx_wallet.py taker-fill --bitcoin-cli "$BITCOINCLI" \
                --datadir "$RT" --wallet btx --artifact-hex "$ART" --broadcast) \
    || die "taker-fill failed"
  echo "$FILL_JSON"
  SWAP_TXID=$(echo "$FILL_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin).get('txid',''))" 2>/dev/null)
  [ -n "$SWAP_TXID" ] || die "taker-fill did not broadcast a swap (no txid)"
  echo "  swap txid = $SWAP_TXID"
  $BCLI generatetoaddress 1 "$MINER" >/dev/null   # confirm the fill
  $BCLI generatetoaddress 2 "$MINER" >/dev/null   # buffer so BRK flushes the block from disk

  say "CHECKPOINT C: offer UTXO must now be SPENT (settlement happened)"
  if $BCLI gettxout "$OFFER_TXID" "$OFFER_VOUT" | grep -q '"value"'; then
    die "offer UTXO still unspent after fill — swap did not settle"
  fi
  grn "  C ok: offer UTXO consumed (gettxout null) — atomic swap settled in one tx"

  say "waiting for BRK to re-index the fill (order should flip to FILLED and leave the open book)"
  AFTER='?'; AFTER_COUNT='-1'
  for i in $(seq 1 40); do
    sleep 3
    AFTER=$(curl -s "http://127.0.0.1:$BRKPORT/api/v1/btx/orders" 2>/dev/null || echo '')
    AFTER_COUNT=$(echo "$AFTER" | python3 -c "import sys,json
try: d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else len(d.get('orders',[])))
except Exception: print(-1)" 2>/dev/null)
    [ "$AFTER_COUNT" = "0" ] && break
  done
  say "GET /api/v1/btx/orders (after fill)"
  echo "$AFTER" | python3 -m json.tool 2>/dev/null || echo "$AFTER"
  echo
  if [ "$AFTER_COUNT" = "0" ]; then
    grn "PASS (full cycle): publish -> served OPEN -> taker filled on-chain -> order left the open book."
    grn "  => Pass 2 (FILLED detection) works on a live node; the complete DEX lifecycle is proven live."
  else
    red "INCOMPLETE: order still in the open book after fill+reindex (count=$AFTER_COUNT)."
    echo "  The swap settled (checkpoint C passed) but the served book didn't drop the order — capture:"
    echo "    tail -n 60 $LOG"
  fi
fi

echo
say "left running for inspection: bitcoind (datadir $RT), brk_cli (pid $BRK_PID, :$BRKPORT)"
echo "  re-query: curl -s http://127.0.0.1:$BRKPORT/api/v1/btx/orders | jq"
echo "  stop all: kill $BRK_PID; $BITCOINCLI -chain=regtest -datadir=$RT -rpcport=$RPCPORT stop; rm -rf $RT $BRKDIR $LOG"
