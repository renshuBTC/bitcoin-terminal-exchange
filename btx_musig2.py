#!/usr/bin/env python3
"""
btx_musig2.py — BIP327 KeyAgg + trusted-aggregator pool-signing for BTX.

This module implements the MuSig2 KeyAggregation primitive per BIP327 §3,
plus a "trusted-aggregator" signing path for demonstration / research use.

**What KeyAgg buys BTX:** N makers can pre-aggregate their individual
public keys into a single aggregated pubkey Q_agg. They sign offers
cooperatively (via the MuSig2 2-round protocol, OR via the simplified
trusted-aggregator path provided here). On-chain, an offer signed by
the N-maker pool is **indistinguishable** from an offer signed by a
single maker — same 64-byte Schnorr signature, same artifact format,
same indexer code path.

**What this module deliberately does NOT do:** the full BIP327 2-round
interactive signing protocol with proper nonce handling. That protocol
requires careful state management (round-1 nonces must never be reused
across signing sessions, partial signatures must never leak the nonce,
etc.); getting it wrong leads to catastrophic secret-key extraction.
For production maker-pool deployment, BTX should use a vetted library
(rust-secp256k1-zkp's musig module, or a Python wrapper around it).

The included `pool_sign_demo()` function is a "trusted-aggregator"
variant: all N pool members hand their secret keys to a single
aggregator who computes the aggregated secret and signs with vanilla
btx_taproot.schnorr_sign. This is **not secure** for production
(any pool member with the aggregator's role can sign alone), but it
faithfully demonstrates that KeyAgg's output behaves as a normal
Schnorr key — which is the architectural property the maker-pool
feature depends on.

References:
  - BIP327 (Tim Ruffing, Jonas Nick, Yannick Seurin, Pieter Wuille,
    Andrew Poelstra): https://github.com/bitcoin/bips/blob/master/bip-0327.mediawiki
  - BlockstreamResearch/secp256k1-zkp@8099999 src/modules/musig — the
    C reference implementation
  - BTX-secp256k1-zkp-scouting-2026-06-02.md section 2
"""

import os, json, hashlib
from btx_taproot import (
    P, N, G,
    point_add, point_mul, lift_x,
    tagged_hash, schnorr_sign, schnorr_verify, xonly_pubkey,
)


# ----------------------------- helpers -----------------------------


def _point_neg(pt):
    if pt is None:
        return None
    x, y = pt
    return (x, (-y) % P)


def _has_even_y(pt):
    if pt is None:
        raise ValueError("point at infinity has no parity")
    return pt[1] % 2 == 0


def _xonly_to_point(pk_xonly_32):
    """Lift a 32-byte x-only pubkey to its even-y point (BIP340 convention)."""
    return lift_x(int.from_bytes(pk_xonly_32, "big"))


def _point_to_xonly(pt):
    """Return the 32-byte x-coordinate of a point (the BIP340 x-only encoding)."""
    if pt is None:
        raise ValueError("cannot serialize point at infinity")
    return pt[0].to_bytes(32, "big")


# ----------------------------- BIP327 KeyAgg -----------------------------


def _hash_keyagg_list(pubkeys_xonly):
    """L = TaggedHash('KeyAgg list', X_1 || X_2 || ... || X_n)."""
    return tagged_hash("KeyAgg list", b"".join(pubkeys_xonly))


def _hash_keyagg_coefficient(L, pk_xonly):
    """KeyAggCoeff(L, X_i) = int(TaggedHash('KeyAgg coefficient', L || X_i)) mod N."""
    return int.from_bytes(
        tagged_hash("KeyAgg coefficient", L + pk_xonly), "big"
    ) % N


def _find_second_key(pubkeys_xonly):
    """
    Per BIP327: the 'second key' (used to set its coefficient to 1) is the
    SECOND DISTINCT pubkey in the list — the first one that differs from
    pubkeys[0]. If all pubkeys are equal, there's no second key (return None).

    The point of this rule is to defeat the rogue-key attack where one signer
    chooses their pubkey based on others' pubkeys: BIP327 fixes the second
    key's coefficient to 1 so it can't be canceled.
    """
    first = pubkeys_xonly[0]
    for pk in pubkeys_xonly[1:]:
        if pk != first:
            return pk
    return None  # all equal — degenerate case (n-signer with same key)


def key_agg(pubkeys_xonly):
    """
    Aggregate N x-only pubkeys per BIP327 KeyAgg.

    Args:
        pubkeys_xonly: list of N 32-byte x-only pubkeys, in the
                       application-defined order. The order is significant
                       (it's committed via the L hash).

    Returns:
        dict with:
          'L':           the 32-byte KeyAgg list hash
          'agg_xonly':   32-byte aggregated x-only pubkey  (BIP340-style)
          'agg_point':   the full point Q (with even y)
          'coefficients': list of N coefficients a_i
          'gacc':        +1 if Q (before x-only normalization) had even y, else -1.
                         Needed during signing to apply parity to the secret keys.
          'second_key':  the second-distinct pubkey used to gate the
                         rogue-key defense (None if all pubkeys are equal).
    """
    n = len(pubkeys_xonly)
    if n == 0:
        raise ValueError("KeyAgg needs ≥1 pubkey")
    for pk in pubkeys_xonly:
        if len(pk) != 32:
            raise ValueError(f"pubkey not 32 bytes: {len(pk)}")

    L = _hash_keyagg_list(pubkeys_xonly)
    second = _find_second_key(pubkeys_xonly)

    coefficients = []
    Q_raw = None  # aggregating point
    for pk in pubkeys_xonly:
        if second is not None and pk == second:
            a_i = 1
        else:
            a_i = _hash_keyagg_coefficient(L, pk)
        coefficients.append(a_i)

        P_i = _xonly_to_point(pk)
        if P_i is None:
            raise ValueError(f"pubkey not on curve: {pk.hex()}")

        term = point_mul(P_i, a_i)
        Q_raw = term if Q_raw is None else point_add(Q_raw, term)

    if Q_raw is None:
        raise ValueError("aggregation yielded point at infinity")

    if _has_even_y(Q_raw):
        Q = Q_raw
        gacc = 1
    else:
        Q = _point_neg(Q_raw)
        gacc = -1

    return {
        "L": L,
        "agg_xonly": _point_to_xonly(Q),
        "agg_point": Q,
        "coefficients": coefficients,
        "gacc": gacc,
        "second_key": second,
    }


# ----------------------------- trusted-aggregator pool signing -----------------------------


def pool_sign_demo(seckeys, msg):
    """
    Demonstration-only "trusted-aggregator" pool signing.

    The aggregator collects all N secret keys, computes the aggregated
    secret  d_agg = sum(a_i · d_i') mod N  where d_i' is each signer's
    EFFECTIVE secret after BIP340 parity normalization, multiplied by gacc
    to match the parity-flipped aggregated point. Then signs `msg` with
    btx_taproot.schnorr_sign over d_agg.

    The resulting signature verifies as a normal BIP340 Schnorr signature
    under the aggregated pubkey returned by key_agg().

    Args:
        seckeys: list of N 32-byte secret keys
        msg:     32-byte message

    Returns:
        (agg_xonly, sig64) — aggregated pubkey + BIP340 signature
    """
    # Derive xonly pubkeys from the seckeys (matches what each signer would publish)
    pubkeys = [xonly_pubkey(sk)[0] for sk in seckeys]
    agg = key_agg(pubkeys)
    coeffs = agg["coefficients"]
    gacc = agg["gacc"]

    d_agg = 0
    for sk_bytes, a_i in zip(seckeys, coeffs):
        d0 = int.from_bytes(sk_bytes, "big")
        if not (1 <= d0 < N):
            raise ValueError("seckey out of range")
        # BIP340 normalization: if d0·G has odd y, the effective d is N - d0.
        P_pt = point_mul(G, d0)
        d_eff = d0 if _has_even_y(P_pt) else (N - d0)
        # Apply gacc parity: if aggregated point had odd y (gacc=-1), we negate the
        # contribution so the signature ends up valid against the parity-flipped agg pubkey.
        if gacc == -1:
            d_eff = N - d_eff
        d_agg = (d_agg + a_i * d_eff) % N

    if d_agg == 0:
        raise ValueError("aggregated secret is zero (vanishingly unlikely)")

    # Sign with vanilla BIP340.
    sk_agg = d_agg.to_bytes(32, "big")
    sig = schnorr_sign(msg, sk_agg)
    return agg["agg_xonly"], sig


# ----------------------------- selftest -----------------------------


def _good_sk(rand_bytes):
    while True:
        s = rand_bytes(32)
        x = int.from_bytes(s, "big")
        if 1 <= x < N:
            return s


def selftest(seed=None):
    if seed is not None:
        import random
        random.seed(seed)
        def rand_bytes(n):
            return bytes(random.randint(0, 255) for _ in range(n))
    else:
        rand_bytes = os.urandom

    failures = []

    # --- Test 1: KeyAgg determinism ---
    sks = [_good_sk(rand_bytes) for _ in range(3)]
    pks = [xonly_pubkey(sk)[0] for sk in sks]
    a1 = key_agg(pks)
    a2 = key_agg(pks)
    if a1["agg_xonly"] != a2["agg_xonly"]:
        failures.append("T1: KeyAgg is not deterministic")
    if a1["coefficients"] != a2["coefficients"]:
        failures.append("T1: KeyAgg coefficients differ across calls")

    # --- Test 2: Order matters ---
    # MuSig2 KeyAgg's hash commits to order, so different orderings produce
    # different aggregates. (This is the BIP327-specified behavior — the
    # protocol expects participants to agree on a canonical order.)
    pks_rev = list(reversed(pks))
    a_rev = key_agg(pks_rev)
    if a_rev["agg_xonly"] == a1["agg_xonly"] and len(set(pks)) > 1:
        failures.append("T2: reversed-order KeyAgg gave same result (unexpected for ≥2 distinct pks)")

    # --- Test 3: 'Second key' coefficient is 1 ---
    if a1["second_key"] is not None:
        idx = pks.index(a1["second_key"])
        if a1["coefficients"][idx] != 1:
            failures.append(f"T3: second-key coeff is {a1['coefficients'][idx]}, expected 1")

    # --- Test 4: Trusted-aggregator signing produces valid sig under agg pubkey ---
    msg = rand_bytes(32)
    agg_pk, sig = pool_sign_demo(sks, msg)
    if not schnorr_verify(msg, agg_pk, sig):
        failures.append("T4: pool-signed signature failed schnorr_verify under aggregated pubkey")

    # --- Test 5: Tampered msg rejects ---
    bad_msg = bytearray(msg)
    bad_msg[0] ^= 0x01
    if schnorr_verify(bytes(bad_msg), agg_pk, sig):
        failures.append("T5: tampered msg incorrectly verified")

    # --- Test 6: Rogue-key defense — coefficient depends on whole pubkey set ---
    # If the rogue-key defense works, an attacker who picks pk_2 = X - pk_1 (so
    # the aggregate would be the attacker's chosen point) cannot succeed because
    # the coefficient hash binds pk_2 to L = H(pk_1 || pk_2). Adding a third
    # signer with a chosen pubkey would change L → all coefficients change →
    # the rogue construction breaks.
    # Verify the coefficient binding by spot-checking that pk[0]'s coefficient
    # depends on what other pubkeys are in the set.
    pks_with_extra = pks + [xonly_pubkey(_good_sk(rand_bytes))[0]]
    a_extra = key_agg(pks_with_extra)
    if a1["coefficients"][0] == a_extra["coefficients"][0]:
        failures.append("T6: coefficient for pk[0] didn't change when extra pubkey added — rogue-key defense weak")

    # --- Test 7: Single-signer KeyAgg (degenerate but should work) ---
    a_single = key_agg([pks[0]])
    if a_single["coefficients"][0] != 1:
        # In strict BIP327, the single-signer KeyAgg... hmm, actually a single-
        # signer case has no "second key" so the only key's coeff is computed
        # from the hash. The single-signer agg_xonly may differ from pks[0].
        # Let's not be strict here; just check the round-trip works.
        pass
    # Try signing with the single-signer aggregation.
    agg_pk1, sig1 = pool_sign_demo([sks[0]], msg)
    if not schnorr_verify(msg, agg_pk1, sig1):
        failures.append("T7: single-signer pool signature failed verify")

    # --- Test 8: 5-signer pool ---
    sks5 = [_good_sk(rand_bytes) for _ in range(5)]
    agg_pk5, sig5 = pool_sign_demo(sks5, msg)
    if not schnorr_verify(msg, agg_pk5, sig5):
        failures.append("T8: 5-signer pool signature failed verify")

    result = {
        "ALL_PASS": len(failures) == 0,
        "tests_total": 8,
        "tests_passed": 8 - len(failures),
        "failures": failures,
        "primitive_info": {
            "aggregated_pubkey_bytes": 32,    # x-only, same as any BIP340 pubkey
            "signature_bytes": 64,            # vanilla BIP340 Schnorr
            "on_chain_distinguishable_from_single_signer": False,
            "what_BTX2_gets":
                "N makers pre-aggregate keys; offers signed by the pool look "
                "identical on-chain to single-maker offers. Maker rotation, "
                "shared-custody offer UTXOs, and institutional-maker semantics "
                "all become possible without any indexer or consensus change.",
            "deferred_for_production":
                "Full BIP327 2-round signing protocol (interactive nonce handling). "
                "The trusted-aggregator path included here is for research demo only.",
        },
    }
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    import sys
    result = selftest()
    sys.exit(0 if result["ALL_PASS"] else 1)
