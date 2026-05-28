# BTX Phase 5 spike — BTC ↔ rune trade, end-to-end, nothing offchain

**STATUS: PROVEN on regtest, Bitcoin Core v29.1 + ord 0.27.1 (2026-05-26).** A complete, on-chain,
tokenless, issuer-less BTC↔rune trade with validated backing — no ord wallet, nothing offchain.
Reproduced txids: etch/reveal `a8afd8fa…` (rune id `131:1`), swap `d8cf9f49…`.

BTX mints its **own** counter-asset rune with its own primitives (`btx_etch.py`), so it does NOT
use ord's wallet (which fails on Core v29.1: "commit tx recovery key import failed" — Core v29 rejects
importing a watch-only descriptor into a private-keys-enabled wallet, and ord 0.27.1 is the latest).
`ord` is used only as a read-only rune oracle/indexer.

## Assumptions / paths
- `ord` 0.27.1 + `bitcoind`/`bitcoin-cli` v29.1 (`~/bitcoin-29.1/bin`) on PATH; python-bitcoinlib installed.
- Throwaway regtest datadir so nothing touches signet state.

```bash
export PATH="$HOME/bitcoin-29.1/bin:$PATH"
export RT="$HOME/btx-p5-regtest"; mkdir -p "$RT"
CLI="bitcoin-cli -regtest -datadir=$RT"
BTX="/mnt/c/Users/Ren Shu/Documents/Claude/Projects/bitcoin-terminal-exchange"
```

## 1. Regtest node + funded signing wallet
```bash
bitcoind -regtest -datadir="$RT" -txindex=1 -fallbackfee=0.0002 -server -daemon; sleep 3
$CLI createwallet btx 2>/dev/null || $CLI loadwallet btx
ADDR=$($CLI -rpcwallet=btx getnewaddress "" bech32)
$CLI generatetoaddress 101 "$ADDR" >/dev/null
```

## 2. ord index + server (the rune oracle — read-only, no ord wallet needed)
```bash
ord --regtest --bitcoin-data-dir "$RT" --data-dir "$RT/ord" --index-runes \
    server --http-port 8089 >"$RT/ord.log" 2>&1 &
sleep 4; curl -s http://127.0.0.1:8089/status >/dev/null && echo "ord up"
```

## 3. Etch the counter-asset rune with BTX (commit → 6 blocks → reveal)
The premine becomes the offer UTXO directly (reveal output 0 = a wallet P2WPKH holding exactly N units).
Uses an ephemeral key + `sendrawtransaction` — no ord wallet, no `importdescriptors`.
```bash
cd "$BTX"
python3 btx_etch.py etch --rune BTXUSDTESTS --premine 1000 --divisibility 0 --symbol '$' \
  --bitcoin-cli "$(command -v bitcoin-cli)" --chain regtest --datadir "$RT" --wallet btx --broadcast
# note the printed reveal_txid (== offer txid) and offer_outpoint <reveal_txid>:0
```
Confirm ord indexed it (gives the rune id `block:tx`) and the offer UTXO holds exactly the premine:
```bash
sleep 4
curl -s -H "Accept: application/json" "http://127.0.0.1:8089/rune/BTXUSDTESTS"; echo      # -> "id":"<block:tx>"
curl -s -H "Accept: application/json" "http://127.0.0.1:8089/output/<reveal_txid>:0"; echo  # -> runes BTXUSDTESTS:1000
```

## 4. Maker-sign the order, with backing validated by the ord oracle
```bash
python3 btx_wallet.py maker-sign --bitcoin-cli "$(command -v bitcoin-cli)" --chain regtest \
  --datadir "$RT" --wallet btx \
  --offer-txid <reveal_txid> --offer-vout 0 \
  --rune-block <BLOCK> --rune-tx <TX> --amount-units 1000 \
  --price-btc 0.01 --carrier envelope \
  --ord-url http://127.0.0.1:8089 --require-rune-backing
# emits artifact_hex; the oracle confirms the offer holds EXACTLY 1000. Negative test: --amount-units 1001 must REFUSE.
```

## 5. Taker-fill — the settlement that moves the rune to the taker
```bash
ART=<artifact_hex from step 4>
python3 btx_wallet.py taker-fill --bitcoin-cli "$(command -v bitcoin-cli)" --chain regtest \
  --datadir "$RT" --wallet btx --artifact-hex $ART --broadcast      # prints swap txid
$CLI generatetoaddress 1 "$($CLI -rpcwallet=btx getnewaddress)" >/dev/null; sleep 3
```

## 6. Confirm the trade settled correctly (the proof)
```bash
curl -s -H "Accept: application/json" "http://127.0.0.1:8089/output/<swap_txid>:1"; echo  # taker: runes BTXUSDTESTS:1000
curl -s -H "Accept: application/json" "http://127.0.0.1:8089/output/<swap_txid>:0"; echo  # maker: value 1000000, runes {}
$CLI gettxout <reveal_txid> 0                                                              # offer: null (spent)
```
PASS = taker output holds 1000 of the rune, maker output holds the BTC and no rune, offer UTXO spent.

## Teardown
```bash
$CLI stop; pkill -f "http-port 8089"
```

## Honest notes
- **Bitcoin Core is rune-blind** — lock rune UTXOs in any wallet that does coin-selection so it can't
  spend the asset as fee. `maker-sign` locks the offer; `taker-fill` funds from non-rune UTXOs.
- **P2WPKH offer** — BTX `maker-sign`/`verify_maker_sig` is P2WPKH-only; `btx_etch.py` sends the
  premine to a fresh wallet bech32 (P2WPKH) address, so the offer UTXO is already the right type.
- **Exactly-amount** — set `--premine` to the order amount so the offer holds exactly that; the
  maker-side guard enforces it (a remainder would default to the maker on settlement).
- **Rune name** must exceed `ord`'s `minimum_rune_for_next_block` (13+ chars on a fresh regtest).
