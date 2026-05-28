# BTX Phase 0 — Order-Artifact Layout & Atomic-Swap Regtest Plan

> Scope: de-risk the single load-bearing piece of BTX — proving that an order can live
> entirely on chain (no relay) **and** be completed as one atomic BTC↔asset transaction.
> This spec is a starting point for a spike, not a frozen wire format. Items I cannot verify
> against the live 2026 protocol state are flagged **[VERIFY]**; my reliable knowledge ends
> May 2025.

---

## 0. Spike target choices

### Asset protocol for the spike: **Runes** (regtest)
Rationale:
- Pure Bitcoin L1 — a single Bitcoin transaction can move BTC *and* runes together, which is
  exactly the atomicity primitive BTX needs. No second daemon.
- Indexable from block data alone, which is the whole point of the chain-reconstructed book.
- Taproot Assets is the alternative but needs `tapd`/`lnd` infrastructure and a more complex
  proof model — heavier for a spike. Keep it as a pluggable backend later (the production
  counter-asset is still the USD-stablecoin; Runes here is the cheapest way to prove the
  *mechanism*).

**[VERIFY]** Runes specifics below (runestone/edict/cenotaph semantics, rune-id format) are
from the protocol as I knew it; confirm against the current `ord` / Runes spec before coding.

### Swap mechanism: **pre-signature published on chain** (mechanism (b) from the architecture doc)
The architecture doc named two candidates. For Phase 0, prototype (b) first because it is
clearly feasible with today's Bitcoin; treat (a) script-enforced as a research stretch goal.

The settlement primitive is the **`SIGHASH_SINGLE | ANYONECANPAY` partial-signed swap** that
Ordinals/Runes PSBT markets already use — but with the maker's pre-signature *published in an
on-chain artifact* instead of handed to a taker over a relay. That on-chain publication is the
only thing that makes it "pure chain-reconstructed" rather than an off-chain order book.

How the signature stays valid while the taker fills in the rest:
- Maker signs **input 0** (their rune/offer UTXO) with `SIGHASH_SINGLE | ANYONECANPAY`.
- `ANYONECANPAY` → other inputs (the taker's BTC) can be added without breaking the maker sig.
- `SIGHASH_SINGLE` → only the **output at the same index (output 0)** is committed. Output 0 =
  the maker's BTC payout. Everything else (taker's rune-destination output, change, the
  runestone `OP_RETURN`) is uncommitted and supplied by the taker.
- Net guarantee: the maker is paid exactly their BTC at output 0 or the transaction is invalid.
  The maker does not care where the rune lands — the taker assigns it to themselves.

**Position convention (load-bearing):** offer input MUST be index 0; maker payout MUST be
output 0. The taker must preserve these. The indexer rejects artifacts that don't follow this.

---

## 1. Order-artifact byte layout (BTX v1)

A "new order" artifact carries everything a taker needs to reconstruct and complete the swap
from chain data alone: the offer location, the terms, where the maker is paid, and the maker's
pre-signature.

| Field | Bytes | Notes |
|---|---|---|
| `magic` = `"BTX1"` | 4 | namespace/version tag for the indexer's filter |
| `version` | 1 | format version |
| `msg_type` | 1 | `0x01` new order, `0x02` cancel |
| `side` | 1 | `0x00` sell asset for BTC, `0x01` buy asset with BTC |
| `rune_id.block` | 4 | Runes id is `block:tx` **[VERIFY]** (varint in practice) |
| `rune_id.tx` | 2 | tx index within block |
| `asset_amount` | 8 | u64, base units offered |
| `price` | 8 | u64, sats per asset base-unit |
| `expiry` | 4 | block height after which the order is dead |
| `offer_outpoint.txid` | 32 | the asset UTXO being offered (input 0) |
| `offer_outpoint.vout` | 4 | |
| `maker_payout_spk_len` | 1 | length prefix |
| `maker_payout_spk` | 34 | P2TR scriptPubKey where maker receives BTC (output 0) |
| `sighash_flag` | 1 | expected `0x83` = SINGLE\|ANYONECANPAY |
| `maker_sig` | 64 | Schnorr signature over input 0 / output 0 |
| **Total** | **169** | |

**Carrier decision (verified, not assumed):** at **169 bytes** this does not fit a classic
80-byte `OP_RETURN` — the 64-byte signature alone leaves only ~9 bytes. So the artifact rides a
**Taproot script-path "envelope"** in the witness (the Ordinals inscription technique:
`OP_FALSE OP_IF <pushdata...> OP_ENDIF`), which carries hundreds of bytes cheaply at the
witness discount. A tiny `OP_RETURN` "beacon" (just `magic` + a pointer) can optionally be
added so a lightweight scan can find envelopes without parsing every witness. **[VERIFY]** the
2026 standardness of large `OP_RETURN` — Core relaxed the data-carrier limit around 2024–2025;
if a single large `OP_RETURN` is now standard on your target network, that becomes a simpler
carrier than the witness envelope. Confirm before committing.

**Cancel artifact (`msg_type=0x02`)** is just `magic|version|msg_type|offer_outpoint(+sig by
maker key)`. But note: the cheapest, most unambiguous cancel is simply **the maker spending
their own offer UTXO back to themselves** — the indexer sees the offer UTXO spent by a non-swap
tx and drops the order. Prefer that; keep the explicit cancel artifact only if you need a
"reduce/replace" semantic.

**What does NOT go in the artifact** (derivable from chain, so don't bloat the payload): the
offer UTXO's amount and scriptPubKey — the indexer/taker fetches those by looking up
`offer_outpoint`, and they are required anyway to verify the Taproot sighash (BIP-341 commits
to the spent output's value and spk).

---

## 2. Lifecycle, reconstructed from chain only

1. **Etch/own** — maker holds a rune in a UTXO (`offer_outpoint`).
2. **Post** — maker broadcasts an *announcement tx* carrying the BTX artifact (envelope). The
   offer UTXO stays unspent. Indexers across all nodes parse the artifact → identical open
   order appears in every local book. No relay involved.
3. **Discover** — taker's indexer surfaces the order; taker verifies the maker sig against the
   looked-up offer UTXO and that the offer UTXO is still unspent.
4. **Take** — taker assembles the swap tx: input 0 = maker's offer UTXO (with maker's published
   sig in the witness), input 1+ = taker BTC; output 0 = maker payout (must match
   `maker_payout_spk` + the price×amount sats the sig committed to), output 1 = taker's rune
   destination, output 2 = change, plus a runestone `OP_RETURN` whose **edict assigns the rune
   to output 1**. Taker signs their own inputs (`SIGHASH_ALL`) and broadcasts.
5. **Settle** — one confirmation = atomic swap done. Indexers see `offer_outpoint` spent by a
   tx matching the swap shape → mark the order **filled**.
6. **Cancel/expire** — maker spends the offer UTXO back to self (→ **cancelled**), or height
   passes `expiry` (→ **expired**, indexer stops offering it even if still unspent).

---

## 3. Regtest test plan

Environment: `bitcoind -regtest -txindex=1`, a Runes-capable indexer/wallet (e.g. `ord` in
regtest mode **[VERIFY]** it supports regtest etching in your version), and two wallets
(`maker`, `taker`) on the same node first, then on two nodes to prove the no-relay property.

### Milestone 0a — Atomic swap primitive (off-chain handoff allowed)
Goal: prove the `SINGLE|ANYONECANPAY` BTC↔rune swap settles atomically. Relay allowed here —
this milestone is *only* about the settlement tx, not yet about chain-reconstruction.
1. Etch a test rune to `maker`; fund `taker` with regtest BTC.
2. Maker builds + partial-signs the offer (input 0 = rune UTXO, output 0 = BTC payout, flag
   `0x83`). Hand the PSBT to taker directly.
3. Taker completes (adds BTC input, rune-dest output, change, runestone edict), signs, broadcasts.
4. Mine 1 block.
   - **PASS:** rune moved maker→taker, BTC moved taker→maker, in ONE txid; maker received
     exactly the committed sats; no rune burned (no cenotaph).

### Milestone 0b — Pure chain-reconstruction (the real exit criterion)
Goal: a **second node, given only the chain, finds the order and completes it** — no relay.
1. Maker broadcasts the announcement tx carrying the BTX envelope; mine 1 block.
2. On a **separate** node (own datadir, connected only by P2P block sync, no BTX messaging),
   run the indexer over blocks. It must parse the artifact and surface the open order with
   correct terms, validating the maker sig against the looked-up offer UTXO.
3. From that second node, taker reconstructs and broadcasts the swap tx; mine 1 block.
   - **PASS (Phase 0 exit criterion):** the swap settles atomically using *only* data the
     second node read from the chain. If this can't be achieved, the "pure chain-reconstructed"
     decision must be revisited before any further build (per the architecture doc).

### Milestone 0c — Negative & adversarial tests
- **Expiry:** post an order, mine past `expiry`, attempt take → indexer must refuse to surface
  it; if force-broadcast, define whether script/policy still allows it (document the answer).
- **Double-take race:** two takers build swaps spending the same offer UTXO; broadcast both.
  - **EXPECT:** exactly one confirms; the other is a double-spend and is rejected. Confirms the
    "first valid spender wins / fee auction" property (no price-time priority) — this is the
    intended behavior, not a bug.
- **Stale book:** maker cancels (spends offer UTXO to self) **after** a taker has built but not
  yet broadcast → taker's broadcast must fail (input already spent). Confirms cancel safety.
- **Reorg:** confirm a fill, then invalidate the block (`invalidateblock`) → indexer must move
  the order back to **open** (the book is a projection of chain state and must be revertible).
- **Cenotaph/burn safety:** feed a malformed runestone → confirm the wallet never *constructs*
  one, and the indexer flags burns rather than counting them as fills. **[VERIFY]** exact
  cenotaph rules.
- **Signature-rebinding attack:** verify a taker cannot redirect the maker's BTC payout
  (move/alter output 0) — the `SINGLE` sig must fail. This is the core safety property; test it
  explicitly.

---

## 4. Open uncertainties (resolve in the spike, don't assume)
1. **`SIGHASH_SINGLE|ANYONECANPAY` × Runes assignment** — the interaction between the maker's
   partial signature and the runestone/edict that assigns the rune in the *final* tx is the
   subtlest part. Confirm the maker need not see the runestone (they shouldn't, since it's not
   at their committed output index) and that a taker-supplied edict reliably delivers the rune.
2. **Carrier standardness in 2026** — witness envelope vs (possibly now-relaxed) large
   `OP_RETURN`. Pick based on what relays on your target network.
3. **Mechanism (a) feasibility** — whether Bitcoin Script (no new opcodes) can *enforce* the
   counter-asset leg atomically remains unproven; (b) is the safe Phase 0 path.
4. **Runes-on-regtest tooling** — confirm `ord`/your indexer supports etching + edicts on
   regtest, else use signet.

## 4a. Empirical result — settlement primitive validated on regtest (2026-05-23)

The core signing mechanism behind Milestone 0a was run against the real consensus engine
(Bitcoin Core v29.1, regtest). Scripts in the project folder: `swap_test.py` (builds the
swap), `run_swap.sh` (orchestrates the node), `swap_0a_result.log` (raw output).

Setup: a maker "offer" UTXO (1.0 BTC, standing in for the asset-bearing UTXO) and a taker
payment UTXO (0.6 BTC). The maker pre-signs **only** `[input0, output0]` with
`SIGHASH_SINGLE | ANYONECANPAY` (flag `0x83`); the taker then appends their input and a
proceeds output and signs only their own input. Results:

- **Honest completion → ACCEPTED.** `testmempoolaccept allowed=true`; broadcast settled in a
  **single txid**; the maker payout output held exactly **0.5 BTC** at 1 confirmation and the
  offer UTXO was spent. The maker's witness was transplanted unchanged — **no relay-time
  re-signing** — confirming the pre-signature survives the taker's later additions.
- **Payout-shaving attack → REJECTED.** When the taker rebuilt the tx reducing the maker's
  payout to 0.4 BTC (pocketing 0.1), consensus rejected it:
  `mandatory-script-verify-flag-failed`. The maker's signature is cryptographically bound to
  its committed payout output and cannot be redirected or reduced.

**What this does and does not prove.** It proves the `SINGLE|ANYONECANPAY` partial-signing /
witness-transplant primitive — the safety-critical heart of the swap — works as designed. It
does **not** yet include: (1) the **Runes asset leg** (the offer UTXO here is plain BTC, not a
rune; the runestone/edict interaction in §4 item 1 remains the next thing to prove), or (2)
**on-chain publication + reconstruction** (Milestone 0b — here the completed tx was assembled
locally, not discovered from chain by a second node). Those two remain the open Phase 0 work.

## 4b. Empirical result — Runes asset leg (2026-05-23)

Next, the rune transfer was added to the swap. Scripts: `btx_runes.py` (build + minimal
indexer), `run_runes.sh` (node orchestration), `runes_leg_result.log` (output).

A **byte-accurate runestone** was embedded in the swap tx as a value-0 output:
`6a 5d 08 00 c0a233 01 e807 01` = `OP_RETURN OP_13` + LEB128 payload decoding to
`Tag::Body(0), block-delta 840000, tx-delta 1, amount 1000, output 1` — i.e. an edict assigning
1000 units of rune `840000:1` to output index 1 (the taker). This output is **taker-supplied**:
it is not at the maker's committed index (output 0), so the maker's `SINGLE|ANYONECANPAY`
signature does not cover it.

- **Encoding round-trip + edict allocation → PASS** (machine-verified, pure Python). A minimal
  Runes indexer parsed the runestone back out of the serialized tx and allocated **1000 RUNE to
  the taker's output #1, 0 to the maker payout #0, 0 unallocated** — the rune moves with the BTC
  payment in one transaction, and the taker's edict (not the maker) directs it.
- **Consensus acceptance of the runestone-bearing tx → VERIFIED ON-NODE 2026-05-23** (WSL,
  Bitcoin Core v29.1). `run_runes.sh` reported `testmempoolaccept allowed=true` and the swap
  settled in one txid; the minimal indexer then read the edict from chain and confirmed 1000
  RUNE on the taker output, 0 on the maker payout. The earlier analytical argument (kept below
  for the record) is now backed by an on-node run. The argument it is accepted: (1) Milestone 0a already
  proved the `SINGLE|ANYONECANPAY` swap is consensus-valid; (2) the only additions are a value-0
  `OP_RETURN OP_13 <push>` output and a taker P2WPKH output, neither covered by the maker's
  `SINGLE` sighash, so input0's signature is unaffected; (3) `OP_RETURN OP_13 <push>` is
  push-only `TX_NULL_DATA` (OP_13 = 0x5d ≤ OP_16), well under the data-carrier size limit — which
  is also why real runestones relay on mainnet today. Treat this as **high-confidence but
  unverified-on-node**; re-run `run_runes.sh` on a stable node to close it.

**Caveat on the indexer.** `btx_runes.py`'s indexer is faithful at the byte level for a single
transfer edict but is a **simplified model** of Runes — it does not implement cenotaph rules,
etching/mint, divisibility, or default-output/pointer edge cases. Final validation should run the
canonical `ord` indexer against the same transactions.

## 4c. Empirical result — Milestone 0b reconstruction logic (offline, 2026-05-23)

The chain-reconstruction logic was built and validated offline (`btx_0b.py`; on-node procedure
in `BTX-0b-runbook.md`). The maker publishes a **BTX artifact** carrying the
`SINGLE|ANYONECANPAY` pre-signature; a second party reconstructs the order from that artifact
alone. `btx_0b.py selftest` — **ALL_PASS**:

- A party with **only the artifact bytes + the offer UTXO amount** (the amount being the one
  thing it looks up from its own chain state) VERIFIES the maker signature. This is the property
  that makes "no relay" possible: the order's authorization travels on chain, not through a
  coordinator.
- Tampering the price in the artifact makes the signature fail — order terms are signature-bound.
- The swap rebuilt purely from artifact data transplants the maker witness into input 0 and
  reproduces the committed payout. BTX v1 artifact is **~200 bytes** (33-byte pubkey + DER sig
  added for on-chain verifiability), so the carrier needs relaxed `-datacarriersize` or a witness
  envelope.

**VERIFIED ON-NODE 2026-05-23** (WSL, Bitcoin Core v29.1, `run_0b.sh`): the maker published the
BTX artifact in a real on-chain `OP_RETURN` (datacarriersize=240), and a second party read the
announce tx back off the chain, parsed it, looked up the offer UTXO from its own node, and
**verified the maker signature from chain data alone** (`True`) — then completed the swap
(`testmempoolaccept allowed=true`), settling atomically (maker payout 0.5 BTC @ 1 conf, offer
UTXO consumed). No relay, no message from the maker's process. This is the single-node
chain-reconstruction proof.

**Stricter two-node variant → ALSO VERIFIED ON-NODE 2026-05-23** (`run_0b_twonode.sh`): two
separate `bitcoind` datadirs (`/tmp/rt0bA`, `/tmp/rt0bB`) connected only by P2P (`-connect`).
Node A published the order; node B received the announce tx **solely via block propagation**,
verified the maker sig from its own chain (`True`), and broadcast the completed swap, which
relayed back to A and confirmed (payout 0.5 BTC, offer UTXO consumed). No shared files, no order
relay — the artifact reached the taker through the blockchain alone. This is the strongest form
of the no-externality claim and it holds.

**Genuinely remaining:** canonical `ord` validation of the rune movement (vs. the simplified
indexer), the double-take race test, calling `index_block_brk` from BRK's loop, and the MAS
regulatory review before any mainnet/stablecoin step.

## 4d. Fill vs. cancel detection is exact, not heuristic (2026-05-23)

When the indexer sees an order's offer UTXO spent, it must decide Filled vs Cancelled. This is
**exact**, because the maker's `SINGLE|ANYONECANPAY` signature consensus-enforces output 0 to be
`(price, payout_spk)`: any *confirmed* spend that used the maker's pre-signature necessarily
carries the committed payout. So the rule is:

> A confirmed spend of the offer UTXO is a **FILL** iff its output 0 == `(price, payout_spk)`;
> otherwise it is the maker spending their own UTXO with a different signature → **CANCEL**.

Verified offline in `classify_test.py` (and `btx_index.rs::is_fill` + its test): a real fill tx →
FILL; a maker self-spend → CANCEL; and an adversarial spend paying the payout SPK but a *wrong
(too-low) amount* → CANCEL (it could never confirm with the maker's price-committing signature,
so if seen it isn't an authorized fill). This removes the only hand-waved piece of the indexer.

## 5. Suggested Phase 0 exit gate
Phase 0 is "done" only when Milestone **0b** passes on **two separate nodes with no messaging
channel between them**, and the **signature-rebinding** and **double-take** negative tests
behave as specified. Anything less means the no-relay claim isn't proven yet.
