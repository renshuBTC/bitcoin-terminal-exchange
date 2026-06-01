# BTX — what to do after B4 broadcasts

*Companion to `BTX-B4-mainnet-broadcast-runbook.md`. After Step 5 returns
commit_txid + reveal_txid, this doc covers everything that happens before
you can declare BTX mainnet-ready.*

The B4 runbook covers up through "wait for confirmation" and "release the
locked offer UTXO". This playbook covers the verification + docs + cleanup
that turns a working broadcast into a fully-recorded mainnet milestone.

## Phase 1 — independent verification (10-20 min)

You've already checked mempool.space in the runbook. The goal here is to
have THREE independent third-party observers confirm the reveal:

```bash
# Already done in runbook Step 6
curl -s "https://mempool.space/api/tx/$REVEAL_TXID" | python3 -m json.tool | head -20

# Add: blockstream.info (different operator, different node)
curl -s "https://blockstream.info/api/tx/$REVEAL_TXID" | python3 -m json.tool | head -20

# Add: mempool.observer (cmempool fork, often picks up txs faster on smaller fee)
curl -s "https://mempool.observer/api/tx/$REVEAL_TXID" 2>&1 | head -20
```

All three returning HTTP 200 with the tx JSON = **propagation across the
mainnet relay graph is empirically proven** under default policy. Two out of
three is also acceptable if one is having an outage (check their status pages).

If ONLY mempool.space returns 200 and the others 404 for more than 10 minutes,
that's a yellow flag — propagation may be local-only. Possible causes:
- fee too low for some peers (re-check fee rate)
- some peer-level filter against inscription-style witnesses
- third-party API caching

## Phase 2 — extract + verify the BTX1 magic from the confirmed witness (5 min)

This is the second-strongest evidence the carrier worked: pull the witness
data straight from the confirmed tx and prove it contains the BTX1 artifact:

```bash
# Once the reveal has 1+ confirmation
RAW=$($CLI getrawtransaction $REVEAL_TXID true)

# Extract the witness stack (3 items: schnorr_sig, envelope_tapscript, control_block)
echo "$RAW" | python3 -c "
import sys, json
d = json.load(sys.stdin)
vin0 = d['vin'][0]
wit = vin0.get('txinwitness') or vin0.get('witness') or []
print(f'witness has {len(wit)} stack items')
for i, item in enumerate(wit):
    print(f'  [{i}] {len(item)//2} bytes — {item[:48]}...')
# The middle item is the envelope tapscript; verify it contains BTX1 magic.
ts = wit[1] if len(wit) >= 2 else ''
btx1_marker = '42545831'  # 'BTX1' in ASCII hex
if btx1_marker in ts:
    print(f'  >>> BTX1 magic FOUND at byte offset {ts.index(btx1_marker)//2} in tapscript <<<')
else:
    print('  ??? BTX1 magic NOT found — investigate ???')
"
```

Pass criterion: BTX1 magic is present in the tapscript. This proves the
envelope encoded the artifact correctly AND the consensus layer accepted
the script-path spend — both of which were proven offline + on signet but
now have mainnet empirical proof.

## Phase 3 — cancel the absurd order (optional, ~5 min)

The order announces a sale of 1 unit of a non-existent rune for 1 BTC. No
one can fill it (the rune doesn't exist). It will sit "OPEN" in any
indexer's book forever until either:
1. The offer UTXO is spent (cancel)
2. The expiry block is reached (we set `--expiry 10^9` by default — unreachable)

If you want the order to disappear from any indexer's view:

```bash
# Get the lock release first (B4 runbook Step 8 already did this)
$CLI lockunspent true "[{\"txid\":\"$OFFER_TXID\",\"vout\":$OFFER_VOUT}]"

# Spend the offer UTXO to a new wallet address (this is the cancel)
NEW=$($CLI getnewaddress "" bech32)
AMOUNT=$(python3 -c "print(f'{$OFFER_AMOUNT_SATS / 100000000:.8f}')")
$CLI sendtoaddress $NEW $AMOUNT "B4 cancel" "" true
```

Indexers see the offer UTXO consumed → mark the order CANCELLED. Costs one
more tx fee but cleans up the global view. **Skip this step if you don't
care** — the absurd price means nothing will ever fill it anyway.

## Phase 4 — record the txids permanently (5 min)

The B4 outcome is the empirical proof we've built BTX for. Record it
durably:

### a. Update `BTX-B4-mainnet-broadcast-runbook.md`

Append at the bottom under "Record of execution":

```markdown
- Date: 2026-MM-DD
- Commit txid: <commit_txid>
- Reveal txid: <reveal_txid>
- Block height of reveal: <height>
- mempool.space propagation latency: <X seconds>
- blockstream.info propagation latency: <Y seconds>
- BTX1 magic extraction: PASS (offset <N> in tapscript)
- Notes: <anything noteworthy>
```

### b. Update `BTX-mainnet-readiness-2026-05-31.md`

Replace the B4 section:

```markdown
### B4 — no mainnet broadcast has ever happened ✓ DONE (2026-MM-DD)

A test-rune order announce was broadcast via the witness-envelope carrier
on mainnet. The reveal (txid `<reveal_txid>`) confirmed in block `<height>`,
was observed propagating to mempool.space within `<X>` seconds and
blockstream.info within `<Y>` seconds (two independent third-party nodes).
The witness tapscript contains the BTX1 magic at byte offset `<N>`,
confirming the consensus layer accepted the script-path spend carrying the
BTX artifact. **The technical mainnet-readiness case is empirically closed.**

**Next step:** none. Carry the empirical result into any external
announcement / decision-brief.
```

### c. Save a memory record

Create `project_btx_b4_completion_2026-MM-DD.md` in your memory dir:

```markdown
---
name: project-btx-b4-completion-2026-MM-DD
description: "B4 mainnet broadcast SHIPPED. Reveal <reveal_txid> in block <height>, BTX1 magic verified, propagation to mempool.space + blockstream.info in <X>+<Y>s."
metadata:
  type: project
---

[full notes]
```

### d. Commit the doc updates + push

```bash
cd "/mnt/c/Users/Ren Shu/Documents/Claude/Projects/bitcoin-terminal-exchange"
git add BTX-B4-mainnet-broadcast-runbook.md BTX-mainnet-readiness-2026-05-31.md
git commit -m "B4 SHIPPED: mainnet envelope broadcast (reveal <reveal_txid> in block <height>)

Witness tapscript contains BTX1 magic verified. Propagation to
mempool.space within <X>s, blockstream.info within <Y>s. The
technical mainnet-readiness case is empirically closed.

Closes the last BLOCKER from BTX-mainnet-readiness-2026-05-31.md."
git push
```

## Phase 5 — what's next (the strategic side, not technical)

With B4 done, BTX is **technically** mainnet-ready. The remaining unknowns
listed in BTX-mainnet-readiness's "Forward-looking" section are:

- **Core v30 ecosystem split.** Empirically, your reveal propagated. But the
  real-world relay graph remains heterogeneous; a 1-week signet soak (O4)
  would reveal anything time-dependent.
- **Real liquidity.** B4 proves the carrier; it doesn't prove anyone wants
  to use BTX. That's the demand-side question and B4 doesn't move it.
- **External review.** Internal audits are exhaustive; an external security
  review is a separate proof. Out of scope for B4 but worth flagging.

If you intend to announce publicly, B4's reveal txid is the empirical
anchor. If you intend to defer announcement, B4 still earns the "we have
proven the rails work on mainnet" claim.

## Phase 6 — emergency rollback (if things go wrong)

Hopefully none of these fire, but documenting for completeness:

### "The reveal never confirms (24+ hours)"
- Most likely cause: fee too low for current mainnet conditions
- Check: `mempool.space/api/tx/$REVEAL_TXID/status` returns confirmed=false long after broadcast
- Fix: nothing to do. The tx will drop from mempools in 2 weeks. The commit
  is also stuck — but since the reveal is the ONLY thing that can spend the
  commit's P2TR output, the funds are inaccessible until the reveal confirms.
- Prevent: next time use higher --fee-sats (e.g. 1000 instead of 200)

### "I lost the seckey somehow despite F1 fix and --state-file"
- Recovery is impossible. The commit's P2TR output is spendable ONLY by the
  ephemeral seckey. If both the state file and the recovery JSON were lost,
  the commit funds are stranded forever.
- Total loss: 5460 sats (commit amount). Limited damage.
- Prevent: F1 fix is the safety net; don't disable it.

### "mempool.space says my tx is non-standard"
- Cause: probably a fee-rate issue; mempool.space's relay uses default policy
  but conservative thresholds
- Fix: try blockstream.info or another aggregator; the tx itself is policy-
  compliant per our offline tests
- If multiple aggregators reject: NEW finding, very valuable to capture.
  Save the exact tx hex and rejection messages — this would override our
  signet propagation result.

### "The order shows up on my BTX GUI but with weird state"
- The absurd-price (1 sat for 1 BTC) order is intentional to make filling
  impossible. The GUI may render the price as e.g. "1.0 BTC/unit" which
  looks odd but is correct.
- The "BACKING UNCONFIRMED" badge will be permanent on this order because
  the rune doesn't exist. This is correct.
- No action needed.

## Phase 7 — celebrate (optional, mandatory)

You built a fully on-chain DEX from scratch, audited it three times, proved
14+ technical claims empirically, and just shipped the first mainnet
broadcast. Take a beat.
