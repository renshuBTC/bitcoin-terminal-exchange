#!/usr/bin/env python3
"""
btx_attest_endpoint_test — unit test for h_attest_challenge / h_attest_verify
in btxd.py. Runs purely in-process (no btxd process spawned, no HTTP), so it
is safe to wire into btx_xtest_suite.

Coverage:
  challenge: returns 64-char hex; two calls yield different values
  verify:    canonical simple-format vector PASSES
             canonical full-format vector PASSES
             tampered message → valid=False (NOT a 400 — the format
               is well-formed; only the sig binding fails)
             malformed inputs (wrong-type / oversized / wrong prefix /
               non-Taproot address) → 400 with informative error
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import btxd as D       # noqa: E402
import btx_bip322 as B  # noqa: E402


def _take(res):
    """h_attest_verify can return a dict OR (dict, code). Normalise."""
    if isinstance(res, tuple):
        return res[0], res[1]
    return res, 200


def main() -> int:
    failures = []

    # ---------- challenge ----------------------------------------------------
    c1 = D.h_attest_challenge()
    c2 = D.h_attest_challenge()
    if not (isinstance(c1, dict) and isinstance(c1.get("challenge_hex"), str)
            and len(c1["challenge_hex"]) == 64
            and all(ch in "0123456789abcdef" for ch in c1["challenge_hex"])):
        failures.append(f"challenge: bad shape {c1!r}")
    if c1.get("challenge_hex") == c2.get("challenge_hex"):
        failures.append("challenge: two consecutive calls returned the same nonce")

    # ---------- load canonical vectors --------------------------------------
    CANDIDATES = [
        os.path.join(
            os.path.dirname(HERE),
            "Bitcoin CoreX",
            "bitcoin-bips-reference",
            "bip-0322",
            "generated-test-vectors.json",
        ),
        "/mnt/c/Users/Ren Shu/Documents/Claude/Projects/Bitcoin CoreX/bitcoin-bips-reference/bip-0322/generated-test-vectors.json",
    ]
    gen_src = None
    for p in CANDIDATES:
        if os.path.isfile(p):
            gen_src = p
            break
    if gen_src is None:
        print("(SKIP canonical-vector phase: generated-test-vectors.json not found)")
    else:
        with open(gen_src) as f:
            gen = json.load(f)
        simple = [e for e in gen["simple"] if e.get("type") == "p2tr"][0]
        full = [e for e in gen["full"] if e.get("type") == "p2tr"][0]

        # ---------- simple format verify ------------------------------------
        body = {"address": simple["address"],
                "message": simple["message"],
                "signature": simple["bip322_signatures"][0]}
        obj, code = _take(D.h_attest_verify(body))
        if code != 200 or obj.get("valid") is not True or obj.get("format") != "simple":
            failures.append(f"verify simple canonical: {obj} (code {code})")

        # tampered message → valid:False but still 200
        body2 = dict(body); body2["message"] = body["message"] + "x"
        obj, code = _take(D.h_attest_verify(body2))
        if code != 200 or obj.get("valid") is not False:
            failures.append(f"verify tampered msg: expected valid=False got {obj}")

        # ---------- full format verify --------------------------------------
        bodyf = {"address": full["address"],
                 "message": full["message"],
                 "signature": full["bip322_signatures"][0]}
        obj, code = _take(D.h_attest_verify(bodyf))
        if code != 200 or obj.get("valid") is not True or obj.get("format") != "full":
            failures.append(f"verify full canonical: {obj} (code {code})")

    # ---------- malformed-input rejection (400) ------------------------------
    cases = [
        ("non-dict body",        "not a dict",                  400),
        ("missing address",      {"message": "x", "signature": "smpAQA="}, 400),
        ("address wrong type",   {"address": 123, "message": "x", "signature": "smpAQA="}, 400),
        ("address too long",     {"address": "bc1p" + "a" * 200,
                                  "message": "x", "signature": "smpAQA="}, 400),
        ("non-Taproot address",  {"address": "bc1q9vza2e8x573nczrlzms0wvx3gsqjx7vavgkx0l",
                                  "message": "x", "signature": "smpAQA="}, 400),
        ("message too large",    {"address": "bc1p" + "a" * 60,
                                  "message": "y" * 99999, "signature": "smpAQA="}, 400),
        ("signature too short",  {"address": "bc1p" + "a" * 60,
                                  "message": "x", "signature": "x"}, 400),
        ("unknown variant",      {"address": "bc1p" + "a" * 60,
                                  "message": "x", "signature": "xyzAQA="}, 400),
    ]
    for label, body, want_code in cases:
        try:
            obj, code = _take(D.h_attest_verify(body))
        except Exception as e:
            failures.append(f"{label}: handler raised {type(e).__name__}: {e}")
            continue
        if code != want_code:
            failures.append(f"{label}: expected HTTP {want_code}, got {code} body={obj}")

    if failures:
        for m in failures:
            print(f"  FAIL: {m}")
        print(f"✗ btx_attest_endpoint_test: {len(failures)} failure(s)")
        return 1
    print("✓ btx_attest_endpoint_test: all cases pass — endpoints behave correctly in-process")
    return 0


if __name__ == "__main__":
    sys.exit(main())
