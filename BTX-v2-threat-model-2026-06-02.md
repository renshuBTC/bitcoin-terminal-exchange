# BTX2 — threat model (draft 2026-06-02)

*Companion to `BTX-v2-spec-2026-06-02.md`. Spec §9 sketched the security
considerations; this document expands them into a structured threat model
implementers and reviewers can work against. Same draft status as the
spec — load-bearing only after a BTX2 mainnet B4-equivalent broadcast
confirms the assumptions hold under production policy.*

## 1. Scope

In scope:

- The cryptographic primitives in `btx_halfagg.py`, `btx_adaptor.py`,
  `btx_musig2.py` and their Rust ports.
- The BTX2 envelope and three record types (SINGLE_ORDER, BATCH_ANNOUNCE,
  CONDITIONAL_ORDER).
- The indexer state machine that ingests BTX2 envelopes.
- The maker-pool setup workflow for MuSig2 KeyAgg.
- The oracle-attested settlement workflow for CONDITIONAL_ORDERs.

Out of scope (covered by separate threat models):

- BTX1 spot trading mechanics — see `BTX-threat-model.md` /
  `BTX-mainnet-hardening.md`.
- Bitcoin consensus failure modes.
- Operational security of maker key management (HSM, cold-warm-hot
  rails) — generic Bitcoin practice applies.

## 2. Threat actors

| Actor | Capability assumed |
|---|---|
| **Passive observer** | Reads the chain and any public BTX2 indexer APIs. No private channels, no key material. |
| **Active taker** | Like passive observer + can publish on-chain transactions to fill or attempt to fill orders. |
| **Rogue maker** | Like active taker + controls the secret key for one or more maker pubkeys. |
| **Rogue pool member** | Like rogue maker, but is one of N participants in a MuSig2 maker pool. |
| **Compromised oracle** | Controls the secret `t` such that `T = t·G` for a conditional order's encryption point — i.e., can either reveal `t` truthfully, lie about the outcome, or refuse to attest. |
| **Network-level adversary** | Can suppress / delay / replay transactions and indexer responses. Equivalent to a network-level mempool monitor. |
| **Indexer operator** | Runs the indexer. May be honest, lazy, or malicious. Indexer is *not* a trusted oracle for prices but is a trusted oracle for "what's on chain." |

## 3. Adaptor signature threats

### 3.1 ECDH leakage from adaptor pre-signing

**Threat:** Given the signing pubkey `P = d·G`, the encryption pubkey
`T = t·G`, and the adaptor signature, any observer can compute the
shared DH point `T^d = P^t`. This is the documented "warning" the
`secp256k1-zkp/src/modules/ecdsa_adaptor` C header ships with.

**Affected protocols:** Diffie-Hellman key exchange, ElGamal encryption,
ECIES, Lightning's Noise handshake — anything that derives a shared
secret from `d` and an external counterparty pubkey via CDH.

**Impact:** If a maker reuses key `d` for both BTX2 adaptor sigs AND any
of the above protocols, an adaptor sig observer who is *also* the
counterparty in one of the above protocols can correlate identities or
decrypt messages.

**Mitigation (implemented):** BTX2 makers SHOULD generate fresh keys
per offer. The existing BTX1 maker tooling already creates fresh
keypairs per signing session, so the practice carries over. Implementer
requirement: the BTX2 CLI / SDK API surface for adaptor signing MUST
document this and SHOULD enforce it (refuse to sign with a key that has
already been used in a non-adaptor context).

**Mitigation (auditable):** The indexer SHOULD log any case where the
same maker_pubkey appears in both a CONDITIONAL_ORDER and a SINGLE_ORDER
within the same chain window. This is a heuristic signal of key reuse
and surfaces in the indexer's threat-monitoring output.

**Residual risk:** A maker who deliberately reuses a key (e.g., for
brand-recognition purposes) has knowingly accepted the CDH leakage. No
protocol-level defense.

### 3.2 Oracle non-attestation (liveness failure)

**Threat:** A maker publishes a CONDITIONAL_ORDER locked to oracle
encryption point `T`. The expected outcome materializes in the world,
but the oracle refuses to attest (down, censored, malicious).

**Impact:** The conditional order is unfillable. The maker's offer UTXO
remains locked. No settlement, no taker pay-in (per construction, taker
funds only flow on adaptor decryption).

**Mitigation:** Each CONDITIONAL_ORDER MUST carry an `expiry` block
height in its body (already present in §3.4 OrderBody). When the
indexer observes the offer UTXO's containing block exceeds `expiry`,
the order transitions to EXPIRED and the maker can recover the offer
UTXO via a normal cancel path.

**Residual risk:** Between announcement and expiry, the maker's offer
UTXO is encumbered. Capital efficiency cost.

### 3.3 Oracle dishonest attestation

**Threat:** Oracle attests outcome Y even though the real-world outcome
was X. The conditional order settles based on the false attestation.

**Impact:** Maker or taker (depending on direction) loses funds vs the
true outcome. Same as classical DLC oracle dishonesty.

**Mitigation (cryptographic):** None at the BTX2 layer. Oracle
honesty is a trust assumption.

**Mitigation (selection):** Use multi-oracle setups where multiple
independent oracles attest, and the conditional order settles only on
threshold attestation. This requires either (a) multiple separate
CONDITIONAL_ORDERs locked to different oracles (each maker waits for
the right outcome to materialize before publishing the matching
order), or (b) a future BTX2 extension supporting t-of-N oracle
constructions via FROST. Currently FROST is not in `secp256k1-zkp`;
this extension is forward-looking.

### 3.4 Decryption race / front-running

**Threat:** Oracle publishes `t`. Multiple takers observe `t` and race
to decrypt + settle. The taker who broadcasts first wins the offer.

**Impact:** Fair-but-arbitrary winner selection. Not a security
violation; an MEV-like dynamic.

**Mitigation:** Use the existing BTX addressed-mode pattern (per
BTX-threat-model.md) — pre-commit the taker via an addressed offer
that only one specific taker can complete. The conditional order
becomes "taker X can fill this if and when the oracle attests Y."
Combines the two existing snipe-resistance mechanisms cleanly.

### 3.5 R̂ collision (cryptographic)

**Threat:** Adversary finds two distinct (P, T, m) tuples that produce
the same R̂. If they could also produce two valid pre-signatures over
the same R̂ but for different (T, m), they could extract `d`.

**Mitigation:** Standard BIP340 nonce derivation prevents nonce
collisions across different (P, m) for a given key. The R̂ here is
deterministically derived from P, T, m via tagged hash; collision
resistance comes from SHA256. No additional defense needed beyond what
BIP340 already provides.

**Residual risk:** Negligible (2^128 work).

## 4. MuSig2 maker-pool threats

### 4.1 Round-1 nonce reuse (CRITICAL)

**Threat:** A signer reuses their round-1 nonce `(R1_i, R2_i)` across
two signing sessions. The two partial signatures share the same nonce
contribution, and the signer's secret key share is extractable from
two linear equations.

**Impact:** Complete loss of the contributing signer's share. In MuSig2
n-of-n, losing one share doesn't immediately give the attacker the
ability to forge — they still need the other n-1 shares — but if the
attacker is one of the other signers, this lets them forge unilaterally.

**Mitigation:** BIP327's nonce protocol is designed around the
assumption that round-1 nonces are NEVER reused. Implementations MUST:

1. Persist round-1 secret nonces only until round-2 partial signature
   emission, then zero them out.
2. Refuse to start a new signing session until the previous round-2 is
   complete (or the prior session is explicitly abandoned with key
   rotation).
3. NEVER export round-1 nonces.

The `pool_sign_demo()` Python function (`btx_musig2.py`) deliberately
sidesteps round-1 nonces by using a trusted-aggregator path. It is
labeled research-only for exactly this reason. **Production
maker-pool deployment MUST use a vetted MuSig2 implementation** — the
C reference in `secp256k1-zkp` is the gold standard.

### 4.2 Partial signature leakage

**Threat:** A signer leaks their round-2 partial signature before the
session aggregator combines all partials. Or: the aggregator publishes
a partial signature alongside the aggregate.

**Impact:** Combined with the public coefficient `a_i`, the partial
signature reveals `k1_i + b·k2_i + e·a_i·d_i`. With the public R1_i
and R2_i nonces, the signer's `d_i` is extractable.

**Mitigation:** Partial signatures MUST be treated as session secrets
until the aggregator emits the combined signature. Any implementation
that exposes partial sigs through a public API is broken.

### 4.3 Rogue-key attack (mitigated by KeyAgg)

**Threat:** A malicious signer claims pubkey `P_2 = X - P_1` where `X`
is the attacker's chosen point. Without the rogue-key defense, the
aggregated key would just be `X` and the attacker could sign alone.

**Mitigation (implemented):** BIP327 KeyAgg's "second key" rule and
coefficient hash defeat this. The first pubkey distinct from `pk[0]`
gets coefficient 1; all others get hash-derived coefficients that
commit to the full pubkey set. An attacker cannot cancel another
signer's contribution because the coefficient depends on `L` which
depends on all pubkeys including the attacker's.

The Python `btx_musig2.py` test suite includes an empirical check of
this property (T6 in the selftest).

**Residual risk:** None known under BIP327's analyzed model.

### 4.4 Aggregator-as-honest-but-curious

**Threat:** In production, a maker pool delegates aggregation to one
party who knows none of the secret keys but learns: (a) the round-1
nonces from all signers, (b) the round-2 partials, (c) what was
signed.

**Impact:** The aggregator can reconstruct the message-signing history
of the pool. Privacy loss, not financial loss.

**Mitigation:** Rotate the aggregator role between sessions. Each pool
member takes a turn. No single party has the full history.

### 4.5 Coalition extraction (n-1 collusion)

**Threat:** n-1 pool members collude to learn the n-th member's secret
key.

**Mitigation:** MuSig2 is n-of-n. By design, n-1 cannot sign without
the n-th. They also cannot extract the n-th member's secret from
public observation of correctly-executed signing sessions.

**Residual risk:** If the n-th member's nonce is leaked through a side
channel (timing, memory dump), the n-1 colluders can complete the
attack. Standard secret-handling discipline applies.

## 5. Half-aggregate signature threats

### 5.1 Batch atomicity bypass

**Threat:** Adversary attempts to construct a BATCH_ANNOUNCE such that
N-1 of the N maker signatures are valid and the N-th is forged. Since
the indexer verifies one aggregate covering all N (P_i, m_i), partial
forgery would break atomicity if it verified.

**Mitigation:** The half-aggregate verification equation
`s·G == Σ z_i (R_i + e_i·P_i)` is satisfied only when all N
contributions are individually valid Schnorr signatures (the z_i
coefficients are non-trivial and the e_i depend on P_i and m_i).
Forging any one term would require finding either a Schnorr signature
under an unknown private key OR a collision in the tagged hash family
— both are infeasible.

**Empirical evidence:** The Python and Rust test suites both verify
that tampering any byte of the aggregate or any (R, P, m) triple
breaks verification.

**Residual risk:** None known under standard ROM assumptions.

### 5.2 Mixed-signature batches

**Threat:** A maker pool might want to mix Schnorr (BIP340) and ECDSA
maker signatures in one BATCH_ANNOUNCE for backward compatibility.

**Mitigation:** The spec §3.2 declares BATCH_ANNOUNCE is
Schnorr-only. Implementations MUST refuse to aggregate or verify a
batch where any signature is ECDSA. Mixing the two breaks the
half-aggregate verification equation (different challenge function,
different sighash semantics).

### 5.3 Replay across (P, m) pairs

**Threat:** An aggregate is published in one envelope. An adversary
copies the aggregate and embeds it in a different envelope with a
different ordering of (P_i, m_i).

**Mitigation:** The z_i coefficients depend on the running prefix
`R_0||P_0||m_0||...||R_i||P_i||m_i`. Reordering the inputs changes the
z_i values, which changes the verification equation. A copied
aggregate will not verify under a different ordering.

**Residual risk:** None.

## 6. Indexer state-machine threats

### 6.1 CONDITIONAL_ORDER false settlement

**Threat:** Adversary publishes a transaction that spends a
CONDITIONAL_ORDER's offer UTXO with some valid Schnorr signature
(perhaps from an unrelated key), then claims the order is FILLED and
the secret `t` should be derived.

**Mitigation:** The indexer MUST verify:

1. The settlement transaction's signature is a Schnorr sig over the
   same sighash `TaggedHash("BTX2/order/sighash", BODY)` that the
   adaptor pre-sig was bound to.
2. The signature is from the same maker_pubkey extracted from BODY.
3. The recovered `t` from `recover(adaptor_sig, settlement_sig)`
   satisfies `t·G == T` (the announced encryption point).

If any check fails, the order does NOT transition to FILLED. It stays
CONDITIONAL until a valid settlement or expiry.

### 6.2 Reorg-induced state divergence

**Threat:** A CONDITIONAL_ORDER announce confirms in block H. A
settlement tx confirms in block H+k. A reorg removes block H+k. The
indexer's CONDITIONAL_ORDER state machine must roll back the FILLED
transition.

**Mitigation:** The existing BTX1 reorg-rollback logic in `brk-btx`
(`crates/brk_indexer/src/btx.rs::rollback_plan`) extends to BTX2 by
adding the new CONDITIONAL state transitions to the rollback table.
The state machine is deterministic given the chain; reorg correctness
is a re-run-from-the-fork-point property.

### 6.3 Indexer ignoring records

**Threat:** Indexer skips a record type it doesn't know how to verify
(spec §2 says this is allowed for forward compatibility) — but a
malicious envelope encodes a SINGLE_ORDER as an unknown type to
suppress it from a target indexer's view.

**Mitigation:** Forward-compatibility skip applies only to TYPE in
the reserved range (`0x04 — 0x7F`). Indexers MUST hard-reject
envelopes containing types in `0x01 — 0x03` that they cannot parse;
they cannot silently drop a SINGLE_ORDER. Implementers should
unit-test "known type fails to parse" → "envelope rejected, not
skipped."

## 7. Network-level threats

### 7.1 Settlement-tx censorship

**Threat:** A miner or mempool censor delays or blocks a
CONDITIONAL_ORDER's settlement tx, preventing the order from
transitioning to FILLED before expiry.

**Impact:** The conditional order expires unfilled. Taker funds are
unaffected (they only flow on settlement); maker's offer UTXO is
unlocked at expiry.

**Mitigation:** Use multiple broadcast paths. Maintain a higher fee
ceiling for time-sensitive settlement.

### 7.2 Encryption-point predictability

**Threat:** Adversary predicts the encryption point `T` an oracle
will use BEFORE the oracle publishes it. The adversary can pre-front-
run conditional orders by setting up a parallel infrastructure.

**Mitigation:** Oracles' encryption points should be derived from
deterministic-but-hard-to-predict-in-advance sources (signed event
predictions, hash chains rooted at non-public events). Application-
specific; BTX2 doesn't dictate oracle design.

## 8. What the spec deliberately does NOT defend

- **Honest oracle.** A dishonest oracle is out of scope. BTX2
  delegates oracle-honesty assumption to the application designing the
  conditional order.
- **Anonymity of maker pools.** A maker pool's existence is private at
  the chain layer (KeyAgg produces a vanilla pubkey), but membership
  is private only at the pool's discretion. If members leak, BTX2
  cryptographic primitives cannot hide them.
- **Demand and liquidity.** No primitive here addresses "will anyone
  fill this order." Pure protocol layer.
- **Smart-contract-style escalation.** BTX2 has no built-in dispute
  resolution. Conditional orders settle or expire; there is no
  arbitration. Applications wanting this should layer it above BTX2.

## 9. Implementer checklist

For anyone building on BTX2:

- [ ] Generate fresh maker keys per offer.
- [ ] When implementing CONDITIONAL_ORDER signing, document the
      ECDH-leakage warning prominently in the API surface.
- [ ] Production MuSig2 signing uses a vetted library, NOT the
      pure-Python or pure-Rust reference here.
- [ ] Indexer rejects unknown TYPE values in `0x01 — 0x03`; only
      reserved `0x04 — 0x7F` are silently skipped.
- [ ] Conditional-order settlement verification checks:
      same sighash, same maker_pubkey, `t·G == T`.
- [ ] Reorg rollback handles CONDITIONAL ↔ FILLED transitions.
- [ ] BATCH_ANNOUNCE is Schnorr-only; no mixed ECDSA fallback.
- [ ] Maker pool aggregator rotates between sessions.
- [ ] Round-1 MuSig2 nonces are persisted only until round-2 emission.

## 10. Open security questions

- **Cross-chain unlock side-channels.** When a CONDITIONAL_ORDER
  settles, the recovered `t` is publicly observable. If the same `t`
  is reused as the lock on an unrelated cross-chain swap, settling
  BTX2 also settles the other chain. This is the intended feature for
  cross-chain atomic swaps but is a footgun if the encryption point's
  reuse isn't explicit. Recommendation: implementations distinguish
  between single-chain conditional orders (where `T` should be a
  fresh per-order point) and cross-chain swap conditional orders
  (where `T` is intentionally shared).
- **MEV around oracle attestation.** When `t` becomes public, the
  decryption-race in §3.4 happens. MEV opportunities exist for
  block-producers to reorder. Worth a separate study.
- **Indexer divergence on partial reorgs.** What if two indexers
  observe different settlement transactions during a reorg window?
  The deterministic chain-rooted state machine should converge once
  reorgs settle. Worth empirical testing during the BTX2 mainnet
  B4-equivalent broadcast.

## 11. Status

- Doc: draft (2026-06-02), this file.
- Implementation status: §3 + §4 + §5 primitives have Python + Rust
  references with golden cross-tests at commits `cdb6ec2` (brk-btx) /
  `c200f08` (bitcoin-terminal-exchange).
- Empirical validation: pending BTX2 mainnet B4-equivalent broadcast.

---

*This document deepens `BTX-v2-spec-2026-06-02.md` §9. Both should be
read together. Reviewers are encouraged to PR back with additional
threats, mitigations, or empirical findings.*
