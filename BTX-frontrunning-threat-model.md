# BTX order fills — front-running / mempool-sniping threat model

*Backlog item #1 from `BTX-vs-light-pools.md`. The one axis where Casey Rodarmor's Light Pools is
provably ahead of BTX. This memo establishes exactly what is and isn't at risk, why, how it
compares to Light Pools, and what to do about it.*

Date: 2026-05-27. Grounded in the actual signing code; lines cited inline.

---

## 1. The construction (what the maker's signature actually commits to)

A BTX swap transaction is:

```
inputs                                   outputs
  [0] maker's offer UTXO (rune + sats)     [0] maker payout: `price` sats to the maker's address
  [1] taker funding UTXO(s)                [1] taker receipt: rune (routed by edict) + sats
                                           [2] OP_RETURN runestone (edict: rune -> output 1)
                                           [.] taker change (optional)
```

- The **maker** pre-signs input 0 with `SIGHASH_SINGLE | SIGHASH_ANYONECANPAY` = `0x83`
  (`btx_0b.py:34`, signed at input index 0 in `btx_0b.py:100`). Under this flag the maker's
  signature commits to **only**: its own input (the offer outpoint) and the single output at the
  same index — output 0, the maker's payout (amount + script). It commits to **nothing else**: not
  the taker's inputs, not the taker's receipt, not the OP_RETURN edict, not the change.
- The **taker** signs their funding input 1 with `SIGHASH_ALL` (`btx_0b.py:118`), committing to
  the entire transaction as the taker constructed it.

This is the deliberate mechanism that makes a BTX order an **open, non-interactive limit order**:
the maker publishes one signature on-chain and goes offline; *any* taker can complete the swap
without the maker's further involvement, as long as they pay output 0.

---

## 2. What is and isn't protected

**Protected — solid:**

- **Maker price.** Every valid spend of the offer input must reproduce output 0 exactly (the maker's
  `0x83` signature is over it). No one can take the rune without paying the maker the asked price.
- **Taker funds.** The taker's `SIGHASH_ALL` signature commits to the whole transaction; nobody can
  alter the taker's inputs, receipt, or change without invalidating the taker's own signature. A
  taker cannot be tricked into overpaying or misrouting their funds *within a transaction they
  signed*.

**Not protected — the gap:**

- **Which taker captures the rune is decided by a mempool fee race.** Because the maker's signature
  commits to *only* input 0 + output 0, the maker's signed input is effectively "anyone-can-complete."
  The moment it is public — and it always is, either as the published BTX artifact or in a broadcast
  fill in the mempool — a third party can lift the maker's input+signature and build their **own**
  fill that pays the same output 0 but routes the rune to themselves.

---

## 3. The attack: fill-racing / offer substitution

1. Maker publishes an open order (offer UTXO + `0x83` signature over output 0).
2. Honest taker **A** builds a fill — adds A's funding, routes the rune to A's address, sets a fee —
   and broadcasts it.
3. A watcher **B** (another taker, a bot, or a miner) sees A's fill in the mempool. B extracts the
   maker's input + `0x83` signature from input 0's witness (it's public), and constructs B's own
   fill: same maker input, same output 0 (maker still paid), rune routed to **B**, at a **higher
   fee**.
4. Miners prefer B's higher-fee transaction. B's fill is mined; A's fill is now invalid (the offer
   UTXO is spent). A wasted the effort and lost the trade.

The maker is indifferent (paid either way). **The victim is the intended taker A**; **the profiteer
is whoever bids the highest fee** (B, or the miner who reorganizes the fill for themselves).

### When it actually matters

- **At-market orders → benign.** If the order is priced at fair value, B "winning" the rune just
  means B also valued it ≥ price. This is ordinary open-market competition, not theft.
- **Underpriced / stale orders → real MEV.** If a standing order is below market (a maker mistake, or
  a limit order that has moved into the money), it is a free option for the mempool: whoever bids the
  highest fee captures the spread. The intended taker cannot reliably win against a sophisticated
  watcher or the miner itself. This is the genuine exposure.

### Related, but not unique to BTX

- **Maker reneging.** The maker holds the offer key and can double-spend the offer (cancel) any time
  before a fill confirms. So an unconfirmed fill is never final. This is true of *any* standing
  pre-signed offer, including Light Pools (a Light Pools maker can also double-spend their input
  before the co-signed tx is mined). Only confirmation is final.
- **On-chain expiry is advisory.** The BTX artifact carries an `expiry`, but Bitcoin has no
  "invalid-after-height" primitive; expiry is enforced by the indexer dropping the order from the
  book, not by consensus. A maker who wants hard expiry must spend/replace the offer.

---

## 4. Why Light Pools is immune — and the irreducible tradeoff

Casey's claim (Light Pools): *"These PSBTs and transactions are not vulnerable to mempool sniping,
since signatures commit to all inputs and outputs."* In Light Pools the maker **countersigns a
specific taker's fully-formed PSBT** — both parties sign over all inputs and outputs (`SIGHASH_ALL`
on both sides). Once the maker countersigns taker A's PSBT, there is no "anyone-can-complete" half:
substituting taker B would change inputs/outputs and break the maker's signature. Hence no fill-race.

The cost is exactly what BTX was designed to avoid:

- **The maker must be online and interactive** to countersign each fill. BTX's whole "publish once,
  go offline, anyone fills" property is gone.
- **It's a 1:1 negotiation, not an open standing order.** The maker commits to one counterparty per
  signature.

So this is not a bug to be patched away — it is a **fundamental tradeoff** between two points on the
same spectrum:

| | Open, non-interactive (BTX `0x83`) | Addressed, interactive (Light Pools full PSBT) |
|---|---|---|
| Maker liveness | offline after publishing | must countersign every fill |
| Order type | open — anyone can take | addressed — one counterparty per sig |
| Fill-race / sniping | yes (the cost) | no |
| Maker price safety | yes | yes |
| Taker fund safety | yes | yes |

BTX deliberately chose the left column. The sniping exposure is the price of that choice.

---

## 5. Severity assessment

- **No theft of principal, ever.** Maker is price-protected; taker funds are `SIGHASH_ALL`-protected.
  The worst case is not "funds stolen" but "the intended taker loses an underpriced order to a
  higher-fee actor, and/or wastes a broadcast."
- **What "principal" means here, precisely** (so the claim isn't read with EVM intuition). *Principal*
  = the funds a party holds going in. A taker who **loses** a fill race — displaced by a higher fee,
  out-raced by a multi-lot batch fill, or beaten by an unrelated spend / a maker cancel in the same
  block — has their funding UTXO returned **untouched and pays no on-chain fee at all**: on Bitcoin a
  fee is claimed only by the miner who *confirms* a tx, so an unconfirmed/displaced/double-spent-out
  fill costs nothing (unlike EVM, where a reverted tx still burns gas). The loser's only cost is
  **opportunity (the missed trade) + the effort of a broadcast** — not principal and not fees. The one
  way a *confirmed* fill can cost a taker their purchase is a **self-built malformed runestone** (a
  cenotaph ord burns): for an open order the taker constructs their own fill, so a correct fill builder
  is the taker's responsibility (`btx_wallet` builds a valid one; a buggy third-party tool could burn
  the taker's own purchase). That is taker-tooling error, not a protocol exposure.
- **Liveness vs principal — mempool pinning.** A distinct griefing vector beyond simple fee-racing: an
  attacker broadcasts a *large, low-feerate but high-absolute-fee* fill of the offer UTXO. BIP125 rule 3
  requires any RBF replacement to pay a higher **absolute** fee, so an honest taker cannot cheaply
  displace it and the order is pinned in an unconfirmable fill. **No principal is at risk** (if the pin
  confirms the pinner simply buys at the maker's price; if it never confirms nobody is charged), but the
  order's **liveness** is degraded and the maker's *cancel* must itself out-bid the pin's absolute fee.
  The maker can always recover (they hold the offer key and RBF-conflict the pin), and pinning is costly
  to the attacker (a high-absolute-fee tx risks actually confirming) — so it is a cost-and-delay harm,
  not a custody harm.
- The exposure is therefore **MEV on mispriced standing orders + griefing/pinning of broadcast fills**,
  not a custody risk. For a self-custody, no-custodian L1 DEX this is a meaningfully smaller class of
  harm than the custodial/bridge risks of the alternatives — but it is real and should be documented,
  not hidden.

---

## 6. Recommendations

1. **Keep open `0x83` orders as the default and document the model honestly.** Frame a BTX order as
   an *open mempool auction*: the maker sets a floor (output 0), and the best-fee taker wins. This is
   the correct mental model and matches the permissionless, anyone-can-fill ethos. Add a short
   "front-running" section to the README/case study with the §2 guarantees (no principal at risk).

2. **Maker guidance to minimize the MEV surface:** price at or near market; keep orders short-lived;
   re-price by **RBF-replacing the unconfirmed announce** rather than leaving stale underpriced
   orders standing (this also fixes the duplicate-order pile-up we saw on signet). Don't post deep
   in-the-money limit orders and walk away.

3. **Add an opt-in "addressed swap" mode (adopt Light Pools as an option).** For OTC / large trades
   where snipe-resistance matters more than openness, support a maker signature over a
   **fully-specified** swap to a known taker output (`SIGHASH_ALL`, or an interactive 2-step
   countersign). This is non-snipeable by construction and directly imports Casey's design as a
   *choice* layered on top of BTX, without giving up open orders as the default. Concretely: a new
   artifact variant / sighash flag byte (the artifact already stores `sighash_flag`, `btx_0b.py:56`),
   plus a `btx_wallet` path that builds the fully-committed tx and a taker flow that supplies its
   receipt output to the maker before signing.

   **Implemented (2026-05-27).** Shipped as a two-message BIP-174 PSBT handshake rather than an
   on-chain artifact variant, since an addressed swap is a private 1:1 deal that never needs to hit
   the open book: `btx_wallet addressed-propose` (taker builds the full swap, signs only its
   funding input, emits a PSBT) and `btx_wallet addressed-countersign` (maker runs
   `verify_addressed_tx` to confirm output 0 == the agreed price/address, then signs the offer input
   `SIGHASH_ALL`, finalizes, broadcasts). The PSBT is exchanged out-of-band — BTX adds no relay or
   server. Proven live on regtest with two separate wallets (taker cannot sign the maker's input;
   maker's `SIGHASH_ALL` commits to the whole tx → no substitution). The open `0x83` order remains
   the default; this is purely additive for OTC / snipe-sensitive trades.

   **Extended to rune↔rune (2026-05-27).** The addressed mode now also covers the case where the maker
   wants to *receive a counter-rune* rather than BTC — i.e. a true asset-for-asset swap, which is
   impossible as an open order (see `btx_rune_swap.py` and `[[project-rune-swap-design]]`). Because
   `SIGHASH_ALL` commits the maker to the whole tx including the OP_RETURN runestone, the maker can
   verify — before signing — that the runestone actually routes the agreed counter-rune amount to
   their output 0. `btx_wallet addressed-rune-propose` / `addressed-rune-countersign` +
   `verify_addressed_rune_tx` (which runs a Runes allocator over the proposed runestone and confirms
   output 0 receives ≥ the agreed amount of rune B, and rejects any edict that would make ord treat
   the tx as a cenotaph). Proven live on regtest: maker received the counter-rune at output 0, taker
   received the offered rune + change at output 1, ord-confirmed.

4. **Taker self-help (off-protocol, optional).** A taker who wants to avoid the public-mempool race
   can submit a fill directly to a miner / via a private submission path. This is the taker's choice
   and needs no protocol change; note it does lean on infrastructure outside Bitcoin's relay, so it's
   a pragmatic escape hatch, not the nothing-offchain default.

**Bottom line:** BTX's open orders are fill-race-able, and that is the deliberate, well-understood
cost of being non-interactive and open — with no principal ever at risk. The clean way to *also* offer
Light Pools' snipe-resistance is an **opt-in addressed-swap mode**, not a change to the open-order
default. That gives BTX both points on the spectrum while keeping the on-chain, nothing-offchain
order book that makes it more Bitcoin-native than Light Pools in the first place.

---

## 7. Is open-order snipe-resistance even coherent? (the deeper claim)

It is tempting to treat open-order sniping as a *missing primitive* — "if only Bitcoin had the right
covenant (CTV / `OP_CHECKTEMPLATEVERIFY`, `SIGHASH_ANYPREVOUT`, `OP_CAT`-built introspection), an open
order could be both fillable-by-anyone and immune to fill-racing." It cannot, and the reason is
logical, not technological:

> **Snipe-resistance means the maker's signature commits to *which* taker gets the asset. Openness
> means the maker's signature must *not* commit to which taker gets the asset. These are the same
> degree of freedom; you cannot bind it and leave it free at once.**

Walk it through with the most powerful covenant you like. Suppose the maker's offer is encumbered by a
covenant `C`. For the order to be *open*, `C` must accept a fill funded by an arbitrary, a-priori-
unknown taker and routing the asset to that taker's chosen output. So `C` admits a family of valid
spends parameterized by the taker's funding+receipt. Now two distinct parties A and B each produce a
member of that family (each pays the maker's price, each routes the asset to themselves). Both satisfy
`C`. The chain can include only one. Which one? Whatever the fee market / miner selects — i.e. the
fill-race, unchanged. The covenant narrowed *nothing* about the contest, because the contest is over
the very parameter the covenant had to leave open to be an open order. A covenant that instead pinned
the receipt to a specific key would just *be* an addressed order (§4) wearing a covenant costume.

So "open + snipe-proof" is not on the roadmap of any conceivable Bitcoin upgrade; it is a
contradiction in terms. The fill-race **is** the open auction. Calling the winning taker a "sniper"
and the losing taker a "victim" smuggles in an assumption — that taker A had a *right* to the fill —
that an open order never granted. An open order grants exactly one right, and it is the maker's: *be
paid output 0, or the asset doesn't move.* That right is cryptographically absolute (§2).

**Precise scope of the irreducibility (steelman'd — and the reason is deeper than "covenants don't
help").** The honest claim is not the bare "contradiction in terms" but: *irreducible for an open,
single-transaction, permissionless fill under ANY per-transaction validation predicate* — not merely
"under current script." Every Bitcoin predicate (current script, or CTV / `SIGHASH_ANYPREVOUT` /
a `TXHASH`-style introspection opcode / full Simplicity) evaluates over the SPENDING transaction and its
inputs' prevout data ONLY. None has an oracle for the *global ordering of off-transaction events* —
"which taker committed first" is a fact about all the OTHER commitments, which a per-tx predicate
structurally cannot see. The only "first" a covenant can use is "first to spend this UTXO," which *is*
the fill-race, decided by fee. (CTV commits to a specific template = the addressed order, not open; APO
makes signatures *less* binding = more open; richer introspection still can't enumerate competitors.)
A genuine *first-to-commit publication-time auction* IS logically constructible — but only by adding a
**sequencing / coordination layer** (a shared commitment-registry UTXO, an off-chain sequencer, or an
in-script validity proof of commitment-chain headship). Each forfeits the exact property in question —
open, permissionless, single-tx, nothing-offchain — so it is a *different market design* (a sequenced
order book, like a CEX or a rollup sequencer), not a snipe-proof OPEN order. So: no per-transaction
predicate can make an open single-tx fill snipe-proof; the only escape is a coordination layer that
changes the order type. That is the precise, defensible form of "irreducible."

### What residual harm actually remains, precisely

Strip away the mislabeled "race-between-equals" (which is just competition) and exactly one real harm
is left: **a standing order priced below its current market value is a free option to the whole
mempool.** This is worth stating crisply because it is *not* unique to BTX and *not* a property of
the `0x83` construction:

- A resting limit order on **any** venue — a CEX order book, an AMM pool, a Light Pools offer left
  standing — is pick-off-able the instant it is mispriced. On a CEX the pick-off goes to the lowest-
  latency bot; on an AMM to the arbitrageur in the first post-oracle block; on BTX to the highest-
  fee mempool bid. Same *kind* of economic event everywhere — stale quote → captured spread — and BTX
  did not introduce it; it inherited it from the concept "resting limit order."
- **But the option is genuinely *larger and harder to retract* on BTX, and the model should say so
  rather than claim strict parity.** The difference is the **cancellation axis**. On a CEX, a cancel is
  a separate, instant control-plane action: a cancel that reaches the matching engine before a fill wins
  by sequence/time and does NOT compete with the pick-off in a price auction, so a maker with reasonable
  latency retracts a mispriced quote for free before most bots. On BTX the maker's cancel is a
  double-spend of the offer UTXO that **competes in the same mempool fee auction as the sniper's fill**;
  the sniper profits from the spread and can bid fees up to ≈ the spread, so for a *deep* in-the-money
  mispricing the sniper out-bids the maker's cancel and **the maker cannot reliably retract**. Net: the
  BTX option premium approaches the full spread minus the fee needed to out-bid the canceller, and it
  is least retractable exactly when it is most valuable — strictly worse on this axis than an
  instant-cancel CEX. Crucially this is still **opportunity cost, not principal**: the maker who posted
  a sell at floor `P` receives `P` (what they asked); they only forgo the better price `M` they could
  have re-quoted to. So **"no principal at risk" holds**; what does *not* hold is the comparative claim
  of "identical economic event" — the premium is bigger and stickier here.
- The BTX-specific flavor is therefore the *selection function* (fee auction in the mempool), the
  *visibility* (the offer is on-chain, so the option is maximally public), and the *retraction cost*
  (cancel is itself race-able, above). Visibility arguably makes it **fairer**, not worse: there is no
  privileged colocation or private orderflow lane — the option is auctioned in the open to whoever
  values it most, which is the maker's stated floor or better. The retraction asymmetry is the real
  downside, and the mitigation is the same as §6.2: don't rest deep-mispriced; re-quote by RBF-replacing
  the *unconfirmed* announce *before* it is picked off; use the addressed mode for anything you'd want to
  pull instantly.

### Practical consequence (supersedes nothing in §6, sharpens it)

Because the only real harm is the mispriced-resting-order option, the entire mitigation reduces to
**don't rest mispriced**: price at market, keep orders short-lived, RBF-replace the unconfirmed
announce to re-quote, and use the **addressed mode** (§6.3) — not for "anti-sniping" but because a
deal you want bound to one counterparty is by definition *not an open order* and should never have
hit the open book. There is no fourth option to build, and no Bitcoin soft-fork that would create one.
This closes backlog item #1: the gap vs Light Pools is real on its own axis (open orders are
fill-race-able) and simultaneously *not a defect to engineer away* — it is the price, and the proof,
of being a genuinely open, permissionless, on-chain auction.

---

## 8. Cancellation semantics (the cancel-vs-fill race), precisely

A maker who wants to retract a confirmed open order races their own *cancel* against any taker's *fill* —
both spend the same offer UTXO, so only one confirms. Grounded in the code:

- **It is a BIP125 fee auction the maker can win.** BTX fills RBF-signal their **taker funding input**
  (`btx_wallet.py` `RBF_SEQUENCE = 0xfffffffd`, applied in both fill builders; asserted by
  `btx_fuzz.py`). The offer input itself is *not* RBF (the maker's `0x83` signature commits its
  `nSequence = 0xffffffff` and can't be changed), but BIP125 only needs *one* signaling input, so the
  fill is replaceable. Therefore a maker who broadcasts a **higher-fee cancel** can replace an unconfirmed
  fill (BIP125 rules 3/4: higher absolute fee *and* higher feerate). The cancel re-signs the offer input
  fresh (`SIGHASH_ALL`, maker's key) — it does *not* reuse the `0x83` artifact sig — so the maker fully
  controls it.
- **The cancel tool.** `btx_wallet cancel --offer-txid … --fee-rate <sat/vB> --broadcast` builds an
  RBF-signaled (`replaceable`), fee-bumped spend of the offer UTXO back to the maker's own wallet
  (releasing the maker-sign lock first). The rune on the offer follows ord's default allocation to the
  first non-OP_RETURN output — all of which are the maker's addresses — so it returns to the maker with no
  runestone. **Set `--fee-rate` above the racing fill's feerate**; a low-fee cancel will not satisfy the
  replacement rules and will lose.
- **Residual risk — non-RBF / out-of-band mining.** If a miner runs a first-seen (non-opt-in-RBF) policy,
  or the filler submits its fill out-of-band straight to a miner, the maker's cancel cannot displace it
  *at that miner*. The exposure is bounded by `(non-RBF hashrate share that saw the fill first) × P(that
  miner finds the next block before the cancel propagates and confirms elsewhere)` — small on 2026
  mainnet (most hashrate honors opt-in RBF, a growing share full-RBF) but nonzero. Mitigation: pay a high
  fee (so even first-seen miners prefer the cancel if they see it) and broadcast widely/early.
- **Worst-case latency = the option the maker is short.** Best/normal case: ~1 block (broadcast a
  high-fee RBF-replacing cancel → confirms next block; block intervals are exponential, so occasionally
  30–60 min). Adversarial worst case: **unbounded — or the cancel never lands because the maker is
  *filled* instead**, if a non-RBF fill reaches a non-RBF miner first or the filler keeps out-bidding the
  cancel up to the spread (§7). So a *guaranteed* cancel has no hard upper bound under fee competition; in
  practice it is ~1 block when the maker pays competitively and the fill is RBF (the normal case). The
  option the maker is short therefore = the spread over the window from "decide to cancel" to "cancel
  confirms" — ≥ one block of adverse price movement, and effectively the full in-the-moneyness if
  out-raced. **No principal is at risk in any of these** (the maker is always paid output 0 if filled, or
  recovers the offer if cancelled) — only this opportunity cost.
