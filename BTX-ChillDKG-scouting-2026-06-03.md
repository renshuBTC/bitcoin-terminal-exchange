# Scouting report — `BlockstreamResearch/bip-frost-dkg` (ChillDKG: Tim Ruffing, Jonas Nick, Sivaram Dhakshinamoorthy)

*Eleventh scouting target this 2026-06-03 cycle. Domain: distributed
key generation (DKG) for FROST. The direct upgrade path for BTX's
current trusted-dealer FROST.*

Date: 2026-06-03.

## Why this developer / repo

Jonas Nick is a Blockstream cryptography engineer, co-author of
MuSig2 (BIP-327, already validated in BTX's xtest suite), and a major
FROST contributor. Tim Ruffing is the BIP-327 co-author and primary
FROST researcher. Together with Sivaram Dhakshinamoorthy, they
authored **ChillDKG**, the BIP-draft distributed key generation
protocol specifically designed for FROST.

For BTX, this is the most direct upgrade path identified in the
entire scouting cycle. BTX's `btx_frost.py` (per memory, Phase A
last session) is **trusted-dealer only** — a single party generates
all `n` secret shares and distributes them. ChillDKG eliminates that
trusted party.

## Repository at a glance

Cloned to `Bitcoin CoreX/frost-dkg-reference/`, master HEAD
2026-06-03.

```
README.md   77,938 bytes   the BIP draft itself
python/
  ├── chilldkg_ref/                     ~2,177 LOC pure-Python
  │   ├── chilldkg.py        998 LOC    main protocol layer
  │   ├── encpedpop.py       480 LOC    encrypted PedPop sub-protocol
  │   ├── simplpedpop.py     438 LOC    simplified PedPop sub-protocol
  │   ├── vss.py             146 LOC    Verifiable Secret Sharing
  │   └── util.py            107 LOC
  ├── secp256k1lab/                     ~603 LOC standalone secp256k1
  │   ├── secp256k1.py       483 LOC    field + group arithmetic
  │   ├── bip340.py           73 LOC    BIP-340 Schnorr sign/verify
  │   ├── ecdh.py             16 LOC    ECDH
  │   ├── util.py             24 LOC    tagged_hash + helpers
  │   └── keys.py             15 LOC
  ├── example.py            305 LOC    end-to-end demo
  ├── tests.py              700 LOC    test harness
  ├── vectors/                          official test vectors
  └── gen_vector_utils/                 vector generators (1606 LOC)
```

Total ~5,717 LOC pure-Python.

## Why this matters for BTX

BTX's current FROST stack (per memory entries
`project_btx_secp256kfun_closure_2026-06-03`):

> *"FROST integrated trusted-dealer + zero-protocol-change
> BATCH_ANNOUNCE"*

Trusted-dealer means: one BTX maker (or a coordinator) holds all
`n` participant secret shares before distributing. If that party is
compromised, all `n` keys are compromised. This is acceptable for
single-organization maker pools (one trading desk running all
participant nodes) but a non-starter for multi-organization pools.

ChillDKG replaces the trusted dealer with an interactive `n`-party
protocol where:

1. Each participant generates and broadcasts a Pedersen polynomial
   commitment.
2. Each participant sends encrypted shares to every other
   participant.
3. Each participant verifies the received shares against the
   commitments.
4. After enough rounds, all participants converge on the same
   threshold public key with no party ever holding all secret
   shares.

ChillDKG specifically adds **abort-and-restart correctness** (if any
participant misbehaves, the protocol detects it and aborts cleanly,
no half-baked state) and **certified consensus** (the threshold key
is published with cryptographic proof of agreement, not just
hand-wave).

Verbatim from the README's abstract:

> *"This Bitcoin Improvement Proposal proposes ChillDKG, a
> distributed key generation protocol (DKG) for use with the FROST
> Schnorr threshold signature scheme."*

## The integration path

### What lands easily today

`secp256k1lab/bip340.py` (73 LOC) is the cleanest BIP-340 reference
seen in the cycle so far. It exposes a `tag_prefix` parameter that
generalises BIP-340 to other Schnorr-tagged variants — for example,
calling it with `tag_prefix="BIP0374"` gives you BIP-374 DLEQ's
Schnorr-like construction.

A 4th BIP-340 oracle is *possible* but marginal: BTX already has
triple-validation (Bitcoin Core CSV + Jonas's bips reference +
internal goldens). Adding Jonas's secp256k1lab as a 4th would
strengthen the BIP-374 tag-prefix variant specifically. Bookmarked
but not shipped this session (diminishing returns).

### What requires a real product effort

ChillDKG integration. Three components:

1. **Port the protocol.** ~2,177 LOC of `chilldkg_ref/`. Pure-Python
   with no external deps (relies only on `secp256k1lab`). Estimate
   2-3 weeks of focused work to integrate cleanly with `btx_frost`
   and add a `btx_chilldkg.py` module.

2. **Add an N-party orchestration harness.** ChillDKG is
   *interactive* — you can't unit-test it standalone. You need
   either:
   - `N` actual nodes communicating over a transport (requires real
     networking)
   - An in-process simulator that drives `N` participant state
     machines and routes messages between them

   Jonas's `python/example.py` (305 LOC) is the in-process
   simulator; it's a starting point but BTX would need to adapt it.

3. **Define the BTX2 envelope that carries the threshold key.**
   BATCH_ANNOUNCE already supports MuSig2-aggregated and
   FROST-aggregated keys. Adding ChillDKG output is a docstring +
   metadata change; no protocol change required.

### Effort vs. value

Today's BTX has **one user** (Renshu) on RenshuBTC mainnet, with
**zero multi-party maker pools** in production. ChillDKG is
optimising a feature that has no users.

For v1.0 — when BTX wants to onboard external maker desks — ChillDKG
becomes the right answer. Until then, trusted-dealer FROST is
operationally adequate.

## Module-by-module value to BTX

| Module | BTX-relevance |
|--------|---------------|
| `chilldkg_ref/chilldkg.py` (998 LOC) | **v1.0 upgrade path** — trustless FROST DKG |
| `chilldkg_ref/encpedpop.py` (480 LOC) | sub-protocol; ports together with chilldkg.py |
| `chilldkg_ref/simplpedpop.py` (438 LOC) | sub-protocol; ports together |
| `chilldkg_ref/vss.py` (146 LOC) | Pedersen VSS primitive — could ship standalone for educational xtest |
| `secp256k1lab/bip340.py` (73 LOC) | 4th BIP-340 oracle (marginal — bookmark only) |
| `secp256k1lab/secp256k1.py` (483 LOC) | Schnorr arithmetic — already covered by BTX's own |
| `python/example.py` (305 LOC) | reference orchestration harness; useful template |
| `tests.py` (700 LOC) | test vectors — useful when integrating |

## Verdict — defer with concrete roadmap

ChillDKG is the canonical FROST-DKG and the right answer for BTX's
v1.0+ multi-organization maker pools. For BTX's current single-user
mainnet scope, the trusted-dealer FROST shipped last session is
operationally adequate.

**No code lands this session.** This is the third "right tool, wrong
timing" outcome — the others being the secp256kfun cross-curve DLEQ
(secp256kfun scouting, Phase C: design spec only) and pymatt's MATT
covenants (consensus-dependent).

The unique value of this scouting: a **clear sequenced plan** for
when ChillDKG becomes load-bearing. The integration effort is bounded
(~2-3 weeks), the test path is bounded (orchestration harness +
official vectors), and the BTX2 envelope-side change is zero.

## Trigger conditions for actually shipping the integration

| Trigger | Justification |
|---------|---------------|
| First multi-org maker pool requests trustless key generation | Trusted-dealer is a hard "no" for unaffiliated desks |
| BTX2 promotes BATCH_ANNOUNCE to first-class with external participants | ChillDKG is the dependency to make BATCH_ANNOUNCE auditable |
| Bitcoin community settles on FROST + ChillDKG as the canonical pair | Coordination with the BIP draft once finalized |

## Pattern across 11 scouts

| Repo | Outcome | Reason |
|------|---------|--------|
| `secp256k1-zkp` | shipped | primitive fit |
| `secp256kfun` | shipped FROST + specced DLEQ | primitive fit + design extraction |
| `bitcoin/bips` | shipped BIP-374 DLEQ | primitive port |
| `rust-miniscript` | shipped descriptors | found fit after deeper read |
| `sipa/minisketch` | spec only | operational |
| `mit-dci/utreexo` | spec only | architectural |
| `Merkleize/pymatt` | spec only | consensus-dependent |
| `bitcoin-core/HWI` | spec only | product-driven |
| `petertodd/python-bitcoinlib` | spec only | era mismatch |
| `darosior/python-bip380` | shipped cross-test | second oracle for prior work |
| **`BlockstreamResearch/bip-frost-dkg` (ChillDKG)** | **spec only + roadmap** | **product timing — v1.0 upgrade** |

Extraction rate: 5/11 ≈ 45%.

The deferred half now spans 6 distinct categories:
- operational (build deps)
- architectural (no use case)
- consensus-dependent (CCV not active)
- product-driven (no hardware user)
- era mismatch (pre-Taproot)
- product timing (v1.0 upgrade) — **NEW this scouting**

## File index

```
Bitcoin CoreX/frost-dkg-reference/                          (cloned 2026-06-03)
  ├── python/chilldkg_ref/                                   ~2,177 LOC ChillDKG
  ├── python/secp256k1lab/                                   ~603 LOC secp256k1
  ├── python/example.py                                      305 LOC orchestration
  ├── python/tests.py                                        700 LOC tests
  └── README.md                                              77,938 byte BIP draft

bitcoin-terminal-exchange/
  └── BTX-ChillDKG-scouting-2026-06-03.md                    (THIS DOC)
```

## Source

Repo: <https://github.com/BlockstreamResearch/bip-frost-dkg>
Authors: Tim Ruffing, Jonas Nick, Sivaram Dhakshinamoorthy
License: BIP doc CC0-1.0; code MIT
Examined: master HEAD at clone time 2026-06-03.
BIP status: Draft.
Related: BTX's current `btx_frost.py` is trusted-dealer per Phase A
last session. ChillDKG is the named v1.0 upgrade.
