#!/usr/bin/env python3
"""
btx_xtest_vs_rust_bitcoin_sighash — close the BIP-341 TapSighash 2nd
oracle bookmark from the cycle 2 saturation doc.

BTX's `btx_taproot.tap_sighash` already cross-tests against the
canonical bitcoin/bips wallet-test-vectors keyPathSpending sub-cases
(sub-test 2 of the suite). This module adds a second oracle:
**rust-bitcoin's `SighashCache::taproot_key_spend_signature_hash`**.

For every canonical inputSpending sub-case we now check that:
  - BTX's tap_sighash matches the spec's `intermediary.sigHash`
  - rust-bitcoin's sighash matches the spec's `intermediary.sigHash`
  - All three agree byte-for-byte

This closes the bookmark documented in BTX-cycle2-saturation-2026-06-
04.md as "BIP-341 TapSighash 2nd oracle | open | high-effort vs
marginal value (Transaction FFI)". The high-effort path turned out
to be ~50 LOC of Rust + ~120 LOC of Python — well within scope.

Skips gracefully if the `sighash` probe binary isn't built.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))


def _find_probe() -> str | None:
    candidates = [
        HERE / "xtest_taproot_probe" / "target" / "release" / "sighash",
        Path("/tmp/rb_target/release/sighash"),
        Path("/sessions/keen-determined-einstein/mnt/bitcoin-terminal-exchange/"
             "xtest_taproot_probe/target/release/sighash"),
    ]
    for c in candidates:
        if Path(c).is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def _find_vectors() -> str | None:
    for c in (
        os.path.expanduser(
            "~/Documents/Claude/Projects/Bitcoin CoreX/"
            "bitcoin-bips-reference/bip-0341/wallet-test-vectors.json"
        ),
        "/mnt/c/Users/Ren Shu/Documents/Claude/Projects/Bitcoin CoreX/"
        "bitcoin-bips-reference/bip-0341/wallet-test-vectors.json",
        "/sessions/keen-determined-einstein/mnt/Bitcoin CoreX/"
        "bitcoin-bips-reference/bip-0341/wallet-test-vectors.json",
    ):
        if os.path.isfile(c):
            return c
    return None


def _decode_tx_for_btx(tx_hex: str) -> dict:
    """Decode a raw transaction into BTX's tap_sighash kwargs shape.

    Returns a dict with version, locktime, vin (list of (txid_be,
    vout, sequence)), vout (list of (value, spk)).
    """
    raw = bytes.fromhex(tx_hex)
    pos = 0

    def take(n: int) -> bytes:
        nonlocal pos
        b = raw[pos:pos + n]
        pos += n
        return b

    def varint() -> int:
        nonlocal pos
        b = raw[pos]
        pos += 1
        if b < 0xFD:
            return b
        if b == 0xFD:
            n = int.from_bytes(raw[pos:pos + 2], "little")
            pos += 2
            return n
        if b == 0xFE:
            n = int.from_bytes(raw[pos:pos + 4], "little")
            pos += 4
            return n
        n = int.from_bytes(raw[pos:pos + 8], "little")
        pos += 8
        return n

    version = int.from_bytes(take(4), "little")
    # Check for SegWit marker (BIP-341 vectors are pre-witness — no
    # marker since unsigned). If next byte is 0x00 + flag 0x01, skip.
    if raw[pos] == 0x00 and raw[pos + 1] == 0x01:
        pos += 2
    n_in = varint()
    vin = []
    for _ in range(n_in):
        txid_le = take(32)
        vout = int.from_bytes(take(4), "little")
        script_sig_len = varint()
        pos += script_sig_len  # skip
        seq = int.from_bytes(take(4), "little")
        vin.append((txid_le[::-1], vout, seq))  # BTX wants big-endian txid
    n_out = varint()
    vout_list = []
    for _ in range(n_out):
        value = int.from_bytes(take(8), "little")
        spk_len = varint()
        spk = take(spk_len)
        vout_list.append((value, spk))
    locktime = int.from_bytes(raw[-4:], "little")
    return {
        "version": version,
        "locktime": locktime,
        "vin": vin,
        "vout": vout_list,
    }


def main() -> int:
    probe = _find_probe()
    if probe is None:
        print(
            "[SKIP] sighash probe not built; "
            "`cd xtest_taproot_probe && cargo build --release --bin sighash`"
        )
        return 0
    print(f"  probe: {probe}")

    vec_path = _find_vectors()
    if vec_path is None:
        print("[SKIP] BIP-341 wallet-test-vectors.json not found")
        return 0

    import btx_taproot as T

    with open(vec_path) as f:
        d = json.load(f)
    kp = d["keyPathSpending"][0]
    tx_hex = kp["given"]["rawUnsignedTx"]
    prevouts = kp["given"]["utxosSpent"]
    # Use BTX's own parser so we feed tap_sighash exactly what
    # btx_bip341_xtest does (the existing test passes 7/7).
    version, locktime, vin, vout = T.parse_unsigned_tx(tx_hex)
    spent_amounts = [int(p["amountSats"]) for p in prevouts]
    spent_spks = [bytes.fromhex(p["scriptPubKey"]) for p in prevouts]

    btx_passed = rust_passed = total = 0
    failures: list[str] = []

    # Build all probe requests in one batch
    probe_lines = []
    sub_meta = []
    for sub in kp["inputSpending"]:
        given = sub["given"]
        idx = given["txinIndex"]
        sht = given["hashType"]
        parts = [tx_hex, str(idx), str(sht), str(len(prevouts))]
        for po in prevouts:
            parts.extend([po["scriptPubKey"], str(po["amountSats"])])
        probe_lines.append(" ".join(parts))
        sub_meta.append(sub)

    rust_out = subprocess.run(
        [probe], input="\n".join(probe_lines).encode(),
        capture_output=True, timeout=30,
    )
    if rust_out.returncode != 0:
        print(f"[ERROR] probe failed: {rust_out.stderr.decode()}")
        return 1
    rust_results = rust_out.stdout.decode().strip().split("\n")

    for i, (sub, rust_sh_hex) in enumerate(zip(sub_meta, rust_results)):
        total += 1
        given = sub["given"]
        intermediary = sub["intermediary"]
        idx = given["txinIndex"]
        sht = given["hashType"]
        expected_hex = intermediary["sigHash"].lower()
        rust_sh = rust_sh_hex.strip().lower()

        # BTX side
        try:
            btx_sh = T.tap_sighash(
                version=version, locktime=locktime,
                vin=vin, vout=vout,
                spent_amounts=spent_amounts, spent_spks=spent_spks,
                input_index=idx, hash_type=sht,
                ext_flag=0,  # key-path
                annex=None, tapleaf_hash=None,
            )
            btx_sh_hex = btx_sh.hex()
        except Exception as e:
            failures.append(f"vec {i}: BTX raised {type(e).__name__}: {e}")
            continue

        if btx_sh_hex != expected_hex:
            failures.append(
                f"vec {i}: BTX={btx_sh_hex[:16]}.. != spec {expected_hex[:16]}.."
            )
            continue
        btx_passed += 1

        if rust_sh != expected_hex:
            failures.append(
                f"vec {i}: rust-bitcoin={rust_sh[:16]}.. != spec {expected_hex[:16]}.."
            )
            continue
        rust_passed += 1

    print(f"  canonical BIP-341 keyPathSpending: {btx_passed} BTX + "
          f"{rust_passed} rust-bitcoin / {total} total")
    if failures:
        for f in failures[:5]:
            print(f"    FAIL: {f}")
        if len(failures) > 5:
            print(f"    ... and {len(failures) - 5} more")
        print("FAIL btx_xtest_vs_rust_bitcoin_sighash")
        return 1

    print(
        "OK btx_xtest_vs_rust_bitcoin_sighash: BTX pure-Python and "
        "rust-bitcoin's bitcoin::sighash::SighashCache compute "
        "byte-identical BIP-341 TapSighash on every canonical "
        "keyPathSpending vector. Second TapSighash oracle in place; "
        "closes the bookmark from BTX-cycle2-saturation-2026-06-04."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
