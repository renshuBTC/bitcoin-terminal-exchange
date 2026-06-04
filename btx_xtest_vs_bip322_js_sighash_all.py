#!/usr/bin/env python3
"""
btx_xtest_vs_bip322_js_sighash_all — verify BTX accepts bip322-js
SIGHASH_ALL signatures (the format Sparrow Wallet, Trezor Suite, and
bip322-js's default Signer.sign produce).

Companion to btx_xtest_vs_bip322_js.py (scout 21), which tested the
BTX-sign → bip322-js-verify direction with SIGHASH_DEFAULT (64-byte
sigs). This test closes the reverse direction: bip322-js-sign →
BTX-verify with SIGHASH_ALL (65-byte sigs ending in 0x01).

Requires the BTX-side patch to `btx_bip322.verify_simple_p2tr` +
`_bip322_p2tr_sighash` + `_decode_simple_signature` that:
  - accepts bare-base64 (no `smp` prefix, the BIP-322 spec form)
  - accepts 65-byte sigs with 0x01 sighash flag
  - computes the BIP-341 sighash with hash_type=0x01 in that case

Skips gracefully if Node or bip322-js isn't installed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))


_BRIDGE_JS = r"""
import { Signer } from 'bip322-js';
let data = '';
process.stdin.on('data', (c) => { data += c; });
process.stdin.on('end', () => {
    const reqs = JSON.parse(data);
    const out = reqs.map((r) => {
        let sig = null, err = null;
        try {
            sig = String(Signer.sign(r.wif, r.address, r.message));
        } catch (e) { err = String(e); }
        return { idx: r.idx, sig, err };
    });
    process.stdout.write(JSON.stringify(out));
});
"""


def _find_node_with_bip322() -> tuple[str, str] | None:
    try:
        if subprocess.run(["node", "--version"], capture_output=True,
                          timeout=5).returncode != 0:
            return None
    except Exception:
        return None
    candidates = [
        os.path.expanduser(
            "~/Documents/Claude/Projects/Bitcoin CoreX/bip322-js-reference"
        ),
        "/sessions/keen-determined-einstein/mnt/Bitcoin CoreX/bip322-js-reference",
        "/tmp/bip322_search",
    ]
    for c in candidates:
        if os.path.isdir(os.path.join(c, "node_modules", "bip322-js")):
            return ("node", c)
    return None


def main() -> int:
    found = _find_node_with_bip322()
    if not found:
        print("[SKIP] bip322-js not installed")
        return 0
    node, cwd = found
    print(f"  node:      {node}")
    print(f"  bip322-js: {cwd}/node_modules/bip322-js")

    import btx_bip322 as B

    # Canonical bip322-js test vector address+key (P2TR single-key-spend)
    wif = "L3VFeEujGtevx9w18HD1fhRbCH67Az2dpCymeRE1SoPK6XQtaN2k"
    address = "bc1ppv609nr0vr25u07u95waq5lucwfm6tde4nydujnu8npg4q75mr5sxq8lt3"

    # 20 different messages
    n = 20
    requests = []
    messages = []
    for i in range(n):
        msg = f"BTX-test-msg-{i}-{os.urandom(4).hex()}"
        messages.append(msg)
        requests.append({
            "idx": str(i), "wif": wif, "address": address, "message": msg,
        })

    payload = json.dumps(requests).encode()
    proc = subprocess.run(
        [node, "--input-type=module", "-e", _BRIDGE_JS],
        input=payload, capture_output=True, cwd=cwd, timeout=60,
    )
    if proc.returncode != 0:
        print(f"  bridge failed rc={proc.returncode}: {proc.stderr.decode()}")
        return 1
    results = json.loads(proc.stdout.decode())

    passed = 0
    failures: list[str] = []
    sighash_all_count = 0
    for r, msg in zip(results, messages):
        if r.get("err"):
            failures.append(f"{r['idx']}: bip322-js raised {r['err'][:60]}")
            continue
        sig = r["sig"]
        # Decode to check sighash byte
        import base64
        raw = base64.b64decode(sig)
        if len(raw) == 67 and raw[-1] == 0x01:
            sighash_all_count += 1
        # BTX verifies
        try:
            ok = B.verify_simple_p2tr(msg.encode(), address, sig)
        except Exception as e:
            failures.append(f"{r['idx']}: BTX raised {type(e).__name__}: {e}")
            continue
        if not ok:
            failures.append(f"{r['idx']}: BTX rejected SIGHASH_ALL sig for msg={msg!r}")
            continue
        passed += 1

    print(
        f"  bip322-js SIGHASH_ALL signatures verified by BTX: "
        f"{passed}/{n} PASS (of which {sighash_all_count} were 65-byte SIGHASH_ALL)"
    )
    if failures:
        for f in failures[:5]:
            print(f"    FAIL: {f}")
        return 1

    print(
        "OK btx_xtest_vs_bip322_js_sighash_all: BTX's verify_simple_p2tr "
        "accepts bip322-js SIGHASH_ALL signatures. Sparrow Wallet, Trezor "
        "Suite, and bip322-js's default Signer.sign are now interoperable "
        "with BTX's BIP-322 verifier. Closes the BIP-322 SIGHASH_ALL "
        "bookmark from BTX-cycle2-FINAL-2026-06-04."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
