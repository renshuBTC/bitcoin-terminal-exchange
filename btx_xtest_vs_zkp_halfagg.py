#!/usr/bin/env python3
"""
btx_xtest_vs_zkp_halfagg — cross-validate btx_halfagg.verify against the
official spec vectors used by BlockstreamResearch/secp256k1-zkp.

Source: `src/modules/schnorrsig_halfagg/tests_impl.h` in the secp256k1-zkp
clone at HEAD 95b9835, in `test_schnorrsig_aggverify_spec_vectors`, which
itself mirrors the hacspec reference at
  hacspec-halfagg/tests/tests.rs#L78
from the cross-input-aggregation repo (BlockstreamResearch).

Three vectors:
  vec 0: N=0   (empty aggregation; aggsig = 32 zero bytes)
  vec 1: N=1   (single signature, no aggregation savings — but a
                strong sanity check that the encoding matches)
  vec 2: N=2   (the first vector where the half-agg scalar s is non-trivial)

Each vector publishes (pubkeys[N], msgs[N], expected_aggsig[32*(N+1)]).
btx_halfagg.verify must return True on each. We also assert it returns
False on (a) wrong message, (b) wrong pubkey, (c) bit-flipped aggsig
— these are tamper checks the C tests don't bother with but which
catch a class of "always-True" verifier bugs.

This is the second BTX-half-agg oracle. The first oracle was the
Python↔Rust port cross-test inside brk-btx (per
project_btx_v2_stack_2026-06-02). This adds Blockstream's canonical
spec vectors as a third independent reference.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import btx_halfagg as HA  # noqa: E402


# --- Vectors transcribed from zkp tests_impl.h lines 76-167 -----------------
# Layout: VEC[i] = (pubkeys_concat, msgs_concat, expected_aggsig)
# Each entry's lengths are: pubkeys = 32*N, msgs = 32*N, aggsig = 32*(N+1).
_VECTORS = [
    # ----- Test vector 0 -----
    # N=0; agg = 32 zero bytes (the "empty" half-agg).
    (
        b"",
        b"",
        bytes.fromhex(
            "00" * 32
        ),
    ),
    # ----- Test vector 1 -----
    # N=1; pubkey = 0x1b 0x84 ...; msg = 0x02 repeated; agg = 0xb0 0x70 ...
    (
        bytes.fromhex(
            "1b84c5567b126440"
            "995d3ed5aaba0565"
            "d71e183460481909"  # n.b. last byte is 0xff but the array reads ff actually
            "9c17f5e9d5dd078f"
        ),
        bytes.fromhex(
            "0202020202020202"
            "0202020202020202"
            "0202020202020202"
            "0202020202020202"
        ),
        bytes.fromhex(
            "b070aafcea439a4f"
            "6f1bbfc2eb66d29d"
            "24b0cab74d6b745c"
            "3cfb009cc8fe4aa8"
            "0e066c3481993654"
            "9ff49b6fd4d41edf"
            "c401a367b87ddd59"
            "fee38177961c225f"
        ),
    ),
    # ----- Test vector 2 -----
    # N=2; two distinct pubkeys, two distinct messages.
    (
        bytes.fromhex(
            "1b84c5567b126440"
            "995d3ed5aaba0565"
            "d71e183460481909"  # actually d71e1834 60481919 then 9ff... — fixed below
            "9c17f5e9d5dd078f"
            "462779ad4aad3951"
            "4614751a71085f2f"
            "10e1c7a593e4e030"
            "efb5b8721ce55b0b"
        ),
        bytes.fromhex(
            "0202020202020202"
            "0202020202020202"
            "0202020202020202"
            "0202020202020202"
            "0505050505050505"
            "0505050505050505"
            "0505050505050505"
            "0505050505050505"
        ),
        bytes.fromhex(
            "b070aafcea439a4f"
            "6f1bbfc2eb66d29d"
            "24b0cab74d6b745c"
            "3cfb009cc8fe4aa8"
            "a3afbdb45a6a34bf"
            "7c8c00f1b6d7e7d3"
            "75b54540f13716c8"
            "7b62e51e2f4f22ff"
            "bf8913ec53226a34"
            "892d60252a705261"
            "4ca79ae939986828"
            "d81d2311957371ad"
        ),
    ),
]


def _normalise_vec1_pubkey():
    """The pubkey for vector 1 / vector 2[0] is identical, taken from
    tests_impl.h lines 92-95. Re-derive directly from those bytes to avoid
    transcription typos (the inline string-pasting above is for eyeballing
    convenience but each row is grouped 16 bytes wide and is easy to mis-
    keyed). Returns 32 bytes."""
    return bytes([
        0x1b, 0x84, 0xc5, 0x56, 0x7b, 0x12, 0x64, 0x40,
        0x99, 0x5d, 0x3e, 0xd5, 0xaa, 0xba, 0x05, 0x65,
        0xd7, 0x1e, 0x18, 0x34, 0x60, 0x48, 0x19, 0xff,
        0x9c, 0x17, 0xf5, 0xe9, 0xd5, 0xdd, 0x07, 0x8f,
    ])


def _normalise_vec2_pubkey1():
    return bytes([
        0x46, 0x27, 0x79, 0xad, 0x4a, 0xad, 0x39, 0x51,
        0x46, 0x14, 0x75, 0x1a, 0x71, 0x08, 0x5f, 0x2f,
        0x10, 0xe1, 0xc7, 0xa5, 0x93, 0xe4, 0xe0, 0x30,
        0xef, 0xb5, 0xb8, 0x72, 0x1c, 0xe5, 0x5b, 0x0b,
    ])


def main() -> int:
    # Rebuild the pubkey-concat arrays from the byte-list constants above
    # to be byte-exact, then run the verifier.
    pk1 = _normalise_vec1_pubkey()
    pk2 = _normalise_vec2_pubkey1()
    vec_pubkeys = [b"", pk1, pk1 + pk2]
    msgs_2 = bytes([0x02] * 32)
    msgs_5 = bytes([0x05] * 32)
    vec_msgs = [b"", msgs_2, msgs_2 + msgs_5]
    vec_aggsigs = [v[2] for v in _VECTORS]

    failures = []
    for i in range(3):
        n = i  # vector index equals N for these particular vectors
        pubkeys_concat = vec_pubkeys[n]
        msgs_concat = vec_msgs[n]
        aggsig = vec_aggsigs[n]
        # Split into N pubkeys / N msgs of 32 bytes each
        pubkeys = [pubkeys_concat[k * 32:(k + 1) * 32] for k in range(n)]
        msgs = [msgs_concat[k * 32:(k + 1) * 32] for k in range(n)]
        if len(aggsig) != 32 * (n + 1):
            failures.append(f"vec {n}: encoded aggsig is {len(aggsig)}B, expected {32*(n+1)}B")
            continue

        try:
            ok = HA.verify(pubkeys, msgs, aggsig)
        except Exception as e:
            failures.append(f"vec {n}: btx_halfagg.verify raised {type(e).__name__}: {e}")
            continue
        if not ok:
            failures.append(f"vec {n}: canonical aggsig did NOT verify under btx_halfagg")

    # ---- Tamper checks on vector 2 ----
    n = 2
    pubkeys = [pk1, pk2]
    msgs = [msgs_2, msgs_5]
    aggsig = vec_aggsigs[2]

    # Tamper 1: wrong message
    bad_msgs = [msgs_2, bytes([0x06] * 32)]
    if HA.verify(pubkeys, bad_msgs, aggsig):
        failures.append("tamper-msg: verify accepted wrong message (BAD)")

    # Tamper 2: bit-flip the aggsig
    flipped = bytes([aggsig[0] ^ 0x01]) + aggsig[1:]
    if HA.verify(pubkeys, msgs, flipped):
        failures.append("tamper-sig: verify accepted bit-flipped aggsig (BAD)")

    # Tamper 3: wrong pubkey order
    if HA.verify([pk2, pk1], msgs, aggsig):
        failures.append("tamper-pubkey: verify accepted swapped pubkey order (BAD)")

    if failures:
        print(f"FAIL ({len(failures)}):")
        for m in failures:
            print(f"  - {m}")
        print("✗ btx_xtest_vs_zkp_halfagg")
        return 1
    print(
        "✓ btx_xtest_vs_zkp_halfagg: 3/3 canonical hacspec vectors "
        "(N=0,1,2) verify + 3/3 tamper checks reject"
    )
    print("  Second canonical oracle for btx_halfagg established "
          "(first was the Python↔Rust port cross-test in brk-btx).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
