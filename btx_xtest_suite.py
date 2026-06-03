#!/usr/bin/env python3
"""
btx_xtest_suite.py — unified cross-validation tripwire.

Runs ALL of BTX's external cross-tests in sequence and reports a unified
pass/fail. This is the canonical "did BTX foundation regress?" gate.

Each sub-test is independent and re-runnable on its own; this runner just
sequences them and rolls up the results.

## What gets exercised

  1. btx_bip340_xtest.py
     Foundation Schnorr (sign + verify) against
     bitcoin/bips/bip-0340/test-vectors.csv (19 official vectors).
     Catches any BIP-340 regression.

  2. btx_bip341_xtest.py
     Foundation Taproot (tweak + scriptPubKey + bech32m address +
     keyPathSpending sighash) against
     bitcoin/bips/bip-0341/wallet-test-vectors.json (7+7+7+7 cases).
     Catches any BIP-341 regression.

  3. btx_bip327_xtest.py
     MuSig2 KeyAgg variant + canonical port against
     bitcoin/bips/bip-0327/vectors/key_agg_vectors.json (4 cases).
     Detects the documented x-only-input variant on `key_agg` AND
     verifies the canonical port `key_agg_bip327` matches all 4 vectors.

  4. btx_runes_xcheck.py
     Runes decoder against Magic Eden runestone-lib (19 golden vectors).
     Catches any divergence from the dormant-but-frozen ME reference.

  5. btx_runestone_cenotaph_adversarial.py
     8 named cenotaph triggers + 2 controls + 50,000-shape totality fuzz.
     Catches any over/under-classification of malformed runestones.

## Reference checkouts required

Both clones live in `~/Documents/Claude/Projects/Bitcoin CoreX/` on the
host:
  - bitcoin-bips-reference/  (bitcoin/bips at depth=1)
  - ord-reference/           (ordinals/ord)
  - runestone-lib-reference/ (me-foundation/runestone-lib; dormant)

If any clone is missing, the corresponding sub-test reports MISSING and
is excluded from the pass/fail rollup.

## Usage

  python3 btx_xtest_suite.py             # run all, print summary
  python3 btx_xtest_suite.py --quiet     # only the rollup line
  python3 btx_xtest_suite.py --verbose   # show per-test stdout

Exit code 0 if all available tests pass; non-zero if any fail. Missing
tests do not affect exit code (they're flagged but not failed).
"""

from __future__ import annotations
import os
import subprocess
import sys
import time
from pathlib import Path


# Each entry: (display_name, script_filename, requires_path or None)
# The optional requires_path is checked before running; if missing, the
# sub-test is reported as SKIPPED rather than FAILED.
SUB_TESTS = [
    (
        "BIP-340 Schnorr (foundation)",
        "btx_bip340_xtest.py",
        "Bitcoin CoreX/bitcoin-bips-reference/bip-0340/test-vectors.csv",
    ),
    (
        "BIP-341 Taproot (foundation)",
        "btx_bip341_xtest.py",
        "Bitcoin CoreX/bitcoin-bips-reference/bip-0341/wallet-test-vectors.json",
    ),
    (
        "BIP-327 MuSig2 KeyAgg (variant + canonical port)",
        "btx_bip327_xtest.py",
        "Bitcoin CoreX/bitcoin-bips-reference/bip-0327/vectors/key_agg_vectors.json",
    ),
    (
        "BIP-374 DLEQ (single-curve discrete log equality)",
        "btx_bip374_xtest.py",
        "Bitcoin CoreX/bitcoin-bips-reference/bip-0374/test_vectors_generate_proof.csv",
    ),
    (
        "Runes decoder vs Magic Eden (asset layer)",
        "btx_runes_xcheck.py",
        None,  # frozen golden vectors are inline in the script itself
    ),
    (
        "Runestone cenotaph adversarial (50,000-fuzz)",
        "btx_runestone_cenotaph_adversarial.py",
        None,
    ),
]


def _host_path_to_sandbox(host_relative: str) -> str:
    """
    Map the `Documents/Claude/Projects/...` relative paths shipped in the
    test scripts to whichever location actually exists on this runner.
    Looks in canonical host path, then the WSL/sandbox mount.
    """
    candidates = [
        os.path.expanduser(f"~/Documents/Claude/Projects/{host_relative}"),
        f"/mnt/c/Users/Ren Shu/Documents/Claude/Projects/{host_relative}",
        f"/sessions/keen-determined-einstein/mnt/{host_relative.split('/', 1)[-1]}",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return ""


def run_one(name, script, requires_path, verbose=False):
    """
    Run one sub-test. Returns (status, elapsed_secs, summary_line).
    status is one of: PASS, FAIL, MISSING, SKIPPED, ERROR.
    """
    here = Path(__file__).parent
    script_path = here / script
    if not script_path.exists():
        return ("MISSING", 0.0, f"script not found: {script_path}")

    if requires_path:
        if not _host_path_to_sandbox(requires_path):
            return (
                "SKIPPED",
                0.0,
                f"reference not found: {requires_path} (clone the source repo)",
            )

    t0 = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return ("ERROR", time.time() - t0, "timed out after 120s")
    elapsed = time.time() - t0

    if verbose:
        print(f"--- {name} stdout ---")
        print(proc.stdout)
        if proc.stderr.strip():
            print(f"--- stderr ---")
            print(proc.stderr)

    if proc.returncode == 0:
        # Extract a 1-line summary from the bottom of stdout
        lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
        summary = lines[-1] if lines else "(no output)"
        return ("PASS", elapsed, summary[:120])
    else:
        # Pull last non-empty line of stderr or stdout
        for stream in (proc.stderr, proc.stdout):
            lines = [ln for ln in stream.strip().splitlines() if ln.strip()]
            if lines:
                return ("FAIL", elapsed, f"rc={proc.returncode} {lines[-1][:120]}")
        return ("FAIL", elapsed, f"rc={proc.returncode} (no output)")


def main():
    argv = sys.argv[1:]
    quiet = "--quiet" in argv
    verbose = "--verbose" in argv

    results = []
    for name, script, requires in SUB_TESTS:
        if not quiet:
            print(f"[ running ] {name}", flush=True)
        status, elapsed, summary = run_one(name, script, requires, verbose=verbose)
        results.append((name, status, elapsed, summary))
        if not quiet:
            marker = {
                "PASS": "✓",
                "FAIL": "✗",
                "MISSING": "?",
                "SKIPPED": "·",
                "ERROR": "!",
            }[status]
            print(f"[{marker} {status:7}] {name}  ({elapsed:.2f}s)")
            print(f"             {summary}")

    pass_count = sum(1 for _, s, _, _ in results if s == "PASS")
    fail_count = sum(1 for _, s, _, _ in results if s in ("FAIL", "ERROR"))
    skip_count = sum(1 for _, s, _, _ in results if s in ("SKIPPED", "MISSING"))
    total = len(results)

    if not quiet:
        print()
        print(f"=== btx_xtest_suite ===")
        print(f"  passed:  {pass_count}/{total}")
        print(f"  failed:  {fail_count}/{total}")
        print(f"  skipped: {skip_count}/{total}  (reference repos not cloned locally)")

    # Final one-liner is the verdict
    if fail_count == 0:
        verdict = (
            f"✓ btx_xtest_suite: {pass_count} PASS, {skip_count} skipped, 0 FAIL"
        )
    else:
        verdict = (
            f"✗ btx_xtest_suite: {pass_count} PASS, {fail_count} FAIL, {skip_count} skipped"
        )
    print(verdict)

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
