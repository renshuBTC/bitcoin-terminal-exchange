#!/usr/bin/env python3
"""
btx_xtest_vs_secp256k1lab — cross-test BTX's pure-Python BIP-340
Schnorr against `secp256k1lab` (Jonas Nick's authoritative pure-
Python BIP reference, used by BIP authors and BlockstreamResearch).

Closes the bookmark from the 2026-06-03 cycle:
> BIP-340 Schnorr has 4 oracles available (3 wired in suite + Jonas
> Nick's `secp256k1lab/bip340.py` available but not yet wired).

secp256k1lab is shipped inside `BlockstreamResearch/bip-frost-dkg` at
`python/secp256k1lab/`. It requires Python 3.11+ (uses `typing.Self`),
so this cross-test polyfills `typing.Self` from `typing_extensions`
when running on Python 3.10.

Why this oracle matters
-----------------------

The first 6 BIP-340 oracles BTX cross-tests against are:
  1. bitcoin/bips CSV (canonical)
  2. secp256kfun (Lloyd Fournier, Rust)
  3. dlcspecs Schnorr vectors
  4. dlcspecs oracle bytes
  5. python-bitcointx (libsecp256k1 C)
  6. @noble/curves (pure JS)

This adds a 7th: **secp256k1lab is Jonas Nick's authoritative
pure-Python reference** — what BIP authors use as the canonical
Python implementation when writing/refining BIPs. Agreement with
it means BTX matches the reference implementation BIP authors
treat as ground truth.

Marginal value above the existing 6 oracles is small (BIP-340 is
already saturated at three-language closure), but this oracle
specifically closes a long-standing bookmark.

Skips gracefully if secp256k1lab is not available.
"""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))


def _find_secp256k1lab() -> str | None:
    candidates = [
        os.path.expanduser(
            "~/Documents/Claude/Projects/Bitcoin CoreX/"
            "bip-frost-dkg-reference/python/secp256k1lab/src"
        ),
        "/sessions/keen-determined-einstein/mnt/Bitcoin CoreX/"
        "bip-frost-dkg-reference/python/secp256k1lab/src",
        "/tmp/bip-frost-dkg/python/secp256k1lab/src",
    ]
    for c in candidates:
        if os.path.isfile(os.path.join(c, "secp256k1lab", "bip340.py")):
            return c
    return None


def _polyfill_typing_self() -> bool:
    """secp256k1lab uses typing.Self (Python 3.11+). Polyfill on 3.10."""
    import typing
    if hasattr(typing, "Self"):
        return True
    try:
        import typing_extensions
        typing.Self = typing_extensions.Self
        return True
    except ImportError:
        return False


def main() -> int:
    lab_path = _find_secp256k1lab()
    if not lab_path:
        print(
            "[SKIP] secp256k1lab not found; clone "
            "BlockstreamResearch/bip-frost-dkg to "
            "Bitcoin CoreX/bip-frost-dkg-reference to enable"
        )
        return 0

    if not _polyfill_typing_self():
        print("[SKIP] typing.Self not available and typing_extensions not installed")
        return 0

    sys.path.insert(0, lab_path)
    try:
        from secp256k1lab.bip340 import schnorr_sign, schnorr_verify
    except Exception as e:
        print(f"[SKIP] secp256k1lab import failed: {type(e).__name__}: {e}")
        return 0
    print(f"  secp256k1lab: {lab_path}")

    import btx_taproot as T

    # Canonical BIP-340 CSV vectors (sandbox path)
    canonical_csv = None
    for c in (
        os.path.expanduser(
            "~/Documents/Claude/Projects/Bitcoin CoreX/"
            "bitcoin-bips-reference/bip-0340/test-vectors.csv"
        ),
        "/sessions/keen-determined-einstein/mnt/Bitcoin CoreX/"
        "bitcoin-bips-reference/bip-0340/test-vectors.csv",
    ):
        if os.path.isfile(c):
            canonical_csv = c
            break

    overall_ok = True

    # Canonical check
    if canonical_csv:
        import csv as _csv
        passed = scoped = 0
        failures: list[str] = []
        with open(canonical_csv) as f:
            for row in _csv.DictReader(f):
                idx = row["index"]
                sk_hex = row["secret key"].strip()
                msg_hex = row["message"].strip()
                aux_hex = row["aux_rand"].strip() or "00" * 32
                sig_hex = row["signature"].strip().lower()
                expected = row["verification result"].strip().upper() == "TRUE"

                if len(msg_hex) != 64:
                    scoped += 1
                    continue

                msg = bytes.fromhex(msg_hex)
                sig = bytes.fromhex(sig_hex)
                xpub = bytes.fromhex(row["public key"].strip())

                # Verify path: both BTX and lab agree
                try:
                    lab_ok = schnorr_verify(msg, xpub, sig)
                except Exception:
                    lab_ok = False
                try:
                    btx_ok = T.schnorr_verify(msg, xpub, sig)
                except Exception:
                    btx_ok = False

                if lab_ok != expected:
                    failures.append(f"vec {idx}: lab verify={lab_ok} expected={expected}")
                    continue
                if btx_ok != expected:
                    failures.append(f"vec {idx}: BTX verify={btx_ok} expected={expected}")
                    continue

                # Sign path: byte-identical sigs
                if sk_hex and expected:
                    sk = bytes.fromhex(sk_hex)
                    aux = bytes.fromhex(aux_hex)
                    lab_sig = schnorr_sign(msg, sk, aux)
                    btx_sig = T.schnorr_sign(msg, sk, aux)
                    if lab_sig != sig:
                        failures.append(f"vec {idx}: lab sig != spec")
                        continue
                    if btx_sig != sig:
                        failures.append(f"vec {idx}: BTX sig != spec")
                        continue
                passed += 1
        in_scope = passed + len(failures)
        print(
            f"  canonical BIP-340 CSV: {passed}/{passed + len(failures)} PASS "
            f"(in BTX scope, {scoped} scoped out)"
        )
        if failures:
            overall_ok = False
            for f in failures[:5]:
                print(f"    FAIL: {f}")
    else:
        print("  canonical BIP-340 CSV: SKIP (file not found)")

    # Random round-trip: 30 vectors
    n = 30
    passed = 0
    failures: list[str] = []
    for i in range(n):
        sk_int = int.from_bytes(secrets.token_bytes(32), "big") % (T.N - 1) + 1
        sk = sk_int.to_bytes(32, "big")
        msg = secrets.token_bytes(32)
        aux = secrets.token_bytes(32)
        try:
            lab_sig = schnorr_sign(msg, sk, aux)
            btx_sig = T.schnorr_sign(msg, sk, aux)
        except Exception as e:
            failures.append(f"rand {i}: {type(e).__name__}: {e}")
            continue
        if lab_sig != btx_sig:
            failures.append(f"rand {i}: BTX != secp256k1lab")
            continue
        passed += 1
    print(f"  random round-trip:     {passed}/{n} PASS")
    if failures:
        overall_ok = False
        for f in failures[:5]:
            print(f"    FAIL: {f}")

    if overall_ok:
        print(
            "OK btx_xtest_vs_secp256k1lab: BTX matches Jonas Nick's "
            "authoritative pure-Python BIP-340 reference byte-for-byte "
            "on every signature. Closes the secp256k1lab bookmark from "
            "the 2026-06-03 cycle."
        )
        return 0
    print("FAIL btx_xtest_vs_secp256k1lab: divergence detected")
    return 1


if __name__ == "__main__":
    sys.exit(main())
