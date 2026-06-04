#!/usr/bin/env python3
"""
btx_pool_ceremony_demo — Phase B of Decision 1 (multi-org maker pools).

Demonstrates a full N-of-N multi-round MuSig2 ceremony with **mutually-
distrusting** members. Each `PoolMember` holds only their own secret key.
A `PoolCoordinator` routes messages but has no key material. After the
ceremony completes, the coordinator publishes a BTX SINGLE_ORDER record
that's indistinguishable on-chain from a single-maker order.

This is the reference flow for the §5 maker-pool protocol with the
multi-org configuration of Decision 1 enabled. It uses:

  - bitcoin-terminal-exchange/btx_musig2_bip327_protocol (Python wrapper)
    for the signing-side path.
  - bitcoin-terminal-exchange/btx_taproot for BIP-340 verification of
    the final aggregated sig (representing what the on-chain indexer /
    Bitcoin node would do).

Two safety properties this demo enforces (matching BTX-v2-spec §9.2):

  1. Each member verifies EVERY other member's partial sig before
     allowing aggregation. A member who can't verify everyone refuses to
     contribute their own partial sig to the aggregation step.
  2. Each member's secnonce is single-use — the wrapper's `sign()`
     internally enforces this (reference impl zeroes secnonce on use).

What this demo does NOT do (out of scope; future work):

  - Wire protocol framing (this just passes Python dicts around).
  - Adversarial-member fail-stop demo (separate test).
  - On-chain envelope construction (we stop at "we have a valid 64-byte
    BIP-340 sig the coordinator could embed in a SINGLE_ORDER record").

Run:
    python3 btx_pool_ceremony_demo.py             # 3-of-3, default
    POOL_N=5 python3 btx_pool_ceremony_demo.py    # 5-of-5

Returns exit 0 on success; exits non-zero with diagnostics on any check
failure.
"""
from __future__ import annotations

import os
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))


def _find_bip327_reference() -> Optional[str]:
    for c in (
        os.path.expanduser(
            "~/Documents/Claude/Projects/Bitcoin CoreX/"
            "bitcoin-bips-reference/bip-0327"
        ),
        "/sessions/keen-determined-einstein/mnt/Bitcoin CoreX/"
        "bitcoin-bips-reference/bip-0327",
    ):
        if os.path.isdir(c) and os.path.isfile(os.path.join(c, "reference.py")):
            return c
    return None


# --- Member-side state -----------------------------------------------


@dataclass
class PoolMember:
    """One participant in a multi-org maker pool.

    Holds ONLY this member's secret key. Receives other members' pubkeys
    and nonces via the coordinator; never sees anyone else's sk.
    """
    name: str
    sk: bytes
    pk: bytes                                              # 33-byte plain
    # Cached across the ceremony (filled progressively):
    pool_pubkeys: list[bytes] = field(default_factory=list)   # 33-byte each
    aggpk_xonly: Optional[bytes] = None                       # 32-byte
    secnonce: Optional[bytearray] = None
    pubnonce: Optional[bytes] = None
    aggnonce: Optional[bytes] = None
    msg: Optional[bytes] = None
    my_psig: Optional[bytes] = None
    my_index: Optional[int] = None

    # ---- setup ceremony ----
    def set_pool(self, pool_pubkeys: list[bytes], M) -> None:
        """Step 1: receive the canonical (sorted) pubkey list, verify our pk
        is in it, compute the aggregated pubkey, verify we got the same
        result every other member will get."""
        if self.pk not in pool_pubkeys:
            raise ValueError(f"{self.name}: my pk not in pool")
        self.pool_pubkeys = pool_pubkeys
        self.my_index = pool_pubkeys.index(self.pk)
        # Independent KeyAgg (each member runs this independently).
        import reference as ref
        agg = ref.key_agg(pool_pubkeys)
        self.aggpk_xonly = ref.get_xonly_pk(agg)

    # ---- round 1: nonces ----
    def round1_nonce(self, msg: bytes, M) -> bytes:
        """Step 2: generate this member's nonces, store secret nonce locally,
        return public nonce for the coordinator to fan out."""
        assert self.aggpk_xonly is not None, "setup not done"
        self.msg = msg
        rand_ = secrets.token_bytes(32)
        self.secnonce, self.pubnonce = M.nonce_gen(
            self.sk, self.pk, self.aggpk_xonly, msg, None
        )
        return self.pubnonce

    # ---- round 2: partial sig ----
    def round2_partial(self, all_pubnonces: list[bytes], aggnonce: bytes, M) -> bytes:
        """Step 3: receive everyone's pubnonces + the aggregated nonce.

        SAFETY CHECK: independently recompute aggnonce from all_pubnonces
        and confirm it matches what the coordinator sent. A dishonest
        coordinator could otherwise feed mismatched nonces to different
        members.
        """
        assert self.msg is not None, "round 1 not done"
        assert self.secnonce is not None
        # Independent aggnonce check.
        my_agg = M.nonce_agg(all_pubnonces)
        if my_agg != aggnonce:
            raise ValueError(
                f"{self.name}: coordinator's aggnonce doesn't match independent computation; aborting"
            )
        self.aggnonce = aggnonce
        ctx = M.session_context(aggnonce, self.pool_pubkeys, [], [], self.msg)
        self.my_psig = M.sign(self.secnonce, self.sk, ctx)
        return self.my_psig

    # ---- pre-aggregation verification ----
    def verify_all_partials(self, all_psigs: list[bytes], all_pubnonces: list[bytes], M) -> bool:
        """Step 4: BEFORE allowing aggregation, verify every other member's
        partial sig. If anyone is invalid, refuse to allow aggregation —
        the session must be re-run without the misbehaving member."""
        for i, psig in enumerate(all_psigs):
            ok = M.partial_sig_verify(
                psig, all_pubnonces, self.pool_pubkeys, [], [], self.msg, i
            )
            if not ok:
                print(f"  {self.name}: REJECTED partial sig from member {i}", file=sys.stderr)
                return False
        return True


# --- Coordinator (no key material) ----------------------------------


@dataclass
class PoolCoordinator:
    """Holds NO secret keys. Routes messages between members."""
    members: list[PoolMember]
    M: object

    def setup(self) -> None:
        # Canonical pubkey order: lex-sort by 33-byte pubkey, per §5.
        sorted_pks = sorted(m.pk for m in self.members)
        for m in self.members:
            m.set_pool(sorted_pks, self.M)
        # Verify all members independently derived the same aggpk.
        xonlys = {m.aggpk_xonly for m in self.members}
        assert len(xonlys) == 1, "setup: aggregated pubkey divergence"
        print(f"  setup OK — pool aggpk: {next(iter(xonlys)).hex()}")

    def sign_order(self, msg: bytes) -> bytes:
        # Process members in canonical (sorted-by-pk) order so that
        # pubnonces[i] / psigs[i] align with pool_pubkeys[i]. partial_sig_verify
        # requires this index alignment.
        ordered = sorted(self.members, key=lambda m: m.pk)

        # Round 1: collect pubnonces in canonical order.
        pubnonces: list[bytes] = []
        for m in ordered:
            pubnonces.append(m.round1_nonce(msg, self.M))
        aggnonce = self.M.nonce_agg(pubnonces)
        print(f"  round 1 done — aggnonce: {aggnonce.hex()[:16]}...")

        # Round 2: collect partial sigs in the same canonical order.
        psigs: list[bytes] = []
        for m in ordered:
            psigs.append(m.round2_partial(pubnonces, aggnonce, self.M))
        print(f"  round 2 done — {len(psigs)} partial sigs collected")

        # Pre-aggregation safety: every member must accept every partial sig.
        for m in self.members:
            if not m.verify_all_partials(psigs, pubnonces, self.M):
                raise RuntimeError(
                    f"{m.name} refused to allow aggregation — ceremony aborted"
                )
        print(f"  pre-agg check OK — all {len(self.members)} members verified all partials")

        # Aggregate.
        ctx = self.M.session_context(
            aggnonce, self.members[0].pool_pubkeys, [], [], msg
        )
        agg_sig = self.M.partial_sig_agg(psigs, ctx)
        print(f"  aggregated sig: {agg_sig.hex()}")
        return agg_sig


# --- Main demo ------------------------------------------------------


def main() -> int:
    ref_dir = _find_bip327_reference()
    if ref_dir is None:
        print("[SKIP] BIP-327 reference directory not found", file=sys.stderr)
        return 0
    sys.path.insert(0, ref_dir)

    try:
        import btx_musig2_bip327_protocol as M
        import reference as bip327_ref
        import btx_taproot as taproot
    except ImportError as e:
        print(f"[SKIP] {e}", file=sys.stderr)
        return 0

    N = int(os.environ.get("POOL_N", "3"))
    if N < 2:
        print(f"POOL_N must be >= 2 (got {N})", file=sys.stderr)
        return 2
    print(f"=== Multi-org maker pool ceremony — {N} mutually-distrusting members ===")

    # Each member generates their own secret key locally.
    members: list[PoolMember] = []
    for i in range(N):
        while True:
            sk = secrets.token_bytes(32)
            if 0 < int.from_bytes(sk, "big") < bip327_ref.n:
                break
        pk = bip327_ref.individual_pk(sk)
        members.append(PoolMember(name=f"member{i}", sk=sk, pk=pk))

    coord = PoolCoordinator(members=members, M=M)
    coord.setup()

    # Each "per-order" cycle (in a real pool, this happens every time the
    # pool wants to publish a new SINGLE_ORDER).
    msg = secrets.token_bytes(32)
    print(f"  signing msg: {msg.hex()}")
    agg_sig = coord.sign_order(msg)

    # Now the consensus-level check: does the aggregated sig BIP-340-verify
    # under the pool's aggregated x-only pubkey? This is exactly what the
    # BTX indexer (or any Bitcoin node) would do when it sees the pool's
    # SINGLE_ORDER record.
    aggpk_xonly = members[0].aggpk_xonly
    assert taproot.schnorr_verify(msg, aggpk_xonly, agg_sig), \
        "BIP-340 verify FAILED on aggregated sig"
    print(f"  BIP-340 verify OK under aggpk {aggpk_xonly.hex()}")

    print(f"\n=== {N}-of-{N} pool ceremony OK — aggregated sig is on-chain-ready ===")
    print(f"    indistinguishable from a single-maker SINGLE_ORDER at the chain layer (§5)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
