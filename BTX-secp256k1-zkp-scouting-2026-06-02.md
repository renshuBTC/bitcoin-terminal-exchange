# Scouting report — Blockstream's `secp256k1-zkp` for BTX

*Deep-dive on `BlockstreamResearch/secp256k1-zkp` at commit `8099999` (2026-06-02),
focused on whether any of its primitives can move BTX forward beyond the current
spot-trading single-maker-single-taker design.*

## Why this repo

`secp256k1-zkp` is the Blockstream fork of the canonical libsecp256k1 with
"advanced and experimental" features that haven't (yet) made it upstream. The
maintainers are exactly the people you'd pick if you wanted cryptographer-grade
reference implementations of Bitcoin-adjacent constructions: **Pieter Wuille
(sipa)**, **Jonas Nick (jonasnick)**, **Tim Ruffing (real-or-random)**, **Andrew
Poelstra (apoelstra)**. The MuSig2 module here is by the BIP327 co-authors
themselves.

Three modules stood out as having concrete, near-term BTX-relevant value:

1. `schnorrsig_halfagg` — Schnorr signature half-aggregation
2. `musig` — BIP327 MuSig2 n-of-n
3. `ecdsa_adaptor` — adaptor signatures (the cryptographic primitive behind DLCs)

A handful of others (`bppp`, `rangeproof`, `surjection`, `ecdsa_s2c`) are
strategically interesting but more distant.

## 1. Schnorr half-aggregation (`schnorrsig_halfagg`)

### What it does

Takes N independent Schnorr signatures, each over a different (message, key)
pair, and produces one "half-aggregate" signature of size **32(N+1) bytes**
instead of 64N bytes. The aggregation is non-interactive: any third party
holding the N original signatures can produce the aggregate. Verification
needs the N (pubkey, message, partial-aggregate) tuples.

Empirical savings table from the API math:

| N | N×64B independent | 32(N+1) half-agg | savings |
|---:|---:|---:|---:|
|  1 |   64 |   64 |  0.0% |
|  2 |  128 |   96 | 25.0% |
|  3 |  192 |  128 | 33.3% |
|  5 |  320 |  192 | 40.0% |
| 10 |  640 |  352 | 45.0% |
| 20 | 1280 |  672 | 47.5% |
| 50 | 3200 | 1632 | 49.0% |
|100 | 6400 | 3232 | 49.5% |

The asymptote is 50%: half the bits go away.

### Where this fits in BTX

Where BTX carries multiple maker signatures, the artifact size drops by ~50%:

- **Batch-fill artifact compression.** A BTX1 envelope that announces N maker
  offers at once (e.g., one entity publishing many orders in one tx) currently
  embeds N independent maker sigs. Each is currently ~71B (ECDSA
  DER + sighash). With Schnorr makers + half-agg, that becomes 32(N+1) bytes.
  For N=10 offers in one envelope: ~710B → ~352B, a ~50% saving on
  signature bytes.

- **Indexer-side aggregate event hashes.** The cumulative event hash already
  half-aggregates conceptually (commits to a stream of events). The same
  primitive could be applied to the maker-sig stream within the indexer for
  cheaper checkpoint signatures.

### Where it does NOT help

- **Consensus-level signatures inside taker fill txs.** Bitcoin nodes verify
  signatures one at a time at consensus; half-agg is not a consensus rule. So
  the witness of an on-chain batch fill **cannot** carry a half-aggregate sig
  — each maker's sig is still verified individually by Bitcoin Core.
- **Single-maker single-offer announces.** At N=1 the savings are zero.

### Concrete cost

- BTX would have to migrate maker signatures from ECDSA P2WPKH (`0x83`
  sighash) to Schnorr P2TR with the equivalent BIP341 sighash. The BIP341
  Schnorr semantics for `SIGHASH_SINGLE|ANYONECANPAY` are well-defined and
  compatible with the existing atomic-swap construction.
- New code: a `btx_halfagg.py` reference + a `halfagg.rs` indexer-side
  parser. Both can lean on the C reference for byte-format.
- Net effort: medium. The migration touches `btx_wallet.py:cmd_maker_sign`,
  the artifact format version (BTX1 → BTX2?), and the indexer's signature
  verifier.

**Verdict: tactical win, ~50% byte savings on multi-maker envelopes. Worth
prototyping AFTER the artifact-format-v2 freeze, not before.**

## 2. MuSig2 (`musig`, BIP327)

### What it does

N parties pre-aggregate their public keys into a single x-only pubkey, then
cooperate (two rounds of communication) to produce a single 64-byte BIP340
Schnorr signature over that aggregated key. The on-chain footprint is
indistinguishable from a single signer.

API surface (from `include/secp256k1_musig.h`):

- `pubkey_agg` — aggregate N pubkeys into one
- `pubkey_xonly_tweak_add` — apply Taproot tweaks to the aggregate
- `nonce_gen` / `nonce_agg` — round 1
- `partial_sign` / `partial_sig_agg` — round 2

The example at `examples/musig.c` walks through a clean 3-of-3 flow.

### Where this fits in BTX

**Maker pools.** A consortium of N makers pre-aggregates their keys into a
single "pool pubkey" that publishes offers via the BTX1 carrier. Each offer
requires all N (or some pre-agreed subset using key-tweak techniques) to
co-sign before the artifact gets broadcast. On-chain the offer looks exactly
like a single-maker offer — same 64-byte sig, same artifact structure, same
witness size. Off-chain, the maker pool gets:

- **Threshold-style custody for offer-side BTC.** No single member can move
  the offer UTXO without the others' partial sigs.
- **Maker rotation without on-chain footprint changes.** Pool members can
  rotate their keys via group key refresh; the aggregated key stays stable
  for the duration of the offer.
- **A primitive for "institutional maker" use cases** — market makers who
  want to share inventory + risk without revealing identity per offer.

### MuSig2's structural limit for BTX

MuSig2 is strictly **n-of-n**, not t-of-n threshold. If you want "3-of-5 of
this pool can sign an offer", MuSig2 alone is insufficient — you need FROST
(RFC 9591), which is on the BTX watchlist but not in this repo.

### Concrete cost

- New maker-side protocol: two rounds of communication between N makers
  before each offer is published.
- No on-chain footprint change. Existing indexer / artifact parser /
  consensus verification path is **unchanged** because the signature is a
  vanilla BIP340 Schnorr.
- Reference impl is C; Python and Rust ports are widely available
  (`bitcoinops/musig2` Python reference, `rust-secp256k1` Rust bindings).

**Verdict: strategic for institutional makers. Zero protocol change, only
maker-side coordination. Build a separate `btx_pool_maker.py` reference;
no impact on the core BTX1 format.**

## 3. ECDSA adaptor signatures (`ecdsa_adaptor`) — the big one

### What it does

Adaptor signatures are a cryptographic primitive that lets you create a
**verifiably-encrypted signature**: a "pre-signature" that's locked to a
secret that only gets revealed when a specific event happens (an oracle
attests, a counterparty signs a particular message, a hashlock unlocks).

The API has four operations:

- `encrypt(seckey, msg, encryption_key)` → 162-byte adaptor signature
- `verify(adaptor_sig, signer_pubkey, msg, encryption_key)` → checks the
  adaptor sig is correctly formed without revealing the secret
- `decrypt(adaptor_sig, secret)` → produces a normal ECDSA signature once
  the secret is revealed
- `recover(adaptor_sig, signed_sig, encryption_key)` → goes the other way:
  given the adaptor sig + the eventually-decrypted real signature, recovers
  the secret (useful for cross-chain atomic swaps where revealing the sig
  also reveals the secret)

### Where this fits in BTX — this is the new market

Adaptor signatures open BTX from **spot trading** to **conditional /
oracle-attested trading**. Three concrete order types become possible:

**3a. Oracle-conditional orders (DLC-style).** A maker publishes an offer:
"I'll sell 100k sats of rune-X if oracle `O` signs `Y` by block height `H`".
Mechanism: maker signs the swap with an adaptor sig where the encryption key
is the oracle's expected attestation point. Taker pays the offer with normal
funds. When the oracle publishes its signature, anyone (including the taker)
can `decrypt` the adaptor sig to complete the swap. If the oracle says no
or fails to attest, the taker can recover funds via timelocked refund path.

This is exactly the DLC construction, but using BTX as the order-discovery
layer instead of off-chain oracle channels.

**3b. Cross-chain atomic swap building block.** Maker publishes an offer in
BTX-style. Counterparty wants to pay in Lightning. The Lightning payment is
made conditional on a hash preimage that's also the encryption secret of the
adaptor sig. When the Lightning payment settles, the preimage propagates,
the adaptor sig decrypts, the on-chain swap settles. Same primitive as
Lightning's point-time-lock-contracts (PTLCs).

**3c. Order privacy.** A maker can pre-encrypt their order signature to a
key only the taker can derive (e.g., after sending a fee deposit). The
adaptor sig is broadcast; nobody else can decrypt to spend the offer until
they've satisfied the maker's encryption condition. This is a strict
generalization of BTX's existing "addressed mode" snipe-resistance.

### The warning the module ships with

The header is very explicit:

> the adaptor signature leaks the Elliptic-curve Diffie–Hellman (ECDH)
> key between the signing key and the encryption key.

For BTX this matters if a maker were to reuse the same signing key for both
adaptor-sig orders AND DH-based protocols (e.g., Lightning gossip, ECIES
encryption). The mitigation is the standard one: derive a fresh key per
order purpose. BTX already creates a fresh keypair per offer signing
session, so the exposure is minimal — but worth calling out in any future
threat model.

### Concrete cost

- Substantial new primitive on the maker + indexer side. The artifact
  format would need a new "conditional offer" sub-type carrying:
  the adaptor sig (162B vs the current ~71B), the encryption pubkey
  (33B), the oracle commitment (varies), and the condition expression.
- Net artifact size: roughly doubles, ~400-500 bytes. Still well within
  v30 datacarriersize + tapscript pushdata limits.
- New code: `btx_adaptor.py` (encrypt/verify/decrypt wrappers), oracle
  registry, conditional-order indexer state, timelock-refund paths.
- Net effort: high. This is a real product surface, not a refactor.

**Verdict: highest strategic value. Adaptor sigs would let BTX claim a market
category nobody else currently has — fully on-chain conditional orders,
no Lightning, no DLC sidechain, no L2. Direct competition would be
Discreet Log Contracts (DLCs), but DLCs require an off-chain channel; BTX
+ adaptor sigs would land them entirely on-chain.**

## Recommendation

If BTX picks ONE thing from this repo to integrate in the next major
version, the order is:

1. **Adaptor signatures (3)** — opens a new product category. Highest
   strategic value but highest build cost.
2. **MuSig2 (2)** — institutional-maker enabler. Zero on-chain change.
   Medium build cost. Done as a maker-side library, no protocol change.
3. **Half-aggregation (1)** — pure byte-efficiency win on multi-maker
   envelopes. Marginal in the v1 single-maker mainline. Tactical.

The cleanest sequence: ship MuSig2 first as a maker-side toolkit (no
artifact change, easy demo), use that to build out maker-pool tooling,
then design the BTX2 artifact format that adds adaptor-sig conditional
orders. Half-agg drops in after BTX2 lands.

## Worth noting

- The adaptor-sig module is the **only** one of these that lives in the
  Blockstream fork and is NOT in upstream `bitcoin-core/secp256k1`. If
  BTX bundles secp256k1, it'd have to bundle the zkp fork specifically.
  Lightning implementations already do this (`lnd`, `ldk`).
- The MuSig2 implementation in this fork **matches** upstream as of late
  2024. The adaptor-sig support is what makes the zkp fork still load-
  bearing for projects that need both.
- Active maintenance: latest merge commit visible at `8099999` is a
  recent sync-upstream-simplify — this is not abandonware.

## What's NOT immediately useful

- `bppp` (Bulletproofs++) — interesting for confidential range proofs but
  requires Confidential Transactions infrastructure that Bitcoin mainnet
  doesn't have. Applies to Liquid, not BTX-on-mainnet.
- `surjection` — same concern; assumes Confidential Assets.
- `rangeproof` — same.
- `ecdsa_s2c` (sign-to-contract) — interesting for covert commitments
  (BTX1 magic could be hidden inside an apparently-random signature). Real
  privacy/un-flaggability potential, but requires careful threat modeling
  to ensure the hidden commitment is also verifiable by the BTX indexer.
- `whitelist`, `generator`, `ellswift` — niche.

## Followups if BTX wants to act on this

| Action | Effort |
|---|---|
| Prototype MuSig2 pool-maker tool in Python using existing reference | ~1 week |
| Spec out the BTX2 artifact format with conditional-order sub-types | ~2 weeks |
| Build a regtest DLC-style demo: oracle attests outcome → adaptor decrypt → swap settles | ~1 month |
| Audit BTX1 → BTX2 format migration path with backward-compatibility | ~1 week |
| Build half-agg into the BTX2 batch-announce path | ~3 days (after BTX2 lands) |

Source repo: <https://github.com/BlockstreamResearch/secp256k1-zkp>
Examined commit: `8099999` (master, 2026-06-02).
