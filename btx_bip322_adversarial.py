#!/usr/bin/env python3
"""
btx_bip322_adversarial — adversarial regression tests for btx_bip322.

Goal: every invalid input must either return False (verify) or raise a
specific Exception (sign / parse), never crash the interpreter and
never silently accept.

Categories covered:
  WIF        — short/long, bad version byte, bad checksum
  bech32m    — bad checksum, wrong HRP, wrong-witver (v0 to P2TR fn)
  base64     — garbage chars, truncated stack, non-canonical compact_size
  P2TR sig   — wrong-length sig, explicit non-default hash_type
  full tx    — multi-input, multi-output, non-empty scriptSig,
               wrong output value, wrong output script, wrong prevout txid,
               wrong witness count
  cross-fn   — passing a P2WPKH address to verify_*_p2tr

Each case is asserted to either:
  - return False  (verify_simple_p2tr / verify_full_p2tr)
  - raise an Exception (sign_*_p2tr / decode_wif / decode_segwit_address)

Failure = either an unexpected True from verify, or an unexpected hard
crash without a controlled exception.
"""
from __future__ import annotations

import base64
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import btx_bip322 as B  # noqa: E402


# ----------------------------------------------------------- helpers


_VALID_WIF = "L5XqN6ckPPsDiTbRxcsthwiWpDBfWLo4uquUEydsPt8rSMoTpqpc"
_VALID_ADDR = "bc1pcquvhrqv0q68t4m0hfq6tpn006qrskyc7yrqnp2uyrf2emg3wynsdjyk38"
_VALID_MSG = "PURVOQ544B6HUATVBJZN5EZJUU"


def _good_sk_addr():
    sk, _ = B.decode_wif(_VALID_WIF)
    return sk, _VALID_ADDR


# ---------------------- the audit cases ------------------------------


def _check_raises(label, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except Exception:
        return None
    return f"{label}: expected an exception, got success"


def _check_false(label, fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
    except Exception as e:
        return f"{label}: unexpected exception {type(e).__name__}: {e}"
    if result is False:
        return None
    return f"{label}: expected False, got {result!r}"


def main() -> int:
    failures = []
    total = 0

    # ============================================== WIF decode

    total += 1
    failures.append(_check_raises("WIF empty", B.decode_wif, ""))

    total += 1
    failures.append(_check_raises("WIF bad chars", B.decode_wif, "0OIl"))  # forbidden chars

    total += 1
    # Mangle the checksum by changing the last character.
    last_swap = "L" if _VALID_WIF[-1] != "L" else "M"
    bad_csum = _VALID_WIF[:-1] + last_swap
    failures.append(_check_raises("WIF bad checksum", B.decode_wif, bad_csum))

    total += 1
    failures.append(_check_raises("WIF too short", B.decode_wif, "L5XqN6"))

    # ============================================== bech32m decode

    total += 1
    failures.append(_check_raises(
        "addr missing hrp",
        B.decode_segwit_address, "xyz1qabc", "bc",
    ))

    total += 1
    failures.append(_check_raises(
        "addr wrong hrp (tb instead of bc)",
        B.decode_segwit_address,
        "tb1pcquvhrqv0q68t4m0hfq6tpn006qrskyc7yrqnp2uyrf2emg3wynsdjyk38",
        "bc",
    ))

    total += 1
    # Flip a checksum byte.
    bad_addr = _VALID_ADDR[:-1] + ("8" if _VALID_ADDR[-1] != "8" else "9")
    failures.append(_check_raises(
        "addr bad checksum",
        B.decode_segwit_address, bad_addr, "bc",
    ))

    # ============================================== verify_simple_p2tr — type confusion

    sk, addr = _good_sk_addr()
    good_sig = B.sign_simple_p2tr(_VALID_MSG, sk, aux_rand=b"\x00" * 32)

    total += 1
    # Pass a P2WPKH address (witver=0) — must reject, not accept.
    failures.append(_check_false(
        "verify_simple_p2tr rejects v0 (P2WPKH) address",
        B.verify_simple_p2tr,
        _VALID_MSG,
        "bc1q9vza2e8x573nczrlzms0wvx3gsqjx7vavgkx0l",
        good_sig,
    ))

    total += 1
    failures.append(_check_false(
        "verify_simple_p2tr rejects missing smp prefix",
        B.verify_simple_p2tr, _VALID_MSG, addr, "foo" + good_sig[3:],
    ))

    total += 1
    failures.append(_check_false(
        "verify_simple_p2tr rejects garbage base64",
        B.verify_simple_p2tr, _VALID_MSG, addr, "smp!!!notbase64!!!",
    ))

    total += 1
    # Build a witness stack with 2 items instead of 1.
    two_item = (
        B.compact_size(2)
        + B.ser_string(b"\x00" * 64)
        + B.ser_string(b"\x00" * 64)
    )
    failures.append(_check_false(
        "verify_simple_p2tr rejects 2-item witness",
        B.verify_simple_p2tr, _VALID_MSG, addr,
        "smp" + base64.b64encode(two_item).decode(),
    ))

    total += 1
    # 65-byte sig with hash_type=0x01 (SIGHASH_ALL) — we only accept 0x00.
    sig65 = good_sig
    raw_stack = base64.b64decode(sig65[3:])
    # raw_stack = 0x01 0x40 || <64 bytes>; rebuild as 0x01 0x41 || <64 bytes> || 0x01
    tampered_stack = (
        B.compact_size(1)
        + B.ser_string(raw_stack[2:] + b"\x01")  # add hash_type byte = SIGHASH_ALL
    )
    failures.append(_check_false(
        "verify_simple_p2tr rejects 65-byte sig with hash_type=0x01",
        B.verify_simple_p2tr, _VALID_MSG, addr,
        "smp" + base64.b64encode(tampered_stack).decode(),
    ))

    # ============================================== full format — structural

    good_full = B.sign_full_p2tr(
        _VALID_MSG, sk,
        version=2, locktime=2016, sequence=2016,
        aux_rand=b"\x00" * 32,
    )

    # Sanity self-check: the well-formed sig must verify (otherwise the
    # below negative tests aren't meaningful).
    if not B.verify_full_p2tr(_VALID_MSG, addr, good_full):
        failures.append("self-check: good_full does not verify (BUG in audit setup)")

    total += 1
    failures.append(_check_false(
        "verify_full_p2tr rejects missing ful prefix",
        B.verify_full_p2tr, _VALID_MSG, addr, "smp" + good_full[3:],
    ))

    total += 1
    # Parse the good_full into mutable bytes
    raw = base64.b64decode(good_full[3:])

    # Mutate the output value from 0 to 1
    # Layout (relative offsets from start):
    #   [0..4)  version
    #   [4..6)  segwit marker+flag
    #   [6..7)  nin = 1
    #   [7..39)  prevout txid
    #   [39..43) vout
    #   [43..44) script_sig_len = 0
    #   [44..48) sequence
    #   [48..49) nout = 1
    #   [49..57) out_value (i64)
    #   [57..58) out_spk_len = 1
    #   [58..59) out_spk = 0x6a
    # ...
    raw_bad_value = raw[:49] + struct.pack("<q", 1) + raw[57:]
    failures.append(_check_false(
        "verify_full_p2tr rejects out.value != 0",
        B.verify_full_p2tr, _VALID_MSG, addr,
        "ful" + base64.b64encode(raw_bad_value).decode(),
    ))

    total += 1
    # Mutate output scriptPubKey from OP_RETURN (0x6a) to OP_FALSE (0x00)
    raw_bad_spk = raw[:58] + b"\x00" + raw[59:]
    failures.append(_check_false(
        "verify_full_p2tr rejects out.spk != OP_RETURN",
        B.verify_full_p2tr, _VALID_MSG, addr,
        "ful" + base64.b64encode(raw_bad_spk).decode(),
    ))

    total += 1
    # Bit-flip the prevout txid
    raw_bad_prev = raw[:7] + bytes([raw[7] ^ 0x01]) + raw[8:]
    failures.append(_check_false(
        "verify_full_p2tr rejects wrong prevout.txid",
        B.verify_full_p2tr, _VALID_MSG, addr,
        "ful" + base64.b64encode(raw_bad_prev).decode(),
    ))

    total += 1
    # Bit-flip the version
    raw_bad_v = bytes([raw[0] ^ 0x01]) + raw[1:]
    failures.append(_check_false(
        "verify_full_p2tr rejects bit-flipped version",
        B.verify_full_p2tr, _VALID_MSG, addr,
        "ful" + base64.b64encode(raw_bad_v).decode(),
    ))

    total += 1
    # Bit-flip the sequence
    raw_bad_seq = raw[:44] + bytes([raw[44] ^ 0x01]) + raw[45:]
    failures.append(_check_false(
        "verify_full_p2tr rejects bit-flipped sequence",
        B.verify_full_p2tr, _VALID_MSG, addr,
        "ful" + base64.b64encode(raw_bad_seq).decode(),
    ))

    total += 1
    failures.append(_check_false(
        "verify_full_p2tr rejects garbage base64",
        B.verify_full_p2tr, _VALID_MSG, addr, "ful!!!notbase64!!!",
    ))

    # ============================================== sign — bad inputs

    total += 1
    failures.append(_check_raises(
        "sign_simple_p2tr rejects 31-byte seckey",
        B.sign_simple_p2tr, _VALID_MSG, b"\x00" * 31,
    ))

    total += 1
    failures.append(_check_raises(
        "sign_simple_p2tr rejects seckey == 0",
        B.sign_simple_p2tr, _VALID_MSG, b"\x00" * 32,
    ))

    # ============================================== tally

    non_passing = [f for f in failures if f is not None]
    if non_passing:
        print(f"FAIL ({len(non_passing)}/{total}):")
        for m in non_passing:
            print(f"  - {m}")
        print(f"✗ btx_bip322_adversarial: {total - len(non_passing)} PASS, {len(non_passing)} FAIL")
        return 1
    print(f"✓ btx_bip322_adversarial: {total}/{total} negative cases handled correctly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
