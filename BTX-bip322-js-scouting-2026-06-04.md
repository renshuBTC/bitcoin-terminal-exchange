# Scouting report — `ACken2/bip322-js` (npm package)

*Twenty-first scout. Domain: dedicated JavaScript BIP-322
implementation. Closes the BIP-322 ecosystem-gap bookmark from scouts
19, 20 and the cycle summary.*

Date: 2026-06-04.

## Why this repo

Scouts 19 and 20 documented BIP-322 as a real Rust + JS ecosystem
gap — neither rust-bitcoin, bdk, scure-btc-signer, nor @noble/curves
implement BIP-322. The cycle summary bookmarked this as the next
high-value open slot.

The hunt this scout: search npm for any standalone BIP-322 package.
Found three:
- `bip322-js` v3.0.0 by ACken2 (Aspect Kennedy)
- `@exodus/bip322-js` v3.2.1 — Exodus Wallet's fork
- `@saturnbtcio/bip322-js` — SaturnBTC's fork

ACken2's `bip322-js` is the upstream. It's a no-WASM TypeScript
implementation that's been in production at Exodus and elsewhere
since 2023. Installs cleanly into Node 22 in the sandbox.

## What this oracle proves

BTX's `btx_bip322.sign_simple_p2tr` produces a SIGHASH_DEFAULT
(64-byte sig, no sighash flag byte) BIP-322 P2TR signature. The
cross-test shows that **bip322-js's `Verifier.verifySignature`
accepts BTX's signatures on 30/30 random `(sk, message)` inputs**,
and **rejects all 10/10 bit-flipped tampered sigs**. Combined:
**40/40 PASS**.

This is the strongest BIP-322 cross-implementation oracle BTX has
access to: bip322-js is what Exodus Wallet uses, what production JS
Bitcoin tooling uses. If bip322-js accepts a BTX signature, that
signature is real-world compatible with the verifier major wallets
ship.

## Sigflag asymmetry (documented scope, not a divergence)

bip322-js's `Signer.sign` defaults to SIGHASH_ALL (65-byte sig with
0x01 flag). BTX's `sign_simple_p2tr` produces SIGHASH_DEFAULT
(64-byte sig). Both are valid per BIP-322; they sign different
sighashes so the signatures themselves differ.

bip322-js's verifier accepts BOTH formats. BTX's verifier only
handles SIGHASH_DEFAULT — a documented scope limit, not a bug. This
cross-test runs the direction BOTH implementations support:
BTX-sign → bip322-js-verify. That direction is what matters for
production interop.

If BTX ever needs to verify BIP-322 signatures from wallets that
emit SIGHASH_ALL (older Sparrow, Trezor Suite), the SIGHASH_ALL
verify path needs to be added to `btx_bip322.verify_simple_p2tr`.
Bookmark.

## Strategic verdict

| Surface                              | Verdict                                                                                                |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| BIP-322 P2TR SIGHASH_DEFAULT sign    | **SHIPPED** — bip322-js accepts BTX signatures (30/30 + 10/10 tamper-reject = 40/40)                  |
| BIP-322 SIGHASH_ALL verify path      | DEFER — adds complexity; only needed if BTX wants to accept sigs from wallets defaulting to SIGHASH_ALL |
| BIP-322 P2PKH / P2WPKH / P2SH-P2WPKH | DEFER — BTX is Taproot-only by design                                                                  |
| BIP-137 legacy verification          | DEFER — BTX doesn't accept legacy sigs                                                                 |
| bip322-js's BIP-322 generation       | DEFER — BTX produces its own; the cross-test is the validation path                                    |

## BIP-322 oracle count: 2

1. Canonical `bitcoin/bips/bip-0322/basic-test-vectors.json`
2. **`bip322-js` (implementation independence)** ← this scout

Adding any further BIP-322 oracle is diminishing returns. The
ecosystem-gap bookmark from scout 19+20 is now CLOSED.

## Suite expansion this scout

- Pre-scout: 17 sub-tests
- Post-scout: **18 sub-tests** (18/18 PASS green on this runner)

## Setup notes for re-running

```
# In Bitcoin CoreX/bip322-js-reference/ (or any directory)
npm install bip322-js
cd path/to/bitcoin-terminal-exchange
python3 btx_xtest_vs_bip322_js.py
```

The cross-test auto-detects the bip322-js install at three candidate
paths (host, sandbox, /tmp). Graceful SKIP if not installed.

## What this scout closes for the broader cycle

Cycle summary (scouts 17-20) listed "BIP-322 cross-impl oracle" as
the top remaining open slot with the trigger "bdk or rust-bitcoin
merges a BIP-322 verifier." The actual answer turned out to be:
neither of those needs to, because the npm ecosystem already has a
dedicated BIP-322 package that does the job.

**Updated open-slot table after scout 21:**

| Slot                          | Status   | Revisit trigger                                                  |
| ----------------------------- | -------- | ----------------------------------------------------------------- |
| BIP-322 cross-impl            | **CLOSED** | (closed by this scout via bip322-js)                            |
| BIP-322 SIGHASH_ALL verify    | open     | if a real counterparty sends BTX a SIGHASH_ALL BIP-322 sig       |
| BIP-341 TapSighash 2nd oracle | open     | high-effort vs marginal value (Transaction FFI)                  |
| btx_s2c external oracle       | open     | secp256k1-zkp ships ec_commit test vectors                       |
| MuSig2 adaptor random         | open     | Rust impl exposing partial_sign + partial_sig_agg                |
| FROST external oracle         | open     | jonasnick/bip-frost-dkg ships test vectors                       |

## Cross-links

[[project-btx-scouting-cycle-2026-06-04]] — cycle summary that
bookmarked this slot.
[[project-btx-rust-bitcoin-scout-2026-06-04]] — scout 20 (BIP-322
absent from rust-bitcoin).
[[project-btx-scure-btc-signer-scout-2026-06-04]] — scout 19 (BIP-322
absent from scure/noble).

## Files

- `bitcoin-terminal-exchange/btx_xtest_vs_bip322_js.py` (NEW, ~240 LOC)
- `bitcoin-terminal-exchange/btx_xtest_suite.py` (+5 LOC, 18th sub-test)
- `bitcoin-terminal-exchange/BTX-bip322-js-scouting-2026-06-04.md` (THIS)

## Source

Package: <https://www.npmjs.com/package/bip322-js> (v3.0.0)
Repo: <https://github.com/ACken2/bip322-js>
Maintainer: ACken2 (Aspect Kennedy)
License: MIT
Forks examined: `@exodus/bip322-js`, `@saturnbtcio/bip322-js`
Examined: master HEAD at clone time 2026-06-04.

## Commit

`06118fb` — "Scout 21: bip322-js cross-test — closes BIP-322
ecosystem-gap bookmark"
