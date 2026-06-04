#!/usr/bin/env python3
"""
btx_pool_ceremony_failstop_demo — empirical evidence for the §11.x
"NO slashing in v1" decision.

The decision rested on this claim:

  > MuSig2 fail-stop suffices: a misbehaving pool member literally
  > cannot produce a valid aggregated sig without honest members'
  > cooperation. The pool just re-runs the session without them.

This demo proves the claim concretely. Three scenarios:

  Scenario A — Honest baseline: every member follows the protocol.
               Ceremony succeeds. (Sanity check.)

  Scenario B — Adversarial member submits a garbage partial sig.
               The pre-aggregation verification step catches it; honest
               members refuse to allow aggregation. NO sig published.
               Re-running without the bad member succeeds.

  Scenario C — Adversarial member submits a partial sig over the WRONG
               message (e.g. trying to sign a different order than what
               the pool agreed on). Same outcome — caught, aborted.

If A succeeds and both B and C produce no on-chain sig, the §11.x
decision is empirically supported: BTX2 doesn't need slashing because
the protocol's own pre-aggregation step is enforcement enough.

Run:
    python3 btx_pool_ceremony_failstop_demo.py
"""
from __future__ import annotations

import os
import secrets
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


def run_ceremony(M, ref, members_sk: list[bytes], adversary_index: Optional[int], adversary_mode: str, msg: bytes):
    """Returns (ok, agg_sig_or_None, reason)."""
    pks = [ref.individual_pk(sk) for sk in members_sk]
    order = sorted(range(len(pks)), key=lambda i: pks[i])
    sorted_pks = [pks[i] for i in order]
    sorted_sks = [members_sk[i] for i in order]
    # Map adversary_index in original order -> sorted-list index
    adversary_sorted = None if adversary_index is None else order.index(adversary_index)

    aggpk_xonly = ref.get_xonly_pk(ref.key_agg(sorted_pks))

    # Round 1: nonces.
    secnonces, pubnonces = [], []
    for sk, pk in zip(sorted_sks, sorted_pks):
        secn, pubn = M.nonce_gen(sk, pk, aggpk_xonly, msg, None)
        secnonces.append(secn)
        pubnonces.append(pubn)
    aggnonce = M.nonce_agg(pubnonces)

    # Round 2: partial sigs.
    ctx = M.session_context(aggnonce, sorted_pks, [], [], msg)
    psigs = []
    for i, sk in enumerate(sorted_sks):
        if i == adversary_sorted and adversary_mode == "garbage":
            # Adversary submits a random 32-byte string instead of a valid psig.
            psigs.append(secrets.token_bytes(32))
        elif i == adversary_sorted and adversary_mode == "wrong_msg":
            # Adversary signs a DIFFERENT message — equivalent to trying to
            # authorize a different order than the pool agreed on.
            other_msg = secrets.token_bytes(32)
            other_ctx = M.session_context(aggnonce, sorted_pks, [], [], other_msg)
            psigs.append(M.sign(secnonces[i], sk, other_ctx))
        else:
            psigs.append(M.sign(secnonces[i], sk, ctx))

    # Pre-aggregation: every member verifies every other member's psig.
    for verifier_idx in range(len(sorted_pks)):
        for i, psig in enumerate(psigs):
            ok = M.partial_sig_verify(psig, pubnonces, sorted_pks, [], [], msg, i)
            if not ok:
                return (False, None,
                        f"member {verifier_idx} rejected partial sig from member {i}")

    # All good — aggregate.
    agg_sig = M.partial_sig_agg(psigs, ctx)
    return (True, agg_sig, "all members verified all partials")


def main() -> int:
    ref_dir = _find_bip327_reference()
    if ref_dir is None:
        print("[SKIP] BIP-327 reference directory not found", file=sys.stderr)
        return 0
    sys.path.insert(0, ref_dir)
    try:
        import btx_musig2_bip327_protocol as M
        import reference as ref
        import btx_taproot as taproot
    except ImportError as e:
        print(f"[SKIP] {e}", file=sys.stderr)
        return 0

    N = 3
    # Reuse the same sks across scenarios so the "with vs without the bad
    # actor" comparison is apples-to-apples.
    sks = []
    for _ in range(N):
        while True:
            sk = secrets.token_bytes(32)
            if 0 < int.from_bytes(sk, "big") < ref.n:
                sks.append(sk)
                break
    msg = secrets.token_bytes(32)

    print("=== Scenario A — honest baseline (sanity check) ===")
    ok, sig, reason = run_ceremony(M, ref, sks, None, "honest", msg)
    assert ok, f"baseline should succeed: {reason}"
    aggpk = ref.get_xonly_pk(ref.key_agg(sorted([ref.individual_pk(s) for s in sks])))
    assert taproot.schnorr_verify(msg, aggpk, sig), "baseline sig should BIP-340 verify"
    print(f"  OK — aggregated sig: {sig.hex()[:32]}... BIP-340 verifies")

    print("\n=== Scenario B — member 1 submits a garbage partial sig ===")
    ok, sig, reason = run_ceremony(M, ref, sks, 1, "garbage", msg)
    assert not ok, "B should be detected!"
    assert sig is None
    print(f"  OK — ceremony aborted: {reason}")
    print(f"  NO sig was published. No on-chain artifact exists.")

    print("\n=== Scenario C — member 2 signs a DIFFERENT message (order swap) ===")
    ok, sig, reason = run_ceremony(M, ref, sks, 2, "wrong_msg", msg)
    assert not ok, "C should be detected!"
    assert sig is None
    print(f"  OK — ceremony aborted: {reason}")
    print(f"  NO sig was published. No on-chain artifact exists.")

    print("\n=== Scenario D — re-run B without the bad actor ===")
    honest_sks = [sks[i] for i in range(N) if i != 1]
    ok, sig, reason = run_ceremony(M, ref, honest_sks, None, "honest", msg)
    assert ok, f"D should succeed: {reason}"
    aggpk_new = ref.get_xonly_pk(ref.key_agg(sorted([ref.individual_pk(s) for s in honest_sks])))
    assert taproot.schnorr_verify(msg, aggpk_new, sig), "D sig should BIP-340 verify"
    print(f"  OK — 2-of-2 pool succeeds; the bad actor is simply excluded.")
    print(f"  Note: the pool's aggregated pubkey CHANGED ({aggpk.hex()[:16]}.. → {aggpk_new.hex()[:16]}..)")
    print(f"  In a real pool, this would require a key-rotation envelope.")

    print("\n=== Conclusion ===")
    print("MuSig2 fail-stop empirically suffices to prevent on-chain damage")
    print("from a misbehaving member. No slashing mechanism is required to")
    print("keep BTX2 secure under the §5 maker-pool protocol.")
    print(f"\n§11.x Decision 2 (NO slashing in v1) — empirically supported.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
