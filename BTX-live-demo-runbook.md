# BTX live demo — node → publish → BRK serves → discover → fill (WSL, regtest)

The full loop end-to-end on a throwaway regtest: a maker publishes an order on-chain, your BRK fork
indexes + serves it at `/api/v1/btx/orders`, and a taker discovers and fills it — all with no relay
and no off-chain state. This is the one integration the offline unit tests can't cover.

Everything is scoped to a throwaway datadir so it **cannot touch your real node/wallet**. Use three
terminals (A = bitcoind + maker, B = BRK, C = taker/queries). Paths assume the repos at
`/mnt/c/Users/Ren Shu/Documents/Claude/Projects/{Bitcoin Terminal Exchange,brk}`.

## Shared vars (run in each terminal)
```bash
RT=/tmp/rt-btx                       # throwaway bitcoind datadir
BRKDIR=/tmp/brk-btx                  # throwaway BRK output dir
BTX="/mnt/c/Users/Ren Shu/Documents/Claude/Projects/Bitcoin Terminal Exchange"
BRK="/mnt/c/Users/Ren Shu/Documents/Claude/Projects/brk"
BCLI="bitcoin-cli -chain=regtest -datadir=$RT"
```

## Terminal A — node + publish a maker order
```bash
# 1. start regtest with a relaxed datacarrier (the ~207B BTX artifact needs >80B OP_RETURN)
mkdir -p $RT
bitcoind -chain=regtest -datadir=$RT -fallbackfee=0.0002 \
         -datacarrier=1 -datacarriersize=240 -server -daemon
sleep 2
$BCLI createwallet btx
MINER=$($BCLI getnewaddress "" bech32)
$BCLI generatetoaddress 101 "$MINER"

# 2. fund a P2WPKH offer UTXO (must be bech32)
OFFER_ADDR=$($BCLI getnewaddress "" bech32)
OFFER_TXID=$($BCLI sendtoaddress "$OFFER_ADDR" 1.0)
$BCLI generatetoaddress 1 "$MINER"
OFFER_VOUT=$($BCLI getrawtransaction "$OFFER_TXID" true \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(next(o['n'] for o in d['vout'] if o['scriptPubKey'].get('address')=='$OFFER_ADDR'))")
echo "offer = $OFFER_TXID:$OFFER_VOUT"

# 3. maker signs the order with the WALLET (real SINGLE|ANYONECANPAY pre-sig)
cd "$BTX"
ART=$(python3 btx_wallet.py maker-sign --datadir $RT --wallet btx \
        --offer-txid "$OFFER_TXID" --offer-vout $OFFER_VOUT --price-btc 0.5 \
      | python3 -c "import sys,json;print(json.load(sys.stdin)['artifact_hex'])")
echo "artifact = $ART"   # expect maker_sig_self_verifies:true in the full JSON

# 4. publish the order on-chain via an OP_RETURN carrier
RAW=$($BCLI createrawtransaction '[]' "[{\"data\":\"$ART\"}]")
FUNDED=$($BCLI fundrawtransaction "$RAW" | python3 -c "import sys,json;print(json.load(sys.stdin)['hex'])")
SIGNED=$($BCLI signrawtransactionwithwallet "$FUNDED" | python3 -c "import sys,json;print(json.load(sys.stdin)['hex'])")
ANNOUNCE=$($BCLI sendrawtransaction "$SIGNED")
$BCLI generatetoaddress 1 "$MINER"
echo "announce txid = $ANNOUNCE"
```

## Terminal B — run BRK against the regtest chain (indexer + server)
```bash
cd "$BRK"
# BRK_BLOCK_MAGIC=fabfb5da makes brk_reader parse REGTEST blk files (mainnet magic is the default).
# blocksdir + cookie + rpcport point at the regtest datadir; server on :3110.
BRK_BLOCK_MAGIC=fabfb5da cargo run -p brk_cli -- \
  --brkdir $BRKDIR \
  --blocksdir $RT/regtest/blocks \
  --rpcconnect 127.0.0.1 --rpcport 18443 \
  --rpccookiefile $RT/regtest/.cookie \
  --brkport 3110
# leave this running; it indexes the regtest blocks (incl. the btx_orders store) and serves the API.
# Wait for the log line indicating it has indexed up to the tip before querying in Terminal C.
```

## Terminal C — discover + fill off the served book
```bash
cd "$BTX"
# 5. discover: the served, chain-reconstructed open book
curl -s http://127.0.0.1:3110/api/v1/btx/orders | python3 -m json.tool
python3 btx.py client orders --api-base http://127.0.0.1:3110     # same data, table form

# 6. fill in one step: fetch the order's artifact by outpoint from BRK and build the swap
#    (PROTOTYPE taker key path; for real keys use btx_wallet.py taker-fill)
python3 btx.py swap build --from-api --api-base http://127.0.0.1:3110 \
  --offer "$OFFER_TXID:$OFFER_VOUT" --offer-amount-btc 1.0 \
  --pay-txid <a-funding-utxo-txid> --pay-vout <n> --pay-amount-btc 0.6

# 6b. OR fill with real wallet keys + broadcast (auto-picks a funding UTXO, transplants maker sig):
python3 btx_wallet.py taker-fill --datadir $RT --wallet btx \
  --artifact-hex "$ART" --broadcast
$BCLI generatetoaddress 1 "$MINER"
```

## Confirm settlement
```bash
SWAP=<txid from step 6b>
$BCLI gettxout "$OFFER_TXID" $OFFER_VOUT     # NULL -> offer UTXO consumed
$BCLI getrawtransaction "$SWAP" true | python3 -c "import sys,json;d=json.load(sys.stdin);print('out0',d['vout'][0]['value'],'BTC ->',d['vout'][0]['scriptPubKey'].get('address'))"
# after BRK indexes the swap block, the order flips out of /orders (FILLED):
curl -s http://127.0.0.1:3110/api/v1/btx/orders | python3 -m json.tool
```

## Cleanup
```bash
# Terminal B: Ctrl-C the BRK process
bitcoin-cli -chain=regtest -datadir=$RT stop; sleep 2
pkill -9 -f -- "-datadir=$RT" 2>/dev/null   # scoped to THIS regtest daemon only
rm -rf $RT $BRKDIR
```

## If something doesn't line up
- **`/api/v1/btx/orders` is empty** after the announce confirms: BRK probably hasn't indexed the
  announce block yet — watch Terminal B's log for the indexed height to reach the tip, then re-query.
- **BRK indexes 0 blocks / `INDEXED_HEIGHT 0`**: the `BRK_BLOCK_MAGIC=fabfb5da` env wasn't picked up
  (mainnet magic `f9beb4d9` won't match regtest blk files). It must be set in Terminal B's shell.
- **`maker_sig_self_verifies` is false** in step 3: the offer UTXO isn't P2WPKH — fund the offer to a
  `getnewaddress "" bech32` address (step 2), not legacy/taproot.
- **carrier tx rejected (`scriptpubkey` / `datacarrier`)**: bitcoind wasn't started with
  `-datacarriersize=240` (step 1), or use the Taproot envelope carrier instead.
- BRK on regtest is non-standard (it's built for mainnet). If the indexer/computer start trips, that's
  the integration edge to iterate on — capture the Terminal B log and we'll work it.
