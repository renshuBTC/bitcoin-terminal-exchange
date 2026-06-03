#!/usr/bin/env python3
"""
btx_descriptor.py — Minimal Bitcoin Output Descriptor support for BTX.

Closes the concrete extraction from `rust-bitcoin/rust-miniscript`. Where
the scouting report bookmarks the full descriptor + policy machinery as
BTX3 work, THIS module ships the small piece that BTX can use TODAY:
canonical `tr(K)` descriptor serialization + bc1p address computation
for key-path-only Taproot outputs.

## What this buys BTX

1. **External tool interop.** Hardware wallets (Ledger, Coldcard, Jade),
   Bitcoin Core wallet, and BDK-using applications all speak the
   canonical Output Descriptor format defined by BIP-380. With this
   module, BTX can publish a maker's pubkey in the canonical
   `tr(<maker_xonly>)` form, and any of those tools can verify the
   resulting scriptPubKey.

2. **Re-runnable cross-test against rust-miniscript.** The address
   computation is deterministic; we pin a small set of golden vectors
   (produced by rust-miniscript via its `examples/taproot.rs`-style
   computation) and re-verify every commit.

3. **BIP-380 checksum support.** Descriptor strings carry an optional
   `#checksum8` suffix (8 chars of bech32 over the descriptor body).
   We compute and verify it the same way rust-miniscript does.

## What this module does NOT do

- Parse `tr(K, {<script_tree>})` with script-path branches — those
  require the full Miniscript machinery. Bookmarked for BTX3.
- Parse `pkh(K)` / `wpkh(K)` / `sh(...)` / `wsh(...)` — BTX is
  Taproot-only.
- Compile policies — that's `policy::compiler` in rust-miniscript,
  ~1k LOC of feature-gated code.

The scope is intentionally narrow: `tr(K)` only, because that's what
BTX2 BATCH_ANNOUNCE + CONDITIONAL_ORDER records actually use today.
Every wider piece is bookmarked in
`BTX-rust-miniscript-scouting-2026-06-03.md`.
"""

from __future__ import annotations
import re
from btx_taproot import (
    taproot_tweak_pubkey, p2tr_scriptpubkey, segwit_address,
)


# ----------------------------- BIP-380 checksum -----------------------------
# Borrowed from `rust-miniscript`/`src/descriptor/checksum.rs` and the
# Bitcoin Core reference: each character in a descriptor is mapped to a
# small alphabet, then a polymod is computed over the resulting sequence.

INPUT_CHARSET = (
    "0123456789()[],'/*abcdefgh@:$%{}"
    "IJKLMNOPQRSTUVWXYZ&+-.;<=>?!^_|~"
    "ijklmnopqrstuvwxyzABCDEFGH`#\"\\ "
)
CHECKSUM_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(c: int, val: int) -> int:
    c0 = c >> 35
    c = ((c & 0x7FFFFFFFF) << 5) ^ val
    if c0 & 1:  c ^= 0xF5DEE51989
    if c0 & 2:  c ^= 0xA9FDCA3312
    if c0 & 4:  c ^= 0x1BAB10E32D
    if c0 & 8:  c ^= 0x3706B1677A
    if c0 & 16: c ^= 0x644D626FFD
    return c


def descriptor_checksum(s: str) -> str:
    """
    Compute the 8-character BIP-380 descriptor checksum for `s`.
    Mirrors Bitcoin Core's `DescriptorChecksum` and rust-miniscript's
    `descriptor::checksum`. Note: `cls` (running value) and `clscount`
    (counter) are TWO separate variables — getting them confused
    produces a different polynomial and different bytes.
    """
    c = 1
    cls = 0       # running value: cls = cls*3 + (idx >> 5), folds into polymod every 3 chars
    clscount = 0  # how many chars have folded into the current cls (0..3)
    for ch in s:
        idx = INPUT_CHARSET.find(ch)
        if idx == -1:
            raise ValueError(f"invalid descriptor character: {ch!r}")
        c = _polymod(c, idx & 31)
        cls = cls * 3 + (idx >> 5)
        clscount += 1
        if clscount == 3:
            c = _polymod(c, cls)
            cls = 0
            clscount = 0
    if clscount > 0:
        c = _polymod(c, cls)
    for _ in range(8):
        c = _polymod(c, 0)
    c ^= 1
    return "".join(CHECKSUM_CHARSET[(c >> (5 * (7 - i))) & 31] for i in range(8))


def split_checksum(s: str) -> tuple[str, str | None]:
    """
    Split a descriptor string `body#checksum` into (body, checksum).
    Returns checksum=None if no `#` separator is present.
    """
    if "#" not in s:
        return s, None
    body, checksum = s.split("#", 1)
    if len(checksum) != 8:
        raise ValueError(f"checksum must be 8 chars, got {len(checksum)}: {checksum!r}")
    if any(ch not in CHECKSUM_CHARSET for ch in checksum):
        raise ValueError(f"checksum has chars outside the checksum alphabet: {checksum!r}")
    return body, checksum


def verify_checksum(s: str) -> bool:
    """True iff `s` ends in `#<checksum>` and the checksum matches the body."""
    body, ck = split_checksum(s)
    if ck is None:
        return False
    return descriptor_checksum(body) == ck


def with_checksum(body: str) -> str:
    """Return `body#<checksum>` per BIP-380."""
    return f"{body}#{descriptor_checksum(body)}"


# ----------------------------- tr(K) parse/serialize -----------------------------


# Match exactly `tr(<64-hex>)` — 32-byte x-only pubkey in hex.
_TR_KEY_ONLY = re.compile(r"^tr\(([0-9a-fA-F]{64})\)$")


def tr_key_only_serialize(maker_xonly: bytes, with_csum: bool = True) -> str:
    """
    Produce the canonical `tr(<hex>)` descriptor string for a key-path-only
    Taproot output keyed on the given 32-byte x-only pubkey.

    If `with_csum`, appends the BIP-380 checksum (`#xxxxxxxx`).
    """
    if len(maker_xonly) != 32:
        raise ValueError(f"maker_xonly must be 32 bytes, got {len(maker_xonly)}")
    body = f"tr({maker_xonly.hex()})"
    return with_checksum(body) if with_csum else body


def tr_key_only_parse(s: str) -> bytes:
    """
    Parse a `tr(<hex>)` or `tr(<hex>)#<csum>` descriptor and return the
    32-byte x-only pubkey. Raises ValueError on any deviation from the
    canonical form (including bad checksum if present).
    """
    body, ck = split_checksum(s)
    if ck is not None and descriptor_checksum(body) != ck:
        raise ValueError(f"bad checksum: expected {descriptor_checksum(body)}, got {ck}")
    m = _TR_KEY_ONLY.match(body)
    if not m:
        raise ValueError(f"not a tr(K) descriptor: {body!r}")
    return bytes.fromhex(m.group(1))


# ----------------------------- canonical scriptPubKey / address -----------------------------


def tr_key_only_scriptpubkey(maker_xonly: bytes) -> bytes:
    """
    Canonical Taproot scriptPubKey for the key-path-only `tr(K)` case.

    Per BIP-341 the output key Q = K + tagged_hash("TapTweak", K) · G.
    BTX's `taproot_tweak_pubkey(K, b"")` returns exactly this; we wrap
    that here so the descriptor-string consumer doesn't need to know
    about the underlying math.
    """
    if len(maker_xonly) != 32:
        raise ValueError(f"maker_xonly must be 32 bytes, got {len(maker_xonly)}")
    parity, tweaked = taproot_tweak_pubkey(maker_xonly, b"")
    return p2tr_scriptpubkey(tweaked)


def tr_key_only_address(maker_xonly: bytes, hrp: str = "bc") -> str:
    """
    Canonical BIP-350 bech32m address for the key-path-only `tr(K)` case.
    `hrp` is "bc" for mainnet, "tb" for testnet/signet, "bcrt" for regtest.
    """
    parity, tweaked = taproot_tweak_pubkey(maker_xonly, b"")
    return segwit_address(1, tweaked, hrp=hrp)


# ----------------------------- BIP-371 PSBT field mapping -----------------------------
# Type codes per BIP-371 (Taproot fields for PSBT v0):
#   0x13  PSBT_IN_TAP_KEY_SIG          — completed key-spend Schnorr sig (taker fills this in)
#   0x14  PSBT_IN_TAP_SCRIPT_SIG       — script-path partial sig (n/a for tr(K))
#   0x15  PSBT_IN_TAP_LEAF_SCRIPT      — tapscript leaf info (n/a for tr(K))
#   0x16  PSBT_IN_TAP_BIP32_DERIVATION — per-x-only-key derivation + leaf hashes
#   0x17  PSBT_IN_TAP_INTERNAL_KEY     — 32-byte internal x-only
#   0x18  PSBT_IN_TAP_MERKLE_ROOT      — 32-byte merkle root (absent for tr(K))

PSBT_IN_TAP_KEY_SIG         = 0x13
PSBT_IN_TAP_SCRIPT_SIG      = 0x14
PSBT_IN_TAP_LEAF_SCRIPT     = 0x15
PSBT_IN_TAP_BIP32_DERIVATION = 0x16
PSBT_IN_TAP_INTERNAL_KEY    = 0x17
PSBT_IN_TAP_MERKLE_ROOT     = 0x18


def tr_key_only_psbt_input_fields(
    maker_xonly: bytes,
    master_fingerprint: bytes = None,
    derivation_path: bytes = None,
) -> dict:
    """
    Return the canonical BIP-371 PSBT input field set for a `tr(K)` descriptor.

    This is the same field set that rust-miniscript's
    `PsbtInputExt::update_with_descriptor_unchecked(&tr(K))` would populate.
    BTX can use this mapping when building hand-rolled PSBTs (BIP-174
    serialiser) so external signers (Ledger / BDK / Core wallet) see the
    canonical descriptor-implied fields and can complete the PSBT
    correctly.

    For a key-path-only `tr(K)`:
      - tap_internal_key  = K (32 bytes)
      - tap_key_origins   = {K: ([], (fp, path))}   — empty leaf list, BIP32 key source
                            (the (fp, path) pair is optional; if not given,
                            we use the canonical placeholder: zero fingerprint + empty path)
      - tap_merkle_root   = None  (absent — no script tree)

    Args:
        maker_xonly:        32-byte x-only pubkey
        master_fingerprint: optional 4-byte master fingerprint (BIP-32);
                            defaults to b"\x00\x00\x00\x00" if None
        derivation_path:    optional BIP-32 derivation path bytes (sequence
                            of 4-byte LE u32 child numbers); defaults to
                            empty bytes (root key)

    Returns:
        dict with keys "tap_internal_key" (32 bytes), "tap_key_origins"
        (dict K → (leaf_hashes_list, (fp, path))), "tap_merkle_root" (None).
    """
    if len(maker_xonly) != 32:
        raise ValueError(f"maker_xonly must be 32 bytes, got {len(maker_xonly)}")
    fp = master_fingerprint if master_fingerprint is not None else b"\x00\x00\x00\x00"
    if len(fp) != 4:
        raise ValueError(f"master_fingerprint must be 4 bytes, got {len(fp)}")
    path = derivation_path if derivation_path is not None else b""
    if len(path) % 4 != 0:
        raise ValueError(f"derivation_path must be a multiple of 4 bytes (u32 LE per child), got {len(path)}")

    return {
        "tap_internal_key": bytes(maker_xonly),
        "tap_key_origins": {
            bytes(maker_xonly): (
                [],                   # leaf_hashes: empty for tr(K) key-path-only
                (bytes(fp), bytes(path)),
            ),
        },
        "tap_merkle_root": None,       # absent for tr(K)
    }


def encode_psbt_tap_internal_key_kv(maker_xonly: bytes) -> tuple[bytes, bytes]:
    """
    Canonical BIP-174/371 (key, value) pair for the PSBT_IN_TAP_INTERNAL_KEY
    field. The key is just the type byte 0x17 (no per-key data); the value
    is the 32-byte x-only pubkey.

    Caller is responsible for the surrounding compact-size length prefixes
    that BIP-174 wraps every key and value with.
    """
    if len(maker_xonly) != 32:
        raise ValueError(f"maker_xonly must be 32 bytes")
    return (bytes([PSBT_IN_TAP_INTERNAL_KEY]), bytes(maker_xonly))


def encode_psbt_tap_bip32_derivation_kv(
    maker_xonly: bytes,
    master_fingerprint: bytes,
    derivation_path: bytes,
) -> tuple[bytes, bytes]:
    """
    Canonical BIP-371 (key, value) pair for the PSBT_IN_TAP_BIP32_DERIVATION
    field, key-path-only case (zero leaf hashes).

    Key:   0x16 || x-only-pubkey  (33 bytes total)
    Value: compact-size(num_leaf_hashes=0) || fingerprint(4) || path(n*4)
           Since num_leaf_hashes=0, the value reduces to: 0x00 || fp || path
    """
    if len(maker_xonly) != 32 or len(master_fingerprint) != 4:
        raise ValueError("bad input lengths")
    if len(derivation_path) % 4 != 0:
        raise ValueError("derivation_path must be multiple of 4 bytes")
    key = bytes([PSBT_IN_TAP_BIP32_DERIVATION]) + bytes(maker_xonly)
    # Number of leaf hashes encoded as a single byte (0) since 0 < 0xfd.
    value = b"\x00" + bytes(master_fingerprint) + bytes(derivation_path)
    return (key, value)


# ----------------------------- selftest -----------------------------


# Golden vectors. These are produced/verified externally against
# `rust-miniscript`'s `Descriptor::<XOnlyPublicKey>::from_str("tr(...)")
# .address(Network::Bitcoin)` flow. Pinning them here gives BTX a
# re-runnable canonical cross-test that mirrors the BIP-340/341 ones.
_GOLDEN_TR_KEY = [
    # (32-byte x-only pubkey hex, network hrp, expected address)
    # All addresses produced by rust-miniscript v12.3.7 via
    # `Descriptor::<XOnlyPublicKey>::from_str("tr(...)").address(Bitcoin)`
    # and confirmed byte-equal with BTX. See
    # BTX-rust-miniscript-scouting-2026-06-03.md for the probe.

    # BIP-341 wallet-test-vectors.json scriptPubKey case 0
    ("d6889cb081036e0faefa3a35157ad71086b123b2b144b649798b494c300a961d",
     "bc", "bc1p2wsldez5mud2yam29q22wgfh9439spgduvct83k3pm50fcxa5dps59h4z5"),
    # NUMS-style "unspendable" x-only
    ("50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0",
     "bc", "bc1prykz5vxt6lgr2tu56np35slhvlc77s7hlajr3qucsrkqwhvp48mq5grvgr"),
    # secp256k1 G x-coord (standard generator)
    ("f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9",
     "bc", "bc1pgxxyvcmdncdxs06cudd5yvmwwahaesaj6n3eu7st7x4sw9hrchaqjy33gs"),
    # 2·G x-coord
    ("c6047f9441ed7d6d3045406e95c07cd85c778e4b8cef3ca7abac09b95c709ee5",
     "bc", "bc1pet7ep3czdu9k4wvdlz2fp5p8x2yp7t6ttyqg2c6cmh0lgeuu9lasmp9hsg"),
    # BIP-340 test vector pubkey #1 (odd-y when uncompressed)
    ("dff1d77f2a671c5f36183726db2341be58feae1da2deced843240f7b502ba659",
     "bc", "bc1p0t2rw5pjcw8t5n7xphk2wharpgaxhhe0kw8huctj3r3dxampzl9slnrkml"),
    # BIP-340 test vector pubkey from vector 0 (=sk=3)
    ("dd308afec5777e13121fa72b9cc1b7cc0139715309b086c960e18fd969774eb8",
     "bc", "bc1pc20yxrvn3t0w5zgmghkfeq9ynp5k0yt7faes6w7wwxhn30z4gmtqxtls37"),
    # Synthetic high-entropy: 0xfedc...
    ("fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210",
     "bc", "bc1ptenuywhuyfr8s4na6q4kwwg4w669lgpe5zrt8eyn206mpvvuq4uqee452c"),
    # 0xaa repeated 32 times (curve-valid x)
    ("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
     "bc", "bc1pqzcjvryjx9gqwncdd0s72zm2atrg5ptd5vwftcyrd2pq3e7wwv9s33rgav"),
    # Just-below-N (large valid x close to the secp256k1 group order)
    ("fffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd036413f",
     "bc", "bc1p64krznl6kg3gm6rjuqkdur3wh5x9l3k68lfnznrpp777y0w95unsh3wnv3"),
    # BIP-341 wallet-test-vectors scriptPubKey case 1 internal key
    ("187791b6f712a8ea41c8ecdd0ee77fab3e85263b37e1ec18a3651926b3a6cf27",
     "bc", "bc1pjxzw9tm6qatyapu3c409dg8k23p4hjlk4ehwwlsum3emjqsaetrqppyu2z"),
]


def selftest(verbose: bool = True) -> bool:
    ok = True

    # 1. Round-trip serialize/parse + checksum stability
    for xonly_hex, hrp, _ in _GOLDEN_TR_KEY:
        xonly = bytes.fromhex(xonly_hex)
        desc = tr_key_only_serialize(xonly, with_csum=True)
        if not verify_checksum(desc):
            ok = False
            if verbose:
                print(f"[descriptor] FAIL: checksum on {desc!r} does not self-verify")
            continue
        parsed = tr_key_only_parse(desc)
        if parsed != xonly:
            ok = False
            if verbose:
                print(f"[descriptor] FAIL: parse({desc!r}) != original")
            continue

    # 2. Canonical address vs golden (this is the rust-miniscript
    #    cross-check — same xonly + same network must give same bc1p...)
    for xonly_hex, hrp, expected_addr in _GOLDEN_TR_KEY:
        xonly = bytes.fromhex(xonly_hex)
        actual = tr_key_only_address(xonly, hrp=hrp)
        if actual != expected_addr:
            ok = False
            if verbose:
                print(f"[descriptor] FAIL: address for {xonly_hex[:16]}...: got {actual}, want {expected_addr}")

    # 3. Reject tampered checksum
    xonly = bytes.fromhex(_GOLDEN_TR_KEY[0][0])
    desc = tr_key_only_serialize(xonly, with_csum=True)
    body, ck = split_checksum(desc)
    # Flip a checksum char to a different valid one
    bad_ck_char = "q" if ck[-1] != "q" else "p"
    bad_desc = body + "#" + ck[:-1] + bad_ck_char
    try:
        tr_key_only_parse(bad_desc)
        ok = False
        if verbose:
            print(f"[descriptor] FAIL: accepted tampered checksum {bad_desc!r}")
    except ValueError:
        pass  # expected

    # 4. Reject non-Taproot descriptors
    for bad in ["wpkh(00...)", "pkh(deadbeef)", "tr()", "tr(zz)"]:
        try:
            tr_key_only_parse(bad)
            ok = False
            if verbose:
                print(f"[descriptor] FAIL: accepted non-tr/malformed descriptor {bad!r}")
        except ValueError:
            pass

    # 5. PSBT field mapping (BIP-371) — shape + canonical byte encoding
    sample_xonly = bytes.fromhex(_GOLDEN_TR_KEY[0][0])
    fields = tr_key_only_psbt_input_fields(sample_xonly)
    if fields["tap_internal_key"] != sample_xonly:
        ok = False
        if verbose: print("[descriptor] FAIL: tap_internal_key mapping")
    if list(fields["tap_key_origins"].keys()) != [sample_xonly]:
        ok = False
        if verbose: print("[descriptor] FAIL: tap_key_origins keys")
    leaves, (fp, path) = fields["tap_key_origins"][sample_xonly]
    if leaves != [] or fp != b"\x00\x00\x00\x00" or path != b"":
        ok = False
        if verbose: print(f"[descriptor] FAIL: default key origin {leaves} {fp.hex()} {path.hex()}")
    if fields["tap_merkle_root"] is not None:
        ok = False
        if verbose: print("[descriptor] FAIL: tap_merkle_root should be None for tr(K)")

    # PSBT_IN_TAP_INTERNAL_KEY canonical (key, value) — key is just type 0x17
    k_int, v_int = encode_psbt_tap_internal_key_kv(sample_xonly)
    if k_int != b"\x17" or v_int != sample_xonly:
        ok = False
        if verbose: print(f"[descriptor] FAIL: PSBT internal key kv encoding")

    # PSBT_IN_TAP_BIP32_DERIVATION canonical (key, value) for empty fingerprint + path
    k_d, v_d = encode_psbt_tap_bip32_derivation_kv(sample_xonly, b"\x00\x00\x00\x00", b"")
    expected_k = b"\x16" + sample_xonly
    expected_v = b"\x00" + b"\x00\x00\x00\x00"  # 0 leaf hashes, then fp, no path
    if k_d != expected_k or v_d != expected_v:
        ok = False
        if verbose: print(f"[descriptor] FAIL: PSBT tap-bip32-derivation kv encoding")

    # 6. Reject malformed PSBT mapping inputs
    try:
        tr_key_only_psbt_input_fields(b"\x00" * 31)  # short pubkey
        ok = False
        if verbose: print("[descriptor] FAIL: accepted short pubkey for PSBT fields")
    except ValueError:
        pass
    try:
        tr_key_only_psbt_input_fields(sample_xonly, master_fingerprint=b"abc")  # 3-byte fp
        ok = False
        if verbose: print("[descriptor] FAIL: accepted 3-byte fingerprint")
    except ValueError:
        pass
    try:
        tr_key_only_psbt_input_fields(sample_xonly, derivation_path=b"abc")  # not multiple of 4
        ok = False
        if verbose: print("[descriptor] FAIL: accepted non-4-multiple derivation path")
    except ValueError:
        pass

    if verbose:
        print(f"[btx_descriptor] {'ALL CHECKS PASS' if ok else 'FAILED'}")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
