#!/usr/bin/env python3
"""
btx_xtest_musig2_rust_signed — closes the Rust→Python signing-direction
symmetry. The brk-btx Rust port (commit b6c7e60) produces partial sigs and
an aggregated sig via its own `sign()` + `partial_sig_agg()`; this script
loads the resulting golden and confirms the Python wrapper accepts every
partial sig + the aggregated sig.

The mirror direction (Python signs, Rust verifies) is covered by
`btx_xtest_bip327_random_to_rust.py` + the brk-btx test
`random_python_to_rust_partial_sigs_verify` (commit 672a5c3).

Together, the two directions empirically prove the Python wrapper and the
Rust port produce byte-identical results under each other's inputs across
random signing sessions — beyond the canonical BIP-327 vector coverage.

Regenerate the golden by running this from the brk-btx repo root with
disk space available:

    BTX_DUMP_RUST_SIGNED_JSON=.../musig2_rust_signed_golden.json \
        BTX_DUMP_RUST_SIGNED_N=5 \
        cargo test -p brk_indexer --lib \
        btx_musig2_protocol::tests::dump_rust_signed_sessions_for_python_verify

Run as:
    python3 btx_xtest_musig2_rust_signed.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))


def _find_bip327_reference() -> Optional[str]:
    for c in (
        os.path.expanduser(
            "~/Documents/Claude/Projects/Bitcoin CoreX/bitcoin-bips-reference/bip-0327"
        ),
        "/sessions/keen-determined-einstein/mnt/Bitcoin CoreX/"
        "bitcoin-bips-reference/bip-0327",
    ):
        if os.path.isdir(c) and os.path.isfile(os.path.join(c, "reference.py")):
            return c
    return None


def main() -> int:
    golden = HERE / "musig2_rust_signed_golden.json"
    if not golden.exists():
        print(f"[SKIP] {golden.name} not present — regenerate via brk-btx", file=sys.stderr)
        return 0

    ref_dir = _find_bip327_reference()
    if ref_dir is None:
        print("[SKIP] BIP-327 reference directory not found", file=sys.stderr)
        return 0
    sys.path.insert(0, ref_dir)
    try:
        import btx_musig2_bip327_protocol as M
        import btx_taproot as taproot
    except ImportError as e:
        print(f"[SKIP] {e}", file=sys.stderr)
        return 0

    with open(golden) as f:
        doc = json.load(f)

    total_partials = 0
    sessions_ok = 0
    for sess_idx, sess in enumerate(doc["sessions"]):
        pubkeys = [bytes.fromhex(s) for s in sess["pubkeys_hex"]]
        pubnonces = [bytes.fromhex(s) for s in sess["pnonces_hex"]]
        aggnonce = bytes.fromhex(sess["aggnonce_hex"])
        msg = bytes.fromhex(sess["msg_hex"])
        all_psigs = [bytes.fromhex(s) for s in sess["all_psigs_hex"]]
        agg_sig = bytes.fromhex(sess["agg_sig_hex"])
        tweaks: list[bytes] = []
        is_xonly: list[bool] = []

        # 1. Python wrapper must compute the same aggnonce.
        py_aggnonce = M.nonce_agg(pubnonces)
        assert py_aggnonce == aggnonce, (
            f"session {sess_idx}: Python's nonce_agg disagrees with Rust's"
        )

        # 2. Python wrapper must accept every partial sig.
        for i, psig in enumerate(all_psigs):
            ok = M.partial_sig_verify(
                psig, pubnonces, pubkeys, tweaks, is_xonly, msg, i
            )
            assert ok, (
                f"session {sess_idx}: Python rejected Rust-produced partial sig {i}"
            )
            total_partials += 1

        # 3. Python wrapper's aggregation must match the Rust aggregated sig.
        ctx = M.session_context(aggnonce, pubkeys, tweaks, is_xonly, msg)
        py_agg = M.partial_sig_agg(all_psigs, ctx)
        assert py_agg == agg_sig, (
            f"session {sess_idx}: Python's aggregated sig disagrees with Rust's"
        )

        # 4. The aggregated sig must BIP-340-verify under the aggregated x-only pubkey.
        import reference as bip327_ref
        agg_ctx = bip327_ref.key_agg(pubkeys)
        aggpk_xonly = bip327_ref.get_xonly_pk(agg_ctx)
        assert taproot.schnorr_verify(msg, aggpk_xonly, agg_sig), (
            f"session {sess_idx}: BIP-340 rejected the Rust-produced aggregated sig"
        )

        sessions_ok += 1

    print(
        f"OK btx_xtest_musig2_rust_signed: {sessions_ok}/{len(doc['sessions'])} "
        f"Rust-signed MuSig2 sessions verified by Python wrapper "
        f"({total_partials} partial sigs total). Rust→Python signing-direction "
        f"symmetry confirmed."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
