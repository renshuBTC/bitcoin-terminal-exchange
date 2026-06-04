# BTX scouting cycle 2 — saturation reached 2026-06-04

This document closes the 2026-06-04 scouting cycle (scouts 17-23). The
session began as an autonomous "keep going" loop and concluded when
every remaining open slot was either closed by an in-session ship or
documented as blocked on upstream availability with explicit revisit
triggers.

## Seven scouts shipped this cycle

| # | Repo / Source                              | Domain                          | Result                                            | Commits                  |
| - | ------------------------------------------ | ------------------------------- | ------------------------------------------------- | ------------------------ |
| 17 | `discreetlogcontracts/dlcspecs`           | DLC oracle bytes + Schnorr     | 25/25 + 24/24                                     | ae6d665 + 6b24d91        |
| 18 | `Simplexum/python-bitcointx`              | BIP-340 vs libsecp256k1 (C)    | 15/15 + 50/50 byte-identical                      | 422235b + cf1749f        |
| 19 | `paulmillr/scure-btc-signer` + @noble     | BIP-340 vs noble (JS)          | three-language closure                            | 45e7d11                  |
| 20 | `rust-bitcoin/rust-bitcoin`               | BIP-341 vs rust-bitcoin (Rust) | 7/7 + 50/50 byte-identical                        | c8a79d0                  |
| 21 | `ACken2/bip322-js` (npm)                  | BIP-322 vs bip322-js           | 30/30 accept + 10/10 tamper-reject                | 06118fb + 42c7af9        |
| 22 | `BlockstreamResearch/bip-frost-dkg`       | BIP-340 vs secp256k1lab (auth) | 15/15 + 30/30 byte-identical                      | 9a6093a                  |
| 23 | `bitcoin/bips/bip-0327` (key_sort)        | BIP-327 KeySort                | 6/6 lex sort match                                | a9c6e21                  |
| — | Cycle docs                                 |                                | —                                                 | ffcb7b6                  |

## Cross-validation suite evolution

| Stage                              | Sub-tests | Status   |
| ---------------------------------- | --------- | -------- |
| Pre-cycle (post-BIP-322 scout 16) | 12        | green    |
| Post-scout-17 (dlcspecs Phase 2)  | 14        | green    |
| Post-scout-18 (python-bitcointx)  | 15        | green    |
| Post-scout-19 (scure/noble)       | 16        | green    |
| Post-scout-20 (rust-bitcoin)      | 17        | green    |
| Post-scout-21 (bip322-js)         | 18        | green    |
| Post-scout-22 (secp256k1lab)      | 19        | green    |
| Post-scout-23 (KeySort amendment) | **19**    | **green** |

## Oracle inventory by primitive (cycle 2 end state)

| Primitive                | Total Oracles | Implementation-Independence? |
| ------------------------ | ------------- | ----------------------------- |
| BIP-340 Schnorr          | **7**         | YES (libsecp256k1-C + noble-JS) |
| BIP-341 Taproot          | **2**         | YES (rust-bitcoin Rust)         |
| BIP-322 message signing  | **2**         | YES (bip322-js)                 |
| BIP-327 MuSig2 KeyAgg    | 1 (+ KeySort) | no                              |
| BIP-374 DLEQ             | 1             | no                              |
| BIP-380 descriptors      | 3             | YES (rust-miniscript + python-bip380) |
| Schnorr adaptor          | 2             | (vectors only)                  |
| DLC oracle               | 2             | (vectors only)                  |
| Half-aggregation         | 1             | no                              |
| Sign-to-contract (s2c)   | **0**         | (blocked — zkp is ECDSA-only)   |
| MuSig2 adaptor           | **0**         | (blocked)                       |
| FROST signing            | **0**         | (blocked — vectors are DKG-only) |
| Runes decoder            | 2             | (vectors only)                  |

## Bookmarks closed this cycle

1. **BIP-322 cross-implementation oracle** — scouts 19+20+cycle1summary
   declared this a "Rust + JS ecosystem gap" (no major library had
   BIP-322). Scout 21 found `bip322-js` (npm) which fills the gap and
   is what Exodus Wallet ships in production.

2. **secp256k1lab oracle wiring** — sat open since the 2026-06-03 cycle
   memory ("Jonas Nick's secp256k1lab/bip340.py available but not yet
   wired"). Scout 22 closed it after locating the code at its new
   home (`BlockstreamResearch/bip-frost-dkg/python/secp256k1lab/`).

3. **dlcspecs Phase 2 (NFC + contract_id)** — scout 17's two-phase
   pattern exhaustively swept all 12 remaining dlcspecs artifacts
   with explicit verdicts.

## Bookmarks confirmed blocked

Documented with explicit revisit triggers in this cycle's per-scout
docs:

| Slot                          | Revisit trigger                                                   |
| ----------------------------- | ----------------------------------------------------------------- |
| BIP-322 SIGHASH_ALL verify    | real counterparty sends BTX a SIGHASH_ALL sig                     |
| BIP-341 TapSighash 2nd oracle | high-effort (Transaction FFI); marginal value                     |
| btx_s2c external oracle       | secp256k1-zkp adds Schnorr s2c (currently ECDSA-only)             |
| MuSig2 adaptor random         | Rust impl exposing partial_sign + partial_sig_agg                 |
| FROST signing oracle          | Rust FROST impl exposing nonce_gen + partial_sign + sig_agg       |
| 6 of 8 BIP-327 vector files   | refactor btx_musig2 to expose internal functions separately       |
| Half-agg 2nd oracle           | secp256k1-zkp adds a second halfagg test corpus                   |

## Three-language closure for BIP-340 Schnorr

This cycle's headline outcome. BTX's pure-Python BIP-340 Schnorr
implementation now produces byte-identical signatures with:

- **C**: libsecp256k1 (via python-bitcointx, the C library Bitcoin
  Core uses in production) — scout 18
- **JavaScript**: @noble/curves (the pure-JS secp256k1 used by
  scure-btc-signer, bitcoinerlab, and most modern JS Bitcoin
  tooling) — scout 19
- **Reference**: secp256k1lab (Jonas Nick's authoritative pure-Python
  BIP reference, what BIP authors use as ground truth) — scout 22

Cross-validated on 50+ random `(sk, msg, aux_rand)` tuples per
implementation, byte-for-byte agreement. This is the strongest non-
formal validation of BIP-340 correctness BTX has access to and the
saturation point — any further BIP-340 oracle is diminishing returns.

## Operational lessons codified

1. **"No big lib has X" ≠ "no lib has X".** Scouts 19+20 declared
   BIP-322 a Rust+JS ecosystem gap based on 4 major libs (rust-
   bitcoin, bdk, scure-btc-signer, @noble/curves) all lacking it.
   Scout 21 found that the actual answer was a **dedicated**
   standalone package (`bip322-js`). Future cycles: don't just survey
   major libs — also search dedicated/standalone packages.

2. **Test-vector independence ≠ implementation independence.** Spec
   compliance can be proven by canonical vectors; implementation
   independence requires round-trip cross-testing on random inputs.

3. **Three-language closure is the saturation point.** Once Py + C
   + JS agree byte-for-byte on 50 random inputs, additional oracles
   for the same primitive give diminishing returns.

4. **Production-state alignment > spec alignment.** BIP-340 CSV
   vectors 15-18 test a 2022 generalization libsecp256k1 hasn't
   shipped. BTX rejects them — matches production behavior.

5. **Edit-tool truncation pattern.** Hit 4 times this cycle on large
   tail additions (suite file + 2 cross-test files + scout 23
   amendment). Rule: prefer Write or bash heredoc; verify with
   ast.parse before commit.

6. **URL pattern shifts.** `jonasnick/bip-frost-dkg` →
   `BlockstreamResearch/bip-frost-dkg`. `jonasnick/secp256k1lab`
   was retired (consolidated into bip-frost-dkg). Worth noting when
   chasing old bookmarks.

7. **Negative findings are deliverables too.** Scout 22 ruled out
   FROST signing vectors in bip-frost-dkg (DKG-only) and Schnorr s2c
   in secp256k1-zkp (ECDSA-only). These rule-outs save future cycles
   from repeating the search.

## Verdict — true saturation

The relevant-repos space for BTX cross-validation is genuinely mined
to saturation as of 2026-06-04. Three primitives (BIP-340, BIP-341,
BIP-322) now have implementation-independence oracles. Every
remaining open slot is blocked on upstream library/test-vector
availability, not on more scouting effort.

The next cross-validation wins will come from:
- Upstream changes (libsecp256k1 ships variable-length BIP-340, zkp
  adds Schnorr s2c, etc)
- Refactoring btx_musig2 to expose internal functions for the
  remaining 6 of 8 BIP-327 vector files
- New BTX primitives requiring fresh oracles

Until any of those happens, the suite at 19/19 PASS green is the
correct stable state.

## Cross-links

[[project-btx-scouting-cycle-2026-06-04]] — earlier cycle summary
covering scouts 17-20 only.
[[project-btx-bip322-js-scout-2026-06-04]] — scout 21 closure
[[project-btx-secp256k1lab-scout-2026-06-04]] — scout 22 closure
[[project-btx-scouting-cycle-2026-06-03]] — prior 15-scout cycle

## Files

This doc + scout-23 amendment, plus all per-scout files from the
17-22 group.

## Commit

`a9c6e21` — "Scout 23 amendment: BIP-327 KeySort vector cross-test"
