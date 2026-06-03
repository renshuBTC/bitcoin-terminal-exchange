#!/usr/bin/env python3
"""
btx_attest — command-line wrapper around the BIP-322 P2TR primitive.

Closes the last exposure surface for the BIP-322 attestation feature:
  - Python module      btx_bip322                              (developers)
  - HTTP endpoints     btxd /api/attest/{challenge,verify}     (apps)
  - Rust module        brk_indexer::btx_bip322                 (indexer)
  - HTML page          btx_attest.html                         (interactive)
  - **CLI**            btx_attest.py {sign,verify,challenge}   (scripts)

Examples
--------

    $ python3 btx_attest.py challenge
    920f1c00b396c9cf1f9b93074278290919f3cb12dc182285ecd07e520eab4c18

    $ python3 btx_attest.py sign \\
          --wif L5XqN6ckPPsDiTbRxcsthwiWpDBfWLo4uquUEydsPt8rSMoTpqpc \\
          --message PURVOQ544B6HUATVBJZN5EZJUU
    smpAQA…

    $ python3 btx_attest.py verify \\
          --address bc1pcquvhrqv0q68t4m0hfq6tpn006qrskyc7yrqnp2uyrf2emg3wynsdjyk38 \\
          --message PURVOQ544B6HUATVBJZN5EZJUU \\
          --signature smpAQA…
    valid    format=simple

    $ # Piping is supported:
    $ CHL=$(python3 btx_attest.py challenge)
    $ SIG=$(python3 btx_attest.py sign --wif "$WIF" --message "$CHL")
    $ python3 btx_attest.py verify --address "$ADDR" --message "$CHL" --signature "$SIG"

Exit codes
----------
    0   verify: signature is valid;  sign/challenge: success
    1   verify: signature is INvalid (well-formed but doesn't bind)
    2   malformed input (bad WIF / address / signature / arguments)
    3   internal error
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import btx_bip322 as B  # noqa: E402


# ----------------------------------------------------------------- sign


def cmd_sign(args) -> int:
    if args.wif is None:
        print("error: --wif is required for sign", file=sys.stderr)
        return 2
    try:
        seckey, _ = B.decode_wif(args.wif)
    except Exception as e:
        print(f"error: bad WIF: {e}", file=sys.stderr)
        return 2

    msg = args.message.encode("utf-8") if isinstance(args.message, str) else args.message

    if args.aux_rand_hex == "fresh":
        aux_rand = os.urandom(32)
    elif args.aux_rand_hex == "zero":
        aux_rand = b"\x00" * 32
    else:
        try:
            aux_rand = bytes.fromhex(args.aux_rand_hex)
            if len(aux_rand) != 32:
                raise ValueError(f"aux-rand must be 32 bytes (got {len(aux_rand)})")
        except ValueError as e:
            print(f"error: bad --aux-rand-hex: {e}", file=sys.stderr)
            return 2

    try:
        if args.format == "simple":
            sig = B.sign_simple_p2tr(msg, seckey, aux_rand=aux_rand)
        else:  # full
            sig = B.sign_full_p2tr(
                msg, seckey,
                version=args.version,
                locktime=args.locktime,
                sequence=args.sequence,
                aux_rand=aux_rand,
            )
    except Exception as e:
        print(f"error: signing failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 3

    print(sig)
    return 0


# ----------------------------------------------------------------- verify


def cmd_verify(args) -> int:
    if not args.address or not args.message or not args.signature:
        print("error: --address, --message, --signature all required",
              file=sys.stderr)
        return 2

    # Pre-flight address shape check so a non-Taproot address surfaces
    # as "malformed input" (rv 2), not as "signature doesn't bind" (rv 1).
    # The library returns False either way, but the CLI is in a position
    # to give the operator a more actionable diagnostic.
    addr = args.address.strip()
    if not (addr.startswith("bc1p") or addr.startswith("tb1p")):
        print(f"error: --address must be a Taproot (bc1p/tb1p) address; "
              f"got {addr[:10]!r}...", file=sys.stderr)
        return 2
    try:
        witver, witprog = B.decode_segwit_address(addr, "bc" if addr.startswith("bc1p") else "tb")
    except ValueError as e:
        print(f"error: bad bech32m address: {e}", file=sys.stderr)
        return 2
    if witver != 1 or len(witprog) != 32:
        print(f"error: address is not a v1/32-byte Taproot output", file=sys.stderr)
        return 2

    msg = args.message.encode("utf-8") if isinstance(args.message, str) else args.message
    sig = args.signature.strip()

    prefix = sig[:3]
    if prefix == "smp":
        verify_fn = B.verify_simple_p2tr
        fmt = "simple"
    elif prefix == "ful":
        verify_fn = B.verify_full_p2tr
        fmt = "full"
    else:
        print(f"error: signature must start with 'smp' or 'ful' "
              f"(got {prefix!r})", file=sys.stderr)
        return 2

    try:
        ok = verify_fn(msg, args.address, sig)
    except Exception as e:
        print(f"error: verify raised {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    if ok:
        if args.json:
            print('{"valid":true,"format":"' + fmt + '"}')
        else:
            print(f"valid    format={fmt}")
        return 0
    else:
        if args.json:
            print('{"valid":false,"format":"' + fmt + '"}')
        else:
            print(f"INVALID  format={fmt}", file=sys.stderr)
        return 1


# ----------------------------------------------------------------- challenge


def cmd_challenge(args) -> int:
    nonce = secrets.token_hex(args.bytes)
    if args.json:
        print('{"challenge_hex":"' + nonce + '"}')
    else:
        print(nonce)
    return 0


# ----------------------------------------------------------------- entry


def main() -> int:
    p = argparse.ArgumentParser(
        prog="btx_attest",
        description="BTX BIP-322 P2TR attestation CLI (sign, verify, challenge).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # ---- challenge ----
    pc = sub.add_parser("challenge", help="emit a random nonce for a maker to sign")
    pc.add_argument("--bytes", type=int, default=32,
                    help="nonce length in bytes (default 32 = 64 hex chars)")
    pc.add_argument("--json", action="store_true",
                    help="emit JSON {challenge_hex:...} instead of bare hex")
    pc.set_defaults(func=cmd_challenge)

    # ---- sign ----
    ps = sub.add_parser("sign", help="BIP-322 sign a message under a bc1p address")
    ps.add_argument("--wif", required=True,
                    help="WIF-encoded private key of the bc1p address")
    ps.add_argument("--message", required=True,
                    help="message to sign (utf-8; usually a challenge hex)")
    ps.add_argument("--format", choices=["simple", "full"], default="simple",
                    help="BIP-322 format (default simple = 'smp' prefix)")
    ps.add_argument("--version", type=int, default=2,
                    help="(full only) to_sign tx nVersion (default 2)")
    ps.add_argument("--locktime", type=int, default=0,
                    help="(full only) to_sign tx nLockTime (default 0)")
    ps.add_argument("--sequence", type=int, default=0,
                    help="(full only) to_sign vin[0].nSequence (default 0)")
    ps.add_argument("--aux-rand-hex", default="fresh",
                    help="32-byte aux-rand as hex; or 'fresh' (default) for "
                         "os.urandom; 'zero' for 32 nulls (deterministic).")
    ps.set_defaults(func=cmd_sign)

    # ---- verify ----
    pv = sub.add_parser("verify", help="BIP-322 verify a signature against a bc1p address")
    pv.add_argument("--address", required=True, help="bc1p (Taproot) address")
    pv.add_argument("--message", required=True, help="message that was signed")
    pv.add_argument("--signature", required=True, help="smp... or ful... signature")
    pv.add_argument("--json", action="store_true",
                    help="emit JSON {valid:..., format:...} instead of human-readable")
    pv.set_defaults(func=cmd_verify)

    args = p.parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
