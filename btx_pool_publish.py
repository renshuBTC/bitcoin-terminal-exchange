#!/usr/bin/env python3
"""
btx_pool_publish.py — Bridge MuSig2 maker-pool signing to BTX2 envelope publish.

Closes the integration gap between:
  - the primitive  : `btx_musig2.pool_sign_trusted_aggregator` (Py + Rust)
  - the format     : BTX2 BATCH_ANNOUNCE record per spec §3.2

Demonstrates that "pool-signed orders" require ZERO protocol change to the
BTX2 envelope format:

  1. Pool runs `pool_sign_trusted_aggregator(seckeys, sighash)` →
     (agg_xonly, 64-byte BIP340 sig)
  2. The aggregated `agg_xonly` is used as that order's `maker_pubkey` field
     in the canonical order body (spec §3.4)
  3. The 64-byte sig from the pool is then half-aggregated alongside any
     other orders in the batch (a pool-signed order is indistinguishable
     from a single-signer order at the BTX2 layer)

Indexer-side: the existing `verify_batch_announce` accepts the BATCH_ANNOUNCE
payload exactly as it does for single-signer orders — it has no idea (and
needs no knowledge) that any of the maker pubkeys are MuSig2-aggregated.

This module ships:
  - `pool_order` dict schema (mirrors the single-signer order dict, but with
    `seckeys` list instead of `seckey` scalar)
  - `build_pool_batch_announce(pool_orders, mixed_orders=None)` — produces
    a BATCH_ANNOUNCE record where each entry is either pool-signed
    (multiple keys) or solo-signed (single key)
  - selftest with mixed batches that verify under
    btx_artifact_v2_demo.verify_batch_announce
"""

from __future__ import annotations
import struct

from btx_taproot import schnorr_sign, xonly_pubkey, tagged_hash
from btx_musig2 import pool_sign_demo as pool_sign_trusted_aggregator
from btx_halfagg import aggregate as halfagg_aggregate, verify as halfagg_verify
from btx_artifact_v2_demo import _order_body_sans_sig, verify_batch_announce


# Re-export for convenience.
__all__ = [
    "build_pool_batch_announce",
    "pool_sign_trusted_aggregator",
    "selftest",
]


def _resolve_order_to_sig(o):
    """
    Take an order dict and return (pubkey_xonly, body, sighash, sig).

    Order may be:
      - solo: has `seckey` (bytes)
      - pool: has `seckeys` (list of bytes)

    For pool orders, the `maker_pubkey` written into the body is the
    aggregated pubkey from `pool_sign_trusted_aggregator`.
    """
    if "seckey" in o and "seckeys" in o:
        raise ValueError("order has both seckey and seckeys; choose one")
    if "seckey" not in o and "seckeys" not in o:
        raise ValueError("order needs seckey (solo) or seckeys (pool)")

    if "seckeys" in o:
        # POOL path
        seckeys = list(o["seckeys"])
        if len(seckeys) < 2:
            # Single-element pool is structurally identical to solo
            raise ValueError("pool order needs ≥2 seckeys; for 1 key use seckey instead")

        # First we need to commit to the agg_xonly so the sighash bakes it in.
        # The pool aggregator does the KeyAgg twice (once here for agg_xonly,
        # once inside pool_sign_trusted_aggregator for the d_agg). Both produce
        # the same agg_xonly deterministically.
        from btx_musig2 import key_agg
        pubkeys = [xonly_pubkey(sk)[0] for sk in seckeys]
        agg = key_agg(pubkeys)
        agg_xonly = agg["agg_xonly"]

        body, sighash = _order_body_sans_sig(
            rune_block=o["rune_block"],
            rune_tx=o["rune_tx"],
            amount=o["amount"],
            price=o["price"],
            expiry=o["expiry"],
            offer_txid=o["offer_txid"],
            offer_vout=o["offer_vout"],
            payout_spk=o["payout_spk"],
            maker_pubkey_xonly=agg_xonly,
        )
        agg_xonly2, sig = pool_sign_trusted_aggregator(seckeys, sighash)
        assert agg_xonly == agg_xonly2, "internal: pool agg_xonly drifted"
        return agg_xonly, body, sighash, sig
    else:
        # SOLO path — same as btx_artifact_v2_demo's path
        sk = o["seckey"]
        pk_xonly, _ = xonly_pubkey(sk)
        body, sighash = _order_body_sans_sig(
            rune_block=o["rune_block"],
            rune_tx=o["rune_tx"],
            amount=o["amount"],
            price=o["price"],
            expiry=o["expiry"],
            offer_txid=o["offer_txid"],
            offer_vout=o["offer_vout"],
            payout_spk=o["payout_spk"],
            maker_pubkey_xonly=pk_xonly,
        )
        sig = schnorr_sign(sighash, sk)
        return pk_xonly, body, sighash, sig


def build_pool_batch_announce(orders):
    """
    Build a BATCH_ANNOUNCE record from a mixed list of solo + pool orders.

    Each order is the same shape as in btx_artifact_v2_demo.build_batch_announce
    EXCEPT that the maker can be a pool — pass `seckeys=[sk1, sk2, ...]`
    instead of `seckey=sk`.

    The resulting record is wire-format identical to a single-signer
    BATCH_ANNOUNCE per spec §3.2:
        N (u16 BE) || N × (BLEN u16 BE || BODY) || HALFAGG_SIG (32 × (N+1) B)

    Indexer verification (verify_batch_announce) treats pool orders exactly
    like single-signer orders.

    Returns (payload_bytes, halfagg_bytes).
    """
    if not orders:
        raise ValueError("batch needs ≥1 order")

    pubkeys, msgs, sigs = [], [], []
    bodies = b""
    for o in orders:
        pk_xonly, body, sighash, sig = _resolve_order_to_sig(o)
        bodies += struct.pack(">H", len(body)) + body
        pubkeys.append(pk_xonly)
        msgs.append(sighash)
        sigs.append(sig)

    halfagg = halfagg_aggregate(pubkeys, msgs, sigs)
    payload = struct.pack(">H", len(orders)) + bodies + halfagg
    return payload, halfagg


# ----------------------------- selftest -----------------------------


def _selftest_orders_v1():
    # 1 solo + 1 pool(N=2) — proves mixed-batch shape works
    return [
        {
            "seckey": bytes.fromhex(
                "b7e151628aed2a6abf7158809cf4f3c762e7160f38b4da56a784d9045190cfef"
            ),
            "rune_block": 840_000,
            "rune_tx": 1,
            "amount": 1000,
            "price": 1_000_000,
            "expiry": 850_000,
            "offer_txid": bytes(32),
            "offer_vout": 0,
            "payout_spk": b"\x00\x14" + b"\xC0" * 20,
        },
        {
            "seckeys": [
                bytes.fromhex(
                    "0000000000000000000000000000000000000000000000000000000000000003"
                ),
                bytes.fromhex(
                    "c90fdaa22168c234c4c6628b80dc1cd129024e088a67cc74020bbea63b14e5c9"
                ),
            ],
            "rune_block": 840_001,
            "rune_tx": 2,
            "amount": 2000,
            "price": 2_500_000,
            "expiry": 850_500,
            "offer_txid": bytes(range(32)),
            "offer_vout": 1,
            "payout_spk": b"\x00\x14" + b"\xB0" * 20,
        },
    ]


def _selftest_orders_v2():
    # All pool (N=3, N=5) — proves pool-only batches verify
    return [
        {
            "seckeys": [
                bytes.fromhex(
                    "0000000000000000000000000000000000000000000000000000000000000001"
                ),
                bytes.fromhex(
                    "0000000000000000000000000000000000000000000000000000000000000002"
                ),
                bytes.fromhex(
                    "0000000000000000000000000000000000000000000000000000000000000003"
                ),
            ],
            "rune_block": 850_000,
            "rune_tx": 0,
            "amount": 5000,
            "price": 1_500_000,
            "expiry": 860_000,
            "offer_txid": bytes(32),
            "offer_vout": 2,
            "payout_spk": b"\x00\x14" + b"\xA0" * 20,
        },
        {
            "seckeys": [
                bytes.fromhex(
                    "0b432b2677937381aef05bb02a66ecd012773062cf3fa2549e44f58ed2401710"
                ),
                bytes.fromhex(
                    "c90fdaa22168c234c4c6628b80dc1cd129024e088a67cc74020bbea63b14e5c9"
                ),
                bytes.fromhex(
                    "0000000000000000000000000000000000000000000000000000000000000007"
                ),
                bytes.fromhex(
                    "b7e151628aed2a6abf7158809cf4f3c762e7160f38b4da56a784d9045190cfef"
                ),
                bytes.fromhex(
                    "0000000000000000000000000000000000000000000000000000000000000005"
                ),
            ],
            "rune_block": 850_010,
            "rune_tx": 5,
            "amount": 10_000,
            "price": 3_000_000,
            "expiry": 861_000,
            "offer_txid": bytes(32),
            "offer_vout": 3,
            "payout_spk": b"\x00\x14" + b"\x90" * 20,
        },
    ]


def selftest(verbose: bool = True) -> bool:
    """
    Two integration tests:
      1. Mixed batch (1 solo + 1 pool N=2) — build, verify, byte-stable
      2. Pool-only batch (1 pool N=3 + 1 pool N=5) — build, verify
    Both checked against the upstream `verify_batch_announce`, proving the
    format is unchanged.
    """
    ok = True

    for label, batch in [("MIXED 1+1", _selftest_orders_v1()),
                          ("POOL-ONLY 3+5", _selftest_orders_v2())]:
        try:
            payload, halfagg = build_pool_batch_announce(batch)
        except Exception as e:
            ok = False
            if verbose: print(f"[pool-publish {label}] FAIL build: {e}")
            continue

        # Verify via the upstream verifier (proves format compatibility)
        is_ok, msg = verify_batch_announce(payload)
        if not is_ok:
            ok = False
            if verbose: print(f"[pool-publish {label}] FAIL verify: {msg}")
            continue

        # Sanity: halfagg size = 32(N+1)
        if len(halfagg) != 32 * (len(batch) + 1):
            ok = False
            if verbose: print(f"[pool-publish {label}] FAIL halfagg size {len(halfagg)}")
            continue

        # Determinism: rebuild produces the same payload
        payload2, _ = build_pool_batch_announce(batch)
        if payload != payload2:
            ok = False
            if verbose: print(f"[pool-publish {label}] FAIL non-deterministic rebuild")
            continue

        if verbose:
            print(f"[pool-publish {label}] OK  payload={len(payload)}B  halfagg={len(halfagg)}B  N={len(batch)}")
            print(f"    upstream verify_batch_announce → {msg}")

    if verbose:
        print(f"\n[pool-publish] {'ALL PASS' if ok else 'FAILED'}")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
