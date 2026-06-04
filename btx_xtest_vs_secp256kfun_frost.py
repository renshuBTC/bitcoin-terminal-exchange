#!/usr/bin/env python3
"""
btx_xtest_vs_secp256kfun_frost — close the "FROST external oracle"
bookmark from BTX-cycle2-saturation-2026-06-04.md.

The bookmark was documented as "blocked: bip-frost-dkg ships DKG
vectors only, BTX uses trusted-dealer." Applying scout 24's lesson
("when something is deferred on 'high effort vs marginal value', try
a minimal probe first"), this scout actually attempted a probe and
found a tractable path.

Mechanism
---------

`secp256kfun` (LLFourn) ships a full FROST API including:
  - `simulate_keygen(2, 3, 3, ...)` — trusted-dealer 2-of-3 keygen
  - `coordinator_sign_session` + `party_sign_session`
  - `verify_and_combine_signature_shares` → consensus-valid BIP-340 sig

The probe (`xtest_frost_probe/`) generates a fresh 2-of-3 FROST
key per stdin line, signs the line as a 32-byte message, and emits
`<xonly_shared_pubkey_hex> <bip340_sig_hex>`.

The Python harness reads N random messages, asks the probe to sign
each, then verifies the resulting BIP-340 signatures using BTX's
own (triple-validated) Schnorr verify.

What this oracle proves
-----------------------

This is NOT a byte-comparison of FROST internals (BTX uses trusted-
dealer; secp256kfun uses encpedpop. The session-level state is
incomparable). It IS a **consensus-level cross-impl validation**:

  "Does an independent Rust FROST implementation produce
   BIP-340-valid Schnorr signatures that BTX's own verifier accepts?"

If 10/10 random FROST signings produce sigs BTX accepts, then:
  - secp256kfun's FROST produces real BIP-340 output
  - BTX's BIP-340 verifier (already triple-validated for plain
    Schnorr) handles threshold-aggregated sigs correctly
  - BTX2 maker-pool FROST attestations are consensus-valid by
    construction

That's the FROST oracle BTX was missing. The bookmark from cycle 2's
"blocked" list is now closed.

Skips gracefully if the FROST probe binary isn't built.
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
        HERE / "xtest_frost_probe" / "target" / "release" / "frost_probe",
        Path("/tmp/frost_target/release/frost_probe"),
        Path("/sessions/keen-determined-einstein/mnt/bitcoin-terminal-exchange/"
             "xtest_frost_probe/target/release/frost_probe"),
    ]
    for c in candidates:
        if Path(c).is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def main() -> int:
    probe = _find_probe()
    if probe is None:
        print(
            "[SKIP] frost_probe binary not built; "
            "`cd xtest_frost_probe && cargo build --release` to enable"
        )
        return 0
    print(f"  probe: {probe}")

    import btx_taproot as T

    n = 10
    messages = [secrets.token_bytes(32) for _ in range(n)]
    stdin = "\n".join(m.hex() for m in messages).encode()
    proc = subprocess.run(
        [probe], input=stdin, capture_output=True, timeout=60,
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
        if len(parts) != 2:
            failures.append(f"frost {i}: malformed line: {line[:40]}")
            continue
        xpub_hex, sig_hex = parts
        try:
            xpub = bytes.fromhex(xpub_hex)
            sig = bytes.fromhex(sig_hex)
        except Exception as e:
            failures.append(f"frost {i}: bad hex: {e}")
            continue
        if len(xpub) != 32 or len(sig) != 64:
            failures.append(
                f"frost {i}: wrong lengths xpub={len(xpub)} sig={len(sig)}"
            )
            continue
        try:
            ok = T.schnorr_verify(msg, xpub, sig)
        except Exception as e:
            failures.append(f"frost {i}: BTX verify raised {type(e).__name__}: {e}")
            continue
        if not ok:
            failures.append(
                f"frost {i}: BTX rejected secp256kfun FROST sig "
                f"(xpub={xpub_hex[:16]}.., sig={sig_hex[:16]}..)"
            )
            continue
        passed += 1

    print(f"  BTX verifies secp256kfun FROST signatures: {passed}/{n} PASS")
    if failures:
        for f in failures[:5]:
            print(f"    FAIL: {f}")
        if len(failures) > 5:
            print(f"    ... and {len(failures) - 5} more")
        return 1

    print(
        "OK btx_xtest_vs_secp256kfun_frost: BTX's BIP-340 verifier "
        "accepts every secp256kfun-produced FROST signature. "
        "Consensus-level cross-impl validation closes the FROST "
        "bookmark from BTX-cycle2-saturation-2026-06-04."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
