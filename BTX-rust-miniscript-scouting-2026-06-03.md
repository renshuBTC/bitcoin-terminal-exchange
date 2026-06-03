# Scouting report — `rust-bitcoin/rust-miniscript` for BTX

*Deep-dive on Sanket Kanjalkar's (sanket1729) Rust implementation of
Miniscript + Output Descriptors. Companion to
`BTX-secp256k1-zkp-scouting-2026-06-02.md` and
`BTX-secp256kfun-scouting-2026-06-03.md`. Pivots from crypto-primitive
extraction to script-policy layer.*

Date: 2026-06-03.

## Why this developer

Sanket Kanjalkar (@sanket1729) is a Blockstream-then-Block (Square)
cryptographer who co-designed **Miniscript** with Pieter Wuille and
Andrew Poelstra. Per his profile:

> *"Ideated, designed and implemented Miniscript, a language for bitcoin
> script from scratch that simplifies script development, wallet fee
> estimation, and enhances security, with ecosystem-wide adoption.
> Miniscript was adopted by the bitcoin core project and used by more
> than 95% of all bitcoin network participants, and he collaborated with
> industry-leading wallet providers including Ledger, Coldcard, and Jade
> to integrate Miniscript into their platforms."*

He maintains three of the canonical `rust-bitcoin` ecosystem crates:
`rust-bitcoin`, `rust-miniscript`, and `rust-secp256k1`.

`rust-miniscript` is the most BTX-relevant of his publicly-maintained
repos because it represents a layer BTX hasn't touched yet: **declarative
script policy**. Every other BTX scouting target has been a crypto
primitive. This one extends BTX's reach into the *spending-condition*
side of Bitcoin, where BTX2 records currently hard-code key-path-only
semantics.

## Repository at a glance

Cloned to `Bitcoin CoreX/rust-miniscript-reference/` at master HEAD
(2026-06-03). 58,331 LOC of Rust across the following modules:

| Module          | LOC    | Purpose                                              |
|-----------------|--------|------------------------------------------------------|
| `miniscript/`   | 33,323 | The Miniscript language itself: parsing, encoding, type system, satisfaction analysis |
| `descriptor/`   | 9,177  | Output Descriptors (BIP-380/381/382/385/386), wallet-oriented spending-condition strings |
| `policy/`       | 4,809  | Concrete and Semantic policy languages, plus the policy → Miniscript compiler (feature-gated) |
| `interpreter/`  | 3,059  | Bitcoin Script interpreter; verifies witnesses against descriptors |
| `psbt/`         | 2,159  | PSBT helpers: finalize an unsigned PSBT from a descriptor + signatures |
| `plan.rs`       | 1,248  | Spending plans — given a descriptor + available signers/preimages/timelocks, produce the optimal witness |
| `validation.rs` | 415    | Type-system checks for Miniscripts |
| `primitives/`   | 577    | locktimes, thresholds                                |

The crate is `no_std`-friendly and supports user-defined key types
(unlike the canonical `bitcoin::PublicKey`-only flavour). Active CI;
MSRV 1.63.

## What's "Miniscript" — one-paragraph mental model

Miniscript is a **structured subset of Bitcoin Script** designed so that:

- Every spending condition can be **analyzed** (size, sat cost, timing
  constraints, what data the spender needs)
- Spending conditions can be **composed** (`and_v(pk(A), older(7d))`)
- Compiling a Miniscript to Bitcoin Script is **invertible** (the
  decoder reconstructs the original tree, not just the byte form)
- Combined with **Output Descriptors** (e.g., `tr(internal_key,
  {pk(taker), pk(maker)})`), it gives wallets a portable string format
  for any spending condition, including all Taproot key-path / script-path
  combinations.

For BTX, this is the layer that would replace hand-rolled
`btx_taproot.p2tr_scriptpubkey` + `tapleaf_hash` + `tapbranch_hash` +
manual witness construction with a single descriptor-parsing call.

## Module-by-module value to BTX

### 1. `descriptor/` — HIGH STRATEGIC VALUE

9,177 LOC. Implements **Output Descriptors** (BIPs 380-388), including
`tr(...)` for Taproot.

Current BTX state:
- Makers publish a 32-byte x-only pubkey in the order body's
  `maker_pubkey` field.
- The offer UTXO is constructed off-chain by the maker via
  `btx_taproot.p2tr_scriptpubkey(maker_xonly)`.
- There is no way for a maker to publish, on-chain, a *complex* spending
  condition (e.g., "this offer is fillable until height H, after which
  it's cancellable by me").

What `descriptor/` buys:

- **Maker can publish a descriptor STRING in the order body** instead of
  a raw x-only pubkey. The string is human-readable, BIP-380 canonical,
  and supports all Taproot variants. E.g.,
  `tr(maker_xonly,{pk(taker),and_v(v:pk(maker),older(1008))})`.
- **BTX indexer can canonically verify** that the maker's claimed
  scriptPubKey matches the published descriptor — using
  `Descriptor::script_pubkey()` from this module.
- **Standardised maker rotation:** `tr(musig(A,B,C))` lets a pool
  publish without revealing the individual pubkeys.

Build cost to integrate: significant. BTX would have to spec a new BTX2
record type (or BTX3 entirely) with a length-prefixed descriptor string
field; teach the indexer to parse it; teach the GUI to display it. ~3
weeks.

### 2. `policy/` — HIGH STRATEGIC VALUE (forward-looking)

4,809 LOC. Concrete and Semantic policy languages + the policy compiler.

Why BTX wants this eventually:

Today BTX2 CONDITIONAL_ORDER records are tied to one specific adaptor
sig + one encryption point T. They can express "fill iff secret t is
revealed." They cannot express "fill iff (oracle says A) OR (oracle says
B AND time > H)."

Miniscript policy can:

```
or(
  and(pk(maker), pk(oracle_attests_A)),
  and(pk(maker), pk(oracle_attests_B), older(1008))
)
```

The policy compiler turns this into an optimal Bitcoin Script tree,
which BTX could embed as a tapscript branch.

Adoption requires BTX to add a SCRIPT_PATH_CONDITIONAL record type. Big
spec change. Realistically only worthwhile if (a) BTX has a customer
asking for multi-outcome DLCs, or (b) BTX adds covenant-based orders
post-CTV activation.

### 3. `plan.rs` — MEDIUM STRATEGIC VALUE

1,248 LOC. The spending-plan module: given a descriptor + a set of
available signers/preimages/timelocks, produce the witness data needed
to spend.

For BTX, this is the "smart fill" capability:
- Taker provides their key + the offer's descriptor
- BTX wallet code asks `plan.rs` what the witness should look like
- Builds the PSBT accordingly

Currently BTX hand-rolls this for the SIGHASH_SINGLE|ANYONECANPAY (`0x83`)
fill pattern. Generalising would let BTX support fills against any
Taproot script-path order in one code path.

Build cost: ~1-2 weeks if BTX2 starts publishing descriptors.

### 4. `psbt/` — MEDIUM STRATEGIC VALUE

2,159 LOC. PSBT utilities: finalize a PSBT given a descriptor +
signatures.

BTX's current PSBT path (`btx_carrier.py`, the Tauri wallet) hand-rolls
PSBT construction. rust-miniscript's `psbt/` would let BTX:
- Validate incoming PSBTs canonically (catches malformed taker
  submissions)
- Finalize PSBTs with proper witness construction
- Cross-check against BTX's hand-rolled path (similar to the BIP-340
  cross-validation)

Build cost: small if used as a validation reference (~1 day), larger
if BTX migrates its PSBT code to rust-miniscript (~1 week).

### 5. `interpreter/` — LOW VALUE

3,059 LOC. Verifies witnesses against descriptors.

BTX doesn't verify scripts — that's bitcoind's job (BTX submits a tx and
the network either accepts or rejects). The interpreter would only be
useful as a *pre-submission validation* step ("would my PSBT actually
succeed if I broadcast?"). Optional polish; not required for BTX
correctness.

### 6. `miniscript/` (the language core) — REFERENCE ONLY

33,323 LOC. The bulk of the crate. Implements the Miniscript language
itself: parsing, encoding, type-system checks, satisfaction.

BTX would consume this transitively via the higher-level
`descriptor/` and `policy/` modules. Direct extraction isn't valuable
— it's the engine under the hood.

## What's actually extractable for BTX NOW

Honest assessment: **none of this is a slam-dunk for BTX's current
scope.**

BTX2 records are deliberately key-path-only:
- Smaller wire format
- Cheaper verification
- Compatible with BTX's existing trusted-aggregator pool / FROST / DLC
  patterns (all key-path)

Miniscript / descriptors become essential when BTX needs:
1. **Multi-outcome DLCs** (the OR-of-conditions case for oracle
   attestations)
2. **Covenant-based orders** (post-CTV / post-CCV)
3. **Script-path conditional fills** (more sophisticated than adaptor
   sig single-key conditions)
4. **External wallet interop via descriptors** (Ledger / Coldcard /
   BDK-using makers)

None of these are on BTX's current product roadmap.

## Recommendation

| Action                                                       | Effort | Strategic value | Status         |
|--------------------------------------------------------------|--------|-----------------|----------------|
| Scout `descriptor/` and `policy/` to understand the design   | done   | high            | this doc       |
| Spec BTX3 record type carrying a Miniscript descriptor string| 1 wk   | high if shipped | bookmarked     |
| Port a minimal Taproot descriptor parser to Python (`tr(K)` only) | 2 days | low currently | bookmarked     |
| Cross-validate BTX's hand-rolled PSBT against rust-miniscript| 1 day  | medium          | bookmarked     |
| Adopt `plan.rs` for "smart fill" of script-path orders       | 1-2 wk | high if BTX3   | bookmarked     |

**No item ships in this scouting session.** Unlike `secp256k1-zkp` and
`secp256kfun` (where BTX directly ported FROST + S2C + half-agg + DLC
+ DLEQ + MuSig2 KeyAgg), `rust-miniscript` does not have a primitive
that maps to BTX's current product surface.

The honest framing: rust-miniscript is a **reference for BTX3 design**,
not an extraction source for BTX2.

## What this rules in / rules out

**Rules in** (if BTX moves to script-path orders in BTX3):
- Use canonical Output Descriptors as the maker_pubkey successor
- Use policy compiler for multi-outcome DLCs
- Use `plan.rs` for "smart fill" against script-path
- Use `psbt/` for canonical PSBT construction

**Rules out** for current BTX2:
- Key-path orders don't need any of this
- The wire-format cost of carrying a descriptor string (vs 32-byte
  x-only) is not justified by the current product
- The complexity of integrating rust-miniscript as a Rust dependency
  has no offsetting benefit in BTX's hot path (the indexer doesn't
  need to verify scripts)

## Comparison with the previous scouting docs

| Repo                                  | What landed in BTX                                       | What rust-miniscript would add                       |
|---------------------------------------|----------------------------------------------------------|-------------------------------------------------------|
| `BlockstreamResearch/secp256k1-zkp`   | half-agg, MuSig2 KeyAgg, Schnorr adaptor, BIP340 S2C, DLC | n/a (different layer)                                |
| `LLFourn/secp256kfun`                 | FROST trusted-dealer; cross-curve DLEQ spec              | n/a (different layer)                                |
| `bitcoin/bips` (Wuille, Nick, Ingala et al.) | BIP-340/341/327/374 canonical-validated; DLEQ port      | n/a (different layer)                                |
| `rust-bitcoin/rust-miniscript`        | **nothing this session**                                 | script policy, descriptors, satisfaction plans (BTX3) |

The first three closed out the crypto-primitive surface. `rust-miniscript`
opens a new surface (script policy) that BTX hasn't yet decided to
inhabit.

## Verdict — REVISED after deeper dive

The first-pass verdict ("no code lands") was wrong. A deeper read of
`examples/taproot.rs`, `src/descriptor/tr/mod.rs`, and
`src/descriptor/checksum.rs` surfaced a concrete extraction point at
**the simple end of the descriptor surface**:

**`btx_descriptor.py` SHIPPED THIS SESSION** (~280 LOC):

- Parses and serialises `tr(<x-only-hex>)` descriptors (key-path-only
  Taproot)
- Computes canonical BIP-380 checksums (byte-identical to
  `rust-miniscript::descriptor::checksum`)
- Produces canonical bc1p... addresses for any maker x-only pubkey
- 3-vector cross-test against a real `rust-miniscript`-built Rust
  probe:

| x-only pubkey input (first 16 hex) | BTX address                    | rust-miniscript address        |
|------------------------------------|--------------------------------|--------------------------------|
| d6889cb081036e0f...                | bc1p2wsldez5mud2y...59h4z5     | bc1p2wsldez5mud2y...59h4z5 ✓   |
| 50929b74c1a04954...                | bc1prykz5vxt6lgr2t...5grvgr    | bc1prykz5vxt6lgr2t...5grvgr ✓  |
| f9308a019258c310...                | bc1pgxxyvcmdncdxs0...y33gs     | bc1pgxxyvcmdncdxs0...y33gs ✓   |

And canonical descriptor checksums also match byte-for-byte
(`zd5eym6u`, `pg0pl855`, `5ceacj8z`).

This unlocks:
- **Canonical maker pubkey publication**: BTX can publish
  `tr(<maker_xonly>)#<csum>` strings that any BIP-380-compliant
  wallet (Ledger / Coldcard / Jade / BDK / Core wallet) understands
  byte-exactly.
- **Cross-test for any future drift** in BTX's Taproot foundation
  (every change to `btx_taproot.taproot_tweak_pubkey` is now
  cross-checked against rust-miniscript via `btx_descriptor.py`'s
  golden vectors).
- **Building block for BTX3** if/when BTX moves to script-path orders
  — the descriptor STRING surface is already plumbed.

The wider rust-miniscript machinery (Policy compiler, `plan.rs`
satisfaction, `psbt/` finalisation, the full Miniscript language) is
still bookmarked as BTX3 work — that part of the original verdict
stands.

### Lessons from the false-start

I initially called "no extraction" after reading only ~80 lines of
`policy/mod.rs` and `policy/concrete.rs`. That was premature. The
extractable piece is at the **simplest** end of the descriptor
hierarchy (`tr(K)` key-only), not the complex policy-compiler end.

There was also a one-line implementation bug worth pinning: my first
draft of `descriptor_checksum` conflated `cls` (the running polynomial
value) with `clscount` (the 0-3 counter). Bitcoin Core's reference
keeps them separate. All 3 vectors diverged from canonical until the
fix. The fix surfaced because I built the rust-miniscript probe and
compared — the kind of cross-validation that catches transcription
errors the polymod constants alone wouldn't reveal.

This is the same discipline as the BIP-340/341/327/374 foundation
work: build a probe against the canonical reference; compare byte by
byte; fix anything that diverges.

## File index

```
Bitcoin CoreX/rust-miniscript-reference/        (cloned 2026-06-03, master HEAD)
  ├── Cargo.toml                                workspace + feature flags
  ├── README.md                                 high-level feature list
  ├── src/
  │   ├── miniscript/    (33,323 LOC)           the language itself
  │   ├── descriptor/    (9,177 LOC)            BIP-380 Output Descriptors
  │   ├── policy/        (4,809 LOC)            concrete + semantic + compiler
  │   ├── interpreter/   (3,059 LOC)            script verification
  │   ├── psbt/          (2,159 LOC)            PSBT finalisation
  │   ├── plan.rs        (1,248 LOC)            spending plans
  │   ├── validation.rs  (415 LOC)              type checks
  │   └── primitives/    (577 LOC)              locktimes, thresholds
  └── examples/                                 wallet patterns

bitcoin-terminal-exchange/
  ├── BTX-rust-miniscript-scouting-2026-06-03.md   (THIS DOC)
  └── (no code changes this session)
```

## Source

Repo: <https://github.com/rust-bitcoin/rust-miniscript>
Maintainer: Sanket Kanjalkar (<https://github.com/sanket1729>)
Co-designers: Pieter Wuille, Andrew Poelstra, Sanket Kanjalkar
Examined: master HEAD as of 2026-06-03 clone.
