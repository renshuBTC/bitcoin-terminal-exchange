#!/usr/bin/env python3
"""
btx.py — BTX maker/taker command-line interface.

A single entry point over the protocol primitives that were already proven on real Bitcoin Core
v29.1 (see BTX-phase0-STATUS.md). This file adds NO new protocol logic: it imports and composes
`btx_0b.py` (BTX order artifact: serialize / parse / verify / build / lots) and `btx_runes.py`
(Runes runestone encoding). Those modules remain the single source of truth.

Everything here is offline and deterministic — it produces bytes (hex) you broadcast yourself with
your own node/wallet. btx.py never talks to a network, never holds keys beyond the deterministic
test seeds used by the proven scripts. Treat the seed-derived keys as PROTOTYPE keys: real maker
keys must come from the wallet, which is the next integration step.

Subcommands
-----------
  order create   maker: sign a BTX order over an offer UTXO; emit artifact hex + carrier OP_RETURN
  order lots     maker: split a total into a powers-of-two lot ladder sharing one group_id
  order inspect  decode a BTX artifact hex into human-readable fields
  order verify   second-node check: verify the maker signature from artifact + on-chain offer amount
  swap  build    taker: assemble the atomic swap tx from an artifact (witness transplanted)
  book  summary  read-side aggregation: total / filled / open per group_id ("X of Y filled")
  runestone      emit a byte-accurate runestone OP_RETURN scriptPubKey for given edicts
  client orders  fetch the OPEN book from a running BRK server (GET /api/v1/btx/orders)
  client groups  fetch partial-fill summaries from BRK (GET /api/v1/btx/groups)

Run `python3 btx.py <cmd> -h` for per-command flags. Amounts are in satoshis unless a *_btc
flag is offered; 1 BTC = 100_000_000 sats.
"""
import sys, os, json, argparse
import urllib.request, urllib.error

# import the proven primitives from this directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import btx_0b as btx
import btx_runes as runes
import btx_carrier as carrier
from bitcoin.core import COIN, b2x, x, lx, b2lx, CTransaction
from bitcoin.core.script import CScript, OP_RETURN


# ----------------------------- helpers -----------------------------
def _carrier_spk(blob: bytes) -> CScript:
    """Default OP_RETURN carrier for the artifact (see btx_0b header re: -datacarriersize)."""
    return CScript([OP_RETURN, blob])


def _artifact_to_public_dict(art: dict) -> dict:
    """Human-readable view of a BTX artifact dict (bytes -> hex, ids -> display form)."""
    return {
        "ver": art.get("ver", 2),
        "msg_type": art["msg_type"],
        "side": art["side"],
        "side_label": "SELL/offer-asset-for-BTC" if art["side"] == 0 else "BUY",
        "rune_id": f"{art['rune_block']}:{art['rune_tx']}",
        "amount_units": art["amount"],
        "price_sats": art["price"],
        "price_btc": art["price"] / COIN,
        "expiry_height": art["expiry"],
        "group_id": art.get("group_id", 0),
        "offer_outpoint": f"{b2lx(art['offer_txid'])}:{art['offer_vout']}",
        "payout_spk_hex": b2x(bytes(art["payout_spk"])),
        "maker_pubkey_hex": b2x(bytes(art["maker_pubkey"])),
        "sighash_flag": art["sighash_flag"],
        "sighash_flag_label": "SINGLE|ANYONECANPAY (0x83)" if art["sighash_flag"] == 0x83 else hex(art["sighash_flag"]),
    }


def _emit(obj):
    print(json.dumps(obj, default=str, indent=2))


def _extract_btx_from_tx(tx):
    """Yield (carrier_index, parsed_artifact) for every BTX1 artifact carried by `tx`, regardless of
    carrier. Mirrors the authoritative brk-btx indexer BYTE-FOR-BYTE: btx.rs::extract_from_script scans
    EVERY output's raw scriptPubKey for the MAGIC and parses from the FIRST MAGIC onward (it is NOT limited
    to OP_RETURN and tolerates bytes before MAGIC), and btx.rs::extract_from_witness does the same over the
    reassembled envelope payload. Matching that exactly is what keeps the cross-indexer consensus hash
    identical even on adversarial carriers (junk before MAGIC, non-OP_RETURN carriers) — a stricter
    "MAGIC must start the push / OP_RETURN-only" rule here would make this reconstruction disagree with
    the served book on such carriers. Carrier index: output vout (>=0) or -1 for a witness envelope."""
    found = []
    # (1) outputs: scan every output's raw scriptPubKey for MAGIC, parse from there (extract_from_script)
    for n, vout in enumerate(tx.vout):
        raw = bytes(vout.scriptPubKey)
        pos = raw.find(btx.MAGIC)
        if pos >= 0:
            try:
                found.append((n, btx.parse_artifact(raw[pos:])))
            except Exception:
                pass
    # (2) Taproot witness envelopes: reassemble the payload, then parse from the FIRST MAGIC onward
    #     (extract_from_witness: parse_envelope_payload -> windows().position(MAGIC) -> parse(payload[pos..]))
    wit = getattr(tx, "wit", None)
    for inw in (wit.vtxinwit if wit is not None else []):
        # Only the REVEALED TAPSCRIPT can carry a BTX envelope — inspect ONLY the leaf script element,
        # mirroring btx.rs::taproot_leaf_script_bytes: it's the 2nd-from-last witness element, or the
        # 3rd-from-last when a BIP341 annex (last element, first byte 0x50) is present. Scanning EVERY
        # element (sig / control block / annex) would over-admit an artifact an adversary hid in the
        # annex — which the Rust indexer ignores — splitting the cross-indexer book.
        stack = list(inw.scriptWitness.stack)
        n = len(stack)
        if n < 2:
            continue
        from_end = 3 if bytes(stack[-1])[:1] == b'\x50' else 2  # skip the annex if present
        if n < from_end:
            continue
        blob = carrier.parse_envelope(bytes(stack[n - from_end]))
        if blob:
            pos = blob.find(btx.MAGIC)
            if pos >= 0:
                try:
                    found.append((-1, btx.parse_artifact(blob[pos:])))
                except Exception:
                    pass
    return found


def _sats_from_args(sats_val, btc_val, name):
    if sats_val is not None and btc_val is not None:
        sys.exit(f"give only one of --{name}-sats / --{name}-btc")
    if sats_val is not None:
        return int(sats_val)
    if btc_val is not None:
        return int(round(btc_val * COIN))
    sys.exit(f"missing --{name}-sats or --{name}-btc")


# ----------------------------- order create -----------------------------
def cmd_order_create(a):
    offer_amt = _sats_from_args(a.offer_amount_sats, a.offer_amount_btc, "offer-amount")
    price = _sats_from_args(a.price_sats, a.price_btc, "price")
    art = btx.make_artifact(
        a.offer_txid, a.offer_vout, offer_amt, price,
        amount_units=a.amount_units, expiry=a.expiry, group_id=a.group_id,
    )
    blob = btx.serialize_artifact(art)
    carrier = _carrier_spk(blob)
    out = {
        "artifact_hex": b2x(blob),
        "artifact_bytes": len(blob),
        "carrier_op_return_spk_hex": b2x(carrier),
        "order": _artifact_to_public_dict(btx.parse_artifact(blob)),
        "note": "PROTOTYPE maker key (deterministic seed). Broadcast the carrier OP_RETURN on-chain to publish.",
    }
    _emit(out)


# ----------------------------- order lots -----------------------------
def cmd_order_lots(a):
    # decompose total into a powers-of-two ladder, then map onto the provided offer UTXOs
    ladder = btx.lot_decomposition(a.total_units)
    utxos = json.loads(a.offer_utxos) if a.offer_utxos else None
    if utxos is None:
        # no real UTXOs supplied: just show the decomposition plan
        _emit({
            "total_units": a.total_units,
            "lot_ladder_units": ladder,
            "n_lots": len(ladder),
            "group_id": a.group_id,
            "note": "Plan only. Pass --offer-utxos to sign one artifact per lot (each needs its own pre-funded UTXO).",
        })
        return
    if len(utxos) != len(ladder):
        sys.exit(f"need exactly {len(ladder)} offer UTXOs for total {a.total_units} "
                 f"(ladder {ladder}); got {len(utxos)}")
    offer_utxos = [(u["txid"], u["vout"], int(u["amount_sats"]), units)
                   for u, units in zip(utxos, ladder)]
    arts = btx.make_lots(offer_utxos, a.price_sats_per_unit, a.group_id, expiry=a.expiry)
    lots = []
    for units, art in zip(ladder, arts):
        blob = btx.serialize_artifact(art)
        lots.append({
            "lot_units": units,
            "artifact_hex": b2x(blob),
            "carrier_op_return_spk_hex": b2x(_carrier_spk(blob)),
            "committed_payout_sats": art["price"],
        })
    _emit({"group_id": a.group_id, "total_units": a.total_units,
           "lot_ladder_units": ladder, "lots": lots})


# ----------------------------- order inspect -----------------------------
def cmd_order_inspect(a):
    blob = bytes.fromhex(a.artifact_hex)
    art = btx.parse_artifact(blob)
    _emit({"artifact_bytes": len(blob), "order": _artifact_to_public_dict(art)})


# ----------------------------- order verify -----------------------------
def cmd_order_verify(a):
    blob = bytes.fromhex(a.artifact_hex)
    art = btx.parse_artifact(blob)
    offer_amt = _sats_from_args(a.offer_amount_sats, a.offer_amount_btc, "offer-amount")
    offer_spk = bytes.fromhex(a.offer_spk_hex) if getattr(a, "offer_spk_hex", None) else None
    ok = btx.verify_maker_sig(art, offer_amt, offer_spk)
    bound = offer_spk is not None
    _emit({
        "offer_outpoint": f"{b2lx(art['offer_txid'])}:{art['offer_vout']}",
        "offer_amount_sats": offer_amt,
        "pubkey_bound_to_offer_spk": bound,
        "maker_sig_verifies": bool(ok),
        "verdict": ("VALID open order" if (ok and bound) else
                    "VALID (sig only — pass --offer-spk-hex to bind the pubkey to the offer UTXO)" if ok else
                    "INVALID (sig does not verify / pubkey not bound to this offer UTXO)"),
        "note": "Offer amount AND scriptPubKey must come from YOUR node's UTXO set (gettxout). Without "
                "--offer-spk-hex this is a sig-only check — a forged artifact over another P2WPKH UTXO "
                "would pass it but can never be filled.",
    })


def _resolve_artifact_hex(a):
    """Get the artifact hex either directly (--artifact-hex) or by fetching the order from the served
    BRK book (--from-api --offer txid:vout). Lets discovery and fill happen in one step."""
    if getattr(a, "from_api", False):
        if not a.offer:
            sys.exit("--from-api requires --offer txid:vout")
        url = a.api_base.rstrip("/") + "/api/v1/btx/orders"
        try:
            orders = _http_get_json(url, a.timeout)
        except (urllib.error.URLError, OSError, ValueError) as e:
            sys.exit(f"failed to fetch {url}: {e}  (is the BRK server running on that port?)")
        match = next(
            (o for o in orders if f"{o['offer_txid']}:{o['offer_vout']}" == a.offer), None)
        if match is None:
            sys.exit(f"order {a.offer} not found in the served book at {url}")
        if not match.get("artifact_hex"):
            sys.exit(f"order {a.offer} has no artifact_hex (BRK server too old?)")
        return match["artifact_hex"]
    if not a.artifact_hex:
        sys.exit("provide --artifact-hex, or --from-api --offer txid:vout")
    return a.artifact_hex


# ----------------------------- swap build -----------------------------
def cmd_swap_build(a):
    blob = bytes.fromhex(_resolve_artifact_hex(a))
    art = btx.parse_artifact(blob)
    offer_amt = _sats_from_args(a.offer_amount_sats, a.offer_amount_btc, "offer-amount")
    pay_amt = _sats_from_args(a.pay_amount_sats, a.pay_amount_btc, "pay-amount")
    tx = btx.build_swap_from_artifact(
        art, offer_amt, (a.pay_txid, a.pay_vout), pay_amt, a.taker_seed.encode())
    wit0 = bytes(tx.wit.vtxinwit[0].scriptWitness.stack[0])
    _emit({
        "tx_hex": b2x(tx.serialize()),
        "input0_witness_is_artifact_sig": (wit0 == art["maker_sig"]),
        "output0_committed_payout_sats": tx.vout[0].nValue,
        "taker_change_sats": tx.vout[1].nValue,
        "note": "PROTOTYPE taker key (seed). Broadcast tx_hex with sendrawtransaction. "
                "Maker witness is transplanted unchanged — no re-sign, no relay.",
    })


# ----------------------------- book summary -----------------------------
def cmd_book_summary(a):
    """Read-side aggregation mirroring btx.rs::group_summary. Input: list of artifact hexes and an
    optional set of filled offer outpoints (txid:vout). Reports total/filled/open units per group."""
    arts = [btx.parse_artifact(bytes.fromhex(h)) for h in json.loads(a.artifacts)]
    filled = set(json.loads(a.filled)) if a.filled else set()
    groups = {}
    for art in arts:
        gid = art.get("group_id", 0)
        op = f"{b2lx(art['offer_txid'])}:{art['offer_vout']}"
        g = groups.setdefault(gid, {"group_id": gid, "total_units": 0, "filled_units": 0,
                                    "open_units": 0, "n_lots": 0, "n_filled": 0})
        g["total_units"] += art["amount"]
        g["n_lots"] += 1
        if op in filled:
            g["filled_units"] += art["amount"]
            g["n_filled"] += 1
        else:
            g["open_units"] += art["amount"]
    _emit({"groups": list(groups.values())})


# ----------------------------- book scan -----------------------------
def cmd_book_scan(a):
    """Reconstruct the order book from chain data only. Input: a JSON list of raw tx hexes (the
    order they confirmed). For each tx we (1) pull any BTX artifacts from OP_RETURN carriers =
    announced orders, and (2) record every spent outpoint + that tx's output0. An order is then
    classified by the consensus-exact rule (btx.rs::is_fill): if its offer UTXO is spent and the spending
    tx's output AT THE OFFER'S INPUT INDEX == (price, payout_spk) it's a FILL, else a CANCEL; unspent =
    OPEN. (Index-matched, not output 0: a batch fill puts offer_k/payout_k at index k.)
    Optional --utxos {"txid:vout": amount_sats} lets us also verify the maker sig on OPEN orders."""
    txs = [CTransaction.deserialize(x(h)) for h in json.loads(a.txs)]
    utxos = json.loads(a.utxos) if a.utxos else {}

    orders = {}   # offer_outpoint -> {artifact, announce_tx_index, carrier_vout}
    spends = {}   # spent_outpoint -> (tx_index, output_value, output_spk_hex) AT THE OFFER'S INPUT INDEX
    for ti, tx in enumerate(txs):
        for in_idx, vin in enumerate(tx.vin):
            op = f"{b2lx(vin.prevout.hash)}:{vin.prevout.n}"
            # SIGHASH_SINGLE commits the output at the SAME index as the input it signs, so a batch-filled
            # offer at input k is matched against output k (not output 0). Mirrors btx.rs pass 2 — using
            # output 0 here would mis-CANCEL every batch-fill leg at index k>0.
            ok = tx.vout[in_idx] if in_idx < len(tx.vout) else None
            spends[op] = (ti, (ok.nValue if ok else None),
                          (b2x(bytes(ok.scriptPubKey)) if ok else None))
        for (n, art) in _extract_btx_from_tx(tx):
            op = f"{b2lx(art['offer_txid'])}:{art['offer_vout']}"
            orders.setdefault(op, {"artifact": art, "announce_tx_index": ti, "carrier_vout": n})

    book = []
    for op, rec in orders.items():
        art = rec["artifact"]
        row = {
            "offer_outpoint": op,
            "status": "OPEN",
            "rune_id": f"{art['rune_block']}:{art['rune_tx']}",
            "amount_units": art["amount"],
            "price_sats": art["price"],
            "group_id": art.get("group_id", 0),
            "announce_tx_index": rec["announce_tx_index"],
        }
        if op in spends:
            ti, o0val, o0spk = spends[op]
            is_fill = (o0val == art["price"] and o0spk == b2x(bytes(art["payout_spk"])))
            row["status"] = "FILLED" if is_fill else "CANCELLED"
            row["spent_in_tx_index"] = ti
            row["spend_output0_value_sats"] = o0val
            row["is_fill"] = is_fill
        else:
            # Unspent. An order past its expiry at the current tip is NOT part of the open book — this
            # MUST match the brk-btx indexer's read-time rule (open_orders_from_records: `tip > expiry`
            # is excluded), otherwise an independent reconstruction would disagree with the served book
            # and the cross-indexer consensus hash would diverge on expired-but-unspent orders.
            if a.tip_height is not None and int(a.tip_height) > int(art.get("expiry", 0xFFFFFFFF)):
                row["status"] = "EXPIRED"
            if op in utxos:
                # --utxos value may be a legacy int (amount only -> sig-only check, NO binding) OR
                # [amount, spk_hex] / {"amount":, "spk":} to ALSO bind the maker pubkey to the offer
                # UTXO's scriptPubKey (gettxout returns both). Sig-only can mislabel a forged artifact
                # over an unrelated UTXO as a "valid open order"; binding rejects it (mirrors btx.rs).
                uv = utxos[op]
                if isinstance(uv, dict):
                    amt_op, spk_hex = int(uv["amount"]), uv.get("spk")
                elif isinstance(uv, (list, tuple)):
                    amt_op, spk_hex = int(uv[0]), (uv[1] if len(uv) > 1 else None)
                else:
                    amt_op, spk_hex = int(uv), None
                ospk = bytes.fromhex(spk_hex) if spk_hex else None
                row["maker_sig_verifies"] = bool(btx.verify_maker_sig(art, amt_op, ospk))
                row["pubkey_bound_to_offer_spk"] = (ospk is not None)
        book.append(row)

    n_open = sum(1 for r in book if r["status"] == "OPEN")
    n_filled = sum(1 for r in book if r["status"] == "FILLED")
    n_cancelled = sum(1 for r in book if r["status"] == "CANCELLED")
    n_expired = sum(1 for r in book if r["status"] == "EXPIRED")
    _emit({"scanned_txs": len(txs), "orders_found": len(book), "open": n_open, "filled": n_filled,
           "cancelled": n_cancelled, "expired": n_expired, "tip_height": a.tip_height, "orders": book})


# ----------------------------- runestone -----------------------------
def cmd_runestone(a):
    """edicts: JSON list of [block, tx, amount, output]."""
    edicts = [tuple(e) for e in json.loads(a.edicts)]
    spk = runes.runestone_spk(edicts)
    _emit({"edicts": edicts, "runestone_spk_hex": b2x(spk)})


# ----------------------------- client (remote BRK order book) -----------------------------
# Discovery against the BRK order-book HTTP API (the served, chain-reconstructed book) instead of a
# local `book scan`. The maker publishes on-chain; BRK's indexer reconstructs the book and serves it
# at /api/v1/btx/orders and /api/v1/btx/groups (default port 3110). Pure stdlib urllib — no new deps.
def _http_get_json(url, timeout=5):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def cmd_client_orders(a):
    url = a.api_base.rstrip("/") + "/api/v1/btx/orders"
    try:
        orders = _http_get_json(url, a.timeout)
    except (urllib.error.URLError, OSError, ValueError) as e:
        sys.exit(f"failed to fetch {url}: {e}  (is the BRK server running on that port?)")
    if a.group_id is not None:
        orders = [o for o in orders if o.get("group_id") == a.group_id]
    if a.json:
        _emit(orders)
        return
    print(f"{len(orders)} open order(s) from {url}")
    for o in orders:
        print(f"  {o['offer_txid']}:{o['offer_vout']}  rune {o['rune_id']}  amount {o['amount']}  "
              f"price {o['price']} sat  group {o['group_id']}  expiry {o['expiry']}  "
              f"announced@{o['announce_height']}")


def cmd_client_groups(a):
    url = a.api_base.rstrip("/") + "/api/v1/btx/groups"
    try:
        groups = _http_get_json(url, a.timeout)
    except (urllib.error.URLError, OSError, ValueError) as e:
        sys.exit(f"failed to fetch {url}: {e}  (is the BRK server running on that port?)")
    if a.json:
        _emit(groups)
        return
    print(f"{len(groups)} group(s) from {url}")
    for g in groups:
        print(f"  group {g['group_id']}: {g['filled']}/{g['total']} filled, "
              f"{g['open']} open, across {g['lots']} lot(s)")


# ----------------------------- argparse -----------------------------
def build_parser():
    p = argparse.ArgumentParser(prog="btx", description="BTX maker/taker CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    order = sub.add_parser("order", help="maker / inspection commands").add_subparsers(
        dest="ocmd", required=True)

    oc = order.add_parser("create", help="sign a BTX order; emit artifact + carrier")
    oc.add_argument("--offer-txid", required=True)
    oc.add_argument("--offer-vout", type=int, required=True)
    oc.add_argument("--offer-amount-sats", type=int)
    oc.add_argument("--offer-amount-btc", type=float)
    oc.add_argument("--price-sats", type=int)
    oc.add_argument("--price-btc", type=float)
    oc.add_argument("--amount-units", type=int, default=1000)
    oc.add_argument("--expiry", type=int, default=10**9)
    oc.add_argument("--group-id", type=int, default=0)
    oc.set_defaults(func=cmd_order_create)

    ol = order.add_parser("lots", help="powers-of-two lot ladder sharing a group_id")
    ol.add_argument("--total-units", type=int, required=True)
    ol.add_argument("--price-sats-per-unit", type=int, default=50000)
    ol.add_argument("--group-id", type=int, required=True)
    ol.add_argument("--expiry", type=int, default=10**9)
    ol.add_argument("--offer-utxos", help='JSON list of {"txid","vout","amount_sats"} (one per lot)')
    ol.set_defaults(func=cmd_order_lots)

    oi = order.add_parser("inspect", help="decode a BTX artifact hex")
    oi.add_argument("--artifact-hex", required=True)
    oi.set_defaults(func=cmd_order_inspect)

    ov = order.add_parser("verify", help="verify maker sig from artifact + offer amount (+ offer spk)")
    ov.add_argument("--artifact-hex", required=True)
    ov.add_argument("--offer-amount-sats", type=int)
    ov.add_argument("--offer-amount-btc", type=float)
    ov.add_argument("--offer-spk-hex", help="the offer UTXO's scriptPubKey hex (from gettxout). REQUIRED "
                    "to bind the maker pubkey to the offer UTXO; without it the check is sig-only and a "
                    "forged artifact over another P2WPKH UTXO would falsely read as VALID.")
    ov.set_defaults(func=cmd_order_verify)

    swap = sub.add_parser("swap", help="taker commands").add_subparsers(
        dest="scmd", required=True)
    sb = swap.add_parser("build", help="assemble the atomic swap tx from an artifact")
    sb.add_argument("--artifact-hex", help="artifact directly (or use --from-api --offer)")
    sb.add_argument("--from-api", action="store_true", help="fetch the order from the served BRK book")
    sb.add_argument("--api-base", default="http://127.0.0.1:3110", help="BRK server base URL")
    sb.add_argument("--offer", help="offer outpoint txid:vout to fill (with --from-api)")
    sb.add_argument("--timeout", type=float, default=5)
    sb.add_argument("--offer-amount-sats", type=int)
    sb.add_argument("--offer-amount-btc", type=float)
    sb.add_argument("--pay-txid", required=True)
    sb.add_argument("--pay-vout", type=int, required=True)
    sb.add_argument("--pay-amount-sats", type=int)
    sb.add_argument("--pay-amount-btc", type=float)
    sb.add_argument("--taker-seed", default="btx-taker")
    sb.set_defaults(func=cmd_swap_build)

    book = sub.add_parser("book", help="read-side order-book queries").add_subparsers(
        dest="bcmd", required=True)
    bs = book.add_parser("summary", help="total/filled/open per group_id")
    bs.add_argument("--artifacts", required=True, help="JSON list of artifact hex strings")
    bs.add_argument("--filled", help='JSON list of filled offer outpoints "txid:vout"')
    bs.set_defaults(func=cmd_book_summary)

    bsc = book.add_parser("scan", help="reconstruct OPEN/FILLED/CANCELLED book from raw txs")
    bsc.add_argument("--txs", required=True, help="JSON list of raw tx hex (confirmation order)")
    bsc.add_argument("--utxos", help='JSON map {"txid:vout": amount_sats} to verify OPEN sigs')
    bsc.add_argument("--tip-height", type=int, default=None,
                     help="current chain tip height; when set, unspent orders past their expiry are "
                          "marked EXPIRED (not OPEN), matching the brk-btx served book so the "
                          "reconstructed book hash agrees across indexers")
    bsc.set_defaults(func=cmd_book_scan)

    rs = sub.add_parser("runestone", help="emit a runestone OP_RETURN scriptPubKey")
    rs.add_argument("--edicts", required=True, help="JSON list of [block,tx,amount,output]")
    rs.set_defaults(func=cmd_runestone)

    client = sub.add_parser("client", help="query the served BRK order book over HTTP").add_subparsers(
        dest="ccmd", required=True)
    co = client.add_parser("orders", help="GET /api/v1/btx/orders (open book)")
    co.add_argument("--api-base", default="http://127.0.0.1:3110", help="BRK server base URL")
    co.add_argument("--timeout", type=float, default=5)
    co.add_argument("--group-id", type=int, help="filter to one group_id")
    co.add_argument("--json", action="store_true", help="raw JSON instead of a table")
    co.set_defaults(func=cmd_client_orders)
    cg = client.add_parser("groups", help="GET /api/v1/btx/groups (partial-fill summaries)")
    cg.add_argument("--api-base", default="http://127.0.0.1:3110", help="BRK server base URL")
    cg.add_argument("--timeout", type=float, default=5)
    cg.add_argument("--json", action="store_true", help="raw JSON instead of a table")
    cg.set_defaults(func=cmd_client_groups)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
