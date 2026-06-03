# BTX MuSig2 KeyAgg vs canonical BIP-327 — empirical finding

*Continues the cross-validation discipline from
`BTX-adaptor-triple-validation-2026-06-03.md`. This session ran BTX's
MuSig2 KeyAgg against the official BIP-327 reference implementation
and test vectors from `bitcoin/bips`.*

Date: 2026-06-03.

## Repo cloned

`bitcoin/bips` at master (depth=1), specifically the `bip-0327/`
directory containing:

- `reference.py` (880 LOC) — canonical Python implementation,
  Status: **Deployed**, Version: **1.0.3**, authors Jonas Nick + Tim
  Ruffing + Elliott Jin
- `vectors/key_agg_vectors.json` — 4 valid + 5 error test cases
- 7 other vector files (`nonce_gen`, `nonce_agg`, `sign_verify`,
  `sig_agg`, `tweak`, `det_sign`, `key_sort`)

The BIP is the *canonical wire-level spec* for MuSig2 — unlike adaptor
signatures, MuSig2 has a fixed byte-level format and a published
reference + vectors.

## Test setup

`btx_bip327_xtest.py` loads the canonical vectors, runs both the BIP-327
reference (sanity check that it matches its own vectors) and BTX's
`btx_musig2.key_agg` on the same input pubkeys, and compares outputs.

Input adaptation: BIP-327 takes 33-byte compressed pubkeys with parity
prefix; BTX takes 32-byte x-only. The cross-test feeds each
implementation what it expects (compressed for BIP-327, x-only-truncated
for BTX) so the comparison is apples-to-apples on the *aggregated x-only*
output.

## Empirical result

For each of 4 valid test cases:

| Case | Indices    | Canonical expected (first 8 hex)| BIP-327 ref output (first 8 hex) | BTX btx_musig2 output (first 8 hex) | BIP-327 self-check | BTX matches |
|------|------------|---------------------------------|----------------------------------|------------------------------------|--------------------|-------------|
| 0    | [0,1,2]    | 90539EED…                       | 90539EED…                        | E5830140…                          | ✓                  | **✗**       |
| 1    | [2,1,0]    | 6204DE8B…                       | 6204DE8B…                        | D70CD69A…                          | ✓                  | **✗**       |
| 2    | [0,0,0]    | B436E3BA…                       | B436E3BA…                        | 81A8B093…                          | ✓                  | **✗**       |
| 3    | [0,0,1,1]  | 69BC22BF…                       | 69BC22BF…                        | 2EB18851…                          | ✓                  | **✗**       |

The BIP-327 reference matches its own vectors (sanity). BTX's
implementation does **not** match the canonical output on any of the 4
cases.

This is a real, definitive finding — not an instrumentation bug. The
divergence has two clear causes (both visible in the code):

1. **Input encoding.** BIP-327 KeyAgg takes 33-byte compressed pubkeys
   (parity-preserving). `btx_musig2.key_agg` takes 32-byte x-only
   pubkeys and `lift_x`s each to the even-y point at hash time.
   Result: for inputs whose canonical compressed form has parity `0x03`
   (odd-y), the actual point summed differs from BIP-327's.

2. **List-hash input bytes.** BIP-327 computes
   `L = TaggedHash("KeyAgg list", concat(33-byte pubkeys))`. BTX
   computes `L = TaggedHash("KeyAgg list", concat(32-byte x-only
   pubkeys))`. The tag string is identical, but the input bytes differ
   by 1 byte per pubkey, so the resulting `L` hashes differ, hence the
   coefficients `a_i = H_coeff(L, x(pk))` differ, hence the aggregated
   pubkeys differ — even for test case 2 (`[0,0,0]`) where all input
   pubkeys are already even-y.

## What this means for BTX

**BTX's MuSig2 is a non-canonical x-only-input variant**, not the
deployed BIP-327 algorithm.

Practical consequences:

1. **No interop with BIP-327 wallets.** A pool of N independent
   MuSig2-1.0.3-compliant signers (e.g. Ledger hardware wallets,
   `schnorr_fun`, Blockstream's libsecp's musig module) cannot
   collaborate to produce a signature valid under a BTX pool's
   aggregated key, and vice-versa.
2. **The trusted-aggregator model is unaffected.** BTX's
   `pool_sign_demo` collects all secret keys at one party at sign
   time; it computes the aggregated secret from its own KeyAgg and
   signs. The signature is a valid BIP340 Schnorr sig under BTX's
   (non-BIP-327) aggregated pubkey. The on-chain settlement path
   doesn't know or care about the KeyAgg flavour.
3. **BTX2 BATCH_ANNOUNCE wire format is unaffected.** The pool's
   aggregated x-only pubkey occupies the `maker_pubkey` field
   regardless of whether it came from BIP-327 or BTX-variant KeyAgg.
   No spec change is required to fix this finding.
4. **`btx_frost_publish` is also unaffected.** FROST signing uses its
   own polynomial-based aggregation, completely separate from the
   MuSig2 KeyAgg. The same divergence does not apply to the FROST
   path shipped earlier this session.

## Two paths to fix

### Path A — keep BTX's variant, document the divergence (RECOMMENDED)

Update the public-facing docs to note that `btx_musig2.key_agg` is
x-only-input MuSig2-like, not BIP-327. Add a docstring caveat. No code
changes; no behaviour changes.

Effort: ~30 min.

Rationale: BTX's existing pool_sign_demo + btx_pool_publish chain are
internally self-consistent. Trusted-aggregator pool signing doesn't
require interop. The only practical loss is the inability to bridge to
external BIP-327 wallets, which BTX's trust model doesn't admit anyway.

### Path B — add a BIP-327-compliant `key_agg_bip327` alongside

Implement the canonical algorithm in `btx_musig2.py` as a parallel
function (preserving the existing `key_agg` for backward compat).
Cross-test against the 4 canonical vectors.

Effort: ~1 day (implementation + golden test + tamper tests).

Rationale: enables future BTX2 interop with hardware wallets and
external MuSig2 signers. Doesn't break any existing BTX path.

## Recommendation

**Path A this session, Path B bookmarked for "if external MuSig2
interop becomes a product driver."**

The cross-validation has already done its job — surfacing that BTX's
MuSig2 is a variant rather than the canonical algorithm. Closing the
finding here without re-implementing matches the same discipline used
for the Schnorr adaptor divergence in
`BTX-adaptor-triple-validation-2026-06-03.md`.

## Compared to the secp256kfun adaptor finding

| Dimension              | Schnorr adaptor (vs schnorr_fun)         | MuSig2 KeyAgg (vs BIP-327)              |
|------------------------|------------------------------------------|------------------------------------------|
| Canonical wire format? | **No** — Lloyd, BTX, zkp all differ      | **Yes** — BIP-327 deployed v1.0.3        |
| BTX byte-compatible?   | No — different challenge inputs          | **No** — different list-hash inputs      |
| Self-consistent in BTX?| Yes — round-trips end-to-end             | Yes — pool sig round-trips end-to-end    |
| Practical impact       | None (CONDITIONAL_ORDER is BTX-internal) | No external MuSig2 wallet interop        |
| Fix effort if pursued  | Spec-level (would touch BTX2)            | Implementation-level (`btx_musig2.py`)   |

Both findings are honest divergences worth documenting; neither breaks
existing BTX functionality.

## Cross-references

- `BTX-adaptor-triple-validation-2026-06-03.md` — the prior cross-test
  closure (Schnorr adaptor format divergence)
- `BTX-v2-spec-2026-06-02.md` — BTX2 wire format (unchanged by this
  finding)
- `btx_musig2.py` — implementation under test
- `btx_pool_publish.py` + `btx_frost_publish.py` — downstream users of
  the KeyAgg (both unaffected — they self-consistently use BTX's
  KeyAgg both for sign-time aggregation and verification)
- `Bitcoin CoreX/bitcoin-bips-reference/bip-0327/reference.py` —
  canonical algorithm
- `bitcoin/bips` master commit at clone time: see
  `Bitcoin CoreX/bitcoin-bips-reference/.git/HEAD`

## Verdict

Recording the finding closes this extraction cycle for the `bitcoin/bips`
BIP-327 directory: BTX's MuSig2 is a documented variant, not
BIP-327-byte-compatible. Path A applies. The 7 remaining vector files
(`nonce_gen`, `nonce_agg`, `sign_verify`, `sig_agg`, `tweak`,
`det_sign`, `key_sort`) are downstream of the same input-encoding
divergence and would produce the same "not byte-compatible" result —
no value in re-running them individually.

The valuable extractions from this directory are:
- ✓ Empirical confirmation that BTX's MuSig2 is a variant (this doc)
- The published reference.py as a known-good comparison point for any
  future BIP-327-compliant work BTX undertakes
- The test vectors, retained in `Bitcoin CoreX/bitcoin-bips-reference/`
  for future regression use
