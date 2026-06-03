# BTX cross-validation discipline — session summary

*Pulls together every "vs canonical reference" cross-test landed in the
2026-06-03 session. Records the discipline, the findings, the boundaries
of validation, and the one-command tripwire that gates regression.*

Date: 2026-06-03.

## The discipline

Borrowed from BTX's Runes layer (which already triple-validates against
ord + Magic Eden's runestone-lib), extended to every crypto + asset
layer BTX exposes. For each layer:

1. Identify the canonical reference implementation (typically in
   `bitcoin/bips/`, or a deployed external library).
2. Identify the canonical test vectors.
3. Write a re-runnable Python script that takes BTX through the same
   inputs and compares byte-for-byte against the canonical output.
4. Document any divergence: is it a bug, a deliberate variant, or a
   spec gap?
5. Land the script in BTX's repo so future commits can be
   regression-tested in seconds.

## What got cross-tested this session

| Layer                  | Canonical source                              | Tests / vectors           | Outcome                                                                |
|------------------------|-----------------------------------------------|---------------------------|------------------------------------------------------------------------|
| BIP-340 Schnorr        | `bitcoin/bips/bip-0340/test-vectors.csv`      | 19 (sign + verify)        | **✓ canonical** — 4/4 sign byte-matches, 19/19 verify result-matches   |
| BIP-341 Taproot output key | `bitcoin/bips/bip-0341/wallet-test-vectors.json` | 7 cases (tweak + spk + bech32m) | **✓ canonical** — 7/7 + 7/7 + 7/7                                |
| BIP-341 keyPathSpending sighash | same                                  | 7 hashType cases          | **✓ canonical** — 7/7                                                  |
| BIP-327 MuSig2 KeyAgg  | `bitcoin/bips/bip-0327/`                      | 4 valid cases             | **divergence (x-only variant) + canonical port** — `key_agg` 0/4 by design, `key_agg_bip327` 4/4 |
| Schnorr adaptor sigs   | `LLFourn/schnorr_fun::adaptor`                | empirical probe           | **no canonical wire format** — closed-with-finding (BTX format ≠ schnorr_fun format) |
| Runes (decoder)        | `me-foundation/runestone-lib`                 | 19 frozen golden vectors  | **✓ aligned** — 19/19                                                  |
| Runestone cenotaph     | adversarial corpus                            | 8 named + 50,000 fuzz     | **✓ all clean**                                                        |

## Findings by category

### Canonical-compliant layers (clean)

- **BIP-340 Schnorr** — `btx_taproot.schnorr_sign` and `schnorr_verify`
  produce byte-identical signatures to the canonical reference on every
  vector with a secret key (4/4), and the canonical verification result
  on every vector (19/19, positive + negative cases).
- **BIP-341 Taproot** — `taproot_tweak_pubkey`, `p2tr_scriptpubkey`,
  `segwit_address`, and `tap_sighash` all match the canonical wallet
  vectors on every dimension (7+7+7+7 cases).
- **Runes** — both `ord` and `runestone-lib` references are at master
  HEAD (no drift since BTX's pin); BTX's `btx_runes_decode` matches
  19/19 ME golden vectors and the cenotaph adversarial sweep stays
  clean at 50,000 randomly-generated runestones.

### Documented variant + canonical port

- **BIP-327 MuSig2 KeyAgg** — divergence found and documented in
  `BTX-bip327-keyagg-finding-2026-06-03.md`. Two causes: input
  encoding (x-only vs 33-byte compressed) and list-hash bytes (32 vs
  33 per pubkey). BTX's `key_agg` is a self-consistent x-only-input
  variant; `key_agg_bip327` was added alongside for full canonical
  compliance, byte-matching all 4 official vectors.

### No canonical wire format

- **Schnorr adaptor sigs** — three implementations (BTX,
  `schnorr_fun`, `secp256k1-zkp`) each encode the same math in
  different bytes, with different challenge inputs. Closed-with-finding
  in `BTX-adaptor-triple-validation-2026-06-03.md` because the
  byte-level "triple-validation" target doesn't exist for this
  primitive.

## What's NOT validated (yet)

These layers have BTX implementations but no canonical-reference
cross-test exists or hasn't been run:

| Layer                    | Why not validated                                            |
|--------------------------|--------------------------------------------------------------|
| BIP-174/370 PSBT         | The BIPs ship docs only — no Python reference, no test vectors |
| BIP-322 signed message   | BTX doesn't currently produce BIP-322 sigs                     |
| Schnorr half-aggregation | Still a BIP draft (`bip-0XYZ-halfagg` not yet standardised)  |
| BTX2 wire format         | BTX-specific — no external canonical to compare against       |
| FROST t-of-n             | BTX's trusted-dealer variant has no canonical wire format     |
| S2C delayed-reveal       | BTX-defined record format (S2C1 magic) — no canonical to compare |

For the BTX-specific items (BTX2, FROST variant, S2C envelope), there is
no canonical reference by construction — BTX defines them. The discipline
applies only to *standardised* layers.

## The tripwire — `btx_xtest_suite.py`

Single command that runs all 5 cross-tests in sequence and rolls up the
result:

```bash
$ python3 btx_xtest_suite.py
[ running ] BIP-340 Schnorr (foundation)
[✓ PASS   ] BIP-340 Schnorr (foundation)  (1.18s)
             Overall: ✓ CANONICAL BIP-340 COMPLIANCE
[ running ] BIP-341 Taproot (foundation)
[✓ PASS   ] BIP-341 Taproot (foundation)  (0.26s)
             Overall: ✓ CANONICAL BIP-341 COMPLIANCE
[ running ] BIP-327 MuSig2 KeyAgg (variant + canonical port)
[✓ PASS   ] BIP-327 MuSig2 KeyAgg (variant + canonical port)  (1.26s)
             Closed-with-finding via the parallel key_agg_bip327 above.
[ running ] Runes decoder vs Magic Eden (asset layer)
[✓ PASS   ] Runes decoder vs Magic Eden (asset layer)  (0.03s)
             runes decoder vs Magic Eden runestone-lib: 19/19 golden vectors match
[ running ] Runestone cenotaph adversarial (50,000-fuzz)
[✓ PASS   ] Runestone cenotaph adversarial (50,000-fuzz)  (3.17s)
             ALL CLEAN

=== btx_xtest_suite ===
  passed:  5/5
  failed:  0/5
  skipped: 0/5
✓ btx_xtest_suite: 5 PASS, 0 skipped, 0 FAIL
```

Total runtime: ~6 seconds. Pure-Python, no external services, no node.
Exit code is 0 on all-pass, non-zero on any failure. Skipped sub-tests
(reference repo not cloned) don't affect exit code.

This is BTX's canonical "did the foundation regress?" gate. Future
commits to `btx_taproot.py`, `btx_musig2.py`, or `btx_runes_decode.py`
should run this and confirm pass.

## Reference checkouts needed

Two clones, both at master HEAD as of 2026-06-03:

| Local path                                | Origin                                  | Pinned commit (== master HEAD as of today) |
|-------------------------------------------|-----------------------------------------|---------------------------------------------|
| `Bitcoin CoreX/bitcoin-bips-reference/`   | `bitcoin/bips`                          | `latest master` (cloned this session)       |
| `Bitcoin CoreX/ord-reference/`            | `ordinals/ord`                          | `5241ef311e015cff4759a379085c8cc8913e621a` (2026-04-03) |
| `Bitcoin CoreX/runestone-lib-reference/`  | `me-foundation/runestone-lib`           | `13b5ef995f44e881b6de541a2f7d5cf77ad491e9` (2024-08-14 — dormant) |

If a reference is missing, the corresponding sub-test reports SKIPPED
(via `_host_path_to_sandbox()` check in the suite runner) instead of
FAILED. Skipped tests don't fail the rollup; only actual divergences do.

## What this discipline buys BTX

1. **A definitive answer to "is BTX's crypto correct?"** Yes for BIP-340,
   BIP-341, Runes. The MuSig2 variant is documented and the canonical
   alternative is shipped alongside.
2. **Sub-6-second tripwire** for any commit touching the foundation.
   Catches regressions before they ship.
3. **Empirical baseline for audits.** Future audit work doesn't have to
   re-derive these claims — the test artefacts ARE the proof.
4. **Honest boundary disclosure.** The "What's NOT validated" section is
   the load-bearing piece: it tells a future reviewer exactly which BTX
   layers are externally-validated and which are BTX-defined-and-tested.

## Cross-references

- `BTX-bip340-bip341-foundation-2026-06-03.md` — foundation findings
- `BTX-bip327-keyagg-finding-2026-06-03.md` — MuSig2 KeyAgg variant +
  canonical port
- `BTX-adaptor-triple-validation-2026-06-03.md` — Schnorr adaptor
  no-canonical-wire-format finding
- `BTX-runes-triple-validation-refresh-2026-06-03.md` — Runes
  alignment refresh
- `BTX-secp256k1-zkp-FINAL-2026-06-03.md` — primitive extraction
  closure (companion to this discipline doc)
- `BTX-secp256kfun-FINAL-2026-06-03.md` — secp256kfun closure
- `btx_xtest_suite.py` — the tripwire (this commit)

## Session deliverables — final tally

Across the 2026-06-03 cross-validation session:

- **5 cross-test scripts** (BIP-340, BIP-341, BIP-327, Runes vs ME,
  cenotaph adversarial)
- **1 unified suite runner** (`btx_xtest_suite.py`)
- **6 closure docs** (BIP-327 finding, BIP-340/341 foundation,
  adaptor triple-validation, Runes refresh, this discipline doc,
  plus the secp256kfun/secp256k1-zkp extraction closures)
- **2 reference clones** pinned and recorded (bitcoin/bips, ord)
- **1 BTX library addition** (`key_agg_bip327` in btx_musig2.py)

The cross-validation cycle is converging. There is no further canonical
reference to test BTX against without first standardising a new BIP (e.g.
the still-draft Schnorr half-aggregation) or until BTX adopts a new
external protocol (e.g. cross-curve DLEQ for XMR/SOL bridging, deferred).
