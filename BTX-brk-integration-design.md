# Wiring `index_block_brk` into BRK's indexing loop — design & options

Status: `mod btx;` is in `brk_indexer/src/lib.rs` and compiles; `index_block_brk` is defined but
**not called**. This doc picks where it hooks in, how the order book persists, and how it stays
correct under reorgs. It's a design decision (touches the hot path), so it's written for review
rather than applied blind.

## 1. Hook point (in `Indexer::index_`, `lib.rs`)

The block loop is `for block in reader.after(prev_hash)?.iter() { ... }`. Each iteration:
constructs a `BlockProcessor`, runs `process_block_metadata` → `compute_txids` →
`process_inputs`/`process_outputs` → `finalize_and_store_metadata` → `lengths.add_block(...)` →
periodic `export`.

**Call site:** immediately after `finalize_and_store_metadata(...)` succeeds and before the
`is_export_height` block — the block is fully validated/indexed at that point, and `client` and
`block`/`height` are all in scope:

```rust
// after: processor.finalize_and_store_metadata(...)?;
btx::index_block_brk(&mut btx_book, &btx::BrkChain { client }, &block, u32::from(height));
```

`btx_book` must outlive the loop — see persistence below. `client: &brk_rpc::Client` is the
`index_` parameter; `BrkChain::offer_utxo` calls `client.get_tx_out`, which is a Bitcoin Core RPC
round-trip per *candidate* order (only txs that contain a `BTX1` artifact), so the cost is
negligible on normal blocks.

## 2. The historical-orders problem (the real decision)

`index_block_brk` only sees blocks processed *in this `index()` call*. BRK resumes indexing from
the last stored height, so a freshly-started process would replay only new blocks — it would
**not** see orders opened in blocks indexed on a previous run. Three ways to handle it:

### Option A — In-memory, rebuilt by full re-scan on startup (simplest, prototype-grade)
Keep `OrderBook` in memory; on process start, scan all blocks once (or from the rune's etch
height) to rebuild open orders, then maintain incrementally. **Pro:** no new storage, no schema.
**Con:** O(chain) rebuild on every start; not viable once the chain is large. Fine for a regtest/
signet prototype, not production.

### Option B — Persist in a fjall `Store` (recommended for production)
Model open orders like BRK already models unspent outpoints
(`addr_type_to_addr_index_and_unspent_outpoint`): a `Store<OutPoint, OrderRecord>` keyed by the
offer outpoint, written when an order opens and removed/updated on fill/cancel/expire. This rides
BRK's existing commit/rollback machinery (`stores.commit(height)`, `rollback_if_needed`), so
persistence and reorg-safety come almost for free and match the codebase's idioms. **Pro:**
durable, incremental, reorg-aligned. **Con:** a new store + (de)serialization for `OrderRecord`;
the most code.

### Option C — Derive on demand in `brk_query` (no indexer state at all)
Don't keep a book in the indexer; expose a query that scans recent blocks / an artifact index and
reconstructs open orders when asked. **Pro:** zero hot-path change, zero new mutable state.
**Con:** every query re-scans; needs at least an index of which txouts carry `BTX1` (could reuse
the existing `OpReturn` script vec + a filter).

**Recommendation:** prototype with **A** (you've already proven the logic), ship with **B** — it
slots into BRK's `Stores`/`Vecs` pattern and inherits rollback. C is attractive only if you want
the indexer to stay strictly append-only and push order-book state entirely into the query layer.

## 3. Reorg consistency (must-do for A and B if kept incrementally)

BRK rolls back at the **start** of `index_` via `stores.rollback_if_needed(&mut vecs,
&starting_lengths)` and `vecs.rollback_if_needed(...)`, using `starting_lengths.height` derived
from the last common block. Wherever that happens, the order book must do the matching
`btx_book.revert_to(starting_lengths.height)` (Option A) or be rolled back by the same store
mechanism (Option B). The `revert_to` logic is already implemented and unit-tested: it drops
orders announced above the height and re-opens fills/cancels recorded above it.

## 4. Fee / expiry / partial-fill (separate from wiring)
- **Expiry** is handled (`OrderBook::expire(height)` runs each block in `index_block_brk`).
- **Partial fills** are out of scope for v1 (the offer UTXO is taken whole). Supporting them means
  the offer can be split across multiple takes — a protocol change to the artifact (min-fill,
  remainder handling), not just indexer work. Decide before, not during, wiring.
- **Fee** for the swap is the taker's concern (they build the completing tx); the indexer only
  observes. No indexer change needed.

## 5. Concrete next step
If you want **A** (prototype): add `let mut btx_book = btx::OrderBook::new();` before the loop and
the one call after `finalize_and_store_metadata`, plus a `btx_book.revert_to(starting_lengths
.height)` next to the existing rollback. ~5 lines, compile-checkable immediately, with the
known historical-orders caveat.
If **B** (production): define `OrderRecord` + a `Store<OutPoint, OrderRecord>` in `Stores`, write
on open / remove on resolve, and let `commit`/`rollback_if_needed` carry it. ~a focused session.

---

## Option B implementation notes (researched 2026-05-23, ready to execute)

`brk_store::Store<K,V>` bounds (from `brk_store/src/lib.rs`):
`K: Debug + Clone + From<ByteView> + Ord + Eq + Hash`, `V: Debug + Clone + From<ByteView>`,
`ByteView: From<K> + From<V>`. So **values may be variable-length** (ByteView is an arbitrary
byte buffer) — the BTX order record (incl. variable `payout_spk`/sig) can be stored directly,
e.g. value = the serialized BTX artifact bytes.

- **Key:** the offer outpoint. Two choices: (a) reuse `brk_types::OutPoint` (= `TxIndex`+`Vout`),
  which means mapping the artifact's *bitcoin* txid → BRK `TxIndex` via `txid_prefix_to_tx_index`
  at index time (the funding tx is already indexed by then); or (b) a new 36-byte key newtype over
  the raw bitcoin outpoint (txid||vout) with `From<ByteView>`/`Into<ByteView>` impls mirroring how
  `AddrIndexOutPoint` does it in `brk_types`. (a) is more BRK-idiomatic and rollback-friendly.
- **Store config:** `Mode::Any` (needs insert + remove, like
  `addr_type_to_addr_index_and_unspent_outpoint`), `Kind::Vec` or `Kind::Random`.
- **Register in `Stores` (stores.rs) in ALL of:** the struct field, `forced_import` (via
  `Store::import`), `iter_any`, `par_iter_any_mut` (so `commit` covers it automatically),
  `take_all_pending_ingests`, and `is_empty`.
- **Write path:** in `btx::index_block_brk`, on a validated new order `store.insert(key, record)`;
  on a resolved spend (fill/cancel) `store.remove(key)` (or insert a tombstoned status if you want
  to keep history).
- **Rollback (the careful part):** add an order-book rollback in `Stores::rollback_if_needed`,
  alongside `rollback_outputs_and_inputs`, that walks blocks above `starting_lengths.height` and
  (i) removes orders announced above the bound and (ii) re-opens orders whose offer UTXO was spent
  above the bound. Mirror the outpoint walk already in `rollback_outputs_and_inputs`. This replaces
  the in-memory `OrderBook::revert_to`.
- **Query:** expose open orders via `brk_query` by scanning the store (or add a typed read path).

**Effort:** one focused session; compile-check loop in WSL is ~5s so iteration is cheap. Do it as
its own pass with a regtest reorg test (`invalidateblock`) to prove the rollback path.
