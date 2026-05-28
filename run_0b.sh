#!/bin/bash
# BTX Milestone 0b — chain-reconstructed order, no relay (single node; taker path uses
# ONLY data read from the chain, never from the maker's process). Run from the Bitcoin Terminal Exchange
# folder in WSL after the run_runes.sh setup (bitcoind in /tmp, python-bitcoinlib installed).
export PATH=/tmp/bitcoin-29.1/bin:$PATH
DD=/tmp/rt0b; PORT=19555
cli(){ bitcoin-cli -datadir=$DD -rpcport=$PORT -rpcuser=btx -rpcpassword=btx -rpcclienttimeout=8 "$@"; }
echo "[1] start node (datacarriersize=240 so the ~200B BTX artifact rides one OP_RETURN)"
pkill -9 -f -- "-datadir=/tmp/rt" 2>/dev/null; sleep 1
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
print(a(b'btx-maker'),a(b'btx-taker'))")
MO=$(echo $ADDRS|awk '{print $1}'); TK=$(echo $ADDRS|awk '{print $2}')
echo "[2] fund maker offer(1.0) + taker pay(0.6)"
OTX=$(cli -rpcwallet=bank sendtoaddress "$MO" 1.0)
PTX=$(cli -rpcwallet=bank sendtoaddress "$TK" 0.6)
cli -rpcwallet=bank generatetoaddress 1 "$BANK" >/dev/null
fv(){ cli getrawtransaction "$1" true | python3 -c "import sys,json
for o in json.load(sys.stdin)['vout']:
 if o['scriptPubKey'].get('address')=='$2': print(o['n'],o['value']);break"; }
read OV OA < <(fv "$OTX" "$MO"); read PV PA < <(fv "$PTX" "$TK")
OFFER_SATS=$(python3 -c "print(int(round($OA*1e8)))")
PAY_SATS=$(python3 -c "print(int(round($PA*1e8)))")
echo "  offer $OTX:$OV ($OA)  pay $PTX:$PV ($PA)"

echo "[3] MAKER: build BTX artifact (carries SINGLE|ANYONECANPAY pre-sig) and publish it on-chain"
BLOB=$(python3 -c "
import btx_0b as c
from bitcoin.core import b2x
art=c.make_artifact('$OTX', $OV, $OFFER_SATS, int(0.5*1e8))
print(b2x(c.serialize_artifact(art)))")
RAW=$(cli -rpcwallet=bank createrawtransaction "[]" "[{\"data\":\"$BLOB\"}]")
FUND=$(cli -rpcwallet=bank fundrawtransaction "$RAW" | python3 -c "import sys,json;print(json.load(sys.stdin)['hex'])")
SIGNED=$(cli -rpcwallet=bank signrawtransactionwithwallet "$FUND" | python3 -c "import sys,json;print(json.load(sys.stdin)['hex'])")
ANN=$(cli sendrawtransaction "$SIGNED")
cli -rpcwallet=bank generatetoaddress 1 "$BANK" >/dev/null
echo "  announce txid=$ANN (offer UTXO still unspent)"

echo "[4] SECOND PARTY: reconstruct order FROM CHAIN ONLY (read announce tx, verify maker sig)"
ANNRAW=$(cli getrawtransaction "$ANN")
python3 -c "
import btx_0b as c
from bitcoin.core import CTransaction, x
tx=CTransaction.deserialize(x('$ANNRAW'))
blob=None
for o in tx.vout:
    spk=bytes(o.scriptPubKey); i=spk.find(b'BTX1')
    if i>=0: blob=spk[i:]; break
assert blob, 'no BTX artifact found on chain'
art=c.parse_artifact(blob)
ok=c.verify_maker_sig(art, $OFFER_SATS)
print('   parsed order: rune', str(art['rune_block'])+':'+str(art['rune_tx']),
      'price', art['price'], 'offer_vout', art['offer_vout'])
print('   maker sig verified from chain data only:', ok)
assert ok"

echo "[5] TAKER: complete the swap built ONLY from the on-chain artifact"
SWAP=$(python3 -c "
import btx_0b as c
from bitcoin.core import CTransaction, x, b2x
tx=CTransaction.deserialize(x('$ANNRAW'))
blob=None
for o in tx.vout:
    spk=bytes(o.scriptPubKey); i=spk.find(b'BTX1')
    if i>=0: blob=spk[i:]; break
art=c.parse_artifact(blob)
swap=c.build_swap_from_artifact(art, $OFFER_SATS, ('$PTX', $PV), $PAY_SATS, b'btx-taker')
print(b2x(swap.serialize()))")
echo -n "   testmempoolaccept: "; cli testmempoolaccept "[\"$SWAP\"]" | python3 -c "import sys,json;r=json.load(sys.stdin)[0];print('allowed=',r['allowed'],'reason=',r.get('reject-reason'))"
SWAPID=$(cli sendrawtransaction "$SWAP")
cli -rpcwallet=bank generatetoaddress 1 "$BANK" >/dev/null
echo "[6] SETTLEMENT: swap txid=$SWAPID"
echo -n "   maker payout (output0): "; cli gettxout "$SWAPID" 0 | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['value'],'BTC, conf',d['confirmations'])"
if [ -n "$(cli gettxout "$OTX" "$OV" 2>/dev/null)" ]; then echo "   offer UTXO after swap : STILL UNSPENT (bad)"; else echo "   offer UTXO after swap : spent (consumed)"; fi
cli stop >/dev/null 2>&1
echo "DONE_0B"
