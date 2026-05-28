# BTX partial fills — design analysis (2026-05-23)

## The constraint that forces the design
A BTX order is a maker-pre-signed spend of the **whole** offer UTXO (input 0), signed with
`SIGHASH_SINGLE | ANYONECANPAY`. That signature commits exactly two things: the offer input, and
**output 0 = the full committed payout**. Consequences:
- A UTXO can only be spent in its entirety — there is no "spend half a UTXO".
- The maker's signature fixes output 0 to one amount (the full price).

So a taker cannot take part of an offer: taking it spends the whole offer UTXO (all the asset) and
must pay the full committed price. **The pre-signed-offer primitive is inherently all-or-nothing.**

## Options, against BTX's constraints (pure on-chain, no relay, no consensus change)

### A. Denomination splitting — the only option that fits  ✅
The maker pre-splits the offered asset into N independent offer UTXOs (lots), each its own BTX
artifact with its own pre-signature. Takers take whole lots. Partial fill = take some lots, leave
the rest.
- **Pros:** works with the existing scheme unchanged; no new crypto; each lot is independently,
  asynchronously takeable with no maker interaction; reorg/fill/cancel logic per lot is what the
  store already does.
- **Cons:** N on-chain artifacts (cost scales with granularity); fixed granularity (a taker wanting
  1.5 lots takes 1, or 2 and over-buys); the maker pays a setup tx to split; "dust" lot at the end.
- **Granularity choice:** fixed lot size, or a ladder (e.g. powers of two: 1,2,4,8 … lots) so a
  taker can cover most amounts with few takes. Powers-of-two minimizes artifact count for arbitrary
  fill sizes (log N lots cover any amount).

### B. Maker re-signs the remainder per partial take  ❌ (breaks no-relay)
Taker takes part, returns the remainder as a new offer UTXO that the maker re-signs and re-posts.
Requires the maker to be online and act on every partial fill — that is a coordinator/interaction
loop, which contradicts the asynchronous, no-relay model. Rejected.

### C. Covenant-enforced partial spend  ❌ (needs consensus changes)
A script that lets a taker spend part of the offer while enforcing the remainder stays offered and
the payment is pro-rata. Requires covenants/introspection (CTV/CSFS/OP_VAULT-style) not in Bitcoin
consensus today. Out of scope per the brief's constraint #5 (no consensus changes / no altcoin).

### D. Asset-level partial via Runes edicts  ❌ (payout doesn't scale)
One offer UTXO holds N runes; a taker takes some runes via an edict, leaving the rest. But the
maker's `SINGLE` sig still commits a fixed output-0 payout, so the taker would pay the **full**
price for a **partial** amount of runes. The payout can't scale with the fill under a single fixed
signature. Rejected.

## Recommendation
Under the pure chain-reconstructed, no-relay, no-consensus-change model, implement partial fills as
**denomination splitting (Option A)** with a powers-of-two lot ladder. This is the partial-fill
analog of the model's other coarse primitives ("first-spender-wins" instead of price-time
priority): it trades fine granularity for zero infrastructure, consistent with the brief's
"slow swap board, not a live CLOB" framing.

### Indexer/store impact (small)
The existing `btx_orders` store already keys by offer outpoint, so N lots are just N records — no
schema change. Optional: add a `group_id` field to the BTX artifact (a maker-chosen id shared by
all lots of one logical order) so the indexer/UI can present "1.5 of 4 BTC filled" by aggregating
lots with the same group_id. That is a one-field artifact addition, fully backward compatible
(unknown/zero group_id = standalone order).

## What this means for the product
Partial fills don't require new cryptography or protocol risk — they're a maker-side packaging
decision (how finely to split) plus an optional `group_id` for aggregation. The hard constraint is
granularity vs on-chain cost, which is the same latency/cost tradeoff the whole chain-reconstructed
model already accepts.
