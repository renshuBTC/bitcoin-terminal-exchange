# Bitcoin Terminal Exchange — Component Architecture & Phased Build Sequence

> Companion to *Bitcoin Terminal Exchange — Project Brief (2026-05-22)*. This document resolves the
> Open Decisions and lays out the architecture and build order that follow from them.
> Where a claim depends on facts I cannot verify (asset-protocol maturity, post-2025
> ecosystem state, edge-of-capability Bitcoin scripting), it is **flagged as uncertain**
> rather than asserted.

## Decisions locked (2026-05-23)

| Open decision | Choice | Consequence |
|---|---|---|
| Packaging | **One-installer bundle** (Core + modules) | App-layer only; no fork maintenance burden; you own the distribution. |
| Order-book transport | **Pure chain-reconstructed** | Maximal "no externality"; pays the latency/cost tax in full. |
| Counter-asset | **Rune-issued stablecoin** (BTC-backed preferred) | Token layer is on Bitcoin L1 (nothing-offchain rails); only the *peg* is trusted, and that lives in the asset's issuer — a user opt-in, not a BTX dependency. **FINALIZED + proven, see `BTX-phase5-design.md`.** |
| Node model | **Full node** | Required for a complete local indexer; pays the IBD/disk/bandwidth cost. |

These four are coherent and all preserve "nothing offchain": three maximize trust-minimization
and zero external infrastructure, and the counter-asset is a **Rune** so even the stablecoin's
*token layer* stays on Bitcoin L1 — the only trusted element is the peg, which is a property of
the chosen asset (opt-in, like any DEX vs. USDT), not of BTX's rails. (A fiat/Liquid/Fedimint
stablecoin would fail this — its token layer is itself offchain/federated.)

## The one tension to keep visible

The brief's load-bearing constraint #2, quoted verbatim:

> "The stablecoin ISSUER is the one irreducible middleman (trust the peg + reserves; chain
> can't verify backing)."

So the honest trust model of BTX is:

- **Trustless** about *settlement* (atomic on-chain swap) and *custody* (your own keys, your own node).
- **Trust-minimized** about the *order book* (your own indexer reconstructs it from chain data — no relay to trust).
- **Trusted** about exactly one thing: the *stablecoin peg and reserves*. The indexer can prove a UTXO holds N units of asset X per the asset protocol's rules; it cannot prove asset X is backed by anything.

Everywhere below, the stablecoin dependency is isolated behind an "Asset Layer Adapter" so
this trust boundary stays in one place. **Resolved: the backend is Runes** (a rune-issued,
BTC-backed-preferred stablecoin). The adapter is `ord` used as a read-only, chain-derived rune
oracle (`btx_wallet.ord_rune_balance`) — so the peg is the only trusted element and it lives
in the asset, not in BTX's rails. PROVEN end-to-end on Bitcoin Core v29.1 (see
`BTX-phase5-design.md`).

---

## 1. Component architecture

BTX is a bundle of an unmodified Bitcoin Core node plus BTX-specific modules that talk
to it over RPC, all shipped in one installer with one GUI. Nothing here touches consensus.

### 1.1 Bitcoin Core node (unmodified, vendored)
- `bitcoind` run as a full node with transaction indexing enabled (the indexer needs full
  block/tx visibility).
- Exposes: block/tx data, mempool, the descriptor wallet RPCs, and the mining RPCs
  (`getblocktemplate` / `submitblock`).
- **Note (from brief):** Core *"removed the built-in CPU hasher,"* so BTX does not mine
  hashes itself — it orchestrates templates and submits solved blocks. Solo-mining BTC is a
  lottery; the GUI should present it as such, not as income.

### 1.2 Indexer / Order-Book Engine  ← the heart of BTX
This is the novel component and the one squarely in your wheelhouse (BRK fork +
bitcointerminal indexing experience).
- Walks every block (and optionally the local mempool) and parses BTX **order artifacts**
  out of transactions.
- Maintains a persisted, queryable **order book**: open orders, implied BTC/asset price,
  depth, and an event log of fills and cancels derived from UTXO spends.
- Handles reorgs: orders and fills must be revertible when a block is orphaned, because the
  book *is* a projection of chain state.
- Serves the book to the local GUI only. There is no network surface — by design.

### 1.3 Asset Layer Adapter (isolates the stablecoin dependency)
- Parses the chosen asset protocol's own encoding so BTX knows which UTXOs carry how many
  stablecoin units. **Uncertain:** the maturity and exact indexing rules of a USD-stablecoin
  *on Bitcoin* as of 2026 are beyond what I can verify from the brief alone (my reliable
  knowledge ends May 2025). Treat the specific protocol — Runes vs Taproot Assets vs Liquid —
  as a pluggable backend, and confirm the live state before committing.
- Single, swappable trust boundary (see "The one tension" above).

### 1.4 Self-custody wallet (asset-aware)
- Wraps Core's descriptor wallet for BTC, and adds asset-UTXO tracking via the Asset Layer
  Adapter (Core's wallet will not natively understand stablecoin balances).
- Builds and signs the PSBTs for both maker and taker swap roles.
- Keys never leave the machine.

### 1.5 PSBT Swap Settlement
- A trade settles as a **single atomic Bitcoin transaction** that moves BTC one way and the
  asset the other. If it confirms, both legs happened; if not, neither did.
- Built on partial-signing (the same mechanism Ordinals/Runes PSBT markets use): the maker
  pre-signs their side such that a taker can add their side without invalidating the maker's
  signature.

### 1.6 Mining controls
- Thin orchestration over `getblocktemplate` / `submitblock`; binds to an external hasher
  since Core no longer ships one. Solo only (no pool middleman), consistent with the thesis.

### 1.7 Unified GUI (bundled, not a bitcoin-qt fork)
- A BTX front end that talks to Core and the modules over RPC, presenting node status,
  wallet, mining controls, and the DEX panel (fed only by the local indexer).
- Because we chose **bundle over fork**, this is a BTX app alongside Core — not a patched
  `bitcoin-qt`. That is what removes the perpetual rebase burden.

### 1.8 Installer / packaging
- One installer per OS that lays down `bitcoind`, the BTX modules, the indexer's datadir,
  and the GUI, with first-run config (enable txindex, point modules at the node).

---

## 2. The load-bearing piece: order encoding + chain-reconstructed settlement

This is where BTX is genuinely unprecedented (per the brief's prior-art section, on-chain
order books — Counterparty DEx, Omni MetaDEx — were *"largely ABANDONED"*). It is also the
single biggest research risk, so it must be prototyped before anything else is built.

### 2.1 What an "order" physically is
An order is **a funded UTXO plus on-chain metadata**:
- The **offer UTXO** holds the thing being sold (BTC, or stablecoin units).
- **Metadata** — asset id, side, price, amount, expiry — carried in an on-chain artifact
  (e.g. an `OP_RETURN` output, ~80-byte budget, or a Taproot witness/annex if more room is
  needed). `OP_RETURN` is provably unspendable, so it carries *metadata only*; it is never
  the offer UTXO itself.
- The book is reconstructable by any node purely from confirmed chain data: open order =
  metadata artifact whose offer UTXO is still unspent; fill/cancel = that UTXO spent.

### 2.2 The crux problem (flag this loudly)
"Pure chain-reconstructed" means **the entire order, including whatever the taker needs to
complete the swap, must be discoverable on chain** — there is no relay to pass a pre-signed
PSBT around. There are two candidate mechanisms, and choosing/proving one is Phase 0:

- **(a) Script-enforced offer.** The offer UTXO is locked so it can only be spent by a
  transaction that simultaneously pays the counter-asset to the maker. Because Runes /
  Taproot Assets settle *on the same Bitcoin transaction*, a single Bitcoin tx can move both
  legs — but having Bitcoin Script *enforce* the counter-leg atomically may exceed today's
  non-covenant scripting. **Uncertain — must be proven on regtest/signet, not assumed.**
- **(b) Pre-signature published on chain.** The maker's partial signature (SIGHASH flags
  chosen so a taker can append their side) is embedded in an on-chain artifact, letting any
  indexer reconstruct a completable PSBT. More clearly feasible today, larger on-chain
  footprint.

I am not confident which is viable without a spike, and I will not pretend otherwise. **The
deliverable of Phase 0 is to answer this empirically.**

### 2.3 Properties you are signing up for (brief, constraint #3, verbatim)
> "~10-min latency, fees per order/cancel, per-node mempool (no global state), no
> price-time-priority matching (first spender wins; miner/fee auction)."

BTX is a **slow swap board, not a live CLOB.** The GUI must set this expectation:
settlement in blocks not milliseconds, a fee to post and a fee to cancel, and "first valid
spender wins" rather than time priority. This is the cost of zero externality, and it is
exactly why the 2014-era on-chain books were abandoned — so the product framing has to make
the no-middleman property feel worth it.

---

## 3. Phased build sequence

Ordering principle: **build the riskiest, most novel thing first.** The node, wallet, and
mining are *"largely ALREADY in Bitcoin Core"* (brief) — that is integration work, not
invention. The order encoding + atomic swap is invention, so it goes first.

### Phase 0 — Swap spike (de-risk THE hard problem)  ·  *highest priority*
- On **regtest then signet**, two parties, command-line only, no GUI.
- Prove a **BTC ↔ asset atomic swap settles in one transaction**, and that the offer is
  **reconstructable purely from chain data** with no off-chain message passing.
- Decide mechanism (a) vs (b) from §2.2 *empirically.*
- **Exit criterion:** a second machine, given only the chain, can find the order and complete
  the swap. If this can't be done, the "pure chain-reconstructed" decision must be revisited
  before any further investment.

### Phase 1 — Indexer / order-book engine
- Extend the BRK fork to parse order artifacts, build and persist the book, compute implied
  price, and track fills/cancels via UTXO spends. Handle reorgs.
- Reuses your existing indexing expertise directly.
- **Exit criterion:** replay a regtest chain of orders and get a correct book + price.

### Phase 2 — Asset-aware wallet + PSBT flows
- Asset-UTXO tracking via the Asset Layer Adapter; maker/taker PSBT construction integrated
  with Core's descriptor wallet.
- **Exit criterion:** wallet can post an order and take an order end-to-end on signet.

### Phase 3 — Bundle + unified GUI
- One installer; GUI surfaces node status, mining controls (`getblocktemplate`/`submitblock`),
  wallet, and a DEX panel reading from the local indexer.
- **Exit criterion:** a non-developer can install once and complete a signet trade from the GUI.

### Phase 4 — Hardening
- Fee/expiry handling, reorg handling in the book, cancel semantics, local mempool view,
  partial fills, dust/edge cases.

### Phase 5 — Counter-asset finalization + regulatory — DONE (2026-05-26)
- **Counter-asset finalized = a Rune-issued (BTC-backed-preferred) stablecoin**; Asset Layer
  Adapter backend = `ord` as a read-only rune oracle. BTX mints its own counter-asset rune
  with its own primitives (`btx_etch.py`) — no ord wallet, latest Core (v29.1). Settlement
  edicts the rune to the taker; maker-sign refuses orders not exactly backed. **Proven live
  end-to-end on regtest** (etch `a8afd8fa…`, rune `131:1`, swap `d8cf9f49…`). Full rationale +
  proof: `BTX-phase5-design.md`; reproduce via `BTX-phase5-spike-runbook.md`.
- **Regulatory (MAS): PAUSED by Renshu — do not treat as a next step.** Note: using a
  *third-party* rune stablecoin means BTX is *not issuing* one, which avoids the stablecoin-
  issuance trigger the brief flagged (issuing your own would re-introduce it). Brief #7 verbatim:
  > "non-custodial BTC/asset facilitation can still hit MAS DPT licensing (SG); issuing a
  > stablecoin triggers MAS's stablecoin framework. Real lawyer early. (Not legal advice.)"

---

## 4. "THE question" the brief insists on answering first

> "what does forking Core add that a standalone app (Bisq/RichSwap/Xverse) does not?"

Since we chose **bundle, not fork**, reframe it as: *what does BTX add over existing
standalone apps?* Honest answer:

- The genuine differentiator is **zero external network at all.** Bisq/RoboSats coordinate
  off-chain (Nostr / their own network); Runes/Ordinals markets relay orders off-chain and
  only settle via on-chain PSBT. BTX's book lives entirely on chain and is rebuilt locally —
  no relay, no coordinator, no server.
- The secondary differentiator is **packaging**: full node + self-custody wallet + solo
  mining + DEX in one self-hosted install.

The honest counterpoint, which the product must answer: the market has *repeatedly tried*
on-chain order books and abandoned them for the latency/cost reasons in §2.3. BTX's bet is
that there is a user who values "no middleman, no server, runs entirely on my own node" more
than they value speed and low fees. **If that user doesn't exist, the chain-reconstructed
decision is the thing to reconsider — not the architecture.** That is why Phase 0 is a
spike and not a commitment.

---

## 5. Constraint cross-check

| Brief constraint | How this architecture honors it |
|---|---|
| 1. App/indexer layer, not consensus | Core is vendored unmodified; all BTX logic is RPC-side modules. |
| 2. Counter-asset can't be fiat; issuer is the middleman | **Rune-issued stablecoin** via the Asset Layer Adapter (ord oracle): token layer on L1, only the peg is trusted and it lives in the asset (opt-in), not BTX's rails. |
| 3. Book can't ride P2P; chain-reconstructed = slow swap board | Indexer rebuilds the book locally; GUI sets block-latency expectations. |
| 4. Strong privacy contradicts the indexed book | Chosen transparency; **no privacy features** layered on the book. Stated, not hidden. |
| 5. Quantum-proofing/privacy are consensus changes | Out of scope; BTX is app-layer and ships no consensus change. |
| 6. Won't merge upstream | Bundle = own distribution by design. |
| 7. Regulatory (MAS) | Phase 5 gated on counsel; flagged to engage early given career context. |

## 6. Honest uncertainties
1. ~~Whether mechanism §2.2(a) is achievable in current Bitcoin Script~~ — **RESOLVED:** took path
   §2.2(b) (maker pre-signature published on-chain), proven on regtest/signet and public signet.
2. ~~The live maturity of a USD-stablecoin on Bitcoin in 2026~~ — **RESOLVED:** rune-issued stablecoins
   exist (USDh/Hermetica, UNIT/Ducat) and the rune-as-counter-asset mechanism is proven end-to-end
   (Phase 5). The peg remains the asset issuer's trust (opt-in), out of BTX's scope by design.
3. **Whether the target user exists** — STILL OPEN. The product-level bet behind the whole
   chain-reconstructed choice (§4): the build is proven, but demand for maximal-sovereignty /
   nothing-offchain trading over speed/UX is unvalidated. This is the real remaining question.
