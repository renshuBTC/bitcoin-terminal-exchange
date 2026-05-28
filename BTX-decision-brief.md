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
