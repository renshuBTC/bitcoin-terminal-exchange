#!/usr/bin/env python3
"""
btx_s2c_envelope.py — S2C *delayed-reveal* integration for BTX.

Closes the integration gap from BTX-secp256k1-zkp-followup-2026-06-03.md:
the S2C primitive (`btx_s2c.py` + `btx_s2c.rs`) is shipped, but no
integration path is wired up. This module ships the simplest of the three
candidate paths surveyed in the followup doc — **delayed-reveal** — as a
working reference implementation.

## The delayed-reveal flow

  STAGE A  (covert commit, block N)
    Maker chooses a payload `c` (a small BTX order summary or full BTX1
    envelope bytes).
    Maker signs an ordinary Bitcoin tx with BIP340 Schnorr, embedding
    an S2C commitment to `c` via `btx_s2c.s2c_sign(...)`.
    The signed tx looks like any other Taproot key-path spend — no BTX1
    magic bytes, no envelope, no scriptpath reveal. Passive observers
    cannot tell this is a BTX commit.

  STAGE B  (reveal, block N+M, M ≥ 0)
    Later — same block or many blocks later — the maker publishes a small
    BTX-S2C-REVEAL record carrying:
        (commit_txid, commit_input_idx, R0_x, c)
    The reveal can ride a witness-envelope or an OP_RETURN; format is
    independent of where it's carried.

  STAGE C  (indexer binding)
    BTX indexer scans for REVEAL records. For each one:
      1. Fetch the witness Schnorr sig from the named (txid, input_idx).
      2. Reconstruct expected_R_x = lift_x(R0_x) + s2c_tweak(R0_x, c) · G
      3. If sig[0:32] == expected_R_x: the commit tx is BOUND to payload `c`.
         The indexer treats it as a retroactive BTX commitment at block N.

The construction has three properties that make it useful for BTX:

  * **Privacy at commit-time.** Before stage B fires, the commit tx is
    indistinguishable from any other BIP340-signed Bitcoin tx.
  * **Atomic anti-front-run.** The reveal locks the commit to `c`; the
    commitment was fixed at signing time and is computationally infeasible
    to change without re-signing. A maker cannot reveal a different payload
    against the same commit.
  * **No protocol change.** Stage A uses standard Bitcoin; stage B can
    re-use the existing BTX1 carrier or any other reveal channel.

## Wire format — BTX-S2C-REVEAL record

A reveal record is a flat byte structure:

    MAGIC (4 B)         "S2C1"  (0x53 0x32 0x43 0x31)
    VERSION (1 B)       0x01
    COMMIT_TXID (32 B)  txid of stage-A commit tx
    INPUT_IDX (u32 BE)  which input's witness carries the S2C sig
    R0_X (32 B)         x-only opening
    C_LEN (u16 BE)      length of payload c
    C (variable)        the committed payload

Total: 75 + len(c) bytes. Fits inside a BTX1 envelope or an OP_RETURN.

For the canonical BTX integration, the payload `c` is the serialized BTX1
order envelope (which makes the S2C commit *equivalent* to the order
announcement, just with a delay).
"""

from __future__ import annotations
import struct

from btx_taproot import lift_x, xonly_pubkey, schnorr_verify
from btx_s2c import s2c_sign, s2c_verify, s2c_expected_R_x


# ----------------------------- record format -----------------------------

MAGIC = b"S2C1"
VERSION = 0x01
HEADER_SIZE = len(MAGIC) + 1 + 32 + 4 + 32 + 2  # 75 bytes

class RevealError(Exception): ...


def build_reveal(commit_txid: bytes, input_idx: int, r0_x: bytes, c: bytes) -> bytes:
    """
    Serialize a BTX-S2C-REVEAL record. Used by the maker in stage B.

    Args:
        commit_txid: 32-byte stage-A tx id (raw bytes, internal byte order)
        input_idx:   which input of the commit tx carries the S2C sig
        r0_x:        32-byte x-only opening (the "R0_x" from s2c_sign)
        c:           the commitment payload (BTX1 envelope or order summary)

    Returns: bytes (≥ 75 bytes total)
    """
    if len(commit_txid) != 32:
        raise RevealError(f"commit_txid must be 32 bytes, got {len(commit_txid)}")
    if not (0 <= input_idx < 2**32):
        raise RevealError(f"input_idx out of u32 range: {input_idx}")
    if len(r0_x) != 32:
        raise RevealError(f"r0_x must be 32 bytes, got {len(r0_x)}")
    if len(c) > 0xFFFF:
        raise RevealError(f"c too long: {len(c)} > 65535")

    out = (
        MAGIC
        + bytes([VERSION])
        + commit_txid
        + struct.pack(">I", input_idx)
        + r0_x
        + struct.pack(">H", len(c))
        + c
    )
    assert len(out) == HEADER_SIZE + len(c)
    return out


def parse_reveal(blob: bytes):
    """
    Parse a BTX-S2C-REVEAL record. Used by the indexer in stage C.

    Returns dict: { commit_txid, input_idx, r0_x, c }
    Raises RevealError if structure is invalid.
    """
    if len(blob) < HEADER_SIZE:
        raise RevealError(f"reveal too short: {len(blob)} < {HEADER_SIZE}")
    if blob[:4] != MAGIC:
        raise RevealError(f"bad magic: {blob[:4]!r}")
    if blob[4] != VERSION:
        raise RevealError(f"unknown version: {blob[4]}")
    commit_txid = blob[5:37]
    input_idx = struct.unpack(">I", blob[37:41])[0]
    r0_x = blob[41:73]
    c_len = struct.unpack(">H", blob[73:75])[0]
    if HEADER_SIZE + c_len != len(blob):
        raise RevealError(
            f"length mismatch: declared body {c_len}B, actual {len(blob) - HEADER_SIZE}B"
        )
    c = blob[75:75 + c_len]
    return {
        "commit_txid": commit_txid,
        "input_idx": input_idx,
        "r0_x": r0_x,
        "c": c,
    }


# ----------------------------- end-to-end verifier -----------------------------


def verify_reveal_against_sig(reveal: dict, commit_sig: bytes, commit_msg: bytes,
                               commit_pubkey_xonly: bytes) -> bool:
    """
    Stage C indexer verification.

    Given a parsed REVEAL record AND the on-chain commit-tx Schnorr signature
    (sig, msg, pubkey) — typically fetched by the indexer using
    `reveal["commit_txid"]` + `reveal["input_idx"]` — verify that the commit
    sig is indeed bound to the revealed payload.

    Returns True iff:
      (a) The commit sig is a valid BIP340 Schnorr sig under the pubkey.
      (b) sig[0:32] == s2c_expected_R_x(R0_x, c)

    This is the same check `btx_s2c.s2c_verify` does, exposed through a
    reveal-record-shaped API.
    """
    return s2c_verify(commit_sig, commit_msg, commit_pubkey_xonly,
                      reveal["r0_x"], reveal["c"])


# ----------------------------- selftest -----------------------------


def selftest(verbose: bool = True) -> bool:
    """
    Full integration loop:
      1. Maker chooses payload c and a Bitcoin sighash
      2. Maker signs with S2C → (commit_sig, R0_x)
      3. commit_sig verifies as a normal BIP340 sig (privacy check)
      4. Maker builds REVEAL record (commit_txid, input_idx, R0_x, c)
      5. Indexer parses REVEAL
      6. Indexer fetches commit_sig from the named (txid, input_idx)
         (here: provided directly), verifies via verify_reveal_against_sig
      7. Indexer tampering tests:
         - swap c → rejected
         - swap R0_x → rejected
         - swap commit_sig → rejected (no longer a BIP340 sig under pubkey)
      8. Round-trip: build → parse → re-serialize is byte-stable
    """
    ok = True

    # Fixed test material
    maker_sk = bytes.fromhex(
        "b7e151628aed2a6abf7158809cf4f3c762e7160f38b4da56a784d9045190cfef"
    )
    maker_pk = xonly_pubkey(maker_sk)[0]
    # Simulated stage-A sighash (any 32 bytes — in production this is the
    # BIP341 key-path-spend sighash)
    commit_msg = bytes.fromhex(
        "243f6a8885a308d313198a2e03707344a4093822299f31d0082efa98ec4e6c89"
    )
    # Simulated stage-A txid (any 32 bytes — in production this is the
    # actual mined txid)
    commit_txid = bytes.fromhex(
        "8acf6c708acf6c708acf6c708acf6c708acf6c708acf6c708acf6c708acf6c70"
    )
    input_idx = 0

    # Payloads — varied
    payloads = [
        b"BTX1" + b"\x00" * 8 + b"order summary v0",
        b"\x00" * 0,                                 # empty payload
        bytes.fromhex("4254583101"
                       + "00112233445566778899aabbccddeeff" * 4),  # 65 B
        b"x" * 1024,                                 # 1 KiB
    ]

    for i, c in enumerate(payloads):
        # 2. Maker signs with S2C
        commit_sig, r0_x = s2c_sign(maker_sk, commit_msg, c)
        # 3. commit_sig is a vanilla BIP340 sig
        if not schnorr_verify(commit_msg, maker_pk, commit_sig):
            ok = False
            if verbose: print(f"[s2c-env #{i}] FAIL: commit_sig fails BIP340 verify (privacy broken)")
            continue
        # 4. Build REVEAL
        reveal_bytes = build_reveal(commit_txid, input_idx, r0_x, c)
        # 5. Indexer parses
        try:
            reveal = parse_reveal(reveal_bytes)
        except RevealError as e:
            ok = False
            if verbose: print(f"[s2c-env #{i}] FAIL parse: {e}")
            continue
        if reveal["commit_txid"] != commit_txid:
            ok = False; continue
        if reveal["input_idx"] != input_idx:
            ok = False; continue
        if reveal["r0_x"] != r0_x:
            ok = False; continue
        if reveal["c"] != c:
            ok = False; continue
        # 6. Indexer verifies
        if not verify_reveal_against_sig(reveal, commit_sig, commit_msg, maker_pk):
            ok = False
            if verbose: print(f"[s2c-env #{i}] FAIL: legit reveal rejected by verifier")
            continue
        # 7a. Tampered c
        bad_c = bytearray(c) if c else bytearray(b"x")
        if bad_c:
            bad_c[0] ^= 0xFF
        bad_reveal = {**reveal, "c": bytes(bad_c)}
        if verify_reveal_against_sig(bad_reveal, commit_sig, commit_msg, maker_pk):
            ok = False
            if verbose: print(f"[s2c-env #{i}] FAIL: tampered c accepted")
            continue
        # 7b. Tampered R0_x — best-effort; if the flipped x is off-curve,
        #     verify also returns False (which is the desired outcome).
        bad_r0 = bytearray(r0_x); bad_r0[31] ^= 0x80
        bad_reveal2 = {**reveal, "r0_x": bytes(bad_r0)}
        if verify_reveal_against_sig(bad_reveal2, commit_sig, commit_msg, maker_pk):
            ok = False
            if verbose: print(f"[s2c-env #{i}] FAIL: tampered R0_x accepted")
            continue
        # 7c. Tampered commit_sig — flip one byte of s; BIP340 verify fails,
        #     so the S2C check short-circuits to False as well.
        bad_sig = bytearray(commit_sig); bad_sig[33] ^= 0xFF
        if verify_reveal_against_sig(reveal, bytes(bad_sig), commit_msg, maker_pk):
            ok = False
            if verbose: print(f"[s2c-env #{i}] FAIL: tampered commit_sig accepted")
            continue
        # 8. Round-trip byte-stable
        reveal_bytes2 = build_reveal(reveal["commit_txid"], reveal["input_idx"],
                                      reveal["r0_x"], reveal["c"])
        if reveal_bytes != reveal_bytes2:
            ok = False
            if verbose: print(f"[s2c-env #{i}] FAIL: build is not deterministic")
            continue

        if verbose:
            print(f"[s2c-env #{i}] OK  c_len={len(c)}B  reveal_len={len(reveal_bytes)}B  "
                  f"commit_sig={commit_sig.hex()[:16]}...")

    if verbose:
        print(f"\n[s2c-env] {'ALL VECTORS PASS' if ok else 'FAILED'}")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
