# BTX competitive landscape — 2026-06-04 refresh

*8-day update of `BTX-competitive-landscape.md` (2026-05-27). The
taxonomy is unchanged; what's changed is BTX's column.*

## TL;DR (what's different from the 2026-05-27 doc)

| | 2026-05-27 baseline | 2026-06-04 today |
|---|---|---|
| **BTX status** | Pre-mainnet, signet-only | Mainnet-broadcast-proven (block 952071, 2026-06-02), v0.3.0 |
| **BTX feature surface** | Single-maker + addressed swaps, runes, light-client follower | Above + BTX2 envelope stack (half-agg, adaptor, MuSig2 KeyAgg) + BIP-322 maker attestation primitive |
| **BTX cross-validation** | Runes triple-validated, BIP-340/341 canonical | Above + BIP-380 checksum triple-validated, BIP-322 vs canonical, half-agg vs hacspec spec |
| **Counterparty (XCP) daily volume** | ~$3.5/24h | ~$12/24h (within noise — both essentially dead) |
| **Light Pools** | Design paper (late 2024) | Still design paper; no shipping code surfaced |
| **Saturn BTC** | Uses Arch Network external VM | Same — confirmed by Arch Network's own blog as "leveraging the Arch Network's virtual machine and verifier nodes" |

Bottom line: nothing material changed for the competitors in 8 days.
BTX shipped a working mainnet broadcast, the BTX2 crypto foundation,
and a full-stack BIP-322 attestation feature.

## Taxonomy — unchanged

The honest way to compare "Bitcoin DEXes" is still by **where the
order book lives** and **what you must trust**:

| Category | Order book | Settlement | Trust | Systems |
|---|---|---|---|---|
| **A. Fully on-chain, Bitcoin L1** | Bitcoin L1 | Bitcoin L1 | Bitcoin consensus only | **BTX**, Counterparty, Omni |
| **B. Off-chain book, on-chain settle** | off-chain (server or gossip) | Bitcoin L1 | book host / gossip net | Magic Eden, **Light Pools**, most PSBT marketplaces |
| **C. Sidechain** | separate chain | separate chain | federation / alt-consensus | Liquid (Elements) |
| **D. VM / app-chain anchored to BTC** | external VM | VM + BTC anchoring | VM verifier set | **Saturn BTC** (Arch Network) |
| **E. Identity / compliance liquidity** | off-chain messages | any rail (often fiat) | credentialed intermediaries | tbDEX |

Within **A** — the only category where you only trust Bitcoin consensus
— BTX is still the only system with **no native token**, **UTXO-native**
state, and **atomic single-tx settlement**.

## Competitor-by-competitor, today (2026-06-04)

### Counterparty (XCP) — fully on-chain, the OG

Confirmed by [Coinpaprika](https://coinpaprika.com/coin/xcp-counterparty/):
24h volume ~$12, down 54% in a day. CoinMarketCap shows
[Counterparty DEX](https://coinmarketcap.com/exchanges/counterparty-dex/)
with "no active Exchanges/Markets" status.

Architecture unchanged: native XCP token, address-balance ledger
(not UTXO), two-phase match→BTCPay settlement with the free-option /
non-settlement gap. ~10 years of mainnet history.

**Versus BTX**: Counterparty has the live (tiny) market; BTX has the
better architecture. Liquidity beats architecture in DEX competition,
historically. BTX's bet is that the liquidity moat goes to whoever
makes self-custodial Bitcoin-native trading actually pleasant, and
that the 10-year-old Counterparty design isn't the answer.

### Omni Layer (MetaDEx) — fully on-chain

Architecture unchanged. The 2026-05-27 doc reads `omnicore-reference/
src/omnicore/mdex.{h,cpp}` directly: price-time book with exact
rational prices, consensus state-hash, native OMNI token,
address-ledger, auto-matching engine. Dormant.

**Versus BTX**: OMNI's price-time + consensus-hash design is what
BTX borrows for the deterministic book (roadmap #1, already shipped:
`brk-corex` Rust consensus book hash). What BTX rejects is the OMNI
token, address-ledger, and auto-matcher.

### Light Pools — design paper, no shipping code surfaced

Per Rodarmor's [Light Pools blog post](https://rodarmor.com/blog/light-pools/)
(late 2024) and the [Delphi Digital](https://members.delphidigital.io/feed/bitcoin-light-pools)
+ [Samara AG](https://www.samara-ag.com/market-insights/bitcoin-light-pools)
writeups (2025-2026): light pools are conceptually live but I see no
public code, mainnet deployment, or volume to point at. The protocol
remains:

- Maker quotes are **BIP-322-signed messages** gossiped on a P2P net
  (off-chain book; category B by the BTX taxonomy)
- Taker constructs a PSBT and broadcasts it to the network
- Maker **countersigns asynchronously** and broadcasts the final tx
- Mempool-sniping resistant by construction (signatures commit to all
  inputs/outputs)

**Versus BTX**: This is the most philosophically aligned competitor in
the entire field. Both stay Bitcoin-L1, both target asset trading,
both refuse external VMs / sidechains / native tokens. The architectural
fork is one of category:

- **Light Pools puts the book on a P2P gossip net (category B).** The
  maker must be online to countersign. The book is mutable in real
  time without on-chain activity.
- **BTX puts the book on Bitcoin's own relay (category A).** Makers
  pre-sign once and the order is non-interactive — open orders
  (`0x83`) don't need the maker online to fill.

Per `BTX-vs-light-pools.md`: "BTX is *more* Bitcoin-native than Light
Pools because it keeps the book on-chain." That claim stands.

Note: the shared use of **BIP-322** for spam-resistance / authentication
is now real for BTX too — see the new BIP-322 maker attestation feature
(commit `da1708d`, v0.3.0). BTX uses BIP-322 for *maker identity*
attestation, not for spamming the book. The book itself is on Bitcoin's
relay.

### Saturn BTC — Arch VM (category D), not Bitcoin L1

Arch Network's own blog [Saturn: The Breakthrough Bitcoin DEX](https://www.blog.arch.network/saturn-the-breakthrough-bitcoin-dex/):
*"By leveraging the Arch Network's virtual machine and verifier nodes,
Saturn enables smart contract functionalities, atomic swaps, and
liquidity pools…"*

This is verbatim what makes Saturn category D, not category A. Saturn
calls itself "on Bitcoin's base layer", but the verifier-node trust
extends to Arch's verifier set. Materially, Saturn is more like
Liquid (category C) than Counterparty (category A) — a separate
trust domain that anchors to Bitcoin but doesn't run inside Bitcoin
consensus.

Saturn is also a hosted product; BTX is a self-hosted bundle that
runs Bitcoin Core + brk_cli + ord + btxd on the user's machine.
That's a different position in the trust stack regardless of the
book layer.

### Magic Eden — closed-source hosted marketplace (category B)

Architecture unchanged. PSBTs with `SIGHASH_SINGLE|ANYONECANPAY`
(same settlement primitive as BTX's open orders), but the order book
lives on Magic Eden's servers. Closed source.

The borrow remains the same: `runestone-lib` (TypeScript) cross-
validates BTX's Runes layer (triple validation: ord Rust + Magic Eden
TS + BTX Python). The order-book design and indexer are not
transferable.

### Liquid (Elements) — federated sidechain (category C)

Unchanged. Strong Federations of functionaries; Confidential Assets
(Pedersen + rangeproofs + surjection proofs) blind amounts and asset
types per output but require a sidechain.

What BTX takes from Liquid: zero implementable code; one
**documentation point**: BTX exposes amounts/prices/rune-ids fully
on-chain and *cannot* blind them on L1 today. That's the one axis
where Liquid leads BTX.

### tbDEX (Block / TBD) — identity/compliance liquidity (category E)

Unchanged. DIDs + Verifiable Credentials + KYC-credentialed PFIs.
Not in BTX's competitive set — it solves a different problem
(regulated fiat↔crypto liquidity) and is the antithesis of BTX's
permissionless model.

## What's new in BTX since 2026-05-27

### Mainnet-broadcast-proven (2026-06-02)

The envelope carrier is proven on mainnet block 952071. The first BTX
order's reveal tx is `8acf6c70…`, the commit is `199ac251…`, the
`BTX1` magic byte sits at byte 38 of `witness[1]`. Confirmed observed
by 3 third-party operators including mempool.space. Fees: ~568 sats.
v30 `getwalletinfo` API fix in commit `e6e33f0`. (Memory:
`project_btx_b4_broadcast_2026-06-02`.)

This makes BTX **the only fully-on-chain Bitcoin DEX in category A
that has both (a) a real mainnet broadcast track record and (b) an
architecture more modern than Counterparty / Omni**. Counterparty's
volume is real but its design is from 2014. BTX's volume is zero but
its design is from 2026.

### BTX2 crypto foundation + indexer parsing stack (2026-06-02)

(Memory: `project_btx_v2_stack_2026-06-02`.) Three primitives shipped
in pure-Python AND ported to Rust in brk-btx with golden cross-tests:

- **Half-aggregation** per `BlockstreamResearch/secp256k1-zkp@8099999`'s
  `schnorrsig_halfagg`. ~50% asymptotic compression of N independent
  Schnorr sigs. Use case: BATCH_ANNOUNCE compresses N maker offers
  into one envelope.
- **Schnorr adaptor signatures** per Lloyd Fournier's OTVES
  construction. 65-byte adaptor pre-signatures that decrypt to normal
  Schnorr sigs when a secret `t` is revealed. Use case: DLC-style
  CONDITIONAL_ORDER records, oracle-attested orders.
- **BIP-327 MuSig2 KeyAgg** + trusted-aggregator pool signing. Use case:
  maker pools share custody / rotate keys without changing the on-chain
  footprint.

Plus the indexer-side parsing stack (`btx_v2.rs` envelope parser,
`btx_v2_records.rs` per-record decoders, `btx_v2_dispatch.rs`
envelope→typed-record helper).

Neither Counterparty, Omni, nor Light Pools has a comparable
post-Taproot cryptographic stack. They predate or sidestep BIP-340.

### BIP-322 maker attestation, full stack (2026-06-04, today)

(Commits `881b433` → `da1708d` + `brk-btx:1b6e619` + `brk-btx:1cbcfa6`.)
Full-stack BIP-322 P2TR attestation:

- Python primitive (`btx_bip322.py`): simple + full format,
  sign + verify, 21-case adversarial battery, 3/3 + 1/1 + 1/1
  canonical vectors PASS.
- HTTP endpoints (`btxd /api/attest/{challenge,verify}`): defensive
  caps, typed errors, existing Host + CSRF guards.
- Rust verifier (`brk_indexer::btx_bip322`): zero new dependencies,
  6/6 unit tests.
- GUI (`btx_attest.html`): challenge generator + verifier UI.
- CLI (`btx_attest.py`): pipeable, JSON-friendly.
- Runbook (`docs/BTX-attestation-runbook.md`): worked examples for
  Sparrow / Coldcard / Ledger HWI / Core 25+ / Python primitive.

Light Pools is the only other category-A-or-B system that uses BIP-322
operationally. BTX's BIP-322 layer is for **maker identity attestation**
(prove you control your bc1p), not for the book itself (which is on
Bitcoin's relay).

### Cross-validation discipline (ongoing, see `project_btx_xtest_discipline_2026-06-03`)

Every BTX primitive now has at least one canonical external oracle:

| BTX primitive | Cross-validated against | State |
|---|---|---|
| BIP-340 Schnorr | Bitcoin Core CSV vectors + Jonas Nick's `secp256k1lab` | suite PASS |
| BIP-341 Taproot | Canonical wallet vectors | suite PASS |
| BIP-327 MuSig2 KeyAgg | 4 BIP-327 official vectors + a deliberate divergence-finding doc | suite PASS |
| BIP-374 DLEQ | Canonical vectors | suite PASS |
| BIP-380 descriptors + checksum | `rust-miniscript v12.3.7` AND `python-bip380` (Pieter Wuille canonical) | **triple-validated** |
| Schnorr half-aggregation | `secp256k1-zkp` hacspec spec vectors | suite PASS |
| BIP-322 hash + tx + P2TR sign/verify | Canonical `generated-test-vectors.json` | suite PASS |
| Runes decoder | ord (Rust) + Magic Eden (TS) + BTX (Python) | **triple-validated** |

None of the competitors operate this kind of cross-validation
discipline as far as I can find from their public artifacts.

## Where BTX leads now (architecture)

Within **category A** (the only trustless-on-Bitcoin tier):

1. **No native token** — Counterparty needs XCP, Omni needs OMNI; BTX
   needs nothing.
2. **UTXO-native asset state via Runes** — Counterparty/Omni keep
   address-balance ledgers bolted onto Bitcoin.
3. **Atomic single-tx settlement** — Counterparty/Omni use two-phase
   match→pay with a free-option gap.
4. **No relay/server** — the book rides Bitcoin's own relay (Light Pools
   needs a gossip net; Magic Eden a server).
5. **Cryptographic foundation that's actually from 2024-2026** —
   half-agg, adaptor sigs, MuSig2, BIP-322 attestation. Counterparty's
   architecture is from 2014; Omni's `MetaDEx` matching logic predates
   Schnorr entirely.
6. **Cross-validation discipline** — every primitive has at least one
   canonical external oracle; two have three.
7. **Real mainnet broadcast** as of 2026-06-02.

## Where BTX still doesn't lead

1. **Liquidity** — Counterparty has $12/day. BTX has ~568 sats from one
   self-broadcast. That's not zero, but it's not a market. **The
   architectural bet is that liquidity follows the best
   self-custodial Bitcoin-native trading UX**, not the other way around.
2. **Privacy** — Liquid's Confidential Assets blind amounts/asset
   types. BTX cannot blind anything on L1 today and probably never can
   without a soft-fork (BIP-118 ANYPREVOUT, BIP-119 CTV, BIP-443 CCV,
   etc. — all watchlisted but not active).
3. **Smart-contract richness** — Saturn (via Arch) and Light Pools
   (via interactive countersign) can express things BTX can't. BTX's
   answer is that anything genuinely Bitcoin-native should be
   expressible at Bitcoin's L1 layer; the rest is out of scope.

## One-line placement (refreshed)

> Every other system buys a feature by giving something up:
> Counterparty/Omni a token + two-phase settlement;
> Saturn an external VM (Arch Network's verifier set);
> Magic Eden a hosted off-chain book;
> Light Pools an off-chain gossip net + interactive maker;
> Liquid a federation;
> tbDEX identity intermediaries.
> **BTX gives up none of those — it gives up privacy (unavoidable on
> L1) and, for now, liquidity. The mainnet broadcast on 2026-06-02
> proves the architecture works in production. The liquidity question
> is open.**

## Files this refresh references

- `BTX-competitive-landscape.md` (2026-05-27) — the structural baseline.
- `BTX-vs-light-pools.md` — full Light Pools-specific treatment.
- `BTX-B4-case-study.md` — the mainnet broadcast.
- `BTX-v2-spec-2026-06-02.md` — BTX2 design spec.
- `BTX-BIP322-scouting-2026-06-03.md` + amendments — attestation feature.
- Memory entries: `project_btx_b4_broadcast_2026-06-02`,
  `project_btx_v2_stack_2026-06-02`, `project_btx_scouting_cycle_2026-06-03`.

## Sources for this refresh

- [Counterparty (XCP) on Coinpaprika](https://coinpaprika.com/coin/xcp-counterparty/)
- [Counterparty DEX on CoinMarketCap](https://coinmarketcap.com/exchanges/counterparty-dex/)
- [Light Pools — Casey Rodarmor's blog](https://rodarmor.com/blog/light-pools/)
- [Bitcoin Light Pools — Samara AG](https://www.samara-ag.com/market-insights/bitcoin-light-pools)
- [Saturn: The Breakthrough Bitcoin DEX — Arch Network blog](https://www.blog.arch.network/saturn-the-breakthrough-bitcoin-dex/)
- [Saturn documentation](https://docs.saturnbtc.io/)
