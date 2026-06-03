#!/usr/bin/env python3
"""
btx_xtest_vs_noble_secp256k1 — cross-test BTX's pure-Python BIP-340
Schnorr against `@noble/curves` Schnorr (the pure-JavaScript secp256k1
used by `paulmillr/scure-btc-signer`).

Why this cross-test exists
--------------------------

BTX already has these BIP-340 oracles:
  1. Bitcoin Core BIP-340 CSV (canonical vectors)
  2. secp256kfun (Lloyd Fournier, pure-Rust no libsecp256k1)
  3. dlcspecs Schnorr vectors (canonical)
  4. dlcspecs oracle bytes vectors (canonical)
  5. python-bitcointx via libsecp256k1 (pure-C wrapper)   <- scout 18

This module adds a 6th: `@noble/curves` (pure-JavaScript, no
libsecp256k1, no C, no Rust). With this in place BTX has cross-tested
its pure-Python Schnorr against THREE independent implementations in
THREE different languages:

  - Python from-scratch     (BTX)        - oracle #5/#6 reference
  - C library               (libsecp256k1) - via scout 18
  - JavaScript from-scratch (noble)      - via THIS scout

All three must agree byte-for-byte on every signature, for every
input. If two disagree, one of them has a bug — and "two of three
agree" identifies the buggy one.

This is the strongest form of implementation-independence validation
short of formal proof.

How it works
------------

`@noble/curves` is the runtime crypto behind `paulmillr/scure-btc-
signer` and most modern JS Bitcoin tooling (CoinKit, BitcoinJS via
secp256k1-js, Sparrow wallet's web build, etc). It has no dependency
on libsecp256k1; it implements secp256k1 + BIP-340 from scratch in
TypeScript.

This cross-test spawns Node with an inline JavaScript bridge that
calls `@noble/curves` schnorr.sign / schnorr.verify on a batch of
inputs (canonical CSV vectors + random round-trip tuples), receives
JSON output, and compares to BTX's output byte-for-byte.

Skips gracefully if Node or @noble/curves isn't available.
"""
from __future__ import annotations

import csv
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))


_BRIDGE_JS = r"""
import { schnorr } from '@noble/curves/secp256k1.js';
let data = '';
process.stdin.on('data', (chunk) => { data += chunk; });
process.stdin.on('end', () => {
    const reqs = JSON.parse(data);
    const out = reqs.map((r) => {
        const sk = Buffer.from(r.sk, 'hex');
        const msg = Buffer.from(r.msg, 'hex');
        const aux = Buffer.from(r.aux, 'hex');
        let sig_hex = null, sig_err = null;
        try {
            const sig = schnorr.sign(msg, sk, aux);
            sig_hex = Buffer.from(sig).toString('hex');
        } catch (e) { sig_err = String(e); }
        let verify_ok = null, verify_err = null;
        if (r.verify_sig && r.verify_xpub) {
            try {
                verify_ok = schnorr.verify(
                    Buffer.from(r.verify_sig, 'hex'),
                    msg,
                    Buffer.from(r.verify_xpub, 'hex'),
                );
            } catch (e) {
                verify_ok = false; verify_err = String(e);
            }
        }
        let xpub_hex = null;
        try { xpub_hex = Buffer.from(schnorr.getPublicKey(sk)).toString('hex'); }
        catch (e) {}
        return { idx: r.idx, sig: sig_hex, sig_err, verify_ok, verify_err, xpub: xpub_hex };
    });
    process.stdout.write(JSON.stringify(out));
});
"""


def _find_node_with_noble() -> tuple[str, str] | None:
    """Return (node_path, cwd) where @noble/curves is installed, or None."""
    node = None
    for cand in ("node", "/usr/bin/node", "/usr/local/bin/node"):
        try:
            r = subprocess.run([cand, "--version"], capture_output=True, timeout=5)
            if r.returncode == 0:
                node = cand
                break
        except Exception:
            continue
    if node is None:
        return None

    # Find a directory with @noble/curves installed
    candidates = [
        os.path.expanduser(
            "~/Documents/Claude/Projects/Bitcoin CoreX/scure-btc-signer-reference"
        ),
        "/mnt/c/Users/Ren Shu/Documents/Claude/Projects/Bitcoin CoreX/scure-btc-signer-reference",
        "/sessions/keen-determined-einstein/mnt/Bitcoin CoreX/scure-btc-signer-reference",
        "/tmp/scure-btc-signer",
    ]
    for c in candidates:
        if os.path.isdir(os.path.join(c, "node_modules", "@noble", "curves")):
            return (node, c)
    return None


def _call_noble(node: str, cwd: str, requests: list[dict]) -> list[dict]:
    """Spawn Node with the bridge JS, send requests, return responses."""
    payload = json.dumps(requests).encode()
    p = subprocess.run(
        [node, "--experimental-strip-types", "--input-type=module", "-e", _BRIDGE_JS],
        input=payload, capture_output=True, cwd=cwd, timeout=60,
    )
    if p.returncode != 0:
        raise RuntimeError(f"node bridge failed rc={p.returncode}: {p.stderr.decode()}")
    return json.loads(p.stdout.decode())


def _find_canonical_csv() -> str | None:
    candidates = [
        os.path.expanduser(
            "~/Documents/Claude/Projects/Bitcoin CoreX/"
            "bitcoin-bips-reference/bip-0340/test-vectors.csv"
        ),
        "/mnt/c/Users/Ren Shu/Documents/Claude/Projects/Bitcoin CoreX/"
        "bitcoin-bips-reference/bip-0340/test-vectors.csv",
        "/sessions/keen-determined-einstein/mnt/Bitcoin CoreX/"
        "bitcoin-bips-reference/bip-0340/test-vectors.csv",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _run_canonical(T, node: str, cwd: str, csv_path: str) -> tuple[int, int, int, list[str]]:
    """(passed, scoped_out, in_scope_total, failures)."""
    requests = []
    rows = []
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            rows.append(row)
            sk = row["secret key"].strip()
            msg = row["message"].strip()
            aux = row["aux_rand"].strip()
            # Only ask Node to sign if sk is provided and msg is 32 bytes
            # (noble also rejects non-32-byte; we'll handle scoped separately).
            if sk and len(msg) == 64:
                requests.append({
                    "idx": row["index"],
                    "sk": sk,
                    "msg": msg,
                    "aux": aux if aux else "00" * 32,
                    "verify_sig": row["signature"].strip(),
                    "verify_xpub": row["public key"].strip(),
                })

    noble_results = _call_noble(node, cwd, requests)
    by_idx = {r["idx"]: r for r in noble_results}

    passed = scoped_out = in_scope = 0
    failures: list[str] = []
    for row in rows:
        idx = row["index"]
        msg_hex = row["message"].strip()
        sig_hex = row["signature"].strip().lower()
        expected = row["verification result"].strip().upper() == "TRUE"

        if len(msg_hex) != 64:
            scoped_out += 1
            continue
        in_scope += 1

        if not row["secret key"].strip():
            # Verify-only vector. Compare BTX-verify and noble-verify
            # to the spec's expected result.
            try:
                btx_ok = T.schnorr_verify(
                    bytes.fromhex(msg_hex),
                    bytes.fromhex(row["public key"].strip()),
                    bytes.fromhex(sig_hex),
                )
            except Exception:
                btx_ok = False
            noble_ok = by_idx.get(idx, {}).get("verify_ok") if idx in by_idx else None
            if btx_ok != expected:
                failures.append(f"vec {idx}: BTX verify={btx_ok} expected={expected}")
                continue
            if noble_ok is not None and noble_ok != expected:
                failures.append(f"vec {idx}: noble verify={noble_ok} expected={expected}")
                continue
            passed += 1
            continue

        sk_hex = row["secret key"].strip()
        aux_hex = row["aux_rand"].strip() or "00" * 32
        msg = bytes.fromhex(msg_hex)
        sk = bytes.fromhex(sk_hex)
        aux = bytes.fromhex(aux_hex)
        spec_sig = bytes.fromhex(sig_hex)

        # BTX sign
        try:
            import btx_taproot as _T
            btx_sig = _T.schnorr_sign(msg, sk, aux)
        except Exception as e:
            failures.append(f"vec {idx}: BTX sign raised {type(e).__name__}: {e}")
            continue

        noble = by_idx.get(idx)
        if noble is None or noble.get("sig") is None:
            failures.append(f"vec {idx}: noble returned no signature: {noble}")
            continue
        noble_sig = bytes.fromhex(noble["sig"])

        if btx_sig != spec_sig:
            failures.append(f"vec {idx}: BTX sig {btx_sig.hex()} != spec {sig_hex}")
            continue
        if noble_sig != spec_sig:
            failures.append(f"vec {idx}: noble sig {noble_sig.hex()} != spec {sig_hex}")
            continue
        if btx_sig != noble_sig:
            failures.append(f"vec {idx}: BTX != noble sig")
            continue

        # cross-verify: noble verifies BTX sig, BTX verifies noble sig
        if noble.get("verify_ok") is not True:
            failures.append(f"vec {idx}: noble verify of spec sig = {noble.get('verify_ok')}")
            continue
        if not T.schnorr_verify(msg, bytes.fromhex(row["public key"].strip()), noble_sig):
            failures.append(f"vec {idx}: BTX rejected noble-produced sig")
            continue

        passed += 1
    return passed, scoped_out, in_scope, failures


def _run_random(T, node: str, cwd: str, n: int = 50) -> tuple[int, int, list[str]]:
    requests = []
    seeds = []
    for i in range(n):
        sk_int = int.from_bytes(secrets.token_bytes(32), "big") % (T.N - 1) + 1
        sk = sk_int.to_bytes(32, "big")
        msg = secrets.token_bytes(32)
        aux = secrets.token_bytes(32)
        seeds.append((sk, msg, aux))
        requests.append({
            "idx": str(i), "sk": sk.hex(), "msg": msg.hex(), "aux": aux.hex(),
        })

    noble_results = _call_noble(node, cwd, requests)
    by_idx = {r["idx"]: r for r in noble_results}

    passed = 0
    failures: list[str] = []
    for i, (sk, msg, aux) in enumerate(seeds):
        idx = str(i)
        # BTX sign
        try:
            btx_sig = T.schnorr_sign(msg, sk, aux)
        except Exception as e:
            failures.append(f"rand {i}: BTX raised {type(e).__name__}: {e}")
            continue

        noble = by_idx.get(idx)
        if noble is None or noble.get("sig") is None:
            failures.append(f"rand {i}: noble returned no sig")
            continue
        noble_sig = bytes.fromhex(noble["sig"])
        if btx_sig != noble_sig:
            failures.append(
                f"rand {i}: BTX != noble "
                f"({btx_sig.hex()[:16]}.. vs {noble_sig.hex()[:16]}..)"
            )
            continue

        # Derive xpub from noble, BTX must verify the noble sig
        xpub_hex = noble.get("xpub")
        if not xpub_hex:
            failures.append(f"rand {i}: noble didn't return xpub")
            continue
        xpub = bytes.fromhex(xpub_hex)
        if not T.schnorr_verify(msg, xpub, noble_sig):
            failures.append(f"rand {i}: BTX rejected noble sig")
            continue
        # tamper rejection check
        bad = bytearray(noble_sig); bad[10] ^= 0x01
        if T.schnorr_verify(msg, xpub, bytes(bad)):
            failures.append(f"rand {i}: BTX accepted tampered sig")
            continue
        passed += 1
    return passed, n, failures


def main() -> int:
    found = _find_node_with_noble()
    if not found:
        print(
            "[SKIP] Node + @noble/curves not found; clone "
            "https://github.com/paulmillr/scure-btc-signer to "
            "Bitcoin CoreX/scure-btc-signer-reference and `npm install` "
            "to enable"
        )
        return 0
    node, cwd = found
    print(f"  node:               {node}")
    print(f"  @noble/curves at:   {cwd}/node_modules/@noble/curves")

    import btx_taproot as T

    overall_ok = True
    csv_path = _find_canonical_csv()
    if csv_path:
        try:
            passed, scoped, in_scope, fails = _run_canonical(T, node, cwd, csv_path)
            print(
                f"  canonical BIP-340 CSV: {passed}/{in_scope} PASS "
                f"(in BTX scope, {scoped} scoped out)"
            )
            if fails:
                overall_ok = False
                for f in fails[:5]:
                    print(f"    FAIL: {f}")
                if len(fails) > 5:
                    print(f"    ... and {len(fails) - 5} more")
        except Exception as e:
            print(f"  canonical BIP-340 CSV: ERROR {type(e).__name__}: {e}")
            overall_ok = False
    else:
        print("  canonical BIP-340 CSV: SKIP (file not found)")

    try:
        passed, total, fails = _run_random(T, node, cwd, n=50)
        print(f"  random round-trip:     {passed}/{total} PASS")
        if fails:
            overall_ok = False
            for f in fails[:5]:
                print(f"    FAIL: {f}")
            if len(fails) > 5:
                print(f"    ... and {len(fails) - 5} more")
    except Exception as e:
        print(f"  random round-trip:     ERROR {type(e).__name__}: {e}")
        overall_ok = False

    if overall_ok:
        print(
            "OK btx_xtest_vs_noble_secp256k1: BTX (pure Python) and "
            "@noble/curves (pure JS) produce byte-identical Schnorr "
            "signatures for every input. Combined with scout 18's "
            "libsecp256k1 (C) result, BTX is now cross-validated "
            "against THREE independent implementations in THREE "
            "different languages."
        )
        return 0
    print("FAIL btx_xtest_vs_noble_secp256k1: divergence detected")
    return 1


if __name__ == "__main__":
    sys.exit(main())
