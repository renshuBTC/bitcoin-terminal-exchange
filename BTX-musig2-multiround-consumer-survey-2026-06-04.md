# BTX2 multi-round MuSig2 — consumer survey (2026-06-04)

**Purpose.** Honest design-space survey of *who actually consumes* the
verification half of BIP-327 multi-round MuSig2 now that the Rust port has
landed in brk-btx (`crates/brk_indexer/src/btx_musig2_protocol.rs`,
commit `60ebb51`). This is NOT a §9.2 redesign — `BTX-v2-spec-2026-06-02.md
§9.2` already covers nonce-handling security, and §5 already specifies the
maker-pool 2-round protocol. The question this doc actually answers is:

> The verification surface is built and tested. Where does it slot in?

**This doc lists options and tradeoffs. It does not pick a winner.** The
choice is yours.

---

## 1. What §5 says about the indexer

Direct quote from `BTX-v2-spec-2026-06-02.md` §5 (Maker pools):

> *"Indexer experience: the indexer sees a vanilla SINGLE_ORDER record with
> a 32-byte maker_pubkey and a 64-byte Schnorr sig. It cannot tell whether
> the order is from a single maker or a pool. This is by design — maker
> pool participation is private at the chain layer."*

**Implication.** The indexer's existing BIP-340 verification path already
handles every maker-pool order ever published — because what lands on-chain
is a vanilla 64-byte Schnorr sig over the aggregated pool pubkey. There is
no on-chain artifact that `partial_sig_verify` consumes. **Therefore the
indexer is not the consumer of the new Rust port.**

This is a real finding. The port has value, but identifying its actual
consumer requires looking past the indexer.

---

## 2. Realistic consumers of `btx_musig2_protocol`

### 2.1 Pool aggregator (Rust runtime)

**Status.** Most likely real consumer.

The aggregator is the participant who collects round-2 partial sigs from
every pool member and combines them into the final 64-byte sig. Per §5
step 4: *"A designated aggregator combines the partials into one 64-byte
Schnorr signature."*

The aggregator MUST verify each member's partial sig before aggregating —
otherwise a malicious member can submit garbage that sabotages the
combined result (or, worse, lets the aggregator generate a sig only the
attacker can spend, depending on the failure mode). `partial_sig_verify` is
exactly the function the aggregator needs.

Today an aggregator could only do this in Python (via the existing wrapper).
Commit `60ebb51` lets a Rust aggregator service do the same.

**Open question:** does BTX2 have / plan a Rust-side aggregator service?
The spec doesn't say. If aggregators stay Python-only, this consumer
collapses.

### 2.2 Independent auditor (post-hoc)

If a pool publishes its session transcript (aggnonce + pubnonces + partial
sigs) off-chain — e.g. to demonstrate to a third party that the order was
honestly multi-party — that auditor can verify every signer contributed
using the Rust port.

**Open question:** are pool transcripts ever made available to third
parties? The spec is silent. Real-world maker pools tend to keep this
opaque (it's competitive information).

### 2.3 Slashing or fraud-proof verifier (hypothetical)

If BTX2 ever introduces *slashing* — penalizing a pool member who submitted
an invalid partial sig — the on-chain slashing record would carry the
offending partial sig + session context, and the indexer would verify it
using `partial_sig_verify`.

**Open question:** does BTX2 want slashing? Today there's no slashing
mechanism mentioned anywhere in the spec. Adding one is a substantial
protocol design choice; it implies bonds, dispute windows, and a new
record type.

### 2.4 Setup-ceremony verifier

A multi-org pool's first state could include a ceremony record where each
org contributes a partial sig over a canonical "I authorize this pool"
message. The indexer verifies the ceremony before honoring the pool's
aggregated pubkey.

**Open question:** does BTX2 want multi-org pools at all? §5 currently
describes pools generically ("N participants") without distinguishing
single-org pools (the existing trust assumption, per the memory note:
*"BTX2 maker pools today have single-entity-holds-all-keys trust
assumption — pool_sign_demo is the CORRECT choice for that use case"*)
from multi-org pools.

### 2.5 Test / development tooling

Already used: `btx_musig2_protocol::tests::random_python_to_rust_partial_sigs_verify`
verifies Python-generated sessions in Rust. This is real but not a
*production* consumer.

---

## 3. Encoding decisions if any of 2.3 / 2.4 are adopted

These are real bytes-on-chain decisions, not aspirations.

### 3.1 Where does session state live?

Partial sigs are 32 bytes each. For a 5-of-5 pool ceremony, that's 160
bytes of partial sigs plus 330 bytes of pubnonces (66 × 5) plus 66 bytes
of aggnonce plus the canonical message. ~600 bytes minimum.

Options:
- **Full envelope.** Carry everything in a new record type. ~600+ bytes
  of overhead per ceremony / slashing event.
- **Commitment-only.** Carry a Merkle root of partial sigs in the envelope;
  the verifier asks for the preimages off-chain when needed. Cheap on-chain,
  but requires an off-chain availability assumption.
- **Hash-and-publish.** Envelope carries a hash of the session transcript;
  the indexer can only verify if someone publishes the preimages later.

### 3.2 What signs the wrapper record?

The aggregated pool pubkey signs everything else BTX2 publishes. If a
ceremony record is signed by the aggregated pool pubkey, you have a
chicken-and-egg problem (the ceremony establishes the pool; the pubkey
needs the pool to exist). Options:
- Ceremony record signed by a designated "founder" key, with the
  ceremony establishing the pool pubkey as a separate output of the
  ceremony.
- Ceremony record co-signed by every founding member's individual key
  (multi-sig script style, not MuSig2).
- Ceremony signed by the aggregated pubkey itself (i.e. the pool's first
  act is to ratify its own existence).

### 3.3 Indexer behaviour when verification fails

If a published ceremony or slashing record fails verification:
- **Strict mode.** Indexer rejects the entire record. The pool can't
  publish anything. Risk: a network-delayed publisher gets cut off.
- **Lenient mode.** Indexer logs the failure, keeps the record visible
  with a warning flag. Risk: invalid records pollute the view.
- **Two-tier.** Indexer accepts the record but tags it
  "verification_pending"; downstream queries can filter.

---

## 4. Honest open questions for you to decide

1. **Does BTX2 want multi-org maker pools?** Yes → 2.1, 2.2, 2.4 become
   real. No → the Rust port stays a Python-runtime-independence win for
   single-org pool aggregators and that's the whole value.

2. **Does BTX2 want slashing?** Yes → 2.3 becomes real, a new record
   type is needed, the encoding decisions in §3 must be made. No → skip.

3. **Where do pool aggregators run?** Python only → §2.1 consumer
   collapses (the wrapper covers it). Rust too → §2.1 is the primary
   consumer of `btx_musig2_protocol`. Either / unknown → keep the Rust
   port as optionality.

4. **Should I (this agent) draft any specific spec amendments?** This
   memo deliberately stops at "list options, name tradeoffs" because the
   above three questions are yours to answer. I can:
   - Wait for your call on 1/2/3, then draft the specific §5 / new-§5.x /
     new-§5.y amendments that follow.
   - Update §9.2 + §10 + §12 with a small note that the Rust
     verification port now exists, without taking a position on
     consumers. This is a low-risk truthful update to the spec doc and
     I would do it without further input.
   - Stop and let you take it from here.

---

## 5. What this memo DOES NOT do

- Pick the right consumer.
- Define new record types or encoding.
- Modify the canonical `BTX-v2-spec-2026-06-02.md`.
- Claim any of these consumers is preferable to the existing single-org
  trust model.

It's a survey. The decisions are protocol-design choices that belong to
you.

---

## 6. Where the verification port has *already* paid off

Even without any of §2.1-2.5 being adopted, two real wins already exist:

- **Three-way cross-validation of BTX's crypto stack:** BIP-327
  reference.py (Jonas Nick), the Python wrapper, and the Rust port all
  agree byte-for-byte on the canonical vectors and on random Python-
  generated sessions. This is *implementation-independence evidence* of
  the same kind that scout 18-22 built for BIP-340 / BIP-341.
- **Test surface for the Python wrapper:** any future Python-side
  regression would now be caught by the brk-btx Rust tests automatically
  when the random golden is regenerated.

These are real but they're test-infrastructure wins, not production-consumer
wins.

---

*Authored 2026-06-04, post-commit `672a5c3` on brk-btx and `0f60ddd` on
bitcoin-terminal-exchange. Cross-links: `[[project-brk-btx-musig2-protocol-2026-06-04]]`,
`BTX-v2-spec-2026-06-02.md §5 + §9.2 + §10 + §12`.*
