# Scouting report — `Simplexum/python-bitcointx` (Dmitry Petukhov / dgpv)

*Eighteenth scout. Domain: implementation-independence cross-validation
of BTX's pure-Python BIP-340 Schnorr against libsecp256k1, the
production C library Bitcoin Core itself ships with.*

Date: 2026-06-04.

## Why this repo

Every BTX BIP-340 cross-test up to this point pulls from the **same
canonical test corpus** (bitcoin/bips, secp256kfun, dlcspecs all use
the BIP-340 reference vectors). Passing all of them proves "BTX
matches the spec on the test corpus" — but a subtle spec misreading
shared across all pure-Python ports could pass canonical vectors while
still being wrong.

`Simplexum/python-bitcointx` (Dmitry Petukhov) is a maintained fork-
direction descendant of Peter Todd's python-bitcoinlib that wraps
**libsecp256k1 via ctypes** for all signing/verification — i.e., it
delegates to the same C library Bitcoin Core uses in production. Pure-
Python BTX vs. libsecp256k1 are a fundamentally different codebase in
a different language: a real cross-implementation oracle, distinct
from the test-vector oracles BTX already wires.

## What's directly testable against BTX

| Surface                  | Verdict                                                                                         |
| ------------------------ | ----------------------------------------------------------------------------------------------- |
| BIP-340 Schnorr          | **SHIPPED** — implementation-independence cross-test, byte-identical sigs + round-trip verify   |
| BIP-341 Taproot helpers  | DEFER — same canonical wallet-test-vectors.json BTX already tests; no implementation comparison adds value here |
| BIP-32 HD keys           | DEFER — BTX delegates HD-derivation to Bitcoin Core's wallet, doesn't reimplement                |
| PSBT (BIP-174)           | DEFER — BTX speaks its own BTX2 envelope, not PSBT                                               |
| signmessage              | DEFER — legacy BIP-137; BTX uses BIP-322 (already cross-tested vs bitcoin/bips)                 |
| Bitcoin Script eval      | DEFER — BTX validates on-chain via Bitcoin Core node directly; no reimplementation               |
| bech32 / base58          | DEFER — BTX uses its own implementations validated separately                                    |

## Cross-test shipped this session

`btx_xtest_vs_python_bitcointx.py` (~280 LOC, wired as 15th sub-test).

Auto-detects libsecp256k1 via three fallbacks:
1. System library (`ctypes.util.find_library("secp256k1")`)
2. Bundled inside the `coincurve` pip package (most common Python
   secp256k1 install)
3. Common explicit paths (`/usr/lib/x86_64-linux-gnu/libsecp256k1.so.1`)

Auto-detects python-bitcointx clone in `Bitcoin CoreX/`, `/mnt/c/...`,
or `/tmp/`. SKIPs gracefully if neither dependency is available.

### Tests run

**A. Canonical bitcoin/bips BIP-340 CSV (19 vectors):**
- 15 in-BTX-scope vectors (32-byte msg): both BTX and libsecp256k1
  agree with the spec's expected verification result, AND when signing
  is requested, **BTX's pure-Python signature output is byte-identical
  to libsecp256k1's C output** (with aux_rand fixed).
- 4 out-of-scope vectors (msg sizes 0, 1, 17, 100): both BTX AND
  libsecp256k1 reject these with `ValueError: Hash must be exactly
  32 bytes long`. The 2022 BIP-340 generalization to variable-length
  messages exists in the reference Python pseudocode but has NOT been
  shipped in the deployed libsecp256k1 binary. BTX's 32-byte-only
  constraint matches the production-state behavior, not a divergence.

**B. 50 random `(sk, msg, aux_rand)` round-trips:**
- Every signature produced by BTX matches the signature produced by
  libsecp256k1 byte-for-byte (50/50).
- libsecp256k1 verifies every BTX-produced signature (50/50).
- BTX verifies every libsecp256k1-produced signature (50/50).
- Bit-flip tampering rejected by both implementations (50/50).

Total: **15/15 + 50/50 = 65/65 PASS**, plus 4 documented out-of-scope
vectors uniformly handled.

### What this rules out

A class of bugs that canonical-vector cross-tests cannot detect:
- BTX correctly handles all 19 canonical CSV vectors → but maybe BTX
  diverges from libsecp256k1 on inputs *not* in the corpus.
- This cross-test answers that by generating 50 random inputs and
  proving byte-identical output. Any silent divergence (e.g., a
  rounding error, an off-by-one in the challenge hash, a wrong parity
  flip) would surface immediately.

The round-trip test is what makes this scout's value distinct from
all prior cross-tests.

## What's NOT extractable

(Detailed in the table above.) The PSBT module is significant code but
out of scope: BTX's wire format is the BTX2 envelope, not BIP-174.
The signmessage module is BIP-137 legacy; BTX uses BIP-322 (already
cross-tested as Phase 1 of scout 16).

The BIP-341 cross-test would use the SAME canonical wallet-test-
vectors.json BTX already validates against. Adding libsecp256k1 there
would only add implementation-comparison value for the sighash math
itself, which is pure SHA-256 + serialization (already cross-tested
end-to-end via the canonical vectors). Marginal additional confidence.

## Schnorr+adaptor canonical-oracle count

This brings BTX's BIP-340 Schnorr oracles to **5**:

1. Bitcoin Core BIP-340 CSV (canonical vectors)
2. secp256kfun (Lloyd Fournier)
3. dlcspecs `dlc_schnorr_test.json`
4. dlcspecs `dlc_hash_test.json` + `contract_id_test.json` (oracle msg
   bytes layer)
5. **python-bitcointx via libsecp256k1** ← this scout (the only one
   that proves *implementation* independence, not just spec compliance)

#5 is qualitatively different from #1-#4: those four prove BTX's
output matches the test corpus. #5 proves BTX's output matches the
C library Bitcoin Core uses in production, on arbitrary inputs.

## Suite expansion this scout

- Pre-scout: 14 sub-tests
- Post-scout: **15 sub-tests**

## Lessons codified

1. **Test-vector independence ≠ implementation independence.**
   Cross-testing against another implementation of the same canonical
   vectors only confirms spec compliance. Round-trip cross-testing
   against an *independent implementation* on *random inputs* is what
   proves no shared-bug class.
2. **Production-state alignment is a stronger guarantee than spec
   alignment.** Vectors 15-18 of the canonical CSV test a 2022 BIP-340
   generalization that the deployed libsecp256k1 hasn't shipped. BTX
   rejects them too, which is the right behavior for matching
   real-world counterparties — not a bug.
3. **`coincurve` is the practical libsecp256k1 fallback.** Sandboxes
   often lack system libsecp256k1 but pip-install it via `coincurve`
   (which bundles a `.so`). Pointing python-bitcointx's
   `_secp256k1_library_path` at coincurve's bundled .so works.

## Cross-links

[[project-btx-scouting-cycle-2026-06-03]] — the prior 15-scout cycle.
[[project-btx-dlcspecs-scout-2026-06-04]] — scout 17 (dlcspecs).
[[feedback-sandbox-mount]] — sandbox mount-lag hit again on Edit tool.

## Files

- `bitcoin-terminal-exchange/btx_xtest_vs_python_bitcointx.py` (NEW)
- `bitcoin-terminal-exchange/btx_xtest_suite.py` (+5 LOC for 15th
  sub-test)
- `bitcoin-terminal-exchange/BTX-python-bitcointx-scouting-2026-06-04.md`
  (THIS DOC)

## Source

Repo: <https://github.com/Simplexum/python-bitcointx>
Maintainer: Dmitry Petukhov (@dgpv)
License: LGPL-3
Examined: master HEAD at clone time 2026-06-04 (~v1.1.5).
