#!/usr/bin/env python3
"""
btx_xtest_vs_rust_bitcoin_taproot — cross-test BTX's pure-Python
BIP-341 Taproot tweak (`btx_taproot.taproot_tweak_pubkey`) against
`rust-bitcoin`'s `bitcoin::taproot` module via a small Rust probe.

Why this oracle is useful
-------------------------

Before this scout BTX had exactly ONE BIP-341 oracle: the canonical
`bitcoin/bips/bip-0341/wallet-test-vectors.json`. That validates
spec compliance on the official corpus but doesn't catch a class
of bugs where BTX and the reference Python pseudocode share an
algorithmic quirk that real Bitcoin tools handle differently.

`rust-bitcoin` is the de-facto Rust Bitcoin library — used by
Sparrow wallet, BDK, electrs, LDK, and BTX's own brk-btx indexer.
Its Taproot tweak path is implemented from scratch on top of
`secp256k1` (the C library). Cross-testing BTX's pure-Python tweak
against rust-bitcoin's gives an implementation-independence oracle
in a third language (Rust) for BIP-341 — complementing scouts 18
(Python ↔ libsecp256k1-C) and 19 (Python ↔ noble-JS) which only
covered BIP-340 Schnorr.

Mechanism
---------

A small Rust probe (in `xtest_taproot_probe/`) reads
`<internal_xonly_hex> [merkle_root_hex]` records from stdin and
emits `<output_xonly_hex> <parity_bool> <tap_tweak_hash_hex>` per
line. The Python harness batches all queries into one probe
invocation and compares to BTX byte-for-byte.

Build the probe once with:
    cd xtest_taproot_probe && cargo build --release
The cross-test auto-detects the binary at `xtest_taproot_probe/
target/release/rb_taproot_probe` or in /tmp/rb_target/. Skips
gracefully if not built.
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
        HERE / "xtest_taproot_probe" / "target" / "release" / "rb_taproot_probe",
        Path("/tmp/rb_target/release/rb_taproot_probe"),
        Path("/sessions/keen-determined-einstein/mnt/bitcoin-terminal-exchange/"
             "xtest_taproot_probe/target/release/rb_taproot_probe"),
    ]
    for c in candidates:
        if Path(c).is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def _find_canonical_json() -> str | None:
    candidates = [
        os.path.expanduser(
            "~/Documents/Claude/Projects/Bitcoin CoreX/"
            "bitcoin-bips-reference/bip-0341/wallet-test-vectors.json"
        ),
        "/mnt/c/Users/Ren Shu/Documents/Claude/Projects/Bitcoin CoreX/"
        "bitcoin-bips-reference/bip-0341/wallet-test-vectors.json",
        "/sessions/keen-determined-einstein/mnt/Bitcoin CoreX/"
        "bitcoin-bips-reference/bip-0341/wallet-test-vectors.json",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _call_probe(probe: str, records: list[tuple[bytes, bytes]]) -> list[dict]:
    """records = list of (internal_xonly_32, merkle_root_or_empty)."""
    lines = []
    for ix, mr in records:
        lines.append(f"{ix.hex()} {mr.hex()}\n")
    p = subprocess.run(
        [probe], input="".join(lines).encode(),
        capture_output=True, timeout=30,
    )
    if p.returncode != 0:
        raise RuntimeError(f"probe failed rc={p.returncode}: {p.stderr.decode()}")
    out = []
    for line in p.stdout.decode().strip().split("\n"):
        parts = line.split()
        out.append({
            "output_xonly": bytes.fromhex(parts[0]),
            "parity_odd": parts[1] == "true",
            "tap_tweak_hash": bytes.fromhex(parts[2]),
        })
    return out


def _gen_random(T, n: int) -> list[tuple[bytes, bytes]]:
    """Random (internal_xonly, merkle_root) — half key-path-only, half script-path."""
    records = []
    for i in range(n):
        # Random valid secret key → xonly
        sk_int = int.from_bytes(secrets.token_bytes(32), "big") % (T.N - 1) + 1
        sk = sk_int.to_bytes(32, "big")
        internal_xonly, _ = T.xonly_pubkey(sk)
        # Half key-path-only, half random 32-byte merkle root
        if i % 2 == 0:
            mr = b""
        else:
            mr = secrets.token_bytes(32)
        records.append((internal_xonly, mr))
    return records


def _run_random(T, probe: str, n: int = 50) -> tuple[int, int, list[str]]:
    records = _gen_random(T, n)
    rust_results = _call_probe(probe, records)
    assert len(rust_results) == n, f"probe returned {len(rust_results)}/{n}"

    passed = 0
    failures: list[str] = []
    for i, ((internal, mr), rr) in enumerate(zip(records, rust_results)):
        try:
            btx_parity, btx_xonly = T.taproot_tweak_pubkey(internal, mr)
        except Exception as e:
            failures.append(f"rand {i}: BTX raised {type(e).__name__}: {e}")
            continue

        if btx_xonly != rr["output_xonly"]:
            failures.append(
                f"rand {i}: BTX tweaked_xonly={btx_xonly.hex()[:16]}.. "
                f"!= rust-bitcoin {rr['output_xonly'].hex()[:16]}.."
            )
            continue
        btx_parity_odd = bool(btx_parity & 1)
        if btx_parity_odd != rr["parity_odd"]:
            failures.append(
                f"rand {i}: BTX parity_odd={btx_parity_odd} "
                f"!= rust-bitcoin {rr['parity_odd']}"
            )
            continue
        passed += 1
    return passed, n, failures


def _run_canonical(T, probe: str, json_path: str) -> tuple[int, int, list[str]]:
    import json
    with open(json_path) as f:
        data = json.load(f)
    key_path_vectors = data.get("keyPathSpending", [])
    # The wallet-test-vectors has a richer structure; pick the
    # `scriptPubKey` section which exposes internal+merkle→output:
    spk_tests = data.get("scriptPubKey", [])
    if not spk_tests:
        return 0, 0, ["wallet-test-vectors.json missing 'scriptPubKey' section"]

    records: list[tuple[bytes, bytes]] = []
    expected: list[dict] = []
    for tv in spk_tests:
        given = tv["given"]
        intended = tv["intermediary"]
        ix_hex = given["internalPubkey"]
        # given["scriptTree"] is null → key-path-only
        mr_hex = intended.get("merkleRoot") or ""
        records.append((bytes.fromhex(ix_hex),
                        bytes.fromhex(mr_hex) if mr_hex else b""))
        expected.append({
            "output_xonly": bytes.fromhex(intended["tweakedPubkey"]),
            "tap_tweak_hash": bytes.fromhex(intended.get("tweak", "00" * 32)),
        })

    rust_results = _call_probe(probe, records)
    passed = 0
    failures: list[str] = []
    for i, (rec, rr, exp) in enumerate(zip(records, rust_results, expected)):
        internal, mr = rec
        try:
            btx_parity, btx_xonly = T.taproot_tweak_pubkey(internal, mr)
        except Exception as e:
            failures.append(f"vec {i}: BTX raised {type(e).__name__}: {e}")
            continue

        if btx_xonly != exp["output_xonly"]:
            failures.append(
                f"vec {i}: BTX={btx_xonly.hex()[:16]}.. != spec "
                f"{exp['output_xonly'].hex()[:16]}.."
            )
            continue
        if rr["output_xonly"] != exp["output_xonly"]:
            failures.append(
                f"vec {i}: rust-bitcoin={rr['output_xonly'].hex()[:16]}.. != spec"
            )
            continue
        passed += 1
    return passed, len(records), failures


def main() -> int:
    probe = _find_probe()
    if probe is None:
        print(
            "[SKIP] rb_taproot_probe not built; cd xtest_taproot_probe && "
            "cargo build --release to enable"
        )
        return 0
    print(f"  probe: {probe}")

    import btx_taproot as T

    overall_ok = True
    csv = _find_canonical_json()
    if csv:
        try:
            passed, total, fails = _run_canonical(T, probe, csv)
            print(f"  canonical BIP-341 scriptPubKey: {passed}/{total} PASS")
            if fails:
                overall_ok = False
                for f in fails[:5]:
                    print(f"    FAIL: {f}")
                if len(fails) > 5:
                    print(f"    ... and {len(fails) - 5} more")
        except Exception as e:
            print(f"  canonical BIP-341: ERROR {type(e).__name__}: {e}")
            overall_ok = False
    else:
        print("  canonical BIP-341 JSON: SKIP (file not found)")

    try:
        passed, total, fails = _run_random(T, probe, n=50)
        print(f"  random Taproot tweak roundtrip: {passed}/{total} PASS")
        if fails:
            overall_ok = False
            for f in fails[:5]:
                print(f"    FAIL: {f}")
            if len(fails) > 5:
                print(f"    ... and {len(fails) - 5} more")
    except Exception as e:
        print(f"  random round-trip: ERROR {type(e).__name__}: {e}")
        overall_ok = False

    if overall_ok:
        print(
            "OK btx_xtest_vs_rust_bitcoin_taproot: BTX pure-Python and "
            "rust-bitcoin's bitcoin::taproot agree on every BIP-341 "
            "tweak. Second oracle for BIP-341 Taproot, complementing "
            "the canonical bitcoin/bips wallet-test-vectors."
        )
        return 0
    print("FAIL btx_xtest_vs_rust_bitcoin_taproot: divergence detected")
    return 1


if __name__ == "__main__":
    sys.exit(main())
