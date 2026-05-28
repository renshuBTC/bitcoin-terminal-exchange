# BTX — Attack/Defense Matrix (Layer 0 principals)

*Per-principal attack ledger grounded in the actual code. For each attack: the principal who mounts it,
the concrete mechanism, the defense the code actually provides (no invented mitigations), and a verdict
of **prevents / mitigates / accepts / doesn't address**. Complements `BTX-threat-model.md` (Layer 0
principals + trust boundaries) and `BTX-frontrunning-threat-model.md` (open-order sniping). Verdicts
trace to code, not aspiration. Date: 2026-05-27.*

Throughline: BTX **prevents** everything that would let a counterparty *steal* (forge a maker sig,
make a taker overpay, fill a fake order, double-fill a UTXO) and **accepts** the standing-offer hazards
intrinsic to a self-custody, no-escrow, on-chain order book, offering the **addressed mode**
(`SIGHASH_ALL`) as the opt-out where prevention is wanted. The only genuinely unaddressed items are
economic/relay (anti-spam stake; mempool pinning), not consensus — and are honestly out of scope for the
current code.

---

## (a) Front-running of unfilled open orders by fee-bidding takers

**Principals:** Taker, Mempool attacker, Miner (the "ultimate sniper" who self-fills the public input).

**Attack:** A maker's open offer commits only `(offer-input-0, payout-output-0)` via
`SIGHASH_SINGLE|ANYONECANPAY` (0x83), so anyone can lift the maker's public input into their own fill.
Taker A broadcasts a fill; B (or a miner) sees it in the mempool and broadcasts a competing fill
spending the same public input at a higher fee.

**Code defense:** For **open** orders, none — inherent to the public 0x83 model (`snipe / fill-race` in
the threat model). What the code does provide: (1) the maker is price-protected regardless of who wins —
the 0x83 sig forces `output0 == (price, payout_spk)`, re-checked in `verify_maker_sig`, so the maker
still receives `price`; the loser is a *taker*, not the maker; (2) the **addressed mode**
(`cmd_addressed_propose/countersign`, `SIGHASH_ALL`) is the opt-in snipe-resistant path — the maker
signs the whole tx, so no input/output substitution is possible; (3) taker funding RBF-signals
(`0xfffffffd`) so a taker can compete on fee.

**Verdict:** **Open orders: ACCEPTED** (by design; profitable to the sniper only on mispriced orders;
maker is never underpaid). **Addressed mode: PREVENTS.**

## (b) Griefing via dust orders that bloat the book without economic stake

**Principal:** Maker (spam).

**Attack:** Publish many tiny orders to bloat the served book.

**Code defense:** (1) **dust floor** — `cmd_maker_sign` rejects `price < 546` (`btx_wallet.py`), so no
sub-dust orders; (2) **every order must be backed by a real, unspent UTXO the spammer controls** — the
indexer admits an order only if `verify_maker_sig` validates against the looked-up offer UTXO
(`try_open_order`), so orders not backed by the spammer's own coins are rejected and each order needs a
*distinct* offer UTXO; (3) **each announce is an on-chain tx** (OP_RETURN or envelope commit/reveal)
costing a real fee; (4) advisory **`expiry`** ages orders out at read time. There is **no** bond/min-stake
beyond the offer UTXO and **no** rate-limit on announces.

**Verdict:** **MITIGATED** (real per-order cost: a funded UTXO + on-chain announce fee + dust floor;
expiry ages stale entries). **Not fully prevented** — a well-funded attacker can still publish many
genuine orders.

## (c) Maker setting prices designed to be sniped during volatility

**Principal:** Maker (self-inflicted / free-option risk), exploited by Taker/Miner.

**Attack:** A standing open order at a price that becomes stale during a price move is hit at the
now-favorable-to-taker price before the maker can react.

**Code defense:** The maker can (1) **cancel** by spending the offer UTXO before a fill confirms;
(2) **RBF-reprice** the *unconfirmed* announce; (3) set an **`expiry`**; (4) use **addressed mode** to
avoid standing a public option at all. A *confirmed* open order remains a live option until cancelled,
and finality is confirmation-only.

**Verdict:** **ACCEPTED** (the free-option / "renege" risk is inherent to standing pre-signed offers),
**mitigated** by cancel / RBF-reprice / expiry / addressed mode. A risk the maker chooses, not a
third-party theft — the maker always receives ≥ `price`.

## (d) Indexer operators serving inconsistent book states to different clients

**Principal:** Indexer operator.

**Attack:** Censor orders, inject fake orders, or report wrong prices — differently to different clients.

**Code defense:** (1) **an injected/fake order can't be filled** — a taker who acts runs `taker-fill`,
which re-verifies the maker sig against the client's own `gettxout` before building (`cmd_taker_fill`),
so a forged order fails; (2) the **consensus `book_hash`** (`/api/v1/btx/book-hash`, order-set-independent,
byte-identical across honest indexers) lets a client *detect* a divergent book by self-hosting or
cross-checking hashes; (3) the operator **cannot** forge a maker signature, make a taker overpay, or
steal funds. Residual: a **passive viewer** who only reads the served book trusts it.

**Verdict:** **Acting takers: PREVENTED** (re-verification). **Passive viewers: ACCEPTED but DETECTABLE**
(the operator can lie to a viewer; the consensus hash is the detection mechanism, but the code doesn't
*force* a client to cross-check).

## (e) Cancellation races between maker and taker

**Principals:** Maker vs Taker.

**Attack:** The maker broadcasts a cancel (spend the offer elsewhere) while a taker broadcasts a fill
(spend the offer to the maker payout) — both spend the *same* offer UTXO.

**Code defense:** Consensus guarantees the offer UTXO is spent **at most once**, so exactly one confirms
— no double-resolution possible. The indexer classifies whichever wins by `output0`:
`output0 == (price, payout_spk)` → FILL, else → CANCEL (`OrderBook::resolve_spend` /
`index_block_orders` pass 2), and the `status == ST_OPEN` guard makes the transition fire **exactly
once**. The winner is decided by fee/mining, like any RBF race.

**Verdict:** **ACCEPTED** (the race is inherent to a standing pre-signed offer; finality is
confirmation), **correctly resolved** by consensus + the indexer's deterministic output-0
classification. No double-spend, no ambiguous book state.

## (f) Reorg-based double-fill / re-broadcast against a now-spent UTXO

**Principals:** Miner, reorg.

**Attack (as stated):** A fill confirms, gets reorged, and is re-broadcast against the offer UTXO.

**Code defense / reality:** A true **double-fill is impossible** — one UTXO is spent once; if a reorg
orphans the fill, the offer becomes *unspent again*, so re-broadcasting the same fill re-confirms the
*same* fill (not a second one). If the fill is **not** orphaned, re-broadcast is rejected (UTXO already
spent). The real reorg risk is **"reorg-recapture of a shallow fill"**: on the new chain a *different*
spend (a snipe or the maker's cancel) wins. Defenses: (1) the indexer's **reorg rollback** re-opens
orders whose fill/cancel was orphaned and re-applies the new chain's spend on replay (`btx_rollback_plan`
+ `revert_to`); (2) the **no-resurrection guard** (PUBLISH only inserts when no terminal/earlier record
exists) ensures a stale re-announce can't resurrect a terminal order; (3) the terminal shows a
**confirmations badge** so a taker can wait for depth before treating a received rune as settled.

**Verdict:** **Double-fill: PREVENTED by consensus** (one UTXO). **Reorg-recapture of a shallow fill:
ACCEPTED** (standard Bitcoin finality), **mitigated** by the indexer's correct rollback/replay + the
confirmations display. The book never enters an inconsistent state across the reorg.

## (g) Mempool pinning to prevent cancellation from confirming

**Principals:** Mempool attacker, Relay-path attacker.

**Attack:** Pin or suppress the maker's cancel tx (BIP125 rule-3 / package-limit pinning, or relay-path
suppression) so the cancel can't confirm, keeping the order fillable longer than the maker intends.

**Code defense:** Partial. `btx_wallet cancel` now builds an **RBF-signaled, fee-bumped** spend of the
offer UTXO (`--fee-rate` sat/vB; `fundrawtransaction replaceable=true`), so the maker can out-bid a
racing fill (which RBF-signals its taker input) under BIP125 — but there is **no anti-pinning measure**
(no CPFP/package construction), so a deliberately *pinned* low-feerate-high-absolute-fee tx still raises
the maker's cost to displace it (see (h)). The threat model lists the relay-path attacker's ability to
"widen the snipe/double-spend window" by suppressing fills/cancels, and marks eclipse as standard-Bitcoin
scope.

**Verdict:** **DOESN'T ADDRESS** (the pinning *primitive* is general L1 mempool-policy / relay-path,
inherited from Bitcoin; BTX provides a fee-aware cancel but no pinning defense). No principal at risk —
the offer UTXO is spent at most once.

## (h) Fill-pinning to LOCK an order (the mirror of (g))

**Principal:** Mempool attacker.

**Attack:** Broadcast a VALID fill (it pays output-0 = the maker price, so it's a real fill) that is
deliberately hard to replace — a large, low-feerate, high-absolute-fee tx (BIP125 rule-3 pin). It
occupies the offer UTXO in the mempool without confirming, so no other taker can cheaply RBF it AND the
maker must out-bid the pin's absolute fee to cancel. The order is locked: it neither fills (the pin won't
confirm) nor cheaply cancels.

**Code defense:** None specific — same class as (g). The maker can still recover by out-bidding
(`btx_wallet cancel --fee-rate`), and the pin is costly to the attacker (a high-absolute-fee tx risks
actually confirming, at which point the pinner just bought at the maker's price — no theft).

**Verdict:** **DOESN'T ADDRESS** (general L1 mempool-pinning; principal-safe, liveness/cost harm only;
offer UTXO spent at most once).

## (i) Indexer indexing-cost DoS via artifact spam

**Principal:** On-chain spammer (anyone who can pay tx fees).

**Attack:** Put MANY `BTX1`-MAGIC outputs (or witness envelopes) in one cheap tx. Each forces the indexer
into a candidate parse + a `gettxout` lookup + a `verify_maker_sig` (ECDSA) during the block scan — even
though they all fail verification and never enter the book. The *work* of rejecting spam is not bounded
per-tx/per-block.

**Code defense:** The parser is bounds-safe and panic-free (fuzz-tested), and forged/unbacked artifacts
are rejected (so spam never bloats the *book* — that is (b)). But there is **no per-block cap on the
number of BTX candidates processed**, no cheap pre-filter before the `gettxout`/sig-verify, and no rate
limit. [VERIFY: the concrete per-artifact cost and whether a malicious block can materially slow indexing
has not been measured.]

**Verdict:** **DOESN'T ADDRESS / [VERIFY]** (resource-exhaustion on the indexer, distinct from book-bloat;
likely Low — each candidate is one RPC + one ECDSA verify — but unbounded in principle; needs measurement).

## (j) Reveal-suppression on the two-phase envelope publish

**Principals:** Relay-path attacker; also a plain fee/mempool stall.

**Attack:** The envelope carrier publishes in two txs (commit → reveal). Letting the COMMIT confirm but
suppressing/delaying the REVEAL strands the commit funds and keeps the order out of the book until the
reveal confirms.

**Code defense:** The commit output is spendable ONLY by the ephemeral reveal key (Class-B), so funds are
not *stolen* — only delayed. `btx_envelope_publish` persists a recovery record (`--state-file`,
`0o600`) so the maker re-builds and re-broadcasts the reveal. (Adjacent, low-severity: weak `os.urandom`
could let the ephemeral commit key be predicted and the commit dust stolen before the reveal — bounded to
the commit amount.)

**Verdict:** **MITIGATED** (recoverable via `--state-file`; no principal loss — Class-B blast radius is
the commit dust; liveness/griefing only).

---

## Summary

| Attack | Principal(s) | Verdict |
|--------|--------------|---------|
| (a) Open-order front-running | Taker / Miner | **Accepted** (open); **Prevented** (addressed mode); maker price-protected |
| (b) Dust-order book bloat | Maker | **Mitigated** (dust floor + real-UTXO backing + announce fee + expiry; no bond) |
| (c) Snipe-bait pricing in volatility | Maker | **Accepted** (free-option risk); mitigated by cancel / RBF / expiry / addressed |
| (d) Inconsistent book to clients | Indexer operator | **Prevented** for acting takers (re-verify); **Accepted/Detectable** for viewers (consensus hash) |
| (e) Cancel vs fill race | Maker / Taker | **Accepted**; resolved deterministically by consensus + output-0 classification |
| (f) Reorg double-fill / recapture | Miner | Double-fill **Prevented** (consensus); recapture **Accepted**, mitigated (rollback + confirmations) |
| (g) Mempool pinning of cancel | Mempool / relay-path attacker | **Doesn't address** (fee-aware cancel exists; no anti-pinning) |
| (h) Fill-pinning to lock an order | Mempool attacker | **Doesn't address** (mirror of g; principal-safe) |
| (i) Indexer indexing-cost DoS | On-chain spammer | **Doesn't address / [VERIFY]** (unbounded per-block BTX-candidate work; needs measurement) |
| (j) Reveal-suppression (two-phase publish) | Relay-path attacker | **Mitigated** (recoverable via `--state-file`; commit-dust blast radius) |

**Genuinely unaddressed (economic/relay, not consensus):** no anti-spam bond beyond the offer UTXO
(b mitigated, not solved); no mempool-pinning defense (g, h); no per-block cap on indexer BTX-candidate
processing (i, [VERIFY]). All are out of scope for the current code and recorded here so they are
accepted deliberately rather than assumed solved. None puts principal at risk — they are
liveness/cost/resource harms.
