#!/usr/bin/env python3
"""
btx_bip327_xtest.py — Cross-test BTX's MuSig2 KeyAgg against the canonical
BIP-327 reference and official test vectors.

Mirrors the Runes triple-validation discipline: BTX vs ord vs runestone-lib.
Here it's BTX (`btx_musig2.key_agg`) vs the bitcoin/bips canonical reference
(co-authored by Jonas Nick, Tim Ruffing, Elliott Jin; Status: Deployed,
Version: 1.0.3) vs the official key_agg_vectors.json.

## Expected outcomes

For each of the 4 valid test cases:
  1. Run BIP-327's reference.key_agg → x-only output
  2. Run BTX's key_agg with same INPUT pubkeys (truncated to x-only) →
     x-only output
  3. Report:
     - bip327_matches_expected (sanity — the canonical ref should match
       its own vectors)
     - btx_matches_bip327 (the question — does BTX's KeyAgg agree
       byte-for-byte with the canonical algorithm?)
     - btx_matches_expected (equivalent shortcut)

If btx_matches_bip327 is True for all vectors, BTX's MuSig2 is BIP-327
compliant. If False for any, BTX's MuSig2 is a variant — record the
divergence in the closure doc.
"""

from __future__ import annotations
import json
import sys
import os


# Locate the BIP-327 reference and vectors
BIP327_DIR = "/mnt/c/Users/Ren Shu/Documents/Claude/Projects/Bitcoin CoreX/bitcoin-bips-reference/bip-0327"
if not os.path.isdir(BIP327_DIR):
    # Fallback for sandbox path
    BIP327_DIR = "/sessions/keen-determined-einstein/mnt/Bitcoin CoreX/bitcoin-bips-reference/bip-0327"


def main():
    sys.path.insert(0, BIP327_DIR)
    import reference as bip327
    import btx_musig2 as btx

    vec_path = os.path.join(BIP327_DIR, "vectors", "key_agg_vectors.json")
    with open(vec_path) as f:
        vec = json.load(f)

    pubkeys_hex = vec["pubkeys"]
    pubkeys = [bytes.fromhex(p) for p in pubkeys_hex]
    valid = vec["valid_test_cases"]
    errors = vec["error_test_cases"]

    print(f"=== BIP-327 KeyAgg cross-test ===")
    print(f"Input pubkeys: {len(pubkeys)} total (33-byte compressed)")
    print(f"Valid test cases: {len(valid)}")
    print(f"Error test cases: {len(errors)}")
    print()

    all_match_bip327 = True
    bip327_self_ok = True

    for i, tc in enumerate(valid):
        indices = tc["key_indices"]
        expected_xonly_hex = tc["expected"]
        expected = bytes.fromhex(expected_xonly_hex)
        case_pubkeys = [pubkeys[j] for j in indices]

        # 1. Run BIP-327's canonical reference
        try:
            ctx = bip327.key_agg(case_pubkeys)
            bip327_xonly = bip327.get_xonly_pk(ctx)
            bip327_ok = bip327_xonly == expected
        except Exception as e:
            bip327_xonly = b""
            bip327_ok = False
            print(f"[case {i}] BIP-327 reference raised: {e}")

        if not bip327_ok:
            bip327_self_ok = False

        # 2. Run BTX's key_agg with x-only-truncated inputs
        case_xonly_inputs = [pk[1:33] for pk in case_pubkeys]  # strip parity byte
        try:
            btx_result = btx.key_agg(case_xonly_inputs)
            btx_xonly = btx_result["agg_xonly"]
        except Exception as e:
            btx_xonly = b""
            print(f"[case {i}] BTX key_agg raised: {e}")

        btx_matches_bip327 = btx_xonly == bip327_xonly
        btx_matches_expected = btx_xonly == expected
        if not btx_matches_bip327:
            all_match_bip327 = False

        print(f"[case {i}] indices={indices}")
        print(f"   expected (canonical):     {expected_xonly_hex}")
        print(f"   bip327 reference output:  {bip327_xonly.hex().upper()}")
        print(f"   btx_musig2 output:        {btx_xonly.hex().upper()}")
        print(f"   bip327 matches expected:  {bip327_ok}")
        print(f"   btx   matches bip327:     {btx_matches_bip327}")
        print(f"   btx   matches expected:   {btx_matches_expected}")
        print()

    print(f"=== Summary ===")
    print(f"BIP-327 reference matches its own vectors: {bip327_self_ok}")
    print(f"BTX btx_musig2 matches BIP-327:            {all_match_bip327}")

    if not all_match_bip327:
        print()
        print("FINDING: BTX's MuSig2 KeyAgg is NOT BIP-327 byte-compatible.")
        print("This is a real divergence to record in the closure doc.")
        print("Both implementations are valid MuSig2-like KeyAgg constructions,")
        print("but they differ in (a) input encoding (x-only vs compressed), and")
        print("(b) list-hash input bytes (32 vs 33 per pubkey).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
