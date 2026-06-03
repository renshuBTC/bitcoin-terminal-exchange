#!/usr/bin/env python3
"""
btx_xtest_vs_python_bip380 — cross-validate btx_descriptor against
darosior/python-bip380's canonical BIP-380 checksum implementation.

This is a second independent oracle for BTX's descriptor checksum. The
first oracle was rust-miniscript v12.3.7 (see BTX-rust-miniscript-
scouting-2026-06-03.md and the original 10-vector validation).

python-bip380's checksum.py (71 LOC) is copyright Pieter Wuille — the
BIP-380 author. If BTX's descriptor_checksum() agrees with it
byte-for-byte across all 10 BTX golden vectors, we have
triple-validation:
   (a) BTX-generated golden vectors
   (b) rust-miniscript v12.3.7 (Rust)
   (c) python-bip380 (Python, Pieter Wuille)

Cross-test target repo:
    darosior/python-bip380       (cloned to ../Bitcoin CoreX/python-bip380-reference/)

Verbatim from python-bip380/bip380/descriptors/checksum.py:1-3 —
  # Copyright (c) 2019 Pieter Wuille
  # Distributed under the MIT software license

Run:
    python3 btx_xtest_vs_python_bip380.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BTX = HERE
# python-bip380 sits as a sibling of bitcoin-terminal-exchange under
# Bitcoin CoreX/. Find it relative to this file.
PARENT = os.path.dirname(BTX)
PB380_CANDIDATES = [
    os.path.join(PARENT, "Bitcoin CoreX", "python-bip380-reference"),
    os.path.join(PARENT, "Bitcoin CoreX", "python-bip380"),
    os.path.join(PARENT, "python-bip380-reference"),
]
PB380 = None
for p in PB380_CANDIDATES:
    if os.path.isfile(os.path.join(p, "bip380", "descriptors", "checksum.py")):
        PB380 = p
        break

if PB380 is None:
    print("[SKIP] python-bip380 not found at any of:")
    for p in PB380_CANDIDATES:
        print(f"         {p}")
    print("         Clone with: git clone https://github.com/darosior/python-bip380")
    sys.exit(0)

sys.path.insert(0, BTX)

# Canonical reference — Pieter Wuille's descsum_create from python-bip380.
# Load the checksum module directly by file path so we bypass
# bip380/__init__.py and bip380/descriptors/__init__.py, which import
# coincurve and bip32 (not needed for this checksum-only cross-test).
import importlib.util as _ilu

_pb380_checksum_path = os.path.join(PB380, "bip380", "descriptors", "checksum.py")
_spec = _ilu.spec_from_file_location("_pb380_checksum", _pb380_checksum_path)
_pb380_mod = _ilu.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_pb380_mod)
pb380_descsum_create = _pb380_mod.descsum_create

# BTX's implementation.
from btx_descriptor import (  # type: ignore
    descriptor_checksum as btx_descriptor_checksum,
    tr_key_only_serialize as btx_tr_serialize,
    _GOLDEN_TR_KEY,
)


def main() -> int:
    total = len(_GOLDEN_TR_KEY)
    csum_ok = 0
    full_ok = 0
    failures = []

    for i, (xonly_hex, hrp, _addr) in enumerate(_GOLDEN_TR_KEY):
        body = f"tr({xonly_hex})"

        # BTX's 8-char checksum
        btx_csum = btx_descriptor_checksum(body)

        # python-bip380 produces "body#checksum"; split to compare the
        # 8-char checksum tail directly.
        pb_full = pb380_descsum_create(body)
        assert pb_full.startswith(body + "#"), (
            f"python-bip380 output not in expected form: {pb_full!r}"
        )
        pb_csum = pb_full[-8:]

        # Independent check: BTX's full serialized descriptor
        btx_full = btx_tr_serialize(bytes.fromhex(xonly_hex), with_csum=True)

        if btx_csum == pb_csum:
            csum_ok += 1
        else:
            failures.append(
                f"vector {i} checksum mismatch: "
                f"body={body!r} btx={btx_csum!r} pb380={pb_csum!r}"
            )

        if btx_full == pb_full:
            full_ok += 1
        else:
            failures.append(
                f"vector {i} full-descriptor mismatch: "
                f"btx={btx_full!r} pb380={pb_full!r}"
            )

    print(f"checksum bytes match: {csum_ok}/{total}")
    print(f"full descriptor match: {full_ok}/{total}")

    if failures:
        print()
        print(f"FAIL: {len(failures)} divergence(s):")
        for f in failures:
            print(f"  - {f}")
        print()
        print("✗ btx_xtest_vs_python_bip380: divergence")
        return 1

    print()
    print(f"✓ btx_xtest_vs_python_bip380: "
          f"{csum_ok}/{total} checksums + "
          f"{full_ok}/{total} full descriptors agree with "
          f"python-bip380 (Pieter Wuille's canonical impl)")
    print("  Triple-validation closed: BTX ↔ rust-miniscript ↔ python-bip380")
    return 0


if __name__ == "__main__":
    sys.exit(main())
