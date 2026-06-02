#!/usr/bin/env python3
"""
btx_artifact_v2_demo.py — BTX2 envelope prototype integrating the
half-aggregation and adaptor-signature primitives from btx_halfagg.py
and btx_adaptor.py.

This is a *research demo*, not a production format. It exists to:

  1. Show the two new primitives (half-agg, adaptor sigs) integrate
     cleanly into a candidate BTX2 envelope shape — no contortions
     needed.
  2. Measure realistic byte savings on a representative N-maker
     batch-announce scenario (today: N independent BTX1 envelopes,
     each ~207B; BTX2 batch: one envelope with one half-aggregate).
  3. Establish the dispatch + record-typing pattern any production
     BTX2 spec will need.

The actual BTX2 format spec is out of scope for this file (it needs
a designed migration path from BTX1, indexer-side cross-validation,
and a published spec). What this file gives the BTX2 designer is
concrete evidence the building blocks compose.

Envelope shape used here:

  ┌─────────┬──────────┬───────────────┬──────────────────────┐
  │ MAGIC=B │ VERSION  │ RECORD_COUNT  │ RECORDS              │
  │ T X 2   │ (u8 = 2) │ (u16 BE)      │ TYPE | LEN | PAYLOAD │
  │ 4 bytes │ 1 byte   │ 2 bytes       │ 1+2+LEN per record   │
  └─────────┴──────────┴───────────────┴──────────────────────┘

Record types implemented here:

  0x01 SINGLE_ORDER       — opaque BTX1-compatible body (passes through
                            an existing BTX1 artifact unchanged).
  0x02 BATCH_ANNOUNCE     — N maker orders sharing one half-aggregate
                            signature. Each order body is sans-sig
                            (everything else as BTX1). The aggregate
                            covers each (maker_pubkey_i, sighash_i).
  0x03 CONDITIONAL_ORDER  — one order body + 33B encryption point T +
                            65B Schnorr adaptor pre-sig. Decryptable
                            when an oracle attests t such that T = t·G.

The demo selftest constructs realistic-looking record bodies,
roundtrips them, verifies the cryptographic invariants on the
embedded half-aggregate / adaptor sigs, and reports byte counts.
"""

import os, json, struct
from btx_taproot import (
    N, G,
    point_mul, lift_x,
    tagged_hash, schnorr_sign, xonly_pubkey,
)
from btx_halfagg import aggregate as halfagg_aggregate, verify as halfagg_verify
from btx_adaptor import (
    pre_sign as adaptor_pre_sign,
    pre_verify as adaptor_pre_verify,
    decrypt as adaptor_decrypt,
    verify_completed as adaptor_verify_completed,
)


MAGIC = b"BTX2"
VERSION = 2

REC_SINGLE_ORDER = 0x01
REC_BATCH_ANNOUNCE = 0x02
REC_CONDITIONAL_ORDER = 0x03


# ----------------------------- envelope codec -----------------------------


def serialize_envelope(records):
    """Encode an envelope: MAGIC || VERSION || COUNT || records[]"""
    if len(records) > 0xFFFF:
        raise ValueError("too many records (max 65535 per envelope)")
    out = MAGIC + bytes([VERSION]) + struct.pack(">H", len(records))
    for rec_type, payload in records:
        if rec_type not in (REC_SINGLE_ORDER, REC_BATCH_ANNOUNCE, REC_CONDITIONAL_ORDER):
            raise ValueError(f"unknown record type {rec_type:#x}")
        if len(payload) > 0xFFFF:
            raise ValueError(f"record payload exceeds 65535 bytes: {len(payload)}")
        out += bytes([rec_type]) + struct.pack(">H", len(payload)) + payload
    return out


def parse_envelope(buf):
    """Decode an envelope. Returns (version, list_of_(type, payload))."""
    buf = bytes(buf)
    if len(buf) < 7 or buf[:4] != MAGIC:
        raise ValueError("not a BTX2 envelope")
    version = buf[4]
    count = struct.unpack(">H", buf[5:7])[0]
    o = 7
    out = []
    for _ in range(count):
        if o + 3 > len(buf):
            raise ValueError("truncated record header")
        rec_type = buf[o]; o += 1
        plen = struct.unpack(">H", buf[o:o+2])[0]; o += 2
        if o + plen > len(buf):
            raise ValueError("truncated record payload")
        out.append((rec_type, buf[o:o+plen]))
        o += plen
    if o != len(buf):
        raise ValueError(f"trailing bytes: parsed {o}, total {len(buf)}")
    return version, out


# ----------------------------- record builders -----------------------------


def _order_body_sans_sig(*, rune_block, rune_tx, amount, price, expiry,
                         offer_txid, offer_vout, payout_spk, maker_pubkey_xonly):
    """
    Encode the BTX2-canonical order body sans signature.
    Matches BTX1 field-for-field except maker_pubkey is 32B x-only (Schnorr
    convention), not a 33B compressed ECDSA pubkey.

    Returns the body bytes + the 32B sighash that the maker would sign.
    """
    if len(offer_txid) != 32 or len(maker_pubkey_xonly) != 32:
        raise ValueError("offer_txid and maker_pubkey_xonly must be 32B")
    body = struct.pack(">IH", rune_block, rune_tx)
    body += struct.pack(">QQ", amount, price)
    body += struct.pack(">I", expiry)
    body += offer_txid
    body += struct.pack(">I", offer_vout)
    body += struct.pack(">H", len(payout_spk)) + bytes(payout_spk)
    body += maker_pubkey_xonly

    # Sighash for this order body — the message the maker signs.
    sighash = tagged_hash("BTX2/order/sighash", body)
    return body, sighash


def build_batch_announce(orders):
    """
    Build a BATCH_ANNOUNCE record from a list of order dicts. Each dict has:
      seckey, rune_block, rune_tx, amount, price, expiry, offer_txid,
      offer_vout, payout_spk.

    Produces: COUNT(2B) || (body || ...) repeated N times || halfagg_sig
    """
    if not orders:
        raise ValueError("batch needs ≥1 order")

    pubkeys, msgs, sigs = [], [], []
    bodies = b""
    for o in orders:
        pk_xonly, _ = xonly_pubkey(o["seckey"])
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
        sig = schnorr_sign(sighash, o["seckey"])
        bodies += struct.pack(">H", len(body)) + body
        pubkeys.append(pk_xonly)
        msgs.append(sighash)
        sigs.append(sig)

    halfagg = halfagg_aggregate(pubkeys, msgs, sigs)

    payload = struct.pack(">H", len(orders)) + bodies + halfagg
    return payload, halfagg


def verify_batch_announce(payload):
    """Re-parse the batch record and verify the embedded half-aggregate."""
    if len(payload) < 2:
        return False, "no count"
    n = struct.unpack(">H", payload[:2])[0]
    o = 2
    pubkeys, msgs = [], []
    for _ in range(n):
        if o + 2 > len(payload):
            return False, "truncated body length"
        blen = struct.unpack(">H", payload[o:o+2])[0]; o += 2
        if o + blen > len(payload):
            return False, "truncated body"
        body = payload[o:o+blen]; o += blen
        sighash = tagged_hash("BTX2/order/sighash", body)
        # The maker_pubkey_xonly is the trailing 32B of the body.
        pubkeys.append(body[-32:])
        msgs.append(sighash)
    halfagg = payload[o:]
    expected_len = 32 * (n + 1)
    if len(halfagg) != expected_len:
        return False, f"aggsig wrong length: {len(halfagg)} != {expected_len}"
    if not halfagg_verify(pubkeys, msgs, halfagg):
        return False, "halfagg verify failed"
    return True, f"verified N={n} orders, halfagg {len(halfagg)}B"


def build_conditional_order(order, T_point):
    """
    Build a CONDITIONAL_ORDER record: order_body || T(33B) || adaptor_sig(65B).

    `T_point` is the encryption point (e.g., an oracle's attestation point Y
    such that the oracle will reveal y = t when they attest the outcome).
    """
    from btx_adaptor import _ser_compressed  # safe — internal helper
    pk_xonly, _ = xonly_pubkey(order["seckey"])
    body, sighash = _order_body_sans_sig(
        rune_block=order["rune_block"],
        rune_tx=order["rune_tx"],
        amount=order["amount"],
        price=order["price"],
        expiry=order["expiry"],
        offer_txid=order["offer_txid"],
        offer_vout=order["offer_vout"],
        payout_spk=order["payout_spk"],
        maker_pubkey_xonly=pk_xonly,
    )
    T_bytes = _ser_compressed(T_point)
    adaptor = adaptor_pre_sign(order["seckey"], sighash, T_point)
    payload = struct.pack(">H", len(body)) + body + T_bytes + adaptor
    return payload


def verify_conditional_order(payload):
    """Parse a conditional record and verify the adaptor pre-sig."""
    if len(payload) < 2 + 33 + 65:
        return False, "too short"
    blen = struct.unpack(">H", payload[:2])[0]
    o = 2
    body = payload[o:o+blen]; o += blen
    if o + 33 + 65 != len(payload):
        return False, "wrong trailing length"
    T_bytes = payload[o:o+33]; o += 33
    adaptor = payload[o:o+65]
    sighash = tagged_hash("BTX2/order/sighash", body)
    pubkey_xonly = body[-32:]
    if not adaptor_pre_verify(adaptor, pubkey_xonly, sighash, T_bytes):
        return False, "adaptor pre_verify failed"
    return True, "verified"


# ----------------------------- BTX1 byte-count baseline -----------------------------


def estimate_btx1_per_order_bytes():
    """
    Estimate the size of one BTX1 v2 artifact for a typical order. Matches
    the layout in btx_0b.serialize_artifact: ~207B (the B4 mainnet broadcast
    confirmed 207B for a runestone-flag order).
    """
    return 207


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

    # --- Build N=5 batch announce record ---
    N_ORDERS = 5
    orders = []
    for i in range(N_ORDERS):
        orders.append(dict(
            seckey=_good_sk(rand_bytes),
            rune_block=9999999 - i,
            rune_tx=i + 1,
            amount=1000 * (i + 1),
            price=2_500_000,  # 0.025 BTC/unit
            expiry=999_999,
            offer_txid=rand_bytes(32),
            offer_vout=i % 4,
            payout_spk=b"\x00\x14" + rand_bytes(20),  # synthetic P2WPKH
        ))

    batch_payload, halfagg = build_batch_announce(orders)
    ok, info = verify_batch_announce(batch_payload)
    if not ok:
        failures.append(f"batch verify failed: {info}")

    # Envelope wrap + roundtrip parse
    env_bytes = serialize_envelope([(REC_BATCH_ANNOUNCE, batch_payload)])
    version, parsed = parse_envelope(env_bytes)
    if version != VERSION:
        failures.append(f"version mismatch: {version}")
    if len(parsed) != 1 or parsed[0][0] != REC_BATCH_ANNOUNCE:
        failures.append("envelope didn't roundtrip to one batch record")
    elif parsed[0][1] != batch_payload:
        failures.append("batch payload changed across roundtrip")

    # --- Build conditional-order record ---
    oracle_seckey = _good_sk(rand_bytes)
    T = point_mul(G, int.from_bytes(oracle_seckey, "big"))
    cond_order = orders[0]  # reuse one of the orders for convenience
    cond_payload = build_conditional_order(cond_order, T)
    ok2, info2 = verify_conditional_order(cond_payload)
    if not ok2:
        failures.append(f"conditional verify failed: {info2}")

    # Wrap conditional in envelope, roundtrip
    env2 = serialize_envelope([(REC_CONDITIONAL_ORDER, cond_payload)])
    _, parsed2 = parse_envelope(env2)
    if len(parsed2) != 1 or parsed2[0][0] != REC_CONDITIONAL_ORDER:
        failures.append("conditional envelope didn't roundtrip")

    # --- Mixed envelope: single, batch, conditional in one ---
    single_passthrough = b"\xab" * 50  # opaque BTX1 body; carrier doesn't introspect
    mixed = serialize_envelope([
        (REC_SINGLE_ORDER, single_passthrough),
        (REC_BATCH_ANNOUNCE, batch_payload),
        (REC_CONDITIONAL_ORDER, cond_payload),
    ])
    _, parsed_mixed = parse_envelope(mixed)
    if [r[0] for r in parsed_mixed] != [REC_SINGLE_ORDER, REC_BATCH_ANNOUNCE, REC_CONDITIONAL_ORDER]:
        failures.append("mixed envelope record order changed")
    if parsed_mixed[1][1] != batch_payload or parsed_mixed[2][1] != cond_payload:
        failures.append("mixed envelope payloads diverged")

    # --- Byte savings: N=5, N=10, N=20 ---
    btx1_per_order = estimate_btx1_per_order_bytes()
    savings = {}
    for n in [1, 5, 10, 20, 50]:
        # BTX1 baseline: N independent envelopes (each ~207B for the artifact alone).
        btx1_total = n * btx1_per_order

        # BTX2 batch: one envelope wrapping one batch record containing N orders.
        # Synthesize bodies (we already have the sizes empirically for N=5; for
        # other N we extrapolate to the same per-order body size).
        sample_body_len = struct.unpack(">H", batch_payload[2:4])[0]  # first body's length
        per_order_overhead = 2 + sample_body_len   # body-length prefix + body
        batch_record_body = 2 + n * per_order_overhead + 32 * (n + 1)
        envelope_overhead = 4 + 1 + 2 + 1 + 2   # magic + ver + count + rec_type + rec_len
        btx2_total = envelope_overhead + batch_record_body

        savings[f"N={n}"] = {
            "btx1_independent_envelopes_bytes": btx1_total,
            "btx2_one_envelope_one_batch_bytes": btx2_total,
            "savings_pct": round((1 - btx2_total / btx1_total) * 100, 1),
        }

    result = {
        "ALL_PASS": len(failures) == 0,
        "tests_total": 6,
        "tests_passed": 6 - len(failures),
        "failures": failures,
        "batch_announce_demo": {
            "N_orders": N_ORDERS,
            "envelope_bytes": len(env_bytes),
            "halfagg_bytes": len(halfagg),
            "halfagg_verify": info,
        },
        "conditional_order_demo": {
            "envelope_bytes": len(env2),
            "adaptor_verify": info2,
        },
        "byte_savings_vs_BTX1_independent_envelopes": savings,
    }
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    import sys
    result = selftest()
    sys.exit(0 if result["ALL_PASS"] else 1)
