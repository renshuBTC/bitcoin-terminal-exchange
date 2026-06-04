#!/usr/bin/env python3
"""
btx_musig2_bip327_protocol — thin wrapper around BIP-327's reference.py
exposing the multi-round MuSig2 protocol functions BTX needs for
external interop:

  - `nonce_gen_internal` — deterministic nonce generation
  - `nonce_gen`          — non-deterministic wrapper around the above
  - `nonce_agg`          — aggregate per-signer pub-nonces

Why a wrapper rather than a port
--------------------------------

BTX's existing `btx_musig2.pool_sign_demo` is a trusted-aggregator
shortcut (single entity holds all secret keys, signs with vanilla
BIP-340 over `d_agg`). That's correct for BTX2 maker pools today
where one maker controls all sub-keys.

For the multi-party non-interactive MuSig2 protocol (multiple parties
each holding their own secret), BTX would need separate
nonce_gen → nonce_agg → partial_sign → partial_sig_agg stages. The
BIP-327 reference.py already implements this carefully. Wrapping it
gives BTX immediate access while letting the reference's
maintainers (Jonas Nick, Tim Ruffing, Elliott Jin) own correctness.

When BTX needs to ship its own from-scratch implementation (e.g.,
for the brk-btx indexer to verify partial signatures without a
Python runtime), the wrapper API surface here defines exactly what
the from-scratch implementation must match byte-for-byte.

Cross-validation
----------------

`btx_xtest_vs_bip327_nonces.py` runs the wrapped functions against
the canonical `nonce_gen_vectors.json` + `nonce_agg_vectors.json`.
All expected outputs match.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple


def _find_bip327_reference() -> str | None:
    candidates = [
        os.path.expanduser(
            "~/Documents/Claude/Projects/Bitcoin CoreX/"
            "bitcoin-bips-reference/bip-0327"
        ),
        "/mnt/c/Users/Ren Shu/Documents/Claude/Projects/Bitcoin CoreX/"
        "bitcoin-bips-reference/bip-0327",
        "/sessions/keen-determined-einstein/mnt/Bitcoin CoreX/"
        "bitcoin-bips-reference/bip-0327",
    ]
    for c in candidates:
        if os.path.isfile(os.path.join(c, "reference.py")):
            return c
    return None


_REF_DIR = _find_bip327_reference()
if _REF_DIR is None:
    raise ImportError(
        "BIP-327 reference.py not found. Clone bitcoin/bips to "
        "Bitcoin CoreX/bitcoin-bips-reference/ to enable BTX's "
        "multi-round MuSig2 protocol API."
    )
sys.path.insert(0, _REF_DIR)
import reference as _bip327  # type: ignore


# ----------------------------- public API ------------------------------


def nonce_gen_internal(
    rand_: bytes,
    sk: Optional[bytes],
    pk: bytes,
    aggpk: Optional[bytes],
    msg: Optional[bytes],
    extra_in: Optional[bytes],
) -> Tuple[bytearray, bytes]:
    """Deterministic MuSig2 nonce generation per BIP-327.

    Returns `(secnonce, pubnonce)` where:
      - secnonce = `k_1` (32) || `k_2` (32) || `pk` (33), 97 bytes
      - pubnonce = compressed(k_1·G) (33) || compressed(k_2·G) (33),
        66 bytes

    Inputs:
      - rand_:   32-byte randomness (deterministic in this function)
      - sk:      optional 32-byte secret key (if None, k is derived
                 from rand_ alone — insecure if rand_ is predictable)
      - pk:      33-byte compressed pubkey
      - aggpk:   optional 32-byte aggregate xonly pubkey
      - msg:     optional message bytes
      - extra_in: optional additional context bytes
    """
    return _bip327.nonce_gen_internal(rand_, sk, pk, aggpk, msg, extra_in)


def nonce_gen(
    sk: Optional[bytes],
    pk: bytes,
    aggpk: Optional[bytes],
    msg: Optional[bytes],
    extra_in: Optional[bytes],
) -> Tuple[bytearray, bytes]:
    """Non-deterministic nonce generation — calls nonce_gen_internal
    with rand_ = secrets.token_bytes(32). USE THIS in production
    unless you have a specific reason to control rand_ (e.g.,
    cross-test against canonical vectors)."""
    return _bip327.nonce_gen(sk, pk, aggpk, msg, extra_in)


def nonce_agg(pubnonces: List[bytes]) -> bytes:
    """Aggregate per-signer pubnonces into the session aggregate
    nonce. Returns 66 bytes (two 33-byte compressed-or-infinity
    points). Raises `InvalidContributionError` on a malformed
    pubnonce; that's the standard MuSig2 disqualification signal."""
    return _bip327.nonce_agg(pubnonces)


# --------------------------- session signing ---------------------------


def session_context(aggnonce, pubkeys, tweaks, is_xonly, msg):
    """Construct SessionContext for sign/partial_sig_verify/partial_sig_agg.
    aggnonce: 66-byte nonce_agg output. pubkeys: list of 33-byte compressed
    pubkeys. tweaks/is_xonly: pass [] for no tweaks. msg: signed message bytes."""
    return _bip327.SessionContext(aggnonce, pubkeys, tweaks, is_xonly, msg)


def sign(secnonce, sk, session_ctx):
    """Produce 32-byte partial signature. secnonce is wiped after to prevent reuse."""
    return _bip327.sign(secnonce, sk, session_ctx)


def partial_sig_verify(psig, pubnonces, pubkeys, tweaks, is_xonly, msg, i):
    """Verify partial signature from signer index `i`. Returns True/False."""
    return _bip327.partial_sig_verify(psig, pubnonces, pubkeys, tweaks, is_xonly, msg, i)


def partial_sig_agg(psigs, session_ctx):
    """Combine partials into final 64-byte BIP-340 signature."""
    return _bip327.partial_sig_agg(psigs, session_ctx)


# Re-export the exception type
InvalidContributionError = _bip327.InvalidContributionError


__all__ = [
    "nonce_gen_internal", "nonce_gen", "nonce_agg",
    "session_context", "sign", "partial_sig_verify", "partial_sig_agg",
    "InvalidContributionError",
]


def deterministic_sign(sk, aggothernonce, pubkeys, tweaks, is_xonly, msg, rand=None):
    """Deterministic single-signer signing path (BIP-327 §Det. Signing).

    Used when a signer wants signing to be reproducible from inputs alone
    (no need to persist a per-session secret nonce). The signer picks an
    `aggothernonce` from the coordinator, optional `rand`, and produces
    (pubnonce, psig) atomically."""
    return _bip327.deterministic_sign(
        sk, aggothernonce, pubkeys, tweaks, is_xonly, msg, rand
    )


__all__ = __all__ + ["deterministic_sign"]
