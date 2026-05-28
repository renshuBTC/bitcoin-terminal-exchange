# BTX — Book Commitment & Membership Proofs (design)

*Upgrade the flat consensus hash to a Merkle-committed book so a client can verify a SINGLE served
order with a log-sized proof — no full book download, no full node. Closes the "passive viewers trust
the indexer" gap (threat-model item d; attack/defense matrix d). Design only; grounded in BTX's
existing `book_hash`. Inspired by OPI-LC (cumulative/verified hash) and RiemaLabs (committed state +
fraud proofs); BTX uses a plain SHA-256 Merkle tree (rationale below). Date: 2026-05-27.*

## Why Merkle, not Verkle
RiemaLabs commits state in a **Verkle tree** (KZG vector commitments) for O(1) proofs, but that requires
pairing crypto + a trusted setup and a much heavier impl. BTX's open book is hundreds–to–low-thousands
of orders; a **binary SHA-256 Merkle tree** gives ~log₂N (≈10–12 hashes) per proof, **no new
dependencies** (SHA-256 is already used for `book_hash`, the artifact, runestones, everywhere), and
keeps the consensus-critical **Python↔Rust byte-for-byte parity** as simple as the existing `book_hash`.
Verkle's O(1) advantage only pays off at millions of entries. Merkle is the right call here.

## Reuse the existing canonical leaf + sort (preserves the consensus property)
The current `book_hash` (Python `btx_orderbook.book_hash`; Rust `book_hash_from_views`) already defines:
- **canonical line** per order: `"{rune_id}|{side}|{price}|{amount}|{announce_height}|{offer_txid}:{offer_vout}"`
- **total sort key**: `(rune_id, side, price, announce_height, offer_txid, offer_vout)`

Keep both **unchanged** — the Merkle tree is built over the *same* sorted canonical lines, so the root is
**order-set-independent** exactly as the flat hash is (two honest indexers ⇒ identical root). Only the
*aggregation* changes from `sha256(concat(lines))` to a Merkle tree.

## Tree construction (must be byte-identical in Python and Rust)
Domain-separated SHA-256 (the RFC6962 / Certificate-Transparency pattern — prevents leaf/internal-node
second-preimage confusion):
```
leaf(order)      = sha256( 0x00 || canonical_line_utf8 )           # 0x00 = leaf tag
node(left,right) = sha256( 0x01 || left(32) || right(32) )         # 0x01 = internal tag
```
Build:
1. Compute `leaf(order)` for every OPEN order; **sort the leaves by the canonical sort key** (NOT by
   leaf-hash value — so the proof can name an order by its sort position, and the tree matches the
   served `/orders` ordering).
2. Reduce level-by-level pairing `(2i, 2i+1)`. **Odd node: carry the lone last node up unchanged**
   (do NOT duplicate it — duplication reintroduces the CVE-2012-2459 ambiguity; carry-up + the leaf/node
   domain tags is unambiguous).
3. `book_root` = the final 32-byte root. **Empty book ⇒ `book_root = 0x00*32`** (fixed sentinel).

## Membership proof
For order `O` at sorted index `i`:
```
proof(O) = { order: OpenOrderView, index: i, n_orders: N,
             path: [ {hash: <32B sibling>, dir: "L"|"R"}, ... ] }  # leaf→root sibling list
```
Client verification (no full node, no full book):
1. `h = sha256(0x00 || canonical_line(order))`
2. for each `{hash, dir}` in path: `h = node(hash, h)` if dir=="L" else `node(h, hash)`
3. assert `h == published book_root`  → **the order is in the committed book.**
4. (optional, fully trustless) independently `gettxout(order.offer_outpoint)` and run
   `verify_maker_sig(order.artifact, value, spk)` → **the order is also valid and fillable.**
Step 3 needs only the proof + the root; step 4 adds one UTXO lookup. Neither needs the whole book.

## Fraud proofs (RiemaLabs-style, cheap because artifacts self-verify)
BTX orders are self-verifying artifacts, so a light client can *disprove* a malicious indexer:
- **Bogus order served**: indexer returns `O` with a valid membership proof, but `verify_maker_sig(O)`
  fails against the real offer UTXO → the membership proof itself is the fraud proof (the indexer
  committed to an invalid order).
- **Omission**: a client that sees an on-chain announce whose order isn't in the committed book holds a
  proof of omission (the artifact + its confirming tx vs. the root that should contain it).
This is the path from "detectable only if you self-host" (current) to "any light client can challenge."

## API (additive — keep the flat hash for back-compat during transition)
- `GET /api/v1/btx/book-root` → `{ root, n_orders, flat_hash }` (flat_hash = today's `book_hash`, kept
  so existing cross-indexer-agreement clients don't break).
- `GET /api/v1/btx/order-proof?offer=<txid>:<vout>` → the `proof(O)` object above.
- The terminal's existing "indexer agreed" badge upgrades from "my hash == served hash" to "this order
  verified against the committed root" — per-order, not whole-book.

## Implementation plan (consensus-critical → parity-first)
1. **Python reference** (`btx_orderbook.py`): `book_merkle_root(orders)`, `merkle_prove(orders, offer)`,
   `merkle_verify(order_line, proof, root)`. Pure, offline-testable.
2. **Rust** (`btx.rs`): `book_root_from_views(&[OpenOrderView])`, `prove_order(...)`, mirroring the
   Python byte-for-byte. **Golden cross-test** Python root == Rust root on the same fixtures (same
   discipline that already keeps `book_hash` identical).
3. **Property tests** (extend `btx_fuzz.py` + btx tests): root is order-set-independent (shuffling
   inputs ⇒ same root); every order's proof verifies against the root; a tampered order/proof fails;
   empty/1-order/odd-N trees handled.
4. **Serve** (`brk_query` + `brk_server`): the two endpoints; reuse the `MAX_SERVED_ROWS` discipline for
   the order list while the **root commits the full set** (same full-set-vs-capped-list split already
   used for `book_hash`).
5. **Terminal**: per-order verification against the root; show "✓ verified in book root" per row.

## Open questions to resolve against the cloned references
- OPI-LC's **cumulative event hash** (announce/fill/cancel stream): worth adding alongside the open-book
  root so a light client can follow the book incrementally and detect reorg/omission — confirm OPI-LC's
  exact hash chain format before deciding BTX's.
- RiemaLabs' **checkpoint distribution** (they use a DA layer): BTX is nothing-offchain, so the root
  should be derivable purely from chain by any indexer (no DA dependency) — the root is *already* a pure
  function of chain, so BTX gets the verifiability without the DA layer. Confirm this is the right
  divergence from their model.

## Status — IMPLEMENTED (2026-05-27)

Shipped end-to-end, with byte-for-byte agreement across all three implementations (golden-cross-tested):
- **Python reference** — `btx_orderbook.book_root` / `merkle_prove` / `merkle_verify` (bitcoin-terminal-exchange
  `2ecf26e`). Canonical leaf/sort factored out of `book_hash` (refactor kept the flat hash identical).
- **Rust indexer** — `btx.rs` `book_root_from_views` / `prove_order` + `MerkleProof`/`MerkleStep`
  (brk-btx `9e57d968c`). Golden cross-test: Rust root == Python `b7d544…853c`; btx tests 27/27.
- **HTTP serving** — `GET /api/v1/btx/book-root` (full-set root + n_orders + legacy `flat_hash`) and
  `GET /api/v1/btx/order-proof/{txid}/{vout}` (brk-btx `7a0912de4`; `brk_server` builds clean).
- **btxd proxy + terminal** — `/api/dex/book-root` + `/api/dex/order-proof/...` passthrough, and a Web
  Crypto `merkle_verify` in `btx_trade.html` that proves a served order is in the committed root and
  flips the book badge to "✓ order verified in root" (bitcoin-terminal-exchange `8877718`). The JS was cross-checked
  in node against the same golden root.

Resolved open questions: RiemaLabs' DA-layer dependency is correctly skipped: BTX's root is a pure
function of chain, so any indexer derives it independently with no data-availability layer.

## Cumulative event hash — IMPLEMENTED (2026-05-27)

The OPI-LC-inspired cumulative-event-hash follow-on (open question #1) is now shipped end-to-end. It
complements the open-book root (which commits book STATE at the tip) with a rolling commitment over the
event STREAM, so a light client can follow the book incrementally and detect reorg/omission.

*Honest sourcing note:* the local OPI-LC checkout is install/docker scaffolding only — it does NOT
contain the light-client hashing source, so OPI-LC's exact chain format could not be re-quoted here. An
earlier note recorded it as `sha256(prev_cum || block_hash)`, but that chains only block hashes (which a
client already has) and does not commit to BTX's order events. BTX therefore grounds the design in
its OWN proven `book_hash` canonical line rather than copying an unverified external format:

- **Events = chain-caused transitions only.** An ANNOUNCE at `announce_height`; a FILL/CANCEL at
  `last_event_height` when the offer UTXO is spent. Expiry is deliberately NOT an event — it has no
  transaction (an order past expiry simply stops being OPEN, a read-time predicate), so it cannot anchor
  a deterministic stream. This matches what the store actually persists (OPEN/FILLED/CANCELLED).
- **Pure function of the record set** (open + closed records, which the store keeps) — like `book_root`,
  no running scalar and no new reorg-rollback surface.
- **Construction** (continues the book_root domain-tag scheme — leaf 0x00 / node 0x01 are taken):
  per-event line `"{height}|{code}|{rune_id}|0|{price}|{amount}|{announce_height}|{txid}:{vout}\n"`
  (`code` ∈ A/F/C; same canonical fields `book_hash` commits to, side hardcoded 0); per-block digest
  `sha256(0x02 || concat(events sorted by canonical key then code))`; cumulative fold
  `sha256(0x03 || cum_prev || height_be4 || block_digest)`, genesis/empty = `00*32`.

Shipped, byte-for-byte golden-cross-tested across all three implementations:
- **Python reference** — `btx_orderbook.cumulative_event_hash` / `event_block_hashes`; offline golden
  test `btx_eventhash_test.py` (wired into `btx_test_all.py`). Golden cumulative
  `0716e1c4…02141e`; verified order-set-independent + omission-detecting.
- **Rust indexer** — `btx.rs` `cumulative_event_hash_from_views` / `event_views_from_records` /
  `cumulative_event_hash_from_store` + `EventOrderView`/`EventHashView`; golden test
  `cumulative_event_hash_matches_python_golden` asserts Rust == Python `0716e1c4…02141e`.
- **HTTP serving** — `GET /api/v1/btx/event-hash` (`{cumulative, n_event_blocks, n_events}`) via
  `Query::btx_event_hash`; btxd `/api/dex/event-hash` passthrough.

The per-block event-stream *listing* is now ALSO shipped (2026-05-28): `GET /api/v1/btx/event-stream`
returns the event-bearing blocks ascending as `[{height, block_hash, cumulative}]` — the running
cumulative through each block, so a light client folds it to follow the book incrementally and can resume
from any `(height, cumulative)` checkpoint (the last entry's `cumulative` equals `/event-hash`). Python
reference `btx_orderbook.event_stream`, Rust `event_stream_from_views`/`_from_store` +
`EventStreamBlockView` + `Query::btx_event_stream`, btxd `/api/dex/event-stream` passthrough; golden
cross-tested (`event_stream_matches_python_golden` Rust == the Python `event_stream` goldens).

Still deferred (UI only): a terminal view that folds the stream client-side and shows a verified
checkpoint badge — the backend capability is complete; the open-book-root badge already covers per-order
verification UX, so the stream-follow UI is the remaining (frontend) add-on.

Known limitation: the terminal JS reads `amount` as a JS Number — exact for sats and rune amounts
< 2^53, but a very-high-divisibility rune amount above 2^53 would need BigInt in the browser verifier
(the Python and Rust paths are exact). Not a consensus issue — only the optional client-side JS check.
