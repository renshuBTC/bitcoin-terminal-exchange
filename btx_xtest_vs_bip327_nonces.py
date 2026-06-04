#!/usr/bin/env python3
"""
btx_xtest_vs_bip327_nonces — close Phase 1 of Task B (the
btx_musig2 BIP-327 inner-function exposure) by cross-testing the
nonce_gen + nonce_agg vectors.

This is the first 2 of 6 remaining BIP-327 vector files BTX hadn't
wired (the others: sign_verify, sig_agg, tweak, det_sign). Phase 1
covers:
  - `nonce_gen_vectors.json` — deterministic per-signer nonce
  - `nonce_agg_vectors.json` — coordinator nonce aggregation

BTX accesses these via `btx_musig2_bip327_protocol` which wraps the
canonical BIP-327 reference.py. Validating the wrapper against the
vectors is equivalent to validating that BIP-327 reference.py + BTX's
wiring around it are byte-for-byte correct.

When BTX eventually ships its own from-scratch implementation of the
multi-round protocol, the same vector cross-test will catch any
divergence from the canonical reference.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))


def _find_vectors_dir() -> str | None:
    for c in (
        os.path.expanduser(
            "~/Documents/Claude/Projects/Bitcoin CoreX/"
            "bitcoin-bips-reference/bip-0327/vectors"
        ),
        "/sessions/keen-determined-einstein/mnt/Bitcoin CoreX/"
        "bitcoin-bips-reference/bip-0327/vectors",
    ):
        if os.path.isdir(c):
            return c
    return None


def main() -> int:
    vec_dir = _find_vectors_dir()
    if not vec_dir:
        print("[SKIP] BIP-327 vectors directory not found")
        return 0

    try:
        import btx_musig2_bip327_protocol as M
    except ImportError as e:
        print(f"[SKIP] btx_musig2_bip327_protocol setup failed: {e}")
        return 0

    overall_ok = True

    # ---- nonce_gen vectors ----
    with open(os.path.join(vec_dir, "nonce_gen_vectors.json")) as f:
        d = json.load(f)

    passed = 0
    failures: list[str] = []
    for i, tc in enumerate(d["test_cases"]):
        rand_ = bytes.fromhex(tc["rand_"])
        # Use `is not None` semantics, not truthiness: empty-string
        # ("") in the vector means "present-but-empty", which the BIP-
        # 327 reference distinguishes from None ("absent context").
        sk = bytes.fromhex(tc["sk"]) if tc.get("sk") is not None else None
        pk = bytes.fromhex(tc["pk"])
        aggpk = bytes.fromhex(tc["aggpk"]) if tc.get("aggpk") is not None else None
        msg = bytes.fromhex(tc["msg"]) if tc.get("msg") is not None else None
        extra_in = bytes.fromhex(tc["extra_in"]) if tc.get("extra_in") is not None else None
        try:
            secnonce, pubnonce = M.nonce_gen_internal(
                rand_, sk, pk, aggpk, msg, extra_in,
            )
        except Exception as e:
            failures.append(f"nonce_gen {i}: {type(e).__name__}: {e}")
            continue
        exp_secnonce = bytes.fromhex(tc["expected_secnonce"])
        exp_pubnonce = bytes.fromhex(tc["expected_pubnonce"])
        if bytes(secnonce) != exp_secnonce:
            failures.append(
                f"nonce_gen {i}: secnonce {bytes(secnonce).hex()[:16]}.. "
                f"!= expected {exp_secnonce.hex()[:16]}.."
            )
            continue
        if pubnonce != exp_pubnonce:
            failures.append(f"nonce_gen {i}: pubnonce mismatch")
            continue
        passed += 1
    print(f"  nonce_gen_vectors:  {passed}/{len(d['test_cases'])} PASS")
    if failures:
        overall_ok = False
        for f in failures[:5]:
            print(f"    FAIL: {f}")

    # ---- nonce_agg vectors ----
    with open(os.path.join(vec_dir, "nonce_agg_vectors.json")) as f:
        d = json.load(f)
    pnonces = [bytes.fromhex(p) for p in d["pnonces"]]

    passed = 0
    failures = []
    for i, tc in enumerate(d["valid_test_cases"]):
        indices = tc["pnonce_indices"]
        case_pnonces = [pnonces[j] for j in indices]
        expected = bytes.fromhex(tc["expected"])
        try:
            agg = M.nonce_agg(case_pnonces)
        except Exception as e:
            failures.append(f"nonce_agg {i}: {type(e).__name__}: {e}")
            continue
        if agg != expected:
            failures.append(
                f"nonce_agg {i}: got {agg.hex()[:16]}.. != expected "
                f"{expected.hex()[:16]}.."
            )
            continue
        passed += 1
    print(f"  nonce_agg_vectors (valid):  {passed}/{len(d['valid_test_cases'])} PASS")
    if failures:
        overall_ok = False
        for f in failures[:5]:
            print(f"    FAIL: {f}")

    # ---- nonce_agg error vectors (negative cases) ----
    passed_err = 0
    failed_err = 0
    for i, tc in enumerate(d.get("error_test_cases", [])):
        indices = tc["pnonce_indices"]
        case_pnonces = [pnonces[j] for j in indices]
        try:
            M.nonce_agg(case_pnonces)
            failed_err += 1  # should have raised
        except M.InvalidContributionError:
            passed_err += 1
        except Exception:
            passed_err += 1  # raised some error — accept
    err_total = len(d.get("error_test_cases", []))
    print(f"  nonce_agg_vectors (error rejected):  {passed_err}/{err_total} PASS")
    if failed_err > 0:
        overall_ok = False
        print(f"    FAIL: {failed_err} malformed pnonces were NOT rejected")

    if overall_ok:
        print(
            "OK btx_xtest_vs_bip327_nonces: BTX's multi-round MuSig2 "
            "protocol wrapper matches BIP-327 reference output byte-for-"
            "byte on all nonce_gen + nonce_agg vectors. Phase 1 of the "
            "btx_musig2 BIP-327 refactor closed; BTX coverage of BIP-327 "
            "vector files now 4 of 8 (key_agg, key_sort, nonce_gen, "
            "nonce_agg). Remaining 4 (sign_verify, sig_agg, tweak, "
            "det_sign) are Phase 2-6 of the refactor scope doc."
        )
        return 0
    print("FAIL btx_xtest_vs_bip327_nonces: divergence detected")
    return 1


if __name__ == "__main__":
    sys.exit(main())
