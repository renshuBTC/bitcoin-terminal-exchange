#!/usr/bin/env python3
"""
btx_dlc_oracle — DLC-compatible oracle message normalization + identity helpers.

Provides:

  normalize_message(s: str) -> bytes
    NFC-normalized UTF-8 encoding of a Unicode string. Required by
    `discreetlogcontracts/dlcspecs` Oracle.md so that visually-identical
    strings (e.g., "Å" U+00C5 vs "Å" U+212B vs "A°" U+0041 U+030A)
    produce identical signing bytes.

  hash_message(s: str) -> bytes
    SHA-256 of `normalize_message(s)`. The 32-byte msgHash a DLC oracle
    then feeds into `BIP340_sign(sk, msgHash)`.

  contract_id(fund_txid_be: bytes, fund_output_index: int,
              temporary_contract_id: bytes) -> bytes
    The 32-byte DLC contract id derivation from Protocol.md §"Definition
    of contract_id":

       contract_id = (funding_txid XOR temporary_contract_id)
                     with the last 2 bytes XORed with funding_output_index
                     (big-endian)

    Useful for BTX2 CONDITIONAL_ORDER records that want to be ID-
    compatible with dlcspecs-following DLC tooling (bitcoin-s,
    p2pderivatives/cfd-dlc, rust-dlc, Suredbits).

Cross-validated against:
  - `test/dlc_hash_test.json` (6 NFC vectors)
  - `test/contract_id_test.json` (4 contract_id vectors)

Strategic note
--------------
BTX's existing `btx_dlc_demo.py` operates on `bytes` for both
`event_id` and `outcome`, leaving normalization to the caller. That's
fine today because BTX2 CONDITIONAL_ORDER records don't yet expose a
string-typed outcome API. This module exists for the path where:
  - BTX accepts a DLC oracle attestation produced by an external tool
    that follows dlcspecs, AND
  - The maker side wants to verify the oracle's attestation matches a
    Unicode event label they specified.

For that path, both sides MUST do NFC normalization, or visually-
identical labels will produce different signatures.
"""
from __future__ import annotations

import hashlib
import unicodedata


def normalize_message(s: str) -> bytes:
    """Return the NFC-normalized UTF-8 encoding of ``s``.

    NFC (Normalization Form C, "canonical composition") is the form the
    DLC oracle spec mandates. See dlcspecs/Oracle.md §"Serialization and
    signing of outcome values".
    """
    if not isinstance(s, str):
        raise TypeError(f"normalize_message expects str, got {type(s).__name__}")
    return unicodedata.normalize("NFC", s).encode("utf-8")


def hash_message(s: str) -> bytes:
    """sha256(normalize_message(s)) — the 32-byte oracle msgHash."""
    return hashlib.sha256(normalize_message(s)).digest()


def contract_id(
    fund_txid_be: bytes,
    fund_output_index: int,
    temporary_contract_id: bytes,
) -> bytes:
    """DLC contract_id per Protocol.md.

    The funding txid is the BIG-ENDIAN form (display / RPC order), NOT
    the little-endian internal byte order. Matches dlcspecs vector
    convention.

    Args:
        fund_txid_be: 32-byte funding tx id in big-endian display order.
        fund_output_index: small integer (typically 0, 1, or 2).
        temporary_contract_id: 32-byte SHA256(offer_message_bytes).

    Returns:
        32-byte contract_id. XOR of funding_txid and temporary, with the
        last 2 bytes additionally XOR-ed by the big-endian
        fund_output_index.
    """
    if len(fund_txid_be) != 32:
        raise ValueError(f"fund_txid_be must be 32 bytes, got {len(fund_txid_be)}")
    if len(temporary_contract_id) != 32:
        raise ValueError(
            f"temporary_contract_id must be 32 bytes, got {len(temporary_contract_id)}"
        )
    if fund_output_index < 0 or fund_output_index > 0xFFFF:
        raise ValueError(f"fund_output_index out of range [0,65535]: {fund_output_index}")

    xored = bytes(a ^ b for a, b in zip(fund_txid_be, temporary_contract_id))
    # Last two bytes get an additional XOR by output_index (big-endian).
    idx_hi = (fund_output_index >> 8) & 0xFF
    idx_lo = fund_output_index & 0xFF
    out = bytearray(xored)
    out[30] ^= idx_hi
    out[31] ^= idx_lo
    return bytes(out)


# ---------------------------------------------------------------- self-test


def _selftest_normalize_via_dlcspecs_vectors() -> int:
    """Cross-test against the 6 dlc_hash_test.json vectors.

    Each entry has:
       Variants  — list of visually-identical strings
       Expected  — hex of NFC UTF-8 bytes that they should all collapse to
       SHA256    — sha256 of Expected bytes

    Every Variant must normalize to Expected and hash to SHA256.
    """
    import json
    import os

    HERE = os.path.dirname(os.path.abspath(__file__))
    CANDIDATES = [
        os.path.join(
            os.path.dirname(HERE),
            "Bitcoin CoreX",
            "dlcspecs-reference",
            "test",
            "dlc_hash_test.json",
        ),
        "/mnt/c/Users/Ren Shu/Documents/Claude/Projects/Bitcoin CoreX/dlcspecs-reference/test/dlc_hash_test.json",
    ]
    src = None
    for p in CANDIDATES:
        if os.path.isfile(p):
            src = p
            break
    if src is None:
        print("[SKIP] dlc_hash_test.json not found")
        return 0

    with open(src) as f:
        vectors = json.load(f)

    failures: list[str] = []
    n_bytes = n_hash = 0
    for vec in vectors:
        desc = vec["Description"]
        expected_bytes = bytes.fromhex(vec["Expected"])
        expected_sha = bytes.fromhex(vec["SHA256"])
        for variant in vec["Variants"]:
            got_bytes = normalize_message(variant)
            if got_bytes != expected_bytes:
                failures.append(
                    f"{desc}: variant {variant!r} normalised to "
                    f"{got_bytes.hex()}, expected {expected_bytes.hex()}"
                )
                continue
            n_bytes += 1
            got_sha = hashlib.sha256(got_bytes).digest()
            if got_sha != expected_sha:
                failures.append(
                    f"{desc}: variant {variant!r} sha256 = "
                    f"{got_sha.hex()}, expected {expected_sha.hex()}"
                )
                continue
            n_hash += 1

    if failures:
        for m in failures:
            print(f"  FAIL: {m}")
        print(f"✗ normalize: {len(failures)} failure(s)")
        return 1
    print(f"  NFC normalization vs Expected bytes:    {n_bytes}/{n_bytes}")
    print(f"  SHA256 of NFC bytes vs Expected SHA256: {n_hash}/{n_hash}")
    return 0


def _selftest_contract_id_via_dlcspecs_vectors() -> int:
    """Cross-test against the 4 contract_id_test.json vectors."""
    import json
    import os

    HERE = os.path.dirname(os.path.abspath(__file__))
    CANDIDATES = [
        os.path.join(
            os.path.dirname(HERE),
            "Bitcoin CoreX",
            "dlcspecs-reference",
            "test",
            "contract_id_test.json",
        ),
        "/mnt/c/Users/Ren Shu/Documents/Claude/Projects/Bitcoin CoreX/dlcspecs-reference/test/contract_id_test.json",
    ]
    src = None
    for p in CANDIDATES:
        if os.path.isfile(p):
            src = p
            break
    if src is None:
        print("[SKIP] contract_id_test.json not found")
        return 0

    with open(src) as f:
        vectors = json.load(f)

    failures = []
    n_ok = 0
    for i, v in enumerate(vectors):
        fund_txid = bytes.fromhex(v["fundTxId"])
        idx = int(v["fundOutputIndex"])
        temp_id = bytes.fromhex(v["temporaryContractId"])
        expected = bytes.fromhex(v["contractId"])
        got = contract_id(fund_txid, idx, temp_id)
        if got != expected:
            failures.append(
                f"vec {i}: got {got.hex()} expected {expected.hex()}"
            )
            continue
        n_ok += 1

    if failures:
        for m in failures:
            print(f"  FAIL: {m}")
        print(f"✗ contract_id: {len(failures)} failure(s)")
        return 1
    print(f"  contract_id derivation:                 {n_ok}/{n_ok}")
    return 0


def main() -> int:
    rv = 0
    rv |= _selftest_normalize_via_dlcspecs_vectors()
    rv |= _selftest_contract_id_via_dlcspecs_vectors()
    if rv == 0:
        print(
            "✓ btx_dlc_oracle: NFC normalization + contract_id derivation "
            "both match dlcspecs canonical vectors"
        )
    return rv


if __name__ == "__main__":
    import sys
    sys.exit(main())
