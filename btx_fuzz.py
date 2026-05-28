#!/usr/bin/env python3
"""btx_fuzz.py — property / robustness fuzzing of BTX's security-critical pure functions.

Institutionalizes the audit: instead of one-off eyeballing, assert INVARIANTS over many random inputs.
Pure (no node). Deterministic by default (fixed seed) so it's a repeatable regression gate; crank up
coverage with BTX_FUZZ_ITERS=200000 for a deeper sweep.

Campaigns (each a property a malicious input must never break):
  1. Runestone decoder robustness — `decode_runestone` must NEVER raise on arbitrary bytes (a panic on
     attacker-crafted chain data would be an indexer DoS); it must always return a dict.
  2. Runes allocator conservation — `allocate_runes` must never create runes (sum allocated <= input),
     never produce a negative amount, and be deterministic (same input -> same output).
  3. Book-hash consensus property — `book_hash` must be order-SET-independent (shuffling the input
     yields the same digest) and stable across calls. This is what lets two indexers prove agreement.

Run:  python3 btx_fuzz.py            # quick gate (deterministic)
      BTX_FUZZ_ITERS=200000 python3 btx_fuzz.py
"""
import os
import random
import sys

import btx_runes_decode as rd
import btx_rune_swap as RS
import btx_orderbook as OB
import btx_0b as btx
import btx_runes as runes
import btx_wallet as W
import bitcoin

bitcoin.SelectParams("regtest")

ITERS = int(os.environ.get("BTX_FUZZ_ITERS", "8000"))
SEED = int(os.environ.get("BTX_FUZZ_SEED", "1234"))


def fuzz_decoder_robustness(n):
    """Arbitrary OP_RETURN OP_13 payloads must decode without ever raising."""
    rng = random.Random(SEED)
    for _ in range(n):
        body = bytes(rng.randint(0, 255) for _ in range(rng.randint(0, 48)))
        spk = bytes([0x6A, 0x5D]) + body
        d = rd.decode_runestone(spk.hex())  # must not raise
        assert isinstance(d, dict), f"decode returned non-dict for {spk.hex()}"
    return n


def fuzz_allocator_conservation(n):
    """`allocate_runes` never creates runes, never goes negative, and is deterministic."""
    rng = random.Random(SEED + 1)
    for _ in range(n):
        nout = rng.randint(1, 5)
        op_idx = set(rng.sample(range(nout), k=rng.randint(0, min(2, nout))))
        ids = [f"{rng.randint(0, 5)}:{rng.randint(0, 5)}" for _ in range(rng.randint(1, 3))]
        inp = {i: rng.randint(0, 10_000) for i in ids}
        edicts = [{"id": rng.choice(ids), "amount": rng.randint(0, 12_000),
                   "output": rng.randint(0, nout + 1)} for _ in range(rng.randint(0, 6))]
        ptr = rng.choice([None] + list(range(nout + 1)))
        a1 = RS.allocate_runes(edicts, dict(inp), nout, op_idx, ptr)
        a2 = RS.allocate_runes(edicts, dict(inp), nout, op_idx, ptr)
        assert a1 == a2, f"non-deterministic allocation: {edicts} {inp}"
        for rune, total in inp.items():
            got = sum(o.get(rune, 0) for o in a1.values())
            assert 0 <= got <= total, f"conservation broken: {rune} got {got} of {total} | {edicts} {inp}"
        for o in a1.values():
            for amt in o.values():
                assert amt >= 0, f"negative allocation {o}"
    return n


def fuzz_book_hash_order_independence(n):
    """`book_hash` depends only on the order SET, not input order; and is stable."""
    rng = random.Random(SEED + 2)
    runes = ["0:0", "840000:7", "131:1", "9999999:65535"]
    for _ in range(n):
        orders = [{"rune_id": rng.choice(runes),
                   "offer_txid": "%064x" % rng.randint(0, 2 ** 256 - 1),
                   "offer_vout": rng.randint(0, 4),
                   "price": rng.randint(0, 10 ** 9),
                   "amount": rng.randint(0, 10 ** 6),
                   "announce_height": rng.randint(0, 900_000)}
                  for _ in range(rng.randint(0, 6))]
        h = OB.book_hash(orders)
        shuffled = orders[:]
        rng.shuffle(shuffled)
        assert OB.book_hash(shuffled) == h, f"book_hash not order-independent: {orders}"
        assert OB.book_hash(orders) == h, "book_hash not stable"
    return n


def fuzz_artifact_roundtrip(n):
    """A BTX artifact must survive serialize -> parse unchanged (parser/serializer symmetry)."""
    rng = random.Random(SEED + 3)
    for _ in range(n):
        art = W.assemble_artifact(
            "aa" * 32, rng.randint(0, 9), rng.randint(546, 10 ** 12),
            bytes([0x00, 0x14] + [rng.randint(0, 255) for _ in range(20)]),
            bytes([0x02] + [rng.randint(0, 255) for _ in range(32)]),
            bytes([0x30, 0x44] + [rng.randint(0, 255) for _ in range(68)] + [0x83]),
            group_id=rng.randint(0, 2 ** 40), amount_units=rng.randint(0, 10 ** 12),
            rune_block=rng.randint(0, 2 ** 31), rune_tx=rng.randint(0, 2 ** 15))
        p = btx.parse_artifact(btx.serialize_artifact(art))
        for k in ("price", "amount", "offer_vout", "rune_block", "rune_tx", "group_id", "sighash_flag"):
            assert int(p[k]) == int(art[k]), f"artifact field {k} changed: {art[k]} -> {p[k]}"
        assert p["payout_spk"] == art["payout_spk"] and p["maker_pubkey"] == art["maker_pubkey"] \
            and p["maker_sig"] == art["maker_sig"], "artifact bytes field changed across round-trip"
    return n


def fuzz_swap_builder_invariants(n):
    """The fill builder must conserve value (inputs - outputs == fee), preserve output 0 = the maker's
    committed (price, payout_spk), RBF-signal the funding input, and reject sub-dust taker output."""
    rng = random.Random(SEED + 4)
    for _ in range(n):
        price = rng.randint(546, 10 ** 8)
        art = {"offer_txid": b"\xaa" * 32, "offer_vout": 0, "price": price,
               "payout_spk": bytes([0x00, 0x14] + [0xBB] * 20), "amount": rng.randint(1, 10 ** 6),
               "rune_block": rng.choice([0, 840000]), "rune_tx": rng.choice([0, 7])}
        offer = rng.randint(546, 10 ** 8); fund = rng.randint(0, 10 ** 8); fee = rng.randint(1, 50_000)
        taker_value = offer + fund - price - fee
        try:
            tx = W.build_taker_swap_unsigned(art, offer, "bb" * 32, 1, fund,
                                             bytes([0x00, 0x14] + [0xCC] * 20), fee=fee)
            assert taker_value >= 546, f"sub-dust taker output {taker_value} was not rejected"
            outsum = sum(o.nValue for o in tx.vout)
            assert (offer + fund) - outsum == fee, f"value not conserved: in {offer+fund} out {outsum} fee {fee}"
            assert tx.vout[0].nValue == price and bytes(tx.vout[0].scriptPubKey) == art["payout_spk"], \
                "output 0 != maker committed (price, payout_spk)"
            assert tx.vin[1].nSequence == 0xFFFFFFFD, f"funding input not RBF-signaled ({tx.vin[1].nSequence:#x})"
        except ValueError:
            assert taker_value < 546, f"builder raised for a non-dust taker output {taker_value}"
    return n


def fuzz_runestone_roundtrip(n):
    """Sorted, in-range edicts must survive runestone_spk -> decode_runestone unchanged and NOT be
    flagged a cenotaph (guards the encoder/decoder symmetry that the delta-vs-absolute bug broke)."""
    rng = random.Random(SEED + 5)
    for _ in range(n):
        ids = sorted({(rng.randint(1, 5000), rng.randint(0, 5000)) for _ in range(rng.randint(1, 3))})
        edicts = [(b, t, rng.randint(0, 10 ** 9), rng.randint(0, 3)) for (b, t) in ids]
        d = rd.decode_runestone(bytes(runes.runestone_spk(edicts)).hex())
        assert not d.get("cenotaph"), f"clean edicts flagged cenotaph: {edicts} {d.get('cenotaph_reasons')}"
        got = [(e["block"], e["tx"], e["amount"], e["output"]) for e in d["edicts"]]
        assert got == edicts, f"runestone round-trip mismatch: {edicts} -> {got}"
    return n


CAMPAIGNS = [
    ("decoder robustness (no panic on arbitrary bytes)", fuzz_decoder_robustness),
    ("allocator conservation + determinism", fuzz_allocator_conservation),
    ("book_hash order-set-independence + stability", fuzz_book_hash_order_independence),
    ("artifact serialize<->parse round-trip", fuzz_artifact_roundtrip),
    ("swap-builder value conservation / output-0 commitment / RBF / dust", fuzz_swap_builder_invariants),
    ("runestone encode<->decode round-trip", fuzz_runestone_roundtrip),
]


def main():
    print(f"BTX property-fuzz ({ITERS} iters/campaign, seed {SEED})\n" + "-" * 48)
    ok = True
    for label, fn in CAMPAIGNS:
        try:
            ran = fn(ITERS)
            print(f"  [PASS] {label} — {ran} cases")
        except AssertionError as e:
            ok = False
            print(f"  [FAIL] {label}\n         {e}")
    print("-" * 48)
    print("ALL CLEAN" if ok else "FUZZ FOUND A VIOLATION")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
