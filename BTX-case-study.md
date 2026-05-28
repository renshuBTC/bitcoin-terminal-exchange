# BTX — a server-less, on-chain order book for Bitcoin

*A case study in Bitcoin protocol engineering: designing an on-chain DEX primitive, implementing the
cryptography from scratch against the official BIP test vectors, and proving it end-to-end on a public
network.*

---

## TL;DR

BTX is a **server-less order book for Bitcoin**: a maker pre-signs an offer, publishes it **as an
ordinary on-chain transaction**, and any node's own indexer reconstructs the live order book by reading
the chain — **no exchange, no relay, no server, no token, no escrow**. Settlement is a single native
Bitcoin transaction; trust is minimized to Bitcoin itself ("first valid spender wins").

I built the full stack — the on-chain artifact format, a Rust indexing/serving layer inside a real
Bitcoin indexer (BRK), the maker/taker tooling, and a from-scratch BIP340/BIP341 implementation — and
proved it **end-to-end on public signet**: an order published under default relay policy propagated
across foreign nodes, was mined by an independent signer, and was then reconstructed from the chain and
served live by my own node.

I'm equally clear-eyed about what it *isn't*: this is not a novel category, and it has no economic moat
(see [Honest positioning](#honest-positioning)). It's a rigorous proof-of-skill and a working
sovereign-DEX implementation, not a startup.

---

## Since the initial signet proof (2026-05-27)

The base primitive (publish → reconstruct → fill) grew into a fuller DEX, each piece built through
BTX's nothing-offchain values and proven, not just coded:

- **Batch fills** — one taker sweeps N maker offers in a single transaction. The maker's
  `SIGHASH_SINGLE|ANYONECANPAY` pre-signature commits only to its own offer-input + payout-output, so
  pre-signatures *compose*; the offline test recomputes the real BIP143 sighash at each offer's true
  input index to prove a pre-sig stays valid at position *k*, not just position 0.
- **Rune↔rune swaps** — asset-for-asset, not just asset-for-BTC. This is impossible as an open order
  (the maker can't commit to an inbound-rune edict that lives in a taker-controlled OP_RETURN), so it
  rides the addressed `SIGHASH_ALL` path where the maker signs — and verifies — the whole transaction.
  Proven live on regtest: maker received the counter-rune, taker received the offered rune + change,
  ord-confirmed.
- **A consensus-hashed, verifiable book** — the reconstructed book now carries an order-set-independent
  content hash, computed natively in the Rust indexer (`/api/v1/btx/book-hash`) and proven byte-for-byte
  identical both to a Python reference (golden vector) and to a *fully independent* Python chain
  reconstruction on live data. This is the property that makes an on-chain DEX *trustworthy*, not merely
  on-chain: any honest indexer reproduces the same book and can prove it.
- **A trading terminal** (`btx_trade.html`) — depth view, divisibility-normalized prices, multi-select
  batch fill, a rune↔rune panel, and a live "indexers agree" badge.

Two findings worth calling out, because they show the work was adversarial, not just happy-path:

- A real bug in the runestone encoder (`runestone_spk` emitted a *delta* tx index across a rune-block
  change; a negative delta looped `leb128` forever) — found while building rune↔rune, fixed, and now
  regression-tested.
- A maker-safety hole in the rune↔rune verifier: an edict whose output index exceeds the output count is
  a *cenotaph* in ord (it burns all input runes), which the decoder didn't flag — so a taker could have
  griefed the maker into burning their offered rune. The verifier now rejects it; regression-tested.

And the one competitive gap versus Casey Rodarmor's Light Pools — open orders being fill-race-able — was
resolved *analytically*: it is logically irreducible (an open order that anyone can fill is one anyone
can outbid to fill), no Bitcoin covenant can fix it, no principal is ever at risk, and the addressed mode
already covers the snipe-sensitive case. See `BTX-frontrunning-threat-model.md` §7.

---

## The idea

Every Bitcoin DEX needs two things: a way to **advertise** orders and a way to **settle** them.
Settlement on Bitcoin is a solved problem — a maker signs their input with
`SIGHASH_SINGLE | ANYONECANPAY`, committing to "spend my offer UTXO, and you must pay me exactly this
at output 0," while leaving the rest of the transaction open for a taker to complete. This is the same
primitive every Ordinals/Runes marketplace uses.

The *advertising* layer is where designs differ. Centralized exchanges use a server; modern
"serverless" DEXs (e.g. Orders.Exchange) distribute orders over **Nostr relays**. BTX asks a
narrower question: **what if the order book itself lived on the Bitcoin blockchain?** Then the book
inherits Bitcoin's own availability and censorship-resistance — there is no relay or server to prune,
drop, censor, or take offline. Nothing to trust but the chain.

## How it works

1. **Maker pre-signs.** The maker signs a partial transaction `[offer-input] → [payout-output]` with
   `SIGHASH_SINGLE | ANYONECANPAY` (sighash byte `0x83`). The signature commits to *exactly* output 0
   (price + payout script); everything else is left open.
2. **Publish on-chain.** The signed offer is serialized into a compact ~207-byte `BTX1` artifact and
   published on-chain via one of **two interchangeable carriers**:
   - an `OP_RETURN` output, or
   - a **Taproot witness envelope** — an inscription-style commit→reveal that carries the artifact in
     *witness* data (so it needs no relaxed `-datacarriersize` and relays under default policy).
3. **Reconstruct from chain.** The node's indexer scans each block, finds the `BTX1` artifact (in an
   output script *or* a revealed tapscript), looks up the offer UTXO, **verifies the maker signature
   against it**, and records the order in a persistent, reorg-safe store with
   `OPEN / FILLED / CANCELLED / EXPIRED` state.
4. **Serve & settle.** The reconstructed book is served read-only over HTTP. A taker completes the
   half-signed transaction and broadcasts; the swap settles **atomically in one transaction**.
   Spending the offer UTXO is what marks the order filled or cancelled — consensus-enforced, because
   the maker's `SINGLE|ANYONECANPAY` signature makes any tampering with output 0 invalid.

```
maker pre-signs  ──►  BTX1 artifact on-chain  ──►  every node's indexer
(SINGLE|ACP)          (OP_RETURN | witness)        rebuilds the book from chain
                                                          │
                            taker completes the half-signed tx ──► atomic settlement (1 txid)
```

## What I built

**On-chain protocol layer (Rust, inside the BRK Bitcoin indexer):**
- The `BTX1` artifact parser + order-book state machine, and a **persistent, reorg-safe order store**
  (fjall-backed) wired into the indexer's commit/rollback path.
- **Witness-envelope extraction** — reassembling the artifact from a Taproot script-path reveal,
  mirroring the publisher byte-for-byte.
- A read-only HTTP API (`/api/v1/btx/{orders,groups,history,swaps}`) and a standalone web UI that
  renders the book with no server-side state.

**Cryptography, implemented from scratch and validated against the standards:**
- A dependency-free **BIP340 Schnorr** signer/verifier and the **BIP341 Taproot script-path sighash**,
  built on a minimal secp256k1 engine.
- Verified against the **official Bitcoin BIP test vectors**: all BIP340 signing/verification vectors
  reproduce exactly, and the BIP341 `TapSighash` matches the published key-path vectors across every
  sighash type (`DEFAULT/ALL/NONE/SINGLE` and their `ANYONECANPAY` variants).
- A byte-accurate **Runes runestone** encoder for the asset leg, validated against canonical `ord`.

**Tooling & tests:** maker/taker CLIs over Bitcoin Core's wallet (the node signs; BTX never sees a
private key), an aggregate offline regression suite, and a one-command live-lifecycle harness covering
both carriers.

## What I proved (with evidence)

| Layer | Evidence |
|---|---|
| Crypto correctness | BIP340 + BIP341 vectors: **all pass** (offline, exact byte match) |
| Indexer unit tests | `cargo test -p brk_indexer btx`: **15/15 pass** |
| Offline integration | aggregate suite: **14/14 pass** (artifact round-trip, both carriers, reveal construction) |
| Live lifecycle (regtest) | publish → serve → taker-fill → **FILLED**, for both carriers |
| Real network format | full lifecycle re-run on a **custom signet** (real signer-commitment coinbase, relay limits) |
| **Public-network proof** | a witness-envelope order published on **public signet** under **default relay policy** propagated to foreign nodes and was **mined by an independent signer** |

The public-signet proof is the one that matters most: it shows the design works on a real
multi-node network, not just a single node I control.

- Reveal transaction: `60e969a3ad65a182faabf8e61f0902aeb607b50c53f7ca1be56e483faf9a63e3`
- Mined in block **305,837**; the order is then reconstructed from that block's witness data and served
  live (offer `1ffebb2f…:0`, announce height 305,837).

A telling detail surfaced during the test: the faucet's own payout transaction (which used *multiple*
`OP_RETURN` outputs) was **rejected** by my v29.1 node's mempool as non-standard — exactly why BTX
carries orders in a single witness-envelope transaction rather than a multi-output one. The design
choice was vindicated in the wild.

*(Built and tested against Bitcoin Core v29.1; Rust crypto pinned to `bitcoin` 0.32.9 / `secp256k1`
0.29.1.)*

## Skills this demonstrates

- **Bitcoin protocol depth:** `SIGHASH` flags, Taproot/BIP340/BIP341, PSBT-style pre-signed settlement,
  witness/inscription envelopes, Runes encoding, signet mechanics, and relay/standardness policy.
- **Cryptographic implementation:** Schnorr signing and the Taproot sighash written from first
  principles and **proven against the official test vectors** — not glued together from a library.
- **Real-codebase Rust:** additive, reviewable changes inside a production-grade Bitcoin indexer
  (custom store, reorg safety, an HTTP API surface) without touching consensus logic.
- **Engineering rigor:** a verification ladder from unit tests → offline vectors → live regtest →
  custom signet → **public signet**, with honest accounting of what each step does and doesn't prove.
- **Technical judgment & candor:** an accurate read of where this sits in the landscape, below.

## Honest positioning

BTX is **not** a novel category, and saying so is the point — credibility comes from accuracy.

- **The on-chain-reconstructed order book was built in 2014.** Counterparty (and Omni) embedded orders
  in Bitcoin transactions and had every node deterministically rebuild the book — Counterparty even had
  *protocol-level matching*, which is stronger than BTX's first-valid-spender model.
- **The settlement primitive is industry-standard.** Pre-signed `SIGHASH_SINGLE|ANYONECANPAY` PSBTs are
  what every Runes/Ordinals marketplace already uses.
- **A Nostr-based book delivers "no server" more cheaply.** It's free and instant; BTX pays an
  on-chain fee per order *and* per cancel, needs confirmations, and is limited by block space.

BTX's **one genuine differentiator** is *where the book lives*: orders are mainchain artifacts, so
the book's availability and censorship-resistance equal Bitcoin's — no relay or token in the trust
path. That's a real edge, but a **narrow** one: it only matters to a maximal-sovereignty user willing
to pay on-chain costs for it. BTX is a proven, honest implementation of that specific point in the
design space — and a demonstration that I can take a protocol idea from spec to a public-network proof.

---

*Research preview. Proven on regtest, custom signet, and public signet against Bitcoin Core v29.1; not
production-hardened, no mainnet or economic testing. Source available on request.*
