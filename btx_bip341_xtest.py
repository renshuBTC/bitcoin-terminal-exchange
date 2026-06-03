#!/usr/bin/env python3
"""
btx_bip341_xtest.py — Cross-test BTX's BIP-341 Taproot implementation against
the LIVE canonical wallet test vectors from
`bitcoin/bips/bip-0341/wallet-test-vectors.json`.

The vector file has two categories:
  - scriptPubKey: 7 cases testing Taproot OUTPUT KEY DERIVATION
      Given internal_pubkey + scriptTree, compute (tweaked_pubkey,
      scriptPubKey, address).
  - keyPathSpending: 1 case with 9 inputSpending sub-cases testing
      KEY-PATH SIGHASH computation.

BTX's `btx_taproot.py` has:
  - taproot_tweak_pubkey(internal_xonly, merkle_root) — for scriptPubKey
  - tap_sighash(...) — for keyPathSpending

If both match canonical on every vector, BTX's Taproot foundation is
canonical-compliant. Same discipline as BTX-bip327-keyagg-finding-2026-06-03
and the BIP-340 cross-test in btx_bip340_xtest.py.
"""

from __future__ import annotations
import json
import os
import sys


BIP341_JSON = "/mnt/c/Users/Ren Shu/Documents/Claude/Projects/Bitcoin CoreX/bitcoin-bips-reference/bip-0341/wallet-test-vectors.json"
if not os.path.isfile(BIP341_JSON):
    BIP341_JSON = "/sessions/keen-determined-einstein/mnt/Bitcoin CoreX/bitcoin-bips-reference/bip-0341/wallet-test-vectors.json"


def _hex(b):
    return b.hex() if b else ""


def _compute_merkle_root_from_tree(tree, btx):
    """
    Walk the canonical scriptTree structure. Each leaf is:
      {"id": int, "script": hex, "leafVersion": int}
    or a list of two children.
    Returns a 32-byte tapbranch hash or None for empty tree.
    """
    if tree is None:
        return None
    if isinstance(tree, list):
        if len(tree) == 1:
            # single leaf
            return _compute_merkle_root_from_tree(tree[0], btx)
        if len(tree) == 2:
            left = _compute_merkle_root_from_tree(tree[0], btx)
            right = _compute_merkle_root_from_tree(tree[1], btx)
            return btx.tapbranch_hash(left, right)
        raise ValueError(f"unexpected tree shape: list of {len(tree)}")
    # leaf
    if isinstance(tree, dict):
        leaf_ver = tree["leafVersion"]
        script_hex = tree["script"]
        return btx.tapleaf_hash(bytes.fromhex(script_hex), leaf_ver)
    raise ValueError(f"unexpected tree node type: {type(tree)}")


def run_scriptpubkey_tests(d, btx):
    cases = d["scriptPubKey"]
    tweak_pass = tweak_fail = 0
    spk_pass = spk_fail = 0
    addr_pass = addr_fail = 0
    failures = []

    for i, tc in enumerate(cases):
        given = tc["given"]
        intermediary = tc["intermediary"]
        expected = tc["expected"]
        internal = bytes.fromhex(given["internalPubkey"])
        try:
            mroot = _compute_merkle_root_from_tree(given.get("scriptTree"), btx)
        except Exception as e:
            tweak_fail += 1
            failures.append((i, f"merkle build raised: {e}"))
            continue
        # BTX's signature: returns (parity_bit, tweaked_xonly_bytes)
        try:
            parity, tweaked_xonly = btx.taproot_tweak_pubkey(internal, mroot if mroot else b"")
            actual_spk = btx.p2tr_scriptpubkey(tweaked_xonly)
        except Exception as e:
            tweak_fail += 1
            failures.append((i, f"BTX raised: {e}"))
            continue

        # tweaked pubkey check
        expected_tweaked = bytes.fromhex(intermediary["tweakedPubkey"])
        if tweaked_xonly == expected_tweaked:
            tweak_pass += 1
        else:
            tweak_fail += 1
            failures.append((i, f"tweaked: got {tweaked_xonly.hex()}, want {expected_tweaked.hex()}"))

        # scriptPubKey check
        expected_spk = bytes.fromhex(expected["scriptPubKey"])
        if actual_spk == expected_spk:
            spk_pass += 1
        else:
            spk_fail += 1
            failures.append((i, f"spk: got {actual_spk.hex()}, want {expected_spk.hex()}"))

        # address check — BTX has segwit_address(witver=1, witprog, hrp='bc')
        try:
            actual_addr = btx.segwit_address(1, tweaked_xonly, hrp="bc")
            expected_addr = expected["bip350Address"]
            if actual_addr == expected_addr:
                addr_pass += 1
            else:
                addr_fail += 1
                failures.append((i, f"addr: got {actual_addr}, want {expected_addr}"))
        except Exception as e:
            addr_fail += 1
            failures.append((i, f"addr raised: {e}"))

    return {
        "tweak_pass": tweak_pass, "tweak_fail": tweak_fail,
        "spk_pass": spk_pass, "spk_fail": spk_fail,
        "addr_pass": addr_pass, "addr_fail": addr_fail,
        "failures": failures,
    }


def run_keypath_tests(d, btx):
    """
    BIP-341 keyPathSpending vectors. Each inputSpending sub-case provides
    given.txinIndex and expected.sigMsg (the canonical sighash).
    BTX's tap_sighash signature is intricate; we extract the necessary
    fields from the parent vector's auxiliary tx + utxo info.
    """
    kp = d["keyPathSpending"][0]
    given = kp["given"]
    aux = kp.get("auxiliary", {})
    inputs = kp["inputSpending"]

    # Parse the raw tx — btx returns (version, locktime, vin, vout)
    version, locktime, vin, vout = btx.parse_unsigned_tx(given["rawUnsignedTx"])

    # UTXOs spent (full list, same order as inputs)
    utxos = given["utxosSpent"]
    spent_amounts = [int(u["amountSats"]) for u in utxos]
    spent_spks = [bytes.fromhex(u["scriptPubKey"]) for u in utxos]

    sighash_pass = sighash_fail = 0
    failures = []

    for sub in inputs:
        idx = sub["given"]["txinIndex"]
        hash_type = int(sub["given"]["hashType"])
        # The canonical JSON has both sigMsg (the message before tagged-hash)
        # and sigHash (the final tagged-hash output). BTX's tap_sighash
        # returns the latter, so compare directly.
        expected_full = bytes.fromhex(sub["intermediary"]["sigHash"])
        try:
            actual_sighash = btx.tap_sighash(
                version=version, locktime=locktime,
                vin=vin, vout=vout,
                spent_amounts=spent_amounts, spent_spks=spent_spks,
                input_index=idx, hash_type=hash_type,
                ext_flag=0,  # key-path => ext_flag = 0
                annex=None, tapleaf_hash=None,
            )
        except Exception as e:
            sighash_fail += 1
            failures.append((idx, f"BTX tap_sighash raised: {e}"))
            continue

        if actual_sighash == expected_full:
            sighash_pass += 1
        else:
            sighash_fail += 1
            failures.append((
                idx,
                f"sighash: got {actual_sighash.hex()}, want {expected_full.hex()}"
            ))

    return {
        "sighash_pass": sighash_pass,
        "sighash_fail": sighash_fail,
        "failures": failures,
    }


def main():
    import btx_taproot as btx

    with open(BIP341_JSON) as f:
        d = json.load(f)

    print(f"=== BIP-341 cross-test ===")
    print(f"scriptPubKey cases: {len(d['scriptPubKey'])}")
    print(f"keyPathSpending input cases: {len(d['keyPathSpending'][0]['inputSpending'])}")
    print()

    spk_res = run_scriptpubkey_tests(d, btx)
    print("--- scriptPubKey (output key derivation) ---")
    print(f"  tweaked pubkey:   {spk_res['tweak_pass']}/{spk_res['tweak_pass'] + spk_res['tweak_fail']}")
    print(f"  scriptPubKey:     {spk_res['spk_pass']}/{spk_res['spk_pass'] + spk_res['spk_fail']}")
    print(f"  bip350 address:   {spk_res['addr_pass']}/{spk_res['addr_pass'] + spk_res['addr_fail']}")
    if spk_res["failures"]:
        for i, msg in spk_res["failures"][:5]:
            print(f"    [#{i}] {msg}")

    kp_res = run_keypath_tests(d, btx)
    print()
    print("--- keyPathSpending sighash ---")
    print(f"  sighash matches:  {kp_res['sighash_pass']}/{kp_res['sighash_pass'] + kp_res['sighash_fail']}")
    if kp_res["failures"]:
        for idx, msg in kp_res["failures"][:5]:
            print(f"    [#{idx}] {msg}")

    all_ok = (
        spk_res["tweak_fail"] == 0 and spk_res["spk_fail"] == 0 and
        spk_res["addr_fail"] == 0 and kp_res["sighash_fail"] == 0
    )
    print()
    print(f"=== Summary ===")
    print(f"Overall: {'✓ CANONICAL BIP-341 COMPLIANCE' if all_ok else '✗ DIVERGENCE'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
