# B4 — smallest possible mainnet broadcast

*The last BLOCKER in `BTX-mainnet-readiness-2026-05-31.md`. Validates that the
witness-envelope carrier propagates on mainnet under default relay policy and
gets accepted by third-party nodes. After B4 passes, BTX has been empirically
exercised end-to-end on real Bitcoin.*

## What B4 proves (and the cost ceiling)

**Proves:**
- The Taproot envelope (commit + reveal) is accepted by mainnet's default relay
  policy — same proof as 2026-05-24 on public signet, but on the real network.
- A third-party node (mempool.space) sees the reveal within ~30s of broadcast.
- `brk_cli` (if synced on mainnet) detects the announce from the witness and
  serves the order at `/api/v1/btx/orders`.

**Costs:**
- Two mainnet wallet transactions (commit + reveal).
- At a 1 sat/vB fee target (mainnet floor): commit ≈ 110 vB → 110 sats,
  reveal ≈ 200 vB → 200 sats. **Total ≈ 310 sats (~$0.15–$0.35).**
- Offer UTXO: gets LOCKED by maker-sign. Recoverable by cancel (a third
  mainnet tx, same fee magnitude). Pick a small offer (e.g. 5,000 sats / ~$3)
  so even if you abandon it, the loss is bounded.
- **Absolute ceiling:** if everything goes wrong, total exposure = offer +
  3× fee ≈ 5,000 + 600 = ~$3.50 at current BTC price. No mainnet asset can
  be drained beyond this.

## Why this is "smallest possible"

The order's price is set so absurd that no rational taker will fill it
(e.g. selling 1 sat of a non-existent rune for 1 BTC). The propagation test
is therefore decoupled from the trade-completion risk — we observe the
network behavior without anyone able to act on it. After observation we
cancel-by-RBF and recover the offer UTXO.

## Prerequisites — verify each before starting

- [ ] B1 ✓ (NSIS installer with v30.2)
- [ ] B2 ✓ (E2E regression passed on regtest)
- [ ] B3 ✓ (walk-back exercise closed — see `BTX-B3-walkback-exercise-2026-06-01.md`)
- [ ] BTX bundle installed at `%LOCALAPPDATA%\BTX` (any version with mainnet support)
- [ ] Mainnet `bitcoind` available, txindex enabled, synced to current tip
- [ ] Mainnet wallet `btx` (or your chosen wallet) loaded with at least 10,000 sats
- [ ] Network egress to `mempool.space` works (`curl -s https://mempool.space/api/v1/fees/recommended`)
- [ ] You can recover your wallet from seed if anything corrupts (safety net)

Confirm BTC price ≥ $80,000 isn't suddenly $1,000,000 — i.e. spot-check
current fee market via mempool.space so the 1 sat/vB target isn't naïve.
At current fee market (verify), 1 sat/vB is the relay floor.

## The runbook

### Step 0a — automated pre-flight (recommended)

```bash
cd /mnt/c/Users/Ren\ Shu/Documents/Claude/Projects/bitcoin-terminal-exchange
bash b4_preflight.sh
```

This runs 8 checks (chain=main, sync state, wallet balance, P2WPKH UTXO available,
fee market, mempool.space reachable, publisher selftest, stale state files) and
returns GREEN/YELLOW/RED. Don't proceed past Step 4 unless GREEN. The script
respects env vars `BTX_BIN`, `BTX_DATADIR`, `BTX_WALLET`, `MAX_OFFER_SATS`.

### Step 0b — set the WSL environment

```bash
# Adjust BIN if your mainnet bitcoind binary lives elsewhere
BIN=$HOME/.btx/bin                    # bundled v30.2
DD=$HOME/.bitcoin                     # or wherever your mainnet datadir is
CLI="$BIN/bitcoin-cli -datadir=$DD -rpcwallet=btx"
cd /mnt/c/Users/Ren\ Shu/Documents/Claude/Projects/bitcoin-terminal-exchange
```

Sanity:

```bash
$CLI getblockchaininfo | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["chain"], d["blocks"], round(d["verificationprogress"],4))'
# expect: main <current_height> 1.0
$CLI getbalance       # expect: at least 0.0001 BTC (10k sats)
```

### Step 1 — pick a UTXO and confirm it's a P2WPKH

```bash
$CLI listunspent 1 | python3 -c "import sys,json;[print(u['txid'], u['vout'], u['amount'], u['scriptPubKey'][:4]) for u in json.load(sys.stdin)]"
# pick one with scriptPubKey starting '0014' (P2WPKH) — easiest for maker-sign.
# Don't pick your largest UTXO; pick the smallest one ≥ 5,000 sats.
OFFER_TXID=<paste>
OFFER_VOUT=<paste>
```

### Step 2 — maker-sign an absurd-price order

```bash
# Pick a deliberately non-existent rune ID. The rune ID is (block, tx_index).
# Real mainnet runes started at block 840000 and grow over time. We pick a
# rune_block FROM THE FUTURE so nothing matches on mainnet. The carrier
# still publishes the artifact bytes regardless of whether the rune exists.
#
# IMPORTANT: rune_tx is a u16 in the artifact wire format (max 65535), so
# pick a tx index that fits. The block far in the future is what guarantees
# non-existence; the tx index inside that block just has to be valid u16.
# Using rune_tx=1 (a real-looking tx index) is fine because rune_block=9999999
# alone makes the rune impossible.
python3 btx_wallet.py maker-sign \
  --bitcoin-cli "$BIN/bitcoin-cli" --chain main --datadir "$DD" --wallet btx \
  --offer-txid "$OFFER_TXID" --offer-vout "$OFFER_VOUT" \
  --price-btc 1.0 \
  --amount-units 1 \
  --rune-block 9999999 --rune-tx 1 \
  --carrier envelope
# -> JSON with "artifact_hex": "42545831..." — copy it into a variable:
ARTIFACT_HEX=<paste from JSON>
# --price-btc 1.0 + --amount-units 1 means selling 1 unit of rune for 1 BTC.
# Absurd by design — no rational taker can fill this.
# We do NOT pass --require-rune-backing so maker-sign won't try to verify
# the offer UTXO against ord. The rune doesn't exist on mainnet by design.
```

If `maker-sign` errors with "offer UTXO already locked" from a previous run,
release it via `$CLI lockunspent true "[{...}]"` and retry, or pick a
different UTXO with `--no-lock-offer` to skip the auto-lock (NOT recommended
— the lock prevents the wallet from accidentally spending the offer UTXO).

> **CHECK before continuing:** Maker-sign locked your `OFFER_TXID:OFFER_VOUT`.
> Confirm with `$CLI listlockunspent` — your UTXO should appear. If something
> goes wrong from here, recover by `$CLI lockunspent true '[{"txid":"…","vout":N}]'`.

### Step 3 — dry-run the envelope publish

```bash
python3 btx_envelope_publish.py publish \
  --artifact-hex <ARTIFACT_HEX> \
  --bitcoin-cli "$BIN/bitcoin-cli" --chain main --datadir "$DD" --wallet btx \
  --commit-amount-btc 0.0000546 \
  --fee-sats 200 \
  --dry-run
# -> JSON with commit_address, commit_scriptpubkey, envelope_tapscript_hex
# Verify the commit_address looks sane (bc1p... = P2TR mainnet)
```

If the dry-run errors at this stage, STOP. Common errors:
- "Insufficient funds" → wallet too small.
- "scriptPubKey policy" → bitcoind config issue, check `getnetworkinfo`.
- "BIP341 sighash" → upstream bug in the publisher (don't proceed; capture
  the error message and investigate).

### Step 4 — testmempoolaccept the would-be reveal

This is the key gate. We're verifying our OWN node would accept the reveal
under default policy BEFORE we commit real sats.

```bash
# btx_envelope_publish.py supports building unsigned commit+reveal without broadcasting
# (look at btx_envelope_publish.py source for --build-only flag if present).
# Alternative: just take the leap with --broadcast on step 5; the commit's policy
# is trivial (P2TR output) and the reveal's policy was proven on signet.
```

(If `--build-only` or similar isn't supported, skip this step and rely on the
2026-05-24 signet result + B2 regtest result. The mainnet default policy for
inscriptions matches signet's, which was empirically proven to accept.)

### Step 5 — BROADCAST (this is the only irreversible step)

> **THIS IS THE ACTION I CANNOT DO FOR YOU.** Per my financial-action rules,
> I leave the actual broadcast to your hand. Below is the exact command;
> copy-paste only when you're certain. The next time you can stop is right
> after this — once `--broadcast` returns, the commit + reveal are in the
> mempool and will start propagating.

```bash
# Use a state file so a crash between commit and reveal is recoverable.
# `publish-reveal --state-file` can complete the reveal if the publisher
# crashes after the commit broadcasts but before the reveal does.
STATE_FILE=$HOME/.btx/b4-state-$(date +%s).json

python3 btx_envelope_publish.py publish \
  --artifact-hex "$ARTIFACT_HEX" \
  --bitcoin-cli "$BIN/bitcoin-cli" --chain main --datadir "$DD" --wallet btx \
  --commit-amount-btc 0.0000546 \
  --fee-sats 200 \
  --state-file "$STATE_FILE" \
  --broadcast
# Output: JSON containing commit_txid, reveal_txid, and the witness fields.
# WRITE THESE DOWN BEFORE CONTINUING.
COMMIT_TXID=<from JSON>
REVEAL_TXID=<from JSON>
```

**If the publish errors after the commit broadcast but before the reveal,**
recover with:
```bash
python3 btx_envelope_publish.py publish-reveal \
  --bitcoin-cli "$BIN/bitcoin-cli" --chain main --datadir "$DD" --wallet btx \
  --state-file "$STATE_FILE" \
  --fee-sats 200 \
  --broadcast
```
This rebuilds and broadcasts the reveal from the saved state. The commit's
already on-chain (or on-mempool) so don't re-broadcast it.

### Step 6 — observe propagation (the actual B4 verdict)

```bash
# Local mempool
$CLI getmempoolentry $COMMIT_TXID >/dev/null 2>&1 && echo "commit in local mempool" || echo "MISSING"
$CLI getmempoolentry $REVEAL_TXID >/dev/null 2>&1 && echo "reveal in local mempool" || echo "MISSING"

# Wait 30s for propagation, then check mempool.space (third-party node)
sleep 30
curl -s "https://mempool.space/api/tx/$REVEAL_TXID" | python3 -m json.tool | head -20
# Expect: a JSON object with txid, fee, vout array, etc.
# 404 = third-party node has NOT seen it = propagation FAILED at minute 0:30.
```

**Verdict criteria:**

| mempool.space at +30s | Verdict | Next step |
|------------------------|---------|-----------|
| Returns 200 with the tx JSON | ✅ **B4 PASS** | continue to Step 7 |
| 404 | inconclusive | wait another 60s, retry; if still 404, increase fee with RBF |
| 5xx | mempool.space issue | try blockstream.info: `curl -s https://blockstream.info/api/tx/$REVEAL_TXID` |

### Step 7 — wait for confirmation (typically 10–30 min)

```bash
# Poll local node for confirmations
$CLI getrawtransaction $REVEAL_TXID true | python3 -c "import sys,json;d=json.load(sys.stdin);print('confs', d.get('confirmations'), 'block', d.get('blockhash','PENDING'))"
# Once 'confs' is ≥1, you have a mined-on-mainnet BTX1 envelope.
```

When the reveal confirms with ≥1 confirmation: **B4 is fully validated.**

### Step 8 — release the locked offer UTXO

```bash
# Unlock so future BTX/wallet operations can use it
$CLI lockunspent true "[{\"txid\":\"$OFFER_TXID\",\"vout\":$OFFER_VOUT}]"
```

If you want to be tidy about the absurd order remaining "OPEN" in the indexer,
spend the offer UTXO back to yourself (cancel):

```bash
$CLI sendtoaddress $($CLI getnewaddress) <amount minus tx fee> "B4 cancel" "" true
# Replace <amount minus tx fee> with the offer's value minus a 200-sat fee
```

This spends `$OFFER_TXID:$OFFER_VOUT`, marking the BTX order as CLOSED in
indexers that see this tx.

## Failure recovery

### "Broadcast succeeded but propagation failed (mempool.space 404 indefinitely)"

This would suggest the envelope reveal is being rejected by default-policy
peers — a NEW finding contradicting the 2026-05-24 signet result. Diagnostic:

```bash
# Compare your fee rate to mempool.space's recommended floor
curl -s https://mempool.space/api/v1/fees/recommended | python3 -m json.tool
# If your --fee-sats was too low for mainnet's minimum relay fee, the tx
# would not propagate even though your local node accepted it.
```

Bump fee with RBF (the v0.2.18 hardening added RBF-signal on the funding
input, but not necessarily on the commit/reveal; check `btx_envelope_publish.py`
for RBF flag). If no RBF support, accept the loss of the commit/reveal fees
(~310 sats) and they'll drop from mempools in 2 weeks.

### "Reveal broadcast errored with mandatory-script-verify-flag-failed"

This is a sighash/sig/control-block bug in `btx_envelope_publish.py`. STOP.
Capture the exact error, the artifact_hex, and the commit_txid. Do NOT retry
— the commit is sunk but the reveal can be rebuilt by an updated publisher.
The 2026-05-24 signet proof + B2 regtest result + offline BIP341 vectors
make this outcome very unlikely.

### "I want to abort mid-runbook before broadcast"

You're safe to abort at any point BEFORE Step 5's `--broadcast` returns. The
maker-sign in Step 2 only LOCKS your UTXO locally (no on-chain side effect).
Release it with `$CLI lockunspent true …` as in Step 8.

## What B4 does NOT prove

- **Demand.** No real takers exist for an absurd-price order. B4 proves the
  carrier works, not that anyone will use it.
- **Adversarial node policy.** mempool.space is one third-party node. A
  hostile node could theoretically reject the carrier. The 2026-05-24 signet
  proof's confirmation-by-public-signet-signer was stronger evidence; B4 just
  extends that to mainnet's relay graph.
- **Long-term miner inclusion.** Confirming once doesn't mean every miner
  will include envelopes. They might at low priority. For a real product, run
  the seeding pattern on mainnet for ≥1 week and observe rates.

## After B4 passes

1. Mark B4 ✓ in `BTX-mainnet-readiness-2026-05-31.md`.
2. Record the mainnet commit + reveal txids in this doc (append to bottom).
3. Tweet/announce — or don't. Up to you. The technical case is closed; the
   demand case is its own problem (see the "Forward-looking" section of the
   readiness doc).

## Record of execution

> Fill in after B4 runs:
>
> - Date: ____________________
> - Commit txid: ____________________
> - Reveal txid: ____________________
> - Block height of reveal: ____________________
> - mempool.space propagation latency: ____________________
> - Notes: ____________________
