# Scouting report — Lloyd Fournier's `secp256kfun` for BTX

*Deep-dive on `LLFourn/secp256kfun` at master commit `74d18bbf`
(2026-05-12), assessing whether any of its primitives move BTX forward
beyond the secp256k1-zkp extraction closed in
`BTX-secp256k1-zkp-FINAL-2026-06-03.md`. Companion to that doc.*

## Why this developer

Lloyd Fournier (LLFourn) is a working Bitcoin cryptographer whose published
research is **already cited** in BTX:

> *"`btx_adaptor.py` ... built on BTX's existing BIP340 primitives in
> btx_taproot.py. Construction (from **Lloyd Fournier's "One-Time
> Verifiably Encrypted Signatures"** and the generalized-channels paper,
> adapted to BIP340)"*  (btx_adaptor.py header)

His GitHub profile shows research-grade artefacts:

- `one-time-VES` — paper repo for the construction BTX uses
- `two-round-dlc` — *"How to make a Prediction Market on Twitter with
  Bitcoin"*
- `sb19-ot-lottery` — Scaling Bitcoin 2019 scriptless lottery from
  oblivious transfer
- `taproot-ggm` — Financial Crypto 2020 analysis of Taproot's hash
  function security requirements
- **`secp256kfun`** — his pure-Rust crypto library that powers
  **Frostsnap** (his production threshold hardware wallet system)

`secp256kfun` is the natural follow-up to the secp256k1-zkp extraction
because it implements the same primitives in pure Rust (no C bindings) with
a researcher-ergonomic API and ships **two things zkp does not**: full
ChillDKG distributed key generation for FROST, and the cross-curve
discrete-log-equality proof underlying Monero/Solana-style atomic swaps.

## Repository at a glance

Cloned to `Bitcoin CoreX/secp256kfun-reference`. Workspace structure:

```
secp256kfun-reference/
├── secp256kfun/       11,673 LOC   point/scalar arithmetic + vendored k256
├── schnorr_fun/        8,640 LOC   BIP340 + MuSig2 + FROST + adaptor sigs
├── ecdsa_fun/          1,076 LOC   ECDSA + ECDSA adaptor (BTX uses Schnorr)
├── sigma_fun/          2,261 LOC   sigma protocols + cross-curve DLEQ
├── vrf_fun/            1,035 LOC   RFC 9381 verifiable random functions
└── arithmetic_macros/      —       compile-time GF helpers
                       ─────────
                       24,685 LOC total
```

Most recent commit: `74d18bbf` 2026-05-12 — actively maintained.

## The author's own caveat (worth quoting in full)

From the README:

> *"**Should use?** This library is ready for production as long what you
> are trying to produce is **fun and amusement!**. If you want to engineer
> something solid that a lot of people's money will depend on, this
> library is a risky choice."*
>
> *"Fun does not mean (yet — please help!): **well reviewed** — The
> implementations here have no received much review. **side-channel
> resistant** — There has been no empirical investigation into whether
> this library or the underlying arithmetic from k256 is resistant against
> timing attacks etc. **No** attempt is made to "zero" out secrets when
> memory is freed."*

This is load-bearing for how BTX should use it. Three usage modes follow
naturally:

1. **As production crypto in `brk_indexer` / makers handling real
   funds** — NO. The README rules this out and BTX makers move real BTC.
   Continue using `rust-secp256k1` (libsecp bindings) for the signing
   hot path.
2. **As a reference for cross-validation** — YES. Mirror the discipline
   BTX already uses for Runes (triple-validated against ord + Magic
   Eden's `runestone-lib`). Lloyd's Schnorr adaptor is his own
   implementation of his own paper — it's the canonical reference for
   what BTX hand-rolled.
3. **As a source for primitives BTX doesn't have yet** — YES, for FROST,
   ChillDKG, and cross-curve DLEQ. Each of these would require a fresh
   Rust port to BTX, not a direct dependency, but having a working
   reference cuts the design risk substantially.

## Module-by-module value to BTX

### 1. `schnorr_fun::frost` + `schnorr_fun::frost::chilldkg` — HIGH VALUE

5,007 LOC across 8 files. Production-grade implementation used by
Frostsnap (Lloyd's hardware wallet system).

What's in it:

- `frost/mod.rs` (453 LOC) — main FROST API: `coordinator_sign_session`,
  `party_sign_session`, `aggregate`
- `frost/session.rs` (253 LOC) — sign-session state machine
- `frost/share.rs` (644 LOC) + `frost/shared_key.rs` (750 LOC) — secret
  share representation and aggregated key types
- `frost/chilldkg/simplepedpop.rs` (974 LOC) — trusted-setup DKG variant
- `frost/chilldkg/encpedpop.rs` (1,115 LOC) — encrypted DKG (no trusted
  comms needed)
- `frost/chilldkg/certpedpop.rs` (702 LOC) — certified DKG (with signing
  certificates)

**Why BTX wants this:**

BTX2 today supports n-of-n maker pools (via `pool_sign_trusted_aggregator`
in both Py and Rust). FROST adds *t-of-n* — e.g. 3-of-5 of a maker pool
can sign an offer, the other 2 can be offline. This is the difference
between "everyone has to be online" and "enough people are online", which
matters for institutional makers running on multiple data centres or
geographies.

The BTX watchlist (`memory/project_btx_watchlist_refresh.md`) already
tracks FROST as **RFC 9591**. Lloyd's implementation is one of the few
production references; the only other one is the BIP draft `bip-frost` /
`bip-frost-keygen`, which is still in flux. ChillDKG (the three flavours
above) is the *modern* DKG that solves the bootstrapping problem older
protocols had.

**Borrow:** ChillDKG's `encpedpop` flavour is the right starting point —
it doesn't require a trusted setup and works over public channels. A Rust
port of the FROST signing path could land in `brk_indexer::btx_frost`
similar to how `btx_musig2` lives today. Format would be UNCHANGED — the
aggregated FROST x-only key occupies the same `maker_pubkey` field in
BATCH_ANNOUNCE; the indexer doesn't know it's FROST.

**Reject:** the README's "fun and amusement" caveat. A production FROST
in BTX should either (a) audit-then-port Lloyd's code with eyes open, or
(b) wait for `bitcoin-core/secp256k1` to ship FROST (currently
PR-tracked) and consume that via `rust-secp256k1`.

**Verdict:** highest strategic value of the entire repo. The closest
BTX can credibly get to "institutional t-of-n maker pools" today.

### 2. `sigma_fun::ext::dl_secp256k1_ed25519_eq` — HIGH VALUE (novel for BTX)

340 LOC. Cross-curve discrete-log-equality proof between secp256k1 and
ed25519 — the cryptographic primitive behind atomic swaps with **Monero**
and **Solana** (both ed25519-based).

From the module doc:

> *"Here 'equality' means the two secret scalars have the same 252-bit
> representation. To prove they have the same representation we make two
> sets of 252 Pedersen commitments and show that: 1. for i=0..252 we show
> the ith commitment is either to 0 or 2^i, 2. that the commitments are
> the same value for both sets, 3. the sum of the commitments equals the
> claimed public keys on each curve."*
>
> *"This was partially inspired by **MRL-0010** [Monero Research Lab
> report] but it re-imagines it as a Sigma protocol."*

**Why BTX wants this:**

A BTX2 CONDITIONAL_ORDER today can be keyed to ANY encryption point T on
secp256k1. If T is constructed as a cross-curve DLEQ commitment, then
revealing the decryption key on Monero or Solana ALSO reveals it on
Bitcoin. That unlocks:

- *"Fill iff there's a Monero payment of X XMR to address Z"* — done
  atomically, no bridge, no oracle, no trust assumption beyond the two
  chains' consensus
- *"Fill iff there's a Solana SPL token transfer of Y USDC"* — same
  shape
- *"Cross-chain pool fills"* — a BTX maker pool can accept payment on
  multiple chains, atomically

No other Bitcoin DEX has this (the competitive landscape in
`BTX-competitive-landscape.md` only lists Category-A on-chain order books;
none of them have cross-chain settlement). It's not just a technical
improvement — it's a market category.

**Borrow:** a reference port (~340 LOC scaled to ~500 LOC of Python +
~600 LOC of Rust) wired into a new `btx_xc_swap.py` and a CONDITIONAL_ORDER
sub-type 0x04 (CROSS_CURVE_CONDITIONAL). Same BIP340 adaptor settlement
on the Bitcoin leg; same ed25519 normal-sig settlement on the other leg.

**Reject:** the MRL-0010 lineage carries Monero's specific encoding
quirks. Care needed to ensure the BTX wire format is endian-clean and
doesn't accidentally re-export a Monero-isomorphic format.

**Verdict:** highest *novelty* value. Opens a feature category none of
BTX's documented competitors have. Build cost is high (~2 weeks per
the analogous estimates in the previous scouting doc) but the moat
matches what BTX needs (technical differentiation that's not just
"nothing offchain").

### 3. `schnorr_fun::adaptor` — MEDIUM VALUE (cross-validation)

387 LOC. Lloyd's own Rust reference for *his own paper*. This is the
canonical implementation of the construction BTX's `btx_adaptor.py` and
`btx_adaptor.rs` ports.

**Why BTX wants this:**

The `BTX-secp256k1-zkp-followup-2026-06-03.md` document explicitly
flagged one open item:

> *"A direct port of zkp's `schnorr_adaptor` C reference. Our Schnorr
> adaptor in Python and Rust is derived from Fournier's paper and BTX's
> existing BIP340 primitives. Cross-validation against zkp's own
> `schnorr_adaptor` module (byte-identical golden test) is a follow-up
> that would mirror our existing Runes triple-validation discipline."*

Lloyd's `schnorr_fun::adaptor` is the *third* implementation that closes
the triangle. BTX → secp256k1-zkp → schnorr_fun. If all three produce
byte-identical (encrypted_signature, decryption, recovery) on the same
golden inputs, BTX's Schnorr adaptor is triple-validated to the same
standard as its Runes layer.

**Borrow:** a single-day cross-test that generates 5 vectors from BTX,
parses through `schnorr_fun::adaptor`, and asserts equality.

**Reject:** none; pure validation work.

**Verdict:** medium value but cheap effort. Closes the one open quality
item from the previous scouting closure.

### 4. `schnorr_fun::musig` — LOW-MEDIUM VALUE

919 LOC. Production-grade BIP327 with both deterministic and synthetic
nonce modes. Full interactive 2-round protocol (the part BTX skipped in
favour of trusted-aggregator).

**Why BTX could want this:**

If BTX adds mutually-distrusting pool members (e.g. two competing market
makers cooperating on a single offer without sharing keys), the full
interactive 2-round protocol becomes load-bearing. Today this isn't a use
case — BTX's pool use case is "one operator with multiple keys" which
trusted-aggregator covers.

**Verdict:** parking. Worth bookmarking for "if BTX needs distrustful pool
members" — a hypothetical future use case. No work now.

### 5. `vrf_fun` — LOW VALUE

1,035 LOC. RFC 9381 Verifiable Random Functions.

Possible BTX use cases:

- **Maker lottery for batch-fill ordering.** When N takers race to fill an
  open offer, a VRF could deterministically pick the winner without a
  coordinator. Niche.
- **Oracle randomness for DLC-style orders.** If BTX adds dice/lottery
  conditional orders, a VRF-based oracle is the canonical construction.

**Verdict:** parking. No current product driver.

### 6. `ecdsa_fun` — NOT BTX-RELEVANT

1,076 LOC. ECDSA + ECDSA adaptor. BTX is Schnorr-only across all signing
paths (BTX1, BTX2, S2C, MuSig2, DLC). Not relevant unless BTX adds an
ECDSA leg, which there's no reason to do.

**Verdict:** skip.

### 7. `secp256kfun` core — REFERENCE ONLY

11,673 LOC. Point/scalar arithmetic, hash-to-curve, vendored k256.

BTX's hand-rolled crypto in `btx_taproot.py` is ~530 LOC of Python doing
the same job. Replacing it with a Rust dependency would mean BTX makers
load this library — and the README's "no side-channel resistance / no
zeroing of secrets" warnings apply.

**Verdict:** the only legitimate use is as a CPU-time benchmark for BTX's
own crypto perf. Not a production replacement.

## Followup table (mirroring the previous scouting doc's structure)

| Action                                                                       | Effort  | Strategic value |
|------------------------------------------------------------------------------|---------|-----------------|
| Cross-validate `btx_adaptor` against `schnorr_fun::adaptor` (5 golden tests) | ~1 day  | medium          |
| Port Schnorr FROST signing (no DKG yet) to `brk_indexer::btx_frost`          | ~1 week | high            |
| Port ChillDKG/encpedpop to `btx_frost_keygen.py` (off-chain maker tooling)   | ~2 weeks| high            |
| Spec a BTX2 CROSS_CURVE_CONDITIONAL (0x04) record type using DLEQ            | ~3 days | high            |
| Port cross-curve DLEQ to `btx_xc_dleq.py` + golden vectors                   | ~1 week | high            |
| Build XMR↔BTX2 atomic-swap demo (pure-Python, like btx_dlc_demo)             | ~2 weeks| high            |
| Bookmark full-interactive MuSig2 (for when distrustful pools become real)    | —       | parking         |
| Bookmark VRF (for when randomness-driven orders become real)                 | —       | parking         |

## Worth noting

- **secp256k1-zkp comparison.** Lloyd's `schnorr_fun::frost` is a more
  complete FROST stack than anything in `BlockstreamResearch/secp256k1-zkp`
  today (zkp has no FROST yet). zkp leads on side-channel resistance and
  review; `secp256kfun` leads on completeness.
- **Frostsnap as production proof.** Lloyd ships `frostsnap` — a working
  hardware wallet that uses this library for threshold signing of real
  Bitcoin. That's the strongest production-use signal short of being in
  Core. (URL: `github.com/frostsnap/frostsnap`.)
- **License.** `0BSD` per the LICENSE file at workspace root. Compatible
  with BTX repo licensing.

## What's NOT in this repo (vs the secp256k1-zkp scouting doc)

- Half-aggregation — BTX has this from zkp; `secp256kfun` does not ship
  it
- ECDSA sign-to-contract — BTX has this from a BIP340 reimplementation;
  `secp256kfun` does not ship S2C in either ECDSA or Schnorr flavour
- Bulletproofs / range proofs / surjection — `secp256kfun` doesn't ship
  these either (correctly — they need CT infrastructure)

These three were all gains specific to zkp. There is no overlap-and-
contradict situation between the two libraries; they're complementary.

## Recommendation

If BTX picks ONE thing from this repo to integrate next, the order is:

1. **FROST + ChillDKG**. Strict upgrade to BTX's current n-of-n pool
   model. Strategic value: opens institutional t-of-n maker pools, a use
   case the current `pool_sign_trusted_aggregator` can't address. Build
   cost: ~1–3 weeks depending on whether DKG ships in the first cut.

2. **Cross-curve DLEQ**. Opens a new product category (cross-chain
   conditional orders without bridges). Build cost: ~3 weeks total
   (~1 week port + ~2 weeks demo + spec). No competitor has this; the
   moat is real.

3. **Cross-validate Schnorr adaptor**. Closes the one open quality item
   from the previous scouting closure. Build cost: ~1 day.

The cleanest sequence: ship #3 first (cheap, closes a known item), then
choose between #1 (deepens existing surface) and #2 (opens new surface)
depending on whether BTX wants to lean into pool-maker or
cross-chain-conditional-order narrative.

## File index

```
Bitcoin CoreX/secp256kfun-reference/      (cloned 2026-06-03)
  ├── Cargo.toml                          workspace + 0.12/0.13 crate versions
  ├── README.md                           the "fun" caveat
  ├── CLAUDE.md                           (their own AI-assistant guidance)
  ├── secp256kfun/                        core arithmetic
  ├── schnorr_fun/
  │   ├── src/musig.rs                    BIP327 full 2-round
  │   ├── src/frost/                      FROST + ChillDKG
  │   ├── src/adaptor/                    Lloyd's reference adaptor
  │   ├── src/binonce.rs                  2-nonce binding for MuSig2/FROST
  │   └── src/schnorr.rs                  BIP340
  ├── sigma_fun/
  │   └── src/ext/dl_secp256k1_ed25519_eq.rs  the cross-curve DLEQ
  ├── ecdsa_fun/                          ECDSA — out of scope
  └── vrf_fun/                            VRF — parked
```

## Source

Repo: <https://github.com/LLFourn/secp256kfun>
Examined commit: `74d18bbf` (master, 2026-05-12).
Author: Lloyd Fournier — paper repo `LLFourn/one-time-VES` is the
construction BTX already cites.
