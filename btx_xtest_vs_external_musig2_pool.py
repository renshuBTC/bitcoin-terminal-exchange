#!/usr/bin/env python3
"""
btx_xtest_vs_external_musig2_pool — close the BIP-327 MuSig2 pool-
sign side of the suite by applying the consensus-level pattern from
scouts 25-27.

BTX's `btx_musig2.pool_sign_demo(seckeys, msg)` returns `(agg_xonly,
sig64)` — the aggregated pubkey + BIP-340 signature for a maker pool.
The docstring explicitly notes:

  "The resulting signature verifies as a normal BIP340 Schnorr
   signature under the aggregated pubkey returned by key_agg()."

So the consensus-level cross-test is straightforward: BTX's pool-sign
output must be accepted by an external BIP-340 verifier.

This validates that BTX2 maker-pool MuSig2 aggregate signatures are
consensus-valid Bitcoin Schnorr signatures, even though BTX's
KeyAgg is the x-only-input variant (not BIP-327 byte-compatible).
The pool-sign output is still BIP-340 under the BTX-specific
aggregate key.

Skips gracefully if libsecp256k1 isn't available.
"""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))


def _setup_libsecp256k1() -> object | None:
    """Return XOnlyPubKey class or None if libsecp256k1 not set up."""
    import ctypes.util
    lib = ctypes.util.find_library("secp256k1")
    if not lib:
        try:
            import coincurve as _cc
            cc_dir = Path(_cc.__file__).parent
            for so in cc_dir.glob("_libsecp256k1*.so"):
                lib = str(so)
                break
        except Exception:
            return None
    if not lib:
        return None

    pbx_candidates = [
        os.path.expanduser(
            "~/Documents/Claude/Projects/Bitcoin CoreX/"
            "python-bitcointx-reference"
        ),
        "/sessions/keen-determined-einstein/mnt/Bitcoin CoreX/"
        "python-bitcointx-reference",
        "/tmp/python-bitcointx",
    ]
    pbx = None
    for c in pbx_candidates:
        if os.path.isfile(os.path.join(c, "bitcointx", "__init__.py")):
            pbx = c
            break
    if not pbx:
        return None

    sys.path.insert(0, pbx)
    try:
        import bitcointx.util as _u
        _u._secp256k1_library_path = lib
        from bitcointx.core.key import XOnlyPubKey
        return XOnlyPubKey
    except Exception:
        return None


def main() -> int:
    XOnlyPubKey = _setup_libsecp256k1()
    if XOnlyPubKey is None:
        print("[SKIP] libsecp256k1 or python-bitcointx not available")
        return 0

    import btx_musig2 as M
    import btx_taproot as T

    # Run 10 random pool signings with varying pool sizes
    n = 10
    print(f"  external verifier: libsecp256k1 (via python-bitcointx)")
    print(f"  testing {n} random MuSig2 pool signings...")

    passed = 0
    failures: list[str] = []
    pool_sizes = [2, 3, 5, 7]
    for i in range(n):
        size = pool_sizes[i % len(pool_sizes)]
        seckeys = []
        for _ in range(size):
            sk_int = int.from_bytes(secrets.token_bytes(32), "big") % (T.N - 1) + 1
            seckeys.append(sk_int.to_bytes(32, "big"))
        msg = secrets.token_bytes(32)

        try:
            agg_xonly, sig = M.pool_sign_demo(seckeys, msg)
        except Exception as e:
            failures.append(
                f"pool {i} (size {size}): pool_sign_demo raised "
                f"{type(e).__name__}: {e}"
            )
            continue

        if not isinstance(sig, bytes) or len(sig) != 64:
            failures.append(f"pool {i}: bad sig type/length")
            continue
        if not isinstance(agg_xonly, bytes) or len(agg_xonly) != 32:
            failures.append(f"pool {i}: bad agg_xonly type/length")
            continue

        # libsecp256k1 must accept it as a valid BIP-340 signature
        try:
            zk_ok = XOnlyPubKey(agg_xonly).verify_schnorr(msg, sig)
        except Exception as e:
            failures.append(f"pool {i}: libsecp256k1 raised {type(e).__name__}")
            continue
        if not zk_ok:
            failures.append(
                f"pool {i} (size {size}): libsecp256k1 rejected "
                f"BTX-pool-aggregated sig"
            )
            continue

        # BTX's own Schnorr verify (defence in depth)
        if not T.schnorr_verify(msg, agg_xonly, sig):
            failures.append(f"pool {i}: BTX schnorr_verify rejected own pool sig")
            continue

        passed += 1

    print(f"  BTX pool-sign sigs accepted by libsecp256k1: {passed}/{n} PASS")
    if failures:
        for f in failures[:5]:
            print(f"    FAIL: {f}")
        return 1

    print(
        "OK btx_xtest_vs_external_musig2_pool: BTX's MuSig2 pool-sign "
        "output (across pool sizes 2/3/5/7) is consensus-valid BIP-340 "
        "Schnorr — accepted by libsecp256k1 every time. BTX2 maker-pool "
        "signatures are real Bitcoin Schnorr signatures even though "
        "the underlying KeyAgg is the x-only-input variant."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
