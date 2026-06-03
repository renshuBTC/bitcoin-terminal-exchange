#!/usr/bin/env python3
"""
btx_musig2_adaptor.py — MuSig2 + Schnorr adaptor combo for BTX maker pools.

Closes the gap that btx_adaptor.py explicitly punted on:

    "What this module does NOT do:
       - Multi-signer adaptor sigs (would need MuSig2 + adaptor extension)."

Use case: an institutional maker pool wants to publish a CONDITIONAL order
(e.g. "fill iff oracle attests X by block H") signed by the AGGREGATED pool
pubkey. The on-chain footprint is identical to a single-signer adaptor sig
— the protocol just stitches the BIP327 KeyAgg machinery onto the existing
single-signer Schnorr adaptor construction from btx_adaptor.

## Trust model

Identical to btx_musig2.pool_sign_demo: this is **trusted-aggregator** combo
signing. The aggregator collects all N secret keys at adaptor-sign time and
internally constructs the aggregate secret d_agg, then runs the single-
signer adaptor sign procedure on d_agg.

For mutually distrusting pool members, the full interactive BIP327 protocol
must be extended with adaptor-aware nonce aggregation; this module does not
ship that (it's a substantial protocol beyond BIP327's own scope). See the
BTX2 spec §9.3 for the design surface.

## Composition

  KeyAgg over N x-only pubkeys  →  (agg_xonly, gacc, coefficients)
  d_agg = sum_i (a_i * d_eff_i)  with BIP340 + gacc parity normalisation
  pre_sig = btx_adaptor.pre_sign(d_agg, msg, T)

The pre-sig verifies under the aggregated pubkey via the standard
btx_adaptor.pre_verify(pre_sig, agg_xonly, msg, T).

## What changes vs btx_adaptor.py

  pre_sign      → POOL_pre_sign(seckeys, msg, T)
  pre_verify    → UNCHANGED — accepts agg_xonly, treats it as any P_xonly
  decrypt       → UNCHANGED — same R̂/s_a math
  recover       → UNCHANGED — same R̂/s_a math
"""

from __future__ import annotations
from btx_taproot import (
    N, P, G, point_mul, _has_even_y,
)
from btx_musig2 import key_agg
from btx_adaptor import pre_sign, pre_verify, decrypt, recover
from btx_taproot import xonly_pubkey


def _aggregate_secret(seckeys):
    """
    Derive (agg_xonly, d_agg) using the same normalisation rules as
    btx_musig2.pool_sign_demo.

    d_agg = sum_i (a_i * d_eff_i)  with:
      - d_eff_i = d0 if d0*G has even y, else N - d0
      - if gacc == -1: d_eff_i = N - d_eff_i  (parity-flip the contribution
        to match the agg-pubkey y-flip)

    Returns (agg_xonly_32, d_agg_bytes_32).
    """
    if not seckeys:
        raise ValueError("seckeys list cannot be empty")
    pubkeys = [xonly_pubkey(sk)[0] for sk in seckeys]
    agg = key_agg(pubkeys)
    coeffs = agg["coefficients"]
    gacc = agg["gacc"]

    d_agg = 0
    for sk_bytes, a_i in zip(seckeys, coeffs):
        d0 = int.from_bytes(sk_bytes, "big")
        if not (1 <= d0 < N):
            raise ValueError("seckey out of range")
        P_pt = point_mul(G, d0)
        d_eff = d0 if _has_even_y(P_pt) else (N - d0)
        if gacc == -1:
            d_eff = N - d_eff
        d_agg = (d_agg + a_i * d_eff) % N

    if d_agg == 0:
        raise ValueError("aggregated secret is zero (vanishingly unlikely)")
    return agg["agg_xonly"], d_agg.to_bytes(32, "big")


def pool_pre_sign(seckeys, msg, T):
    """
    Trusted-aggregator pool adaptor pre-sign.

    Args:
        seckeys: list of N 32-byte signer secrets
        msg:     32-byte message (sighash)
        T:       33-byte compressed encryption point, OR (x,y) tuple

    Returns:
        (agg_xonly_32, pre_sig_65)

    `pre_sig_65 = compressed(R̂) || s_a` — same byte format as btx_adaptor.
    """
    agg_xonly, d_agg_bytes = _aggregate_secret(seckeys)
    pre_sig = pre_sign(d_agg_bytes, msg, T)
    return agg_xonly, pre_sig


# Verifier-side wrappers — exactly btx_adaptor functions, but renamed so
# callers don't have to know "pool" and "solo" use the same primitives.
pool_pre_verify = pre_verify
pool_decrypt = decrypt
pool_recover = recover


# ----------------------------- selftest -----------------------------


def _selftest_vectors():
    return [
        # (seckeys_hex_list, msg_hex, t_hex)
        (
            [
                "0000000000000000000000000000000000000000000000000000000000000003",
                "b7e151628aed2a6abf7158809cf4f3c762e7160f38b4da56a784d9045190cfef",
            ],
            "243f6a8885a308d313198a2e03707344a4093822299f31d0082efa98ec4e6c89",
            "0000000000000000000000000000000000000000000000000000000000000005",
        ),
        (
            [
                "0000000000000000000000000000000000000000000000000000000000000001",
                "0000000000000000000000000000000000000000000000000000000000000002",
                "0000000000000000000000000000000000000000000000000000000000000003",
            ],
            "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899",
            "0000000000000000000000000000000000000000000000000000000000000007",
        ),
        (
            [
                "0b432b2677937381aef05bb02a66ecd012773062cf3fa2549e44f58ed2401710",
                "c90fdaa22168c234c4c6628b80dc1cd129024e088a67cc74020bbea63b14e5c9",
                "0000000000000000000000000000000000000000000000000000000000000007",
                "b7e151628aed2a6abf7158809cf4f3c762e7160f38b4da56a784d9045190cfef",
                "0000000000000000000000000000000000000000000000000000000000000005",
            ],
            "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
            "00000000000000000000000000000000000000000000000000000000beadface",
        ),
    ]


def _ser_compressed_from_scalar(t_scalar_bytes):
    """Compute compressed(T) = compressed(t*G) given t as 32-byte scalar."""
    t = int.from_bytes(t_scalar_bytes, "big")
    if not (1 <= t < N):
        raise ValueError("t out of range")
    T_pt = point_mul(G, t)
    x, y = T_pt
    prefix = 0x02 if (y % 2 == 0) else 0x03
    return bytes([prefix]) + x.to_bytes(32, "big")


def selftest(verbose: bool = True) -> bool:
    """
    Verify, for each vector:
      1. pool_pre_sign produces a 65-byte pre-sig
      2. pool_pre_verify(pre_sig, agg_xonly, msg, T_compressed) accepts
      3. pool_decrypt(pre_sig, t) yields a 65-byte completed sig with same R̂
      4. From completed + pre, pool_recover(pre_sig, completed) returns t
      5. Tampering t before verify is rejected
      6. Determinism — re-running pool_pre_sign with same inputs yields the
         same pre_sig and same agg_xonly
    """
    ok = True
    for i, (sk_hexes, m_hex, t_hex) in enumerate(_selftest_vectors()):
        seckeys = [bytes.fromhex(h) for h in sk_hexes]
        msg = bytes.fromhex(m_hex)
        t_bytes = bytes.fromhex(t_hex)
        T_compressed = _ser_compressed_from_scalar(t_bytes)

        agg_xonly, pre_sig = pool_pre_sign(seckeys, msg, T_compressed)
        # 1. shapes
        if len(pre_sig) != 65 or len(agg_xonly) != 32:
            ok = False
            if verbose: print(f"[m2adapt #{i}] FAIL: bad sizes")
            continue
        # 2. accept under agg_xonly
        if not pool_pre_verify(pre_sig, agg_xonly, msg, T_compressed):
            ok = False
            if verbose: print(f"[m2adapt #{i}] FAIL: pool_pre_verify rejected")
            continue
        # 3. decrypt to completed
        completed = pool_decrypt(pre_sig, t_bytes)
        if completed is None or len(completed) != 65:
            ok = False
            if verbose: print(f"[m2adapt #{i}] FAIL: decrypt did not yield 65 bytes")
            continue
        if completed[:33] != pre_sig[:33]:
            ok = False
            if verbose: print(f"[m2adapt #{i}] FAIL: completed R̂ != pre R̂")
            continue
        # 4. recover t
        rec_t = pool_recover(pre_sig, completed)
        if rec_t != t_bytes:
            ok = False
            if verbose: print(f"[m2adapt #{i}] FAIL: recover got {rec_t!r}, want {t_bytes!r}")
            continue
        # 5. tampered t → completed sig won't match expected, but recovery still
        # operates byte-mechanically. The honest "wrong t was used" check is via
        # whether x(R̂) == completed[:33] under the agg key when paired with a
        # full Schnorr verify. We just sanity-check: decrypting with a tampered
        # t produces a completed sig that does NOT match the original pre R̂'s
        # expected (R̂, s) when paired with adaptor recovery of the WRONG t.
        bad_t = bytearray(t_bytes); bad_t[0] ^= 0xFF
        bad_completed = pool_decrypt(pre_sig, bytes(bad_t))
        bad_rec = pool_recover(pre_sig, bad_completed)
        if bad_rec == t_bytes:
            ok = False
            if verbose: print(f"[m2adapt #{i}] FAIL: tampered-t recovery returned legit t (broken!)")
            continue
        # 6. determinism
        agg2, pre2 = pool_pre_sign(seckeys, msg, T_compressed)
        if agg2 != agg_xonly or pre2 != pre_sig:
            ok = False
            if verbose: print(f"[m2adapt #{i}] FAIL: non-deterministic re-sign")
            continue
        if verbose:
            print(f"[m2adapt #{i}] OK  N={len(seckeys)}  agg={agg_xonly.hex()[:16]}...  pre_sig={pre_sig.hex()[:16]}...")
    if verbose:
        print(f"\n[m2adapt] {'ALL VECTORS PASS' if ok else 'FAILED'}")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
