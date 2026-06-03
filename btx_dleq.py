#!/usr/bin/env python3
"""
btx_dleq.py — BIP-374 single-curve discrete log equality proofs.

Canonical-compliant port of `bitcoin/bips/bip-0374/reference.py`. 64-byte
zero-knowledge proofs that the same scalar `a` is used in two
relationships on secp256k1: `A = a·G` and `C = a·B`, without revealing `a`.

## Why BTX cares

BTX's DLC integration (`btx_dlc_demo.py`, `btx_dlc_publish.py`) already
relies on an `Oracle` publishing a long-lived pubkey `Po = d_o·G` and a
per-event nonce `Ro = r_o·G`. There is currently no on-chain proof that
the oracle's published `Po` and any other commitment derived from `d_o`
actually share the same secret.

BIP-374 DLEQ proofs fix this. An oracle can prove (e.g.) that its
secp256k1 attestation key `Po` and a corresponding rotation key
`Po' = d_o · H` (for some application-defined H ≠ G) come from the same
secret, without revealing the secret.

The primitive is also a building block for:
- **Verifiable encryption-key correctness** in adaptor sigs: prove that
  an encryption point `T` equals `t · G` for the same `t` the oracle
  will publish, without revealing `t`. Complements the existing
  adaptor-sig DLC composition.
- **Pool-rotation proofs**: a MuSig2 pool publishes a new aggregated
  key + a DLEQ tying it to a previous aggregated key, proving the
  pool's underlying secret structure hasn't changed.
- **Cross-protocol key reuse**: a maker uses the same `d` for BTX1
  signing and another protocol; DLEQ proves both pubkeys derive from
  the same `d`.

None of these are wired into BTX2 records today — this module ships the
primitive only. Integration is downstream.

## Construction (BIP-374 §3)

Generate(a, B, r, G=secp256k1_basepoint, m=None):
  A   = a · G
  C   = a · B
  t   = a XOR tagged_hash("BIP0374/aux", r)
  k   = int(tagged_hash("BIP0374/nonce", t || A_compressed || C_compressed || m')) mod N
  R1  = k · G
  R2  = k · B
  e   = int(tagged_hash("BIP0374/challenge", A || B || C || G || R1 || R2 || m)) mod N
  s   = (k + e·a) mod N
  proof = e.to_bytes(32) || s.to_bytes(32)   # 64 bytes total

Verify(A, B, C, proof, G=G, m=None):
  e, s = proof[:32], proof[32:]
  R1 = s·G − e·A
  R2 = s·B − e·C
  accept iff e == tagged_hash("BIP0374/challenge", A || B || C || G || R1 || R2 || m)

All point-byte forms are 33-byte compressed (the same convention used by
`btx_adaptor._ser_compressed`).
"""

from __future__ import annotations
from btx_taproot import (
    N, P, G,
    point_add, point_mul, lift_x, tagged_hash,
)


DLEQ_TAG_AUX = "BIP0374/aux"
DLEQ_TAG_NONCE = "BIP0374/nonce"
DLEQ_TAG_CHALLENGE = "BIP0374/challenge"


# ----------------------------- helpers -----------------------------


def _ser_compressed(pt):
    """Serialise an affine point as a 33-byte compressed pubkey."""
    if pt is None:
        raise ValueError("cannot serialise point at infinity")
    x, y = pt
    prefix = 0x02 if (y % 2 == 0) else 0x03
    return bytes([prefix]) + x.to_bytes(32, "big")


def _parse_compressed(b):
    """Parse a 33-byte compressed pubkey to an affine point."""
    if len(b) != 33:
        raise ValueError(f"compressed pubkey must be 33 bytes, got {len(b)}")
    if b[0] not in (0x02, 0x03):
        raise ValueError(f"bad compressed prefix: {b[0]:#x}")
    x = int.from_bytes(b[1:], "big")
    if x >= P:
        raise ValueError("x coord exceeds field prime")
    pt = lift_x(x)
    if pt is None:
        raise ValueError("x does not lift to a curve point")
    if b[0] == 0x03:
        pt = (pt[0], (-pt[1]) % P)
    return pt


def _point_neg(pt):
    if pt is None:
        return None
    return (pt[0], (-pt[1]) % P)


def _is_infinity(pt):
    return pt is None


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _dleq_challenge(A, B, C, R1, R2, m, GEN):
    """Tagged-hash over the 6 compressed points + optional 32-byte message."""
    if m is not None:
        if len(m) != 32:
            raise ValueError("message must be 32 bytes")
    buf = (
        _ser_compressed(A)
        + _ser_compressed(B)
        + _ser_compressed(C)
        + _ser_compressed(GEN)
        + _ser_compressed(R1)
        + _ser_compressed(R2)
        + (m if m is not None else b"")
    )
    return int.from_bytes(tagged_hash(DLEQ_TAG_CHALLENGE, buf), "big")


# ----------------------------- public API -----------------------------


def generate_proof(a: int, B_pt, r: bytes, GEN=None, m: bytes | None = None):
    """
    Generate a BIP-374 DLEQ proof.

    Args:
        a:   scalar (1 ≤ a < N)
        B_pt: secp256k1 point (the second generator/pubkey)
        r:   32-byte auxiliary randomness
        GEN: optional first generator (default: secp256k1 standard G)
        m:   optional 32-byte message bound into the challenge

    Returns:
        64-byte proof (e || s), or None if generation fails (degenerate
        cases like B==infinity or k==0).
    """
    if len(r) != 32:
        raise ValueError("aux randomness must be 32 bytes")
    if not (0 < a < N):
        return None
    if _is_infinity(B_pt):
        return None
    if m is not None and len(m) != 32:
        raise ValueError("message must be 32 bytes if provided")
    GEN = G if GEN is None else GEN

    A_pt = point_mul(GEN, a)
    C_pt = point_mul(B_pt, a)

    # t = a XOR H_aux(r)
    aux_h = tagged_hash(DLEQ_TAG_AUX, r)
    t = _xor(a.to_bytes(32, "big"), aux_h)

    m_prime = m if m is not None else b""
    nonce_input = t + _ser_compressed(A_pt) + _ser_compressed(C_pt) + m_prime
    rand = tagged_hash(DLEQ_TAG_NONCE, nonce_input)
    k = int.from_bytes(rand, "big") % N
    if k == 0:
        return None

    R1 = point_mul(GEN, k)
    R2 = point_mul(B_pt, k)
    if R1 is None or R2 is None:
        return None

    e = _dleq_challenge(A_pt, B_pt, C_pt, R1, R2, m, GEN) % N
    s = (k + e * a) % N
    proof = e.to_bytes(32, "big") + s.to_bytes(32, "big")

    # Defensive self-verify (matches canonical reference)
    if not verify_proof(A_pt, B_pt, C_pt, proof, GEN=GEN, m=m):
        return None
    return proof


def verify_proof(A_pt, B_pt, C_pt, proof: bytes, GEN=None, m: bytes | None = None) -> bool:
    """
    Verify a BIP-374 DLEQ proof.

    Args:
        A_pt, B_pt, C_pt: secp256k1 points (the statement A=a·G, C=a·B)
        proof: 64-byte (e || s) from generate_proof
        GEN: optional generator (default: standard G)
        m: optional 32-byte message that was bound at generate time

    Returns:
        True iff the proof is valid for the given statement.
    """
    if _is_infinity(A_pt) or _is_infinity(B_pt) or _is_infinity(C_pt):
        return False
    GEN = G if GEN is None else GEN
    if _is_infinity(GEN):
        return False
    if len(proof) != 64:
        return False
    e = int.from_bytes(proof[:32], "big")
    s = int.from_bytes(proof[32:], "big")
    if s >= N:
        return False
    # R1 = s·G - e·A
    sG = point_mul(GEN, s)
    eA = point_mul(A_pt, e)
    R1 = point_add(sG, _point_neg(eA))
    if R1 is None:
        return False
    # R2 = s·B - e·C
    sB = point_mul(B_pt, s)
    eC = point_mul(C_pt, e)
    R2 = point_add(sB, _point_neg(eC))
    if R2 is None:
        return False
    expected_e = _dleq_challenge(A_pt, B_pt, C_pt, R1, R2, m, GEN) % N
    return e == expected_e


# ----------------------------- selftest -----------------------------


def _selftest_basic():
    """
    Sanity round-trip: pick random-ish a, B; produce proof; verify; tamper
    a byte and re-verify (must reject).
    """
    a = 0xB7E151628AED2A6ABF7158809CF4F3C762E7160F38B4DA56A784D9045190CFEF
    b = 0x0B432B2677937381AEF05BB02A66ECD012773062CF3FA2549E44F58ED2401710
    B_pt = point_mul(G, b)
    r = b"\x01" * 32
    msg = b"\xAA" * 32

    # No-message variant
    proof = generate_proof(a, B_pt, r)
    A_pt = point_mul(G, a)
    C_pt = point_mul(B_pt, a)
    if proof is None or len(proof) != 64:
        return False
    if not verify_proof(A_pt, B_pt, C_pt, proof):
        return False
    bad = bytearray(proof); bad[0] ^= 0x01
    if verify_proof(A_pt, B_pt, C_pt, bytes(bad)):
        return False

    # With-message variant
    proof_m = generate_proof(a, B_pt, r, m=msg)
    if proof_m is None or len(proof_m) != 64:
        return False
    if not verify_proof(A_pt, B_pt, C_pt, proof_m, m=msg):
        return False
    # Wrong message → reject
    bad_msg = bytearray(msg); bad_msg[0] ^= 0x01
    if verify_proof(A_pt, B_pt, C_pt, proof_m, m=bytes(bad_msg)):
        return False

    # Determinism (same inputs → same proof)
    if generate_proof(a, B_pt, r) != proof:
        return False

    return True


def selftest(verbose: bool = True) -> bool:
    ok = _selftest_basic()
    if verbose:
        print(f"[btx_dleq] basic round-trip + 3 tamper checks: {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
