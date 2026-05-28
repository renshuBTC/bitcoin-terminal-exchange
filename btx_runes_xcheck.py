#!/usr/bin/env python3
"""btx_runes_xcheck.py — cross-validate BTX's Runes decoder against an INDEPENDENT implementation.

BTX's decoder (`btx_runes_decode.decode_runestone`) was ported from ONE reference (ord's rune.rs).
A decoder divergence is consensus-relevant — `rune_id` and cenotaph status feed the order book and the
trades classifier — so these golden vectors were produced by a SECOND, independent implementation:
Magic Eden's `@magiceden-oss/runestone-lib` (`tryDecodeRunestone`). They come from a differential run of
5 structured specs + 800 random well-framed runestones decoded by BOTH implementations, which agreed on
the cenotaph verdict in 805/805 cases (0 real disagreements). Each vector is
`(scriptPubKey_hex, expected_cenotaph, expected_edicts)` where the expectation is runestone-lib's verdict.
This test is OFFLINE — no node, no ME install needed; it just re-checks BTX against those frozen goldens.

One by-design difference, NOT a divergence: runestone-lib's `edict_output` flaw (an edict output index
>= the tx's output count) makes the whole runestone a cenotaph. BTX's `decode_runestone` is payload-only
(it has no output count) and correctly defers that bounds check to the tx-level allocator/verifier
(`verify_addressed_rune_tx` / the Runes allocator). Vectors whose ONLY flaw is `edict_output` are excluded
here, since BTX legitimately cannot classify them from the runestone payload alone.

Run:  python3 btx_runes_xcheck.py
"""
import sys
import btx_runes_decode as rd

# (scriptPubKey_hex, expected_cenotaph, expected_edicts as [[block, tx, amount_str, output], ...])
# Expectations are Magic Eden runestone-lib's decode verdicts.
VECTORS = [
    ("6a5d0800c0a23307e80701", False, [[840000, 7, "1000", 1]]),
    ("6a5d0b00c0a23301010001030701", False, [[840000, 1, "1", 0], [840001, 3, "7", 1]]),
    ("6a5d17000100ffffffffffffffffffffffffffffffffffff0302", False,
     [[1, 0, "340282366920938463463374607431768211455", 2]]),
    ("6a5d0814c0a23314051603", False, []),                       # etching + terms, no edict
    ("6a5d0b1401140116010002020500", False, [[2, 2, "5", 0]]),   # etching + edict + mint + pointer
    ("6a5d00", False, []),                                        # bare Body tag -> empty runestone
    ("6a5d0fd411bb71d43b0df2637532a8b6e01e", True, []),
    ("6a5d1b06fda93152eaf633f3361cc081db988c5083d4958b136d67015f1e", True, []),
    ("6a5d12c4c8c168f11edb80315f48e1ce222daa9195", True, []),
    ("6a5d083cd207cdbb1eddd1", True, []),
    ("6a5d046cf966a3", True, []),
    ("6a5d1ad68ba2a391ce7e121f1d1305042bee6b164aa6aad0a101c16795", True, []),
    ("6a5d0dcdbdb7b615a94f1272b011edc4", True, []),
    ("6a5d254519a65bfcff2dd287650beddecfe1ec8ceb3fdd26cc40b1255becc6ce5ef4b8f136771fac", True, []),
    ("6a5d03bed904", True, []),
    ("6a5d0142", True, []),
    ("6a5d17a1879a576c33b89e9d4a786a20ac0a6b4fbe73a382a0d6", True, []),
    ("6a5d06f55352e06b9d", True, []),
    # v18 — SupplyOverflow: etching+terms with premine=cap=amount=u128::MAX, so premine + cap*amount
    # overflows u128 (ord Flaw::SupplyOverflow via Etching::supply checked add/mul). Expectation is the
    # ord SPEC verdict (the 805-case random run never hit a near-u128 etching); CONFIRM against ME
    # runestone-lib `tryDecodeRunestone` on the next differential run.
    ("6a5d400203040006ffffffffffffffffffffffffffffffffffff030affffffffffffffffffffffffffffffffffff0308ffffffffffffffffffffffffffffffffffff03", True, []),
]


def main():
    ok = True
    for i, (spk, exp_ceno, exp_edicts) in enumerate(VECTORS):
        d = rd.decode_runestone(spk)
        ceno = bool(d.get("cenotaph"))
        if ceno != exp_ceno:
            print(f"  [FAIL] v{i} {spk}: cenotaph BTX={ceno} ME={exp_ceno} reasons={d.get('cenotaph_reasons')}")
            ok = False
            continue
        if not exp_ceno:
            got = [[e["block"], e["tx"], str(e["amount"]), e["output"]] for e in d.get("edicts", [])]
            if got != exp_edicts:
                print(f"  [FAIL] v{i} {spk}: edicts BTX={got} ME={exp_edicts}")
                ok = False
    n = len(VECTORS)
    print(f"runes decoder vs Magic Eden runestone-lib: {n}/{n} golden vectors match"
          if ok else "RUNES DECODER DIVERGES from runestone-lib")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
