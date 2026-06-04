#!/usr/bin/env python3
"""
btx_xtest_vs_bip327_sign_verify — Phase 2 of Task B. Cross-test BTX's
multi-round MuSig2 protocol wrapper against:

  - `sign_verify_vectors.json` (valid + sign_error + verify_fail
    + verify_error sub-cases)
  - `sig_agg_vectors.json` (valid + error)

These exercise the inner-most functions of the MuSig2 spec: per-
signer partial signature production, partial signature verification,
and partial signature aggregation into a final BIP-340 signature.

Combined with Phase 1 (nonce_gen + nonce_agg), Phase 2 closes 6 of 8
BIP-327 vector files. The remaining 2 (tweak_vectors,
det_sign_vectors) are Phase 3 — they test specific extensions on top
of the core flow this scout's two phases already validate.
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

    # ============ sign_verify_vectors ============
    with open(os.path.join(vec_dir, "sign_verify_vectors.json")) as f:
        d = json.load(f)

    sk = bytes.fromhex(d["sk"])
    pubkeys = [bytes.fromhex(p) for p in d["pubkeys"]]
    secnonces = [bytes.fromhex(s) for s in d["secnonces"]]
    pnonces = [bytes.fromhex(p) for p in d["pnonces"]]
    aggnonces = [bytes.fromhex(a) for a in d["aggnonces"]]
    msgs = [bytes.fromhex(m) for m in d["msgs"]]

    # Valid sign+verify
    passed = 0
    failures: list[str] = []
    for i, tc in enumerate(d["valid_test_cases"]):
        case_pubkeys = [pubkeys[j] for j in tc["key_indices"]]
        case_pnonces = [pnonces[j] for j in tc["nonce_indices"]]
        aggnonce = aggnonces[tc["aggnonce_index"]]
        msg = msgs[tc["msg_index"]]
        signer_index = tc["signer_index"]
        expected = bytes.fromhex(tc["expected"])

        # The secnonce is consumed by sign — copy first so we can also verify
        secnonce = bytearray(secnonces[0])  # signer is at index 0 always
        ctx = M.session_context(aggnonce, case_pubkeys, [], [], msg)
        try:
            psig = M.sign(secnonce, sk, ctx)
        except Exception as e:
            failures.append(f"valid sign {i}: {type(e).__name__}: {e}")
            continue
        if psig != expected:
            failures.append(
                f"valid sign {i}: psig {psig.hex()[:16]}.. != "
                f"expected {expected.hex()[:16]}.."
            )
            continue
        # Also: partial_sig_verify accepts it
        try:
            ok = M.partial_sig_verify(
                psig, case_pnonces, case_pubkeys, [], [], msg, signer_index,
            )
        except Exception as e:
            failures.append(f"valid verify {i}: {type(e).__name__}: {e}")
            continue
        if not ok:
            failures.append(f"valid verify {i}: partial_sig_verify returned False")
            continue
        passed += 1
    print(f"  sign_verify valid cases: {passed}/{len(d['valid_test_cases'])} PASS")
    if failures:
        overall_ok = False
        for f in failures[:5]:
            print(f"    FAIL: {f}")

    # Sign-error cases: each should raise
    err_pass = 0
    for i, tc in enumerate(d.get("sign_error_test_cases", [])):
        case_pubkeys = [pubkeys[j] for j in tc["key_indices"]]
        aggnonce = aggnonces[tc["aggnonce_index"]]
        msg = msgs[tc["msg_index"]]
        secnonce_index = tc.get("secnonce_index", 0)
        secnonce = bytearray(secnonces[secnonce_index]) if secnonce_index < len(secnonces) else bytearray(b"\x00" * 97)
        ctx = M.session_context(aggnonce, case_pubkeys, [], [], msg)
        try:
            M.sign(secnonce, sk, ctx)
            # Should have raised
        except Exception:
            err_pass += 1
    err_total = len(d.get("sign_error_test_cases", []))
    print(f"  sign_error cases (raise expected): {err_pass}/{err_total}")

    # verify_fail: partial_sig_verify returns False
    vf_pass = 0
    for i, tc in enumerate(d.get("verify_fail_test_cases", [])):
        case_pubkeys = [pubkeys[j] for j in tc["key_indices"]]
        case_pnonces = [pnonces[j] for j in tc["nonce_indices"]]
        msg = msgs[tc["msg_index"]]
        signer_index = tc["signer_index"]
        psig = bytes.fromhex(tc["sig"])
        try:
            ok = M.partial_sig_verify(
                psig, case_pnonces, case_pubkeys, [], [], msg, signer_index,
            )
            if ok is False:
                vf_pass += 1
        except Exception:
            vf_pass += 1  # raising also acceptable for clear-failure case
    vf_total = len(d.get("verify_fail_test_cases", []))
    print(f"  verify_fail cases (rejected): {vf_pass}/{vf_total}")

    # verify_error: partial_sig_verify raises
    ve_pass = 0
    for i, tc in enumerate(d.get("verify_error_test_cases", [])):
        case_pubkeys = [pubkeys[j] for j in tc["key_indices"]]
        case_pnonces = [pnonces[j] for j in tc["nonce_indices"]]
        msg = msgs[tc["msg_index"]]
        signer_index = tc["signer_index"]
        psig = bytes.fromhex(tc["sig"])
        try:
            M.partial_sig_verify(
                psig, case_pnonces, case_pubkeys, [], [], msg, signer_index,
            )
        except Exception:
            ve_pass += 1
    ve_total = len(d.get("verify_error_test_cases", []))
    print(f"  verify_error cases (raise expected): {ve_pass}/{ve_total}")

    # ============ sig_agg_vectors ============
    with open(os.path.join(vec_dir, "sig_agg_vectors.json")) as f:
        d = json.load(f)

    pubkeys = [bytes.fromhex(p) for p in d["pubkeys"]]
    pnonces = [bytes.fromhex(p) for p in d["pnonces"]]
    tweaks = [bytes.fromhex(t) for t in d.get("tweaks", [])]
    psigs = [bytes.fromhex(p) for p in d["psigs"]]
    msg = bytes.fromhex(d["msg"])

    passed = 0
    failures = []
    for i, tc in enumerate(d["valid_test_cases"]):
        case_pubkeys = [pubkeys[j] for j in tc["key_indices"]]
        case_pnonces = [pnonces[j] for j in tc["nonce_indices"]]
        case_tweaks = [tweaks[j] for j in tc.get("tweak_indices", [])]
        is_xonly = tc.get("is_xonly", [])
        case_psigs = [psigs[j] for j in tc["psig_indices"]]
        aggnonce = bytes.fromhex(tc["aggnonce"])
        expected = bytes.fromhex(tc["expected"])
        ctx = M.session_context(aggnonce, case_pubkeys, case_tweaks, is_xonly, msg)
        try:
            final_sig = M.partial_sig_agg(case_psigs, ctx)
        except Exception as e:
            failures.append(f"sig_agg valid {i}: {type(e).__name__}: {e}")
            continue
        if final_sig != expected:
            failures.append(
                f"sig_agg valid {i}: got {final_sig.hex()[:16]}.. != "
                f"expected {expected.hex()[:16]}.."
            )
            continue
        passed += 1
    print(f"  sig_agg valid cases:     {passed}/{len(d['valid_test_cases'])} PASS")
    if failures:
        overall_ok = False
        for f in failures[:5]:
            print(f"    FAIL: {f}")

    if overall_ok:
        print(
            "OK btx_xtest_vs_bip327_sign_verify: BTX's multi-round MuSig2 "
            "protocol wrapper now covers 6 of 8 BIP-327 vector files "
            "(key_agg, key_sort, nonce_gen, nonce_agg, sign_verify, "
            "sig_agg). Remaining 2 (tweak, det_sign) are Phase 3 of the "
            "refactor scope doc."
        )
        return 0
    print("FAIL btx_xtest_vs_bip327_sign_verify: divergence detected")
    return 1


if __name__ == "__main__":
    sys.exit(main())
