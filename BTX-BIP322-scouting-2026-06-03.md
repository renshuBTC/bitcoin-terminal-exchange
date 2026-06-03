# Scouting report — `bitcoin/bips bip-0322` (Karl-Johan Alm — Generic Signed Message Format)

*Thirteenth scouting target this 2026-06-03 cycle. Picked up after the
"keep going" directive following the cycle-summary stopping point.
Domain: generic Bitcoin message signing for any address type.*

Date: 2026-06-03.

## Why this BIP / repo

BIP-322 by Karl-Johan Alm (@kallewoof) defines a unified signing/
verification format that works for every Bitcoin address type — legacy
P2PKH, P2SH, P2WPKH (`bc1q...`), P2WSH, and **P2TR / Taproot
(`bc1p...`)**. It is the canonical replacement for the legacy
"signmessage" RPC which only supported P2PKH.

Production references using BIP-322 today: Sparrow Wallet, OKX
exchange's "verify wallet ownership" flow, Magic Eden's bid signing,
Saturn's maker registration, BlueWallet, Specter Desktop, and now
ledger/coldcard hardware wallets.

For BTX, the relevant use case is: **maker attestation.** A maker can
prove control of a `bc1p` address by signing a challenge under
BIP-322, without anything custodial. BTX has no auth layer today; this
primitive is the building block for a future trustless maker-
registration flow.

## Source material at a glance

Already cloned at `Bitcoin CoreX/bitcoin-bips-reference/` (cycle's
earlier `bitcoin/bips` deep-dive).

```
bip-0322.mediawiki                512 lines     specification
bip-0322/
  ├── basic-test-vectors.json     136 lines     3 hash-chain vectors (no signing)
  └── generated-test-vectors.json 550 lines     simple + full signing vectors
                                                (P2WPKH, P2TR, P2WSH-multisig 2/2 and 3/3)
```

Note: BIP-322's reference does NOT ship a Python implementation in the
bitcoin/bips repo. Implementations live in downstream wallets (Sparrow,
BlueWallet, etc.). BTX is therefore implementing from the spec, not
porting.

## What's specifically defined

Verbatim from `bip-0322.mediawiki:138-146`:

> ```
> nVersion = 0
> nLockTime = 0
> vin[0].prevout.hash = 0000...000
> vin[0].prevout.n = 0xFFFFFFFF
> vin[0].nSequence = 0
> vin[0].scriptSig = OP_0 PUSH32[ message_hash ]
> vin[0].scriptWitness = []
> vout[0].nValue = 0
> vout[0].scriptPubKey = message_challenge
> ```

…with `message_hash` defined verbatim from lines 148-151:

> ```
> message_hash is a BIP340-tagged hash of the message, i.e., sha256_tag(m),
> where tag = `BIP0322-signed-message` and m is the message as-is
> without length prefix or null terminator
> ```

And the `to_sign` transaction (lines 153-163):

> ```
> nVersion = 0
> nLockTime = 0
> vin[0].prevout.hash = to_spend.txid
> vin[0].prevout.n = 0
> vin[0].nSequence = 0
> vin[0].scriptSig = []
> vin[0].scriptWitness = message_signature
> vout[0].nValue = 0
> vout[0].scriptPubKey = OP_RETURN
> ```

This is small, sharp, and fully specifiable.

## Code shipped this session — btx_bip322.py

`btx_bip322.py` (244 LOC) implements three primitives:

1. `message_hash(msg)` — BIP-340 tagged sha256, tag `"BIP0322-signed-message"`.
2. `build_to_spend_tx(msg_hash, script_pubkey)` + `to_spend_txid(...)` —
   the synthetic challenge transaction.
3. `build_to_sign_tx_unsigned(to_spend_txid)` + `to_sign_txid(...)` —
   the bare solution transaction (without witness, since the txid is
   computed over the non-witness serialisation per BIP-141).

Plus `build_to_sign_tx_signed(...)` for when an actual witness stack
is being emitted (used when BTX eventually adds signing).

Cross-test result against `basic-test-vectors.json` (all 3 vectors):

```
$ python3 btx_bip322.py
  message_hash + to_spend + to_sign:  3/3 PASS
✓ btx_bip322: all 3 basic-test-vector hash chains agree with canonical
```

The 3 vectors cover: empty message, ASCII message ("Hello World"), and
a UTF-8 message including CJK and emoji code points. The vector test
also re-loads the JSON file and confirms the inline-transcribed hashes
match the on-disk file byte-for-byte (no transcription drift).

Then wired as the 9th sub-test in `btx_xtest_suite.py`:

```
[ running ] BIP-322 generic signed message (hash + to_spend + to_sign)
[✓ PASS   ] BIP-322 generic signed message (hash + to_spend + to_sign)  (0.04s)

=== btx_xtest_suite ===
  passed:  9/9
  failed:  0/9
  skipped: 0/9
✓ btx_xtest_suite: 9 PASS, 0 skipped, 0 FAIL
```

Total suite runtime: ~10s. The new sub-test adds 0.04s.

## What's NOT shipped (yet)

The basic vectors cover the **structural** parts of BIP-322:
`message_hash`, `to_spend` construction, `to_sign` construction. They
do not require any signing key.

Full BIP-322 signing/verification additionally needs:

- **P2WPKH path**: ECDSA sig over BIP-143 sighash. BTX doesn't have
  ECDSA primitives (it's BIP-340-Schnorr-only). Skipping — not BTX
  scope.
- **P2TR path**: BIP-340 Schnorr sig over BIP-341 key-path sighash of
  the to_sign tx. BTX has all primitives via `btx_taproot.py`. This
  is the natural next step, ~50 LOC + 1 cross-test sub-test against
  the P2TR entries in `generated-test-vectors.json`.
- **P2WSH-multisig path**: aggregate witness construction. Out of
  scope for current BTX (key-path only).

These would each be additional sub-tests in future cycles. The
foundation in this session is the BIP-322 hash + tx construction —
the part every implementation gets wrong first.

## Updated 13-scout pattern

| # | Repo | Outcome | Reason |
|---|------|---------|--------|
| 1 | `secp256k1-zkp` | shipped (primitive) | direct fit |
| 2 | `secp256kfun` | shipped FROST + specced DLEQ | fit + design |
| 3 | `bitcoin/bips` (BIP-374) | shipped BIP-374 | primitive port |
| 4 | `rust-miniscript` | shipped descriptors | deeper-read fit |
| 5 | `sipa/minisketch` | spec only | operational |
| 6 | `mit-dci/utreexo` | spec only | architectural-no-use |
| 7 | `Merkleize/pymatt` | spec only | consensus |
| 8 | `bitcoin-core/HWI` | spec only | product |
| 9 | `petertodd/python-bitcoinlib` | spec only | era |
| 10 | `darosior/python-bip380` | shipped xtest | NEW category B |
| 11 | `BlockstreamResearch/bip-frost-dkg` | spec only | product timing |
| 12 | `romanz/electrs` | spec only | architectural-protocol |
| 13 | **`bitcoin/bips` (BIP-322)** | **shipped (primitive)** | **revisit of same-repo, different BIP** |

Extraction rate: **6/13 ≈ 46%**.

Notable: this is the **second time** the `bitcoin/bips` repo yielded
shippable code in the same cycle (first was BIP-374 DLEQ). The repo
is large enough that each BIP is effectively a separate scouting
target. Pattern lesson: large multi-BIP repos can yield multiple
ships if revisited targeting different BIPs.

## BTX integration path for maker attestation (future)

A complete maker registration flow using BIP-322:

1. BTX issues a challenge: random 32-byte nonce + timestamp.
2. Maker uses their hardware wallet (or BTX's bundled wallet) to BIP-322 sign
   the challenge under their `bc1p` maker address.
3. BTX verifies the signature, links the address to the maker's BTX2
   pool key (via a CONDITIONAL_ORDER attestation envelope), and lets
   the maker publish orders.

Today's ship gives BTX steps 1-2's *hash construction*; the verify
step needs the P2TR signing primitive (next session).

## Verdict

**Code lands.** `btx_bip322.py` shipped + wired into xtest suite.
9/9 PASS. Triple validation discipline holds: the construction is
verified against canonical bitcoin/bips test vectors (the
implementer's authority) and the inline transcription is double-
checked against the on-disk JSON.

## Files added / modified this scout

```
bitcoin-terminal-exchange/
  ├── btx_bip322.py                                  (NEW, 244 LOC)
  ├── btx_xtest_suite.py                             (+5 LOC: 9th sub-test)
  └── BTX-BIP322-scouting-2026-06-03.md              (THIS DOC)
```

## Source

BIP: <https://github.com/bitcoin/bips/blob/master/bip-0322.mediawiki>
Author: Karl-Johan Alm (@kallewoof)
License: CC0-1.0 / BSD-2-Clause
Examined: master HEAD of bitcoin/bips clone, 2026-06-03.
Production references: Sparrow Wallet, OKX, Magic Eden, Saturn,
BlueWallet, Specter Desktop.
