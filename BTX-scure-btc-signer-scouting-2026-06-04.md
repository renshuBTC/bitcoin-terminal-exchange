# Scouting report — `paulmillr/scure-btc-signer` + `@noble/curves`

*Nineteenth scout. Domain: pure-JavaScript BIP-340 implementation
independence (third language in the closure).*

Date: 2026-06-04.

## Why this repo

Scout 18 (python-bitcointx → libsecp256k1) gave BTX its first
implementation-independence Schnorr oracle: BTX (pure-Python) matched
libsecp256k1 (C) byte-for-byte on every signature for arbitrary
inputs. That ruled out one class of shared-bug failures.

But two implementations agreeing doesn't tell you which one is right
if a third disagrees. The strongest form of cross-implementation
validation is **agreement across three independent implementations in
three different languages**, because then any pair of two agreeing
identifies the buggy one.

`paulmillr/scure-btc-signer` is Paul Miller's audited modern Bitcoin
signing library. It delegates Schnorr to `@noble/curves`, his pure-
JavaScript secp256k1 implementation. `@noble/curves` has zero
dependence on libsecp256k1 — it implements secp256k1 + BIP-340 from
scratch in TypeScript. That's the third independent codebase BTX
needs.

## Strategic verdict

| Surface                  | Verdict                                                                                                              |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| BIP-340 Schnorr (@noble) | **SHIPPED** — 6th oracle, third language. BTX-py = libsecp256k1-C = noble-JS byte-identical                          |
| BIP-341 Taproot          | DEFER — same canonical wallet-test-vectors.json BTX already validates against; would only confirm spec-compliance     |
| BIP-327 MuSig2           | DEFER — same canonical key_agg_vectors.json BTX already validates against                                             |
| BIP-174 PSBT             | DEFER — BTX speaks BTX2 envelope, not PSBT                                                                            |
| BIP-322 message signing  | DEFER — **absent** from scure-btc-signer despite README claims; not present in source                                 |
| P2P (BIP-324)            | DEFER — BTX doesn't run a peer; delegates network to Bitcoin Core node                                                |

## Cross-test shipped this session

`btx_xtest_vs_noble_secp256k1.py` (~270 LOC, wired as 16th sub-test).

The mechanism: spawns Node with an inline JavaScript bridge that
imports `@noble/curves`, reads JSON-encoded sign/verify requests from
stdin, returns JSON-encoded results. Python harness batches all
requests in one Node invocation (one-shot ~150ms startup, then 65
vectors). Skips gracefully if Node or `@noble/curves` not available.

### Results

**A. Canonical bitcoin/bips BIP-340 CSV (19 vectors):**
- 15 in-scope: noble + BTX both produce byte-identical signatures vs
  spec; both cross-verify the spec sig and each other's sig (15/15).
- 4 scoped out (msg sizes 0/1/17/100): same as scout 18 — noble also
  rejects variable-length per pre-2022 BIP-340 semantics. All three
  implementations match production-state behavior.

**B. 50 random `(sk, msg, aux_rand)` round-trips:**
- BTX and noble produce **byte-identical** signatures every time
  (50/50). BTX verifies every noble-produced signature. Tamper-bit
  rejection consistent.

**Combined with scout 18:** BTX (Python) === libsecp256k1 (C) ===
@noble/curves (JS) on 50 random inputs. Three independent codebases
in three languages, byte-for-byte agreement.

### What this rules out beyond scout 18

Scout 18 caught a class of bugs where BTX and libsecp256k1 might both
have a hidden shared algorithm error (unlikely but possible — they're
both BIP-340 implementations after all). Scout 19 rules out a
narrower but still possible class: BTX and libsecp256k1 happen to
share a deterministic-input-handling quirk inherited from the spec
reference Python, that noble would expose. Three-way agreement
across three languages is the strongest non-formal validation of
implementation correctness BTX has access to.

## What was NOT in scure-btc-signer

The README claims a broad feature set including BIP-322. **There is
no BIP-322 implementation in the source.** `grep -ri "bip.?322" src/`
returns zero hits. Same for `@noble/curves`. So BTX's BIP-322 message
signing remains validated against only one external oracle (the
canonical bitcoin/bips basic-test-vectors.json from scout 16).
Bookmark: a focused BIP-322 cross-validation oracle remains an open
slot in the suite.

## Schnorr oracle count: 6 total, 2 implementation-independence

| # | Oracle                                | Independence type   |
| - | ------------------------------------- | ------------------- |
| 1 | Bitcoin Core BIP-340 CSV              | canonical vectors   |
| 2 | secp256kfun (Lloyd Fournier)          | canonical vectors   |
| 3 | dlcspecs Schnorr math layer           | canonical vectors   |
| 4 | dlcspecs oracle bytes layer           | canonical vectors   |
| 5 | python-bitcointx → libsecp256k1 (C)   | **implementation**  |
| 6 | @noble/curves (pure JS)               | **implementation**  |

Oracles 5 and 6 are qualitatively different: they cross-test on
arbitrary random inputs, not just on the test corpus.

## Suite expansion this scout

- Pre-scout: 15 sub-tests
- Post-scout: **16 sub-tests** (15/16 → 16/16 green on this runner)

## Setup notes

In any sandbox without an existing scure-btc-signer clone:
```
git clone https://github.com/paulmillr/scure-btc-signer \
  "Bitcoin CoreX/scure-btc-signer-reference"
cd "Bitcoin CoreX/scure-btc-signer-reference"
npm install
python3 btx_xtest_vs_noble_secp256k1.py
```

The cross-test invokes `node --experimental-strip-types --input-type=
module -e <inline JS>` so it needs Node 22+ (sandbox has 22.22.0).

## Source

Repo: <https://github.com/paulmillr/scure-btc-signer>
Dependency examined: `@noble/curves` (transitively, via scure)
Maintainer: Paul Miller (@paulmillr)
License: MIT (scure-btc-signer) + MIT (noble-curves)
Examined: master HEAD at clone time 2026-06-04 (~v1.x).

## Cross-links

[[project-btx-python-bitcointx-scout-2026-06-04]] — scout 18, the
libsecp256k1 oracle this scout's third-language closure complements.
[[project-btx-dlcspecs-scout-2026-06-04]] — scout 17.
[[project-btx-scouting-cycle-2026-06-03]] — the prior 15-scout cycle.

## Files

- `bitcoin-terminal-exchange/btx_xtest_vs_noble_secp256k1.py` (NEW)
- `bitcoin-terminal-exchange/btx_xtest_suite.py` (+5 LOC, 16th sub-test)
- `bitcoin-terminal-exchange/BTX-scure-btc-signer-scouting-2026-06-04.md`
  (THIS DOC)
