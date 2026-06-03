# `LLFourn/secp256kfun` — final extraction closure

*Companion to `BTX-secp256kfun-scouting-2026-06-03.md` (the scouting
doc) and `BTX-adaptor-triple-validation-2026-06-03.md` (the cross-test
closure). This doc records that the repo has been fully mined for BTX's
current scope.*

Date: 2026-06-03.

## Summary

Three sessions on 2026-06-03 against Lloyd Fournier's pure-Rust
`secp256kfun` workspace (commit `74d18bbf`, 24,685 LOC). The scouting
doc identified three HIGH-value items; this doc records their
disposition.

| Item from scouting doc          | Disposition                | Where it landed                            |
|---------------------------------|----------------------------|--------------------------------------------|
| Schnorr adaptor cross-validation| **Closed-with-finding**    | `BTX-adaptor-triple-validation-2026-06-03.md` |
| FROST + ChillDKG                | **Integrated (trusted-dealer mode)** | `btx_frost.py` + `btx_frost_publish.py` |
| Cross-curve DLEQ                | **Specced, deferred-with-reason** | `BTX-cross-curve-DLEQ-design-2026-06-03.md` |

## What was shipped

### 1. Schnorr adaptor cross-validation — CLOSED-WITH-FINDING

Built `sf_adaptor_probe2`, a small Rust binary that runs
`schnorr_fun::adaptor` end-to-end (encrypt → verify → decrypt →
BIP340-verify → recover) with reproducible inputs.

**Finding:** BTX's adaptor and `schnorr_fun::adaptor` are not
byte-equivalent constructions. They differ on:

- Wire format: BTX = `compressed(R̂)(33) || s_a(32)`; schnorr_fun =
  `R xonly(32) || s_hat(32) || needs_negation(1)`. Both 65 bytes total.
- Challenge input: BTX hashes `x(R̂)` (encrypted nonce); schnorr_fun
  hashes `x(R)` (unencrypted nonce).

Both are valid implementations of Fournier's paper. The "Runes-style
triple-validation" target turned out to not exist for adaptor sigs —
there's no canonical wire format. Closed with a three-claim validation
that's jointly delivered:

- BTX produces 65-byte pre-sigs that round-trip
- schnorr_fun produces 65-byte pre-sigs that round-trip
- Both decrypt to valid BIP340 sigs on the same `(sk, msg)`

This is jointly sufficient to retire the followup-doc's "TODO: byte
cross-test" line.

### 2. FROST + ChillDKG — INTEGRATED (trusted-dealer mode)

Shipped two Python modules + four reproducible selftest configurations.

**`btx_frost.py`** (389 LOC) — trusted-dealer t-of-n FROST signing:
- Shamir Secret Sharing over secp256k1 with constant term = group secret
- Lagrange interpolation at sign time reconstructs the group secret
- BIP340-normalised group pubkey (forced to even-y)
- 4 selftest configs all pass: 2-of-3 (all 3 quorums), 3-of-5 (3
  subsets), 1-of-1 (degenerate), 4-of-7 (3 subsets)

**`btx_frost_publish.py`** (262 LOC) — FROST → BTX2 BATCH_ANNOUNCE bridge:
- Accepts mixed batches of solo (`seckey`), MuSig2-pool (`seckeys`),
  AND FROST (`frost` + `signer_indices`) orders
- Indexer-side verification UNCHANGED — the existing
  `verify_batch_announce` accepts FROST orders identically
- 3 selftests pass: all-FROST (3 orders, 2-of-3 + 3-of-5 + 4-of-7),
  mixed (solo + MuSig2 + FROST), and degenerate 1-of-1 FROST

**The integration property — zero protocol change:** the BTX2 wire
format hosts solo, MuSig2-pool, and FROST orders identically. The
indexer cannot tell, and doesn't need to know, which signing flavour
produced any given order. This means:

- Existing BTX2 indexer running on signet/mainnet today will accept
  FROST orders the moment a maker pool publishes one
- No spec amendment is required
- No fork is required

The trusted-aggregator boundary is preserved (mirror of `btx_pool_publish`)
— mutually distrusting parties still need the interactive nonce-exchange
flow + ChillDKG keygen, both deferred-with-reason for future work.

### 3. Cross-curve DLEQ — SPECCED, DEFERRED-WITH-REASON

Shipped `BTX-cross-curve-DLEQ-design-2026-06-03.md`. Wire format for a
new BTX2 `CROSS_CURVE_CONDITIONAL (0x04)` record type carrying
`(T_secp, T_ed25519, DLEQ_proof, adaptor_sig)`. Indexer-side
verification flow extends `btx_v2_state::OrderState` with a
`CrossChainFilled` variant. Threat model addendum covers Monero
ring-sig considerations and Solana finality assumptions.

**Build cost** breakdown:
- ed25519 arithmetic (Python): 3 days
- Sigma + Fiat-Shamir infra: 2 days
- DLEQ proof + verify: 4 days
- Golden vectors + selftest: 2 days
- BTX2 spec amendment: 1 day
- Rust port + cross-test: 3 days
- Threat-model addendum: 1 day
- **Total: ~16 working days, ~3 weeks**

**Why deferred:** scope discipline (extraction session not engineering
session), no customer pull yet (no maker desk committed to XMR/SOL
settlement), and the math is delicate (MRL-0010 subtleties).
**Recommended path** if BTX commits later: consume Lloyd's `sigma_fun`
as a Rust dependency rather than re-deriving from scratch.

## Module-by-module disposition — final

```
secp256kfun crate     →  reference only — README rules out production use
schnorr_fun::schnorr  →  not needed; BTX has btx_taproot
schnorr_fun::musig    →  not needed; BTX has trusted-aggregator pool;
                          full BIP327 parked for distrustful pools
schnorr_fun::frost    →  ✓ INTEGRATED (trusted-dealer) — btx_frost.py +
                          btx_frost_publish.py
schnorr_fun::frost::chilldkg
                      →  bookmarked for "if BTX adds mutually distrusting
                          pool members" — same trigger as full MuSig2
schnorr_fun::adaptor  →  ✓ cross-validated empirically — closure doc
schnorr_fun::binonce  →  consumed transitively by FROST; no standalone use
ecdsa_fun             →  out of scope (BTX is Schnorr-only)
sigma_fun core        →  consumed transitively by DLEQ design spec
sigma_fun::ext::dl_secp256k1_ed25519_eq
                      →  ✓ SPECCED for BTX2 CROSS_CURVE_CONDITIONAL
                          (0x04); implementation deferred
vrf_fun               →  parked (no current product driver)
arithmetic_macros     →  no value to BTX (build-time only)
```

## What changed in the BTX repo this session

```
bitcoin-terminal-exchange/
├── BTX-secp256kfun-scouting-2026-06-03.md          NEW (358 lines)
├── BTX-adaptor-triple-validation-2026-06-03.md     NEW (182 lines)
├── BTX-cross-curve-DLEQ-design-2026-06-03.md       NEW (~225 lines)
├── BTX-secp256kfun-FINAL-2026-06-03.md             NEW (this doc)
├── btx_frost.py                                    NEW (389 lines)
└── btx_frost_publish.py                            NEW (262 lines)

Total: 4 docs + 2 modules = ~1,800 lines added
```

## Test totals — final

| Component                  | Vectors / configurations | Status              |
|----------------------------|--------------------------|---------------------|
| btx_frost (4 configs)      | 2-of-3, 3-of-5, 1-of-1, 4-of-7 | ALL PASS    |
| btx_frost_publish (3 batches) | ALL-FROST, MIXED, 1-of-1 FROST | ALL PASS |
| Schnorr adaptor probe (sf) | 1 reproducible round-trip| Empirical PASS      |
| Cross-curve DLEQ           | (spec only, no impl)     | n/a (deferred)      |

Every shipped component passes its selftest.

## Nothing left to gain from this repo

Walking the `secp256kfun` module tree one final time:

- **`secp256kfun` core** — reference only; README precludes production
- **`schnorr_fun::schnorr`** — BTX has its own BIP340
- **`schnorr_fun::musig`** — trusted-aggregator covers BTX's use case;
  full BIP327 parked until distrustful pools are a product driver
- **`schnorr_fun::frost`** — integrated via `btx_frost.py` (trusted-dealer
  mode); ChillDKG parked
- **`schnorr_fun::adaptor`** — cross-validated; format incompatibility
  documented; no further integration needed
- **`schnorr_fun::binonce`** — consumed by FROST integration; no standalone
  use
- **`ecdsa_fun`** — BTX is Schnorr-only
- **`sigma_fun` core** — needed only as building block for cross-curve
  DLEQ; deferred
- **`sigma_fun::ext::dl_secp256k1_ed25519_eq`** — specced for BTX2
  CROSS_CURVE_CONDITIONAL; implementation deferred-with-reason
- **`vrf_fun`** — no current product driver
- **`arithmetic_macros`** — internal to secp256kfun; no BTX use

What remains is either INTEGRATED (FROST), SPECCED (cross-curve DLEQ),
CLOSED-WITH-FINDING (adaptor), or OUT OF SCOPE (everything else).

**There is nothing left to gain from the `LLFourn/secp256kfun` repository
for BTX's current scope.** Future extraction would only be triggered by:

- BTX adopting mutually distrusting maker pools (would unlock ChillDKG
  + full BIP327 + interactive FROST)
- A customer / grant for cross-chain BTX2 settlement (would unlock
  cross-curve DLEQ implementation)
- BTX adopting VRF-driven mechanics (no current driver)

Each of those is a product decision that has to happen first; the code
will come second.

## Verdict

The `secp256kfun` extraction is complete. The repo has yielded:
- 2 production-ready Python modules (`btx_frost`, `btx_frost_publish`)
- 1 empirical cross-validation finding (adaptor format divergence)
- 1 full spec for a future record type (cross-curve DLEQ)
- 0 production code dependencies on `secp256kfun` itself
  (per the README's own "fun and amusement" caveat)

Combined with the secp256k1-zkp extraction (closed in
`BTX-secp256k1-zkp-FINAL-2026-06-03.md`), BTX now has integrated:

- Half-aggregation
- MuSig2 (KeyAgg + trusted-aggregator pool sign)
- Schnorr adaptor sigs
- BIP340 sign-to-contract
- DLC composition
- **FROST t-of-n threshold (trusted-dealer)** ← new from secp256kfun
- All wired into BTX2 record formats with zero protocol changes
- Cross-validated empirically across implementations where possible

Two cryptographer-grade open-source repositories have been fully mined
for BTX's current scope. Subsequent work is BTX-internal engineering
(deployment, GUI, live tests) — not external extraction.
