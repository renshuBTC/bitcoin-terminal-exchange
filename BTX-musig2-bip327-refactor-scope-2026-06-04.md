# Scope: btx_musig2 BIP-327 inner-function exposure

Engineering decision: **deferred to a dedicated session.**

## Background

The cycle 2 saturation doc listed "6 of 8 BIP-327 vector files" as
an open slot needing "btx_musig2 refactor (BTX-side work)." The 8
BIP-327 vector files are:

| Vector file              | Status      | What it tests                          |
| ------------------------ | ----------- | -------------------------------------- |
| `key_agg_vectors.json`   | ✓ Wired     | KeyAgg with various x-only inputs      |
| `key_sort_vectors.json`  | ✓ Wired (scout 23) | Canonical pubkey lex sort       |
| `nonce_gen_vectors.json` | open        | Deterministic nonce generation         |
| `nonce_agg_vectors.json` | open        | Aggregating per-signer pub-nonces      |
| `sign_verify_vectors.json` | open      | Partial signing + verification         |
| `sig_agg_vectors.json`   | open        | Aggregating partial signatures         |
| `tweak_vectors.json`     | open        | KeyAgg with x-only Taproot tweak       |
| `det_sign_vectors.json`  | open        | Deterministic signing path             |

## Why the existing `pool_sign_demo` doesn't cross-test against these

BTX's `btx_musig2.pool_sign_demo(seckeys, msg)` is a **trusted-
aggregator shortcut**: it collects all N secret keys, computes the
aggregated secret `d_agg = sum(a_i · d_i')` directly, and signs with
vanilla BIP-340 over `d_agg`. The output is a valid BIP-340
signature under the aggregated pubkey.

This is correct for BTX2 maker pools where one entity holds all the
private keys (the maker controls all sub-keys). It is *not* the
multi-party non-interactive MuSig2 protocol.

The standard MuSig2 protocol per BIP-327 has four distinct stages:
1. **`nonce_gen`** — each signer derives a per-signing nonce pair
2. **`nonce_agg`** — coordinator aggregates the public nonces
3. **`partial_sign`** — each signer produces a partial signature with
   their share of the aggregate nonce
4. **`partial_sig_agg`** — coordinator combines partial signatures
   into a final BIP-340 signature

The BIP-327 vector files test each of these stages independently.
BTX's `pool_sign_demo` skips stages 1-3 entirely (no separate nonces,
no partial signing) and arrives at the same final BIP-340 signature
via a different computation path.

## Why this is properly deferred (not just "blocked")

Implementing the full multi-round MuSig2 protocol in BTX would be
~300-400 LOC of careful Schnorr math + tagged-hash plumbing, plus
state-machine handling for the per-stage data flow. It's the
equivalent of porting BIP-327's reference.py into the BTX namespace
with BTX's primitive style. Substantial engineering.

The benefit: cross-test against 6 more BIP-327 vector files. Real
value, but BTX's *current* MuSig2 usage (BTX2 maker pools with
single-entity-holds-all-keys trust assumption) doesn't need it.

Practically, this is a feature add that should happen when:
- BTX wants **untrusted-aggregator** pool signing (multiple parties
  pool their keys without any single party holding all secrets)
- BTX wants byte-for-byte compatibility with external MuSig2 wallets
  (so a counterparty can produce a partial signature that BTX
  combines)
- BTX2 maker pools grow to multi-organization configurations

## Recommended implementation order when this becomes a priority

1. **Phase 1:** Port BIP-327's reference.py `nonce_gen` + `nonce_agg`
   verbatim, cross-test against the corresponding vector files.
2. **Phase 2:** Port `partial_sign` + `partial_sig_verify`, cross-
   test against `sign_verify_vectors.json`.
3. **Phase 3:** Port `partial_sig_agg`, cross-test against
   `sig_agg_vectors.json`.
4. **Phase 4:** Wire all four into a `btx_musig2.multi_party_sign`
   API that handles the multi-stage flow.
5. **Phase 5:** Add `tweak_vectors.json` (x-only Taproot tweak in
   MuSig2 — for BTX2 maker pools that publish to a Taproot output
   key derived from the aggregate).
6. **Phase 6:** Add `det_sign_vectors.json` (deterministic signing
   path).

Estimated effort: **2-3 sessions** depending on test fixture
patience.

## What's NOT blocking

The existing `pool_sign_demo` is consensus-valid (verified by scout
28: 10/10 across pool sizes 2/3/5/7 accepted by libsecp256k1) and is
the correct choice for BTX2 maker pools today. The 6 unwired BIP-327
vector files don't reflect bugs in BTX — they reflect features BTX
doesn't yet have.

## BIP-322 SIGHASH_ALL: shipped this session (commit 00d2468)

The other "BTX-side" task — extending `btx_bip322.verify_simple_p2tr`
to accept SIGHASH_ALL signatures from Sparrow/Trezor/bip322-js — was
small enough to ship inline. 20/20 cross-test against bip322-js
output. Suite now at 25 sub-tests.

## Updated open-slot table

| Slot                          | Status        |
| ----------------------------- | ------------- |
| BIP-322 SIGHASH_ALL verify    | **CLOSED**    |
| BIP-322 SIGHASH_NONE/SINGLE   | open (low priority — rare in BIP-322 attestation) |
| 6 of 8 BIP-327 vector files   | scope deferred (this doc) — Phase plan above |
| Half-aggregation 2nd oracle   | genuinely blocked (no other implementation exists) |

## Cross-links

[[project-btx-scouts-25-27-2026-06-04]] — scout 27/28 results
[[project-btx-bip322-js-scout-2026-06-04]] — scout 21 (original
BIP-322 cross-test that this session's SIGHASH_ALL patch extends)
