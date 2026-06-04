# BTX cycle 2 FINAL closure — 12 scouts, 0 remaining external bookmarks

Supersedes `BTX-cycle2-saturation-2026-06-04.md` which prematurely
declared saturation at scout 23. After scouts 24-28 were attempted
under the principle "try a minimal probe before trusting 'blocked'",
**four more bookmarks closed** and one was verified genuinely
unsolvable in current Bitcoin libraries.

## Twelve scouts shipped this cycle

| # | Repo / Source                                | Domain                          | Result                                      | Commit       |
| - | -------------------------------------------- | ------------------------------- | ------------------------------------------- | ------------ |
| 17 | `discreetlogcontracts/dlcspecs`             | DLC oracle bytes + Schnorr     | 25/25 + 24/24                               | ae6d665+6b24d91 |
| 18 | `Simplexum/python-bitcointx`                | BIP-340 vs libsecp256k1 (C)    | 15/15 + 50/50                               | 422235b+cf1749f |
| 19 | `paulmillr/scure-btc-signer` (@noble)       | BIP-340 vs noble (JS)          | three-language closure                      | 45e7d11      |
| 20 | `rust-bitcoin/rust-bitcoin` (Taproot)       | BIP-341 tap_tweak vs Rust      | 7/7 + 50/50                                 | c8a79d0      |
| 21 | `ACken2/bip322-js` (npm)                    | BIP-322 vs JS package          | 30/30 + 10/10 tamper-reject                | 06118fb+42c7af9 |
| 22 | `BlockstreamResearch/bip-frost-dkg`         | BIP-340 vs secp256k1lab        | 15/15 + 30/30                               | 9a6093a      |
| 23 | `bitcoin/bips/bip-0327` (KeySort)           | BIP-327 KeySort                | 6/6                                         | a9c6e21      |
| 24 | `rust-bitcoin/rust-bitcoin` (sighash)       | BIP-341 TapSighash vs Rust     | 7/7 + 7/7                                   | 97953c1      |
| 25 | `LLFourn/secp256kfun` (FROST)               | FROST signing consensus        | 10/10                                       | 7de7fbc      |
| 26 | `LLFourn/secp256kfun` (adaptor)             | Schnorr adaptor consensus      | 10/10                                       | 2b2602f      |
| 27 | libsecp256k1 + BTX-side                     | btx_s2c output is BIP-340      | 30/30                                       | 263b47f      |
| 28 | libsecp256k1 + BTX-side                     | MuSig2 pool-sign is BIP-340    | 10/10 across sizes 2/3/5/7                  | 118f529      |

## Cross-validation suite

**12 → 24 sub-tests.** Every primitive BTX ships now has at least one
external oracle:

| Primitive                       | Oracles | Impl-independence |
| ------------------------------- | ------- | ----------------- |
| BIP-340 Schnorr                 | 7       | YES (C + JS)      |
| BIP-341 Taproot tweak           | 2       | YES (Rust)        |
| BIP-341 TapSighash              | 2       | YES (Rust)        |
| BIP-322 message signing         | 2       | YES (JS)          |
| BIP-327 MuSig2 KeyAgg + KeySort | 2 of 8  | partial           |
| BIP-374 DLEQ                    | 1       | no                |
| BIP-380 descriptors             | 3       | YES (Rust + Py)   |
| Schnorr adaptor                 | 3       | YES (Rust)        |
| DLC oracle                      | 2       | (vectors only)    |
| FROST signing                   | 1       | consensus-level Rust |
| Half-aggregation                | 1       | (genuinely blocked) |
| Sign-to-contract (btx_s2c)      | 1       | consensus-level C |
| MuSig2 pool-sign                | 1       | consensus-level C ← scout 28 |
| Runes decoder                   | 2       | (vectors only)    |

## Bookmark accuracy

The cycle-2-saturation doc (scout-23-era) listed 5 open slots as
"blocked" or "high-effort". When actually attempted with minimal
probes:

| Bookmark                          | Cycle 2 said    | Reality      |
| --------------------------------- | --------------- | ------------ |
| BIP-341 TapSighash 2nd oracle     | "high-effort"   | 7/7 in 250 LOC (scout 24) |
| FROST signing                     | "blocked"       | 10/10 in ~80 LOC Rust (scout 25) |
| MuSig2 adaptor random             | "blocked"       | 10/10 in ~30 LOC Rust (scout 26) |
| btx_s2c external oracle           | "blocked"       | 30/30 in ~80 LOC Py (scout 27) |
| Half-agg 2nd oracle               | "blocked"       | **truly blocked** — verified no other impl exists |

**Bookmark accuracy: 1 of 5 = 20%.** The "blocked" assessments were
systematically wrong.

## Genuinely-blocked slots

Only ONE bookmark from the cycle 2 saturation doc was correct in
claiming "blocked":

- **Half-aggregation 2nd oracle**: Verified by grep across rust-
  bitcoin, bdk, secp256kfun, and @noble/curves that nobody else
  implements BIP-340 half-aggregation. secp256k1-zkp's
  schnorrsig_halfagg is the sole implementation. Bookmark stays open
  until a second implementation exists.

## Remaining open slots that aren't really external scouting

| Slot                                 | Nature                                          |
| ------------------------------------ | ----------------------------------------------- |
| 6 of 8 BIP-327 inner-function vectors | needs btx_musig2 refactor (BTX-side work)      |
| BIP-322 SIGHASH_ALL verify           | needs BTX `verify_simple_p2tr` extension       |

Both require BTX-side code changes, not external scouting effort.
They're tracked as feature work, not as cross-validation gaps.

## Operational rule codified for future cycles

**Bookmark accuracy this cycle: 1/5 = 20%. Do not trust "blocked"
claims.**

The protocol for handling a "blocked" or "high-effort" bookmark is:

1. Spend 5 minutes searching for a minimal probe target
2. If a probe is plausible (any external library exposes the relevant
   API), try it
3. Only after a genuine search across major libraries (rust-bitcoin,
   bdk, secp256kfun, @noble/curves, libsecp256k1, BTX-itself) returns
   nothing should "blocked" be declared

The bookmarks-are-wrong-by-default heuristic is now a permanent
operational rule.

## Three-language + consensus-level oracle inventory

By language:
- **Python (from-scratch):** BTX reference
- **Python (authoritative):** secp256k1lab (Jonas Nick)
- **C:** libsecp256k1 (used by Bitcoin Core itself, accessed via
  python-bitcointx + coincurve)
- **Rust:** rust-bitcoin (Taproot tweak + sighash), secp256kfun
  (FROST, adaptor)
- **TypeScript:** @noble/curves (Schnorr), bip322-js (BIP-322)
- **Scala / Kotlin / Java:** not yet wired (bookmark for if BTX
  wants byte-for-byte against bitcoin-s)

By validation type:
- **Spec-vector oracles:** 10+ (canonical bitcoin/bips files, dlcspecs
  vectors, BIP-340 CSV, BIP-341 wallet-test-vectors, BIP-327 KeyAgg
  vectors, BIP-374 CSV, BIP-380 descriptors corpus, Runes 19 goldens,
  Runestone 50k-fuzz)
- **Implementation-independence (random-input byte-identical):**
  5 oracles (libsecp256k1, @noble, secp256k1lab, rust-bitcoin tweak,
  rust-bitcoin sighash)
- **Consensus-level (BTX output accepted by external verifier on
  random inputs):** 4 oracles (FROST, adaptor, s2c, MuSig2 pool-sign)

## Verdict

The relevant-repos space for BTX cross-validation is **truly mined**
as of 2026-06-04. Every primitive BTX ships has at least one
external oracle. Twelve scouts in the cycle. Every "blocked"
bookmark from the cycle 2 saturation doc except one (half-agg)
turned out tractable when actually probed.

The next cross-validation wins will require:
- A second BIP-340 half-aggregation implementation to appear in
  upstream Bitcoin libraries
- BTX-side refactoring (btx_musig2 internal-function exposure,
  btx_bip322 SIGHASH_ALL verify path)
- New BTX primitives requiring fresh oracles

Until then, the suite at 24 sub-tests is the stable saturated state.

## Cross-links

[[project-btx-scouts-25-27-2026-06-04]] — scouts 25-27 closure
[[project-btx-scouts-23-24-2026-06-04]] — scouts 23-24 closure
[[project-btx-scouting-cycle-2026-06-04]] — original cycle 2 summary
(scouts 17-20)

## Commit

`118f529` — "Scout 28: BTX MuSig2 pool-sign consensus-level cross-test"
