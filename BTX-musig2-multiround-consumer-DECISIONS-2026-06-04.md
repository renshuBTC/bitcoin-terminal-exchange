# BTX2 multi-round MuSig2 — decisions (2026-06-04)

**Companion to** `BTX-musig2-multiround-consumer-survey-2026-06-04.md`.
That memo surveyed the design space. This memo records the decisions
made on each of its 3 open questions, with the reasoning grounded in
BTX's core constraint:

> *"BTX rails = ZERO offchain deps; counter-asset = a RUNE stablecoin
> (token on-chain; peg is asset's opt-in issuer, not a BTX dep); prefer
> BTC-backed (USDh/Ducat)."* — from project memory `feedback_nothing_offchain`

Every decision below is scored against the question: *does this make
BTX a better fully-on-chain exchange?* If the answer is "yes and the
on-chain cost is bounded", the answer is YES. If the answer is "yes but
the on-chain mechanism requires Bitcoin features we don't have", the
answer is DEFERRED. If the answer is "marginal benefit, real complexity",
the answer is NO.

---

## Decision 1 — Multi-org maker pools: **YES**

**The pick.** BTX2 explicitly supports multi-org maker pools as a
first-class configuration of §5.

**Why.** A fully-on-chain exchange's competitive constraint is liquidity.
Single-org pools cap a pool's capital at one firm's balance sheet. Multi-org
pools let independent market-makers pool capital without trusting a
custodian — which is exactly the property a BTC-native exchange should
exploit relative to CEX competitors. Light Pools (the BTX competitive
benchmark per memory `reference_light_pools`) already enables this pattern
on a non-Bitcoin chain; BTX should match it on Bitcoin.

**On-chain cost.** Zero. Per `BTX-v2-spec-2026-06-02.md §5`:
> *"Indexer experience: the indexer sees a vanilla SINGLE_ORDER record
> with a 32-byte maker_pubkey and a 64-byte Schnorr sig. It cannot tell
> whether the order is from a single maker or a pool. This is by design
> — maker pool participation is private at the chain layer."*

This decision changes nothing on-chain. It clarifies that the multi-org
configuration is an intended, supported deployment mode, not an edge case.

**What it requires.** The off-chain coordination tooling (aggregator,
nonce exchange, partial-sig exchange) must be production-ready for
mutually-distrusting signers. §9.2's existing nonce-handling requirements
are already adequate for this — the bar is implementation hygiene, not
new cryptography.

**What it does NOT require.** No new record type. No on-chain bonds.
No multi-sig scripts. No ceremony envelope. The aggregated pool pubkey
publishes vanilla SINGLE_ORDER records and the indexer remains oblivious.

---

## Decision 2 — Slashing: **NO** (deferred to post-covenant)

**The pick.** BTX2 does NOT introduce slashing in v1.

**Why.** Slashing requires three primitives Bitcoin doesn't have natively:
1. **Locked bonds** that can be transferred conditionally on a fraud
   proof. Without covenants (`OP_CTV`, `OP_VAULT`, etc.), this requires
   either a federation (off-chain trust) or pre-signed transactions (which
   bound the slashing window in a fragile way).
2. **Dispute windows** with deterministic clearing. The indexer can
   model these, but enforcement still depends on either covenants or
   off-chain coordination.
3. **Fraud-proof verification.** The Rust port shipped at commit
   `60ebb51` can verify a fraud proof, but only after the fraud-proof
   record has been encoded into an envelope. That encoding is itself
   ~600+ bytes of new on-chain payload (per §3.1 of the survey).

The combination of (1) + (2) means any v1 slashing mechanism either:
- Requires off-chain enforcement → violates BTX's "ZERO offchain deps"
  principle.
- Requires pre-signed transactions that lock funds for a fixed window
  → operational burden similar to Lightning, but without Lightning's
  routing payoff.
- Requires Bitcoin covenants → not deployed on mainnet.

**Competitive context.** Light Pools (the benchmark) doesn't slash. CEXes
don't slash market-makers — they ban them. Slashing is a feature
non-Bitcoin chains (Ethereum staking, Cosmos validators) introduced
specifically because they have native covenants and their security
model demands it. BTX doesn't need to invent a feature its competitors
don't have unless there's a clear reason, and there isn't one.

**The right response to misbehaving pool members.** Pool aggregators
detect bad partial sigs locally (now in Rust too, via
`btx_musig2_protocol::partial_sig_verify`), exclude the bad member from
the pool's pubkey ratchet, and the pool continues. No on-chain artifact
is needed because the on-chain artifact is always just an aggregated
64-byte BIP-340 sig — a misbehaving member literally cannot publish a
bad pool order because they can't produce a valid aggregated sig without
the other members' cooperation.

This is the "fail-stop" behavior of MuSig2: bad partial sig → no
aggregated sig → no on-chain action. The honest pool members just
re-run the session without the misbehaving party. That's enforcement
enough at the protocol layer.

**Revisit when.** Bitcoin covenants ship on mainnet, OR a concrete
attack scenario emerges that fail-stop doesn't address. Until then,
adding slashing would be inventing a problem.

---

## Decision 3 — Rust pool aggregators: **YES (optionality), defer the port**

**The pick.** BTX2 supports Rust aggregators as a deployment option.
The verification half of the Rust port already ships (commit `60ebb51`,
3 of 8 BIP-327 vector files + Py↔Rust random cross-test). The signing
half is **future work**, gated on a concrete aggregator service being
written that needs it.

**Why YES on optionality.** Operators that already run brk-btx in Rust
(the indexer) shouldn't be forced to add a Python runtime to operate a
pool. Optionality is cheap to declare and expensive to retrofit later;
declaring it now keeps the door open.

**Why DEFER the port.** Three reasons stacked:

1. **No real consumer exists today.** The §2.1 consumer in the consumer
   survey is hypothetical — "does BTX2 have / plan a Rust-side aggregator
   service?" got "the spec doesn't say". Building a port for a
   non-existent consumer is the kind of premature work that turns into
   maintenance debt.

2. **The Python wrapper is more battle-tested for the signing path.**
   Per §9.2 of the spec: nonce handling is the riskiest part of MuSig2.
   The Python BIP-327 reference has more eyeballs on its signing
   implementation than any from-scratch Rust port will. Defer the
   reimplementation until the actual aggregator service architecture is
   designed.

3. **The verification port already pays the principal benefit.** A pool
   aggregator that runs Python for signing and Rust for verification is
   a fine deployment — the verification path is where consensus-critical
   checks happen ("did this partial sig actually authorize the
   aggregation?"). The signing path is just nonce gen + math; getting it
   wrong in Rust hurts only the operator running it, not the network.

**Concrete commitment.** The next time someone writes a brk-btx-side
pool aggregator service, the signing port (`nonce_gen`, `sign`,
`deterministic_sign` — ~400-500 LOC + cross-tests against the wrapper)
becomes their first task. The 5-step wrapper-then-cross-test recipe from
this session is the playbook.

---

## What changes in the spec

This memo recommends a small amendment to
`BTX-v2-spec-2026-06-02.md §11 (Open questions)` that records the
decisions above with pointers back to this doc. It does NOT recommend
modifying §5 (Maker pools), §9.2 (Nonce handling), or §10 (Reference
implementation map) — those sections are already correct under these
decisions. The only spec change is in §11 because three of its open
questions just got closed.

---

## Summary table

| Question | Decision | Why |
| -------- | -------- | --- |
| Multi-org maker pools | **YES** | Zero on-chain cost; matches BTX's competitive benchmark; liquidity case is clear |
| Slashing in v1 | **NO** | Needs covenants Bitcoin doesn't have; fail-stop suffices; no consumer is asking |
| Rust pool aggregators | **YES, defer port** | Optionality is cheap; no real consumer today; verification half already covers consensus-critical path |

These three decisions together preserve the BTX core constraint:
**zero off-chain dependencies and zero new on-chain payload.** The Rust
port shipped this session enables a future Rust aggregator without
demanding one exist today.

---

*Authored 2026-06-04, post-`278b7bd`. Companion to the consumer survey.
Cross-links: `[[project-brk-btx-musig2-protocol-2026-06-04]]`,
`BTX-v2-spec-2026-06-02.md §5 + §9.2 + §10 + §11 + §12`,
`feedback_nothing_offchain`, `reference_light_pools`.*
