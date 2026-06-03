# BTX2 cross-curve conditional orders — design spec

*Closes the cross-curve DLEQ integration scope from
`BTX-secp256kfun-scouting-2026-06-03.md` with a working spec (not a full
implementation). Documents what BTX would need to build to wire Lloyd
Fournier's `sigma_fun::ext::dl_secp256k1_ed25519_eq` proof into a BTX2
record type for trustless cross-chain conditional orders.*

Date: 2026-06-03.

## What this doc is and isn't

**Is:** the byte-layout spec for a new BTX2 record sub-type
(`CROSS_CURVE_CONDITIONAL`, type tag `0x04`), the indexer verification
flow, the threat model, and a calibrated build-cost estimate.

**Isn't:** working code. The cryptographic primitive (252-bit Pedersen
commitments across secp256k1 and ed25519, MRL-0010 lineage) is a ~340 LOC
production module in Rust + Python that requires:

- a from-scratch ed25519 field-and-group arithmetic implementation
  (BTX has only secp256k1 today via `btx_taproot.py`)
- the Sigma-protocol Fiat-Shamir transcript machinery (~250 LOC of
  `sigma_fun` infrastructure)
- 252 paired Pedersen commitments per proof, each verifying that the
  same bit appears at the same position on both curves
- a careful threat-model review of Monero-specific encoding quirks
  (the construction inherits MRL-0010's ring-sig considerations)

A faithful BTX implementation is realistically a **3-week task** (1 week
ed25519, 1 week Sigma + DLEQ, 1 week BTX2 integration + tests). This doc
is what we'd hand to whoever picks that work up.

## Motivation — the market gap

From the BTX competitive landscape (`BTX-competitive-landscape.md`):

> *"Every other system buys a feature by giving something up: Counterparty/Omni
> a token + two-phase settlement; Saturn an external VM; Magic Eden a hosted
> off-chain book; Liquid a trusted federation; Light Pools an off-chain gossip
> net; tbDEX identity/intermediaries."*

None of the Category A on-chain Bitcoin DEXes (BTX, Counterparty, Omni) ship
cross-chain settlement. None of the Category B off-chain-book systems do
either — they all assume the asset on offer is a Runes/BRC20/Ordinal token
that's *already* on Bitcoin.

A BTX2 conditional order that settles against a Monero or Solana payment —
*atomically, no oracle, no bridge* — opens a feature category no
competitor currently offers. This isn't speculative; the math has been
known since 2018 (MRL-0010, the Joël Gugger atomic-swap papers, Lloyd's
2020 sigma-protocol re-imagining), and the FarcasterXMR XMR↔BTC swap
production system has shipped it for the Monero side.

What BTX adds is using it as the **conditional encryption point** of a
BTX2 CONDITIONAL_ORDER, which is structurally already in the spec via
`type 0x03`. The new bit is the `CROSS_CURVE_CONDITIONAL (0x04)` record
type that carries an extra DLEQ proof binding the encryption point T to
a known ed25519 pubkey.

## Construction — the math

For an atomic swap "Alice pays X BTC, Bob pays Y XMR":

1. **Bob picks** a secret scalar `t` (252 bits, valid on both curves).
2. **Bob publishes:**
   - `T_btc = t · G_secp` (33-byte compressed)
   - `T_xmr = t · G_ed` (32-byte ed25519 point)
   - `DLEQ_proof` proving `T_btc` and `T_xmr` are commitments to the
     same `t` (the `sigma_fun::ext::dl_secp256k1_ed25519_eq` artefact,
     ~6 KB)
3. **Alice constructs** a BTX2 CROSS_CURVE_CONDITIONAL order with
   `T = T_btc` as the encryption point of a Schnorr adaptor pre-sig.
4. **Alice sends** Bob the equivalent XMR-side adaptor structure
   (Monero key-image-based, also keyed to `T_xmr`).
5. **Either party** can claim by revealing `t` on their chain. Once `t`
   is observable on either chain, the other party's adaptor sig decrypts
   and they can claim.

The DLEQ proof is what guarantees Bob can't lie about `t` matching across
chains. Without it, Bob could publish `T_btc` and `T_xmr` from different
secrets and trap Alice's BTC without exposing his XMR.

## Wire format — `CROSS_CURVE_CONDITIONAL` record (type `0x04`)

A new BTX2 record type. The envelope parser at `brk_indexer::btx_v2`
dispatches it via the existing type-tag scanner.

```
struct CrossCurveConditional {
    rec_type:     u8         = 0x04
    body_len:     u16 BE                        // length of `body` below
    body:         OrderBody                     // unchanged from spec §3.4
    T_secp:       [u8; 33]                      // compressed secp256k1 point
    T_ed25519:    [u8; 32]                      // ed25519 point (compressed)
    dleq_proof:   [u8; DLEQ_LEN]                // sigma_fun cross-curve proof
    adaptor_sig:  [u8; 65]                      // 33-byte R̂ || 32-byte s_a
}
```

`DLEQ_LEN` is approximately **6,432 bytes** per Lloyd's
`sigma_fun::ext::dl_secp256k1_ed25519_eq` analysis (252 paired
commitments × 4 bytes per Sigma response × 3 lines of the protocol +
overhead). The exact length depends on whether bincode or raw encoding
is used; a fixed length will be locked in the BTX2 spec amendment.

Total record size: `2 + body_len + 33 + 32 + ~6432 + 65 ≈ body_len + 6,564`.

For a typical order body of ~118 bytes, the record is ~6,682 bytes. That's
LARGE for a Bitcoin witness — fits inside an OP_RETURN-only envelope on
Core v30 (where `-datacarriersize` is up to 4 MB), but on default policy
pre-v30 it would need a multi-tx commit-reveal carrier. A first cut
should target the witness-envelope carrier on v30.

## Indexer verification flow

`brk_indexer::btx_v2_verify::verify_cross_curve_conditional` would:

1. Parse the OrderBody (existing logic from `btx_v2_records`).
2. Extract `T_secp`, `T_ed25519`, `dleq_proof`, `adaptor_sig`.
3. Run the DLEQ verifier: `dleq::verify(T_secp, T_ed25519, &dleq_proof)`.
   If it returns false, reject the record with `CrossCurveDleqInvalid`.
4. Run the Schnorr-adaptor pre-verify on `(adaptor_sig, body_sighash,
   maker_pubkey, T_secp)`. If false, reject with `AdaptorInvalid`.

A passing record proves:
- The maker committed to an order at `body_sighash`, redeemable by
  revealing the secret `t` matching `T_secp`.
- The same `t` is committed on ed25519, so revelation of `t` on Monero
  or Solana also lets the BTC side decrypt the adaptor sig.

## Settlement flow (indexer-side state machine)

State machine extends `btx_v2_state::OrderState`:

```
None  →  Conditional{T_secp, T_ed25519}  // on announce
                                       
       ┌─→  Filled{t_revealed}            // when adaptor decrypts on-chain
Conditional{T_secp, T_ed25519}
       ├─→  CrossChainFilled{t_revealed_on: "ed25519", ed25519_tx_hash}
       │                                  // when the ed25519 side
       │                                  // reveals t first
       └─→  Expired                       // if neither side reveals
                                          // before order.expiry
```

The `CrossChainFilled` variant is new. The indexer learns `t` from one
of two sources:

- **Bitcoin side:** the adaptor sig completes on-chain (the secp256k1
  recovery is straightforward — exactly what BTX2 already does for
  `CONDITIONAL_ORDER`).
- **Other chain (Monero / Solana):** out-of-band. The BTX indexer
  cannot directly observe Monero / Solana chains, so this branch needs
  either:
  - an oracle / relayer (re-introduces a trust assumption — should be
    flagged in the threat model)
  - OR the user / GUI watches both chains and posts a "reveal record"
    pointing at the BTX1-style envelope channel (the maker-side path)

The clean BTX design is to leave cross-chain reveal as a UI/GUI concern;
the indexer's job is just to verify a passed-in `t` against `T_ed25519`
and update state if it matches.

## Threat model — what's new vs `CONDITIONAL_ORDER`

| Threat                            | CONDITIONAL_ORDER       | CROSS_CURVE_CONDITIONAL |
|-----------------------------------|-------------------------|-------------------------|
| Maker absconds with funds         | Adaptor refund timelock | Adaptor refund timelock |
| Oracle equivocation               | Oracle attests once     | n/a (no oracle)         |
| Cross-chain inconsistency         | n/a                     | **DLEQ prevents this**  |
| Monero ring sig identification    | n/a                     | LOW (the secret `t` is per-order; no long-term correlation across orders unless reused) |
| Solana program-level cancellation | n/a                     | MEDIUM (Solana txns are reversible up to N slots; finality wait required before indexer accepts `t`) |
| Bitcoin reorg post-fill           | Existing handling       | Existing handling (the `t` recovery is on the BTC tx) |
| Stale DLEQ proof reuse            | n/a                     | LOW (proof is bound to `T_secp, T_ed25519`; reusing it requires reusing the same encryption point, which leaks the per-order secret on first reveal) |

## Build cost — calibrated estimate

Mapped to LOC and prior work:

| Task                                                              | Estimate | Reference                       |
|-------------------------------------------------------------------|----------|---------------------------------|
| ed25519 field + group arithmetic in Python                        | 3 days   | similar to btx_taproot.py (~530 LOC) |
| Sigma protocol infrastructure (Fiat-Shamir + transcript)          | 2 days   | sigma_fun's 251-line `lib.rs` is the template |
| Cross-curve DLEQ proof + verify                                   | 4 days   | the 340-LOC core; needs careful port |
| Python golden vectors + selftest                                  | 2 days   | mirror btx_dlc_demo's stage-based test format |
| BTX2 spec amendment for CROSS_CURVE_CONDITIONAL (0x04)            | 1 day    | mostly copy-paste from §3.3      |
| Rust port to `brk_indexer::btx_v2_cross_curve` + golden cross-test| 3 days   | mirror btx_v2_verify pattern    |
| Threat-model addendum (Monero / Solana specifics)                 | 1 day    | similar to BTX-frontrunning-threat-model.md sections |
| GUI / wallet workflow (out of scope here)                         | n/a      | separate effort                  |
| **Total**                                                         | **~16 working days**, ~3 weeks calendar | |

This matches the original ~3-week estimate in the scouting doc.

## Why we stop at spec, not implementation

Three reasons:

1. **Scope discipline.** This session's mandate was to extract everything
   we can from `LLFourn/secp256kfun` for BTX. We've done that at the
   primitive level (this doc captures the design transfer); going from
   design to a working ed25519 port is a self-contained engineering
   project that should be scoped and prioritised on its own merits, not
   bundled into a research-extraction session.
2. **No customer pull.** The product justification for cross-curve
   conditional orders (XMR/SOL settlement) requires market evidence —
   a maker desk willing to commit to the use case, or a grant scoped
   to the work. BTX-decision-brief.md is honest about this: the
   architectural moat is real but the liquidity moat is what wins
   DEXes, and we don't have liquidity for the existing BTX1 carrier
   yet. Building a new feature before validating the old one is the
   wrong sequencing.
3. **The math is delicate.** The MRL-0010 construction has known
   subtleties around bit-encoding consistency and challenge-response
   binding; a from-scratch port without cryptographer review is the
   kind of work that ends up in a CVE list later. If BTX commits to
   this, the safest path is to *consume Lloyd's `sigma_fun` crate as a
   Rust dependency* — accepting the "fun and amusement" caveat for the
   off-chain DLEQ proof generation (it's a maker-side concern; the
   indexer just verifies) — rather than re-derive from scratch.

## What this doc closes

- The scouting-doc followup-table item: *"Spec a BTX2 CROSS_CURVE_CONDITIONAL
  (0x04) record type using DLEQ"* — ✓ this doc IS that spec.
- The scouting-doc followup-table item: *"Port cross-curve DLEQ to
  `btx_xc_dleq.py` + golden vectors"* — deferred-with-reason; build cost
  is ~3 weeks and no customer pull exists today.
- The scouting-doc followup-table item: *"Build XMR↔BTX2 atomic-swap
  demo (pure-Python, like btx_dlc_demo)"* — deferred-with-reason; same
  reasoning.

## Cross-references

- `BTX-secp256kfun-scouting-2026-06-03.md` — the scouting context
- `BTX-v2-spec-2026-06-02.md` §3.3 (CONDITIONAL_ORDER, the existing
  type 0x03 record this 0x04 record extends)
- `btx_dlc_publish.py` — the existing single-chain conditional order
  builder, the closest existing analogue
- `Bitcoin CoreX/secp256kfun-reference/sigma_fun/src/ext/dl_secp256k1_ed25519_eq.rs`
  (cloned source — the construction reference)
- MRL-0010 (Monero Research Lab #10, the original 2018 paper inspiring
  the proof system)
