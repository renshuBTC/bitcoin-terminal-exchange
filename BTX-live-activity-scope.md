# Scope — BTX as a live, server-less view of real on-chain Bitcoin DEX activity

**Goal.** Flip BTX from "an empty book for a brand-new `BTX1` format" into "**a server-less, own-node
view of real on-chain Bitcoin trading activity**" — the Runes / ordinal marketplace trades and Runes
etches/transfers that *already* happen on mainnet — with *publish-your-own-sovereign-order* layered on
top as the differentiating power-feature. This attacks the only real problem (the book is empty / no
demand) by showing data that already exists, and it reuses machinery we've already built and proven.

This stays **standalone** (its own repos/site); it does not fold into Bitcoin terminal.

---

## What we already have (reuse, not rebuild)

- **Pre-signed-swap detector (Rust, `btx.rs`).** `swaps_in_block` scans each block for inputs spent
  with `SIGHASH_SINGLE|ANYONECANPAY` (`0x83`) — the exact pattern every Runes/ordinal marketplace fill
  uses — and emits `SwapView { txid, height, presigned_inputs, has_runestone, payout_sats }`. Served at
  `/api/v1/btx/swaps`; the web UI already has a "Recent atomic swaps (detected on-chain)" section.
- **A minimal runestone decoder (Python, `btx_runes.py verify`).** Parses edicts (block, tx, amount,
  output) from a runestone — but only the simple edict case; not the full Runes protocol.
- **The indexing/serving spine.** BRK-based indexer (can index mainnet), a persistent reorg-safe store,
  the `/api/v1/btx/*` HTTP surface, and a no-server-state web UI.
- **Validated Runes encoding** (vs canonical `ord`) and the full `SIGHASH_SINGLE|ACP` settlement model.

## What's genuinely new (the real work)

1. **A proper Runes decoder in Rust** — the biggest piece. Parse arbitrary mainnet runestones
   (tag/value stream, edicts, etchings, mints, pointer, cenotaph handling), not just the toy edict
   case. *De-risk:* lean on an existing Rust crate (the `ordinals`/runestone crate ord itself uses)
   rather than hand-rolling the whole protocol; validate its output against runestones we decode with
   `ord` (we already have the `ord env` setup that validated our encoder).
2. **A trade classifier (heuristic).** Combine: a pre-signed `0x83` input + a runestone moving rune R +
   the output structure (output 0 = seller payout) → emit a "likely trade" record
   `{ rune_id, asset_amount_moved, btc_paid, buyer_spk, seller_spk, height, txid }`. This is inherently
   **heuristic** — `0x83` has other uses and marketplace output conventions vary — so it must be
   labelled "detected / likely," never "proven." Validate against a handful of *real* mainnet
   marketplace txs (Magic Eden / UniSat) by fetching their raw hex.
3. **A persistent activity feed + richer API.** Today `/swaps` is an on-demand last-~50-block scan.
   Turn it into a persisted, paginated feed (e.g. `/api/v1/btx/trades`, `/api/v1/btx/runes`) with real
   history, so the page shows more than the last few minutes.
4. **Mainnet indexing.** The real version must index mainnet to show real data — **hundreds of GB, a
   long initial sync, and a separate node to run/maintain.** This is the heavy, recurring cost.
5. **UI reframe.** `btx_book.html` becomes "**Live on-chain Bitcoin DEX activity**": recent trades
   (Runes/ordinal), recent Runes etches/transfers, with the BTX sovereign-order book as one section
   rather than the whole page.

## Suggested phasing (de-risked, cheap → expensive)

- **Phase A — Rust runestone decoder + tests (offline, cheap, high-value).** Decode real runestones;
  unit-test against captured mainnet runestone hex cross-checked with `ord`. No mainnet sync needed.
  This is the prerequisite for everything and is a clean, bounded piece of work.
- **Phase B — trade classifier on captured txs (offline).** Build the classifier; validate against a
  dozen real mainnet marketplace txs fetched by txid. Tune the heuristic; measure false positives.
- **Phase C — persisted feed + UI reframe (regtest / captured data).** Wire the feed + API + the new
  UI, proven on constructed/captured data before any mainnet commitment.
- **Phase D — mainnet index (the heavy commit).** Only after A–C show the feed is genuinely useful on
  real captured data. Hundreds of GB + long sync; decide then whether it's worth standing up.

## Honest cost / payoff — read before committing

- **Classification is heuristic.** From a confirmed tx alone you cannot *prove* "this was a trade of X
  runes for Y BTC"; you infer it from the `0x83` input + runestone + output shape. The feed must be
  honestly labelled, and there will be false positives/negatives.
- **You'd be competing with polished incumbents.** mempool.space, Magic Eden, UniSat, and ord explorers
  already show Runes/ordinal trades with full history and far better UX. BTX will **not** out-feature
  them. Its *only* differentiator is the same narrow one as the DEX: **your own node, no third-party
  API, server-less / no relay.** That matters to a sovereignty-minded user and as an "it's all from
  your node" story — not to a general audience looking for the slickest explorer.
- **Mainnet is a real, recurring cost** (sync + a node to keep running), separate from your analytics
  node.
- **Honest payoff:** a genuinely *useful* (non-empty, real-data) server-less view that reuses what you
  built, tells a clean "reconstructed from your own node, nothing else" story, and is plausibly
  interesting content. It does **not** create a moat or a monetization path on its own — the value, as
  before, is the interesting/sticky feature and the credibility of the underlying skills, not revenue.

## Recommendation

Start with **Phase A** (the Rust runestone decoder + offline tests). It's bounded, needs no mainnet
sync, is the prerequisite for the whole direction, and produces immediate, verifiable value (decode any
mainnet runestone, cross-checked with `ord`). Defer the mainnet decision (Phase D) until Phases A–C
prove the feed is worth running. If after Phase A/B the heuristic feed looks weak or too close to the
incumbents, that's a cheap, honest off-ramp before the expensive part.

*Open question for you:* is the intended audience the **sovereignty/self-host** crowd (in which case
"own-node, no API" is the whole pitch and worth leaning into hard), or a general Bitcoin audience (in
which case this competes with incumbents on UX and is a harder sell)? That answer shapes how much to
invest past Phase A.
