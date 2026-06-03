# Scouting report — `mit-dci/utreexo` (Tadge Dryja, MIT-DCI)

*Sixth scouting target this 2026-06-03 cycle. Different domain again:
UTXO accumulator for pruned/light Bitcoin nodes.*

Date: 2026-06-03.

## Why this developer / repo

Tadge Dryja is a Bitcoin researcher at MIT's Digital Currency
Initiative, co-author of the original Lightning Network paper, and the
designer of **UTreexo** — a dynamic hash-based accumulator that lets
Bitcoin nodes verify chain validity with only a few kilobytes of state
instead of the full ~10GB UTXO set.

## Repository at a glance

Cloned to `Bitcoin CoreX/utreexo-reference/`, master HEAD 2026-06-03.

Total: ~13,300 LOC of Go across:

| Module | LOC | Purpose |
|--------|-----|---------|
| `accumulator/` | 7,745 | The core math: Forest (full) + Pollard (partial) accumulators, batch proofs, hash forest |
| `bridgenode/` | 3,927 | Bitcoin Core bridge: reads blocks, maintains the full accumulator, serves proofs |
| `csn/` | 734 | Compact State Node — the verifier that runs with just the Pollard |
| `btcacc/` | 369 | Bitcoin-specific accumulator wrapping |
| `wire/` | 282 | Network protocol for proof distribution |
| `util/` | 223 | Common helpers |
| `cmd/` | (binaries) | utreexoserver + utreexoclient |

## The honest README caveat

From the repo's own top-level README:

> *"This currently is testing/research level code and should not be
> expected to be stable or secure. But it also should work, and if it
> doesn't please report bugs!"*

Same kind of caveat as `secp256kfun`'s README. Worth honouring: any
BTX integration would be against research-grade Go, not production
Bitcoin Core code.

## The data model (from `accumulator/readme.md`)

```
Forest    — full accumulator (every node hashed and stored). Bridge node
            keeps this. Can produce inclusion proofs for any UTXO.

Pollard   — partial accumulator. Like a Merkle-tree summary. Verifies
            inclusion proofs from the Forest. Storage ~constant per
            verifier regardless of total UTXO count.

Modify(adds, dels)        → mutate accumulator with new UTXOs / spends
ProveBatch(leaves)        → emit inclusion proof for a batch of UTXOs
IngestBatchProof(proof)   → verify a batch proof (Pollard side)
```

## Why this isn't a BTX fit today

BTX's architecture **doesn't track UTXOs at all**. The breakdown:

- `brk_indexer` reads Bitcoin Core's chain via RPC and extracts BTX2
  envelope records from transactions. It doesn't maintain an independent
  UTXO set; it doesn't validate script execution.
- The BTX2 order book is a different state: ~36-byte order IDs keyed by
  announce-txid + record index. Sizes range from 0 (mainnet today) to
  thousands eventually.
- BTX clients talk to BTX's HTTP API, not the Bitcoin P2P network
  directly. They trust the BTX indexer, not the UTXO commitment.

For UTreexo's value proposition to materialise for BTX, BTX would have
to add one of:

1. **Trustless light-client mode** — BTX clients verify chain validity
   independently. Today they trust the BTX indexer. Not on the roadmap.
2. **Pruned-indexer mode** — BTX indexer runs without the full UTXO
   set (which is currently provided by the user's Bitcoin Core node,
   not by BTX). Saves disk on the user's *Bitcoin Core* install, not
   on BTX itself.
3. **A peer-to-peer indexer-mesh** with cryptographically-verifiable
   state commitments. Possible BTX3 work, but speculative.

None of those have a current product driver.

## Side note — language barrier

`utreexo` is Go. BTX is Python + Rust. Direct integration would mean
either:

- Building utreexo into the BTX bundle as a subprocess (~80 MB Go
  binary)
- Porting the accumulator math to Python or Rust (~7,500 LOC of careful
  cryptographic engineering)
- Using only the protocol-design ideas (cheap; no code)

Compare with `rust-miniscript` and `sipa/minisketch` (both C/C++ with
clean APIs that ctypes-bind easily) — `utreexo` is a less natural
integration target purely on packaging grounds.

## What could be borrowed at the design level

Three protocol-level ideas in this repo that BTX might apply LATER:

1. **Batch proofs.** UTreexo proves *many* inclusions with shared
   hashes, reducing per-proof bandwidth dramatically. BTX's
   light-client follower (`brk_indexer`'s event-stream subscriber)
   already uses cumulative event hashes (per
   `BTX-cross-validation-discipline-2026-06-03.md` mention); the
   batch-proof aggregation pattern could be borrowed if BTX adds a
   real Merkle commit-and-prove for order book state.

2. **Forest / Pollard split.** Two-tier verifier roles (full
   accumulator vs. light verifier) maps naturally onto BTX
   indexer-server vs. user-client. BTX2 doesn't have a cryptographic
   light-client mode today, but the design is sound.

3. **Undo log for reorgs.** UTreexo's `undo.go` (217 LOC) handles the
   reorg case for a UTXO accumulator. BTX already has its own reorg
   handling (`btx_v2_reorg.rs`) at the order-book level; the patterns
   are different enough that direct extraction doesn't apply, but the
   accumulator-reorg design is a useful reference.

## Verdict

`utreexo` is a beautiful piece of cryptographic engineering with one
production use case (the planned utreexod fork of bitcoind, separate
from this repo). For BTX:

- **No code lands this session.** BTX doesn't have a UTXO accumulator
  problem.
- **Worth bookmarking for BTX3** — if BTX adds a trustless light-client
  mode or a peer-to-peer indexer mesh, UTreexo's design (not its Go
  code) becomes relevant.

This is the **fourth** "no code lands" scouting in the cycle. The
pattern is becoming clearer: as the scouting goes wider, the gap
between what's CRYPTOGRAPHICALLY INTERESTING and what's
PRODUCT-DRIVEN-FOR-BTX-TODAY grows.

| Scouting | Outcome | Reason |
|----------|---------|--------|
| `secp256k1-zkp` | code shipped | Direct primitive fit |
| `secp256kfun` | code shipped | Direct primitive fit (FROST) + spec deferred |
| `bitcoin/bips` | BIP-374 code shipped | Direct primitive fit |
| `rust-miniscript` | code shipped (descriptors) | Found a fit on the simple end after deeper read |
| `sipa/minisketch` | spec only | Operational (build deps) — not architectural |
| **`mit-dci/utreexo`** | **spec only** | **Architectural — no BTX use case** |

## File index

```
Bitcoin CoreX/utreexo-reference/                  (cloned 2026-06-03, master HEAD)
  ├── accumulator/   ~7.7k LOC   Forest + Pollard + batch proofs
  ├── bridgenode/    ~3.9k LOC   bitcoin-core bridge
  ├── csn/             734 LOC   compact state node (verifier)
  ├── btcacc/          369 LOC   bitcoin-specific wrappings
  └── cmd/{utreexoserver, utreexoclient}

bitcoin-terminal-exchange/
  └── BTX-utreexo-scouting-2026-06-03.md          (THIS DOC)
```

## Source

Repo: <https://github.com/mit-dci/utreexo>
Author: Tadge Dryja and MIT-DCI contributors
Examined: master HEAD at clone time 2026-06-03.
Paper: <https://eprint.iacr.org/2019/611> (Dryja, 2019).
