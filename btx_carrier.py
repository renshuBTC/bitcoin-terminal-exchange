#!/usr/bin/env python3
"""
btx_carrier.py — pluggable on-chain carriers for the BTX order artifact.

The BTX reconstruction layer reads the *artifact bytes*; it does not care how those bytes got
on-chain. This module gives two interchangeable carriers so the protocol does NOT depend on a
relaxed -datacarriersize:

  1. OP_RETURN carrier        — one output, `OP_RETURN <artifact>`. Simplest, but the ~208-byte
                                BTX v2 artifact exceeds the default 80-byte datacarrier limit, so
                                this needs a node configured with -datacarriersize>=240 (the spec
                                marks 2026 carrier standardness as [VERIFY]).

  2. Taproot witness envelope — inscription-style. The artifact rides in a tapscript inside the
                                WITNESS of a Taproot script-path spend:
                                    <internal_xonly_pubkey> OP_CHECKSIG
                                    OP_FALSE OP_IF <chunk0> <chunk1> ... OP_ENDIF
                                Witness data is not subject to -datacarriersize at all, and each
                                push may be up to 520 bytes (MAX_SCRIPT_ELEMENT_SIZE). This is the
                                same mechanism ordinals/inscriptions use, so it is well-exercised on
                                mainnet. Reconstruction extracts the artifact from the revealed
                                tapscript exactly as it would from an OP_RETURN.

What is proven here (offline): the envelope encoding round-trips for any artifact size (single- and
multi-chunk), and the BIP341 tapleaf hash is computed per spec. The commit/reveal *broadcast* is built
in `btx_envelope_publish.py` (commit funding + a script-path reveal whose witness `[schnorr_sig,
this_tapscript, control_block]` round-trips back to the artifact, offline-proven). The brk-btx
indexer reads it via `btx::extract_from_witness`. PROVEN on-node: on signet 2026-05-24 a real envelope
reveal confirmed (block 121) and the order was reconstructed from witness data and served — see
BTX-envelope-publish-runbook.md.
"""
import hashlib, struct
from bitcoin.core.script import (CScript, OP_RETURN, OP_CHECKSIG, OP_FALSE, OP_IF, OP_ENDIF)

MAGIC = b'BTX1'
MAX_CHUNK = 520          # MAX_SCRIPT_ELEMENT_SIZE — max bytes per witness/script push
LEAF_VERSION = 0xc0      # BIP342 default tapscript leaf version


# ----------------------------- OP_RETURN -----------------------------
def op_return_carrier(blob: bytes) -> CScript:
    """scriptPubKey for the simple OP_RETURN carrier."""
    return CScript([OP_RETURN, bytes(blob)])


# ----------------------------- Taproot envelope -----------------------------
def _chunks(b: bytes, n: int):
    if not b:
        return [b'']
    return [b[i:i + n] for i in range(0, len(b), n)]


def envelope_tapscript(blob: bytes, internal_xonly_pubkey: bytes = b'\x02' * 32) -> CScript:
    """Build the inscription-style tapscript that carries `blob` in an always-skipped
    OP_FALSE OP_IF ... OP_ENDIF envelope. The artifact is pushed in <=520-byte chunks."""
    if len(internal_xonly_pubkey) != 32:
        raise ValueError("internal pubkey must be 32-byte x-only")
    ops = [bytes(internal_xonly_pubkey), OP_CHECKSIG, OP_FALSE, OP_IF]
    ops += _chunks(bytes(blob), MAX_CHUNK)
    ops += [OP_ENDIF]
    return CScript(ops)


def parse_envelope(script_bytes) -> bytes | None:
    """Extract the concatenated envelope payload from a tapscript. Returns the artifact bytes if an
    OP_FALSE OP_IF ... OP_ENDIF envelope is present, else None. Carrier-agnostic: feed it any
    candidate script (a tapscript pulled from a witness stack)."""
    try:
        items = list(CScript(bytes(script_bytes)).raw_iter())
    except Exception:
        return None
    out = bytearray()
    # state: 0 = searching for OP_FALSE, 1 = saw OP_FALSE expecting OP_IF, 2 = collecting pushes
    state = 0
    for (op, data, _sop) in items:
        if state == 0:
            if op == OP_FALSE:           # 0x00
                state = 1
        elif state == 1:
            if op == OP_IF:              # 0x63
                state = 2
            else:
                state = 1 if op == OP_FALSE else 0
        elif state == 2:
            if op == OP_ENDIF:           # 0x68
                break
            if data:
                out += data
    return bytes(out) if out else None


# ----------------------------- BIP341 tapleaf -----------------------------
def _tagged_hash(tag: str, msg: bytes) -> bytes:
    t = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(t + t + msg).digest()


def _compact_size(n: int) -> bytes:
    if n < 0xfd:
        return bytes([n])
    if n <= 0xffff:
        return b'\xfd' + struct.pack('<H', n)
    if n <= 0xffffffff:
        return b'\xfe' + struct.pack('<I', n)
    return b'\xff' + struct.pack('<Q', n)


def tapleaf_hash(tapscript) -> bytes:
    """BIP341 tapleaf hash = tagged_hash("TapLeaf", leaf_version || compact_size(len) || script).
    This is the leaf that the commit Taproot output must commit to (combined with the internal key
    via the BIP341 output-key tweak — that tweak is done on the node where the wallet key lives)."""
    s = bytes(tapscript)
    return _tagged_hash("TapLeaf", bytes([LEAF_VERSION]) + _compact_size(len(s)) + s)


# ----------------------------- offline selftest -----------------------------
def selftest():
    import json
    checks = {}
    # 1) small artifact (typical BTX v2 ~208 bytes) round-trips through the envelope
    small = MAGIC + bytes(range(256)) * 0 + b'\xaa' * 204   # 208 bytes, starts with magic
    env = envelope_tapscript(small)
    checks["small_roundtrip"] = (parse_envelope(bytes(env)) == small)
    checks["small_single_chunk"] = (len(small) <= MAX_CHUNK)
    # 2) large artifact spanning multiple 520-byte chunks
    large = MAGIC + b'\x5a' * 1300                          # 1304 bytes -> 3 chunks
    envL = envelope_tapscript(large)
    checks["large_roundtrip"] = (parse_envelope(bytes(envL)) == large)
    checks["large_multichunk"] = (len(large) > 2 * MAX_CHUNK)
    # 3) non-envelope script returns None
    checks["non_envelope_is_none"] = (parse_envelope(bytes(op_return_carrier(small))) is None)
    # 4) tapleaf hash is 32 bytes and deterministic
    h1 = tapleaf_hash(env); h2 = tapleaf_hash(env)
    checks["tapleaf_32_bytes"] = (len(h1) == 32 and h1 == h2)
    # 5) the extracted payload still begins with the BTX magic
    checks["payload_keeps_magic"] = (parse_envelope(bytes(env))[:4] == MAGIC)
    allpass = all(v is True for v in checks.values())
    print(json.dumps({"checks": checks, "tapleaf_hex": h1.hex(), "ALL_PASS": allpass}, indent=2))
    return allpass


if __name__ == "__main__":
    selftest()
