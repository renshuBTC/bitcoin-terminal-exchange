# E4 — walk-back unit test feasibility scoping (no implement)

*Per `BTX-mainnet-readiness-2026-05-31.md` E4: the `find_recognized_ancestor`
algorithm in `brk_indexer/src/lib.rs:458-532` has no unit test. The audit
described this as requiring "moderate refactor cost" because `brk_rpc::Client`
is a concrete struct. This doc scopes the actual cost — turns out to be
**smaller than estimated**.*

## What `find_recognized_ancestor` actually uses from the Client

Reading lines 458-532 in detail, the function calls exactly ONE method on
the client:

```rust
client.recognizes_block(&hash)?     // line 467 (first check)
client.recognizes_block(&h)?        // line 498 (exponential backoff loop)
client.recognizes_block(&mh)?       // line 520 (binary search refine)
```

That is the entire client surface area for this algorithm. No
`get_block`, no `get_block_header`, no `get_last_height`. Just one method
returning `Result<bool>`.

## Minimal trait + impl

```rust
// In brk_rpc or wherever Client lives:
pub trait BlockHashRecognizer {
    fn recognizes_block(&self, hash: &BlockHash) -> brk_error::Result<bool>;
}

impl BlockHashRecognizer for brk_rpc::Client {
    fn recognizes_block(&self, hash: &BlockHash) -> brk_error::Result<bool> {
        brk_rpc::Client::recognizes_block(self, hash)
    }
}
```

That's ~10 lines.

## Signature change to find_recognized_ancestor

```rust
// BEFORE
fn find_recognized_ancestor(
    &self,
    client: &Client,
    tip: BlockHash,
) -> Result<Option<BlockHash>> { … }

// AFTER
fn find_recognized_ancestor<C: BlockHashRecognizer>(
    &self,
    client: &C,
    tip: BlockHash,
) -> Result<Option<BlockHash>> { … }
```

`find_recognized_ancestor` is `fn` (private), not `pub fn`. Its only call
site is `index_()` at lib.rs:187. The call passes the existing `client: &Client`
which already implements the new trait via the impl above, so the call site
needs no change.

## Mock + test harness

```rust
struct MockClient {
    // Map from BlockHash -> bool (recognized or not). Empty map = nothing recognized.
    recognized: std::collections::HashMap<BlockHash, bool>,
    // For tracking RPC count in assertions:
    calls: std::cell::Cell<usize>,
}

impl BlockHashRecognizer for MockClient {
    fn recognizes_block(&self, hash: &BlockHash) -> brk_error::Result<bool> {
        self.calls.set(self.calls.get() + 1);
        Ok(*self.recognized.get(hash).unwrap_or(&false))
    }
}
```

Plus a small helper that builds an `Indexer` with a synthetic `vecs.blocks.blockhash`
vec containing N hashes — that's the trickiest part because `Vecs` has its
own setup. Could use:
- The `tempdir` crate to build an Indexer fresh in a temp dir, then directly
  push hashes into `vecs.blocks.blockhash` via `checked_push`.
- OR write a smaller in-memory shim for the blockhash vec specifically.

The former is more honest (tests the real type), maybe ~30 lines of setup.

## Test cases to cover

These are the 7+ scenarios the audit walked through by hand. Each becomes a
test function:

1. **tip recognized at first check** — should return `Some(tip)` with 1 RPC.
2. **all stored hashes unrecognized** — should return `Ok(None)` after walking
   to genesis.
3. **recognized at exact exponential step** (e.g. recovery height = tip - 128
   on a 200-deep chain) — should return that hash with `log_2(128) + 1` = 8
   RPCs.
4. **recognized between exponential steps** (e.g. recovery height = tip - 100)
   — exponential overshoots, binary search refines; verify it lands on the
   HIGHEST recognized index (not just any one).
5. **recognized exactly at genesis (idx=0)** — should return genesis hash.
6. **vec length 1 (only tip stored)** — tip unrecognized → return `Ok(None)`
   without further calls.
7. **vec length 0 (no stored chain)** — this case is actually handled at the
   caller (lib.rs:215 `else { (Lengths::default(), None) }`), not in
   `find_recognized_ancestor`. Verify caller logic separately or document.
8. **RPC error propagates** — `recognizes_block` returns `Err`, should
   propagate as `Err` (not be confused with `Ok(false)`).

## Total estimated cost

| Component | Lines | Time |
|-----------|-------|------|
| Trait + impl in brk_rpc | ~10 | 5 min |
| Signature change + import | ~3 | 2 min |
| MockClient struct + impl | ~15 | 10 min |
| Test setup (temp Indexer) | ~30 | 20 min |
| 8 test cases | ~120 | 45 min |
| **Total** | **~180 lines** | **~80 min** |

This is **smaller than the audit's "moderate refactor" framing**. The actual
work is closer to "an afternoon's effort" not a multi-day refactor.

## Recommendation

Worth doing **if and when** the walk-back algorithm is modified. The current
algorithm is correct and unlikely to change. Re-evaluate this scoping if any
of these become true:

- A bug is found in `find_recognized_ancestor` (then tests are needed before
  the fix).
- Someone wants to change the exponential→binary refinement (then tests
  prevent regression).
- An external auditor wants empirical proof beyond the audit walk-through.

If none of those, the algorithm sits comfortably under the audit's static
review + the bundled-binary `strings` verification + the 3 adjacent recovery
paths' empirical proofs (see `BTX-B3-walkback-exercise-2026-06-01.md`).

## Why I'm not implementing this in-session

1. Touching `brk_rpc::Client`'s public API ripples through every brk_cli
   consumer. Trivial in code, but worth a review pass.
2. Without running `cargo test -p brk_indexer` after to verify, the tests
   could be wrong (`Vecs` setup is the unknown unknown).
3. E4 was marked "deferred" in the audit; the readiness doc says it's
   "moderate refactor cost" and "reconsider if the algorithm ever needs to
   change". Both apply.

If you want me to implement, say the word and I'll do it. Otherwise this
doc captures everything needed for a future session to do it in ~80 minutes.
