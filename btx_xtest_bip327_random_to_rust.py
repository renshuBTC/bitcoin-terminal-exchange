#!/usr/bin/env python3
"""
btx_xtest_bip327_random_to_rust — generate N random MuSig2 sessions via the
Python wrapper and dump them as a JSON golden file consumed by the brk-btx
Rust port (`crates/brk_indexer/src/btx_musig2_protocol.rs`).

The goal: cover the Python→Rust verification loop with **random inputs**,
in addition to the canonical BIP-327 vector files. Random inputs catch
implementation bugs that fixed vectors can't (e.g. wrong parity handling
that happens to align with a chosen pubkey, off-by-one in coefficient
order, etc.).

Output schema (one JSON document):
{
  "n_sessions": N,
  "sessions": [
    {
      "comment": "n_signers=K signer_index=i",
      "pubkeys_hex":  ["<33 bytes>", ...],         # BIP-327 PlainPubkey
      "pnonces_hex":  ["<66 bytes>", ...],
      "aggnonce_hex": "<66 bytes>",
      "msg_hex":      "<32 bytes>",
      "signer_index": i,
      "psig_hex":     "<32 bytes>",
      "agg_sig_hex":  "<64 bytes>",                # final aggregated sig
      "tweaks_hex":   [],
      "is_xonly":     []
    },
    ...
  ]
}

Wire as a brk-btx Rust test: regenerate this file via this script whenever
the wrapper or the Rust port changes.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))


def _find_bip327_reference() -> str | None:
    for cand in (
        os.path.expanduser(
            "~/Documents/Claude/Projects/Bitcoin CoreX/"
            "bitcoin-bips-reference/bip-0327"
        ),
        "/sessions/keen-determined-einstein/mnt/Bitcoin CoreX/"
        "bitcoin-bips-reference/bip-0327",
    ):
        if os.path.isdir(cand) and os.path.isfile(os.path.join(cand, "reference.py")):
            return cand
    return None


def main(argv: list[str]) -> int:
    ref = _find_bip327_reference()
    if ref is None:
        print("[SKIP] BIP-327 reference directory not found", file=sys.stderr)
        return 0
    # The reference dir needs to be on sys.path for the wrapper.
    sys.path.insert(0, ref)

    try:
        import btx_musig2_bip327_protocol as M
        # We also need the reference's IndividualPubkey helper to derive 33-byte
        # plain pubkeys from secret keys.
        import reference as bip327_ref
    except ImportError as e:
        print(f"[SKIP] {e}", file=sys.stderr)
        return 0

    if len(argv) >= 2:
        out_path = Path(argv[1])
    else:
        out_path = (
            HERE.parent / "brk-btx" / "crates" / "brk_indexer" / "tests"
            / "musig2_protocol_random_golden.json"
        )

    n_sessions = int(os.environ.get("BTX_MUSIG2_RAND_N", "20"))
    rng = secrets.SystemRandom()

    sessions: list[dict] = []
    for sess_idx in range(n_sessions):
        # Choose random ensemble size.
        k = rng.choice([2, 3, 5])

        # Random secret keys (1 .. n-1).
        sks: list[bytes] = []
        for _ in range(k):
            # Reject 0 and oversize.
            while True:
                cand = secrets.token_bytes(32)
                v = int.from_bytes(cand, "big")
                if 0 < v < bip327_ref.n:
                    sks.append(cand)
                    break

        # Per-signer 33-byte plain pubkey via IndividualPubkey.
        pks: list[bytes] = [bip327_ref.individual_pk(sk) for sk in sks]

        # Per-signer nonce generation. nonce_gen needs aggpk (the x-only KeyAgg
        # output) for proper context-binding. Compute KeyAgg first.
        aggpk_ctx = bip327_ref.key_agg(pks)
        aggpk_xonly = bip327_ref.get_xonly_pk(aggpk_ctx)

        msg = secrets.token_bytes(32)

        secnonces: list[bytearray] = []
        pubnonces: list[bytes] = []
        for sk, pk in zip(sks, pks):
            secn, pubn = M.nonce_gen(sk, pk, aggpk_xonly, msg, None)
            secnonces.append(secn)
            pubnonces.append(pubn)

        aggnonce = M.nonce_agg(pubnonces)

        # No tweaks for this random pass — keeps focus on the multi-round core.
        tweaks: list[bytes] = []
        is_xonly: list[bool] = []

        ctx = M.session_context(aggnonce, pks, tweaks, is_xonly, msg)

        psigs: list[bytes] = []
        for i, sk in enumerate(sks):
            psig = M.sign(secnonces[i], sk, ctx)
            # Confirm Python-side verify accepts every partial sig — this is
            # the wrapper's own sanity check before the Rust round-trip.
            assert M.partial_sig_verify(psig, pubnonces, pks, tweaks, is_xonly, msg, i), \
                f"Python-side verify rejected session {sess_idx} signer {i}"
            psigs.append(psig)

        agg_sig = M.partial_sig_agg(psigs, ctx)

        # Pick a random signer to be the "subject" of the Rust verify test.
        # We include ALL partial sigs in the JSON, so the Rust test can verify
        # each signer's contribution independently.
        signer_index = rng.randrange(k)

        sessions.append({
            "comment": f"n_signers={k} signer_index={signer_index}",
            "pubkeys_hex": [pk.hex() for pk in pks],
            "pnonces_hex": [pn.hex() for pn in pubnonces],
            "aggnonce_hex": aggnonce.hex(),
            "msg_hex": msg.hex(),
            "signer_index": signer_index,
            "psig_hex": psigs[signer_index].hex(),
            "all_psigs_hex": [p.hex() for p in psigs],
            "agg_sig_hex": agg_sig.hex(),
            "tweaks_hex": [t.hex() for t in tweaks],
            "is_xonly": is_xonly,
        })

    doc = {"n_sessions": n_sessions, "sessions": sessions}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(doc, f, indent=2)
    print(f"OK wrote {n_sessions} random MuSig2 sessions -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
