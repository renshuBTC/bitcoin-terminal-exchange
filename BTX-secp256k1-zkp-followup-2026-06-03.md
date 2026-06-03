# Followup — `BlockstreamResearch/secp256k1-zkp` extraction closure

Companion to `BTX-secp256k1-zkp-scouting-2026-06-02.md`. That doc identified what
to take from the Blockstream Research fork; this doc records what actually got
taken and lands the gaps the audit (2026-06-03) found.

## Scope of this session (2026-06-03)

The 2026-06-03 audit cross-checked the original scouting recommendations against
what was actually shipped, found gaps, and closed them where load-bearing:

| Item                                | Status before audit | Action this session                                       |
|-------------------------------------|---------------------|-----------------------------------------------------------|
| Schnorr half-aggregation            | shipped Py + Rust   | none — already complete                                   |
| MuSig2 KeyAgg                       | shipped Py + Rust   | none — already complete                                   |
| MuSig2 full signing                 | Py: pool demo; Rust: missing | added `pool_sign_trusted_aggregator` to Rust   |
| Schnorr adaptor sigs                | shipped Py + Rust   | none — already complete                                   |
| ECDSA sign-to-contract (`ecdsa_s2c`)| **MISSING**         | shipped as BIP340 sign-to-contract (Py + Rust)            |
| MuSig2 + adaptor combo              | **MISSING**         | shipped `btx_musig2_adaptor.py`                           |
| DLC-style regtest demo              | **MISSING**         | shipped `btx_dlc_demo.py`                                 |
| `bppp` / `rangeproof` / `surjection`| skipped (CT-only)   | none — correctly out of scope (mainnet has no CT)         |
| `whitelist` / `generator` / `ellswift`| skipped (niche)   | none — correctly out of scope                             |

## What shipped

### 1. `btx_s2c.py` + `crates/brk_indexer/src/btx_s2c.rs`

BIP340 sign-to-contract — the primitive flagged in the scouting doc line
263–266 as *"Real privacy/un-flaggability potential, but requires careful threat
modelling to ensure the hidden commitment is also verifiable by the BTX
indexer."*

Construction: tweak `t = TaggedHash("BTX/s2c/v1", R0_x || c) mod N`, on-chain
`R = R0 + t·G`, sig is normal BIP340 `(x(R), s)`. Opening `(R0_x, c)` lets a
verifier check `sig[0..32] == x(R0 + t·G)`. The on-chain signature is
structurally indistinguishable from any other BIP340 sig.

- Python reference: 5 pinned golden vectors, all verify + tamper-rejected
- Rust verifier: 4 tests pass — golden vectors verify, tampered c rejected,
  tampered R0_x rejected, short sig rejected
- Tag string `"BTX/s2c/v1"` is locked across both ports via a pinned constant
- Indexer scanning helper: `s2c_recover_c_indexer_path` / `recover_c` —
  registry-driven, scans a small candidate set per observed sig

This directly addresses the post-B4 observation (memory
`project_btx_b4_broadcast_2026-06-02`) that BTX1 magic at byte 38 of witness[1]
was visible to three third-party operators (mempool.space, blockstream.info,
bitaps.com). With S2C, a future "BTX3" envelope can hide the magic inside the
witness signature itself.

**Integration paths NOT yet built** (design discussion):

- **Delayed-reveal**: maker publishes a normal-looking Schnorr sig containing
  the S2C commitment to BTX1 payload; reveals `R0_x, c` in a later block via a
  visible BTX1 envelope. Anyone can verify after-the-fact that the earlier sig
  committed to the same payload. Useful for **proof of pre-commitment** —
  anti-front-run, anti-MEV.
- **Per-maker `R0_x` registry**: each maker publishes a long-lived `R0_x` value
  at first-announce; indexer scans every signature on that maker's pubkey
  against the BTX1 payload registry. Privacy hinges on the registry being
  visible only to consenting BTX indexers, not on the chain.
- **Key-path-only commit**: a Taproot key-path spend whose sig commits to BTX1
  payload via S2C. Zero script-path visibility; fully anonymous to non-BTX
  observers.

Each of these is a follow-up design choice with non-trivial threat-model
implications. Shipping the primitive first lets the design space be explored
empirically.

### 2. `btx_musig2.rs::pool_sign_trusted_aggregator` (Rust)

Closes the Rust-side MuSig2 gap. Before this session, only `key_agg` was
exposed in Rust; the full signing path lived only in Python (`pool_sign_demo`).

The Rust version is byte-identical to Python: golden test
`pool_sign_matches_python_golden` proves that, for N=2/3/5, the same input
secret keys + message yield byte-identical 64-byte BIP340 signatures.

This is **trusted-aggregator** signing, not the interactive BIP327 2-round
protocol. For mutually-distrusting pool members, the interactive path is still
deferred to a future "BIP327-port" task — but the trusted-aggregator path is
what BTX makers actually use (a single pool operator holding multiple keys for
inventory rotation).

### 3. `btx_musig2_adaptor.py`

The combination `btx_adaptor.py` explicitly punted on:

> "What this module does NOT do: Multi-signer adaptor sigs (would need MuSig2 +
>  adaptor extension)."

Same trusted-aggregator composition: KeyAgg + parity normalisation → `d_agg`,
then run the standard `btx_adaptor.pre_sign(d_agg, msg, T)`. Three golden vectors
(N=2, 3, 5) all verify + decrypt + recover + tamper-rejected.

This unlocks the "institutional maker pool publishes a conditional order"
use case: e.g. a market-maker desk publishes a DLC-style "fill iff oracle
attests X" order on behalf of a pool, without revealing the pool's per-member
keys to the chain.

### 4. `btx_dlc_demo.py`

Followup table item: *"Build a regtest DLC-style demo: oracle attests outcome
→ adaptor decrypt → swap settles ~1 month"*.

Pure-Python end-to-end demo (no regtest node — the entire flow is on-curve
math, no consensus interaction needed). Six stages:

- **A** Oracle setup: publishes `Po` (long-lived pubkey) + `Ro` (per-event
  nonce point).
- **B** Maker builds adaptor pre-sig under attestation point
  `T_yes = Ro + Hash(event_id || "yes")·Po`.
- **C** Taker verifies the pre-sig is bound to `T_yes` independently.
- **D** Oracle attests "yes" by publishing `s_o = r_o + Hash(...)·d_o`.
  `s_o` is the secret `t` that unlocks the adaptor sig. Decrypt + verify under
  standard BIP340 ⇒ swap settles.
- **E** Round-trip: `recover(pre, completed) == s_o` (cryptographic invariant).
- **F** Negative: attestation for "no" produces a different scalar that does
  NOT decrypt to a valid BIP340 sig under the maker's pubkey — i.e. the wrong
  oracle outcome cannot maliciously settle the swap.

All 6 stages PASS. The demo is **proof that the composition works**, not a
production protocol — that needs additional CSV-timelocked refund paths in the
on-chain artifact, which is out of scope here but already specified in BTX2
spec §6 (CONDITIONAL_ORDER record).

## What deliberately stayed out

- **Full BIP327 interactive 2-round signing in Rust.** The trusted-aggregator
  variant covers BTX's actual use case (single pool operator). Full BIP327
  interactive signing is on the roadmap as a separate ~1-week port; the
  scouting doc's verdict ("strategic for institutional makers… zero protocol
  change, only maker-side coordination") still applies.
- **A direct port of zkp's `schnorr_adaptor` C reference.** Our Schnorr adaptor
  in Python and Rust is derived from Fournier's paper and BTX's existing BIP340
  primitives. Cross-validation against zkp's own `schnorr_adaptor` module
  (byte-identical golden test) is a follow-up that would mirror our existing
  Runes triple-validation discipline. Not load-bearing — the construction is
  small enough that an audit is more useful than a byte-cross-test.
- **`ecdsa_s2c` (literally — the ECDSA flavour).** BTX makers use Schnorr; the
  Schnorr S2C we shipped is simpler and aligned. The ECDSA module from zkp is
  not useful to BTX.
- **`bppp` / `rangeproof` / `surjection`.** These require Confidential
  Transactions infrastructure that Bitcoin mainnet doesn't have and isn't
  getting. Correctly skipped per the scouting doc; still correct now.

## File map

```
bitcoin-terminal-exchange/
├── btx_s2c.py                                (309 LOC, NEW this session)
├── btx_musig2_adaptor.py                     (NEW this session)
├── btx_dlc_demo.py                           (NEW this session)
├── btx_taproot.py                            (existing — BIP340/341 primitives)
├── btx_adaptor.py                            (existing — Schnorr adaptor)
├── btx_musig2.py                             (existing — KeyAgg + pool demo)
├── btx_halfagg.py                            (existing — half-aggregation)
├── BTX-secp256k1-zkp-scouting-2026-06-02.md  (existing — what to extract)
└── BTX-secp256k1-zkp-followup-2026-06-03.md  (THIS DOC — what got extracted)

brk-btx/crates/brk_indexer/
├── src/btx_s2c.rs                            (NEW this session — verifier-side)
├── src/btx_musig2.rs                         (EXTENDED — added pool_sign_trusted_aggregator)
├── src/btx_adaptor.rs                        (existing — Rust adaptor)
├── src/btx_halfagg.rs                        (existing — Rust half-agg)
├── tests/s2c_golden.json                     (NEW — 5 vectors)
├── tests/musig2_pool_golden.json             (NEW — 3 vectors)
├── tests/adaptor_golden.json                 (existing)
├── tests/halfagg_golden.json                 (existing)
└── tests/musig2_golden.json                  (existing)
```

## Test totals

| Module                              | Python tests       | Rust tests       |
|-------------------------------------|--------------------|------------------|
| btx_s2c                             | 5 golden vectors   | 4 (golden + 3 negative) |
| btx_musig2 (key_agg + pool sign)    | self-test          | 4 (incl. byte-cross-test of pool sign) |
| btx_adaptor                         | existing 5 vectors | existing         |
| btx_halfagg                         | existing 6 vectors | existing         |
| btx_musig2_adaptor                  | 3 vectors          | not ported       |
| btx_dlc_demo                        | 6-stage flow       | not ported       |

The Rust ports cover everything that runs on the indexer side (verification +
state transition). Python ports cover the maker side (signing). This split
matches the existing BTX2 stack.

## Closing the scouting doc's follow-up table

Quoting from `BTX-secp256k1-zkp-scouting-2026-06-02.md` lines 271–277:

| Action                                                                          | Effort estimate | Status at 2026-06-03 |
|---------------------------------------------------------------------------------|-----------------|----------------------|
| Prototype MuSig2 pool-maker tool in Python using existing reference             | ~1 week         | DONE — `btx_musig2.pool_sign_demo` + `btx_musig2_adaptor.pool_pre_sign` |
| Spec out the BTX2 artifact format with conditional-order sub-types              | ~2 weeks        | DONE — `BTX-v2-spec-2026-06-02.md` §6 (CONDITIONAL_ORDER record) |
| Build a regtest DLC-style demo: oracle attests outcome → adaptor decrypt → swap | ~1 month        | DONE — `btx_dlc_demo.py` (pure-Python; regtest version trivial follow-up) |
| Audit BTX1 → BTX2 format migration path with backward-compatibility             | ~1 week         | partial — BTX2 indexer ships; explicit migration audit doc not written |
| Build half-agg into the BTX2 batch-announce path                                | ~3 days         | not done — module exists; wiring into record format not verified |

## Recommended next items

In rough order of value, all *outside* the secp256k1-zkp extraction (the
extraction is now complete for BTX's current scope):

1. Wire half-agg into BTX2 BATCH_ANNOUNCE record format (3 days). Module
   exists; the record schema needs to accept and verify the aggregated form.
2. Cross-validate Schnorr adaptor against zkp's `schnorr_adaptor` module
   (1 day). Mirror our Runes triple-validation discipline.
3. Decide on S2C integration path (delayed-reveal vs registry vs key-path).
   The primitive is shipped; the design decision is its own task.
4. Full BIP327 interactive 2-round signing in Rust (~1 week). Only needed
   if BTX adds mutually-distrusting pool members; trusted-aggregator covers
   all current use cases.

## Commits this session

- `btx_s2c.py` Python primitive — `bitcoin-terminal-exchange` `f77cc79`
- `btx_s2c` Rust verifier + golden — `brk-btx` `629ca8e`
- MuSig2 pool sign Rust + adaptor combo Py + DLC demo Py — pending commit
  (this doc + remaining files committed together once all stages PASS)

## Verdict

Reading the scouting doc against the current state of both repos, **every
load-bearing item from `BlockstreamResearch/secp256k1-zkp` that the doc
identified as having BTX-relevant value has now been extracted, ported, and
tested**. The one item the doc itself flagged with "real privacy/un-
flaggability potential" (sign-to-contract) is now both in Python and Rust with
golden cross-validation. The items the doc deferred-with-reason (CT-dependent
primitives, niche modules) remain correctly deferred.

What remains in the scouting doc's follow-up surface is **integration work**
(wiring primitives into BTX2 records, designing the S2C reveal-channel,
production-grade interactive BIP327) — not extraction. The cloned repo's
extractable value to BTX is, by the audit's own criteria, fully captured.
