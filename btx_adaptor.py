#!/usr/bin/env python3
"""
btx_adaptor.py — Schnorr adaptor signatures for BTX2 conditional orders.

An adaptor signature is a "verifiably encrypted" Schnorr signature: a maker
can publish a pre-signature locked to a secret t known only to be revealed
when some condition fires (an oracle attests, a hash preimage is shown,
a counterparty completes a payment). The taker can VERIFY the pre-signature
is well-formed without knowing t. Once t is revealed, anyone holding the
pre-sig can DECRYPT it into a normal Schnorr signature that settles the
swap. Conversely, given the pre-sig and the eventually-revealed real sig,
anyone can RECOVER t — useful for cross-chain atomic swaps.

This is the cryptographic primitive behind:
  - Discreet Log Contracts (DLCs) — bets / futures / options based on oracle
    attestations to a discrete log point.
  - Point-Time-Lock-Contracts (PTLCs) — Lightning's replacement for HTLCs,
    same-preimage as the secret t.
  - Cross-chain atomic swaps where one side reveals t to settle, and the
    other side learns t to settle on a different chain.

The C reference at BlockstreamResearch/secp256k1-zkp src/modules/ecdsa_adaptor
implements ECDSA adaptor sigs (162-byte payload, more complex due to ECDSA's
nonce structure). This module implements SCHNORR adaptor sigs (64-byte
adaptor sig, simpler arithmetic), built on BTX's existing BIP340 primitives
in btx_taproot.py.

Construction (from Lloyd Fournier's "One-Time Verifiably Encrypted Signatures"
and the generalized-channels paper, adapted to BIP340):

  Given signing key d, pubkey P = d·G, message m, encryption point T = t·G:
  - Pick nonce k → R = k·G
  - Compute R̂ = R + T  (the "completed nonce")
  - e = TaggedHash("BIP0340/challenge", x(R̂) || x(P) || m)
  - s_a = (k + e·d) mod N
  - Pre-sig = (R̂, s_a) — note R̂ is published as a 33-byte compressed point
    (NOT BIP340 x-only) so the parity is preserved across decryption.

  pre_verify(pre_sig, P, m, T) = checks  s_a·G + T == R̂ + e·P
  decrypt(pre_sig, t)         = (R̂, s = s_a + t mod N)
  recover(pre_sig, real_sig)  = t = (s - s_a) mod N

The decrypted (R̂, s) satisfies  s·G == R̂ + e·P, which is the normal Schnorr
verification equation. We expose verify_schnorr_with_parity() to check it
without requiring BIP340 x-only normalization — that's what BTX2's adaptor-
order indexer would call. On-chain settlement (where BIP340 normalization
matters) requires negating s if R̂ has odd y.

What this module does NOT do:
  - Multi-signer adaptor sigs (would need MuSig2 + adaptor extension).
  - ECDSA adaptor sigs (the C reference covers those; not needed for BTX
    since BTX uses Schnorr for the Taproot script-path spend).
  - Standalone DLC oracle protocols. This is the cryptographic primitive
    only; oracle attestation choreography is a separate layer.
"""

import os, json
from btx_taproot import (
    P, N, G,
    point_add, point_mul, lift_x,
    tagged_hash, schnorr_sign, schnorr_verify, xonly_pubkey,
)


# ----------------------------- helpers -----------------------------


def _point_neg(pt):
    """Negate a point: (x, y) → (x, -y)."""
    if pt is None:
        return None
    x, y = pt
    return (x, (-y) % P)


def _has_even_y(pt):
    """True iff y is even (BIP340 convention)."""
    if pt is None:
        raise ValueError("point at infinity has no y-parity")
    return pt[1] % 2 == 0


def _bip340_challenge(R_hat_x_bytes, P_x_bytes, msg):
    """e = TaggedHash('BIP0340/challenge', R̂_x || P_x || m)  reduced mod N."""
    return int.from_bytes(
        tagged_hash("BIP0340/challenge", R_hat_x_bytes + P_x_bytes + msg),
        "big",
    ) % N


def _ser_compressed(pt):
    """Serialize an affine point as a 33-byte compressed pubkey."""
    if pt is None:
        raise ValueError("cannot serialize point at infinity")
    x, y = pt
    prefix = 0x02 if (y % 2 == 0) else 0x03
    return bytes([prefix]) + x.to_bytes(32, "big")


def _parse_compressed(b):
    """Parse a 33-byte compressed pubkey back into an affine point."""
    if len(b) != 33:
        raise ValueError(f"compressed point must be 33 bytes, got {len(b)}")
    if b[0] not in (0x02, 0x03):
        raise ValueError(f"bad compressed prefix: {b[0]:#x}")
    x = int.from_bytes(b[1:], "big")
    pt = lift_x(x)  # even-y point with that x-coordinate
    if b[0] == 0x03:
        pt = _point_neg(pt)
    return pt


# ----------------------------- API -----------------------------


def pre_sign(seckey, msg, T):
    """
    Pre-sign a message under encryption point T.

    Args:
        seckey: 32-byte signing key
        msg:    32-byte message
        T:      either a 33-byte compressed pubkey or an (x, y) point

    Returns:
        adaptor_sig = 33 + 32 = 65 bytes:  compressed(R̂) || s_a
    """
    if isinstance(T, (bytes, bytearray)):
        T_pt = _parse_compressed(bytes(T))
    else:
        T_pt = T
    if T_pt is None:
        raise ValueError("encryption point T cannot be infinity")
    if len(seckey) != 32 or len(msg) != 32:
        raise ValueError("seckey and msg must each be 32 bytes")

    d0 = int.from_bytes(seckey, "big")
    if not (1 <= d0 < N):
        raise ValueError("secret key out of range")

    # BIP340 y-parity normalization: the canonical pubkey is the even-y
    # version, so flip d if d0·G has odd y. After this, P_pt has even y,
    # which matches what lift_x(pubkey_xonly) gives the verifier.
    P_pt_raw = point_mul(G, d0)
    if _has_even_y(P_pt_raw):
        d = d0
        P_pt = P_pt_raw
    else:
        d = N - d0
        P_pt = (P_pt_raw[0], (-P_pt_raw[1]) % P)

    # Deterministic nonce derivation: tag the nonce with the encryption point
    # to avoid nonce reuse across different (m, T) pairs from the same key.
    aux = b"\x00" * 32  # no auxiliary randomness in the API surface here
    t_hash = tagged_hash("BIP0340/aux", aux)
    d_bytes = d.to_bytes(32, "big")
    k_hash_input = bytes(d_byte ^ a_byte for d_byte, a_byte in zip(d_bytes, t_hash))
    k = int.from_bytes(
        tagged_hash(
            "BTX/adaptor/nonce",
            k_hash_input + P_pt[0].to_bytes(32, "big") + _ser_compressed(T_pt) + msg,
        ),
        "big",
    ) % N
    if k == 0:
        raise ValueError("nonce derivation produced 0; retry with different aux")

    R = point_mul(G, k)
    R_hat = point_add(R, T_pt)
    if R_hat is None:
        # Cosmically improbable: k·G + T = 0  ⇒  T = -k·G
        raise ValueError("R̂ landed at point at infinity; pick a different nonce")

    R_hat_x = R_hat[0].to_bytes(32, "big")
    P_x = P_pt[0].to_bytes(32, "big")
    e = _bip340_challenge(R_hat_x, P_x, msg)
    s_a = (k + e * d) % N

    return _ser_compressed(R_hat) + s_a.to_bytes(32, "big")


def pre_verify(adaptor_sig, pubkey_xonly, msg, T):
    """
    Verify an adaptor signature is well-formed under (pubkey, msg) and T.

    Returns True iff  s_a·G + T == R̂ + e·P  where e = TaggedHash on (R̂_x, P_x, m).
    """
    if len(adaptor_sig) != 65:
        return False
    if len(pubkey_xonly) != 32 or len(msg) != 32:
        return False

    try:
        R_hat = _parse_compressed(adaptor_sig[:33])
        s_a = int.from_bytes(adaptor_sig[33:], "big")
        if s_a >= N:
            return False

        P_pt = lift_x(int.from_bytes(pubkey_xonly, "big"))
        if isinstance(T, (bytes, bytearray)):
            T_pt = _parse_compressed(bytes(T))
        else:
            T_pt = T
    except (ValueError, AssertionError):
        return False
    if R_hat is None or P_pt is None or T_pt is None:
        return False

    R_hat_x = R_hat[0].to_bytes(32, "big")
    P_x = pubkey_xonly
    e = _bip340_challenge(R_hat_x, P_x, msg)

    # LHS: s_a · G + T
    lhs = point_add(point_mul(G, s_a), T_pt)
    # RHS: R̂ + e · P
    rhs = point_add(R_hat, point_mul(P_pt, e))
    return lhs == rhs


def decrypt(adaptor_sig, t_secret):
    """
    Decrypt an adaptor sig given the secret t (where T = t·G).

    Returns a "completed" signature pair (R̂_compressed_33B, s_32B) — 65 bytes.
    Satisfies the Schnorr verification equation s·G == R̂ + e·P.
    """
    if len(adaptor_sig) != 65 or len(t_secret) != 32:
        raise ValueError("bad lengths for adaptor sig (65B) or t (32B)")
    t = int.from_bytes(t_secret, "big")
    if not (1 <= t < N):
        raise ValueError("t out of range")
    s_a = int.from_bytes(adaptor_sig[33:], "big")
    s = (s_a + t) % N
    return adaptor_sig[:33] + s.to_bytes(32, "big")


def recover(adaptor_sig, completed_sig):
    """
    Given the adaptor pre-sig and the decrypted real sig, recover the secret t.

    Returns 32-byte t such that  T = t·G  is the encryption point used at
    pre-sign time. Anyone observing both sigs can extract t — this is what
    makes adaptor sigs the basis for cross-chain atomic swaps.
    """
    if len(adaptor_sig) != 65 or len(completed_sig) != 65:
        raise ValueError("bad lengths")
    if adaptor_sig[:33] != completed_sig[:33]:
        raise ValueError("R̂ mismatch — these sigs are not adaptor-pair")
    s_a = int.from_bytes(adaptor_sig[33:], "big")
    s = int.from_bytes(completed_sig[33:], "big")
    t = (s - s_a) % N
    return t.to_bytes(32, "big")


def verify_completed(completed_sig, pubkey_xonly, msg):
    """
    Verify a decrypted adaptor sig satisfies the Schnorr equation.

    NOTE: this is NOT strictly BIP340 schnorr_verify because R̂ may have odd y
    (BIP340 forbids that). For on-chain settlement, the maker has to negate s
    if R̂'s y is odd, then BIP340 schnorr_verify accepts. For off-chain BTX2
    state machine checks (e.g., 'has the oracle attested yet?'), this verify
    is the right one.
    """
    if len(completed_sig) != 65:
        return False
    try:
        R_hat = _parse_compressed(completed_sig[:33])
        s = int.from_bytes(completed_sig[33:], "big")
        if s >= N:
            return False
        P_pt = lift_x(int.from_bytes(pubkey_xonly, "big"))
    except (ValueError, AssertionError):
        return False
    if R_hat is None or P_pt is None:
        return False

    R_hat_x = R_hat[0].to_bytes(32, "big")
    P_x = pubkey_xonly
    e = _bip340_challenge(R_hat_x, P_x, msg)

    # s·G == R̂ + e·P
    lhs = point_mul(G, s)
    rhs = point_add(R_hat, point_mul(P_pt, e))
    return lhs == rhs


# ----------------------------- selftest -----------------------------


def selftest(seed=None):
    """
    Tests:
      1. Roundtrip — pre_sign → pre_verify → decrypt → verify_completed
      2. Recovery — given pre-sig + completed, recover t and confirm T = t·G
      3. Wrong-t decrypt — using a wrong t produces a sig that fails verify
      4. Tampered pre-sig — flipped byte → pre_verify fails
      5. Wrong-encryption-point — verifying with a different T fails
      6. DLC-style end-to-end scenario — maker pre-signs, oracle attests,
         taker decrypts, swap settles, anyone can recover oracle's t.
    """
    if seed is not None:
        import random
        random.seed(seed)
        def rand_bytes(n):
            return bytes(random.randint(0, 255) for _ in range(n))
    else:
        rand_bytes = os.urandom

    def _good_sk():
        while True:
            s = rand_bytes(32)
            x = int.from_bytes(s, "big")
            if 1 <= x < N:
                return s

    failures = []

    # --- Test 1: roundtrip ---
    maker_sk = _good_sk()
    maker_pk = xonly_pubkey(maker_sk)[0]
    oracle_t = _good_sk()
    T = point_mul(G, int.from_bytes(oracle_t, "big"))
    msg = rand_bytes(32)

    adaptor = pre_sign(maker_sk, msg, T)
    if len(adaptor) != 65:
        failures.append(f"T1: adaptor sig size {len(adaptor)} != 65")
    if not pre_verify(adaptor, maker_pk, msg, T):
        failures.append("T1: pre_verify failed on fresh adaptor sig")
    completed = decrypt(adaptor, oracle_t)
    if not verify_completed(completed, maker_pk, msg):
        failures.append("T1: decrypted sig fails verify")

    # --- Test 2: secret recovery ---
    recovered = recover(adaptor, completed)
    if recovered != oracle_t:
        failures.append(f"T2: recovered t {recovered.hex()[:8]} != original {oracle_t.hex()[:8]}")

    # --- Test 3: wrong-t decrypt ---
    wrong_t = _good_sk()
    if wrong_t == oracle_t:
        wrong_t = bytes([wrong_t[0] ^ 1]) + wrong_t[1:]
    fake_completed = decrypt(adaptor, wrong_t)
    if verify_completed(fake_completed, maker_pk, msg):
        failures.append("T3: completed sig with wrong t incorrectly verified")

    # --- Test 4: tamper detection on pre-sig ---
    tampered = bytearray(adaptor)
    tampered[-1] ^= 0x01
    if pre_verify(bytes(tampered), maker_pk, msg, T):
        failures.append("T4: tampered pre-sig incorrectly pre-verified")

    # --- Test 5: wrong encryption point ---
    other_t = _good_sk()
    other_T = point_mul(G, int.from_bytes(other_t, "big"))
    if pre_verify(adaptor, maker_pk, msg, other_T):
        failures.append("T5: pre-sig verified under wrong T (encryption-point binding broken)")

    # --- Test 6: DLC-style scenario ---
    # A "swap" message: 'I, the maker, agree to atomic-swap if oracle signs Y'.
    swap_msg = tagged_hash("BTX/adaptor/scenario", b"BTC-USD oracle outcome Y at block 1000000")
    sk = _good_sk()
    pk = xonly_pubkey(sk)[0]
    oracle_secret = _good_sk()
    oracle_point = point_mul(G, int.from_bytes(oracle_secret, "big"))

    # Maker publishes adaptor sig.
    a = pre_sign(sk, swap_msg, oracle_point)
    # Taker verifies (without knowing the oracle's secret).
    if not pre_verify(a, pk, swap_msg, oracle_point):
        failures.append("T6: DLC pre-verify failed")
    # Oracle eventually publishes its secret.
    c = decrypt(a, oracle_secret)
    # Anyone can now extract the oracle's secret from on-chain settlement,
    # which is how cross-chain atomic swaps propagate the unlock.
    if recover(a, c) != oracle_secret:
        failures.append("T6: DLC oracle-secret recovery failed")
    if not verify_completed(c, pk, swap_msg):
        failures.append("T6: DLC completed sig fails verify")

    result = {
        "ALL_PASS": len(failures) == 0,
        "tests_total": 6,
        "tests_passed": 6 - len(failures),
        "failures": failures,
        "primitive_sizes": {
            "adaptor_sig_bytes": 65,        # 33 (compressed R̂) + 32 (s_a)
            "completed_sig_bytes": 65,      # same format, s instead of s_a
            "secret_t_bytes": 32,
            "encryption_point_T_bytes": 33, # compressed
            # By comparison, the secp256k1-zkp ECDSA adaptor sig is 162 bytes.
            "comparison_vs_ecdsa_adaptor_zkp_bytes": 162,
        },
    }
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    import sys
    result = selftest()
    sys.exit(0 if result["ALL_PASS"] else 1)
