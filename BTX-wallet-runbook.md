# BTX wallet runbook — on-node confirmation (WSL, regtest)

`btx_wallet.py` replaces the deterministic prototype seeds with **real Bitcoin Core wallet keys**.
The offline `simulate` already proved the new plumbing (witness lift / artifact assembly / witness
transplant). This runbook covers the one thing the offline sim cannot: that Bitcoin Core's own
wallet produces a `SINGLE|ANYONECANPAY` signature that verifies under `btx_0b.verify_maker_sig`,
and that the assembled swap is **accepted by consensus** and settles in one txid.

Run everything in WSL. All commands are scoped to a throwaway regtest datadir so they **cannot touch
your real node/wallet**. Kill only that datadir's daemon (never a blanket `pkill bitcoind`).

## 0. Prereqs
```bash
cd ~/path/to/Bitcoin\ BTX           # where the btx_*.py live
pip install python-bitcoinlib --break-system-packages   # if not already
RT=/tmp/rt-wallet                      # throwaway datadir
BCLI="bitcoin-cli -chain=regtest -datadir=$RT"
```

## 1. Start a throwaway regtest node
The BTX v2 artifact is ~208 bytes, so the OP_RETURN carrier needs a relaxed datacarrier limit.
(Alternatively use the Taproot envelope carrier — see step 6b — which has no such limit.)
```bash
mkdir -p $RT
bitcoind -chain=regtest -datadir=$RT -fallbackfee=0.0002 \
         -datacarrier=1 -datacarriersize=240 -daemon
sleep 2
$BCLI createwallet btx            # maker+taker share one wallet here for simplicity
MINER=$($BCLI getnewaddress "" bech32)
$BCLI generatetoaddress 101 "$MINER"   # mature coinbase
```

## 2. Fund a P2WPKH offer UTXO
The offer **must** be P2WPKH (bech32) — the maker sig verifies only for a P2WPKH offer whose witness
pubkey is the signing key.
```bash
OFFER_ADDR=$($BCLI getnewaddress "" bech32)
OFFER_TXID=$($BCLI sendtoaddress "$OFFER_ADDR" 1.0)
$BCLI generatetoaddress 1 "$MINER"
# find the vout that paid OFFER_ADDR (its scriptPubKey starts 0014)
$BCLI gettxout "$OFFER_TXID" 0     # inspect; note which vout is 1.0 BTC to OFFER_ADDR
OFFER_VOUT=0                        # set to the correct index from the output above
```

## 3. Maker signs the offer → BTX artifact
```bash
python3 btx_wallet.py maker-sign \
  --datadir $RT --wallet btx \
  --offer-txid "$OFFER_TXID" --offer-vout $OFFER_VOUT \
  --price-btc 0.5 --amount-units 1000 --group-id 0
```
Expect JSON with `"maker_sig_self_verifies": true`. **This is the key on-node assertion**: a
wallet-produced sig verifies under the same code Milestone 0b proved. Copy `artifact_hex` and
`carrier_op_return_spk_hex`.

## 4. Publish the order on-chain (OP_RETURN carrier)
Fund a tx that carries the artifact in an OP_RETURN, using the wallet:
```bash
ART=<artifact_hex from step 3>
RAW=$($BCLI createrawtransaction '[]' "[{\"data\":\"$ART\"}]")
FUNDED=$($BCLI fundrawtransaction "$RAW" | python3 -c "import sys,json;print(json.load(sys.stdin)['hex'])")
SIGNED=$($BCLI signrawtransactionwithwallet "$FUNDED" | python3 -c "import sys,json;print(json.load(sys.stdin)['hex'])")
ANNOUNCE_TXID=$($BCLI sendrawtransaction "$SIGNED")
$BCLI generatetoaddress 1 "$MINER"
echo "announce txid: $ANNOUNCE_TXID"
```

## 5. Taker discovers + fills
A second party would run `btx book scan` over the blocks; here, fill directly from the artifact.
The tool re-verifies the maker sig from the on-chain offer amount before building anything.
```bash
python3 btx_wallet.py taker-fill \
  --datadir $RT --wallet btx \
  --artifact-hex "$ART" --broadcast
$BCLI generatetoaddress 1 "$MINER"
```
Expect JSON with a `txid`. That single txid IS the settlement.

## 6. Confirm settlement
```bash
SWAP_TXID=<txid from step 5>
$BCLI gettransaction "$SWAP_TXID"            # confirmations >= 1
$BCLI gettxout "$OFFER_TXID" $OFFER_VOUT     # should be NULL — offer UTXO consumed
# output 0 of the swap pays exactly 0.5 BTC to the maker payout_addr from step 3
$BCLI getrawtransaction "$SWAP_TXID" true | python3 -c "import sys,json; d=json.load(sys.stdin); print('out0', d['vout'][0]['value'], d['vout'][0]['scriptPubKey'].get('address'))"
```
Success = swap confirmed in one txid, offer UTXO spent, output 0 == 0.5 BTC to the maker payout.

### 6b. (Optional) Taproot envelope carrier instead of OP_RETURN
Re-run step 3 with `--carrier envelope` to also emit `envelope_tapscript_hex` + `envelope_tapleaf_hex`.
Publishing that requires a commit/reveal: derive the P2TR output key from your internal key + the
tapleaf (BIP341 tweak), send to the commit address, then spend it revealing the tapscript in the
witness. This needs wallet Taproot support (descriptor `tr(...)`); it removes the `-datacarriersize`
requirement entirely. Marked `[VERIFY]` until run end-to-end.

## 7. Cross-check with the reconstructor (optional)
```bash
ANN_HEX=$($BCLI getrawtransaction "$ANNOUNCE_TXID")
SWAP_HEX=$($BCLI getrawtransaction "$SWAP_TXID")
python3 btx.py book scan --txs "[\"$ANN_HEX\",\"$SWAP_HEX\"]"
# expect: 1 order, status FILLED, is_fill true
```

## 8. Cleanup
```bash
bitcoin-cli -chain=regtest -datadir=$RT stop
sleep 2
pkill -9 -f -- "-datadir=$RT" 2>/dev/null   # scoped: only THIS regtest daemon
rm -rf $RT
```

## What this proves vs. what it assumes
- **Proves on-node:** Core's wallet `SINGLE|ANYONECANPAY` sig verifies under BTX's verifier; the
  assembled swap is consensus-valid; one-txid settlement; offer UTXO consumed; payout exact.
- **Still assumes:** `-datacarriersize=240` for the OP_RETURN carrier (or the envelope path in 6b).
  This is the standardness `[VERIFY]` flagged in `BTX-phase0-STATUS.md`.
