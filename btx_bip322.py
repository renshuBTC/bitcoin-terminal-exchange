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

import base64
import hashlib
import struct
from typing import List, Optional


# BIP-322 tag for message hashing
_BIP322_TAG = "BIP0322-signed-message"


# secp256k1 constants (mirror of btx_taproot)
_SECP_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


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


# =====================================================================
#  BIP-322 simple P2TR signing/verification
# =====================================================================
#
# The "simple" format consists of the to_sign witness stack, consensus-
# encoded (compact_size(N) || ser_string(item) for each item), and
# base64-encoded with the literal ASCII prefix "smp".
#
# For a P2TR key-path spend the witness is just [sig] where sig is a
# BIP-340 Schnorr signature over the BIP-341 key-path sighash of to_sign.
# When the resulting sig is 64 bytes (SIGHASH_DEFAULT), the implicit
# hash_type is 0x00; a 65-byte sig would carry an explicit hash_type
# byte but BTX always emits SIGHASH_DEFAULT here.


# -------------------------- bech32m decode (BIP-350) ----------------------

# (Keep this self-contained so btx_bip322 has no extra dependency on
#  btx_taproot's bech32m implementation. The polymod logic is identical;
#  the only difference between bech32 and bech32m is the constant.)
_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32M_CONST = 0x2BC830A3


def _bech32_polymod(values):
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            chk ^= gen[i] if ((b >> i) & 1) else 0
    return chk


def _hrp_expand(hrp):
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convertbits(data, frm, to, pad=True):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << to) - 1
    for b in data:
        acc = (acc << frm) | b
        bits += frm
        while bits >= to:
            bits -= to
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (to - bits)) & maxv)
    elif not pad and (bits >= frm or ((acc << (to - bits)) & maxv)):
        return None
    return ret


def decode_segwit_address(addr: str, expected_hrp: str = "bc"):
    """Return (witver, witprog_bytes) for a bc1q/bc1p address, or raise."""
    addr = addr.lower()
    if not addr.startswith(expected_hrp + "1"):
        raise ValueError(f"bad hrp prefix on {addr!r}")
    enc = addr[len(expected_hrp) + 1:]
    if any(c not in _BECH32_CHARSET for c in enc):
        raise ValueError("address contains non-bech32 chars")
    data = [_BECH32_CHARSET.find(c) for c in enc]
    if len(data) < 6:
        raise ValueError("address too short")
    values = _hrp_expand(expected_hrp) + data
    poly = _bech32_polymod(values)
    witver = data[0]
    expected_const = 1 if witver == 0 else _BECH32M_CONST
    if poly != expected_const:
        raise ValueError(
            f"bad checksum (got polymod={poly:#x}, "
            f"want={expected_const:#x} for witver={witver})"
        )
    bits = _convertbits(data[1:-6], 5, 8, False)
    if bits is None:
        raise ValueError("bad witness program 5->8 bit convert")
    witprog = bytes(bits)
    if not (2 <= len(witprog) <= 40):
        raise ValueError(f"witness program length {len(witprog)} out of range")
    if witver == 0 and len(witprog) not in (20, 32):
        raise ValueError("v0 witness program must be 20 or 32 bytes")
    return witver, witprog


# -------------------------- WIF (base58check) decode ----------------------

_B58_CHARSET = (
    "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
)


def _b58_decode(s: str) -> bytes:
    num = 0
    for c in s:
        idx = _B58_CHARSET.find(c)
        if idx < 0:
            raise ValueError(f"non-base58 char {c!r}")
        num = num * 58 + idx
    # Encode as bytes (big-endian) preserving leading "1"s as zero bytes.
    n_bytes = max(1, (num.bit_length() + 7) // 8)
    out = num.to_bytes(n_bytes, "big")
    pad = 0
    for c in s:
        if c == "1":
            pad += 1
        else:
            break
    return b"\x00" * pad + out


def decode_wif(wif: str) -> tuple[bytes, bool]:
    """Decode a WIF private key. Returns (32-byte privkey, compressed_flag).

    Mainnet WIF format:
        [0x80] || [32-byte privkey] || [optional 0x01 = compressed] || [4-byte checksum]
    """
    raw = _b58_decode(wif)
    if len(raw) < 4:
        raise ValueError("WIF too short")
    payload, checksum = raw[:-4], raw[-4:]
    if hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] != checksum:
        raise ValueError("WIF checksum mismatch")
    if payload[0] != 0x80:
        raise ValueError(f"unexpected WIF version byte {payload[0]:#x}")
    if len(payload) == 33:
        return payload[1:], False           # uncompressed
    if len(payload) == 34 and payload[33] == 0x01:
        return payload[1:33], True          # compressed
    raise ValueError(f"unexpected WIF payload length {len(payload)}")


# -------------------------- Taproot tweak helper --------------------------


def _taproot_tweak_seckey(seckey: bytes, merkle_root: bytes = b"") -> bytes:
    """BIP-341 key-spend secret-key tweak. Returns the 32-byte tweaked
    secret key d_q such that schnorr_sign with d_q produces a valid
    key-path signature under the output key Q = P + t·G where
    t = H_TapTweak(P || merkle_root).
    """
    # Import lazily to avoid circular import surprises in some build
    # configurations.
    from btx_taproot import (
        xonly_pubkey,
        taproot_tweak_pubkey,
        tagged_hash as _ttag,
        _has_even_y,
    )

    assert len(seckey) == 32
    d0 = int.from_bytes(seckey, "big")
    if not (1 <= d0 < _SECP_N):
        raise ValueError("secret key out of range")
    p_xonly, point = xonly_pubkey(seckey)
    d_internal = d0 if _has_even_y(point) else (_SECP_N - d0)
    t_bytes = _ttag("TapTweak", p_xonly + bytes(merkle_root))
    t = int.from_bytes(t_bytes, "big") % _SECP_N
    d_tweaked = (d_internal + t) % _SECP_N
    # Now check parity of the output key Q. If Q has odd y, negate.
    parity, q_xonly = taproot_tweak_pubkey(p_xonly, bytes(merkle_root))
    if parity == 1:                              # output key has odd y
        d_tweaked = (_SECP_N - d_tweaked) % _SECP_N
    if d_tweaked == 0:
        raise ValueError("tweaked secret key is 0 (vanishingly unlikely)")
    return d_tweaked.to_bytes(32, "big")


# -------------------------- simple BIP-322 P2TR sign/verify ---------------


def _p2tr_spk_from_xonly(output_xonly: bytes) -> bytes:
    """Build the OP_1 PUSH32 [Q] scriptPubKey for a Taproot output."""
    assert len(output_xonly) == 32
    return b"\x51" + b"\x20" + output_xonly


def _bip322_p2tr_sighash(
    msg_hash: bytes, output_xonly: bytes, hash_type: int = 0x00
) -> bytes:
    """Compute the BIP-341 key-path sighash that a BIP-322 simple P2TR
    signature must commit to.

    `hash_type` is 0x00 (SIGHASH_DEFAULT, BTX's default — 64-byte
    signatures) or 0x01 (SIGHASH_ALL, used by Sparrow Wallet, Trezor
    Suite, and `bip322-js` with default `Signer.sign` — 65-byte
    signatures with explicit 0x01 sighash flag).

    Per BIP-341 these two are semantically equivalent but produce
    different on-chain signatures because SIGHASH_ALL includes the
    hash_type byte in sigMsg.
    """
    from btx_taproot import tap_sighash

    spk = _p2tr_spk_from_xonly(output_xonly)
    spend_txid_le = to_spend_txid(msg_hash, spk)
    # to_sign tx: spends to_spend:0, outputs (0, OP_RETURN), no witness yet
    vin = [(bytes(spend_txid_le), 0, 0)]
    spent_amounts = [0]
    spent_spks = [spk]
    vout = [(0, b"\x6a")]                # value=0, scriptPubKey=OP_RETURN
    return tap_sighash(
        version=0,
        locktime=0,
        vin=vin,
        spent_amounts=spent_amounts,
        spent_spks=spent_spks,
        vout=vout,
        input_index=0,
        hash_type=hash_type,
        ext_flag=0,
    )


def sign_simple_p2tr(
    message: bytes | str,
    seckey: bytes,
    aux_rand: Optional[bytes] = None,
) -> str:
    """Produce a BIP-322 'simple' signature for a P2TR (key-path) address.

    The returned string is the "smp" + base64(<witness stack>) form
    suitable for direct comparison or transmission.

    The signing key is the *internal* private key; the BIP-341 key-path
    tweak (with empty merkle root) is applied internally so the resulting
    signature verifies under the output key Q.
    """
    from btx_taproot import schnorr_sign

    if aux_rand is None:
        aux_rand = b"\x00" * 32
    mh = message_hash(message)
    # Derive output x-only from the internal seckey
    from btx_taproot import xonly_pubkey, taproot_tweak_pubkey

    p_xonly, _ = xonly_pubkey(seckey)
    _parity, q_xonly = taproot_tweak_pubkey(p_xonly, b"")
    sighash = _bip322_p2tr_sighash(mh, q_xonly)
    d_q = _taproot_tweak_seckey(seckey, b"")
    sig = schnorr_sign(sighash, d_q, aux_rand)
    return _encode_simple_signature([sig])


def verify_simple_p2tr(message: bytes | str, address: str, signature_str: str) -> bool:
    """Verify a BIP-322 'simple' P2TR signature against a bc1p address."""
    from btx_taproot import schnorr_verify

    try:
        witver, witprog = decode_segwit_address(address, "bc")
    except ValueError:
        return False
    if witver != 1 or len(witprog) != 32:
        return False                              # not a v1 (Taproot) address
    output_xonly = bytes(witprog)
    try:
        stack = _decode_simple_signature(signature_str)
    except ValueError:
        return False
    if len(stack) != 1 or len(stack[0]) not in (64, 65):
        return False
    sig = stack[0]
    # BIP-341 sighash type encoding:
    #   64-byte sig         → SIGHASH_DEFAULT (0x00)
    #   65-byte sig last=0x00 → SIGHASH_DEFAULT (non-canonical but valid)
    #   65-byte sig last=0x01 → SIGHASH_ALL (Sparrow, Trezor, bip322-js default)
    # SIGHASH_DEFAULT and SIGHASH_ALL are semantically equivalent for
    # full-output signing; the on-chain bytes differ because SIGHASH_ALL
    # appends the 0x01 sighash byte into sigMsg.
    if len(sig) == 64:
        hash_type = 0x00
    else:
        flag = sig[64]
        # Currently accepted: SIGHASH_DEFAULT (0x00) + SIGHASH_ALL (0x01).
        #
        # Bookmark for future: SIGHASH_NONE (0x02) and SIGHASH_SINGLE
        # (0x03) require btx_taproot.tap_sighash to handle the variant
        # sigMsg structure where output commitment differs. Probing
        # (Task C, 2026-06-04) confirmed: extending JUST this allowlist
        # is insufficient because tap_sighash currently computes the
        # all-outputs sigMsg regardless of hash_type, so own-sign+verify
        # for 0x02/0x03 returns False. Real-world relevance is minimal
        # (no attestation tool defaults to NONE/SINGLE).
        #
        # ACP variants (0x81-0x83) are inherently degenerate for the
        # BIP-322 simple format (one input only) and stay rejected.
        if flag not in (0x00, 0x01):
            return False
        hash_type = flag
    sig64 = sig[:64]
    mh = message_hash(message)
    sighash = _bip322_p2tr_sighash(mh, output_xonly, hash_type=hash_type)
    return schnorr_verify(sighash, output_xonly, sig64)


def _encode_simple_signature(stack: List[bytes]) -> str:
    """smp + base64( compact_size(N) || (ser_string(item) for item in stack) )"""
    body = compact_size(len(stack))
    for item in stack:
        body += ser_string(item)
    return "smp" + base64.b64encode(body).decode("ascii")


# =====================================================================
#  BIP-322 "full" format P2TR signing/verification
# =====================================================================
#
# The full format is the entire to_sign transaction in standard segwit
# network serialisation, base64-encoded with the literal "ful" prefix.
#
# Unlike the simple format, the full format lets the signer choose
# arbitrary nVersion, nLockTime, and nSequence values — useful for
# time-locked attestations ("this attestation is only valid after
# block N").
#
# For P2TR key-path: witness stack is [sig], sighash is BIP-341
# key-path over the to_sign tx using those version/locktime/sequence
# values.


def _build_to_sign_tx_p2tr_full(
    to_spend_txid_le: bytes,
    witness_stack: List[bytes],
    *,
    version: int = 2,
    locktime: int = 0,
    sequence: int = 0,
) -> bytes:
    """Full-format to_sign tx serialised with segwit marker + flag and
    a single-input / single-OP_RETURN-output skeleton.

    `witness_stack` is the witness for input 0. For an unsigned skeleton
    used as a sighash precursor, pass an empty list — but note that the
    sighash is computed independent of the witness anyway."""
    assert len(to_spend_txid_le) == 32
    assert 0 <= sequence <= 0xFFFFFFFF
    assert 0 <= locktime <= 0xFFFFFFFF
    txin = _ser_txin(to_spend_txid_le, 0, b"", sequence)
    txout = _ser_txout(0, b"\x6a")           # OP_RETURN
    body = (
        struct.pack("<i", version)
        + b"\x00\x01"                        # segwit marker + flag
        + compact_size(1) + txin
        + compact_size(1) + txout
        + _ser_witness_stack(witness_stack)
        + struct.pack("<I", locktime)
    )
    return body


def _bip322_p2tr_sighash_full(
    msg_hash: bytes,
    output_xonly: bytes,
    *,
    version: int,
    locktime: int,
    sequence: int,
) -> bytes:
    """BIP-341 key-path sighash for the full-format to_sign tx."""
    from btx_taproot import tap_sighash, SIGHASH_DEFAULT

    spk = _p2tr_spk_from_xonly(output_xonly)
    spend_txid_le = to_spend_txid(msg_hash, spk)
    vin = [(bytes(spend_txid_le), 0, sequence)]
    return tap_sighash(
        version=version,
        locktime=locktime,
        vin=vin,
        spent_amounts=[0],
        spent_spks=[spk],
        vout=[(0, b"\x6a")],
        input_index=0,
        hash_type=SIGHASH_DEFAULT,
        ext_flag=0,
    )


def sign_full_p2tr(
    message: bytes | str,
    seckey: bytes,
    *,
    version: int = 2,
    locktime: int = 0,
    sequence: int = 0,
    aux_rand: Optional[bytes] = None,
) -> str:
    """Produce a BIP-322 'full' format signature for a P2TR (key-path)
    address. Returns the "ful"-prefixed base64 string.

    `version` / `locktime` / `sequence` parameterise the to_sign tx,
    enabling time-locked attestations."""
    from btx_taproot import schnorr_sign, xonly_pubkey, taproot_tweak_pubkey

    if aux_rand is None:
        aux_rand = b"\x00" * 32
    mh = message_hash(message)
    p_xonly, _ = xonly_pubkey(seckey)
    _parity, q_xonly = taproot_tweak_pubkey(p_xonly, b"")
    sighash = _bip322_p2tr_sighash_full(
        mh, q_xonly, version=version, locktime=locktime, sequence=sequence
    )
    d_q = _taproot_tweak_seckey(seckey, b"")
    sig = schnorr_sign(sighash, d_q, aux_rand)
    spend_txid_le = to_spend_txid(mh, _p2tr_spk_from_xonly(q_xonly))
    full_tx = _build_to_sign_tx_p2tr_full(
        spend_txid_le, [sig],
        version=version, locktime=locktime, sequence=sequence,
    )
    return "ful" + base64.b64encode(full_tx).decode("ascii")


def _parse_full_tx(raw: bytes):
    """Parse the to_sign segwit-serialised tx in BIP-322 'full' form.
    Returns dict(version, prevout_txid, prevout_n, sequence, vout,
    witness_stack, locktime). Strict: must be exactly 1 input + 1 output."""
    pos = 0

    def _u(n):
        nonlocal pos
        v = int.from_bytes(raw[pos:pos + n], "little")
        pos += n
        return v

    def _cs():
        nonlocal pos
        first = raw[pos]
        pos += 1
        if first < 0xFD:
            return first
        if first == 0xFD:
            return _u(2)
        if first == 0xFE:
            return _u(4)
        return _u(8)

    def _read(n):
        nonlocal pos
        out = raw[pos:pos + n]
        pos += n
        return out

    version = int.from_bytes(raw[pos:pos + 4], "little", signed=True)
    pos += 4
    if raw[pos:pos + 2] != b"\x00\x01":
        raise ValueError("expected segwit marker+flag (0x0001)")
    pos += 2
    nin = _cs()
    if nin != 1:
        raise ValueError(f"expected 1 input, got {nin}")
    prevout_txid = _read(32)
    prevout_n = _u(4)
    ss_len = _cs()
    if ss_len != 0:
        raise ValueError(f"scriptSig must be empty, got len={ss_len}")
    sequence = _u(4)
    nout = _cs()
    if nout != 1:
        raise ValueError(f"expected 1 output, got {nout}")
    out_value = _u(8)
    out_spk_len = _cs()
    out_spk = _read(out_spk_len)
    # witness stack for input 0
    ws_count = _cs()
    stack = []
    for _ in range(ws_count):
        item_len = _cs()
        stack.append(_read(item_len))
    locktime = _u(4)
    if pos != len(raw):
        raise ValueError(f"trailing bytes ({len(raw) - pos} leftover)")
    return {
        "version": version,
        "prevout_txid": prevout_txid,
        "prevout_n": prevout_n,
        "sequence": sequence,
        "vout": [(out_value, out_spk)],
        "witness_stack": stack,
        "locktime": locktime,
    }


def verify_full_p2tr(message: bytes | str, address: str, signature_str: str) -> bool:
    """Verify a BIP-322 'full' format P2TR signature against a bc1p
    address. Validates the entire to_sign envelope:
      - segwit-encoded skeleton with 1 input, 1 (0-value, OP_RETURN) output
      - prevout.txid == computed to_spend.txid; prevout.n == 0
      - witness is [sig] of length 64 (SIGHASH_DEFAULT)
      - BIP-340 verifies the sig over the BIP-341 key-path sighash
        using the tx's actual version/locktime/sequence."""
    from btx_taproot import schnorr_verify

    if not signature_str.startswith("ful"):
        return False
    try:
        raw = base64.b64decode(signature_str[3:])
    except Exception:
        return False
    try:
        tx = _parse_full_tx(raw)
    except ValueError:
        return False

    # to_sign output must be (0, OP_RETURN)
    out_value, out_spk = tx["vout"][0]
    if out_value != 0 or out_spk != b"\x6a":
        return False

    # Address → output key
    try:
        witver, witprog = decode_segwit_address(address, "bc")
    except ValueError:
        return False
    if witver != 1 or len(witprog) != 32:
        return False
    output_xonly = bytes(witprog)

    # Recompute to_spend.txid and check the input prevout
    mh = message_hash(message)
    expected_spend_txid_le = to_spend_txid(mh, _p2tr_spk_from_xonly(output_xonly))
    if tx["prevout_txid"] != expected_spend_txid_le or tx["prevout_n"] != 0:
        return False

    # Witness must be [sig], either 64 or 65 bytes (with explicit hash_type)
    stack = tx["witness_stack"]
    if len(stack) != 1:
        return False
    sig = stack[0]
    if len(sig) == 65 and sig[64] != 0x00:
        return False
    if len(sig) not in (64, 65):
        return False
    sig64 = sig[:64]

    sighash = _bip322_p2tr_sighash_full(
        mh, output_xonly,
        version=tx["version"], locktime=tx["locktime"], sequence=tx["sequence"],
    )
    return schnorr_verify(sighash, output_xonly, sig64)


def _decode_simple_signature(s: str) -> List[bytes]:
    """Inverse of _encode_simple_signature. Returns the witness stack.

    Accepts two forms:
      - BTX's `smp<base64>` (the format BTX produces — `smp` is a self-
        identifying variant prefix BTX prepends so the format type is
        unambiguous at a glance)
      - Standard BIP-322 `<base64>` (no prefix — the format produced by
        bip322-js, Sparrow Wallet, Trezor Suite, and per the BIP-322
        spec text)

    Both forms decode to the same witness stack. BIP-322 simple format
    per the spec is: base64(serialized witness) — without any prefix.
    BTX's `smp` prefix is a BTX-specific extension for self-ID.
    """
    if s.startswith("smp"):
        raw = base64.b64decode(s[3:])
    else:
        # Standard BIP-322 simple format — no prefix, raw base64.
        raw = base64.b64decode(s)
    pos = 0

    def _read_compact_size() -> int:
        nonlocal pos
        first = raw[pos]
        pos += 1
        if first < 0xFD:
            return first
        if first == 0xFD:
            v = int.from_bytes(raw[pos:pos + 2], "little")
            pos += 2
            return v
        if first == 0xFE:
            v = int.from_bytes(raw[pos:pos + 4], "little")
            pos += 4
            return v
        v = int.from_bytes(raw[pos:pos + 8], "little")
        pos += 8
        return v

    n = _read_compact_size()
    stack: List[bytes] = []
    for _ in range(n):
        length = _read_compact_size()
        if pos + length > len(raw):
            raise ValueError("truncated stack item")
        stack.append(raw[pos:pos + length])
        pos += length
    if pos != len(raw):
        raise ValueError(f"trailing bytes after stack ({len(raw) - pos} leftover)")
    return stack


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

    # ------------------------------------------------------------------
    #   Phase 2 — P2TR sign + verify against the official generated
    #   test vectors.
    # ------------------------------------------------------------------
    p2tr_ok = 0
    p2tr_total = 0
    GENERATED_CANDIDATES = [
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
    for p in GENERATED_CANDIDATES:
        if os.path.isfile(p):
            gen_src = p
            break

    if gen_src is not None:
        with open(gen_src) as f:
            gen = json.load(f)
        p2tr_entries = [e for e in gen.get("simple", []) if e.get("type") == "p2tr"]
        for entry in p2tr_entries:
            p2tr_total += 1
            wif = entry["private_keys"][0]
            msg = entry["message"]
            addr = entry["address"]
            canonical_sig = entry["bip322_signatures"][0]
            try:
                seckey, _compressed = decode_wif(wif)
            except Exception as e:
                failures.append(f"p2tr: WIF decode failed: {e}")
                continue

            # Independent sanity: the address bech32m-decodes to
            # the tweaked output key derived from the private key.
            try:
                witver, witprog = decode_segwit_address(addr, "bc")
            except ValueError as e:
                failures.append(f"p2tr: addr decode failed: {e}")
                continue
            if witver != 1 or len(witprog) != 32:
                failures.append(f"p2tr: addr is not v1/32B for {addr}")
                continue

            from btx_taproot import xonly_pubkey, taproot_tweak_pubkey
            p_xonly, _ = xonly_pubkey(seckey)
            _parity, q_xonly = taproot_tweak_pubkey(p_xonly, b"")
            if q_xonly != bytes(witprog):
                failures.append(
                    f"p2tr: address Q={witprog.hex()} doesn't match "
                    f"derived Q={q_xonly.hex()} from WIF"
                )
                continue

            # 1. The canonical signature must verify against our verifier.
            if not verify_simple_p2tr(msg, addr, canonical_sig):
                failures.append(
                    f"p2tr: canonical sig from generated-test-vectors did NOT verify "
                    f"for addr {addr}"
                )
                continue

            # 2. Round-trip: sign with aux_rand=0; verify must pass.
            our_sig = sign_simple_p2tr(msg, seckey, aux_rand=b"\x00" * 32)
            if not verify_simple_p2tr(msg, addr, our_sig):
                failures.append("p2tr: own sign->verify round-trip failed")
                continue

            # 3. Tamper test — wrong message must fail.
            if verify_simple_p2tr(msg + "x", addr, our_sig):
                failures.append("p2tr: verify accepted tampered message (BAD)")
                continue

            # 4. Tamper test — wrong address must fail.
            wrong_q = (int.from_bytes(q_xonly, "big") ^ 1).to_bytes(32, "big")
            try:
                # rebuild a bech32m address from the flipped key; if it
                # doesn't pass the curve check we just skip this sub-step
                from btx_taproot import segwit_address as _sa, lift_x
                lift_x(int.from_bytes(wrong_q, "big"))   # ensures it's on-curve
                wrong_addr = _sa(1, wrong_q, "bc")
                if verify_simple_p2tr(msg, wrong_addr, our_sig):
                    failures.append("p2tr: verify accepted tampered address (BAD)")
                    continue
            except Exception:
                pass

            p2tr_ok += 1

    # ------------------------------------------------------------------
    #   Phase 3 — P2TR "full" format with time-locks
    # ------------------------------------------------------------------
    full_ok = 0
    full_total = 0
    if gen_src is not None:
        full_entries = [e for e in gen.get("full", []) if e.get("type") == "p2tr"]
        for entry in full_entries:
            full_total += 1
            wif = entry["private_keys"][0]
            msg = entry["message"]
            addr = entry["address"]
            canonical_sig = entry["bip322_signatures"][0]
            vsn = entry["tx_version"]
            lt = entry["lock_time"]
            seq = entry["sequence"]
            try:
                seckey, _ = decode_wif(wif)
            except Exception as e:
                failures.append(f"full p2tr: WIF decode failed: {e}")
                continue

            # 1. Canonical sig must verify.
            if not verify_full_p2tr(msg, addr, canonical_sig):
                failures.append(
                    f"full p2tr: canonical sig did NOT verify for {addr}"
                )
                continue

            # 2. Round-trip with the same params.
            our_sig = sign_full_p2tr(
                msg, seckey,
                version=vsn, locktime=lt, sequence=seq,
                aux_rand=b"\x00" * 32,
            )
            if not verify_full_p2tr(msg, addr, our_sig):
                failures.append("full p2tr: own sign->verify round-trip failed")
                continue

            # 3. Tampered message rejected.
            if verify_full_p2tr(msg + "x", addr, our_sig):
                failures.append("full p2tr: verify accepted tampered message")
                continue

            # 4. Tampered locktime (rebuild tx with locktime+1) — our sig
            #    should NOT verify under that altered envelope. Build by
            #    re-signing with new params and verifying that yields a
            #    *different* envelope, then make sure swapping a witness
            #    item from one tx into the other invalidates it.
            #    Easier check: our_sig with version-tampered must fail.
            #    Achieved by parsing, mutating, re-encoding.
            try:
                raw = base64.b64decode(our_sig[3:])
                tampered = raw[:-4] + struct.pack("<I", (lt + 1) & 0xFFFFFFFF)
                tampered_sig = "ful" + base64.b64encode(tampered).decode("ascii")
                if verify_full_p2tr(msg, addr, tampered_sig):
                    failures.append(
                        "full p2tr: verify accepted lockTime-tampered sig"
                    )
                    continue
            except Exception:
                pass

            full_ok += 1

    if failures:
        print(f"FAIL: {len(failures)} divergence(s):")
        for f in failures:
            print(f"  - {f}")
        print(
            f"✗ btx_bip322: hash {ok}/{total}, "
            f"simple p2tr {p2tr_ok}/{p2tr_total}, ful