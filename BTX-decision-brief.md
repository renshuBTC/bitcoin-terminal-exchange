# BTX — decision brief (2026-05-23)

An honest synthesis of where BTX stands and the realistic ways forward. Written to be useful for a
decision, not to flatter the project.

## What you actually have (assets, verified)
- A **working, end-to-end-proven** chain-reconstructed on-chain order-book DEX on Bitcoin: publish →
  index → serve → fill → settle, validated on **regtest and signet** (real network block format).
- A non-trivial **Rust + Bitcoin-protocol body of work**: a BRK indexer fork with a custom store,
  reorg-safe order book, HTTP API; PSBT `SIGHASH_SINGLE|ANYONECANPAY` settlement; Taproot/BIP341
  envelope + OP_RETURN carriers; runes encoding validated against `ord`; a self-tested signet magic
  tool. All committed across two private repos (`bitcoin-terminal-exchange` for the Python
  tooling/frontend, `brk-btx` for the BRK indexer fork).

## The hard truth (so you don't bet on a mirage)
- **No technical moat.** The on-chain-reconstructed order book was shipped by **Counterparty in
  2014** (with *better* matching — protocol-level vs. your first-valid-spender). The settlement
  primitive is the industry-standard PSBT pattern every Runes/Ordinals market uses. BTC↔asset
  order-book DEXs already ship (Orders.Exchange, Unitap, UniSat, Fluid Tokens).
- **Your one differentiator is narrow:** the order book is as uncensorable/available as Bitcoin
  itself (no relay/server/Nostr). Real, but it loses to a Nostr book (e.g. Orders.Exchange) on cost,
  speed, scale, and privacy — and Nostr already delivers "no server, no middleman" nearly as well,
  for free. The edge only matters to an extreme-sovereignty / adversarial-environment user.
- **Monetization fights the design.** No server + no token = no fee chokepoint. Every order/cancel is
  an on-chain tx. The purity that makes it unique is exactly what makes it hard to fund.

## Three honest paths

**A. Ship BTX as a sovereignty product.** Pursue the narrow "uncensorable order book" niche.
- Next: public-signet propagation test → then mainnet; pick the carrier (Taproot envelope is the
  robust one; OP_RETURN now relays by default on Core v30+); decide the real counter-asset (the
  locked goal is a USD-stablecoin, which reintroduces an issuer/middleman — the one accepted
  exception). Funding likely = grants (OpenSats/HRF — the censorship angle fits) or being the
  market-maker yourself.
- Honest odds: small addressable audience; competes with free, faster Nostr designs. High effort,
  uncertain payoff. Do this only if maximal sovereignty is the *point* for you, not the money.

**B. Pivot the value to the indexer/analytics + your skills (recommended for income).**
- You already run a BRK analytics fork (the Bitcoin terminal). That — plus the depth this BTX work
  demonstrates (Rust, indexer internals, Bitcoin protocol, live debugging, signet) — is the more
  reliable route to money, especially toward your Singapore-bank-BTC-analyst goal.
- Next: package BTX as a **portfolio/credibility piece** (the repos + a sharp case study), and
  invest in the analytics/indexer as the sellable product or the resume that lands the role/contracts.
- Honest odds: the highest-EV path given the no-moat finding. Income comes from *skills + tooling*,
  not DEX fees.

**C. Bank it and pause.** Everything is proven, documented, and version-controlled. Walk away clean
and return only if a concrete reason (a customer, a grant, a sovereignty mandate) appears.

## Recommendation
Given that the goal includes **making money**, and BTX has no moat: treat BTX as a **finished,
impressive proof-of-skill (Path B / credibility), not a product to bet on (Path A).** Lean into the
indexer/analytics and what these repos prove you can build. Keep Path A alive only as a grant-funded
or personal-conviction side-bet, not the income plan. This isn't pessimism about the engineering —
that part is genuinely strong — it's matching effort to where the return actually is.

## Immediate, low-regret next actions (Path B)
1. Write a 1-page case study from the proven results (settlement, signet validation, the debugging
   wins) — reusable for job/contract conversations.
2. Decide what the analytics BRK fork (the Bitcoin terminal) needs to become a sellable product or a
   standout portfolio piece, and scope that.
3. Park BTX at this clean checkpoint; revisit Path A only with a concrete external pull.

---

## Post-audit refresh (2026-05-29)

Six days after the original brief. What's changed since 2026-05-23, and does it move the needle on
the no-moat / Path-B conclusion?

**What changed:**

1. **CoreX → BTX rename + 14/14 end-to-end audit closed.** Both repos now PRIVATE
   (`renshuBTC/bitcoin-terminal-exchange` + `renshuBTC/brk-btx`); old public CoreX repos left as
   historical artifacts. Every load-bearing safety property is now empirically verified — including
   live signet propagation observed by `mempool.space` (third-party node) at +5 seconds. Full result
   matrix in `BTX-e2e-audit-results.md` (14 commits + a closing summary).
2. **Bitcoin Core v30 (target October 2026) ships OP_RETURN policy relaxation** (multi-OP_RETURN, up
   to 4MB combined). Slightly *erodes* the "uncensorable carrier" niche: once v30 deploys, the
   OP_RETURN carrier becomes more permissive on default-policy nodes, narrowing the gap between the
   "obscure Taproot envelope" and "plain OP_RETURN" carriers. BTX still wins on
   "indexer-reconstructed book = no off-chain dependency at all", which a relaxed OP_RETURN doesn't
   address.

**Does this move the needle?**

- **Path A viability**: marginally *worse*, not better. The audit makes BTX more credible as a
  sovereignty product, but the addressable audience hasn't grown — and Core v30 specifically reduces
  one of the technical edges (carrier obscurity) that Path A leaned on. **Recommendation unchanged:
  Path A only with a concrete external pull (grant, customer, sovereignty mandate).**
- **Path B value**: meaningfully *better*. The original brief's "impressive proof-of-skill" is now
  *empirically verified* proof-of-skill: 14/14 prompts, 1.8M property-fuzz assertions, live
  cross-network propagation observed by a third-party node. That's a much sharper artifact to point
  at in interviews or contract conversations than "we built it and it seems to work."
  **Recommendation strengthened: Path B is now the cleaner pitch.**
- **Path C** (bank it): genuinely available now. Everything is checked into private repos with
  per-prompt commit messages carrying the evidence; nothing rots. Can be resumed cleanly from this
  exact tag if a Path-A pull ever materializes.

**Triggers that would flip Path A → viable** (be honest about what these would need to look like):

- *Grant funded specifically for censorship-resistant Bitcoin DEX work* (OpenSats / HRF / similar)
  — concrete dollar amount + work plan, not aspirational alignment.
- *Sanctions / KYC squeeze on existing Runes/Ordinals marketplaces severe enough that "no server"
  becomes a market need*. Watch for: Magic Eden / Unisat / Saturn under regulatory pressure;
  exchanges delisting wrapped-asset OTC; mining concentration crossing 80% in a single jurisdiction.
- *A small market-maker desk willing to be the first liquidity provider* — needs a real BTC
  treasury, not just enthusiasm.

Until one of those exists, **Path B remains the matching-effort-to-EV recommendation**, now
upgraded by the audit closure to a sharper artifact.

**Final immediate action set (2026-05-29, supersedes the original "Immediate, low-regret"):**

1. The case study, threat-model docs, audit-results doc, and watchlist are all current and in-repo
   at HEAD. They function as the 1-page-equivalent portfolio artifact (the original brief's
   action #1). *Done.*
2. The Bitcoin terminal (analytics BRK fork) is the next product surface — but it's a different
   repo (`brk` analytics, not `brk-btx`) and a different scope. Treat that as its own decision.
3. Park BTX at commit `ccc3ef0` (HEAD as of this refresh). No code in `bitcoin-terminal-exchange`
   needs further work for the safety story. Future code work is only triggered by:
   - A Path A external pull (above), or
   - Core v30 deploying and Prompt 10's empirical result needing to be annotated for the new policy.
