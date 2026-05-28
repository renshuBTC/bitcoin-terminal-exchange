#!/bin/bash
# BTX double-take race: two takers each build a VALID swap spending the SAME offer UTXO.
# Both are individually acceptable; once one is in the mempool the other is a double-spend.
# Proves the "first valid spender wins / no price-time priority" property (brief constraint #3).
export PATH=/tmp/bitcoin-29.1/bin:$PATH
DD=/tmp/rtdt; PORT=19666
cli(){ bitcoin-cli -datadir=$DD -rpcport=$PORT -rpcuser=btx -rpcpassword=btx -rpcclienttimeout=8 "$@"; }
echo "[1] start node"
pkill -9 -f -- "-datadir=/tmp/rt" 2>/dev/null; sleep 2
rm -rf $DD; mkdir -p $DD
printf 'regtest=1\nserver=1\ntxindex=1\nfallbackfee=0.0002\ndatacarriersize=240\nrpcuser=btx\nrpcpassword=btx\n[regtest]\nrpcport=%s\n' "$PORT" > $DD/bitcoin.conf
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
print(a(b'btx-maker'),a(b'btx-taker'),a(b'btx-taker2'))")
MO=$(echo $ADDRS|awk '{print $1}'); TK1=$(echo $ADDRS|awk '{print $2}'); TK2=$(echo $ADDRS|awk '{print $3}')
echo "[2] fund maker offer(1.0) + taker1 pay(0.6) + taker2 pay(0.6)"
OTX=$(cli -rpcwallet=bank sendtoaddress "$MO" 1.0)
P1=$(cli -rpcwallet=bank sendtoaddress "$TK1" 0.6)
P2=$(cli -rpcwallet=bank sendtoaddress "$TK2" 0.6)
cli -rpcwallet=bank generatetoaddress 1 "$BANK" >/dev/null
fv(){ cli getrawtransaction "$1" true | python3 -c "import sys,json
for o in json.load(sys.stdin)['vout']:
 if o['scriptPubKey'].get('address')=='$2': print(o['n'],o['value']);break"; }
read OV OA < <(fv "$OTX" "$MO"); read V1 A1 < <(fv "$P1" "$TK1"); read V2 A2 < <(fv "$P2" "$TK2")
OFFER_SATS=$(python3 -c "print(int(round($OA*1e8)))"); A1S=$(python3 -c "print(int(round($A1*1e8)))"); A2S=$(python3 -c "print(int(round($A2*1e8)))")

echo "[3] both takers build a swap from the SAME offer UTXO ($OTX:$OV)"
mkswap(){ # $1=seed $2=payTxid $3=payVout $4=paySats
python3 -c "
import btx_0b as c
from bitcoin.core import b2x
art=c.make_artifact('$OTX', $OV, $OFFER_SATS, int(0.5*1e8))
art=c.parse_artifact(c.serialize_artifact(art))
print(b2x(c.build_swap_from_artifact(art, $OFFER_SATS, ('$2', $3), $4, b'$1').serialize()))"; }
SWAP1=$(mkswap btx-taker  "$P1" "$V1" "$A1S")
SWAP2=$(mkswap btx-taker2 "$P2" "$V2" "$A2S")

echo "[4] each swap is individually valid (tested against an empty mempool):"
echo -n "   taker1: "; cli testmempoolaccept "[\"$SWAP1\"]" | python3 -c "import sys,json;r=json.load(sys.stdin)[0];print('allowed=',r['allowed'])"
echo -n "   taker2: "; cli testmempoolaccept "[\"$SWAP2\"]" | python3 -c "import sys,json;r=json.load(sys.stdin)[0];print('allowed=',r['allowed'])"

echo "[5] race: broadcast taker1, then taker2 (which now double-spends the offer UTXO)"
ID1=$(cli sendrawtransaction "$SWAP1"); echo "   taker1 broadcast OK: $ID1"
echo -n "   taker2 broadcast: "; cli sendrawtransaction "$SWAP2" 2>&1 | head -1

echo "[6] mine; exactly one confirms"
cli -rpcwallet=bank generatetoaddress 1 "$BANK" >/dev/null
C1=$(cli getrawtransaction "$ID1" true 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('confirmations',0))" 2>/dev/null || echo 0)
echo "   taker1 ($ID1) confirmations: $C1"
if [ -n "$(cli gettxout "$OTX" "$OV" 2>/dev/null)" ]; then echo "   offer UTXO: STILL UNSPENT (bad)"; else echo "   offer UTXO: spent exactly once (race resolved)"; fi
cli stop >/dev/null 2>&1
echo "DONE_DOUBLETAKE"
