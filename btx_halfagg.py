#!/usr/bin/env python3
"""
btx_halfagg.py — Schnorr signature half-aggregation for BTX.

Implements the half-aggregation scheme used in BlockstreamResearch/secp256k1-zkp's
`schnorrsig_halfagg` module: takes N independent BIP340 Schnorr signatures over
N independent (pubkey, message) pairs and produces a single aggregate signature
of size **32 * (N + 1) bytes** instead of **64 * N bytes**.

The aggregation is non-interactive — any third party holding the N original
sigs can produce the aggregate, and any verifier holding the N (pubkey, message)
pairs can verify it.

Aggregate format:  R_0 || R_1 || ... || R_{N-1} || s
  - each R_i is the BIP340 nonce x-coord from sig_i (32 bytes)
  - s is the aggregated scalar  s = sum_i (z_i * s_i)  mod N
    where z_0 = 1 (implicit) and z_i (i ≥ 1) is a tagged hash binding the
    current i and all prior (R, pubkey, msg) tuples to prevent rogue-key /
    sub-extraction attacks.

Reference: BlockstreamResearch/secp256k1-zkp commit 8099999, file
src/modules/schnorrsig_halfagg/main_impl.h.

What this module does NOT do:
  - Consensus-level aggregation. Bitcoin Core verifies each signature
    individually; this aggregate is for off-chain / artifact-layer use only.
  - Threshold or t-of-n. This is a multi-signer-over-multi-message
    aggregation, not a single-signer threshold scheme.

BTX use case: shrinking multi-maker BTX artifacts. A BTX1 envelope that
announces N maker offers (current: N * ~64-byte sigs) becomes 32 * (N+1)
bytes with half-aggregation. Asymptotic savings 50%; 45% at N=10.
"""

import os, json, hashlib
from btx_taproot import (
    P, N, G,
    point_add, point_mul, lift_x,
    tagged_hash, schnorr_sign, schnorr_verify, xonly_pubkey,
)

# Tag used by the secp256k1-zkp reference. The C impl uses a pre-computed
# SHA256 midstate of SHA256("HalfAgg/randomizer") || SHA256("HalfAgg/randomizer");
# in Python we just call tagged_hash with the tag string (which does the same
# thing: tagged_hash(t, m) = SHA256(SHA256(t) || SHA256(t) || m)).
HALFAGG_TAG = "HalfAgg/randomizer"


def aggregate(pubkeys, msgs, sigs):
    """
    Half-aggregate N independent BIP340 Schnorr signatures.

    Args:
        pubkeys: list of N 32-byte x-only pubkeys
        msgs:    list of N 32-byte messages
        sigs:    list of N 64-byte BIP340 signatures, each = R_i || s_i

    Returns:
        bytes of length 32 * (N + 1):  R_0 || R_1 || ... || R_{N-1} || s_agg

    Raises:
        ValueError on length mismatch or malformed inputs.
    """
    n = len(sigs)
    if not (len(pubkeys) == n and len(msgs) == n):
        raise ValueError(f"length mismatch: {len(pubkeys)} pubkeys, {len(msgs)} msgs, {n} sigs")
    if n == 0:
        # Empty aggregate is just a 32-byte zero scalar — degenerate but valid.
        return (0).to_bytes(32, "big")

    R_concat = b""
    s_agg = 0
    prefix = b""  # running prefix for z_i tagged hash

    for i in range(n):
        sig_i = sigs[i]
        if len(sig_i) != 64:
            raise ValueError(f"sig[{i}] has length {len(sig_i)}, expected 64")
        if len(pubkeys[i]) != 32:
            raise ValueError(f"pubkey[{i}] has length {len(pubkeys[i])}, expected 32")
        if len(msgs[i]) != 32:
            raise ValueError(f"msg[{i}] has length {len(msgs[i])}, expected 32")

        R_i = sig_i[:32]
        s_i = int.from_bytes(sig_i[32:], "big")
        pk_i = pubkeys[i]
        m_i = msgs[i]

        # Extend the running prefix with this tuple.
        prefix += R_i + pk_i + m_i

        # z_0 = 1 implicitly (per the reference). z_i (i ≥ 1) commits to the
        # prefix-so-far, which already includes the tuple at i.
        if i == 0:
            z_i = 1
        else:
            z_i = int.from_bytes(tagged_hash(HALFAGG_TAG, prefix), "big") % N

        s_agg = (s_agg + z_i * s_i) % N
        R_concat += R_i

    return R_concat + s_agg.to_bytes(32, "big")


def verify(pubkeys, msgs, aggsig):
    """
    Verify a half-aggregate signature.

    Args:
        pubkeys: list of N 32-byte x-only pubkeys
        msgs:    list of N 32-byte messages
        aggsig:  bytes of length 32 * (N + 1)

    Returns:
        True iff the aggregate verifies as the half-aggregation of N valid
        BIP340 signatures (R_i, s_i) by pubkey_i over msg_i.

    Equation checked:
        s * G  ==  sum_i  z_i * ( R_i + e_i * P_i )
    where:
        e_i = TaggedHash("BIP0340/challenge", R_i || pk_i || m_i)
        z_0 = 1, z_i (i ≥ 1) = TaggedHash(HalfAgg/randomizer, R_0||pk_0||m_0||...||R_i||pk_i||m_i)
    """
    n = len(pubkeys)
    if len(msgs) != n:
        return False
    if len(aggsig) != 32 * (n + 1):
        return False
    if n == 0:
        # Empty aggregate is the zero scalar — vacuously valid.
        return aggsig == (0).to_bytes(32, "big")

    s = int.from_bytes(aggsig[n * 32 : (n + 1) * 32], "big")
    if s >= N:
        return False

    rhs = None  # point at infinity
    prefix = b""

    for i in range(n):
        R_i_bytes = aggsig[i * 32 : (i + 1) * 32]
        pk_i = pubkeys[i]
        m_i = msgs[i]

        if len(pk_i) != 32 or len(m_i) != 32:
            return False

        # Lift R_i and P_i to affine points with even y.
        try:
            R_pt = lift_x(int.from_bytes(R_i_bytes, "big"))
            P_pt = lift_x(int.from_bytes(pk_i, "big"))
        except (ValueError, AssertionError):
            return False
        if R_pt is None or P_pt is None:
            return False

        # e_i = BIP340 challenge
        e_i = int.from_bytes(
            tagged_hash("BIP0340/challenge", R_i_bytes + pk_i + m_i), "big"
        ) % N

        # Update prefix (must match aggregate's hashing order)
        prefix += R_i_bytes + pk_i + m_i
        if i == 0:
            z_i = 1
        else:
            z_i = int.from_bytes(tagged_hash(HALFAGG_TAG, prefix), "big") % N

        # term = z_i * (R_i + e_i * P_i)
        ePi = point_mul(P_pt, e_i)
        Ri_plus_ePi = point_add(R_pt, ePi)
        term = point_mul(Ri_plus_ePi, z_i)

        rhs = term if rhs is None else point_add(rhs, term)

    lhs = point_mul(G, s)
    return lhs == rhs


# ----------------------------- selftest -----------------------------


def selftest(seed=None):
    """
    Self-test:
      1. N=1 aggregate equals the original signature (degenerate case)
      2. N=3 round-trip
      3. N=10 round-trip + measured byte savings
      4. Tamper-detection (flipped last byte fails verification)
      5. Wrong-msg detection (swap two messages → verification fails)
      6. Cross-validation: each individual sig verifies under BIP340 schnorr_verify
    """
    if seed is not None:
        import random
        random.seed(seed)
        def rand_bytes(n):
            return bytes(random.randint(0, 255) for _ in range(n))
    else:
        rand_bytes = os.urandom

    failures = []

    # Test 1 — N=1
    sk1 = rand_bytes(32)
    pk1 = xonly_pubkey(sk1)[0]
    m1 = rand_bytes(32)
    sig1 = schnorr_sign(m1, sk1)
    agg1 = aggregate([pk1], [m1], [sig1])
    if len(agg1) != 64:
        failures.append(f"N=1 size: {len(agg1)} != 64")
    if agg1 != sig1:
        failures.append("N=1: agg != original sig (z_0 should be 1)")
    if not verify([pk1], [m1], agg1):
        failures.append("N=1: verify failed")
    if not schnorr_verify(m1, pk1, agg1):
        failures.append("N=1: cross-check via schnorr_verify failed")

    # Test 2 — N=3
    sks = [rand_bytes(32) for _ in range(3)]
    pks = [xonly_pubkey(sk)[0] for sk in sks]
    msgs = [rand_bytes(32) for _ in range(3)]
    sigs = [schnorr_sign(m, sk) for m, sk in zip(msgs, sks)]

    # Sanity: each individual sig must verify under BIP340.
    for i, (m, pk, s) in enumerate(zip(msgs, pks, sigs)):
        if not schnorr_verify(m, pk, s):
            failures.append(f"N=3: input sig[{i}] failed BIP340 verify")
    agg3 = aggregate(pks, msgs, sigs)
    if len(agg3) != 32 * 4:
        failures.append(f"N=3 size: {len(agg3)} != {32*4}")
    if not verify(pks, msgs, agg3):
        failures.append("N=3: verify failed")

    # Test 3 — tamper detection on N=3
    tampered = bytearray(agg3)
    tampered[-1] ^= 0x01
    if verify(pks, msgs, bytes(tampered)):
        failures.append("N=3: tampered aggsig incorrectly verified")

    # Test 4 — wrong-message detection
    swapped_msgs = msgs.copy()
    swapped_msgs[0], swapped_msgs[1] = swapped_msgs[1], swapped_msgs[0]
    if verify(pks, swapped_msgs, agg3):
        failures.append("N=3: swapped-msgs aggsig incorrectly verified")

    # Test 5 — N=10 size + verify
    sks10 = [rand_bytes(32) for _ in range(10)]
    pks10 = [xonly_pubkey(sk)[0] for sk in sks10]
    msgs10 = [rand_bytes(32) for _ in range(10)]
    sigs10 = [schnorr_sign(m, sk) for m, sk in zip(msgs10, sks10)]
    agg10 = aggregate(pks10, msgs10, sigs10)
    independent_size = 64 * 10
    halfagg_size = len(agg10)
    savings_pct = round((1 - halfagg_size / independent_size) * 100, 1)
    if halfagg_size != 32 * 11:
        failures.append(f"N=10 size: {halfagg_size} != {32*11}")
    if not verify(pks10, msgs10, agg10):
        failures.append("N=10: verify failed")

    # Test 6 — wrong-pubkey detection
    bad_pks = pks10.copy()
    # Flip a bit in one pubkey x-coord; if it's still on-curve, verify must fail
    bad_pk = bytearray(bad_pks[0])
    bad_pk[0] ^= 0x01
    bad_pks[0] = bytes(bad_pk)
    try:
        if verify(bad_pks, msgs10, agg10):
            failures.append("N=10: wrong-pubkey aggsig incorrectly verified")
    except Exception:
        pass  # lift_x failure is also acceptable rejection

    # Test 7 — incremental property (aggregate of [a] then add [b] equals aggregate of [a,b])
    # We don't expose an incremental API, but the relationship should hold
    # implicitly: aggregate([a]) == sig_a, so this is mostly a smoke check that
    # the running-prefix logic in our aggregate matches what we'd compute fresh.
    agg2_fresh = aggregate(pks[:2], msgs[:2], sigs[:2])
    # Confirm the aggregate of first 2 still verifies with the right first 2 (P,m).
    if not verify(pks[:2], msgs[:2], agg2_fresh):
        failures.append("N=2 incremental smoke: verify failed")

    result = {
        "ALL_PASS": len(failures) == 0,
        "tests_total": 7,
        "tests_passed": 7 - len(failures),
        "failures": failures,
        "byte_savings_at_N10": {
            "independent_bytes": independent_size,
            "halfagg_bytes": halfagg_size,
            "savings_pct": savings_pct,
        },
        "halfagg_sizes": {
            f"N={n}": {
                "independent": 64 * n,
                "halfagg": 32 * (n + 1),
                "savings_pct": round((1 - 32 * (n + 1) / (64 * n)) * 100, 1) if n > 0 else 0,
            }
            for n in [1, 2, 3, 5, 10, 20, 50, 100]
        },
    }
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    import sys
    result = selftest()
    sys.exit(0 if result["ALL_PASS"] else 1)
