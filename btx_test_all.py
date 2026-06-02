#!/usr/bin/env python3
"""btx_test_all.py — run every OFFLINE BTX test suite with one command. No node required.

Subprocess-runs each test and reports pass/fail by exit code (each suite sys.exit(0) on success,
non-zero on failure). Use before any change touching the protocol/crypto/funding paths.

    python3 btx_test_all.py
"""
import sys, os, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))

# (label, argv after the python interpreter) — all offline, no bitcoind/ord needed
SUITES = [
    ("encoder + rune-name validation (round-trip + ord vectors)", ["btx_etch.py", "selftest"]),
    ("aggregate offline selftest",                            ["btx_selftest.py"]),
    ("wallet plumbing (simulate)",                            ["btx_wallet.py", "simulate"]),
    ("addressed-swap maker gate",                             ["btx_addressed_test.py"]),
    ("signet etch control-flow",                              ["btx_etch_signet_test.py"]),
    ("funding selection (taproot regression)",                ["btx_funding_test.py"]),
    ("deterministic order book + consensus hash",             ["btx_orderbook_test.py"]),
    ("batch fill (SINGLE|ACP pre-sig at index k>0)",           ["btx_batch_test.py"]),
    ("rune<->rune addressed swap + Runes allocator",           ["btx_rune_swap_test.py"]),
    ("property fuzz (decoder/allocator/hash invariants)",      ["btx_fuzz.py"]),
    ("runes decoder cross-check (vs Magic Eden runestone-lib)", ["btx_runes_xcheck.py"]),
    ("cumulative event hash (announce/fill/cancel stream)",      ["btx_eventhash_test.py"]),
    ("light-client follower (independent fold + checkpoint guard)", ["btx_light_client.py", "--selftest"]),
    ("cross-impl extraction corpus (Python side vs Rust golden)", ["btx_xcheck.py"]),
    ("Schnorr half-aggregation (BTX1 multi-maker artifact compression)", ["btx_halfagg.py"]),
    ("Schnorr adaptor signatures (BTX2 conditional / oracle-attested orders)", ["btx_adaptor.py"]),
]


def run(argv):
    script = os.path.join(HERE, argv[0])
    if not os.path.isfile(script):
        return None, f"missing: {argv[0]}"
    p = subprocess.run([sys.executable, script, *argv[1:]], capture_output=True, text=True)
    tail = (p.stdout or "").strip().splitlines()
    tail += (p.stderr or "").strip().splitlines()
    return p.returncode == 0, (tail[-1] if tail else "(no output)")


def main():
    print("BTX offline test suite\n" + "-" * 40)
    results = []
    for label, argv in SUITES:
        ok, last = run(argv)
        results.append(ok)
        mark = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
        print(f"  [{mark}] {label}" + ("" if ok else f"  — {last}"))
    passed = sum(1 for r in results if r)
    total = len(results)
    print("-" * 40)
    print(f"{passed}/{total} suites passed" + ("  — ALL GREEN" if passed == total else ""))
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
