#!/bin/bash
# BTX Phase 0 / Milestone 0a orchestration. Logs every step; no scantxoutset (too heavy).
export PATH=/tmp/bitcoin-29.1/bin:$PATH
DD=/tmp/rt3; PORT=19222
cli(){ bitcoin-cli -datadir=$DD -rpcport=$PORT -rpcuser=btx -rpcpassword=btx -rpcclienttimeout=8 "$@"; }
echo "[1] cleanup + start node"
pkill -9 -f -- "-datadir=/tmp/rt" 2>/dev/null
sleep 1
rm -rf $DD; mkdir -p $DD
printf 'regtest=1\nserver=1\ntxindex=1\nfallbackfee=0.0002\nrpcuser=btx\nrpcpassword=btx\n[regtest]\nrpcport=%s\n' "$PORT" > $DD/bitcoin.conf
bitcoind -datadir=$DD -daemon >/dev/null 2>&1
for i in $(seq 1 40); do cli getblockchaininfo >/dev/null 2>&1 && { echo "  node up after $i tries"; break; }; sleep 0.3; done

echo "[2] fund maker offer (1.0) + taker payment (0.6)"
cli createwallet bank >/dev/null
BANK=$(cli -rpcwallet=bank getnewaddress "" bech32)
cli -rpcwallet=bank generatetoaddress 101 "$BANK" >/dev/null
ADDRS=$(python3 -c "
import hashlib, bitcoin
bitcoin.SelectParams('regtest')
from bitcoin.core import Hash160
from bitcoin.core.script import CScript, OP_0
from bitcoin.wallet import CBitcoinSecret, P2WPKHBitcoinAddress
a=lambda s:str(P2WPKHBitcoinAddress.from_scriptPubKey(CScript([OP_0,Hash160(CBitcoinSecret.from_secret_bytes(hashlib.sha256(s).digest()).pub)])))
print(a(b'btx-maker'), a(b'btx-taker'))")
MAKER_OFFER=$(echo $ADDRS|awk '{print $1}'); TAKER=$(echo $ADDRS|awk '{print $2}')
OFFER_TXID=$(cli -rpcwallet=bank sendtoaddress "$MAKER_OFFER" 1.0)
PAY_TXID=$(cli -rpcwallet=bank sendtoaddress "$TAKER" 0.6)
cli -rpcwallet=bank generatetoaddress 1 "$BANK" >/dev/null
echo "  offer txid=$OFFER_TXID  pay txid=$PAY_TXID"

echo "[3] locate funded vouts"
findvout(){ # $1=txid $2=address
  cli getrawtransaction "$1" true | python3 -c "
import sys,json
tx=json.load(sys.stdin)
for o in tx['vout']:
    if o['scriptPubKey'].get('address')=='$2':
        print(o['n'], o['value']); break"
}
read OV OAMT < <(findvout "$OFFER_TXID" "$MAKER_OFFER")
read PV PAMT < <(findvout "$PAY_TXID" "$TAKER")
echo "  offer outpoint $OFFER_TXID:$OV ($OAMT)  pay outpoint $PAY_TXID:$PV ($PAMT)"
JSON=$(python3 -c "import json;print(json.dumps({'offer':{'txid':'$OFFER_TXID','vout':$OV,'amount_btc':$OAMT},'pay':{'txid':'$PAY_TXID','vout':$PV,'amount_btc':$PAMT}}))")

echo "[4] build swap (maker pre-signs SINGLE|ANYONECANPAY; taker completes)"
OUT=$(python3 "$(dirname "$0")/swap_test.py" "$JSON")
rd(){ echo "$OUT"|python3 -c "import sys,json;print(json.load(sys.stdin)['$1'])"; }
TXOK=$(rd tx_ok_hex); TXBAD=$(rd tx_bad_hex); PAYOUT=$(rd maker_payout_addr)

echo "[5] NEGATIVE test (taker shaves maker payout 0.5 -> 0.4): expect allowed=false"
cli testmempoolaccept "[\"$TXBAD\"]" | python3 -c "import sys,json;r=json.load(sys.stdin)[0];print('   allowed=',r['allowed'],'| reason=',r.get('reject-reason'))"
echo "[6] POSITIVE test (honest completion): expect allowed=true"
cli testmempoolaccept "[\"$TXOK\"]" | python3 -c "import sys,json;r=json.load(sys.stdin)[0];print('   allowed=',r['allowed'],'| reason=',r.get('reject-reason'))"
TXID=$(cli sendrawtransaction "$TXOK")
cli -rpcwallet=bank generatetoaddress 1 "$BANK" >/dev/null
echo "[7] SETTLEMENT: single swap txid = $TXID"
echo -n "   maker payout (output0): "; cli gettxout "$TXID" 0 | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['value'],'BTC, confirmations',d['confirmations'])"
echo -n "   offer UTXO after swap:  "; cli gettxout "$OFFER_TXID" "$OV" | python3 -c "import sys,json;d=json.load(sys.stdin);print('STILL UNSPENT (bad)') if d else print('spent')" 2>/dev/null || echo "spent (consumed by swap)"
cli stop >/dev/null 2>&1
echo "DONE_OK"
