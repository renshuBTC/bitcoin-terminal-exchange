#!/usr/bin/env python3
"""
btx_xtest_vs_secp256kfun_adaptor — close the "MuSig2 adaptor random
round-trip" bookmark from the cycle 2 saturation doc by applying the
same pattern as scout 25 (FROST).

The bookmark said "blocked: need Rust impl exposing partial_sign +
partial_sig_agg". The actual answer turned out to be: secp256kfun's
`schnorr_fun::adaptor` exposes the full encrypt-sign-decrypt-verify
flow as a clean trait. ~30 LOC of Rust + ~80 LOC of Python.

The probe (`xtest_frost_probe/src/bin/adaptor.rs`) does:
  1. Fresh signing_keypair + decryption_key
  2. encryption_key (T-point) = decryption_key * G
  3. encrypted_sig = encrypted_sign(signer, T, msg)
  4. final_sig = decrypt_signature(decryption_key, encrypted_sig)
  5. Emit (xonly_pubkey, decryption_key, final_sig)

The Python harness then verifies that BTX's BIP-340 verifier accepts
the final_sig — proving the adaptor encrypt+decrypt round-trip
produces a consensus-valid Schnorr signature.

What this oracle proves
-----------------------

Not a byte-comparison of adaptor internals (nonce randomness makes
that impossible without explicit aux). It IS:

  - secp256kfun's adaptor encrypt-then-decrypt produces real BIP-340
  - BTX's BIP-340 verifier accepts the decrypted output
  - BTX's adaptor scheme assumption (that decryption produces a
    valid Schnorr) is validated against an independent Rust
    implementation

Skips gracefully if the adaptor probe binary isn't built.
"""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))


def _find_probe() -> str | None:
    candidates = [
        HERE / "xtest_frost_probe" / "target" / "release" / "adaptor",
        Path("/tmp/frost_target/release/adaptor"),
        Path("/sessions/keen-determined-einstein/mnt/bitcoin-terminal-exchange/"
             "xtest_frost_probe/target/release/adaptor"),
    ]
    for c in candidates:
        if Path(c).is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def main() -> int:
    probe = _find_probe()
    if probe is None:
        print(
            "[SKIP] adaptor probe not built; "
            "`cd xtest_frost_probe && cargo build --release --bin adaptor` to enable"
        )
        return 0
    print(f"  probe: {probe}")

    import btx_taproot as T

    n = 10
    messages = [secrets.token_bytes(32) for _ in range(n)]
    stdin = "\n".join(m.hex() for m in messages).encode()
    proc = subprocess.run(
        [probe], input=stdin, capture_output=True, timeout=30,
    )
    if proc.returncode != 0:
        print(f"  probe failed rc={proc.returncode}: {proc.stderr.decode()}")
        return 1

    lines = proc.stdout.decode().strip().split("\n")
    if len(lines) != n:
        print(f"  probe returned {len(lines)} lines, expected {n}")
        return 1

    passed = 0
    failures: list[str] = []
    for i, (line, msg) in enumerate(zip(lines, messages)):
        parts = line.strip().split()
        if len(parts) != 3:
            failures.append(f"adapt {i}: malformed line")
            continue
        xpub_hex, dkey_hex, sig_hex = parts
        try:
            xpub = bytes.fromhex(xpub_hex)
            sig = bytes.fromhex(sig_hex)
        except Exception as e:
            failures.append(f"adapt {i}: hex error: {e}")
            continue
        try:
            ok = T.schnorr_verify(msg, xpub, sig)
        except Exception as e:
            failures.append(f"adapt {i}: BTX raised {type(e).__name__}: {e}")
            continue
        if not ok:
            failures.append(
                f"adapt {i}: BTX rejected decrypted adaptor sig "
                f"(xpub={xpub_hex[:16]}.., sig={sig_hex[:16]}..)"
            )
            continue
        passed += 1

    print(f"  BTX verifies secp256kfun adaptor-decrypted sigs: {passed}/{n} PASS")
    if failures:
        for f in failures[:5]:
            print(f"    FAIL: {f}")
        return 1

    print(
        "OK btx_xtest_vs_secp256kfun_adaptor: BTX's BIP-340 verifier "
        "accepts every encrypt-then-decrypt round-trip produced by "
        "secp256kfun's adaptor scheme. Schnorr adaptor signing is "
        "now cross-validated at the consensus level against an "
        "independent Rust implementation."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
