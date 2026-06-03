#!/usr/bin/env python3
"""
btx_bip322 — BIP-322 Generic Signed Message Format primitives.

BIP-322 by Karl-Johan Alm (kallewoof) defines a single signing/verification
scheme that works for ANY Bitcoin address type, including bc1p (Taproot
key-path), bc1q (P2WPKH), and legacy P2PKH/P2SH.

This module implements the foundational pieces:

  1. ``message_hash(msg)`` — BIP-340 tagged sha256 with tag
     ``"BIP0322-signed-message"``.

  2. ``build_to_spend_tx(message_hash, script_pubkey)`` — the synthetic
     "challenge" transaction defined in BIP-322:

         nVersion         = 0
         nLockTime        = 0
         vin[0].prevout   = 0x00..00 : 0xFFFFFFFF
         vin[0].nSequence = 0
         vin[0].scriptSig = OP_0 PUSH32[message_hash]
         vout[0].nValue   = 0
         vout[0].scriptPubKey = message_challenge

  3. ``build_to_sign_tx(to_spend_txid, message_signature)`` — the
     "solution" transaction. The ``message_signature`` here is the
     witness stack; when called with an empty list, this returns the
     unsigned transaction (which is what the test vectors hash).

         nVersion         = 0
         nLockTime        = 0
         vin[0].prevout   = to_spend.txid : 0
         vin[0].nSequence = 0
         vin[0].scriptSig = []
         vin[0].witness   = message_signature
         vout[0].nValue   = 0
         vout[0].scriptPubKey = OP_RETURN

BTX use case
------------
Makers can attest control of an address (bc1p / bc1q) by signing a
challenge under BIP-322. Today BTX has no auth layer; this primitive is
the building block for a future maker-registration flow that doesn't
require a custodial registry.

Verbatim cross-reference
------------------------
The construction is taken from BIP-322's "Detailed Specification" /
"Full" section. The mediawiki defines (lines 138-146):

    nVersion = 0
    nLockTime = 0
    vin[0].prevout.hash = 0000...000
    vin[0].prevout.n = 0xFFFFFFFF
    vin[0].nSequence = 0
    vin[0].scriptSig = OP_0 PUSH32[ message_hash ]
    vin[0].scriptWitness = []
    vout[0].nValue = 0
    vout[0].scriptPubKey = message_challenge

Tested against bitcoin/bips bip-0322/basic-test-vectors.json — 3 vectors.
"""

from __future__ import annotations

import hashlib
import struct
from typing import List


# BIP-322 tag for message hashing
_BIP322_TAG = "BIP0322-signed-message"


# ---------------------------------------------------------------- helpers


def sha256(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def dsha256(b: bytes) -> bytes:
    """Bitcoin double-SHA256 (txid hashing)."""
    return sha256(sha256(b))


def tagged_hash(tag: str, data: bytes) -> bytes:
    """BIP-340 tagged hash: sha256(sha256(tag) || sha256(tag) || data)."""
    t = sha256(tag.encode())
    return sha256(t + t + data)


def compact_size(n: int) -> bytes:
    """Bitcoin compact-size integer encoding."""
    assert n >= 0
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", n)
    if n <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", n)
    return b"\xff" + struct.pack("<Q", n)


def ser_string(b: bytes) -> bytes:
    """Length-prefixed byte string."""
    return compact_size(len(b)) + b


# ---------------------------------------------------------------- BIP-322 core


def message_hash(message: bytes | str) -> bytes:
    """Compute the BIP-322 message hash.

    >>> message_hash("").hex()
    'c90c269c4f8fcbe6880f72a721ddfbf1914268a794cbb21cfafee13770ae19f1'

    Per BIP-322 line 148:
        message_hash is a BIP340-tagged hash of the message, i.e.,
        sha256_tag(m), where tag = "BIP0322-signed-message" and m is the
        message as-is without length prefix or null terminator.
    """
    if isinstance(message, str):
        message = message.encode("utf-8")
    return tagged_hash(_BIP322_TAG, message)


def _ser_outpoint(txid_le: bytes, vout: int) -> bytes:
    assert len(txid_le) == 32
    return txid_le + struct.pack("<I", vout)


def _ser_txin(
    prevout_txid_le: bytes,
    prevout_n: int,
    script_sig: bytes,
    sequence: int,
) -> bytes:
    return (
        _ser_outpoint(prevout_txid_le, prevout_n)
        + ser_string(script_sig)
        + struct.pack("<I", sequence)
    )


def _ser_txout(value: int, spk: bytes) -> bytes:
    return struct.pack("<q", value) + ser_string(spk)


def _ser_witness_stack(stack: List[bytes]) -> bytes:
    out = compact_size(len(stack))
    for item in stack:
        out += ser_string(item)
    return out


def build_to_spend_tx(msg_hash: bytes, script_pubkey: bytes) -> bytes:
    """Return the BIP-322 ``to_spend`` transaction in standard (non-witness)
    serialisation.

    The to_spend tx has no witness, so the serialisation is just:
        nVersion(4) || vin(1+...) || vout(1+...) || nLockTime(4)
    """
    assert len(msg_hash) == 32
    # scriptSig = OP_0 (0x00) + PUSH32 (0x20) + msg_hash
    script_sig = b"\x00" + b"\x20" + msg_hash
    # Outpoint: prevout.hash = 32 zeroes; prevout.n = 0xFFFFFFFF
    prev_txid = b"\x00" * 32
    prev_n = 0xFFFFFFFF
    # nSequence = 0
    txin = _ser_txin(prev_txid, prev_n, script_sig, 0)
    txout = _ser_txout(0, script_pubkey)
    tx = (
        struct.pack("<i", 0)              # nVersion = 0
        + compact_size(1) + txin          # 1 input
        + compact_size(1) + txout         # 1 output
        + struct.pack("<I", 0)            # nLockTime = 0
    )
    return tx


def to_spend_txid(msg_hash: bytes, script_pubkey: bytes) -> bytes:
    """Compute the to_spend txid (little-endian bytes — internal form)."""
    return dsha256(build_to_spend_tx(msg_hash, script_pubkey))


def build_to_sign_tx_unsigned(to_spend_txid_le: bytes) -> bytes:
    """Return the BIP-322 ``to_sign`` transaction in **non-witness**
    serialisation, with an empty witness.

    Per BIP-322 lines 153-163:
        nVersion = 0
        nLockTime = 0
        vin[0].prevout.hash = to_spend.txid
        vin[0].prevout.n = 0
        vin[0].nSequence = 0
        vin[0].scriptSig = []
        vin[0].scriptWitness = message_signature
        vout[0].nValue = 0
        vout[0].scriptPubKey = OP_RETURN

    The to_sign **txid** is computed over the non-witness serialisation
    (no segwit marker/flag, no witness). This matches the test vectors
    `to_sign_tx_hash` field.
    """
    assert len(to_spend_txid_le) == 32
    txin = _ser_txin(to_spend_txid_le, 0, b"", 0)   # empty scriptSig
    txout = _ser_txout(0, b"\x6a")                  # OP_RETURN
    tx = (
        struct.pack("<i", 0)
        + compact_size(1) + txin
        + compact_size(1) + txout
        + struct.pack("<I", 0)
    )
    return tx


def to_sign_txid(to_spend_txid_le: bytes) -> bytes:
    """Compute the to_sign txid (little-endian bytes)."""
    return dsha256(build_to_sign_tx_unsigned(to_spend_txid_le))


def build_to_sign_tx_signed(
    to_spend_txid_le: bytes, witness_stack: List[bytes]
) -> bytes:
    """Return the to_sign tx in **segwit** serialisation including the
    provided witness stack. Used for emitting actual signatures, not for
    computing the bare to_sign txid (which is over the non-witness form).
    """
    assert len(to_spend_txid_le) == 32
    txin = _ser_txin(to_spend_txid_le, 0, b"", 0)
    txout = _ser_txout(0, b"\x6a")
    body = (
        struct.pack("<i", 0)
        + b"\x00\x01"                     # segwit marker + flag
        + compact_size(1) + txin
        + compact_size(1) + txout
        + _ser_witness_stack(witness_stack)
        + struct.pack("<I", 0)
    )
    return body


# ---------------------------------------------------------------- cross-test


# All 3 basic-test-vectors.json entries use the same address, decoded once.
# Address: bc1q9vza2e8x573nczrlzms0wvx3gsqjx7vavgkx0l
# Bech32 decode (witver=0): witness_program = 2b05d564e6a7a33c087f16e0f730d1440123799d
# scriptPubKey = 0x00 0x14 || witness_program = 00142b05d564e6a7a33c087f16e0f730d1440123799d
_BC1Q_TEST_SPK = bytes.fromhex("00142b05d564e6a7a33c087f16e0f730d1440123799d")


_BIP322_BASIC_VECTORS = [
    # (message, expected_message_hash, expected_to_spend_txid_be, expected_to_sign_txid_be)
    # All txids in the JSON file are big-endian display form (network/RPC).
    # Internally Bitcoin txids are little-endian; flip for comparison.
    (
        "",
        "c90c269c4f8fcbe6880f72a721ddfbf1914268a794cbb21cfafee13770ae19f1",
        "c5680aa69bb8d860bf82d4e9cd3504b55dde018de765a91bb566283c545a99a7",
        "1e9654e951a5ba44c8604c4de6c67fd78a27e81dcadcfe1edf638ba3aaebaed6",
    ),
    (
        "Hello World",
        "f0eb03b1a75ac6d9847f55c624a99169b5dccba2a31f5b23bea77ba270de0a7a",
        "b79d196740ad5217771c1098fc4a4b51e0535c32236c71f1ea4d61a2d603352b",
        "88737ae86f2077145f93cc4b153ae9a1cb8d56afa511988c149c5c8c9d93bddf",
    ),
    (
        "UTF-8 support: öäüéàè 测试文本 \U0001F604",
        "43936b237ea38c7794eb5d755e0d220b6db92ebfc5c8f482759d22b1286376d7",
        "c8f4f525fe8afb1bc09b44175bd2096f079c98425e8a1be676b712add1fb62f0",
        "8f488e06b89eafd019ec528109eafaf7f1d1811fd617aa1eeb9658f1c1be6586",
    ),
]


def main() -> int:
    import json
    import os
    import sys

    ok = 0
    failures = []

    for i, (msg, exp_mh, exp_spend_be, exp_sign_be) in enumerate(_BIP322_BASIC_VECTORS):
        # message_hash
        mh = message_hash(msg)
        if mh.hex() != exp_mh:
            failures.append(
                f"vector {i} message_hash: got {mh.hex()} want {exp_mh}"
            )
            continue

        # to_spend
        spend_txid_le = to_spend_txid(mh, _BC1Q_TEST_SPK)
        spend_txid_be = spend_txid_le[::-1].hex()
        if spend_txid_be != exp_spend_be:
            failures.append(
                f"vector {i} to_spend_txid: got {spend_txid_be} want {exp_spend_be}"
            )
            continue

        # to_sign (unsigned, no witness)
        sign_txid_le = to_sign_txid(spend_txid_le)
        sign_txid_be = sign_txid_le[::-1].hex()
        if sign_txid_be != exp_sign_be:
            failures.append(
                f"vector {i} to_sign_txid: got {sign_txid_be} want {exp_sign_be}"
            )
            continue

        ok += 1

    total = len(_BIP322_BASIC_VECTORS)

    # Optionally re-load the original JSON file too (sanity that goldens
    # weren't typoed when transcribed inline).
    HERE = os.path.dirname(os.path.abspath(__file__))
    CANDIDATES = [
        os.path.join(
            os.path.dirname(HERE),
            "Bitcoin CoreX",
            "bitcoin-bips-reference",
            "bip-0322",
            "basic-test-vectors.json",
        ),
        os.path.expanduser(
            "~/Documents/Claude/Projects/Bitcoin CoreX/bitcoin-bips-reference/bip-0322/basic-test-vectors.json"
        ),
        "/mnt/c/Users/Ren Shu/Documents/Claude/Projects/Bitcoin CoreX/bitcoin-bips-reference/bip-0322/basic-test-vectors.json",
    ]
    src = None
    for p in CANDIDATES:
        if os.path.isfile(p):
            src = p
            break
    if src is not None:
        with open(src) as f:
            data = json.load(f)
        json_hashes = data.get("tx_hashes", [])
        for j, entry in enumerate(json_hashes):
            inline_mh = _BIP322_BASIC_VECTORS[j][1] if j < total else None
            if entry["message_hash"] != inline_mh:
                failures.append(
                    f"inline transcription drift at vec {j}: "
                    f"inline={inline_mh} json={entry['message_hash']}"
                )

    if failures:
        print(f"FAIL: {len(failures)} divergence(s):")
        for f in failures:
            print(f"  - {f}")
        print(f"✗ btx_bip322: {ok}/{total} PASS, {len(failures)} fail")
        return 1

    print(f"  message_hash + to_spend + to_sign:  {ok}/{total} PASS")
    print(f"✓ btx_bip322: all {total} basic-test-vector hash chains agree with canonical")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
