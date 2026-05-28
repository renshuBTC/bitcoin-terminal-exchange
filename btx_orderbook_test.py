#!/usr/bin/env python3
"""Offline test for btx_orderbook — the deterministic verifiable book (roadmap #1).

Locks in: canonical price-time ordering, cumulative depth, best bid/ask, pair separation, and the
order-set-INDEPENDENT content hash (the cross-indexer consensus property). Pure, no node.
Run in WSL: python3 btx_orderbook_test.py
"""
import sys, os, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import btx_orderbook as B

OK = True
def check(name, cond, detail=""):
    global OK; OK = OK and bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))

def o(rune, price, amount, height, txid, vout=0, side=0):
    return {"rune_id": rune, "price": price, "amount": amount, "announce_height": height,
            "offer_txid": txid, "offer_vout": vout, "side": side}

orders = [
    o("306154:2", 10000, 1000, 120, "aa"*32),
    o("306154:2", 10000, 500, 118, "bb"*32),     # same price, earlier height -> ranks first
    o("306154:2", 9800, 2000, 130, "cc"*32),      # better (lower) ask -> best
    o("306154:2", 10000, 700, 118, "ab"*32),      # same price+height, txid tiebreak (ab<bb)
    o("840000:1", 200000, 1000, 121, "dd"*32),    # different pair
    o(None, 50000, 1, 100, "ee"*32),              # BTC-only -> "BTC" bucket
    o("306154:2", 9900, 100, 140, "ff"*32, side=1),  # a bid
]

book = B.build_book(orders)

# pairs separated
check("three pairs (306154:2, 840000:1, BTC)", set(book.keys()) == {"306154:2", "840000:1", "BTC"}, str(set(book.keys())))

asks = book["306154:2"]["asks"]
check("best ask is the lowest price (9800)", asks[0]["price"] == 9800 and book["306154:2"]["best_ask"] == 9800)
# price-time-outpoint ordering: 9800; then the three 10000s by (height,txid): 118/ab, 118/bb, 120/aa
order = [(a["price"], a["announce_height"], a["offer_txid"][:2]) for a in asks]
check("canonical price-time-outpoint order",
      order == [(9800,130,"cc"), (10000,118,"ab"), (10000,118,"bb"), (10000,120,"aa")], str(order))
# cumulative depth
check("cumulative totals", [a["total"] for a in asks] == [2000, 2700, 3200, 4200], str([a["total"] for a in asks]))
# bid side
check("bid recorded on 306154:2", book["306154:2"]["best_bid"] == 9900 and len(book["306154:2"]["bids"]) == 1)

# --- the consensus property: hash depends only on the SET, not input order ---
h1 = B.book_hash(orders)
shuffled = orders[:]; random.shuffle(shuffled)
h2 = B.book_hash(shuffled)
check("book_hash is order-set-independent (shuffle -> same hash)", h1 == h2, f"{h1[:12]} vs {h2[:12]}")
check("book_hash is stable across runs", B.book_hash(orders) == h1)

# changing any field changes the hash
mutated = [dict(x) for x in orders]; mutated[0]["price"] += 1
check("book_hash changes when an order changes", B.book_hash(mutated) != h1)

# empty book
check("empty orders -> empty book, stable hash", B.build_book([]) == {} and len(B.book_hash([])) == 64)

# summary shape
s = B.summary(orders)
check("summary has best_ask for the rune pair", s["306154:2"]["best_ask"] == 9800 and s["306154:2"]["depth"] == 4200)

# --- normalized prices (roadmap #5): ADDITIVE display fields, must NOT change the consensus hash ---
h_before = B.book_hash(orders)
nb = B.build_book(orders, divmap={"306154:2": 2})
lvl = nb["306154:2"]["asks"][0]
check("level carries unit_price (sats per base unit)", lvl["unit_price"] == lvl["price"] / lvl["amount"])
check("level carries norm_price with divmap (sats per whole rune)",
      lvl["norm_price"] == lvl["price"] * 100 / lvl["amount"])
check("normalization does NOT change book_hash (consensus untouched)", B.book_hash(orders) == h_before)
check("no divmap -> unit_price present but no norm_price",
      "unit_price" in B.build_book(orders)["306154:2"]["asks"][0]
      and "norm_price" not in B.build_book(orders)["306154:2"]["asks"][0])
check("pure helpers: whole_rune div 0 == unit_price", B.whole_rune_price_sats(200000, 1000, 0) == B.unit_price_sats(200000, 1000))

# --- Python<->Rust determinism boundaries (see BTX-security-audit-2026-05.md determinism pass) ---
# The canonical line is the ONLY thing book_hash/book_root commit to; it must equal the Rust
# `format!("{rune_id}|{side}|{price}|{amount}|{ann}|{txid}:{vout}\n")` (side=0) byte-for-byte even at the
# field-width maxima. Fixed-width LE parsing caps price/amount at u64, rune_block at u32, rune_tx at u16,
# so a Python bigint can never exceed the Rust value and decimal formatting is identical (no separators,
# no leading zeros). This locks that equivalence at the extremes.
MAXU64, MAXU32, MAXU16 = 2**64 - 1, 2**32 - 1, 2**16 - 1
omax = {"rune_id": f"{MAXU32}:{MAXU16}", "offer_txid": "ab" * 32, "offer_vout": MAXU32,
        "price": MAXU64, "amount": MAXU64, "announce_height": MAXU32, "side": 0}
exp_line = (f'{MAXU32}:{MAXU16}|0|{MAXU64}|{MAXU64}|{MAXU32}|{"ab"*32}:{MAXU32}\n').encode()
check("canonical line at u64/u32/u16 maxima == Rust format! string", B._canonical_line(B._norm(omax)) == exp_line)
check("u64 max decimal has no separators/leading zeros", str(MAXU64) == "18446744073709551615")

# book_root (the Merkle commitment) must ALSO be order-set-independent, exactly like book_hash.
r1 = B.book_root(orders)
rsh = orders[:]; random.shuffle(rsh)
check("book_root is order-set-independent (shuffle -> same root)", B.book_root(rsh) == r1, f"{r1[:12]} vs {B.book_root(rsh)[:12]}")
check("book_root changes when an order changes", B.book_root(mutated) != r1)
check("empty book_root is the 00*32 sentinel", B.book_root([]) == "00" * 32)
# side is pinned 0 in the commitment: a side=1 ('bid') order hashes the SAME as side=0 (Rust ignores side)
o_ask = o("306154:2", 10000, 1000, 120, "aa" * 32, side=0)
o_bid = o("306154:2", 10000, 1000, 120, "aa" * 32, side=1)
check("canonical commitment is side-independent (matches Rust hardcoded side=0)",
      B._canonical_line(B._norm(o_ask)) == B._canonical_line(B._norm(o_bid)))

# --- flat-hash delimiter-injection guard (BTX-security-audit-2026-05.md, Informational) ---
# The leaf/event encoding is delimiter-separated with no length prefix; a free-form rune_id/offer_txid
# could otherwise smuggle '|'/':'/'\n' to make ONE order serialize as TWO (a structural collision in the
# flat book_hash; book_root is immune). Chain data is always rune_id='<int>:<int>' + 64-hex txid, so the
# guard never fires in practice — but it must FAIL CLOSED on hostile/non-chain dicts.
P = {"rune_id":"1","price":2,"amount":3,"announce_height":4,"offer_txid":"aa","offer_vout":0}
Q = {"rune_id":"1","price":2,"amount":3,"announce_height":4,"offer_txid":"bb","offer_vout":0}
R = {"rune_id":"1","price":2,"amount":3,"announce_height":4,
     "offer_txid":"aa:0\n1|0|2|3|4|bb","offer_vout":0}  # smuggles a 2nd line into the txid
def _raises(fn):
    try: fn(); return False
    except ValueError: return True
check("book_hash rejects a short/non-hex offer_txid (was a collision vector)", _raises(lambda: B.book_hash([P,Q])))
check("book_hash rejects a delimiter-injecting offer_txid", _raises(lambda: B.book_hash([R])))
check("book_root rejects the same hostile inputs", _raises(lambda: B.book_root([R])))
check("cumulative_event_hash rejects delimiter injection",
      _raises(lambda: B.cumulative_event_hash([dict(R, status="cancelled", last_event_height=4)])))
check("rune_id with a pipe is rejected",
      _raises(lambda: B.book_hash([{"rune_id":"1|0|9","price":1,"amount":1,"announce_height":1,
                                    "offer_txid":"cc"*32,"offer_vout":0}])))
# chain-shaped inputs (numeric rune_id incl. '0:0' BTC bucket, 64-hex txid) still hash fine
check("chain-shaped orders still hash (no false positives)",
      len(B.book_hash([{"rune_id":"840000:1","price":1,"amount":1,"announce_height":1,"offer_txid":"ab"*32,"offer_vout":0},
                       {"rune_id":"0:0","price":1,"amount":1,"announce_height":1,"offer_txid":"cd"*32,"offer_vout":0}])) == 64)

print("ALL_PASS" if OK else "FAILURES ABOVE")
sys.exit(0 if OK else 1)
