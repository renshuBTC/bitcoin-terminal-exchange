#!/usr/bin/env python3
"""
btx_s2c.py — BIP340 sign-to-contract (S2C / "pay-to-contract") for BTX.

The B4 mainnet broadcast (2026-06-02, reveal 8acf6c70…) was observed by three
independent third-party operators (mempool.space, blockstream.info, bitaps.com)
because the BTX1 magic was plainly visible at byte 38 of witness[1] of the
reveal tx. Sign-to-contract is the cryptographic primitive that lets a maker
embed a commitment to BTX1 payload *inside the random-looking nonce of a normal
BIP340 Schnorr signature*. To a passive observer the signature is structurally
indistinguishable from any other BIP340 sig.

This module ships the primitive only. Integration paths (delayed-reveal,
registry-of-R0, key-path-only commit) are surveyed in
BTX-secp256k1-zkp-followup-2026-06-03.md.

## Construction (BIP340 sign-to-contract, x-only opening)

Inputs:
  d      : 32-byte secret key
  P      : x-only pubkey derived from d (BIP340 even-y convention)
  m      : 32-byte message (transaction sighash)
  c      : arbitrary-length commitment payload (e.g. BTX1 envelope bytes)
  k0     : 32-byte initial nonce (deterministically derived from d, m, c)

Tweak:
  t = int(TaggedHash("BTX/s2c/v1", lift_x_even(k0·G).x32 || c)) mod N
  k = k0 + t                                 (mod N)
  R = k·G = k0·G + t·G                       (point addition)

BIP340 finalisation:
  if y(R) is odd:  k <- N - k   ;  R <- -R    (x-only sig is unchanged)
  e = TaggedHash("BIP0340/challenge", x(R) || x(P) || m) mod N
  s = (k + e*d_eff) mod N
  sig = x(R) || s32                          (64 bytes, valid BIP340 sig)

Opening / verify:
  Inputs: sig, m, P_xonly, R0_x (32 bytes), c
  Verifier reconstructs:
    R0 = lift_x_even(R0_x)
    t' = int(TaggedHash("BTX/s2c/v1", R0_x || c)) mod N
    R'  = R0 + t'*G
  Then accepts iff:
    (a) schnorr_verify(m, P_xonly, sig) == True               (sig is valid)
    (b) x(R') == sig[0:32]                                    (sig commits to c)

Notes:
  - The opening only requires R0_x (the x-coord of the original nonce point).
    Y-parity is forced to even by lift_x; the tweak t is computed from x(R0)
    only, so the maker and verifier agree without exchanging parity bits.
  - Hash domain "BTX/s2c/v1" is BTX-specific (NOT a BIP340 tag).
  - The selftest pins five vectors so any future port can golden-cross-test.
"""

from __future__ import annotations
from btx_taproot import (
    N, P, G,
    point_add, point_mul, lift_x,
    tagged_hash, schnorr_sign, schnorr_verify, xonly_pubkey,
)


# ----------------------------- helpers -----------------------------


def _has_even_y(pt):
    if pt is None:
        raise ValueError("point at infinity")
    return pt[1] % 2 == 0


def _x32(pt):
    return pt[0].to_bytes(32, "big")


def _bip340_challenge(R_x: bytes, P_x: bytes, m: bytes) -> int:
    return int.from_bytes(
        tagged_hash("BIP0340/challenge", R_x + P_x + m),
        "big",
    ) % N


def _s2c_tweak(R0_x: bytes, c: bytes) -> int:
    """t = TaggedHash('BTX/s2c/v1', R0_x || c) mod N."""
    if len(R0_x) != 32:
        raise ValueError("R0_x must be 32 bytes (x-only)")
    return int.from_bytes(tagged_hash("BTX/s2c/v1", R0_x + c), "big") % N


def _derive_k0(d: int, m: bytes, c: bytes, aux: bytes) -> int:
    """
    Deterministic nonce. Tag with the commitment c so different commitments
    under the same (d, m) produce different R0 — prevents nonce reuse across
    commitments.
    """
    if len(aux) != 32:
        raise ValueError("aux_rand must be 32 bytes")
    t_hash = tagged_hash("BIP0340/aux", aux)
    d_bytes = d.to_bytes(32, "big")
    masked = bytes(a ^ b for a, b in zip(d_bytes, t_hash))
    raw = tagged_hash("BTX/s2c/nonce", masked + m + c)
    k0 = int.from_bytes(raw, "big") % N
    if k0 == 0:
        raise ValueError("nonce derivation produced 0; pass a different aux_rand")
    return k0


# ----------------------------- public API -----------------------------


def s2c_sign(seckey: bytes, msg: bytes, c: bytes, aux_rand: bytes = b"\x00" * 32):
    """
    Produce a BIP340 Schnorr signature that hides a sign-to-contract
    commitment to `c`.

    Returns:
      sig:   64-byte BIP340 Schnorr signature (verifies under standard rules)
      R0_x:  32-byte x-coord of the unmodified nonce (the "opening")
    """
    if len(seckey) != 32 or len(msg) != 32:
        raise ValueError("seckey and msg must each be 32 bytes")
    d0 = int.from_bytes(seckey, "big")
    if not (1 <= d0 < N):
        raise ValueError("secret key out of range")

    # BIP340 y-parity normalisation on d
    P_pt = point_mul(G, d0)
    if _has_even_y(P_pt):
        d_eff = d0
    else:
        d_eff = N - d0
        P_pt = (P_pt[0], (-P_pt[1]) % P)
    P_x = _x32(P_pt)

    # Step 1: derive k0, force R0 to even-y (so verifier can use lift_x)
    k0_raw = _derive_k0(d_eff, msg, c, aux_rand)
    R0 = point_mul(G, k0_raw)
    if not _has_even_y(R0):
        k0 = N - k0_raw
        R0 = (R0[0], (-R0[1]) % P)
    else:
        k0 = k0_raw
    R0_x = _x32(R0)

    # Step 2: tweak by t = H(R0_x || c) and produce R = R0 + t*G
    t = _s2c_tweak(R0_x, c)
    k_tweaked = (k0 + t) % N
    if k_tweaked == 0:
        raise ValueError("k0 + t == 0; vanishingly improbable")
    R = point_add(R0, point_mul(G, t))
    if R is None:
        raise ValueError("R landed at infinity; pick different aux_rand")

    # Step 3: BIP340 finalisation — force R to even-y for the x-only sig
    if not _has_even_y(R):
        k = N - k_tweaked
        R = (R[0], (-R[1]) % P)
    else:
        k = k_tweaked
    R_x = _x32(R)

    e = _bip340_challenge(R_x, P_x, msg)
    s = (k + e * d_eff) % N
    sig = R_x + s.to_bytes(32, "big")
    return sig, R0_x


def s2c_expected_R_x(R0_x: bytes, c: bytes) -> bytes:
    """
    Given the opening (R0_x, c), compute the x-coord that a sign-to-contract
    signature MUST have if it correctly commits to c.

    This is what the verifier compares against sig[0:32].
    """
    if len(R0_x) != 32:
        raise ValueError("R0_x must be 32 bytes")
    R0 = lift_x(int.from_bytes(R0_x, "big"))
    if R0 is None:
        raise ValueError("R0_x is not on the curve")
    t = _s2c_tweak(R0_x, c)
    R = point_add(R0, point_mul(G, t))
    if R is None:
        raise ValueError("opening reconstruction landed at infinity")
    return _x32(R)


def s2c_verify(sig: bytes, msg: bytes, pubkey_xonly: bytes, R0_x: bytes, c: bytes) -> bool:
    """
    Verify a sign-to-contract signature.

    Returns True iff:
      (a) `sig` is a valid BIP340 Schnorr signature on `msg` under `pubkey_xonly`
      (b) `sig[0:32]` equals s2c_expected_R_x(R0_x, c)
    """
    if len(sig) != 64:
        return False
    if not schnorr_verify(msg, pubkey_xonly, sig):
        return False
    try:
        expected_R_x = s2c_expected_R_x(R0_x, c)
    except Exception:
        return False
    return sig[:32] == expected_R_x


def s2c_recover_c_indexer_path(sig: bytes, msg: bytes, pubkey_xonly: bytes,
                                R0_x: bytes, candidate_payloads):
    """
    Indexer-side scanning helper. Given a known R0_x and a set of candidate
    BTX payloads, returns the first payload c such that s2c_verify accepts.
    """
    if not schnorr_verify(msg, pubkey_xonly, sig):
        return None
    R_x_obs = sig[:32]
    for c in candidate_payloads:
        try:
            if s2c_expected_R_x(R0_x, c) == R_x_obs:
                return c
        except Exception:
            continue
    return None


# ----------------------------- selftest -----------------------------


def _selftest_golden_vectors():
    return [
        ("0000000000000000000000000000000000000000000000000000000000000003",
         "0000000000000000000000000000000000000000000000000000000000000000",
         "425458310000000000",
         "0000000000000000000000000000000000000000000000000000000000000000"),
        ("b7e151628aed2a6abf7158809cf4f3c762e7160f38b4da56a784d9045190cfef",
         "243f6a8885a308d313198a2e03707344a4093822299f31d0082efa98ec4e6c89",
         "deadbeef",
         "0000000000000000000000000000000000000000000000000000000000000001"),
        ("c90fdaa22168c234c4c6628b80dc1cd129024e088a67cc74020bbea63b14e5c9",
         "7e2d58d8b3bcdf1abadec7829054f90dda9805aab56c77333024b9d0a508b75c",
         "",
         "ff" * 32),
        ("0b432b2677937381aef05bb02a66ecd012773062cf3fa2549e44f58ed2401710",
         "5e2d58d8b3bcdf1abadec7829054f90dda9805aab56c77333024b9d0a508b75c",
         "01" * 64,
         "ab" * 32),
        ("0000000000000000000000000000000000000000000000000000000000000001",
         "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
         "425458312600",
         "5555555555555555555555555555555555555555555555555555555555555555"),
    ]


def selftest(verbose: bool = True) -> bool:
    """Run the full S2C selftest."""
    ok = True
    vectors = _selftest_golden_vectors()
    for i, (sk_hex, m_hex, c_hex, aux_hex) in enumerate(vectors):
        sk = bytes.fromhex(sk_hex)
        m = bytes.fromhex(m_hex)
        c = bytes.fromhex(c_hex)
        aux = bytes.fromhex(aux_hex)
        Px = xonly_pubkey(sk)[0]  # btx_taproot returns (xonly_32, point)

        sig, R0_x = s2c_sign(sk, m, c, aux)
        if len(sig) != 64 or len(R0_x) != 32:
            ok = False
            if verbose: print(f"[s2c #{i}] FAIL: bad sizes")
            continue
        if not schnorr_verify(m, Px, sig):
            ok = False
            if verbose: print(f"[s2c #{i}] FAIL: schnorr_verify rejected the produced sig")
            continue
        if not s2c_verify(sig, m, Px, R0_x, c):
            ok = False
            if verbose: print(f"[s2c #{i}] FAIL: s2c_verify rejected the legit opening")
            continue
        # tampered c
        if c:
            c_bad = bytearray(c)
            c_bad[0] ^= 0xFF
        else:
            c_bad = b"\x42"
        if s2c_verify(sig, m, Px, R0_x, bytes(c_bad)):
            ok = False
            if verbose: print(f"[s2c #{i}] FAIL: accepted tampered c")
            continue
        # indexer recovery
        decoys = [b"decoy" + bytes([j]) * 8 for j in range(4)]
        candidates = decoys[:2] + [c] + decoys[2:]
        rec = s2c_recover_c_indexer_path(sig, m, Px, R0_x, candidates)
        if rec != c:
            ok = False
            if verbose: print(f"[s2c #{i}] FAIL: indexer recovery returned {rec!r}, want {c!r}")
            continue
        # determinism
        sig2, R0_x2 = s2c_sign(sk, m, c, aux)
        if sig2 != sig or R0_x2 != R0_x:
            ok = False
            if verbose: print(f"[s2c #{i}] FAIL: non-deterministic sign")
            continue
        if verbose:
            print(f"[s2c #{i}] OK  sig={sig.hex()[:16]}...  R0_x={R0_x.hex()[:16]}...")
    if verbose:
        print(f"\n[s2c] {'ALL VECTORS PASS' if ok else 'FAILED'}")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
