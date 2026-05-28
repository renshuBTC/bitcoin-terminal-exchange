#!/usr/bin/env python3
"""btx_orderbook.py — deterministic, verifiable BTX order book (roadmap #1).

Turns the flat list of chain-reconstructed BTX orders into a canonical price-time book plus a content
hash, so any two indexers over the same chain produce a byte-identical book they can prove they agree
on — the discipline behind Omni MetaDEx's saveOffer->CHash256, adapted to BTX's pre-signed UTXO
offers. The book itself stays on-chain-reconstructed and nothing-offchain; this only canonicalizes the
read.

Pure: no node, no network.

Determinism rules (fully specified so independent implementations match byte-for-byte):
  - Group by rune pair (`rune_id`). BTC-only orders (rune_id missing or "0:0") bucket under "BTC".
  - `side`: 0 = sell-rune (ask), 1 = buy-rune (bid).
  - Asks sort by: price asc, then announce_height asc, then offer_txid asc (hex), then offer_vout asc.
  - Bids sort by: price DESC, then announce_height asc, then offer_txid asc, then offer_vout asc.
    (Time priority by height; the offer outpoint is the final, globally-unique tiebreak so the order
    is total and implementation-independent — never rely on input order or dict iteration.)
  - Cumulative `total` = running sum of `amount` from best price outward.
  - `book_hash` = sha256 over one canonical line per order, orders sorted by the same total key, so
    the hash depends only on the order SET, not the order they arrived in.
"""
import hashlib
import re

# Chain-derived canonical fields can NEVER contain the canonical-line delimiters ('|', ':', '\n'):
# rune_id is '{rune_block:u32}:{rune_tx:u16}' and offer_txid is a 32-byte hash rendered as 64 lowercase
# hex. The leaf/event encoding is delimiter-separated with no length prefix, so its collision-resistance
# depends on that field discipline. We enforce it at the single point that emits hashed bytes (fail
# closed) so a non-chain / hostile dict can't forge a delimiter-injection collision in the flat hash
# (the Merkle book_root is structurally immune, but the shared leaf encoding is guarded once).
# See BTX-security-audit-2026-05.md (flat-hash delimiter-injection, Informational).
_RUNE_ID_RE = re.compile(r"^[0-9]+:[0-9]+$")
_TXID_RE = re.compile(r"^[0-9a-f]{64}$")


def _check_canonical_fields(rune_id, offer_txid):
    if not _RUNE_ID_RE.match(rune_id):
        raise ValueError(f"non-canonical rune_id {rune_id!r} (must be '<digits>:<digits>')")
    if not _TXID_RE.match(offer_txid):
        raise ValueError(f"non-canonical offer_txid {offer_txid!r} (must be 64 lowercase hex)")


def _norm(o):
    return {
        "rune_id": str(o.get("rune_id") or "0:0"),
        "offer_txid": str(o.get("offer_txid") or ""),
        "offer_vout": int(o.get("offer_vout") or 0),
        "price": int(o.get("price") or 0),
        "amount": int(o.get("amount") or 0),
        "announce_height": int(o.get("announce_height") or 0),
        "side": int(o.get("side") or 0),
        # passthrough for clients (e.g. the GUI's click-to-fill); NOT part of book_hash, which
        # serializes only the canonical fields below — so carrying it never changes the hash.
        "artifact_hex": o.get("artifact_hex"),
    }


def _pair_of(o):
    return o["rune_id"] if (o["rune_id"] and o["rune_id"] != "0:0") else "BTC"


def _ask_key(o):
    return (o["price"], o["announce_height"], o["offer_txid"], o["offer_vout"])


def _bid_key(o):
    return (-o["price"], o["announce_height"], o["offer_txid"], o["offer_vout"])


def unit_price_sats(price, amount):
    """sats per ASSET BASE UNIT = total committed payout / units offered. The comparable price across
    orders of the same rune regardless of lot size (the raw `price` is the whole-lot payout, so two
    asks with equal `price` but different `amount` are NOT equally priced)."""
    amount = int(amount or 0)
    return (int(price or 0) / amount) if amount else 0.0


def whole_rune_price_sats(price, amount, divisibility):
    """sats to buy ONE WHOLE rune. A rune with divisibility d has 10**d base units per whole rune, so
    this normalizes per-unit prices into a unit comparable ACROSS runes of different divisibility.
    Needs the rune's divisibility (from the ord oracle); divisibility 0 -> identical to unit price."""
    amount = int(amount or 0)
    if amount <= 0:
        return 0.0
    return int(price or 0) * (10 ** int(divisibility or 0)) / amount


def build_book(orders, divmap=None):
    """Return {pair: {"asks":[..], "bids":[..], "best_ask":int|None, "best_bid":int|None}}; each level
    carries a cumulative "total", a `unit_price` (sats per base unit), and — when `divmap`
    ({rune_id: divisibility}) is supplied — a `norm_price` (sats per whole rune, comparable across
    runes). These are ADDITIVE display fields only; they are NOT part of book_hash, so adding them
    never changes the cross-indexer consensus hash. Fully deterministic for a given order set."""
    divmap = divmap or {}
    pairs = {}
    for raw in (orders or []):
        o = _norm(raw)
        pairs.setdefault(_pair_of(o), []).append(o)
    book = {}
    for pair in sorted(pairs):
        rows = pairs[pair]
        asks = sorted([o for o in rows if o["side"] == 0], key=_ask_key)
        bids = sorted([o for o in rows if o["side"] == 1], key=_bid_key)
        c = 0
        for o in asks:
            c += o["amount"]; o["total"] = c
        c = 0
        for o in bids:
            c += o["amount"]; o["total"] = c
        for o in asks + bids:
            o["unit_price"] = unit_price_sats(o["price"], o["amount"])
            if o["rune_id"] in divmap:
                o["norm_price"] = whole_rune_price_sats(o["price"], o["amount"], divmap[o["rune_id"]])
        book[pair] = {
            "asks": asks, "bids": bids,
            "best_ask": asks[0]["price"] if asks else None,
            "best_bid": bids[0]["price"] if bids else None,
        }
    return book


def _canonical_line(o):
    """The exact per-order bytes that BOTH book_hash and the Merkle leaf commit to — defined once so the
    flat hash and the book root can never drift. Order-independent canonical fields only (no artifact_hex).
    `side` is hardcoded 0, NOT taken from the order: the authoritative Rust indexer (btx::book_sorted_rows)
    hardcodes side=0 and ignores the artifact's parsed side, so the commitment is side-INDEPENDENT. Pinning
    0 here keeps Python byte-identical to Rust even if a caller passes a side-bearing dict (a side=1 order
    would otherwise emit "|1|" and diverge). Adding bids later requires committing side in BOTH impls together."""
    _check_canonical_fields(o["rune_id"], o["offer_txid"])   # fail closed on delimiter-injectable fields
    return (f'{o["rune_id"]}|0|{o["price"]}|{o["amount"]}|'
            f'{o["announce_height"]}|{o["offer_txid"]}:{o["offer_vout"]}\n').encode()


def _sorted_norm(orders):
    """Canonical, totally-ordered, normalized order list — the shared basis for book_hash and book_root.
    Sort key pins side=0 (constant) to match the Rust sort, which never uses the artifact side."""
    return sorted((_norm(o) for o in (orders or [])),
                  key=lambda o: (o["rune_id"], 0, o["price"], o["announce_height"],
                                 o["offer_txid"], o["offer_vout"]))


def book_hash(orders):
    """Order-set-independent content hash of the canonical book (the cross-indexer consensus check)."""
    h = hashlib.sha256()
    for o in _sorted_norm(orders):
        h.update(_canonical_line(o))
    return h.hexdigest()


# ---- Merkle book commitment + membership proofs (see BTX-book-commitment-design.md) -------------
# Domain-separated SHA-256 (RFC6962 / Certificate-Transparency pattern): leaf tag 0x00, internal-node
# tag 0x01 (prevents leaf/node second-preimage confusion). Leaves are the SAME canonical lines book_hash
# commits to, sorted by the SAME total key, so the root is order-set-independent exactly as book_hash is.
# A lone odd node at a level is carried up UNCHANGED (never duplicated — duplication reintroduces the
# CVE-2012-2459 ambiguity; carry-up + the domain tags is unambiguous). Empty book -> 00*32.
_EMPTY_ROOT = b"\x00" * 32


def _leaf_hash(o):
    return hashlib.sha256(b"\x00" + _canonical_line(o)).digest()


def _node_hash(left, right):
    return hashlib.sha256(b"\x01" + left + right).digest()


def _merkle_levels(leaves):
    """All levels bottom->top: levels[0] == leaves, levels[-1] == [root]; [] for an empty book."""
    if not leaves:
        return []
    levels = [list(leaves)]
    while len(levels[-1]) > 1:
        cur, nxt, i = levels[-1], [], 0
        while i + 1 < len(cur):
            nxt.append(_node_hash(cur[i], cur[i + 1])); i += 2
        if i < len(cur):
            nxt.append(cur[i])          # odd: carry the lone node up unchanged
        levels.append(nxt)
    return levels


def book_root(orders):
    """Hex Merkle root over the canonical open book (the committed book; supersedes the flat book_hash
    for light-client verification, but both are order-set-independent so cross-indexer agreement holds)."""
    levels = _merkle_levels([_leaf_hash(o) for o in _sorted_norm(orders)])
    return (levels[-1][0] if levels else _EMPTY_ROOT).hex()


def merkle_prove(orders, offer_txid, offer_vout):
    """Membership proof for the order at (offer_txid, offer_vout): {index, n, path:[{hash,dir}]} leaf->root,
    or None if that order isn't in the book. A lone-odd-node level contributes no step (carried up)."""
    norm = _sorted_norm(orders)
    idx = next((i for i, o in enumerate(norm)
                if o["offer_txid"] == str(offer_txid) and o["offer_vout"] == int(offer_vout)), None)
    if idx is None:
        return None
    levels = _merkle_levels([_leaf_hash(o) for o in norm])
    path, i = [], idx
    for lvl in range(len(levels) - 1):
        cur = levels[lvl]
        if i % 2 == 0:
            if i + 1 < len(cur):
                path.append({"hash": cur[i + 1].hex(), "dir": "R"})   # sibling to the right
        else:
            path.append({"hash": cur[i - 1].hex(), "dir": "L"})       # sibling to the left
        i //= 2
    return {"index": idx, "n": len(norm), "path": path}


def merkle_verify(order, proof, root_hex):
    """Recompute the root from a (normalized) order + its proof; True iff it equals root_hex. Needs only
    the proof + the root — no full book, no full node."""
    h = _leaf_hash(_norm(order))
    for step in proof["path"]:
        sib = bytes.fromhex(step["hash"])
        h = _node_hash(sib, h) if step["dir"] == "L" else _node_hash(h, sib)
    return h.hex() == root_hex


# ---- Cumulative event hash (announce/fill/cancel stream) -----------------------------------------
# Lets a light client FOLLOW the reconstructed book incrementally and detect reorg/omission: a single
# rolling commitment over the chain-CAUSED order events — an ANNOUNCE when an order is published, a
# FILL/CANCEL when its offer UTXO is spent. Like book_root this is a PURE function of the record set
# (the indexer keeps closed records, status-based, so the whole stream is reconstructable) — no running
# scalar, no new reorg-rollback surface. Inspired by OPI-LC's cumulative event hash; BTX grounds it in
# its OWN canonical order line so the Python<->Rust byte-for-byte parity is as trivial as book_hash's.
#
# Expiry is intentionally NOT an event: it has no transaction (an order past its expiry simply stops
# being OPEN, a read-time predicate), so it can't anchor a deterministic stream. The chain stream is
# exactly: announce (announce_height) + spend (last_event_height -> FILL if the spend pays the committed
# payout, else CANCEL). Domain tags continue the book_root scheme: leaf 0x00, node 0x01 are taken, so
# the per-block event digest is tagged 0x02 and the cumulative fold 0x03 (no cross-construction reuse).
_EVENT_BLOCK_TAG = b"\x02"
_CUM_TAG = b"\x03"
_CUM_GENESIS = b"\x00" * 32


def _events_of_record(r):
    """Chain-caused events of one order record as (height, code, normalized_order): always an ANNOUNCE
    'A' at announce_height; plus a 'F'/'C' at last_event_height iff the record resolved filled/cancelled.
    `status` is case-insensitive ('open'|'filled'|'cancelled'); OPEN/EXPIRED contribute only the ANNOUNCE."""
    o = _norm(r)
    evs = [(o["announce_height"], "A", o)]
    st = str(r.get("status") or "open").lower()
    leh = int(r.get("last_event_height") or 0)
    if st in ("filled", "fill", "f"):
        evs.append((leh, "F", o))
    elif st in ("cancelled", "canceled", "cancel", "c"):
        evs.append((leh, "C", o))
    return evs


def _event_line(height, code, o):
    """Canonical per-event bytes — the order body is the SAME canonical fields book_hash commits to,
    with `side` hardcoded 0 to match the authoritative Rust (which ignores the artifact side; see
    _canonical_line), prefixed by the event height and one-char code."""
    _check_canonical_fields(o["rune_id"], o["offer_txid"])   # same fail-closed guard as the book leaf
    return (f'{height}|{code}|{o["rune_id"]}|0|{o["price"]}|{o["amount"]}|'
            f'{o["announce_height"]}|{o["offer_txid"]}:{o["offer_vout"]}\n').encode()


def _event_sort_key(code, o):
    """Total order within a block: the canonical order key (side pinned 0, as in the line), then the
    event code (so an announce-and-fill in the SAME block is still deterministically ordered)."""
    return (o["rune_id"], 0, o["price"], o["announce_height"],
            o["offer_txid"], o["offer_vout"], code)


def event_block_hashes(records):
    """[(height, block_event_hash_hex), ...] ascending, one entry per EVENT-BEARING block, reconstructed
    from the record set. Each block digest is sha256(0x02 || concat(sorted event lines)) — order-set-
    independent (events sorted by the canonical key). This list IS the stream a light client folds."""
    by_h = {}
    for r in (records or []):
        for (h, code, o) in _events_of_record(r):
            by_h.setdefault(int(h), []).append((code, o))
    out = []
    for h in sorted(by_h):
        evs = sorted(by_h[h], key=lambda ce: _event_sort_key(ce[0], ce[1]))
        eng = hashlib.sha256()
        eng.update(_EVENT_BLOCK_TAG)
        for code, o in evs:
            eng.update(_event_line(h, code, o))
        out.append((h, eng.hexdigest()))
    return out


def cumulative_event_hash(records):
    """Rolling commitment over the whole announce/fill/cancel stream — a PURE function of the record set.
    Folds event-bearing blocks ascending: cum = sha256(0x03 || cum_prev || height_be4 || block_hash).
    Empty stream -> 00*32. Any honest indexer over the same chain returns the identical digest, and a
    light client that has followed to height H can advance by folding only each later block's digest."""
    cum = _CUM_GENESIS
    for h, bh_hex in event_block_hashes(records):
        cum = hashlib.sha256(_CUM_TAG + cum + int(h).to_bytes(4, "big") + bytes.fromhex(bh_hex)).digest()
    return cum.hex()


def event_stream(records):
    """The per-block event STREAM a light client folds to follow the book incrementally:
    [(height, block_hash_hex, cumulative_hex), ...] ascending, one entry per event-bearing block, where
    cumulative is the rolling commitment THROUGH that block (so any block is a resumable checkpoint). The
    last entry's cumulative equals cumulative_event_hash(records). PURE function of the record set;
    byte-identical to the Rust `event_stream_from_views` (golden cross-tested)."""
    cum = _CUM_GENESIS
    out = []
    for h, bh_hex in event_block_hashes(records):
        cum = hashlib.sha256(_CUM_TAG + cum + int(h).to_bytes(4, "big") + bytes.fromhex(bh_hex)).digest()
        out.append((h, bh_hex, cum.hex()))
    return out


def summary(orders):
    """Compact per-pair top-of-book + depth, for a status/header view."""
    return {pair: {"best_ask": b["best_ask"], "best_bid": b["best_bid"],
                   "asks": len(b["asks"]), "bids": len(b["bids"]),
                   "depth": (b["asks"][-1]["total"] if b["asks"] else 0)}
            for pair, b in build_book(orders).items()}


if __name__ == "__main__":
    import json, sys
    data = json.load(sys.stdin) if not sys.stdin.isatty() else []
    print(json.dumps({"hash": book_hash(data), "summary": summary(data)}, indent=2))
