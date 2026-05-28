# BTX competitive landscape

*A single reference placing BTX against every system researched this round, by architecture rather
than marketing. Consolidates the scattered findings + the cloned-source reads (ord, Counterparty,
Omni, Magic Eden's runestone-lib, Elements, tbDEX). Companion to `BTX-vs-light-pools.md`,
`BTX-roadmap.md`, `BTX-frontrunning-threat-model.md`, `BTX-utxo-hygiene-audit.md`.*

Date: 2026-05-27.

## BTX's values (the filter everything is judged against)

Nothing off-chain (no relay/server/gossip; book propagates over Bitcoin relay, reconstructed locally) ·
no native token · UTXO-native asset state (Runes) · atomic single-tx settlement (no two-phase
match→pay) · self-custody throughout · Bitcoin L1 only (no sidechain, rollup, or external VM).

## The taxonomy

The honest way to compare "Bitcoin DEXes" is by **where the order book lives** and **what you must
trust**:

| Category | Order book | Settlement | Trust assumption | Systems |
|---|---|---|---|---|
| **A. Fully on-chain, Bitcoin L1** | on Bitcoin L1 | on Bitcoin L1 | Bitcoin consensus only | **BTX**, Counterparty, Omni |
| **B. Off-chain book, on-chain settle** | off-chain (server or gossip) | on Bitcoin L1 | the book host / gossip net | Magic Eden, **Light Pools**, most PSBT marketplaces |
| **C. Sidechain** | on a separate chain | on a separate chain | a federation / alt-consensus | Liquid (Elements) |
| **D. VM / app-chain anchored to BTC** | on an external VM | VM + Bitcoin anchoring | the VM's verifier set | Saturn BTC (Arch Network) |
| **E. Identity / compliance liquidity** | off-chain messages | any rail (often fiat) | credentialed intermediaries | tbDEX |

BTX is in **A**, and within A it is the only one with **no native token**, **UTXO-native** state,
and **atomic single-tx settlement** — see below.

## Each system

### Counterparty — fully-on-chain L1 (the OG)
- On-chain order book as *consensus state*; deterministic protocol matching. **Native token (XCP)**
  for some operations; **address-balance ledger** (not UTXO); **two-phase match→BTCPay settlement**
  with the well-known free-option / non-settlement gap. Live mainnet but **moribund (~$3.5/24h)**.
- **Borrow (in roadmap #1):** the discipline that the book is *consensus state* — a fully-specified,
  deterministic, independently-verifiable book.
- **Reject:** XCP token, address-ledger, two-phase settlement.

### Omni Layer (MetaDEx) — fully-on-chain L1
- `MetaDEx` matches any-property-for-any-property on-chain. Read from
  `omnicore-reference/src/omnicore/mdex.{h,cpp}`: book = `map<property → map<price → set ordered by
  (block, idx)>>`; **exact rational prices** `rational(desired, forsale)` (no floats); partial fills
  via `amount_remaining` + status enum; **a consensus state-hash** (`saveOffer()` → `CHash256`) so
  nodes prove identical books. **Native token (OMNI)**, address-ledger, auto-matching engine
  (`x_Trade`). Dormant.
- **Borrow (roadmap #1, #4):** the price-time book structure, exact-rational prices, and the
  consensus state-hash — the concrete design for BTX's deterministic book. rune↔rune maps onto
  MetaDEx's property-pair model (BTX does it via the addressed `SIGHASH_ALL` path).
- **Reject:** OMNI token, address-ledger, and the `x_Trade` *auto-matcher* (BTX keeps
  taker-initiated atomic fills, no settlement follow-up).

### Saturn BTC — VM/app-chain (not L1)
- Runes trading, but built on **Arch Network — an external VM with verifier nodes** ("smart contract
  functionalities, atomic swaps, liquidity pools via Arch's VM"). So **not** fully-on-chain Bitcoin
  L1; trust extends to Arch's verifier set. Hosted platform.
- **Borrow:** the *idea* of batch/aggregated fills + a clean rune-trading UX (roadmap #2, #5) — but
  as L1 compositions, not from Saturn's architecture.
- **Reject:** the external VM, verifier-set trust, hosted model.

### Magic Eden — off-chain-book marketplace (category B)
- Centralized, hosted; rune/ordinal listings use `SIGHASH_SINGLE|ANYONECANPAY` PSBTs (same settlement
  primitive as BTX's open orders) but the **order book lives on Magic Eden's servers**. Marketplace
  is closed-source.
- **Borrow:** its open-source **`runestone-lib`** (TypeScript) — read `runestone-lib-reference/src/
  rune.ts` and confirmed byte-identical rune spec to ord and BTX (STEPS, `RESERVED`,
  `getMinimumAtHeight`, `commitment`, name↔number). So BTX's rune layer is now **triple-validated**
  (ord Rust + Magic Eden TS + BTX Python). Its `src/indexer/` is a second indexing reference for
  roadmap #1. UX ideas (collection/floor/market pages) inform roadmap #5.
- **Reject:** the off-chain order book and hosted/centralized model.

### Liquid (Elements) — federated sidechain (category C)
- A separate chain secured by **Strong Federations** (functionaries as trusted blocksigners/watchmen).
  Headline tech (read `elements-reference/doc/elements-confidential-transactions.md`): **Confidential
  Assets** — Pedersen commitments + rangeproofs + surjection proofs blind *amounts and asset types*
  (tx graph stays public), ~1,000 vBytes/blinded output, requires secp256k1-zkp + consensus rules.
  Native, consensus-level asset issuance/reissuance.
- **Borrow:** nothing implementable on L1. Two documentation items: (a) a precise **privacy
  limitation** — BTX exposes amounts/prices/rune-ids/terms fully on-chain and *cannot* blind them on
  L1 today; (b) the **native-vs-overlay asset-model contrast** — Elements bakes `(asset, amount)`
  per-output into a *new chain*; Runes overlays the identical idea on *unmodified Bitcoin*. PSET asset
  swaps validate the PSBT-swap pattern BTX already uses.
- **Reject:** the sidechain, the functionary federation, anything needing CT/consensus changes.

### Light Pools (Casey Rodarmor's design) — off-chain gossip book (category B)
- Maker quotes are **BIP-322-signed messages gossiped on a P2P network** (off-chain book); settlement
  on-chain via a co-signed PSBT (maker must countersign each fill → interactive). Snipe-immune
  (signatures commit to all inputs/outputs).
- **Borrow:** the snipe-resistance property — already adopted as BTX's opt-in **addressed-swap mode**
  (`SIGHASH_ALL`). Its BIP-322 spam-resistance idea (low priority — BTX's on-chain publish is its
  spam resistance).
- **Reject:** the off-chain gossip book and the maker-must-be-online requirement (BTX's open `0x83`
  orders are non-interactive). See `BTX-vs-light-pools.md` for the full treatment — BTX is *more*
  Bitcoin-native than Light Pools because it keeps the book on-chain.

### tbDEX (Block / TBD) — identity-liquidity messaging (category E)
- A protocol for *credentialed* fiat↔crypto liquidity: **DIDs + Verifiable Credentials** for identity,
  **PFIs** (regulated intermediaries) as counterparties, off-chain `RFQ → Quote → Order → Close`
  messages. The RFQ carries **KYC credential proofs**. Read `tbdex-reference/hosted/json-schemas/
  offering.schema.json`: payment methods, fiat currency codes, settlement times, `requiredClaims`
  (KYC), cancellation terms.
- **Borrow:** two minor message-field ideas for a future RFQ-discovery layer — **rate-as-ratio**
  (`payoutUnitsPerPayinUnit`) and **min/max ranges** (only useful if BTX adds partial fills). That's
  the entire transferable surface.
- **Reject:** DID/VC identity, KYC credentials, PFI intermediaries — the antithesis of BTX's
  permissionless, anonymous model.

## Where BTX leads (and the one axis where it doesn't)

Within **category A** (the only category that is actually trustless-on-Bitcoin), BTX is the most
Bitcoin-native by every architectural measure:

- **No native token** (Counterparty/Omni require XCP/OMNI).
- **UTXO-native** via Runes (Counterparty/Omni use address-ledgers bolted onto Bitcoin).
- **Atomic single-tx settlement** (Counterparty/Omni use two-phase match→pay with a free-option gap).
- **No relay/server** — the book rides Bitcoin's own relay (Light Pools needs a gossip net; Magic Eden
  a server).
- **Rune layer triple-validated** against ord and Magic Eden's independent implementations.

The single axis where others lead: **privacy** (Liquid's Confidential Assets) — impossible on L1
today — and, more importantly, **liquidity/adoption**. Counterparty has a (tiny, live) market and a
decade of history; BTX has zero users and no mainnet activity. BTX's moat is *technical*
(nothing-offchain, no-token, UTXO-native, atomic), not a *liquidity* moat — and liquidity is what
actually wins DEXes.

## One-line placement

Every other system buys a feature by giving something up: Counterparty/Omni a token + two-phase
settlement; Saturn an external VM; Magic Eden a hosted off-chain book; Liquid a trusted federation;
Light Pools an off-chain gossip net; tbDEX identity/intermediaries. **BTX gives up none of those —
it gives up privacy (unavoidable on L1) and, for now, liquidity.** That is the trade, stated plainly.
