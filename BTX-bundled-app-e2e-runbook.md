# BTX bundled-app E2E runbook — etch → publish → book → fill (regtest, GUI-verified)

A reproducible walk through the **full BTX trade rail** as it runs inside the bundled Windows app
(v0.2.10+). You launch `btx-app.exe`, the daemon stack spins up inside WSL, you etch a regtest rune,
maker-sign + publish an order, and watch it appear on the BTX **Book** page; then you fill it from
WSL and see the atomic swap on the **Trades** page. No relay, no off-chain state, no third-party
indexer.

This is the GUI-verified counterpart to `BTX-live-demo-runbook.md` (which exercises the same
primitives via standalone bitcoind without the bundled app). Use this runbook when you want to
prove the bundled app itself works end-to-end on a throwaway chain.

## What you'll see at the end

| Page | Final state |
|---|---|
| **Trade** | `ORDER BOOK: book e3b0c44298… · 0 orders · indexer agreed`, STREAM HASH advanced |
| **Book** | 0 OPEN ORDERS, 1 RECENT FILL (filled, h*N*), 1 ATOMIC SWAP (`<swap_txid>` h*N*) |
| **Trades** | 1 trade leg: rune 109:1, amount 1,000,000,000, paid 0.001 BTC |

## Prerequisites

- Windows 10/11 with WSL2 + a Linux distro (Ubuntu tested)
- BTX installed (`%LOCALAPPDATA%\BTX\btx-app.exe`) — build from this repo via `app\rebuild.ps1`
- A PowerShell window and a WSL bash window open side-by-side
- ~2GB free disk for the regtest blocks + ord index

The bundle ships its own `bitcoind`, `brk_cli`, `ord`, and `btxd` — nothing to install separately.

## Step 1 — Launch BTX on regtest

The bundle defaults to signet on first launch (via the setup wizard). Either complete the wizard
choosing **regtest**, or edit `~/.btx/setup.json` directly:

```bash
# In WSL — first-launch wizard alternative
cat > ~/.btx/setup.json <<EOF
{"chain":"regtest","wallet":"btx","datadir_override":null}
EOF
```

Then from PowerShell:

```powershell
Start-Process -FilePath "$env:LOCALAPPDATA\BTX\btx-app.exe"
```

The window shows the orange "BTX — BITCOIN ONCHAIN EXCHANGE" loading screen for ~30s while the
supervisor brings up bitcoind → brk_cli → ord → btxd. When the trade page loads, you should see
`ORACLE ON · SYNC 100.0% · CONNECT` chips, all green.

## Step 2 — Mine some blocks so brk_cli has work to do

brk_cli refuses to start on a 1-block (genesis-only) regtest. Mine 101 first:

```bash
# In WSL
ADDR=$(~/.btx/bin/bitcoin-cli -regtest -datadir=$HOME/.btx/data/regtest -rpcwallet=btx getnewaddress)
~/.btx/bin/bitcoin-cli -regtest -datadir=$HOME/.btx/data/regtest generatetoaddress 101 "$ADDR" \
  > /dev/null
~/.btx/bin/bitcoin-cli -regtest -datadir=$HOME/.btx/data/regtest getblockcount
```

Click **WALLET** in the BTX nav. You should see **BTC BALANCE 50.00000000 BTC**, IMMATURE
~5000 BTC, and 1 spendable UTXO. (Regtest coinbase reward is 50 BTC, mature after 100
confirmations.)

## Step 3 — Etch a rune

Need a 17-character name to pass the regtest minimum-rune-number threshold at these low heights:

```bash
python3 ~/.btx/app/btx_etch.py etch \
  --bitcoin-cli ~/.btx/bin/bitcoin-cli \
  --chain regtest \
  --datadir ~/.btx/data/regtest \
  --wallet btx \
  --rune BTXUSDONREGTESTAA \
  --premine 1000000000 \
  --divisibility 0 \
  --symbol '$' \
  --ord-url http://127.0.0.1:3349 \
  --broadcast \
  | tee /tmp/etch.json
```

The script does commit → 6-block mine → reveal in one shot. Grab the premine UTXO from the output:

```bash
OFFER_TXID=$(python3 -c "import json; print(json.load(open('/tmp/etch.json'))['reveal_txid'])")
OFFER_VOUT=0
OFFER_SATS=98000
echo "offer: $OFFER_TXID:$OFFER_VOUT ($OFFER_SATS sats)"
```

## Step 4 — Maker-sign

The btx_wallet.py `maker-sign` command produces a SIGHASH_SINGLE|ANYONECANPAY signature over a
spend of the rune UTXO. The artifact embeds the signature + the asked price + the offered amount.

ord's regtest indexer can wedge (see `reference-wsl-subshell` memory); v0.2.10's auto-detector
restarts it but if you hit it during this step, just skip `--ord-url` and accept the warning —
maker-sign doesn't strictly require ord:

```bash
python3 ~/.btx/app/btx_wallet.py maker-sign \
  --bitcoin-cli ~/.btx/bin/bitcoin-cli \
  --chain regtest \
  --datadir ~/.btx/data/regtest \
  --wallet btx \
  --offer-txid "$OFFER_TXID" \
  --offer-vout "$OFFER_VOUT" \
  --offer-amount-sats "$OFFER_SATS" \
  --price-btc 0.001 \
  --amount-units 1000000000 \
  --rune-block 109 --rune-tx 1 \
  --carrier op_return \
  | tee /tmp/maker.json
```

Verify `maker_sig_self_verifies: true` and `offer_locked: true` in the JSON.

## Step 5 — Publish via OP_RETURN carrier tx

Embed the artifact in a transaction's OP_RETURN, fund it, sign it, broadcast it:

```bash
ART=$(python3 -c "import json; print(json.load(open('/tmp/maker.json'))['artifact_hex'])")

RAW=$(~/.btx/bin/bitcoin-cli -regtest -datadir=$HOME/.btx/data/regtest -rpcwallet=btx \
       createrawtransaction '[]' "[{\"data\":\"$ART\"}]")
FUNDED=$(~/.btx/bin/bitcoin-cli -regtest -datadir=$HOME/.btx/data/regtest -rpcwallet=btx \
          fundrawtransaction "$RAW" | python3 -c 'import json,sys; print(json.load(sys.stdin)["hex"])')
SIGNED=$(~/.btx/bin/bitcoin-cli -regtest -datadir=$HOME/.btx/data/regtest -rpcwallet=btx \
          signrawtransactionwithwallet "$FUNDED" | python3 -c 'import json,sys; print(json.load(sys.stdin)["hex"])')
PUBLISH_TXID=$(~/.btx/bin/bitcoin-cli -regtest -datadir=$HOME/.btx/data/regtest -rpcwallet=btx \
                sendrawtransaction "$SIGNED")
echo "publish_txid: $PUBLISH_TXID"

# Confirm
ADDR=$(~/.btx/bin/bitcoin-cli -regtest -datadir=$HOME/.btx/data/regtest -rpcwallet=btx getnewaddress)
~/.btx/bin/bitcoin-cli -regtest -datadir=$HOME/.btx/data/regtest generatetoaddress 1 "$ADDR" > /dev/null
```

## Step 6 — Verify the order on the Book page

Click **BOOK** in the BTX nav. You should see:

- `1 OPEN ORDERS`, `1,000,000,000 ASSET UNITS OFFERED`
- A row with offer outpoint `<OFFER_TXID prefix>…:0`, rune `109:1`, amount `1,000,000,000`,
  price `0.001 BTC`, announce height `N`

The Trade page header should also show `ORDER BOOK: book <hash> · 1 orders · indexer agreed ·
✓ order verified in root`. Both **indexer agreement** (brk_cli + btxd compute the same book hash)
and **light-client root verification** badges should be green.

## Step 7 — Fill the order

```bash
python3 ~/.btx/app/btx_wallet.py taker-fill \
  --bitcoin-cli ~/.btx/bin/bitcoin-cli \
  --chain regtest \
  --datadir ~/.btx/data/regtest \
  --wallet btx \
  --artifact-hex "$ART" \
  --offer-amount-sats "$OFFER_SATS" \
  2>&1 | tee /tmp/taker.json

# Extract the final tx hex (skip the # WARNING preamble)
SWAP_HEX=$(python3 -c "
import json
with open('/tmp/taker.json') as f:
    s = f.read()
print(json.loads(s[s.index('{'):])['final_tx_hex'])
")

# Broadcast + confirm
SWAP_TXID=$(~/.btx/bin/bitcoin-cli -regtest -datadir=$HOME/.btx/data/regtest -rpcwallet=btx \
             sendrawtransaction "$SWAP_HEX")
echo "swap_txid: $SWAP_TXID"
ADDR=$(~/.btx/bin/bitcoin-cli -regtest -datadir=$HOME/.btx/data/regtest -rpcwallet=btx getnewaddress)
~/.btx/bin/bitcoin-cli -regtest -datadir=$HOME/.btx/data/regtest generatetoaddress 1 "$ADDR" > /dev/null
```

## Step 8 — Verify the swap on the Trades page

Click **TRADES** in the BTX nav. Expect 1 trade leg:

- txid `<SWAP_TXID prefix>…`
- rune `109:1`
- amount `1,000,000,000`
- paid `0.00100000` BTC
- seller spk_hex matches the `payout_addr` from step 4
- buyer spk_hex matches a fresh address from your wallet

The **Book** page now shows `0 OPEN ORDERS`, `1 RECENT FILL` (status `filled`), and
`1 ATOMIC SWAP` (the swap txid, asset `rune`). The **Trade** page shows the book hash back to the
empty-book sentinel `e3b0c44298…` and STREAM HASH advanced to include the announce + fill events.

## Mental model of what just happened

```
etch rune (109:1)                            ← step 3, block ~109
  → maker-sign offer (P2WPKH UTXO,           ← step 4, no chain write
    1B units for 0.001 BTC)
  → publish OP_RETURN carrier tx              ← step 5, block ~224
  → brk_cli + btxd reconstruct order,
    agree on book_hash                         ← step 6, visible in BOOK
  → BTX Book page renders the order
  → taker-fill builds swap                     ← step 7
    (transplants maker witness)
  → broadcast atomic SIGHASH_SINGLE|ACP swap   ← block ~226
  → brk_cli detects fill, drops order
  → BTX Trades page renders the fill           ← step 8
  → BTX Book page: empty book + 1 fill
```

No off-chain state was created. Anyone running their own bitcoind + brk-btx fork would reach the
same book hash by replaying the chain.

## Cleanup (optional)

```bash
# Stop everything, throw the regtest chain away
pkill -f 'python3 btxd.py' 2>/dev/null
pkill -x ord 2>/dev/null
pkill -x brk_cli 2>/dev/null
pkill -SIGTERM -x bitcoind 2>/dev/null
sleep 3
rm -rf ~/.btx/data/regtest ~/.btx/brk-regtest
```

Restarting btx-app brings the stack back up clean.
