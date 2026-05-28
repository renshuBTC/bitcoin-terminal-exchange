#!/bin/bash
# BTX Milestone 0b (STRICT) — two bitcoind nodes connected ONLY by P2P, no shared datadir,
# no messaging channel. Maker publishes the order on node A; the taker reconstructs + verifies +
# completes it on node B, which received the announce tx solely via block propagation.
export PATH=/tmp/bitcoin-29.1/bin:$PATH
DA=/tmp/rt0bA; DB=/tmp/rt0bB
RA=19812; RB=19822      # rpc ports
PA=19811; PB=19821      # p2p ports
cliA(){ bitcoin-cli -datadir=$DA -rpcport=$RA -rpcuser=btx -rpcpassword=btx -rpcclienttimeout=8 "$@"; }
cliB(){ bitcoin-cli -datadir=$DB -rpcport=$RB -rpcuser=btx -rpcpassword=btx -rpcclienttimeout=8 "$@"; }
conf(){ printf 'regtest=1\nserver=1\ntxindex=1\nfallbackfee=0.0002\ndatacarriersize=240\nrpcuser=btx\nrpcpassword=btx\n'; }

echo "[1] start two nodes (B connects to A by P2P only)"
pkill -9 -f -- "-datadir=/tmp/rt" 2>/dev/null; sleep 2
rm -rf $DA $DB; mkdir -p $DA $DB
conf > $DA/bitcoin.conf
conf > $DB/bitcoin.conf
bitcoind -datadir=$DA -daemon -rpcport=$RA -port=$PA -bind=127.0.0.1:$PA >/dev/null 2>&1
bitcoind -datadir=$DB -daemon -rpcport=$RB -port=$PB -bind=127.0.0.1:$PB -connect=127.0.0.1:$PA >/dev/null 2>&1
for i in $(seq 1 40); do cliA getblockchaininfo >/dev/null 2>&1 && cliB getblockchaininfo >/dev/null 2>&1 && { echo "  both up after $i"; break; }; sleep 0.3; done
for i in $(seq 1 40); do [ "$(cliB getconnectioncount)" -ge 1 ] && { echo "  B<->A peer connected"; break; }; sleep 0.3; done

cliA createwallet bank >/dev/null
BANK=$(cliA -rpcwallet=bank getnewaddress "" bech32)
cliA -rpcwallet=bank generatetoaddress 101 "$BANK" >/dev/null

ADDRS=$(python3 -c "
import hashlib,bitcoin; bitcoin.SelectParams('regtest')
from bitcoin.core import Hash160
from bitcoin.core.script import CScript,OP_0
from bitcoin.wallet import CBitcoinSecret,P2WPKHBitcoinAddress
a=lambda s:str(P2WPKHBitcoinAddress.from_scriptPubKey(CScript([OP_0,Hash160(CBitcoinSecret.from_secret_bytes(hashlib.sha256(s).digest()).pub)])))
print(a(b'btx-maker'),a(b'btx-taker'))")
MO=$(echo $ADDRS|awk '{print $1}'); TK=$(echo $ADDRS|awk '{print $2}')

echo "[2] node A: fund maker offer(1.0) + taker pay(0.6); mine so they confirm"
OTX=$(cliA -rpcwallet=bank sendtoaddress "$MO" 1.0)
PTX=$(cliA -rpcwallet=bank sendtoaddress "$TK" 0.6)
cliA -rpcwallet=bank generatetoaddress 1 "$BANK" >/dev/null
fvA(){ cliA getrawtransaction "$1" true | python3 -c "import sys,json
for o in json.load(sys.stdin)['vout']:
 if o['scriptPubKey'].get('address')=='$2': print(o['n'],o['value']);break"; }
read OV OA < <(fvA "$OTX" "$MO"); read PV PA < <(fvA "$PTX" "$TK")
OFFER_SATS=$(python3 -c "print(int(round($OA*1e8)))"); PAY_SATS=$(python3 -c "print(int(round($PA*1e8)))")

echo "[3] node A: publish BTX artifact on-chain, mine the block"
BLOB=$(python3 -c "import btx_0b as c
from bitcoin.core import b2x
print(b2x(c.serialize_artifact(c.make_artifact('$OTX', $OV, $OFFER_SATS, int(0.5*1e8)))))")
RAW=$(cliA -rpcwallet=bank createrawtransaction "[]" "[{\"data\":\"$BLOB\"}]")
FUND=$(cliA -rpcwallet=bank fundrawtransaction "$RAW" | python3 -c "import sys,json;print(json.load(sys.stdin)['hex'])")
SIGNED=$(cliA -rpcwallet=bank signrawtransactionwithwallet "$FUND" | python3 -c "import sys,json;print(json.load(sys.stdin)['hex'])")
ANN=$(cliA sendrawtransaction "$SIGNED")
cliA -rpcwallet=bank generatetoaddress 1 "$BANK" >/dev/null
HEIGHT=$(cliA getblockcount)
echo "  announce txid=$ANN at A height $HEIGHT"

echo "[4] wait for node B to receive the block via P2P (no shared files)"
for i in $(seq 1 60); do [ "$(cliB getblockcount)" = "$HEIGHT" ] && { echo "  B synced to height $HEIGHT"; break; }; sleep 0.3; done

echo "[5] node B ONLY: reconstruct order from B's chain + verify maker sig from chain data"
ANNRAW=$(cliB getrawtransaction "$ANN")   # B has it only because the block propagated
python3 -c "
import btx_0b as c
from bitcoin.core import CTransaction, x
tx=CTransaction.deserialize(x('$ANNRAW'))
blob=None
for o in tx.vout:
    spk=bytes(o.scriptPubKey); i=spk.find(b'BTX1')
    if i>=0: blob=spk[i:]; break
assert blob, 'no BTX artifact in block B received'
art=c.parse_artifact(blob)
print('   B parsed order from P2P-delivered block: price', art['price'], 'offer_vout', art['offer_vout'])
print('   B verified maker sig from chain data only:', c.verify_maker_sig(art, $OFFER_SATS))"

echo "[6] node B: build + broadcast the swap from the on-chain artifact"
SWAP=$(python3 -c "
import btx_0b as c
from bitcoin.core import CTransaction, x, b2x
tx=CTransaction.deserialize(x('$ANNRAW'))
blob=None
for o in tx.vout:
    spk=bytes(o.scriptPubKey); i=spk.find(b'BTX1')
    if i>=0: blob=spk[i:]; break
art=c.parse_artifact(blob)
print(b2x(c.build_swap_from_artifact(art, $OFFER_SATS, ('$PTX', $PV), $PAY_SATS, b'btx-taker').serialize()))")
echo -n "   B testmempoolaccept: "; cliB testmempoolaccept "[\"$SWAP\"]" | python3 -c "import sys,json;r=json.load(sys.stdin)[0];print('allowed=',r['allowed'],'reason=',r.get('reject-reason'))"
SWAPID=$(cliB sendrawtransaction "$SWAP")
echo "   B broadcast swap txid=$SWAPID"

echo "[7] swap propagates B->A; A mines; both confirm"
for i in $(seq 1 40); do cliA getrawmempool | grep -q "$SWAPID" && { echo "  A saw swap in mempool"; break; }; sleep 0.3; done
cliA -rpcwallet=bank generatetoaddress 1 "$BANK" >/dev/null
H2=$(cliA getblockcount)
for i in $(seq 1 60); do [ "$(cliB getblockcount)" = "$H2" ] && break; sleep 0.3; done

echo "[8] settlement, checked on node B"
echo -n "   maker payout (output0) on B: "; cliB gettxout "$SWAPID" 0 | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['value'],'BTC, conf',d['confirmations'])"
if [ -n "$(cliB gettxout "$OTX" "$OV" 2>/dev/null)" ]; then echo "   offer UTXO on B: STILL UNSPENT (bad)"; else echo "   offer UTXO on B: spent (consumed)"; fi
cliA stop >/dev/null 2>&1; cliB stop >/dev/null 2>&1
echo "DONE_0B_TWONODE"
