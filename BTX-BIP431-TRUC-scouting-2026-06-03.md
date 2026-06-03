# Scouting report — `bitcoin/bips bip-0431` (Gloria Zhao — TRUC v3 transactions)

*Fifteenth scouting target this 2026-06-03 cycle. Domain: mempool
policy hardening against pinning attacks via `nVersion=3` opt-in.*

Date: 2026-06-03.

## Why this BIP / repo

BIP-431 by Gloria Zhao (Bitcoin Core mempool policy maintainer)
defines **TRUC** — Topologically Restricted Until Confirmation —
opt-in via `nVersion=3`. It's specifically designed to harden
contracting protocols (Lightning, but also any presigned-tx system
like BTX) against **pinning attacks**: an adversary attaching a
low-fee descendant to a counterparty's transaction to block RBF
replacement.

For BTX, the relevance is direct: BTX's
`BTX-frontrunning-threat-model.md` documents adversarial mempool
manipulation as a real concern. TRUC is a recently-merged Core
hardening (PRs #28948, #29873, #29496, all in Core v28+) that could
materially harden BTX's reveal transaction's mempool position.

## What TRUC specifies (verbatim from BIP-431 §Specification, lines 94-139)

> ```
> Senders can signal that they want a transaction to be Topologically
> Restricted Until Confirmation (TRUC). Specifically, set
> nVersion=3.
> ```

The 6 rules:

1. **Auto-RBF**: TRUC signals replaceability regardless of nSequence.
2. **All-or-none ancestors/descendants**: TRUC unconfirmed ancestors
   must be TRUC; TRUC descendants must be TRUC. *Exception:* TRUC
   may spend **confirmed** non-TRUC outputs (line 104).
3. **1-parent-1-child topology**: max 1 unconfirmed ancestor; max 1
   unconfirmed descendant.
4. **10,000 vB cap** on TRUC transaction size.
5. **1,000 vB cap** on TRUC child if it has an unconfirmed TRUC
   parent.
6. **Sub-min-relay-feerate allowed** in a package that meets the
   feerate as a whole.

## BTX's current emission

From `btx_envelope_publish.py:92` verbatim:

> ```python
> tx = CMutableTransaction([txin], [txout], nVersion=2, nLockTime=0)
> ```

And the txin:

> ```python
> txin = CMutableTxIn(COutPoint(txid_internal, commit_vout),
>                     nSequence=0xffffffff)
> ```

BTX's reveal is:
- `nVersion = 2`
- `nLockTime = 0`
- `nSequence = 0xffffffff` (BIP-125-incompatible — no RBF signal)
- 1 input (the commit utxo), 1 output (the envelope output)
- Total size: ~150-200 vB (well under the 10,000 vB TRUC cap)

## TRUC-compatibility audit, rule by rule

| Rule | BTX status | Notes |
|------|------------|-------|
| 1 — auto-RBF on `nVersion=3` | ✓ trivially compatible | Flip nVersion=3, get RBF for free. |
| 2 — all-or-none ancestors | ⚠ **blocker** | Reveal spends commit. Commit is the user's wallet funding tx, typically `nVersion=2`. The reveal can be TRUC only if commit is also TRUC OR is confirmed. |
| 3 — 1-parent-1-child | ✓ trivially compatible | BTX reveal has exactly 1 parent (the commit) and zero descendants until taker fills. |
| 4 — 10,000 vB cap | ✓ trivially compatible | BTX reveal is ~150-200 vB. |
| 5 — 1,000 vB child cap | ⚠ context-dependent | If a taker's fill tx becomes the TRUC child of the reveal, the fill must be ≤ 1,000 vB. Single-rune-output fills are ~150 vB; multi-rune fills can grow. |
| 6 — sub-min-relay-feerate package | ✓ trivially compatible | BTX doesn't rely on this but it's free. |

**Rule 2 is the real architectural blocker.** A user-wallet-funded
commit cannot be TRUC unless the user's wallet patches `nVersion=3`
onto its outgoing txs — that's a Bitcoin Core wallet change, not
something BTX controls.

## Two viable BTX paths

### Path A — Confirm-first

BTX flow change: require the commit to confirm before broadcasting
the reveal. Under Rule 2's exception "TRUC can spend confirmed
non-TRUC", the reveal then becomes TRUC-eligible.

Pros:
- No wallet changes required
- Reveal gets full TRUC protections (RBF + pinning resistance)

Cons:
- Slowest UX path: commit confirmation can take 10+ minutes
- BTX's current flow allows immediate reveal broadcast (commit and
  reveal in successive blocks or even the same block)

### Path B — Dedicated TRUC fee-only wallet

BTX bundles a tiny "fee-only" wallet that BTX itself controls. All
commit funding comes from this wallet, which emits `nVersion=3`
funding txs.

Pros:
- Reveal can be TRUC immediately
- No waiting on commit confirmation

Cons:
- Wallet bundle change (significant; BTX deliberately uses Core's
  wallet today, per `btx_wallet.py`)
- Operational complexity: BTX would need to top-up its fee-only
  wallet from the user's main funds

### Path C — Don't adopt TRUC (status quo)

BTX's reveal stays `nVersion=2`. The threat model already covers
mempool sniping at a structural level (snipe-resistant addressed
swaps, per `BTX-frontrunning-threat-model.md`). TRUC adds
defense-in-depth but the existing protocol-level snipe defenses are
the primary line of defense.

## Recommendation

**Defer with concrete trigger.** TRUC is shippable but only useful
if BTX's threat model identifies pinning of reveals as a real attack
path. Currently the threat model focuses on:

- Maker-side snipe: a third party watches the mempool, copies the
  maker's announce envelope, signs a competing taker fill
- Solved via addressed-only swaps (commit `60cd23a` per memory)

Pinning of the reveal itself is a different attack: an adversary
attaches a low-fee descendant to the maker's reveal, preventing the
maker from RBF-bumping it. This:

- Requires the adversary to be able to spend from the reveal output,
  which is BTX2-envelope-encumbered — only the maker can spend
- Therefore the pinning attack surface is NOT present for BTX2
  reveals

**Conclusion**: TRUC's primary benefit (pinning resistance via
descendant-feerate constraints) doesn't apply to BTX because BTX
reveals are not spendable by adversaries before being filled. The
reveal cannot be pinned because no one but the maker can attach a
descendant to it.

TRUC could still be adopted for *fee-bump reliability* (Rule 1:
auto-RBF), but BTX's reveal is small and broadcastable at a
reasonable fee from the start, so RBF is a marginal benefit.

## Verdict

`bip-0431` TRUC is well-designed for Lightning and similar
contracting protocols where presigned txs need bullet-proof
broadcast reliability under adversarial mempool conditions.

For BTX:
- **No code lands.** BTX's threat model doesn't have a pinning attack
  on reveals (the encumbered output isn't spendable until filled).
- **Bookmark for v1.0 with maker pools**: if BTX maker pools ever
  emit presigned-style txs where third-party pinning is possible,
  TRUC becomes load-bearing. Rule 2's "must be all-TRUC unless
  confirmed" is the implementation gating constraint.

New defer-reason category: **threat-model-mismatch** — the tool
addresses a threat BTX's architecture doesn't expose. Distinct from
the previous 8 categories.

| Category | Distinction |
|----------|-------------|
| product-timing (ChillDKG) | Right tool, BTX wants it later |
| scope-mismatch (BIP-388) | Right tool, BTX may never need it |
| **threat-model-mismatch (BIP-431)** | **Right tool, BTX's design already neutralises the threat** |

This is now **9 defer-reason categories**.

## Updated pattern across 15 scouts

| # | Target | Outcome |
|---|--------|---------|
| 1 | secp256k1-zkp | shipped |
| 2 | secp256kfun | shipped + specced |
| 3 | BIP-374 DLEQ | shipped |
| 4 | rust-miniscript | shipped |
| 5 | sipa/minisketch | spec (operational) |
| 6 | mit-dci/utreexo | spec (architectural-no-use) |
| 7 | Merkleize/pymatt | spec (consensus) |
| 8 | bitcoin-core/HWI | spec (product) |
| 9 | petertodd/python-bitcoinlib | spec (era) |
| 10 | darosior/python-bip380 | shipped xtest |
| 11 | BlockstreamResearch/bip-frost-dkg | spec (product-timing) |
| 12 | romanz/electrs | spec (architectural-protocol) |
| 13 | BIP-322 | shipped |
| 14 | BIP-388 | spec (scope-mismatch) |
| 15 | **BIP-431 TRUC** | **spec (threat-model-mismatch — NEW)** |

Extraction: 6/15 = 40%. 9 distinct defer categories.

## Trigger conditions

| Trigger | What to do |
|---------|------------|
| BTX maker pools emit presigned txs spendable by counterparties before fill | Adopt TRUC for those txs |
| BTX uses Lightning-style anchor outputs | Adopt TRUC (BIP-431's primary intended use case) |
| Core deprecates BIP-125 RBF signaling | TRUC's auto-RBF becomes the default RBF path |

## Files

```
Bitcoin CoreX/bitcoin-bips-reference/
  └── bip-0431.mediawiki                       290 lines spec

bitcoin-terminal-exchange/
  └── BTX-BIP431-TRUC-scouting-2026-06-03.md   (THIS DOC)
```

## Source

BIP: <https://github.com/bitcoin/bips/blob/master/bip-0431.mediawiki>
Author: Gloria Zhao (Bitcoin Core mempool maintainer)
License: BSD-3-Clause
Examined: master HEAD of bitcoin/bips clone, 2026-06-03.
Status: Draft (as of 2024-01-10 assignment); Core PRs merged.
