#!/usr/bin/env python3
"""
btx_dlc_publish.py — DLC primitives wired into real BTX2 CONDITIONAL_ORDER records.

Closes the integration gap between:
  - the primitives    : `btx_dlc_demo.Oracle` (publish Po, Ro, attest)
                       `btx_adaptor.pre_sign`/`pre_verify`/`decrypt`/`recover`
  - the on-chain format: BTX2 CONDITIONAL_ORDER record per spec §3.3
                       (`btx_artifact_v2_demo.build_conditional_order`)

The DLC flow (oracle attests outcome → adaptor decrypt → swap settles) was
already proven end-to-end in `btx_dlc_demo.py` using on-curve math only —
no on-chain interaction. This module is the bridge: it produces a *real*
CONDITIONAL_ORDER record whose embedded adaptor pre-sig is keyed to a
real oracle's attestation point, then verifies the round-trip:

    Stage A  oracle setup: publish (Po, Ro, event_id)
    Stage B  maker builds CONDITIONAL_ORDER with T = Ro + H(event||outcome)·Po
    Stage C  indexer verifies record via verify_conditional_order
    Stage D  oracle attests outcome → s_o
    Stage E  anyone decrypts adaptor_sig with s_o → completed BIP340 sig
    Stage F  completed sig verifies under maker_pubkey at the BTX2 sighash
              (the order can settle on-chain)
    Stage G  wrong-outcome attestation → completed sig fails BIP340 verify
              (the order cannot maliciously settle)

The CONDITIONAL_ORDER record format itself is unchanged — the existing
BTX2 indexer (verify_conditional in brk-btx) accepts the produced record
as-is. The DLC binding is *cryptographically external* to the BTX2 layer:
it lives in how `T` is derived. That's what makes this clean — the BTX2
format doesn't need to know about oracles at all.

## Integration value

Before this module:
  - btx_dlc_demo.py proved the math works in abstract
  - btx_artifact_v2_demo.build_conditional_order accepted any `T_point`
  - No wiring between them — a CONDITIONAL_ORDER's T was opaque

After this module:
  - btx_dlc_publish.build_oracle_conditional_order produces a CONDITIONAL_ORDER
    whose T is bound to a specific (oracle_pubkey, event_id, outcome) triple
  - The corresponding attestation scalar from the oracle is exactly the
    secret `t` needed to decrypt the adaptor sig
  - The completed sig is a valid BIP340 sig under the maker's pubkey, which
    means it can settle the order via the existing on-chain swap path
"""

from __future__ import annotations

from btx_taproot import schnorr_verify, xonly_pubkey, N
from btx_adaptor import decrypt as adaptor_decrypt
from btx_artifact_v2_demo import (
    build_conditional_order,
    verify_conditional_order,
)
from btx_dlc_demo import Oracle, maker_derive_T


# ----------------------------- public API -----------------------------


def build_oracle_conditional_order(order, oracle: Oracle, event_id: bytes,
                                    outcome: bytes):
    """
    Build a CONDITIONAL_ORDER record where the encryption point T is the
    oracle's DLC attestation point for the (event_id, outcome) pair.

    Args:
        order:   dict with the same keys as `btx_artifact_v2_demo.build_conditional_order`
                 (seckey, rune_block, rune_tx, amount, price, expiry,
                  offer_txid, offer_vout, payout_spk)
        oracle:  an Oracle instance (publishes Po, Ro)
        event_id: identifier for the event the oracle will attest (any bytes)
        outcome: the outcome the maker is committing to (any bytes)

    Returns:
        (payload_bytes, T_compressed, attestation_point_bytes)

        payload_bytes:   wire-format CONDITIONAL_ORDER record
        T_compressed:    33-byte compressed encryption point
        attestation_point_bytes:  same as T_compressed (alias for clarity)
    """
    # The taker (and anyone with Po, Ro, event_id, outcome) can derive T
    # independently — this is the DLC binding contract.
    T_compressed = maker_derive_T(
        oracle.Po_xonly, oracle.Ro_compressed, event_id, outcome,
    )
    # build_conditional_order's _ser_compressed expects a point tuple, so
    # we parse the compressed bytes back into a point. (btx_adaptor.pre_sign
    # downstream accepts either form, but the demo's serialiser is strict.)
    from btx_adaptor import _parse_compressed
    T_point = _parse_compressed(T_compressed)
    payload = build_conditional_order(order, T_point)
    return payload, T_compressed, T_compressed


def completed_sig_from_adaptor(adaptor_pre_sig: bytes, s_o: bytes) -> bytes:
    """
    Given the adaptor pre-sig from a CONDITIONAL_ORDER record and the oracle's
    attestation scalar s_o, produce the completed BIP340 Schnorr signature
    that settles the swap.

    The adaptor pre-sig is 65 bytes: compressed(R_hat) || s_a.
    decrypt() returns 65 bytes: compressed(R_hat) || s.
    For BIP340 verification, we need (x(R_hat), s_bip340) where s_bip340 is
    s if R_hat has even y, or N-s if R_hat has odd y.
    """
    completed = adaptor_decrypt(adaptor_pre_sig, s_o)
    if completed is None or len(completed) != 65:
        raise ValueError("adaptor decrypt did not produce 65 bytes")
    R_hat_compressed = completed[:33]
    s_bytes = completed[33:]
    R_hat_x = R_hat_compressed[1:]
    if R_hat_compressed[0] == 0x03:
        s_int = int.from_bytes(s_bytes, "big")
        s_norm = (N - s_int) % N
        return R_hat_x + s_norm.to_bytes(32, "big")
    return R_hat_x + s_bytes


def extract_adaptor_sig(payload: bytes) -> bytes:
    """Return the 65-byte adaptor pre-sig embedded in a CONDITIONAL_ORDER payload."""
    if len(payload) < 2 + 33 + 65:
        raise ValueError("payload too short")
    import struct
    blen = struct.unpack(">H", payload[:2])[0]
    o = 2 + blen + 33
    return payload[o:o + 65]


def extract_sighash(payload: bytes) -> bytes:
    """Compute the BTX2 sighash from a CONDITIONAL_ORDER payload's body."""
    from btx_taproot import tagged_hash
    import struct
    blen = struct.unpack(">H", payload[:2])[0]
    body = payload[2:2 + blen]
    return tagged_hash("BTX2/order/sighash", body)


def extract_maker_pubkey(payload: bytes) -> bytes:
    """Return the 32-byte x-only maker pubkey from a CONDITIONAL_ORDER body."""
    import struct
    blen = struct.unpack(">H", payload[:2])[0]
    body = payload[2:2 + blen]
    return body[-32:]


# ----------------------------- selftest -----------------------------


def _make_order(seckey_hex, expiry=860_000):
    return {
        "seckey": bytes.fromhex(seckey_hex),
        "rune_block": 840_000,
        "rune_tx": 7,
        "amount": 1500,
        "price": 1_750_000,
        "expiry": expiry,
        "offer_txid": bytes.fromhex(
            "11" * 32
        ),
        "offer_vout": 0,
        "payout_spk": b"\x00\x14" + b"\xC0" * 20,
    }


def selftest(verbose: bool = True) -> bool:
    """
    End-to-end DLC → BTX2 CONDITIONAL_ORDER → settle flow.

    Stages match the module docstring; each stage adds an integration
    assertion the abstract demo couldn't make.
    """
    ok = True

    # Stage A: oracle setup
    oracle = Oracle(
        secret_key=bytes.fromhex(
            "0b432b2677937381aef05bb02a66ecd012773062cf3fa2549e44f58ed2401710"
        ),
        nonce_secret=bytes.fromhex(
            "c90fdaa22168c234c4c6628b80dc1cd129024e088a67cc74020bbea63b14e5c9"
        ),
    )
    event_id = b"BTX2-DLC-PUB-2026-06-03-BTC-PRICE-Q3"
    outcome_yes = b"BTC>60K"
    outcome_no = b"BTC<=60K"

    if verbose:
        print(f"[A] oracle Po={oracle.Po_xonly.hex()[:16]}...  Ro={oracle.Ro_compressed.hex()[:16]}...")

    # Stage B: maker builds a CONDITIONAL_ORDER with DLC-derived T
    order = _make_order(
        "b7e151628aed2a6abf7158809cf4f3c762e7160f38b4da56a784d9045190cfef"
    )
    maker_xonly = xonly_pubkey(order["seckey"])[0]
    payload, T_compressed, _ = build_oracle_conditional_order(
        order, oracle, event_id, outcome_yes
    )
    if verbose:
        print(f"[B] CONDITIONAL_ORDER record built: {len(payload)}B  T={T_compressed.hex()[:16]}...")

    # Stage C: the existing BTX2 verifier accepts the record
    is_ok, msg = verify_conditional_order(payload)
    if not is_ok:
        ok = False
        if verbose: print(f"[C] FAIL: upstream verify_conditional_order rejected: {msg}")
        return False
    if verbose: print(f"[C] upstream verify_conditional_order → {msg}")

    # Stage D: oracle attests "yes" → publishes s_o
    s_o = oracle.attest(event_id, outcome_yes)
    if verbose: print(f"[D] oracle attestation s_o = {s_o.hex()[:16]}...")

    # Stage E: decrypt adaptor sig → completed sig
    adaptor_sig = extract_adaptor_sig(payload)
    sig_bip340 = completed_sig_from_adaptor(adaptor_sig, s_o)
    if verbose: print(f"[E] completed BIP340 sig = {sig_bip340.hex()[:16]}...")

    # Stage F: completed sig verifies under maker pubkey at BTX2 sighash
    sighash = extract_sighash(payload)
    pubkey = extract_maker_pubkey(payload)
    if pubkey != maker_xonly:
        ok = False
        if verbose: print(f"[F] FAIL: maker pubkey in body != input order's xonly")
        return False
    if not schnorr_verify(sighash, pubkey, sig_bip340):
        ok = False
        if verbose: print(f"[F] FAIL: completed sig fails BIP340 verify at BTX2 sighash")
        return False
    if verbose: print(f"[F] schnorr_verify(sighash, maker_xonly, completed) → OK (order can settle)")

    # Stage G: wrong-outcome attestation must NOT produce a settling sig
    s_o_no = oracle.attest(event_id, outcome_no)
    sig_bip340_no = completed_sig_from_adaptor(adaptor_sig, s_o_no)
    if schnorr_verify(sighash, pubkey, sig_bip340_no):
        ok = False
        if verbose: print(f"[G] FAIL: wrong-outcome attestation produced a valid settling sig (broken!)")
        return False
    if verbose: print(f"[G] wrong-outcome attestation fails BIP340 verify (anti-MEV holds)")

    # Bonus: determinism — rebuild produces byte-identical payload
    payload2, _, _ = build_oracle_conditional_order(order, oracle, event_id, outcome_yes)
    if payload != payload2:
        ok = False
        if verbose: print(f"[bonus] FAIL: rebuild not deterministic")
        return False
    if verbose: print(f"[bonus] rebuild deterministic: payload bytes match")

    if verbose:
        print(f"\n[dlc-publish] {'ALL STAGES PASS — DLC ↔ BTX2 CONDITIONAL_ORDER wired end-to-end.' if ok else 'FAILED'}")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
