#!/usr/bin/env python3
"""Derive BRK_BLOCK_MAGIC (the block-file message-start bytes) for a signet.

A signet's network magic is NOT fixed: it is computed from the signet challenge as
    sha256d( CompactSize(len(challenge)) || challenge )[:4]
(Bitcoin Core serializes the challenge as a byte vector with a CompactSize length prefix,
then takes the first 4 bytes of the double-SHA256). The public/default signet yields 0a03cf40;
a custom signet (your own `signetchallenge`) yields a different value, which brk_reader needs
as BRK_BLOCK_MAGIC to parse that signet's blk*.dat files.

Usage:
    python3 btx_signet_magic.py <challenge_hex>        # print magic for a challenge
    python3 btx_signet_magic.py --datadir /path/to/sd  # read signetchallenge from bitcoin.conf
    python3 btx_signet_magic.py --selftest             # verify against public signet (0a03cf40)

Self-test runs automatically and must pass, or the derivation is wrong for your environment.
"""
import hashlib
import os
import re
import sys

# Bitcoin Core's built-in default (public) signet challenge -> magic 0a03cf40.
DEFAULT_SIGNET_CHALLENGE = (
    "512103ad5e0edad18cb1f0fc0d28a3d4f1f3e445640337489abb10404f2d1e086be430"
    "210359ef5021964fe22d6f8e05b2463c9540ce96883fe3b278760f048f5189f2e6c452ae"
)
DEFAULT_SIGNET_MAGIC = "0a03cf40"


def compact_size(n: int) -> bytes:
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xfd" + n.to_bytes(2, "little")
    if n <= 0xFFFFFFFF:
        return b"\xfe" + n.to_bytes(4, "little")
    return b"\xff" + n.to_bytes(8, "little")


def signet_magic(challenge_hex: str) -> str:
    """Return the 4-byte message-start magic as an 8-char hex string (BRK_BLOCK_MAGIC form)."""
    challenge = bytes.fromhex(challenge_hex.strip())
    ser = compact_size(len(challenge)) + challenge
    digest = hashlib.sha256(hashlib.sha256(ser).digest()).digest()
    return digest[:4].hex()


def challenge_from_datadir(datadir: str) -> str:
    conf = os.path.join(datadir, "bitcoin.conf")
    with open(conf, "r", encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"\s*signetchallenge\s*=\s*([0-9a-fA-F]+)", line)
            if m:
                return m.group(1)
    raise SystemExit(f"no signetchallenge= line found in {conf}")


def selftest() -> bool:
    got = signet_magic(DEFAULT_SIGNET_CHALLENGE)
    ok = got == DEFAULT_SIGNET_MAGIC
    print(f"[selftest] public signet: derived {got}, expected {DEFAULT_SIGNET_MAGIC} -> "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] == "--selftest":
        ok = selftest()
        if not args:
            print("\nUsage: btx_signet_magic.py <challenge_hex> | --datadir <dir> | --selftest")
        sys.exit(0 if ok else 1)

    # Always self-test first so a correct algorithm is proven before trusting the output.
    if not selftest():
        sys.exit("self-test FAILED — derivation is wrong; do not trust the magic below")

    if args[0] == "--datadir":
        if len(args) < 2:
            sys.exit("--datadir requires a path")
        challenge = challenge_from_datadir(args[1])
    else:
        challenge = args[0]

    magic = signet_magic(challenge)
    print(f"\nchallenge = {challenge}")
    print(f"BRK_BLOCK_MAGIC = {magic}")
    print(f"\nRun brk_cli with:  BRK_BLOCK_MAGIC={magic} cargo run -p brk_cli -- ...")


if __name__ == "__main__":
    main()
