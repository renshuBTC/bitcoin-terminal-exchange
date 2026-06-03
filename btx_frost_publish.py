#!/usr/bin/env python3
"""
btx_frost_publish.py — Bridge FROST t-of-n signing to BTX2 BATCH_ANNOUNCE.

Strictly upgrades btx_pool_publish.py (which only supports n-of-n) to
also accept t-of-n FROST-signed orders. Same zero-protocol-change
property: the indexer treats a FROST order identically to a single-signer
order — only the maker's *off-chain* signing path changes.

## Order schema additions

A FROST order is the same dict shape as the solo and pool orders in
btx_pool_publish, but with these keys instead of `seckey` or `seckeys`:

    "frost": FrostKey            # the keygen-trusted-dealer output
    "signer_indices": [int]      # which t of the n shares co-sign

Mixed batches are supported: solo + pool + FROST orders in any
combination. Indexer-side verification is unchanged — it runs the
existing `verify_batch_announce` from btx_artifact_v2_demo.

## Threat model

Trusted-aggregator FROST signing: the aggregator must hold ALL the
share secrets it intends to use at sign time. Same security boundary
as btx_musig2.pool_sign_demo / btx_pool_publish for n-of-n. The
upgrade from MuSig2-pool to FROST-pool is *quorum flexibility*, not
trust reduction — for mutually distrusting parties you still need
the interactive nonce-exchange flow and ChillDKG keygen.
"""

from __future__ import annotations
import struct

from btx_taproot import schnorr_sign, xonly_pubkey
from btx_musig2 import pool_sign_demo
from btx_halfagg import aggregate as halfagg_aggregate
from btx_artifact_v2_demo import _order_body_sans_sig, verify_batch_announce
from btx_frost import FrostKey, threshold_sign


def _resolve_order(o):
    """
    Take an order dict and return (pubkey_xonly, body, sighash, sig).

    Order may be:
      - solo : `seckey` (bytes)
      - pool : `seckeys` (list of bytes)
      - frost: `frost` (FrostKey) + `signer_indices` (list of int)
    """
    has_solo = "seckey" in o
    has_pool = "seckeys" in o
    has_frost = "frost" in o
    if sum([has_solo, has_pool, has_frost]) != 1:
        raise ValueError(
            "order needs exactly one of: seckey (solo), seckeys (pool), frost+signer_indices"
        )

    if has_frost:
        frost: FrostKey = o["frost"]
        indices = o["signer_indices"]
        # The body's maker_pubkey is the FROST group x-only.
        body, sighash = _order_body_sans_sig(
            rune_block=o["rune_block"],
            rune_tx=o["rune_tx"],
            amount=o["amount"],
            price=o["price"],
            expiry=o["expiry"],
            offer_txid=o["offer_txid"],
            offer_vout=o["offer_vout"],
            payout_spk=o["payout_spk"],
            maker_pubkey_xonly=frost.group_xonly,
        )
        sig = threshold_sign(frost, indices, sighash)
        return frost.group_xonly, body, sighash, sig

    if has_pool:
        seckeys = list(o["seckeys"])
        if len(seckeys) < 2:
            raise ValueError("pool order needs ≥2 seckeys")
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
        agg_xonly2, sig = pool_sign_demo(seckeys, sighash)
        assert agg_xonly == agg_xonly2
        return agg_xonly, body, sighash, sig

    # solo
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


def build_frost_batch_announce(orders):
    """
    Build a BATCH_ANNOUNCE record from a mixed list of solo / pool / FROST
    orders.

    The resulting record is wire-format identical to a single-signer
    BATCH_ANNOUNCE per BTX2 spec §3.2.

    Returns (payload_bytes, halfagg_bytes).
    """
    if not orders:
        raise ValueError("batch needs ≥1 order")

    pubkeys, msgs, sigs = [], [], []
    bodies = b""
    for o in orders:
        pk_xonly, body, sighash, sig = _resolve_order(o)
        bodies += struct.pack(">H", len(body)) + body
        pubkeys.append(pk_xonly)
        msgs.append(sighash)
        sigs.append(sig)

    halfagg = halfagg_aggregate(pubkeys, msgs, sigs)
    payload = struct.pack(">H", len(orders)) + bodies + halfagg
    return payload, halfagg


# ----------------------------- selftest -----------------------------


def _make_frost_order(t, n, seed_hex, signer_indices, rune_tx, amount):
    """Helper: keygen + assemble a FROST order dict."""
    from btx_frost import keygen_trusted_dealer
    seed = bytes.fromhex(seed_hex.ljust(64, "0"))[:32]
    fk = keygen_trusted_dealer(t, n, seed=seed)
    return {
        "frost": fk,
        "signer_indices": signer_indices,
        "rune_block": 840_000,
        "rune_tx": rune_tx,
        "amount": amount,
        "price": 1_500_000,
        "expiry": 850_000,
        "offer_txid": bytes.fromhex("11" * 32),
        "offer_vout": rune_tx,
        "payout_spk": b"\x00\x14" + b"\xA0" * 20,
    }


def selftest(verbose: bool = True) -> bool:
    """
    Three integration tests:
      1. All-FROST batch  (2-of-3 + 3-of-5 + 4-of-7)
      2. Mixed batch      (solo + pool + FROST 2-of-3)
      3. Single FROST     (1-of-1 — degenerate, proves wiring works)
    Each batch is verified against the upstream verify_batch_announce,
    proving zero protocol change.
    """
    ok = True

    # Test 1: all FROST
    batch1 = [
        _make_frost_order(2, 3, "aa", [1, 2], rune_tx=1, amount=1000),
        _make_frost_order(3, 5, "bb", [1, 3, 5], rune_tx=2, amount=2000),
        _make_frost_order(4, 7, "cc", [2, 4, 5, 7], rune_tx=3, amount=3000),
    ]
    try:
        payload, halfagg = build_frost_batch_announce(batch1)
        is_ok, msg = verify_batch_announce(payload)
        if not is_ok:
            ok = False
            if verbose: print(f"[frost-publish ALL-FROST] FAIL: {msg}")
        elif verbose:
            print(f"[frost-publish ALL-FROST] OK  N=3  payload={len(payload)}B  halfagg={len(halfagg)}B")
            print(f"    upstream verify → {msg}")
    except Exception as e:
        ok = False
        if verbose: print(f"[frost-publish ALL-FROST] FAIL exc: {e}")

    # Test 2: mixed (solo + pool + FROST)
    batch2 = [
        {
            "seckey": bytes.fromhex(
                "b7e151628aed2a6abf7158809cf4f3c762e7160f38b4da56a784d9045190cfef"
            ),
            "rune_block": 840_010, "rune_tx": 10, "amount": 500,
            "price": 1_000_000, "expiry": 850_000,
            "offer_txid": bytes.fromhex("22" * 32),
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
            "rune_block": 840_011, "rune_tx": 11, "amount": 1500,
            "price": 2_000_000, "expiry": 850_500,
            "offer_txid": bytes(range(32)),
            "offer_vout": 1,
            "payout_spk": b"\x00\x14" + b"\xB0" * 20,
        },
        _make_frost_order(2, 3, "dd", [1, 3], rune_tx=12, amount=2500),
    ]
    try:
        payload, halfagg = build_frost_batch_announce(batch2)
        is_ok, msg = verify_batch_announce(payload)
        if not is_ok:
            ok = False
            if verbose: print(f"[frost-publish MIXED] FAIL: {msg}")
        elif verbose:
            print(f"[frost-publish MIXED] OK  N=3 (solo+pool+frost)  payload={len(payload)}B  "
                  f"halfagg={len(halfagg)}B")
            print(f"    upstream verify → {msg}")
    except Exception as e:
        ok = False
        if verbose: print(f"[frost-publish MIXED] FAIL exc: {e}")

    # Test 3: degenerate 1-of-1 FROST (proves wiring)
    batch3 = [_make_frost_order(1, 1, "ee", [1], rune_tx=20, amount=4000)]
    try:
        payload, halfagg = build_frost_batch_announce(batch3)
        is_ok, msg = verify_batch_announce(payload)
        if not is_ok:
            ok = False
            if verbose: print(f"[frost-publish 1-of-1] FAIL: {msg}")
        elif verbose:
            print(f"[frost-publish 1-of-1] OK  payload={len(payload)}B  halfagg={len(halfagg)}B")
            print(f"    upstream verify → {msg}")
    except Exception as e:
        ok = False
        if verbose: print(f"[frost-publish 1-of-1] FAIL exc: {e}")

    if verbose:
        print(f"\n[frost-publish] {'ALL PASS' if ok else 'FAILED'}")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
