#!/bin/bash
export PATH=/tmp/bitcoin-29.1/bin:$PATH
DD=/tmp/rt4; PORT=19333
cli(){ bitcoin-cli -datadir=$DD -rpcport=$PORT -rpcuser=btx -rpcpassword=btx -rpcclienttimeout=8 "$@"; }
echo "[1] start node"
pkill -9 -f -- "-datadir=/tmp/rt" 2>/dev/null; sleep 1
rm -rf $DD; mkdir -p $DD
printf 'regtest=1\nserver=1\ntxindex=1\nfallbackfee=0.0002\nrpcuser=btx\nrpcpassword=btx\n[regtest]\nrpcport=%s\n' "$PORT" > $DD/bitcoin.conf
bitcoind -datadir=$DD -daemon >/dev/null 2>&1
for i in $(seq 1 40); do cli getblockchaininfo >/dev/null 2>&1 && { echo "  up after $i"; break; }; sleep 0.3; done
cli createwallet bank >/dev/null
BANK=$(cli -rpcwallet=bank getnewaddress "" bech32)
cli -rpcwallet=bank generatetoaddress 101 "$BANK" >/dev/null

ADDRS=$(python3 -c "
import hashlib,bitcoin; bitcoin.SelectParams('regtest')
from bitcoin.core import Hash160
from bitcoin.core.script import CScript,OP_0
from bitcoin.wallet import CBitcoinSecret,P2WPKHBitcoinAddress
a=lambda s:str(P2WPKHBitcoinAddress.from_scriptPubKey(CScript([OP_0,Hash160(CBitcoinSecret.from_secret_bytes(hashlib.sha256(s).digest()).pub)])))
print(a(b'btx-maker'),a(b'btx-taker'))")
MO=$(echo $ADDRS|awk '{print $1}'); TK=$(echo $ADDRS|awk '{print $2}')
echo "[2] fund maker-offer(1.0 BTC, carries 1000 RUNE) + taker(0.6 BTC)"
OTX=$(cli -rpcwallet=bank sendtoaddress "$MO" 1.0)
PTX=$(cli -rpcwallet=bank sendtoaddress "$TK" 0.6)
cli -rpcwallet=bank generatetoaddress 1 "$BANK" >/dev/null
fv(){ cli getrawtransaction "$1" true | python3 -c "import sys,json
for o in json.load(sys.stdin)['vout']:
 if o['scriptPubKey'].get('address')=='$2': print(o['n'],o['value']);break"; }
read OV OA < <(fv "$OTX" "$MO"); read PV PA < <(fv "$PTX" "$TK")
JSON=$(python3 -c "import json;print(json.dumps({'offer':{'txid':'$OTX','vout':$OV,'amount_btc':$OA},'pay':{'txid':'$PTX','vout':$PV,'amount_btc':$PA}}))")

echo "[3] build swap WITH runestone edict (rune -> taker output 1)"
B=$(python3 btx_runes.py build "$JSON")
TXH=$(echo "$B"|python3 -c "import sys,json;print(json.load(sys.stdin)['tx_hex'])")
RS=$(echo "$B"|python3 -c "import sys,json;print(json.load(sys.stdin)['runestone_spk_hex'])")
SUP=$(echo "$B"|python3 -c "import sys,json;print(json.load(sys.stdin)['supply'])")
echo "  runestone scriptPubKey: $RS   (6a5d=OP_RETURN OP_13)"

echo "[4] Core consensus check: does the runestone break the partial-signed swap? expect allowed=true"
cli testmempoolaccept "[\"$TXH\"]" | python3 -c "import sys,json;r=json.load(sys.stdin)[0];print('   allowed=',r['allowed'],'| reason=',r.get('reject-reason'))"
TXID=$(cli sendrawtransaction "$TXH")
cli -rpcwallet=bank generatetoaddress 1 "$BANK" >/dev/null
echo "  settled txid=$TXID"

echo "[5] reconstruct rune movement FROM CHAIN via minimal indexer"
RAW=$(cli getrawtransaction "$TXID" true)
python3 btx_runes.py verify "$RAW" "$SUP" | python3 -c "
import sys,json; d=json.load(sys.stdin)
print('   edicts (block,tx,amount,output):',d['edicts'])
print('   RUNE on taker output#1 :',d['rune_on_output_1'])
print('   RUNE on maker payout#0 :',d['rune_on_output_0_maker'])
print('   unallocated            :',d['unallocated'])"
cli stop >/dev/null 2>&1
echo "DONE_OK"
