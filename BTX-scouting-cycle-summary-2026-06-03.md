# BTX Scouting Cycle Summary — 2026-06-03

*Master record of the autonomous scouting cycle run on 2026-06-03.
Originally closed at 11 scouts (commit `5b83912`); extended to 14
after the user's "keep going" directive. Each repo or BIP was cloned
+ deep-read; outcomes are either code shipped or honest deferred-
with-reason scouting docs.*

This document was first written at the 11-scout mark and is now post-
amended with the 12th–14th scouts. The substantive content below
still describes the 11-scout reasoning; see
[Post-amendment](#post-amendment-12th-14th-scouts) at the bottom for
the additions.

---

## Cycle overview

| # | Repo | Author(s) | LOC | Outcome | Defer reason |
|---|------|-----------|-----|---------|--------------|
| 1 | `BlockstreamResearch/secp256k1-zkp` | Pieter Wuille et al. | ~50k C | **shipped** | — |
| 2 | `LLFourn/secp256kfun` | Lloyd Fournier | ~40k Rust | **shipped FROST + specced DLEQ** | — |
| 3 | `bitcoin/bips` | BIP authors | per-bip | **shipped BIP-374 DLEQ** | — |
| 4 | `rust-bitcoin/rust-miniscript` | Sanket Kanjalkar et al. | ~30k Rust | **shipped descriptors** | — |
| 5 | `sipa/minisketch` | Pieter Wuille, Greg Maxwell, Gleb Naumenko | ~5k C++ | spec only | operational (build deps) |
| 6 | `mit-dci/utreexo` | Tadge Dryja | ~13.3k Go | spec only | architectural |
| 7 | `Merkleize/pymatt` | Salvatore Ingala | ~12k Py | spec only | consensus (CCV not active) |
| 8 | `bitcoin-core/HWI` | Andrew Chow | ~5.4k Py + vendor SDKs | spec only | product (no hardware user) |
| 9 | `petertodd/python-bitcoinlib` | Peter Todd | ~6.8k Py | spec only | era (pre-Taproot) |
| 10 | `darosior/python-bip380` | Antoine Poinsot (checksum © Pieter Wuille) | ~4.1k Py | **shipped xtest** (new category) | — |
| 11 | `BlockstreamResearch/bip-frost-dkg` (ChillDKG) | Ruffing, Nick, Dhakshinamoorthy | ~5.7k Py | spec only | product timing (v1.0 upgrade) |

**Extraction rate: 5/11 ≈ 45%.**

---

## What "shipped" looks like by category

### Category A — Primitive port (4 scouts)

For these, BTX gained new working code that implements a Bitcoin
primitive:

- **secp256k1-zkp** — half-aggregation + MuSig2 + adaptor signatures
  + sign-to-contract + DLC demo. ~6 modules across Python + Rust.
- **secp256kfun (Phase A)** — `btx_frost.py` trusted-dealer t-of-n
  FROST.
- **bitcoin/bips (BIP-374)** — `btx_dleq.py` single-curve DLEQ.
- **rust-miniscript** — `btx_descriptor.py` BIP-380 tr(K) +
  checksum + BIP-371 PSBT fields. (This one had a methodological
  course-correction: the first verdict was "no code lands" after a
  shallow read; the user pushed back, the deeper read found the fit,
  and code shipped.)

### Category B — Cross-validation oracle (1 scout, NEW this cycle)

A new outcome category surfaced this cycle, distinct from Category A:

- **python-bip380** — no new primitive. Instead, the repo became a
  *second canonical oracle* for code BTX had already shipped (BIP-380
  checksum). The cross-test (`btx_xtest_vs_python_bip380.py`)
  validates BTX's checksum against Pieter Wuille's canonical Python
  reference. Result: 10/10 byte-for-byte match. The descriptor
  checksum is now triple-validated: BTX goldens + rust-miniscript +
  python-bip380.

This category permanently de-risks prior shipped code. It's
high-leverage when applied to code that has historically had bugs
(BTX's checksum had a `cls/clscount` bug last session, caught
by the rust-miniscript cross-test).

---

## What "spec only" looks like — the 6-category taxonomy

The deferred half of the cycle clusters into 6 distinct reason
categories. Each represents a different kind of "right tool, wrong
something":

### 1. Operational (build/install constraints)

- **`sipa/minisketch`** — pristine C++ library with a clean C API,
  but building requires `autoconf` / `libtool` / `cmake` which need
  `sudo apt install` (no password). Pure-Python re-derivation would
  be 1-2 weeks of careful cryptographic engineering. **Trigger to
  ship: user installs build deps.**

### 2. Architectural (no use case in current scope)

- **`mit-dci/utreexo`** — beautiful UTXO accumulator. BTX doesn't
  track UTXOs (brk_indexer extracts BTX2 envelopes; clients trust
  HTTP API). Plus Go language vs Python/Rust. **Trigger to ship:
  BTX adds trustless light-client mode or peer-to-peer indexer
  mesh.**

### 3. Consensus-dependent (soft-fork not active)

- **`Merkleize/pymatt`** — MATT covenants via
  `OP_CHECKCONTRACTVERIFY` (BIP-443 draft). The opcode is not on
  mainnet; pymatt runs only against `bitcoin-inquisition`. **Trigger
  to ship: CCV activates on mainnet.**

### 4. Product-driven (no current user demand)

- **`bitcoin-core/HWI`** — canonical hardware-wallet interface.
  Three concrete integration paths laid out (subprocess shim, library
  import, PSBT cross-validation oracle). All blocked on: BTX has one
  user (Renshu), no maker desk requesting hardware signing. **Trigger
  to ship: first hardware-wallet maker desk request.**

### 5. Era mismatch (pre-Taproot library)

- **`petertodd/python-bitcoinlib`** — *"The Swiss Army Knife of the
  Bitcoin protocol"* per Wladimir van der Laan, ~6.8k LOC. But no
  Schnorr, no Taproot, no bech32m, no tagged hashes — pre-BIP-340.
  BTX is Taproot-native. **Trigger to ship: Peter Todd publishes a
  Taproot update (no signal).**

### 6. Product timing (v1.0+ upgrade) — NEW this cycle

- **`BlockstreamResearch/bip-frost-dkg` (ChillDKG)** — the direct
  upgrade path from trusted-dealer FROST. ~2,177 LOC pure-Python
  reference. Integration is bounded (~2-3 weeks) and the BTX2
  envelope change is zero. But BTX has zero multi-org maker pools
  today, so the feature has no users. **Trigger to ship: first
  multi-org maker pool requests trustless key generation.**

---

## Lessons / patterns

### 1. "Always clone and do a deeper dive before concluding"

The user's mid-cycle correction on the rust-miniscript verdict was
the most consequential moment of the cycle. The initial "no code
lands" verdict (~80-line shallow read) was wrong. The deeper dive
(examples/, descriptor/tr/mod.rs) surfaced a real fit and shipped
`btx_descriptor.py`. **Generalised rule: never trust a shallow-read
verdict on a non-trivial library.**

### 2. Cross-validation discipline catches real bugs

The same descriptor checksum that triple-validated cleanly in this
cycle had a `cls vs clscount` conflation bug in its first draft last
session. The discipline of "build canonical probe, compare bytes"
caught it. The bug recipe is in
`BTX-cross-validation-discipline-2026-06-03.md`. **Generalised rule:
when shipping cryptographic code, always pair with at least one
external canonical reference cross-test.**

### 3. Deferred-with-reason is a first-class outcome

Six "spec only" scouts in this cycle are NOT failures. Each is a
bounded, well-categorised future commitment with a named trigger.
The cycle's master artifact isn't the code that landed — it's the
**clean taxonomy of when to revisit each scout**. **Generalised
rule: write the trigger conditions explicitly; vague "TODO: revisit"
notes have no half-life.**

### 4. New outcome categories emerge from real work

Category B (cross-validation oracle) was not in the plan when the
cycle started. It emerged from the python-bip380 read: "this repo
has nothing new to port, BUT it has a canonical reference for code
BTX already ships." Recording that as a distinct outcome lets future
scouting cycles target it deliberately. **Generalised rule: let the
work surface new outcome categories; codify them only after they've
appeared.**

### 5. Independent NUMS-key confirmation

Two repos in the cycle (pymatt and python-bip380's TrDescriptor
construction) independently use the same BIP-341 NUMS x-only key
that BTX picked as vector #1 for descriptor goldens:

```
50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0
```

This is a *meta* cross-validation: independent implementations of
the BIP-341 "unspendable internal key" recommendation converge on
the same value. Not a discovery (the BIP defines it) but a small
confidence boost that BTX is on canonical convention.

### 6. The watcher-script pattern works

Across ~12 commits this cycle, the WSL watcher pattern (drop
numbered `.sh` files into `.btx-watcher/queue/`, get `.done` files
back with output) executed cleanly. Two specific gotchas surfaced:

- **Filename ordering matters.** Files numbered below the current
  queue head won't be picked up. The cycle's recent commits used
  3200-series numbers.
- **`setsid bash -c '...'`** is the right pattern when the kicker
  needs to return immediately (e.g., for git push that could hang).
  For simpler synchronous runs, plain `bash` works.

---

## Resulting BTX state

After this cycle:

- **`btx_xtest_suite.py`**: 8 PASS, 0 FAIL, 0 SKIPPED in ~10s.
  Sub-tests cover BIP-340 Schnorr, BIP-341 Taproot, BIP-327 MuSig2
  KeyAgg, BIP-374 DLEQ, BIP-380 tr(K) descriptors vs rust-miniscript,
  BIP-380 checksum vs python-bip380 (NEW), Runes decoder vs Magic
  Eden, Runestone cenotaph adversarial.
- **Triple-validated primitives**: BIP-380 descriptor checksum (3
  oracles: BTX goldens + rust-miniscript + python-bip380).
- **Quadruple-validated primitives**: BIP-340 Schnorr (BTX goldens +
  Bitcoin Core CSV + Jonas Nick's bips reference + Jonas's
  secp256k1lab/bip340.py [available, not yet wired]).
- **New scouting docs in bitcoin-terminal-exchange/**: 11 docs, one
  per scout, plus this summary.
- **Reference clones in `Bitcoin CoreX/`**: 7 new clones today
  (HWI, python-bitcoinlib, python-bip380, frost-dkg, plus the prior
  6 from earlier in the cycle). Each is preserved for future
  cross-tests or re-scouting.

---

## Forward-looking trigger table

The most useful artifact of this cycle is the **named-trigger map**
for when to revisit each deferred scout:

| Trigger event | Scout to revisit | What to ship |
|---------------|------------------|--------------|
| Build deps installed in watcher (sudo apt) | minisketch | libminisketch bindings + indexer sync |
| BTX adds light-client mode | utreexo | Pollard verifier port |
| `OP_CHECKCONTRACTVERIFY` activates on mainnet | pymatt | vault-style maker escrow |
| First hardware-wallet maker desk request | HWI | subprocess-shim path (~30 LOC) |
| Peter Todd publishes a Taproot update | python-bitcoinlib | re-scout for primitives |
| First multi-org maker pool request | ChillDKG | ~2-3 week port of `chilldkg_ref` |

---

## Files added this cycle (bitcoin-terminal-exchange/)

```
BTX-secp256k1-zkp-followup-2026-06-03.md
BTX-secp256kfun-FINAL-2026-06-03.md
BTX-bitcoin-bips-FINAL-2026-06-03.md
BTX-bip327-keyagg-finding-2026-06-03.md
BTX-bip340-bip341-foundation-2026-06-03.md
BTX-bip374-dleq-closure-2026-06-03.md
BTX-cross-validation-discipline-2026-06-03.md
BTX-runes-drift-check-2026-06-03.md
BTX-rust-miniscript-scouting-2026-06-03.md
BTX-minisketch-scouting-2026-06-03.md
BTX-utreexo-scouting-2026-06-03.md
BTX-pymatt-scouting-2026-06-03.md
BTX-HWI-scouting-2026-06-03.md
BTX-python-bitcoinlib-scouting-2026-06-03.md
BTX-python-bip380-scouting-2026-06-03.md
BTX-ChillDKG-scouting-2026-06-03.md
BTX-scouting-cycle-summary-2026-06-03.md           (THIS DOC)

btx_halfagg.py                    btx_s2c.py
btx_adaptor.py                    btx_musig2_adaptor.py
btx_musig2.py                     btx_dlc_demo.py
btx_dleq.py                       btx_pool_publish.py
btx_descriptor.py                 btx_s2c_envelope.py
btx_frost.py                      btx_dlc_publish.py
btx_frost_publish.py              btx_xtest_vs_python_bip380.py
btx_artifact_v2_demo.py
btx_xtest_suite.py                (extended +2 sub-tests)
```

Plus various Rust-side ports in brk-btx (halfagg, s2c, MuSig2
KeyAgg + nonce_gen + partial_sign), BTX2 indexer stack
(`btx_v2_*.rs`), threat model expansions, and audit closure docs.

---

## Source

This cycle was run autonomously after the user said
*"im going out for dinner, dont stop working until im back, if
you're done with a repo, go find another one"* on 2026-06-03.

Eleven repos scouted in one continuous session. Each cloning,
reading, and decision recorded in its own scouting doc plus a
git commit.

---

## Post-amendment (12th–14th scouts)

After the 11-scout summary was shipped at commit `5b83912`, the user
returned briefly and said **"keep going"**. Three more scouts were
added:

| # | Target | Outcome | Defer reason |
|---|--------|---------|--------------|
| 12 | `romanz/electrs` | spec only | **architectural-protocol** (NEW: different stack for similar role) |
| 13 | `bitcoin/bips` (BIP-322) | **shipped code** (9th xtest sub-test) | — |
| 14 | `bitcoin/bips` (BIP-388) | spec only | **scope-mismatch** (NEW: BTX descriptors simpler than minimum tier) |

Updated totals after 14 scouts:

- **6 ship / 8 spec** (extraction rate 6/14 ≈ 43%)
- **8 distinct defer-reason categories**: operational,
  architectural-no-use, consensus, product, era, product-timing,
  architectural-protocol, scope-mismatch
- **`btx_xtest_suite`**: 9/9 PASS in ~10s (was 8/8 at 11-scout mark)
- **New code shipped post-11**: `btx_bip322.py` (244 LOC) — BIP-322
  generic signed message foundation, 3/3 PASS on canonical vectors
- **Pattern lesson confirmed**: large multi-BIP repos like
  `bitcoin/bips` can yield multiple ships in one cycle if revisited
  per-BIP. BIP-374 (scout #3) and BIP-322 (scout #13) both shipped.

### Defer-category refinement

The "product-timing" category (ChillDKG: BTX wants this in v1.0) and
the new "scope-mismatch" category (BIP-388: BTX descriptors are too
simple to benefit) were initially conflated. The distinction:

- **product-timing**: feature *will* matter when BTX has more users.
  Implementation is sized, scheduled, and triggered.
- **scope-mismatch**: feature addresses a complexity tier BTX may
  never enter. Bookmarked only as "if BTX's scope changes."

### Final commits (chronological)

```
2668c32 Scouting: BIP-388 Wallet Policies (Ingala) — scope-mismatch
7a45b7a Scouting: BIP-322 (kallewoof) — CODE LANDS
b9040e8 Scouting: romanz/electrs — different protocol stack
5b83912 Cycle summary: 11-repo autonomous scouting cycle
cfb50db Scouting: ChillDKG — v1.0 FROST DKG upgrade roadmap
f79bfd0 Scouting: darosior/python-bip380 — CODE LANDS
72489d3 Scouting: petertodd/python-bitcoinlib — pre-Taproot
8536225 Scouting: bitcoin-core/HWI — hardware-wallet interface
7d6362e Scouting: Merkleize/pymatt — MATT covenants
c8cabc0 Scouting: mit-dci/utreexo — UTXO accumulator
6154743 Scouting: sipa/minisketch — set reconciliation
```

All commits pushed to `bitcoin-terminal-exchange` master.
