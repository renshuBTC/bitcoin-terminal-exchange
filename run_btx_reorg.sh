#!/bin/bash
# BTX live-indexer reorg integration test. Publishes an order on a regtest node, runs the BRK
# indexer (populating the btx_orders store), invalidates the announce block, re-mines, and
# re-indexes against the SAME output dir -> exercises Stores::rollback_btx_orders on a live reorg.
# Proof = the "BTX rollback ... removed N" log line on run 2, with the order still consistent.
# Run from the Bitcoin Terminal Exchange folder (btx_0b.py present); BRK is the sibling ../brk.
set -u
export PATH=$HOME/bitcoin-29.1/bin:$PATH
export BRK_BLOCK_MAGIC=fabfb5da   # regtest block-file magic, read by brk_reader scan
SCRIPTDIR="$(cd "$(dirname "$0")" && pwd)"
BRKDIR="$(cd "$SCRIPTDIR/../brk-btx" && pwd)"
DD=/tmp/rtcxo; PORT=19777; OUT=/tmp/btx_brk_out
cli(){ bitcoin-cli -datadir="$DD" -rpcport=$PORT "$@"; }   # cookie auth (default)

echo "[0] build the btx_reorg example"
( cd "$BRKDIR" && cargo build --example btx_reorg 2>&1 | tail -2 )
BIN="$BRKDIR/target/debug/examples/btx_reorg"
COOKIE="$DD/regtest/.cookie"; BLOCKS="$DD/regtest/blocks"; URL="http://127.0.0.1:$PORT"

echo "[1] start regtest node (cookie auth, datacarriersize=240)"
pkill -9 -f -- "-datadir=/tmp/rt" 2>/dev/null; sleep 2
rm -rf "$DD" "$OUT"; mkdir -p "$DD"
printf 'regtest=1\nserver=1\ntxindex=1\nfallbackfee=0.0002\ndatacarriersize=240\n[regtest]\nrpcport=%s\n' "$PORT" > "$DD/bitcoin.conf"
bitcoind -datadir="$DD" -daemon >/dev/null 2>&1
for i in $(seq 1 40); do cli getblockchaininfo >/dev/null 2>&1 && break; sleep 0.3; done
cli createwallet bank >/dev/null
BANK=$(cli -rpcwallet=bank getnewaddress "" bech32)
cli -rpcwallet=bank generatetoaddress 101 "$BANK" >/dev/null

echo "[2] fund maker offer(1.0), confirm it"
MO=$(cd "$SCRIPTDIR" && python3 -c "
import hashlib,bitcoin; bitcoin.SelectParams('regtest')
from bitcoin.core import Hash160
from bitcoin.core.script import CScript,OP_0
from bitcoin.wallet import CBitcoinSecret,P2WPKHBitcoinAddress
print(str(P2WPKHBitcoinAddress.from_scriptPubKey(CScript([OP_0,Hash160(CBitcoinSecret.from_secret_bytes(hashlib.sha256(b'btx-maker').digest()).pub)]))))")
OTX=$(cli -rpcwallet=bank sendtoaddress "$MO" 1.0)
cli -rpcwallet=bank generatetoaddress 1 "$BANK" >/dev/null
OV=$(cli getrawtransaction "$OTX" true | python3 -c "import sys,json
for o in json.load(sys.stdin)['vout']:
 if o['scriptPubKey'].get('address')=='$MO': print(o['n']);break")
OFFER_SATS=100000000

echo "[3] publish BTX order artifact on-chain, mine it (the announce block)"
BLOB=$(cd "$SCRIPTDIR" && python3 -c "
import btx_0b as c
from bitcoin.core import b2x
print(b2x(c.serialize_artifact(c.make_artifact('$OTX', $OV, $OFFER_SATS, int(0.5*1e8)))))")
RAW=$(cli -rpcwallet=bank createrawtransaction "[]" "[{\"data\":\"$BLOB\"}]")
FUND=$(cli -rpcwallet=bank fundrawtransaction "$RAW" | python3 -c "import sys,json;print(json.load(sys.stdin)['hex'])")
SIGNED=$(cli -rpcwallet=bank signrawtransactionwithwallet "$FUND" | python3 -c "import sys,json;print(json.load(sys.stdin)['hex'])")
ANN=$(cli sendrawtransaction "$SIGNED")
cli -rpcwallet=bank generatetoaddress 1 "$BANK" >/dev/null
ANN_BLOCK=$(cli getbestblockhash); ANN_HEIGHT=$(cli getblockcount)
echo "  announce tx=$ANN in block $ANN_HEIGHT ($ANN_BLOCK)"

echo "[4] RUN 1: index the chain -> btx_orders BEFORE reorg"
"$BIN" "$URL" "$COOKIE" "$BLOCKS" "$OUT" 2>/dev/null | grep -E 'BTX_ORDER|INDEXED_HEIGHT'

echo "[5] REORG: invalidate the announce block, mine 2 EMPTY blocks (announce orphaned, not re-mined)"
cli invalidateblock "$ANN_BLOCK"
FRESH=$(cli -rpcwallet=bank getnewaddress "" bech32)
cli generateblock "$FRESH" "[]" >/dev/null 2>&1
cli generateblock "$FRESH" "[]" >/dev/null 2>&1
echo "  new tip height $(cli getblockcount)"

echo "[6] RUN 2: re-index SAME store -> triggers rollback_btx_orders (watch for the log line)"
"$BIN" "$URL" "$COOKIE" "$BLOCKS" "$OUT" 2>&1 | grep -E 'BTX rollback|BTX_ORDER|INDEXED_HEIGHT'
cli stop >/dev/null 2>&1
echo "DONE_BTX_REORG"
