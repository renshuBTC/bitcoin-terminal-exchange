#!/usr/bin/env python3
"""
btx_bip374_xtest.py — Cross-test BTX's BIP-374 DLEQ port against the
canonical test vectors at `bitcoin/bips/bip-0374/`.

Exercises two CSV files:
  - test_vectors_generate_proof.csv: produce a proof from (G, a, B, r, m),
    compare to expected 64-byte proof bytes
  - test_vectors_verify_proof.csv: run verify on (G, A, B, C, proof, m),
    compare to expected TRUE/FALSE

A canonical-compliance pass requires BOTH:
  - Every generate vector with a non-empty `result_proof` produces the
    exact expected bytes (byte-equality)
  - Every verify vector returns the expected boolean
"""

from __future__ import annotations
import csv
import os
import sys


BIP374_DIR = "/mnt/c/Users/Ren Shu/Documents/Claude/Projects/Bitcoin CoreX/bitcoin-bips-reference/bip-0374"
if not os.path.isdir(BIP374_DIR):
    BIP374_DIR = "/sessions/keen-determined-einstein/mnt/Bitcoin CoreX/bitcoin-bips-reference/bip-0374"


def main():
    import btx_dleq as dleq

    # --- Generate vectors ---
    gen_path = os.path.join(BIP374_DIR, "test_vectors_generate_proof.csv")
    with open(gen_path) as f:
        gen_rows = list(csv.DictReader(f))

    print(f"=== BIP-374 cross-test ===")
    print(f"Generate vectors: {len(gen_rows)}")

    gen_pass = gen_fail = gen_skip = 0
    failures = []

    for row in gen_rows:
        idx = int(row["index"])
        G_hex = row["point_G"].strip()
        a_hex = row["scalar_a"].strip()
        B_hex = row["point_B"].strip()
        r_hex = row["auxrand_r"].strip()
        m_hex = row["message"].strip()
        expected_proof_hex = row["result_proof"].strip()
        comment = row.get("comment", "").strip()

        # Expected outcome: the canonical CSV uses sentinel strings for
        # failure cases. result_proof = "INVALID" means generate must
        # return None; point_B = "INFINITY" represents the point at
        # infinity (also a failure-mode input).
        should_fail = (not expected_proof_hex) or expected_proof_hex.upper() == "INVALID"

        try:
            GEN = dleq._parse_compressed(bytes.fromhex(G_hex))
            a = int(a_hex, 16)
            if B_hex.upper() == "INFINITY":
                B_pt = None
            else:
                B_pt = dleq._parse_compressed(bytes.fromhex(B_hex))
            r = bytes.fromhex(r_hex)
            m = bytes.fromhex(m_hex) if m_hex else None

            produced = dleq.generate_proof(a, B_pt, r, GEN=GEN, m=m)

            if should_fail:
                if produced is None:
                    gen_pass += 1
                else:
                    gen_fail += 1
                    failures.append((idx, comment, f"expected None, got {produced.hex()[:20]}..."))
            else:
                expected = bytes.fromhex(expected_proof_hex)
                if produced == expected:
                    gen_pass += 1
                else:
                    gen_fail += 1
                    got_disp = produced.hex()[:20] + "..." if produced else "None"
                    failures.append((idx, comment, f"got {got_disp}, want {expected_proof_hex[:20]}..."))
        except Exception as e:
            # Parse exception on a failure-case vector → PASS
            # (the input was deliberately malformed for the negative test)
            if should_fail:
                gen_pass += 1
            else:
                gen_fail += 1
                failures.append((idx, comment, f"raised {type(e).__name__}: {e}"))

    print(f"  generate byte-match: {gen_pass}/{gen_pass + gen_fail}")
    if failures:
        for idx, comment, msg in failures[:8]:
            print(f"    [#{idx}] {comment} — {msg}")

    # --- Verify vectors ---
    ver_path = os.path.join(BIP374_DIR, "test_vectors_verify_proof.csv")
    with open(ver_path) as f:
        ver_rows = list(csv.DictReader(f))

    print(f"\nVerify vectors: {len(ver_rows)}")
    ver_pass = ver_fail = 0
    ver_failures = []

    for row in ver_rows:
        idx = int(row["index"])
        G_hex = row["point_G"].strip()
        A_hex = row["point_A"].strip()
        B_hex = row["point_B"].strip()
        C_hex = row["point_C"].strip()
        proof_hex = row["proof"].strip()
        m_hex = row["message"].strip()
        expected = row["result_success"].strip() == "TRUE"
        comment = row.get("comment", "").strip()

        try:
            GEN = dleq._parse_compressed(bytes.fromhex(G_hex))
            A_pt = dleq._parse_compressed(bytes.fromhex(A_hex))
            B_pt = dleq._parse_compressed(bytes.fromhex(B_hex))
            C_pt = dleq._parse_compressed(bytes.fromhex(C_hex))
            proof = bytes.fromhex(proof_hex)
            m = bytes.fromhex(m_hex) if m_hex else None
            actual = dleq.verify_proof(A_pt, B_pt, C_pt, proof, GEN=GEN, m=m)
        except Exception:
            # If parsing the inputs raises and expected==FALSE, that's a pass
            actual = False

        if actual == expected:
            ver_pass += 1
        else:
            ver_fail += 1
            ver_failures.append((idx, comment, actual, expected))

    print(f"  verify result-match: {ver_pass}/{ver_pass + ver_fail}")
    if ver_failures:
        for idx, comment, actual, expected in ver_failures[:8]:
            print(f"    [#{idx}] {comment} — got {actual}, want {expected}")

    overall = gen_fail == 0 and ver_fail == 0
    print()
    print(f"=== Summary ===")
    print(f"Generate byte-match: {gen_pass}/{gen_pass + gen_fail}")
    print(f"Verify result-match: {ver_pass}/{ver_pass + ver_fail}")
    print(f"Overall: {'✓ CANONICAL BIP-374 COMPLIANCE' if overall else '✗ DIVERGENCE'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
