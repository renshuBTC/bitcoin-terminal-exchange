# `bitcoin/bips` — final extraction closure for BTX

*Walks every BIP in the cloned `Bitcoin CoreX/bitcoin-bips-reference/`
that has a reference implementation or test vectors, maps it to a BTX
disposition, and records the closing state. Companion to:
`BTX-secp256k1-zkp-FINAL-2026-06-03.md` and
`BTX-secp256kfun-FINAL-2026-06-03.md`.*

Date: 2026-06-03.

## Survey method

The cloned `bitcoin/bips` repo at master HEAD contains:
- `reference.py` files for 7 BIPs: 89, 324, 327, 328, 340, 352, 374
- vector directories for 3 BIPs: 89, 119, 327

For each, the question was: does BTX use this layer? If yes, is BTX
canonical-compliant? If no, can/should BTX add it?

## Per-BIP disposition

### BIP-340 — Schnorr signatures (Deployed)

- BTX use: `btx_taproot.schnorr_sign` + `schnorr_verify` (the
  foundation under everything else)
- Validation: `btx_bip340_xtest.py` against the 19 official CSV
  vectors → **canonical, 4/4 sign + 19/19 verify**
- Closure: `BTX-bip340-bip341-foundation-2026-06-03.md`

### BIP-341 — Taproot (Deployed)

- BTX use: `taproot_tweak_pubkey`, `p2tr_scriptpubkey`,
  `segwit_address`, `tap_sighash` (carriers + envelope reveals)
- Validation: `btx_bip341_xtest.py` against the wallet-test-vectors.json
  → **canonical, 7/7 + 7/7 + 7/7 + 7/7**
- Closure: same as BIP-340

### BIP-327 — MuSig2 (Deployed)

- BTX use: `btx_musig2.key_agg` (BTX-internal pool sign) + the new
  `btx_musig2.key_agg_bip327` (external interop)
- Validation: `btx_bip327_xtest.py` against 4 official vectors →
  **divergence finding documented + canonical port shipped**.
  `key_agg` (x-only variant) 0/4; `key_agg_bip327` 4/4.
- Closure: `BTX-bip327-keyagg-finding-2026-06-03.md`. The 7 remaining
  vector files (nonce_gen, nonce_agg, sign_verify, sig_agg, tweak,
  det_sign, key_sort) test the full 2-round interactive signing flow,
  which BTX has not ported. Deferred-with-reason: no current product
  driver requires external BIP-327 interactive signing (BTX uses
  trusted-aggregator pool signing).

### BIP-374 — DLEQ (Draft) — **NEW THIS CLOSURE**

- BTX use: not yet wired into BTX2 records; primitive shipped as
  `btx_dleq.py` for future use cases (oracle key validity proofs,
  pool-rotation proofs, cross-protocol key reuse proofs).
- Validation: `btx_bip374_xtest.py` against 11 generate + 15 verify
  canonical vectors → **canonical, 11/11 generate byte-match + 15/15
  verify result-match**.
- The 64-byte proof format and challenge construction byte-match the
  canonical reference, including the failure cases (a=0, a=N,
  B=infinity).
- Status NOTE: BIP-374 is still in Draft. Spec changes are possible.
  BTX's port matches the current reference; future BIP-374 revisions
  may require updating `btx_dleq.py`.

### BIP-352 — Silent Payments (Complete)

- BTX use: NONE today. BTX makers publish a fixed `payout_spk` per
  order; silent payment addresses would let each fill go to a
  different one-time address derived per-taker, improving on-chain
  privacy of maker income.
- Disposition: **deferred-with-reason**. The reference implementation
  is substantial (~380 LOC + bech32m + scan downloader). Integration
  into BTX2 would touch:
  - The order body (silent payment address replacing
    `payout_spk` — or alongside it, as an opt-in flag).
  - The maker-side scanner (compute the per-taker P2TR output key
    from the SP code).
  - The indexer (compute the expected output to attribute fills).
  - The trade UI / wallet.
  - No watchlist trigger has fired yet (no Magic Eden or competitor
    has rolled out SP for fills; no maker has requested it).
- Build cost estimate: ~3 weeks calendar (1 week SP port + 1 week
  BTX2 record format work + 1 week wallet/indexer integration).

### BIP-119 — `OP_CHECKTEMPLATEVERIFY` / CTV (Draft)

- BTX use: NONE today. CTV is not consensus-active on mainnet.
- BTX watchlist tracks covenants (CTV, BIP-345 OP_VAULT [withdrawn],
  BIP-443 CCV) per `project_btx_watchlist_refresh`.
- 102 ctvhash test vectors available.
- Disposition: **deferred until activation OR until a maker pool
  publishes a CTV-locked vault order spec**. Cross-test the canonical
  ctvhash algorithm only once BTX actually has CTV use.

### BIP-328 — MuSig2 Derivation Scheme (Complete)

- BTX use: NONE today. BIP-328 extends BIP-32 HD derivation to MuSig2
  aggregate keys. BTX doesn't use HD derivation; it uses fixed
  per-maker keys.
- Disposition: **skip**. Only relevant if BTX adds HD wallet
  integration for makers, which is not on the roadmap.

### BIP-324 — Version 2 P2P Encrypted Transport (Deployed)

- BTX use: NONE. BTX doesn't run a P2P stack; it relies on Bitcoin
  Core's transport.
- Disposition: **skip**. Out of BTX's scope.

### BIP-89 — Chain Code Delegation (Draft)

- BTX use: NONE. HD-key-related.
- Disposition: **skip**.

## What's NOT in this repo that BTX could use

For completeness, here are the BIPs that BTX touches but for which the
cloned `bitcoin/bips` repo ships only docs (no reference + no vectors):

- **BIP-141** SegWit — foundation; BTX uses P2WPKH
- **BIP-143** SegWit v0 sighash — BTX computes this for SIGHASH_SINGLE|
  ANYONECANPAY fills. **Not cross-validated this session** because
  bitcoin/bips doesn't ship vectors for it.
- **BIP-174 / BIP-370** PSBT — BTX uses PSBTs. Same status: docs only.
- **BIP-322** Generic signed message format — BTX doesn't use today.

For BIP-143 specifically, BTX's atomic-swap fill correctness depends
on it being right. Future validation would require either:
- Manually building test vectors from Bitcoin Core's `src/test/data/`
  (it ships sighash test vectors there).
- Cross-test against `rust-bitcoin`'s sighash implementation.

This is a real gap and should be tracked as a watchlist item.

## Final per-BIP table

| BIP | Title                          | Status (in spec) | BTX disposition this session                    |
|-----|--------------------------------|------------------|--------------------------------------------------|
| 340 | Schnorr signatures             | Deployed         | ✓ validated 19/19 vectors                       |
| 341 | Taproot                        | Deployed         | ✓ validated 7+7+7+7 vectors                     |
| 327 | MuSig2                         | Deployed         | variant + canonical port (4/4 + Path B)         |
| 374 | DLEQ proofs                    | Draft            | **NEW: shipped + 11+15 vectors canonical-match** |
| 352 | Silent Payments                | Complete         | deferred — 3-week build cost, no product driver |
| 119 | CHECKTEMPLATEVERIFY            | Draft            | deferred — CTV not consensus-active             |
| 328 | MuSig2 derivation              | Complete         | skip — BTX doesn't use HD                       |
| 324 | v2 P2P transport               | Deployed         | skip — BTX doesn't run P2P                      |
| 89  | Chain code delegation          | Draft            | skip — HD-specific                              |

## Update to the cross-test suite

`btx_xtest_suite.py` now includes `btx_bip374_xtest.py` as the 6th
sub-test. Updated tripwire output:

```
[✓ PASS] BIP-340 Schnorr (foundation)                    19/19
[✓ PASS] BIP-341 Taproot (foundation)                    7+7+7+7
[✓ PASS] BIP-327 MuSig2 KeyAgg (variant + canonical)     0+4 (by design)
[✓ PASS] BIP-374 DLEQ                                    11+15  ← NEW
[✓ PASS] Runes decoder vs Magic Eden                     19/19
[✓ PASS] Runestone cenotaph adversarial                  50,000 fuzz CLEAN
```

## Nothing left to extract for current BTX scope

Walking the bitcoin/bips repo one final time:

- All BIPs with `reference.py` AND a clear BTX use case have been
  cross-tested and either landed (BIP-340/341/327/374) or
  deferred-with-reason (BIP-119/328/352).
- All BIPs that BTX uses but where bitcoin/bips doesn't ship a
  reference (BIP-141/143/174/322) need external sources — flagged for
  the watchlist.

**The bitcoin/bips repo has been fully mined for BTX's current scope.**
Future extraction would be triggered by:

1. BTX activating BIP-119 CTV use (if covenants become a product
   driver)
2. BTX activating BIP-352 silent payments (if maker privacy becomes a
   product driver)
3. BTX integrating BIP-374 DLEQ into a real BTX2 record (e.g.
   oracle-key-validity proofs in CONDITIONAL_ORDER)
4. Future Schnorr half-aggregation BIP standardisation (not yet a
   numbered BIP)
5. A new BIP that touches BTX's scope (PSBT v3, etc.)

## Session-end deliverable map

```
bitcoin-terminal-exchange/
├── btx_dleq.py                                     NEW (282 LOC)
├── btx_bip374_xtest.py                             NEW (143 LOC)
├── btx_xtest_suite.py                              EXTENDED (+1 sub-test)
└── BTX-bitcoin-bips-FINAL-2026-06-03.md            NEW (this doc)
```

Combined with the prior session-day work (BIP-327 finding, BIP-340/341
foundation closure, runes refresh, discipline doc, secp256k1-zkp and
secp256kfun closures), this completes the 2026-06-03 cross-validation
cycle.

## Cross-references

- `BTX-cross-validation-discipline-2026-06-03.md` — the session
  meta-summary
- `BTX-secp256k1-zkp-FINAL-2026-06-03.md` — prior crypto extraction
- `BTX-secp256kfun-FINAL-2026-06-03.md` — second-repo crypto extraction
- `btx_xtest_suite.py` — the unified tripwire
