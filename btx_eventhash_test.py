#!/usr/bin/env python3
"""btx_eventhash_test.py — offline tests for the cumulative event hash (announce/fill/cancel stream).

The cumulative event hash is a rolling commitment a light client folds to FOLLOW the reconstructed book
incrementally and detect reorg/omission (BTX-book-commitment-design.md open question #1). Like
`book_root` it is a PURE function of the order record set, so it must be byte-for-byte identical in the
Python reference (`btx_orderbook`) and the Rust indexer (`btx.rs`). This file is that golden anchor:
the GOLDEN below is the exact value the Rust `cumulative_event_hash` golden test must reproduce.

Run:  python3 btx_eventhash_test.py
"""
import sys
import btx_orderbook as ob

# A deterministic 3-order record set exercising every event kind:
#   - order1: OPEN  -> only an ANNOUNCE (height 100)
#   - order2: FILLED -> ANNOUNCE (101) + FILL (105), announce and fill in DIFFERENT blocks
#   - order3: CANCELLED at its announce height -> ANNOUNCE (103) + CANCEL (103) in the SAME block
#             (proves the per-block event sort + code tiebreak are deterministic)
RECORDS = [
    {"rune_id": "840000:1", "offer_txid": "aa" * 32, "offer_vout": 0, "price": 100000, "amount": 5,
     "announce_height": 100, "status": "open", "last_event_height": 100},
    {"rune_id": "840000:1", "offer_txid": "bb" * 32, "offer_vout": 1, "price": 250000, "amount": 3,
     "announce_height": 101, "status": "filled", "last_event_height": 105},
    {"rune_id": "840500:9", "offer_txid": "cc" * 32, "offer_vout": 2, "price": 777, "amount": 1,
     "announce_height": 103, "status": "cancelled", "last_event_height": 103},
]

# Frozen goldens (must match the Rust btx.rs golden test byte-for-byte).
GOLDEN_BLOCKS = [
    (100, "1d86d47bdd69aadc0af2a602c7623cd0a83f54664b4160cd8a5db68986e8f451"),
    (101, "5e99fece8e4e0af5d6afb486acafb18afd8e458560b7863f68201b3c2d775ee6"),
    (103, "47df3d30306fdb34375c5cfe5ce4024129beedcb376ee653eda0eab485d480d5"),
    (105, "280f90991f5ffaceeeb7a0a41985471fd3be505fd284c6fa15b839bdf0fe1322"),
]
GOLDEN_CUM = "0716e1c48e823dfc8f03cf8d5b8bb30f5a91fbf0622943c1553537203a02141e"
EMPTY_CUM = "00" * 32


def main():
    ok = True

    blocks = ob.event_block_hashes(RECORDS)
    if blocks != GOLDEN_BLOCKS:
        print(f"  [FAIL] per-block event hashes drifted\n    got={blocks}\n    exp={GOLDEN_BLOCKS}")
        ok = False

    cum = ob.cumulative_event_hash(RECORDS)
    if cum != GOLDEN_CUM:
        print(f"  [FAIL] cumulative_event_hash BTX={cum} golden={GOLDEN_CUM}")
        ok = False

    # Order-set-independence: any input/iteration order must yield the identical commitment.
    import random
    for seed in range(8):
        r = RECORDS[:]
        random.seed(seed)
        random.shuffle(r)
        if ob.cumulative_event_hash(r) != GOLDEN_CUM:
            print(f"  [FAIL] cumulative not order-independent (seed {seed})")
            ok = False
            break

    # Empty stream -> fixed sentinel.
    if ob.cumulative_event_hash([]) != EMPTY_CUM:
        print(f"  [FAIL] empty cumulative {ob.cumulative_event_hash([])} != {EMPTY_CUM}")
        ok = False

    # Incremental-follow property: a client that has folded up to block H reaches the same value as a
    # full recompute when it folds the remaining blocks (the whole point of a cumulative commitment).
    import hashlib
    cum_b = ob._CUM_GENESIS
    for h, bh in GOLDEN_BLOCKS:
        cum_b = hashlib.sha256(ob._CUM_TAG + cum_b + int(h).to_bytes(4, "big") + bytes.fromhex(bh)).digest()
    if cum_b.hex() != GOLDEN_CUM:
        print(f"  [FAIL] incremental fold {cum_b.hex()} != {GOLDEN_CUM}")
        ok = False

    # Omission is detectable: dropping any single order changes the cumulative.
    for i in range(len(RECORDS)):
        dropped = RECORDS[:i] + RECORDS[i + 1:]
        if ob.cumulative_event_hash(dropped) == GOLDEN_CUM:
            print(f"  [FAIL] dropping order {i} did NOT change the cumulative (omission undetectable)")
            ok = False

    # Event STREAM (incremental light-client following): per-block (height, block_hash) match the goldens,
    # the running cumulative ends at GOLDEN_CUM, and it equals the Rust event_stream_from_views golden.
    stream = ob.event_stream(RECORDS)
    if [(h, bh) for (h, bh, _cum) in stream] != GOLDEN_BLOCKS:
        print(f"  [FAIL] event_stream per-block (height, hash) != GOLDEN_BLOCKS")
        ok = False
    if not stream or stream[-1][2] != GOLDEN_CUM:
        print(f"  [FAIL] event_stream final cumulative != {GOLDEN_CUM}")
        ok = False
    if ob.event_stream([]) != []:
        print("  [FAIL] empty event_stream is not empty")
        ok = False

    print(f"cumulative event hash: golden + order-independence + omission-detection all hold ({GOLDEN_CUM[:12]}…)"
          if ok else "CUMULATIVE EVENT HASH TEST FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
