# BTX2 store wiring — follow-up scope (2026-06-04)

**Context.** The session that landed the BTX2 HTTP API (brk-btx `8b08c83`,
`7eb3510`) deliberately stopped short of wiring the `Btx2Store` into
the persistent `Stores` struct on the `Indexer`. Reason: there are 30
call sites that construct `Indexer`, mostly tests, and changing its
field surface mid-session with the recurring sandbox mount-lag would
be a high-risk landing for the end of a long working day.

This doc captures the exact remaining work so the next session is
mechanical. The conversion helper `Btx2OrderView::from_indexer` is
already in place (brk-btx commit `_______`); plug-in points are
flagged with `TODO(btx2-wire)` markers in the codebase.

## What needs to change

### 1. `crates/brk_indexer/src/stores.rs`

Add a `Btx2Store` field to `Stores`:

```rust
pub struct Stores {
    pub btx_orders: BtxStore,  // existing BTX1
    pub btx2_orders: Arc<RwLock<Btx2Store>>,  // NEW
    // ... other existing fields ...
}

impl Stores {
    pub fn forced_import(path: &Path, version: Version) -> Result<Self> {
        // existing code...
        Ok(Self {
            btx_orders: BtxStore::forced_import(...)?,
            btx2_orders: Arc::new(RwLock::new(Btx2Store::new())),  // NEW
            // ...
        })
    }
}
```

For the MVP `Btx2Store` stays in-memory and starts empty at boot.
Persistence (so the store survives restarts) is a separate task; for
now the driver loop will refill it on startup by replaying any
unconfirmed BTX2 envelopes from the existing record stream.

### 2. `crates/brk_query/src/impl/btx2.rs`

Replace each of the 8 stub Query methods with reads from the new field:

```rust
use brk_indexer::btx_v2_query;

impl Query {
    pub fn btx2_open_orders(&self) -> Result<Vec<Btx2OrderView>> {
        let store = self.indexer().stores.btx2_orders.read();
        let internal = btx_v2_query::list_open(&store);
        let mut out: Vec<Btx2OrderView> = internal
            .iter()
            .take(MAX_BTX2_SERVED_ROWS)
            .map(Btx2OrderView::from_indexer)
            .collect();
        Ok(out)
    }
    // ... same shape for btx2_get_order, btx2_conditional_orders, etc.
}
```

The `from_indexer` converter (already shipped) handles all the field
translation including the 36-byte hex `OrderId` encoding.

### 3. `crates/brk_indexer/src/btx_v2_driver.rs` (optional in this round)

The driver already produces `OrderMetadata` updates per block; it just
needs to write them into the new `btx2_orders` field instead of (or in
addition to) wherever it writes today. This is a 10–20 LOC change in
`run_block` / `step`.

If the driver doesn't get wired in this round, the API still works —
it just returns an empty book until something populates the store.
That's acceptable for the frontend MVP because the frontend handles
the empty case explicitly ("No open orders" view in
`btx-web/src/components/OrderBook.tsx`).

### 4. `crates/brk_query/src/impl/btx2.rs` — state_root + health

Replace the stubs:

```rust
pub fn btx2_state_root(&self) -> Result<Btx2StateRoot> {
    let store = self.indexer().stores.btx2_orders.read();
    let root = brk_indexer::btx_v2_root::compute_root(&store);  // already exists
    Ok(Btx2StateRoot {
        root_hex: hex(&root),
        height: u32::from(self.height()),
        block_hash: self.indexer().tip_blockhash().to_string(),
    })
}
```

`btx_v2_root::compute_root` (or equivalent) already exists per
memory `project_btx_v2_stack_2026-06-02`.

### 5. Test the empty-store path

```rust
#[test]
fn btx2_endpoints_return_empty_on_fresh_store() {
    let q = make_test_query();
    assert!(q.btx2_open_orders().unwrap().is_empty());
    assert_eq!(q.btx2_stats().unwrap().total, 0);
    let root = q.btx2_state_root().unwrap();
    assert_eq!(root.root_hex.len(), 64);  // 32 bytes hex
}
```

## Why this can ship without touching 30 test sites

The 30 `Indexer::forced_import` call sites don't pass the `Stores`
struct directly; they let `forced_import` construct it. Adding a new
field that initializes via `Btx2Store::new()` is fully internal —
existing tests don't change unless they explicitly probe `stores`
state (none do for BTX2 today).

The single explicit change touching test fixtures is if the existing
`Stores::forced_import` has a stricter signature; verify by `cargo
check` after step 1 alone.

## Estimated time

- Step 1: ~30 minutes (single file edit + verify all crates compile)
- Step 2: ~45 minutes (replace 8 stub methods)
- Step 4: ~15 minutes (state root + health, if `compute_root` exists)
- Step 5: ~30 minutes (integration test + verify)
- Step 3: 1–2 hours if the driver wiring is bundled in this round;
  defer if pressed for time

Total minimum to make the API non-stub-y: **~2 hours**. Full
end-to-end with driver wiring: **~3-4 hours**.

## What the frontend gets when this lands

Once steps 1+2+4 ship, the btx-web orderbook page stops showing the
empty state and starts displaying real BTX2 orders pulled from the
indexer. The transparency page shows a real state root. The whole
thing becomes useful end-to-end on signet/mainnet.

## Cross-links

- Build plan: `BTX-frontend-architecture-2026-06-04.md` §3 + §8 (week 1-2)
- Conversion helper: `crates/brk_query/src/impl/btx2.rs::Btx2OrderView::from_indexer`
- Stub markers: grep for `TODO(btx2-wire)` in the same file
- Memory anchor: `[[project-brk-btx-btx2-api-2026-06-04]]` (to be written
  when this work lands)

---

*Authored 2026-06-04 after the btx2 HTTP API + POST /broadcast + Next.js
scaffold landed. The conversion helper shipped in this session; the
remaining store wiring is documented here so the next pickup is
mechanical.*
