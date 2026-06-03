# BTX foundation crypto — BIP-340 + BIP-341 canonical compliance

*Continues the cross-validation cycle from
`BTX-bip327-keyagg-finding-2026-06-03.md`. This time validating BTX's
**foundation layer** (`btx_taproot.py`) against the canonical references
and official test vectors.*

Date: 2026-06-03.

## Why these layers

BTX's `btx_taproot.py` implements BIP-340 Schnorr signatures and BIP-341
Taproot from scratch (no `python-bitcoinlib`, no `rust-secp256k1`). Every
other BTX crypto module — `btx_adaptor`, `btx_s2c`, `btx_musig2`,
`btx_frost`, `btx_v2_*` — calls into `btx_taproot` for primitive
operations. If the foundation is wrong, everything above it is wrong.

The BIP-327 finding (`BTX-bip327-keyagg-finding-2026-06-03.md`) surfaced
that BTX's MuSig2 is a non-canonical variant. This raises the question:
is the divergence a one-off design choice at the MuSig2 layer, or is
BTX's whole crypto stack non-canonical?

Answer (from this session's cross-tests): **the divergence is isolated to
the MuSig2 KeyAgg layer**. BTX's BIP-340 and BIP-341 are canonically
compliant.

## BIP-340 cross-test

Script: `btx_bip340_xtest.py` (134 LOC) runs BTX against the live
`bitcoin/bips/bip-0340/test-vectors.csv` — 19 official vectors covering
sign + verify, positive + negative cases.

**Result:**

```
=== BIP-340 cross-test ===
Vectors: 19

--- Sign path ---
  PASS:    4
  FAIL:    0
  SKIPPED: 15  (no secret key in vector)
--- Verify path ---
  PASS:    19
  FAIL:    0

Overall: ✓ CANONICAL BIP-340 COMPLIANCE
```

- **4/4** sign vectors produce byte-identical signatures (the vectors
  with a secret key fixed)
- **19/19** verify vectors produce the canonical result (positive and
  negative cases)
- The 15 "skipped" sign cases are verify-only vectors (no secret key
  provided) — they all pass verify

BTX's `schnorr_sign` and `schnorr_verify` are canonical BIP-340.

## BIP-341 cross-test

Script: `btx_bip341_xtest.py` (234 LOC) runs BTX against
`bitcoin/bips/bip-0341/wallet-test-vectors.json` — 7 scriptPubKey cases
and 1 keyPathSpending case with 7 inputSpending sub-cases.

**Result:**

```
=== BIP-341 cross-test ===
scriptPubKey cases: 7
keyPathSpending input cases: 7

--- scriptPubKey (output key derivation) ---
  tweaked pubkey:   7/7
  scriptPubKey:     7/7
  bip350 address:   7/7

--- keyPathSpending sighash ---
  sighash matches:  7/7

Overall: ✓ CANONICAL BIP-341 COMPLIANCE
```

Three independent properties checked per scriptPubKey vector:
1. `taproot_tweak_pubkey(internal, merkle_root)` — produces canonical
   tweaked output key
2. `p2tr_scriptpubkey(tweaked)` — produces canonical `51 20 <key>`
3. `segwit_address(1, tweaked, hrp='bc')` — produces canonical BIP-350
   bech32m address

All three pass on all 7 scriptPubKey cases (with varying script trees:
None, single-leaf, two-leaf, multi-leaf).

For keyPathSpending, BTX's `tap_sighash` produces byte-identical sighash
to the canonical `intermediary.sigHash` for all 7 input sub-cases
covering all 7 valid `hashType` values (0x00, 0x01, 0x02, 0x03, 0x81,
0x82, 0x83).

## Implementation note — sigMsg vs sigHash

A cross-test cul-de-sac worth recording. The BIP-341 vector JSON has
TWO closely-related fields:

- `intermediary.sigMsg` — the sighash *message bytes* before the final
  TaggedHash. ~200 bytes long.
- `intermediary.sigHash` — the 32-byte sighash output that signers
  actually sign over.

The relationship is `sigHash = TaggedHash("TapSighash", b"\x00" + sigMsg)`,
documented in BIP-341 §4.

BTX's `tap_sighash()` returns the final `sigHash` directly. My first
draft of the cross-test compared `tap_sighash()` against `sigMsg` —
which obviously failed. Fix: compare directly against `intermediary.sigHash`.
Pinned here so the trap doesn't get re-walked next time someone reaches
for the BIP-341 vectors.

## Combined verdict — BTX foundation is canonical

| Layer                  | Module             | Cross-test source              | Vectors | Result |
|------------------------|--------------------|--------------------------------|---------|--------|
| BIP-340 Schnorr        | `btx_taproot.py`   | bip-0340/test-vectors.csv      | 19      | **19/19 ✓** |
| BIP-341 tweak          | `btx_taproot.py`   | bip-0341/wallet-test-vectors.json | 7    | **7/7 ✓**  |
| BIP-341 p2tr scriptPubKey | `btx_taproot.py` | same                          | 7       | **7/7 ✓**  |
| BIP-350 address        | `btx_taproot.py`   | same                           | 7       | **7/7 ✓**  |
| BIP-341 keyPathSpending sighash | `btx_taproot.py` | same                  | 7       | **7/7 ✓**  |
| BIP-327 KeyAgg (x-only variant) | `btx_musig2.py` | bip-0327/vectors/key_agg_vectors.json | 4 | **0/4 ✗** (documented divergence) |
| BIP-327 KeyAgg (canonical port) | `btx_musig2.py::key_agg_bip327` | same | 4 | **4/4 ✓** |

The MuSig2 KeyAgg divergence at the application layer does NOT propagate
down to the foundation. Whatever BTX's MuSig2 produces, it does so by
calling canonically-compliant BIP-340 primitives.

## Implication for the BTX threat model

The empirical evidence — BIP-340 byte-matching the canonical reference
on every vector — promotes a previously-asserted property in BTX's
documentation to a tested-and-confirmed property:

- `BTX-secp256kfun-FINAL-2026-06-03.md` cited `btx_taproot` as the BIP-340
  primitive everything else builds on
- `BTX-adaptor-triple-validation-2026-06-03.md` carried an open question
  about whether BTX's BIP-340 was a one-off or canonical
- This doc closes that question: **canonical**

Future BTX audits can treat the BIP-340/341 layer as a black box that
agrees with the canonical reference on all official inputs. Audit
attention should focus on the LAYERS ABOVE: MuSig2 KeyAgg (variant +
canonical co-exist), Schnorr adaptor (variant), FROST (variant), BTX2
record format (BTX-specific), etc.

## Cross-references

- `BTX-bip327-keyagg-finding-2026-06-03.md` — the MuSig2 KeyAgg
  divergence finding
- `BTX-adaptor-triple-validation-2026-06-03.md` — Schnorr adaptor
  finding (no canonical wire format)
- `BTX-secp256kfun-FINAL-2026-06-03.md` — secp256kfun extraction
  closure
- `btx_taproot.py` — the foundation under test (BTX commit `e43c466`)
- `bitcoin/bips/bip-0340/reference.py` + `test-vectors.csv` — BIP-340
  canonical source
- `bitcoin/bips/bip-0341/wallet-test-vectors.json` — BIP-341 canonical
  source
- `btx_bip340_xtest.py`, `btx_bip341_xtest.py` — the cross-test runners
  (re-runnable on demand)

## Test runners — re-runnable

Both cross-tests are pure-Python, no node required, ~1 second runtime
each:

```bash
cd ~/bitcoin-terminal-exchange
python3 btx_bip340_xtest.py
python3 btx_bip341_xtest.py
```

If BTX ever changes its BIP-340 or BIP-341 code, re-running these
catches regressions immediately. They're the "Runes-style triple
validation" equivalent for the crypto foundation.
