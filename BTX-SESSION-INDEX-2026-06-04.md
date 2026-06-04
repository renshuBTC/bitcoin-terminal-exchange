# BTX 2026-06-04 session — navigable index

A single document indexing 12 external scouts + 4 BTX-side engineering
tasks shipped this session, with operational rules codified for future
sessions.

## Quick stats

- **24 commits pushed** to `bitcoin-terminal-exchange/main`
- **12 external scouts** (cross-validation oracles)
- **4 BTX-side engineering tasks** (Sparrow/Trezor interop + all 8
  BIP-327 vector files)
- **Suite: 12 → 28 sub-tests**
- **Bookmark-accuracy this session: 1 of 7 = 14%** — the dominant
  operational lesson

## Index by commit

| Commit | Title |
| ------ | ----- |
| `ae6d665` | Scout 17 Phase 1: dlcspecs Schnorr 5×5 |
| `6b24d91` | Scout 17 Phase 2: dlcspecs NFC + contract_id |
| `422235b` + `cf1749f` | Scout 18: python-bitcointx (libsecp256k1) |
| `45e7d11` | Scout 19: scure-btc-signer / @noble (JS) |
| `c8a79d0` | Scout 20: rust-bitcoin Taproot |
| `06118fb` + `42c7af9` | Scout 21: bip322-js (BIP-322) |
| `9a6093a` | Scout 22: secp256k1lab (Jonas Nick reference) |
| `a9c6e21` | Scout 23: BIP-327 KeySort |
| `97953c1` | Scout 24: rust-bitcoin TapSighash |
| `7de7fbc` | Scout 25: secp256kfun FROST |
| `2b2602f` | Scout 26: secp256kfun adaptor |
| `263b47f` | Scout 27: btx_s2c is BIP-340-valid |
| `118f529` | Scout 28: MuSig2 pool-sign is BIP-340-valid |
| `ffcb7b6` | Cycle summary scouts 17-20 |
| `0103f00` | Cycle 2 saturation doc (prematurely declared) |
| `95e240f` | Cycle 2 FINAL (after scouts 24-28 falsified bookmarks) |
| `00d2468` | **Task A**: BIP-322 SIGHASH_ALL verify |
| `c281d8d` | Task B scope deferral (later overruled) |
| `8c8a45f` | **Task B Phase 1**: MuSig2 nonce_gen + nonce_agg |
| `3519bfe` | **Task B Phases 2+3**: sign_verify + sig_agg + tweak + det_sign |
| `cd0b68d` | Task C: BIP-322 NONE/SINGLE probe (correctly deferred) |
| `b00e262` + `fab0663` | btx_bip322 mount-lag tail repairs |

## Final suite state — 28 sub-tests

| # | Sub-test | Oracle type |
| - | -------- | ----------- |
| 1 | BIP-340 Schnorr canonical CSV | spec |
| 2 | BIP-341 Taproot canonical | spec |
| 3 | BIP-327 KeyAgg + KeySort (scout 23 amendment) | spec |
| 4 | BIP-374 DLEQ | spec |
| 5 | BIP-380 tr(K) descriptors vs rust-miniscript | impl-indep Rust |
| 6 | BIP-380 checksum vs python-bip380 | spec |
| 7 | BIP-322 generic + P2TR sign/verify | spec |
| 8 | BIP-322 adversarial 21 negative cases | spec |
| 9 | /api/attest endpoint | self |
| 10 | Half-agg vs secp256k1-zkp | spec (1 of 1 — truly blocked) |
| 11 | Schnorr+adaptor sigPoint vs dlcspecs | spec |
| 12 | DLC oracle NFC + contract_id (scout 17) | spec |
| 13 | BIP-340 vs libsecp256k1 (scout 18) | **impl-indep C** |
| 14 | BIP-340 vs @noble/curves (scout 19) | **impl-indep JS** |
| 15 | BIP-341 tap_tweak vs rust-bitcoin (scout 20) | **impl-indep Rust** |
| 16 | BIP-322 vs bip322-js (scout 21) | **impl-indep JS** |
| 17 | BIP-340 vs secp256k1lab (scout 22) | auth-reference |
| 18 | BIP-341 TapSighash vs rust-bitcoin (scout 24) | **impl-indep Rust** |
| 19 | FROST vs secp256kfun (scout 25) | consensus-level Rust |
| 20 | Schnorr adaptor vs secp256kfun (scout 26) | **impl-indep Rust** |
| 21 | btx_s2c is BIP-340-valid (scout 27) | consensus-level C |
| 22 | MuSig2 pool-sign is BIP-340-valid (scout 28) | consensus-level C |
| 23 | BIP-322 SIGHASH_ALL vs bip322-js (Task A) | wallet interop |
| 24 | BIP-327 nonce_gen + nonce_agg (Task B Ph1) | spec, BIP-327 wrapper |
| 25 | BIP-327 sign_verify + sig_agg (Task B Ph2) | spec, BIP-327 wrapper |
| 26 | BIP-327 tweak + det_sign (Task B Ph3) | spec, BIP-327 wrapper |
| 27 | Runes vs Magic Eden | spec |
| 28 | Runestone cenotaph 50k-fuzz | self |

## Implementation-independence oracles by primitive

| Primitive | Spec oracles | Impl-indep oracles | Languages |
| --------- | ------------ | ------------------ | --------- |
| BIP-340 Schnorr | 4 | 2 (C + JS) + auth-ref | Py, C, JS |
| BIP-341 Taproot tweak | 1 | 1 (Rust) | Py, Rust |
| BIP-341 TapSighash | 1 | 1 (Rust) | Py, Rust |
| BIP-322 message signing | 1 | 1 (JS) | Py, JS |
| BIP-327 MuSig2 (all 8 vectors) | 8 | (wrapper) | Py |
| BIP-374 DLEQ | 1 | none | Py |
| BIP-380 descriptors | 3 | 1 (Rust) | Py, Rust |
| Schnorr adaptor | 2 | 1 (Rust) | Py, Rust |
| DLC oracle | 2 | (vectors) | Py |
| FROST signing | 0 | 1 consensus-level Rust | Py, Rust |
| Half-aggregation | 1 | (TRULY BLOCKED) | Py |
| btx_s2c | 0 | 1 consensus-level C | Py, C |
| MuSig2 pool-sign | 0 | 1 consensus-level C | Py, C |
| Runes decoder | 2 | (vectors) | Py |

## Genuinely-blocked slots

Only **one** bookmark across this session was correctly "blocked":

**Half-aggregation 2nd oracle** — Verified by grep across rust-bitcoin,
bdk, secp256kfun, and @noble/curves that nobody else implements
BIP-340 halfagg. secp256k1-zkp's `schnorrsig_halfagg` is the sole
existing implementation. Bookmark stays open until a second
implementation appears in the Bitcoin ecosystem.

## Honestly-deferred slots (BTX-side work, not external)

**BIP-322 SIGHASH_NONE/SINGLE verify** — Task C probe confirmed
extending the verify_simple_p2tr allowlist is insufficient because
`btx_taproot.tap_sighash` computes all-outputs sigMsg regardless of
hash_type. Real-world relevance minimal (no major attestation tool
defaults to NONE/SINGLE). Inline comment in `btx_bip322.py` documents
the probe findings and scope-future-work.

## Operational rules codified to memory

### Rule 1: Don't trust "blocked" bookmarks

**Evidence: 1 of 7 = 14% accuracy this session.** Of seven "blocked"
or "high-effort vs marginal value" claims:

| Bookmark | Reality | Source |
| -------- | ------- | ------ |
| BIP-322 ecosystem gap | bip322-js exists | scout 21 |
| BIP-341 TapSighash 2nd oracle | 7/7 in 250 LOC | scout 24 |
| FROST signing | 10/10 in 80 LOC Rust | scout 25 |
| MuSig2 adaptor random | 10/10 in 30 LOC Rust | scout 26 |
| btx_s2c external oracle | 30/30 in 80 LOC | scout 27 |
| MuSig2 inner-functions ~300 LOC | actually ~675 LOC across 3 phases via wrapper | Task B |
| Half-agg 2nd oracle | truly blocked | (correct) |

The protocol when encountering a "blocked" bookmark:
1. Spend 5-15 minutes searching for a minimal probe target
2. If any major library exposes the relevant API, try a wrapper
3. Only declare blocked after grepping rust-bitcoin, bdk, secp256kfun,
   @noble/curves, libsecp256k1, and BTX itself returns nothing
4. **Default assumption: the bookmark is wrong**

### Rule 2: The 5-step wrapper-then-cross-test recipe

Proven across TapSighash (24), FROST (25), adaptor (26), s2c (27),
MuSig2 pool-sign (28), and MuSig2 Phases 1-3 (Task B). Six distinct
primitives, same recipe:

1. **Locate upstream reference** (BIP-327 reference.py, secp256kfun,
   rust-bitcoin, libsecp256k1, bip322-js, etc.)
2. **Write a ~30-50 LOC wrapper** exposing what BTX needs as BTX-style
   API. Path-finding for the reference. Graceful skip if absent.
3. **Write a cross-test** running canonical vectors against the
   wrapper
4. **Confirm byte-for-byte PASS** on all vectors
5. **Document scope-for-future-from-scratch-port** in the wrapper
   docstring

When BTX eventually needs its own port (e.g., for the brk-btx Rust
indexer to verify partial signatures without a Python runtime), the
wrapper API surface defines exactly what the from-scratch impl must
match byte-for-byte.

### Rule 3: Sandbox mount-lag pattern (Edit tool)

Hit 5+ times this cycle on grown files (suite, cross-tests, btx_bip322).
Recovery sequence:
1. Repair via `bash heredoc` append
2. Verify via `python3 -c "import ast; ast.parse(...)"`
3. Run the affected module to confirm runtime behavior
4. If still broken, dedupe orphan partial lines (the
   double-append-after-truncation pattern)

For substantial tail additions (>50 LOC), prefer Write tool over Edit.

### Rule 4: "Production state > spec text" for crypto verifiers

Established by scout 18: BIP-340 CSV vectors 15-18 test a 2022 spec
generalization that the deployed libsecp256k1 hasn't shipped. BTX
rejects them → matches production behavior, not just spec text.

When a spec update isn't in production deployments, BTX's defensive
behavior matching production is the correct stance. Bookmark spec-
conformance updates for "when upstream libraries adopt them."

### Rule 5: Bookmark accuracy applies to MY OWN scoping

Task B was a vivid example: I wrote a "scope deferral" doc claiming
~300-400 LOC + state machine + 2-3 sessions. Actual ship was ~675
LOC across 3 phases in this same session via the wrapper pattern.

The bookmark-accuracy heuristic isn't only for upstream claims — it
applies to MY OWN scoping decisions. When I say "this is too big for
this session", probe it anyway.

## Next-session priorities (when applicable)

Roughly ordered by impact:

1. **Wait for a 2nd Schnorr halfagg implementation** to appear in any
   major Bitcoin library. Watch: rust-bitcoin, bdk, secp256kfun,
   @noble/curves issue trackers. Trigger: anyone implements BIP-340
   half-aggregation → ship cross-test in ~30 LOC.

2. **brk-btx Rust-side MuSig2 verification** — for when the indexer
   needs to verify partial signatures without a Python runtime. The
   wrapper API from `btx_musig2_bip327_protocol` defines what the
   Rust port must match.

3. **Lift the `len(msg) != 32` constraint in btx_taproot.schnorr_sign**
   if/when libsecp256k1 ships the 2022 BIP-340 variable-length message
   generalization. Bookmarked in scout 18 doc.

4. **BIP-322 SIGHASH_NONE/SINGLE verify** if/when a real counterparty
   sends BTX a SIGHASH_NONE attestation. Currently no real-world demand.

5. **DLC oracle implementation-independence oracle** — bitcoin-s
   (Scala, Nadav Kohen) has DLC. Would require JVM + sbt setup in
   sandbox. Defer until needed.

## Cross-links to per-scout / per-task memory entries

All entries in `~/memory/`:
- project_btx_dlcspecs_scout_2026-06-04.md (scout 17)
- project_btx_python_bitcointx_scout_2026-06-04.md (scout 18)
- project_btx_scure_btc_signer_scout_2026-06-04.md (scout 19)
- project_btx_rust_bitcoin_scout_2026-06-04.md (scout 20)
- project_btx_bip322_js_scout_2026-06-04.md (scout 21)
- project_btx_secp256k1lab_scout_2026-06-04.md (scout 22)
- project_btx_scouts_23_24_2026-06-04.md (scouts 23+24)
- project_btx_scouts_25_27_2026-06-04.md (scouts 25-27, MEMORY-INDEX entry)
- project_btx_scouting_cycle_2026-06-04.md (cycle summary doc — superseded by FINAL)
- project_btx_bip322_sighash_all_2026-06-04.md (Tasks A + B + scope)

Plus on-repo docs:
- BTX-dlcspecs-scouting-2026-06-04.md
- BTX-python-bitcointx-scouting-2026-06-04.md
- BTX-scure-btc-signer-scouting-2026-06-04.md
- BTX-rust-bitcoin-scouting-2026-06-04.md
- BTX-bip322-js-scouting-2026-06-04.md
- BTX-scouting-cycle-summary-2026-06-04.md (scouts 17-20)
- BTX-cycle2-saturation-2026-06-04.md (prematurely declared at scout 23)
- BTX-cycle2-FINAL-2026-06-04.md (after scouts 24-28 + Task A)
- BTX-musig2-bip327-refactor-scope-2026-06-04.md (Task B scope, later overruled)
- **BTX-SESSION-INDEX-2026-06-04.md (THIS DOC)**

## Verdict

The autonomous loop has produced 24 commits, expanded the cross-
validation suite by 16 sub-tests, codified five operational rules,
and reached genuine saturation. Future sessions inherit:

- A 28-sub-test cross-validation suite with three primitives at
  implementation-independence (BIP-340 saturated at 7 oracles
  including 3-language closure; BIP-341 and BIP-322 each with one
  impl-indep oracle)
- A complete BIP-327 wrapper covering all 8 vector files
- A working BIP-322 SIGHASH_ALL verify path for Sparrow/Trezor interop
- A 5-step wrapper recipe for any future "blocked" primitive
- Five operational rules in force, with strong empirical backing

The bookmark-accuracy heuristic (14% this cycle) is the single most
important lesson. Future cycles default to "the bookmark is wrong" and
probe before deferring.
