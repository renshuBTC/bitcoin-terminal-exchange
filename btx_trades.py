#!/usr/bin/env python3
"""
btx_trades.py — heuristic Runes-marketplace-trade classifier (Phase B of the live-activity feed).

Combines two things BTX already understands:
  - the SIGHASH_SINGLE|ANYONECANPAY pre-signed-swap pattern (sighash byte 0x83) — how Magic Eden /
    UniSat / OKX runes & ordinal fills settle: the seller pre-signs their asset-bearing input,
    committing the output at the SAME index (BIP143/341 SINGLE) to their BTC payout;
  - the runestone decoder (btx_runes_decode) — which rune moved, how much, to which output.

From a confirmed tx it emits a LIKELY-trade record: {rune_id, amount, btc_paid, seller(receives the
BTC payout), buyer(receives the rune)}.

HEURISTIC — not proof. `0x83` has other uses, marketplaces pad with dummy/postage outputs, and a tx
can carry several edicts; so a hit means "looks like a runes marketplace fill," and the buyer/seller
attribution is best-effort. Honest labelling is the point.

Operates on mempool.space-style tx JSON:
  vin[i].witness          : list of witness hex items (to detect the 0x83 pre-signed input)
  vout[i].scriptpubkey    : output script hex (to find the runestone OP_RETURN)
  vout[i].value           : sats
  vout[i].scriptpubkey_address : (optional) address for display

Usage:
  python3 btx_trades.py classify <tx.json>    # tx.json = a mempool.space /api/tx/<txid> response
  python3 btx_trades.py selftest
"""
import sys, json
from btx_runes_decode import decode_runestone, _encode_runestone_spk

SAA = 0x83  # SIGHASH_SINGLE | SIGHASH_ANYONECANPAY


def _b(x):
    return bytes.fromhex(x) if isinstance(x, str) else bytes(x)


def witness_is_single_anyonecanpay(items):
    """True if a witness stack is a SINGLE|ANYONECANPAY-signed input (mirrors the Rust detector):
      - P2WPKH: [der_sig||0x83, pubkey(33)]  (DER sig starts 0x30, ends 0x83)
      - P2TR key-path: [schnorr_sig(65)]     (64-byte sig + 0x83 sighash byte)"""
    its = [_b(x) for x in (items or [])]
    if len(its) == 2 and len(its[1]) == 33 and len(its[0]) >= 9 and its[0][0] == 0x30 and its[0][-1] == SAA:
        return True
    if len(its) == 1 and len(its[0]) == 65 and its[0][64] == SAA:
        return True
    return False


def classify_runes_trade(tx):
    """Classify a mempool.space-style tx dict. Returns a record; is_runes_trade is True only when the
    tx has BOTH a pre-signed (0x83) input AND a runestone with at least one edict."""
    vin = tx.get("vin", []) or []
    vout = tx.get("vout", []) or []
    presigned = [i for i, v in enumerate(vin) if witness_is_single_anyonecanpay(v.get("witness", []))]

    runestone = None
    for vo in vout:
        spk = vo.get("scriptpubkey", "") or ""
        if spk.startswith("6a5d"):  # OP_RETURN OP_PUSHNUM_13
            runestone = decode_runestone(spk)
            break
    edicts = (runestone or {}).get("edicts") or []

    out = {
        "is_runes_trade": bool(presigned) and bool(edicts),
        "presigned_inputs": presigned,
        "has_runestone": runestone is not None,
        "cenotaph": bool((runestone or {}).get("cenotaph")),
        "trades": [],
    }
    if not out["is_runes_trade"]:
        return out

    for i in presigned:
        # SIGHASH_SINGLE commits the output at the same index as the signed input => seller's payout
        payout = vout[i] if i < len(vout) else None
        for ed in edicts:
            oi = ed["output"]
            buyer = vout[oi] if oi < len(vout) else None
            out["trades"].append({
                "rune_id": ed["id"],
                "amount": ed["amount"],
                "btc_paid_sats": (payout or {}).get("value"),
                "seller_addr": (payout or {}).get("scriptpubkey_address"),  # receives the BTC payout
                "buyer_addr": (buyer or {}).get("scriptpubkey_address"),    # receives the rune
                "rune_output": oi,
                "presigned_input": i,
            })
    return out


# ----------------------------- selftest -----------------------------
def _runestone_vout(edicts_after_body):
    """Build a runestone vout dict carrying a Body + edict stream (ints after Body tag)."""
    spk = _encode_runestone_spk([0] + edicts_after_body).hex()  # 0 = Tag::Body
    return {"scriptpubkey": spk, "value": 0}


def selftest():
    checks = {}
    sig83 = (b"\x00" * 64 + b"\x83").hex()                       # 65-byte taproot sig ending 0x83
    der_all = ("30" + "44" + "0220" + "11" * 32 + "0220" + "22" * 32 + "01")  # DER sig ending 0x01
    pub = "02" + "33" * 32                                       # 33-byte pubkey

    # synthetic marketplace fill: seller's pre-signed rune input at index 0 (=> output0 is the payout),
    # buyer funding input at index 1; runestone moves rune 840100:7 (amount 1000) to output 1 (buyer).
    fill = {
        "vin": [
            {"witness": [sig83]},                                # presigned seller input
            {"witness": [der_all, pub]},                         # buyer funding (SIGHASH_ALL) - not presigned
        ],
        "vout": [
            {"value": 50000, "scriptpubkey": "0014" + "aa" * 20, "scriptpubkey_address": "bc1q_seller"},
            {"value": 546, "scriptpubkey": "5120" + "bb" * 32, "scriptpubkey_address": "bc1p_buyer"},
            _runestone_vout([840100, 7, 1000, 1]),
        ],
    }
    r = classify_runes_trade(fill)
    checks["fill_is_trade"] = (r["is_runes_trade"] is True)
    checks["fill_presigned_input0_only"] = (r["presigned_inputs"] == [0])
    t = r["trades"][0] if r["trades"] else {}
    checks["fill_rune_id"] = (t.get("rune_id") == "840100:7")
    checks["fill_amount"] = (t.get("amount") == 1000)
    checks["fill_btc_paid"] = (t.get("btc_paid_sats") == 50000)
    checks["fill_seller"] = (t.get("seller_addr") == "bc1q_seller")
    checks["fill_buyer"] = (t.get("buyer_addr") == "bc1p_buyer")
    checks["fill_rune_output"] = (t.get("rune_output") == 1)

    # negative 1: runestone but NO presigned input => not a trade
    no_presign = {"vin": [{"witness": [der_all, pub]}],
                  "vout": [{"value": 1000, "scriptpubkey": "0014" + "cc" * 20},
                           _runestone_vout([840000, 3, 1000, 0])]}
    checks["neg_no_presign"] = (classify_runes_trade(no_presign)["is_runes_trade"] is False)

    # negative 2: presigned input but NO runestone => not a trade (just a pre-signed BTC swap)
    no_rune = {"vin": [{"witness": [sig83]}],
               "vout": [{"value": 50000, "scriptpubkey": "0014" + "dd" * 20}]}
    nr = classify_runes_trade(no_rune)
    checks["neg_no_runestone"] = (nr["is_runes_trade"] is False and nr["presigned_inputs"] == [0])

    # negative 3: a cenotaph runestone (non-push opcode) with a presigned input => no edicts => not a trade
    ceno = {"vin": [{"witness": [sig83]}],
            "vout": [{"value": 50000, "scriptpubkey": "0014" + "ee" * 20},
                     {"value": 0, "scriptpubkey": "6a5d51"}]}  # OP_RETURN OP_13 OP_1
    cr = classify_runes_trade(ceno)
    checks["neg_cenotaph_no_edicts"] = (cr["is_runes_trade"] is False and cr["cenotaph"] is True)

    allpass = all(v is True for v in checks.values())
    print(json.dumps({"checks": checks, "ALL_PASS": allpass}, indent=2))
    return allpass


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "classify":
        with open(sys.argv[2]) as f:
            print(json.dumps(classify_runes_trade(json.load(f)), indent=2, default=str))
    elif len(sys.argv) >= 2 and sys.argv[1] == "selftest":
        sys.exit(0 if selftest() else 1)
    else:
        print(__doc__)
        sys.exit(2)
