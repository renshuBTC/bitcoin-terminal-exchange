# Scouting report — `Merkleize/pymatt` (Salvatore Ingala's covenant framework)

*Seventh scouting target this 2026-06-03 cycle. Domain: Bitcoin
covenants via OP_CHECKCONTRACTVERIFY (CCV / BIP-443).*

Date: 2026-06-03.

## Why this developer

Salvatore Ingala (@bigspider) is the proposer of **MATT — Merkleize All
The Things** — a covenant design that uses a single opcode
(`OP_CHECKCONTRACTVERIFY`) to enable general-purpose stateful Bitcoin
smart contracts. Salvatore is at Ledger; co-authored MuSig2 BIP-327 work
(already validated in `BTX-bip327-keyagg-finding-2026-06-03.md`).

`pymatt` is his Python reference implementation of MATT contracts for
the `bitcoin-inquisition` regtest. The repo's own README says **WIP
Work In Progress framework**.

BTX's watchlist tracks covenants (per memory
`project_btx_watchlist_refresh`: *"OP_VAULT BIP-345 WITHDRAWN (May
2025) → BIP-443 CCV"*). So this is the canonical reference for the
post-OP_VAULT covenant path BTX is forward-watching.

## Repository at a glance

Cloned to `Bitcoin CoreX/pymatt-reference/`, master HEAD 2026-06-03.

```
pyproject.toml
LICENSE                            (CC0-1.0 — public domain dedication)
README.md                          install + run-on-regtest instructions
src/matt/
  ├── __init__.py                  flag constants (CCV_FLAG_CHECK_INPUT etc.)
  ├── argtypes.py                  contract argument types
  ├── contracts.py                 main MATT contract abstraction
  ├── environment.py               regtest runner / bitcoin-inquisition harness
  ├── btctools/                    Bitcoin primitives (PSBT, script, segwit, key)
  └── hub/fraud.py                 fraud-proof helpers
examples/
  ├── vault/                       OP_VAULT-style covenant (the canonical demo)
  ├── ram/                         RAM-like state machine via covenant chain
  ├── rps/                         rock-paper-scissors via commitment + covenant
  └── game256/                     generic 2-player game framework
tests/
  ├── test_vault.py     (215 LOC)
  ├── test_fraud.py     (277 LOC)
  ├── test_minivault.py (193 LOC)
  ├── test_ram.py       (92 LOC)
  └── test_rps.py       (53 LOC)
docs/
  ├── matt.md                      MATT design overview
  ├── checkcontractverify.md       CCV opcode spec
  └── contracts.md                 contract-design walk-through
```

Total ~12k LOC of Python.

## The hard prerequisite

From the README:

> *"Run bitcoin-inquisition MATT in regtest mode … The fastest way to
> get started is this docker container … bigspider/bitcoin_matt …
> Alternatively, build the same yourself from this branch:
> Merkleize/bitcoin/tree/inq-ccv."*

The `OP_CHECKCONTRACTVERIFY` opcode is **not in any mainnet release of
Bitcoin Core**. It exists only on Salvatore's `bitcoin-inquisition`
branch — a soft-fork testbed. BTX makers cannot use MATT contracts on
mainnet today.

This is the same blocker I'd note for BIP-119 CTV (deferred in
`BTX-bitcoin-bips-FINAL-2026-06-03.md` for the same reason): no
consensus activation, no consumer wallets, no on-chain liquidity.

## What MATT could give BTX (if CCV ever activates)

A taste from the examples directory:

- **`vault/`** — Maker funds escrowed in a vault that requires either a
  cooldown + recovery key OR a successful trade. Useful for institutional
  makers wanting "if anything goes wrong, my funds claw back to a cold
  key in 7 days."
- **`ram/`** — A state machine encoded on-chain. For BTX, this could
  power *multi-phase orders* (e.g., "open for 24h at price X, then
  auto-discount 1% / hour until filled or expired").
- **`rps/`** — Two-party commit-reveal with a referee covenant. Could
  underpin a trustless atomic-swap referee for cross-chain BTX2 orders.
- **`game256/`** — Generic 2-player game framework. Equivalent to "you
  can encode any 2-party state machine on-chain via covenants."

All of this is the **post-CCV-activation** BTX3 product surface. None
of it ships today.

## Module-by-module assessment for BTX TODAY

| Module | BTX-relevance today |
|--------|---------------------|
| `matt.contracts` (the main covenant framework) | **None** — CCV not active on mainnet |
| `matt.argtypes` | **None** — contract argument types specific to CCV |
| `matt.environment` (regtest runner) | **None** — needs bitcoin-inquisition |
| `matt.btctools.script` | Skip — BTX already has equivalents in btx_taproot |
| `matt.btctools.psbt` | Skip — BTX has its own minimal PSBT support |
| `matt.btctools.key` / `segwit_addr` / `ripemd160` | Skip — BTX has these primitives or doesn't need them |
| `matt.hub.fraud` | Bookmark — fraud-proof patterns could inform BTX3 dispute resolution if CCV lands |

One small thing I noticed: `src/matt/__init__.py` exports a `NUMS_KEY`:

```python
NUMS_KEY: bytes = bytes.fromhex("50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0")
```

This is the **same NUMS x-only** I used as one of BTX's golden vectors
in `btx_descriptor.py` (vector 1). The fact that an independent author
chose the same NUMS construction (per BIP-341 §3 unspendable key
recommendation) is a small cross-validation of the canonical NUMS
construction — not a real finding, just a coincidence worth noting.

## Verdict — defer + bookmark

**No code lands this session.** Same conclusion as BIP-119 CTV and
utreexo: the underlying soft-fork isn't on mainnet, so the design space
is purely forward-looking.

Trigger conditions for revisiting:

1. **CCV activates on mainnet** (no near-term plausibility — BIP-443
   is still draft)
2. **BTX adopts BTX3 with multi-phase / state-machine orders**
3. **A maker desk requests vault-style escrow for offered funds**

Pattern across the 7 scouted repos so far:

| Repo | Outcome | Reason |
|------|---------|--------|
| `secp256k1-zkp` | code shipped | direct primitive fit |
| `secp256kfun` | FROST shipped | direct primitive fit + DLEQ specced |
| `bitcoin/bips` | BIP-374 DLEQ shipped | direct primitive fit |
| `rust-miniscript` | `btx_descriptor.py` shipped | found simple-end fit after deeper read |
| `sipa/minisketch` | spec only | operational (build deps) |
| `mit-dci/utreexo` | spec only | architectural (no UTXO use case) |
| **`Merkleize/pymatt`** | **spec only** | **dependent soft-fork not active** |

The session's effective extraction rate has settled into ~50% (the
crypto-primitive end shipped; the script-policy / accumulator / covenant
ends bookmarked).

## File index

```
Bitcoin CoreX/pymatt-reference/                    (cloned 2026-06-03)
  ├── src/matt/                                    ~12k LOC framework
  ├── examples/{vault, ram, rps, game256}          canonical MATT demos
  ├── tests/                                       ~1k LOC pytest
  └── docs/{matt.md, checkcontractverify.md, contracts.md}

bitcoin-terminal-exchange/
  └── BTX-pymatt-scouting-2026-06-03.md            (THIS DOC)
```

## Source

Repo: <https://github.com/Merkleize/pymatt>
Author: Salvatore Ingala (@bigspider) and Merkleize contributors
License: CC0-1.0 (public domain)
Examined: master HEAD at clone time 2026-06-03.
Prerequisites: bitcoin-inquisition (Merkleize/bitcoin tree inq-ccv branch).
