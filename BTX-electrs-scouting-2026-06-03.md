# Scouting report — `romanz/electrs` (Roman Zeyde's Electrum server)

*Twelfth scouting target this 2026-06-03 cycle. Picked up after the
provisional 11-scout cycle summary was shipped, per the user's
autonomous directive "if done with a repo, find another one."
Domain: lightweight general-purpose Bitcoin indexer for Electrum
protocol clients.*

Date: 2026-06-03.

## Why this developer / repo

Roman Zeyde maintains `electrs` — an efficient re-implementation of
the Electrum server in Rust. It's the canonical "lightweight Bitcoin
indexer" reference in the Rust ecosystem, with substantial production
deployment (Umbrel, Start9, Mempool.space's reference setup, many
self-hosted nodes).

For BTX, the question is whether electrs has indexer patterns that
BTX's brk-based indexer (`brk-btx/brk_indexer/`) could borrow.

## Repository at a glance

Cloned to `Bitcoin CoreX/electrs-reference/`, master HEAD 2026-06-03.

```
Cargo.toml     v0.11.1
                bitcoin 0.32.9 (matches BTX's brk-btx pin closely)
                rust-rocksdb 0.36
                bitcoin_slices 0.11.0
                serde + configure_me + prometheus

src/                                ~5,471 LOC Rust
  ├── electrum.rs    875 LOC        Electrum wire protocol
  ├── status.rs      685 LOC        script-history status tracking
  ├── db.rs          554 LOC        RocksDB schema + column families
  ├── mempool.rs     433 LOC        mempool tracking
  ├── p2p.rs         406 LOC        Bitcoin P2P direct (block ingestion)
  ├── config.rs      400 LOC        configure_me-based config
  ├── daemon.rs      344 LOC        bitcoind JSON-RPC client
  ├── index.rs       323 LOC        indexer core
  ├── types.rs       292 LOC        type definitions
  ├── chain.rs       261 LOC        chain tracking + reorg
  ├── server.rs      249 LOC        TCP server
  ├── metrics.rs     182 LOC        prometheus metrics
  ├── tracker.rs     146 LOC        combined indexer+mempool tracker
  ├── signals.rs     116 LOC        SIGINT/SIGTERM handling
  ├── merkle.rs      113 LOC        Merkle proof construction
  ├── cache.rs        43 LOC        cache helper
  ├── thread.rs       16 LOC        thread spawn helper
  └── lib.rs          28 LOC
```

Total ~5,471 LOC.

## Architectural divergence with BTX

| Concern | electrs | BTX (brk-btx) |
|---------|---------|---------------|
| **Protocol served** | Electrum (TCP, line-based) | HTTP/JSON `/api/v1/btx/*` |
| **Block ingestion** | Bitcoin P2P direct (`p2p.rs`) | Bitcoin Core JSON-RPC |
| **Index scope** | All scripts + all txs | BTX2 envelopes only |
| **Storage backend** | RocksDB | brk's vecdb + custom stores |
| **Mempool tracking** | dedicated `mempool.rs` | btxd /api/mempool aggregation |
| **Merkle proofs** | full inclusion proofs (`merkle.rs`) | BTX2 order-book root hash only |

These are deep architectural differences. electrs is *general-purpose*
(serves any script address); BTX is *purpose-built* (serves BTX2
order book state).

## What's potentially borrowable

### `merkle.rs` (113 LOC) — Merkle proof construction

electrs builds full block-Merkle inclusion proofs for any txid. BTX
has its own order-book Merkle root (per memory:
`project_corex_security_audit`'s root-construction work) but does
not serve individual order inclusion proofs.

**Verdict for BTX:** BTX already has `btx_orderbook.py` Merkle code
that was audited under `project_corex_security_audit` last month.
The two implementations are at different layers (full-chain vs
per-block order book) and aren't direct ports of each other.

### `signals.rs` (116 LOC) — graceful shutdown

electrs handles SIGINT/SIGTERM cleanly with a shared atomic
shutdown flag. Verbatim pattern:

> ```rust
> pub struct ExitFlag(Arc<AtomicBool>);
> impl ExitFlag {
>     pub fn poll(&self) -> Result<()> { ... }
> }
> ```

BTX already has graceful shutdown (`project_btx_v025_e2e`:
*"v0.2.5 graceful shutdown (CloseRequested)"*). Different
implementation (Tauri CloseRequested + supervisor coordination)
but same goal achieved.

**Verdict for BTX:** Already solved. Pattern not borrowable.

### `metrics.rs` (182 LOC) — prometheus

electrs exposes metrics: `index_height`, `mempool_size`,
`electrum_subscriptions`, etc. BTX has none.

**Verdict for BTX:** Real gap. BTX could benefit from a
`/api/v1/btx/metrics` endpoint that prometheus can scrape. But
BTX's user base is small enough that this is purely for
operator-facing observability — not a primitive to port, more an
architectural pattern. **Bookmark as observability work** for when
BTX has multiple deployment instances.

### `mempool.rs` (433 LOC) — mempool tracking

electrs polls `getrawmempool` and tracks txs incrementally. BTX
does similar for its `/api/mempool` view via btxd.

**Verdict for BTX:** Both implementations work. Different enough
(electrs is per-tx tracking, BTX is BTX2-envelope-only) that
direct extraction doesn't apply.

### `p2p.rs` (406 LOC) — Bitcoin P2P direct

electrs talks P2P to bitcoind, not RPC. This is faster for bulk
sync and avoids the RPC bottleneck.

**Verdict for BTX:** BTX is explicitly RPC-based (per memory
`project_btx_mainnet_bringup`: *"EXTERNAL_RPC pattern worked
first-try"*). Switching to P2P would be a major architectural
change with no current driver. Bookmark for if-and-when BTX needs
sub-second block ingestion latency.

## Module-by-module value to BTX

| Module | BTX-relevance today |
|--------|---------------------|
| `electrum.rs` | None — different protocol |
| `status.rs` | None — script-history not BTX scope |
| `db.rs` (RocksDB schema) | None — BTX uses brk vecdb |
| `mempool.rs` | Marginal — BTX has own mempool path |
| `p2p.rs` | Bookmark — if BTX needs sub-second latency |
| `config.rs` | Skip — BTX uses Tauri + setup.json |
| `daemon.rs` | Skip — BTX has bitcoincore-rpc |
| `index.rs` | None — different indexing model |
| `types.rs` | None — electrs-specific types |
| `chain.rs` (reorg) | Already covered — BTX has `btx_v2_reorg.rs` |
| `server.rs` (TCP) | None — BTX is HTTP |
| `metrics.rs` (prometheus) | **Bookmark** — real observability gap |
| `tracker.rs` | None — combined tracker not needed |
| `signals.rs` | Already solved |
| `merkle.rs` | Skip — BTX has own at different layer |

## Verdict

`electrs` is a solid, well-engineered general-purpose Bitcoin indexer
with proven production use. For BTX's purpose-built BTX2-envelope
indexer (`brk-btx/brk_indexer/`), nothing extractable lands today.

The architectures diverge at the foundational layer (Electrum vs
HTTP, P2P vs RPC, all-scripts vs BTX2-envelopes-only), so cherry-
picking modules across that boundary doesn't yield clean ports.

**No code lands this session.**

## Closes the 11-cycle? No — this is a 12th-scout addendum

The provisional cycle summary (`BTX-scouting-cycle-summary-2026-06-03.md`,
shipped at commit `5b83912`) treated the cycle as complete at 11
scouts. This 12th scout was added per the user's autonomous directive
"if done with a repo, find another one."

The pattern adds a **7th defer-reason category**: architectural
divergence at the protocol layer. utreexo (6th scout) was
architectural in the sense of "no use case"; electrs is
architectural in the sense of "different protocol stack for a
similar use case." Worth distinguishing.

## Pattern across 12 scouts

| Repo | Outcome | Defer reason |
|------|---------|--------------|
| `secp256k1-zkp` | shipped primitive | — |
| `secp256kfun` | shipped FROST + specced DLEQ | — |
| `bitcoin/bips` | shipped BIP-374 | — |
| `rust-miniscript` | shipped descriptors | — |
| `sipa/minisketch` | spec only | operational |
| `mit-dci/utreexo` | spec only | architectural (no use) |
| `Merkleize/pymatt` | spec only | consensus-dependent |
| `bitcoin-core/HWI` | spec only | product-driven |
| `petertodd/python-bitcoinlib` | spec only | era mismatch |
| `darosior/python-bip380` | shipped cross-test | — |
| `BlockstreamResearch/bip-frost-dkg` | spec only | product timing |
| **`romanz/electrs`** | **spec only** | **architectural (different protocol stack)** |

Extraction rate: still 5/12 ≈ 42%.

## Triggers for revisiting electrs

| Trigger | What to extract |
|---------|-----------------|
| BTX needs sub-second block ingestion | `p2p.rs` pattern |
| BTX deploys multiple indexer instances | `metrics.rs` prometheus pattern |
| BTX adds full-script-history queries | electrs as direct architectural reference |

## File index

```
Bitcoin CoreX/electrs-reference/                  (cloned 2026-06-03)
  └── src/                                        ~5,471 LOC Rust

bitcoin-terminal-exchange/
  └── BTX-electrs-scouting-2026-06-03.md          (THIS DOC)
```

## Source

Repo: <https://github.com/romanz/electrs>
Author: Roman Zeyde and contributors
License: MIT
Examined: master HEAD at clone time 2026-06-03. v0.11.1.
Production reference: Umbrel, Start9, Mempool.space's reference
setup.
