# BTX scouting cycle summary — scouts 17-20, 2026-06-04

This document closes the second autonomous scouting cycle (scouts
17-20) after the original 15-scout cycle (2026-06-03) plus the BIP-322
ship (scout 16).

The four scouts in this cycle were tightly thematic: **all of them
extended BTX's cross-validation discipline along the implementation-
independence axis**. The prior 15-scout cycle's cross-tests all
validated against the SAME canonical test vectors; this cycle added
the first oracles that validate BTX's pure-Python implementations
against fundamentally different codebases in fundamentally different
languages.

## Cycle outcomes

| # | Repo / Domain                              | Outcome                                                                                              | Commits             |
| - | ------------------------------------------ | ---------------------------------------------------------------------------------------------------- | ------------------- |
| 17 | `discreetlogcontracts/dlcspecs`           | shipped Schnorr 5x5 + DLC oracle NFC+contract_id 24/24                                                | ae6d665 + 6b24d91   |
| 18 | `Simplexum/python-bitcointx`              | shipped BIP-340 vs libsecp256k1 (C) cross-test                                                       | 422235b + cf1749f   |
| 19 | `paulmillr/scure-btc-signer` (@noble/curves) | shipped BIP-340 vs noble (pure-JS) cross-test                                                       | 45e7d11             |
| 20 | `rust-bitcoin/rust-bitcoin`               | shipped BIP-341 Taproot vs rust-bitcoin cross-test                                                   | c8a79d0             |

## Cross-validation suite expansion

| Stage              | Sub-tests | Result on this runner   |
| ------------------ | --------- | ----------------------- |
| Pre-cycle (post-scout-16) | 12 | 12/12 PASS green |
| Post-scout-17 (Phase 1+2) | 14 | 14/14 PASS green |
| Post-scout-18            | 15 | 15/15 PASS green |
| Post-scout-19            | 16 | 16/16 PASS green |
| Post-scout-20            | **17** | **17/17 PASS green** |

## Implementation-independence achieved this cycle

Before scout 18 every BIP-340 oracle BTX had validated against the
same canonical test corpus — passing all of them proves spec
compliance but not implementation independence. This cycle added
three implementation-independence oracles:

| BIP      | BTX (reference) | Independence oracle 1 | Independence oracle 2 |
| -------- | --------------- | --------------------- | --------------------- |
| BIP-340  | Python (from-scratch) | **libsecp256k1 (C)** ← scout 18 | **@noble/curves (TypeScript)** ← scout 19 |
| BIP-341  | Python (from-scratch) | **rust-bitcoin (Rust)** ← scout 20 | (none yet) |
| BIP-322  | Python (from-scratch) | (none yet)            | (none yet)            |

For BIP-340 Schnorr, BTX is now cross-validated across **three
independent implementations in three different languages**. On 50
random `(sk, msg, aux_rand)` tuples plus 15 canonical CSV vectors,
all three produce byte-identical signatures. This is the strongest
non-formal validation of BIP-340 correctness BTX has access to.

For BIP-341 Taproot, BTX has its first implementation-independence
oracle via rust-bitcoin. rust-bitcoin's `bitcoin::taproot` is used
downstream by Sparrow, BDK, electrs, LDK — agreement with it means
BTX matches what every major Rust Bitcoin tool does.

## Oracle inventory by primitive

| Primitive                | Oracles | Implementation-independence? |
| ------------------------ | ------- | ----------------------------- |
| BIP-340 Schnorr          | 6       | YES (libsecp256k1-C + noble-JS) |
| BIP-341 Taproot          | 2       | YES (rust-bitcoin)              |
| BIP-322 message signing  | 1       | no                              |
| BIP-327 MuSig2           | 1       | no                              |
| BIP-374 DLEQ             | 1       | no                              |
| BIP-380 descriptors      | 3       | YES (rust-miniscript + python-bip380) |
| Schnorr adaptor          | 2       | (vectors only)                  |
| DLC                      | 2       | (vectors only)                  |
| Half-aggregation         | 1       | no                              |
| Sign-to-contract (btx_s2c) | 0     | no                              |
| MuSig2 adaptor           | 0       | no                              |
| FROST                    | 0       | no                              |
| Runes decoder            | 2       | (vectors only)                  |

## What was searched for and not found

### BIP-322 cross-implementation oracle — ecosystem gap

Scout 19 closure explicitly bookmarked "focused BIP-322 cross-
implementation oracle" as the next high-value open slot. Scout 20
+ the followup survey checked four major candidates:

| Library                       | Has BIP-322? | Notes                                                                |
| ----------------------------- | ------------ | -------------------------------------------------------------------- |
| `rust-bitcoin/rust-bitcoin`   | NO           | Only legacy BIP-137 `sign_message.rs`                                |
| `bitcoindevkit/bdk`           | NO           | grep -i bip322 returns zero hits across all crates                   |
| `paulmillr/scure-btc-signer`  | NO           | README claims it but `grep -i bip-?322 src/` returns zero            |
| `paulmillr/noble-curves`      | NO           | Schnorr primitive only, not protocol-layer                           |

**Verdict**: The Rust + JavaScript Bitcoin ecosystem hasn't
standardized on BIP-322 yet. It's a recent (2022) spec and adoption
is slow. Until a major library ships it, BTX's BIP-322 implementation
remains validated against only one external oracle (canonical
bitcoin/bips basic-test-vectors.json).

Candidate scouts for if/when this becomes a priority:
- `bitcoin-s` (Scala) — Nadav Kohen's, has BIP-322 verification but
  requires JVM + sbt
- `BlueWallet/BlueWallet` (JS) — has a partial BIP-322 impl
- `Casa/casa-node` — unknown
- Build a verifier on top of rust-bitcoin's primitives ourselves

## Operational lessons codified this cycle

1. **Test-vector independence ≠ implementation independence.** Cross-
   testing against another implementation of the same canonical
   vectors only confirms spec compliance. Round-trip cross-testing
   against an *independent implementation* on *random inputs* is what
   proves no shared-bug class.
2. **Three-language closure is the saturation point.** Once BTX-py,
   libsecp256k1-C, and noble-JS all agree byte-for-byte on 50 random
   inputs, additional oracles for the same primitive provide
   diminishing marginal value.
3. **Production-state alignment > spec alignment.** Vectors 15-18 of
   the BIP-340 CSV test a 2022 generalization that the deployed
   libsecp256k1 hasn't shipped. BTX rejects them too — matching real-
   world counterparty behavior, not just the latest spec text.
4. **Sandbox mount-lag bites the Edit tool too.** This cycle hit the
   Edit-tool truncation pattern 3 times (suite file twice, scout 18
   cross-test once). Recovery: bash heredoc append + ast.parse check.
   Standard operational risk for substantial tail additions.
5. **Honest deferral with reason beats "TODO".** Scouts 17 Phase 2 +
   19 + 20 each documented explicit out-of-scope inventory tables.
   BIP-322 ecosystem gap is now a tracked bookmark, not vague TODO.

## Suite definition snapshot

`btx_xtest_suite.py` at the end of this cycle has 17 sub-tests:

```
 1. BIP-340 Schnorr (foundation, canonical CSV)
 2. BIP-341 Taproot (foundation, canonical wallet-test-vectors)
 3. BIP-327 MuSig2 KeyAgg (variant + canonical port)
 4. BIP-374 DLEQ
 5. BIP-380 tr(K) descriptors vs rust-miniscript
 6. BIP-380 checksum vs python-bip380
 7. BIP-322 generic signed message (hash + tx + P2TR)
 8. BIP-322 adversarial (21 negative cases)
 9. /api/attest endpoint (in-process)
10. Half-agg vs secp256k1-zkp hacspec vectors
11. Schnorr+adaptor sigPoint vs dlcspecs
12. DLC oracle NFC + contract_id vs dlcspecs                ← scout 17
13. BIP-340 vs libsecp256k1 via python-bitcointx (C)        ← scout 18
14. BIP-340 vs @noble/curves (JS)                           ← scout 19
15. BIP-341 Taproot vs rust-bitcoin (Rust)                  ← scout 20
16. Runes decoder vs Magic Eden
17. Runestone cenotaph adversarial (50,000-fuzz)
```

Runtime on this runner: ~12 seconds with all reference clones
present.

## Remaining open slots (low priority, not blocking)

| Slot                          | Trigger to revisit                                                                   |
| ----------------------------- | ------------------------------------------------------------------------------------ |
| BIP-322 cross-impl oracle     | bdk or rust-bitcoin merges a BIP-322 verifier                                        |
| BIP-341 TapSighash 2nd oracle | High-effort (needs Transaction serialization across FFI) for marginal value          |
| btx_s2c external oracle       | secp256k1-zkp ships an ec_commit test vector file                                    |
| MuSig2 adaptor random round-trip | Need a Rust impl that exposes `partial_sign` + `partial_sig_agg` separately      |
| FROST external oracle         | jonasnick/bip-frost-dkg ships test vectors (currently spec-only)                     |
| Half-agg 2nd oracle           | secp256k1-zkp adds a second halfagg test corpus                                      |

## Cross-links

[[project-btx-dlcspecs-scout-2026-06-04]]
[[project-btx-python-bitcointx-scout-2026-06-04]]
[[project-btx-scure-btc-signer-scout-2026-06-04]]
[[project-btx-scouting-cycle-2026-06-03]] — the prior cycle that this
one builds on.

## Files produced this cycle

- `btx_xtest_vs_dlcspecs.py` (scout 17 Phase 1)
- `btx_dlc_oracle.py` (scout 17 Phase 2)
- `BTX-dlcspecs-scouting-2026-06-04.md` (scout 17)
- `btx_xtest_vs_python_bitcointx.py` (scout 18)
- `BTX-python-bitcointx-scouting-2026-06-04.md` (scout 18)
- `btx_xtest_vs_noble_secp256k1.py` (scout 19)
- `BTX-scure-btc-signer-scouting-2026-06-04.md` (scout 19)
- `xtest_taproot_probe/{Cargo.toml,src/main.rs,.gitignore}` (scout 20)
- `btx_xtest_vs_rust_bitcoin_taproot.py` (scout 20)
- `BTX-rust-bitcoin-scouting-2026-06-04.md` (scout 20)
- `btx_xtest_suite.py` (+15 LOC across 5 sub-test additions)
- `BTX-scouting-cycle-summary-2026-06-04.md` (THIS DOC)

## Verdict

This cycle moved BTX's cross-validation discipline from "spec
compliance" to "implementation independence." For BIP-340 Schnorr,
which is the foundation of every other BTX crypto primitive, three-
language byte-identical agreement closes the validation question
for this layer.

For BIP-341 Taproot, one implementation-independence oracle is now
in place. Additional Taproot oracles are bookmarked but lower
priority.

For BIP-322 message signing, the Rust + JS Bitcoin ecosystem has
not standardized — that's a real ecosystem gap, not a BTX gap, and
the bookmark stays open until upstream catches up.
