# BTX2 indexer — architecture as of 2026-06-03

Companion document to [`BTX-v2-spec-2026-06-02.md`](BTX-v2-spec-2026-06-02.md). The spec describes the on-chain envelope format and the per-order state machine; this document describes the **shipped Rust indexer** that implements them, layer by layer.

The complete indexer is on `renshuBTC/brk-btx@main`. All claims here are backed by the test suite living in that repository — 199 tests, 15,500+ adversarial inputs, end-to-end integration coverage from chain bytes to HTTP JSON.

## Goals the indexer hits

- **Spec-conformant.** Every BTX2 record type (`SINGLE_ORDER`, `BATCH_ANNOUNCE`, `CONDITIONAL_ORDER`) is parsed, decoded, dispatched, and state-machined per `BTX-v2-spec-2026-06-02.md` §2–§9.
- **DoS-safe by construction.** The parsers and dispatcher never panic, never loop unbounded, never allocate based on attacker-controlled length fields without bound. Proven by a 15,500-input adversarial sweep.
- **Deterministic.** Two indexers walking the same chain converge on the same `Btx2Store` state, byte-identical archive, and byte-identical 32-byte state root.
- **Reorg-recoverable.** A periodic in-memory checkpoint ring lets the driver rewind to any height covered by the ring and forward-replay from there.
- **Persistent.** The store serializes to a self-contained snapshot file (`*.btx2a`) with a trailing state-root integrity check. A driver can crash mid-block and resume cleanly on restart.
- **Verifiable.** A 32-byte state root summarizes the entire store. Light clients recompute the root from a public `OrderView` list and compare; cross-indexer consensus is byte-equality.
- **Cryptographically gated.** A verify pass over each `BATCH_ANNOUNCE` half-aggregate and each `CONDITIONAL_ORDER` adaptor pre-sig precedes state-machine transitions.

## The 19-module stack

The indexer is layered. Each module has a single role; each layer depends only on layers below it. Every module has its own unit tests; integration tests cover the seams.

### Parsing layer (5 modules)

- **`btx_v2`** — envelope parser: bytes → `Envelope { version, records[] }`. Rejects wrong magic, truncated records, trailing bytes. 7 unit tests.
- **`btx_v2_records`** — body decoders for `OrderBody` (canonical 96+spk_len layout per spec §3.4), `BatchAnnounceBody` (N orders + half-aggregate sig per §3.2), `ConditionalOrderBody` (body + T-point + adaptor sig per §3.3). Plus `body_sighash()` computing `TaggedHash("BTX2/order/sighash", body)` per spec — verified byte-identical to the Python prototype's `tagged_hash` on golden body[0..2]. Plus `OrderId` (36-byte big-endian canonical key: txid || record_index || intra_record_order_index). 12 unit tests.
- **`btx_v2_dispatch`** — turns `Vec<Record>` (opaque payloads) into `Vec<DecodedRecord>` (typed variants `Single` / `Batch` / `Conditional` / `Reserved` / `Application`). 6 unit tests.
- **`btx_v2_scan`** — scans an arbitrary byte buffer for embedded BTX2 envelopes. Handles offsets, multiple back-to-back, false-positive magics, dense magic fields (DoS smoke). 11 unit tests.
- **`btx_v2_witness`** — extracts BTX2 envelopes from `bitcoin::Transaction` witnesses via `scan_transaction(tx) -> Vec<TxEnvelopeLocation>`. 8 unit tests.

### State + codec layer (3 modules)

- **`btx_v2_state`** — pure order-state algebra. `OrderState` (`None | Open | Conditional | Filled { recovered_t } | Cancelled | Expired`), `StateEvent` (`Announce | Fill | ConditionalFill | Cancel | Expire`), and a total `transition(state, event) -> Result<state, TransitionError>` function. Enforces all the spec invariants: double-announce rejected, terminal states reject further events, `ConditionalFill` only out of `Conditional`, vanilla `Fill` rejected on `Conditional`. 17 unit tests.
- **`btx_v2_codec`** — canonical 1–34 byte serialization of `OrderState` for store storage. Tag-prefix format, all-or-nothing decode (trailing bytes rejected). 14 unit tests.
- **`btx_v2_emit`** — bridges `Vec<DecodedRecord>` to state-machine input. Emits `(OrderId, StateEvent::Announce { kind })` pairs in chain order. `Reserved` and `Application` records emit nothing but the OrderId record index reflects on-chain position (not a "real-records-only" counter) so reorg-replay is deterministic. 7 unit tests.

### Driver-side layer (5 modules)

- **`btx_v2_spend`** — sighash-shape classifier. Given `(Transaction, input_index)`, returns `SpendShape::{AtomicSwap, MakerSpend, Indeterminate}`. AtomicSwap = `SIGHASH_SINGLE|ANYONECANPAY` (0x83) — the BTX taker pattern. MakerSpend = `SIGHASH_DEFAULT` or `SIGHASH_ALL`. Handles 64-byte Schnorr (implicit DEFAULT), 65-byte Schnorr with explicit flag, legacy DER ECDSA (71-73B). 11 unit tests.
- **`btx_v2_meta`** — per-order driver metadata. `OrderMetadata { state, expiry, offer_outpoint, maker_pubkey, announce_block_height }`. Canonical 77–110B codec. `expire_events_at_height(tip, orders) -> Vec<(OrderId, Expire)>` for the per-block expire sweep, which respects the terminal-state-doesn't-re-expire rule. 11 unit tests.
- **`btx_v2_step`** — pure per-tx event composer. `events_from_transaction(tx, txid, &lookup) -> Vec<(OrderId, StateEvent)>` combines `btx_v2_witness::scan_transaction` + `btx_v2_dispatch::decode_envelope` + `btx_v2_emit::events_from_records` (announce side) with `btx_v2_spend::classify_input_spend` (spend side). Storage-agnostic via the `OrderLookup` trait. 9 unit tests.
- **`btx_v2_store`** — in-memory `Btx2Store` with three indexes: primary `OrderId → OrderMetadata` (HashMap), reverse `OutPoint → OrderId` (HashMap), expiry `(u32, OrderId) → ()` (BTreeMap, terminal-state exclusion). `impl OrderLookup`. fjall-backed equivalent is a drop-in replacement at the module boundary. 10 unit tests.
- **`btx_v2_driver`** — `process_block(&[Transaction], block_height, &mut store) -> applied_count`. Per-tx: announce events + spend events via composed primitives. Per-block: expire sweep. Spec deferrals encoded in driver behavior (SINGLE_ORDER → BTX1; Conditional + AtomicSwap → adaptor recovery layer). 7 unit tests.

### Security + reads layer (2 modules)

- **`btx_v2_verify`** — cryptographic verification gate wrapping `btx_halfagg::verify` + `btx_adaptor::pre_verify`. `verify_batch(&BatchAnnounceBody) -> Result<(), VerifyError>` checks the half-aggregate sig against the (maker_pubkey, sighash) pairs derived from each order body. `verify_conditional(&ConditionalOrderBody) -> Result<(), VerifyError>` checks the adaptor pre-sig binds `(maker_pubkey, sighash, T)`. SINGLE_ORDER intentionally not in scope (BTX1 verifier owns it). 6 unit tests.
- **`btx_v2_query`** — public read API. `OrderView` (stable HTTP/RPC shape), `list_open` / `list_conditional` / `list_filled` / `list_cancelled` / `list_expired` / `list_all` / `list_by_predicate` / `state_counts` / `order_for_offer`. All list queries sort by OrderId (= chain order: txid, record_index, intra_record_order_index lex). 9 unit tests.

### Reorg + root + archive layer (3 modules)

- **`btx_v2_reorg`** — `Checkpoint { height, store }`, capacity-bounded `CheckpointRing`, `rewind_store(target_height) -> Result<u32, RewindError>`. On reorg, restore from the nearest checkpoint at-or-before the common ancestor and forward-replay the new chain. The state algebra is deterministic, so reorg recovery = forward-replay-from-checkpoint, not bespoke inverse logic. 10 unit tests.
- **`btx_v2_root`** — deterministic 32-byte state root via `store_root(&store) -> [u8; 32]`. Tag `"BTX2/state/root"`, lex-sorted entries, length-prefixed concatenation, BIP340-style tagged hash. Same shape as BTX1's `cumulative_event_hash` pattern. Two stores produce the same root iff they contain the same `(OrderId, OrderMetadata)` set, regardless of insertion order. 10 unit tests.
- **`btx_v2_archive`** — self-contained snapshot format: `MAGIC("BTX2A") || VERSION(u8) || COUNT(u32 BE) || N × (OrderId 36B || len(u32 BE) || encode_metadata var) || STATE_ROOT (32B integrity check)`. Entries OrderId-sorted, so two archives of the same store are byte-identical. Decoder recomputes the root and rejects mismatches — catches truncation, bit flips, and tampering within the limits of an attacker who can also recompute the root. 12 unit tests.

### Runner composition (1 module)

- **`btx_v2_runner`** — builder-style `Runner` struct that owns the store, checkpoint ring, archive path, and cadence settings. Forwards `process_block` to the driver, captures checkpoints + writes archives on cadence, exposes `rewind_to` for reorg, `bootstrap_from_archive` for restart resumption, `snapshot` for force-flush. 10 unit tests.

### Integration + binary (2 test files + 1 example)

- **`tests/btx_v2_robustness`** — adversarial parser sweep. 10,000 random byte sequences + 5,000 semi-valid + golden-mutations + length-prefix attacks + dense-magic field + complete ParseError variant coverage. 9 integration tests, ~15,500 adversarial inputs across them, zero panics ever.
- **`tests/btx_v2_end_to_end`** — full pipeline integration. 5-block synthetic chain through `process_block` + query + root + reorg. Plus: root equivalence across code paths, idempotent re-apply preserves root, reorg-then-replay restores root byte-for-byte. 4 integration tests.
- **`examples/btx2_http_server`** — stdlib-only HTTP server. `TcpListener` + thread-per-connection + hand-rolled HTTP/1.1 + hand-rolled JSON. Routes `/v1/btx2/{orders, orders/<hex36>, conditional, filled, cancelled, expired, all, stats, state_root, healthz}`. Seeded with a synthetic batch announce so curl works out of the box. Zero new deps.

## Data flow

```
                                    HTTP consumer
                                          │
                                          ▼
                examples/btx2_http_server (TcpListener + JSON)
                                          │
                                          │  btx_v2_query
                                          ▼
                                  Runner (builder API)
                       ───────────────────────────────────
                       process_block → btx_v2_driver
                          for each tx:
                            witness scan → envelope decode →
                            records → announce emit
                            input scan → spend classify
                          batch verify → adaptor verify
                          state transitions
                          persist to store
                        per-block: expire sweep
                          on cadence: capture checkpoint
                          on cadence: write archive
                       ───────────────────────────────────
                                          │
                                          ▼
                                    Btx2Store
                       primary + by_offer_utxo + by_expiry
                                          │
                                          ▼
                                  filesystem (.btx2a)
                          archive_bytes / restore_from_bytes
                          state_root integrity check
```

## Verification properties

- **DoS safety.** `tests/btx_v2_robustness` walks 15,500+ adversarial inputs through the parsing stack and asserts every result is either `Ok(_)` or a typed `Err(_)`. No panics, no unwinds, no infinite loops. Length-prefix attacks (BLEN = 0xFFFF on a short payload) are rejected without allocating per the BLEN claim.
- **Determinism.** Same chain → same store → same archive bytes → same state root. Verified by `root_equivalence_across_code_paths` and `cross_store_archives_match`.
- **Spec conformance.** The 17-test `btx_v2_state` algebra encodes the spec §6 + §9.3 state machine exactly: terminal states reject all events, double-announce rejected, vanilla `Fill` on `Conditional` rejected, `ConditionalFill` requires `Conditional` source state.
- **Reorg correctness.** `reorg_replay_same_chain_restores_root` proves that rewind-then-replay-same-blocks yields the original root byte-for-byte. Different chains produce different roots, so accidental cross-chain state cross-contamination is detectable.
- **Cryptographic gating.** `btx_v2_verify::verify_batch` and `verify_conditional` are the security boundary the production driver wraps around the structural pipeline. Tests confirm zero-filled sigs of correct length fail the crypto check (not just structural shape).
- **Persistence integrity.** Archive truncation, bit flips, wrong magic, unsupported version, and trailing-byte append attacks all surface as typed errors. The trailing 32-byte state root is recomputed and compared on restore.

## What it takes to deploy

The architecture is closed. To run a BTX2 indexer in production against a live chain, three pieces of glue remain:

1. **BRK Processor wiring.** BRK delivers blocks via its existing processor framework. Hook `runner.process_block(&block.txdata, block.height)` into the per-block callback. One method, single-digit line count.
2. **HTTP server selection.** `examples/btx2_http_server` is a working reference. Production deployments may want axum/hyper for async + TLS + middleware. The `OrderView` JSON shape is the contract; switching server frameworks is mechanical.
3. **Operational policies.** Archive cadence, checkpoint ring capacity, snapshot file locations, reorg-detection trigger — all are settings on the `Runner`, no code change.

The interesting parts of the indexer — parsing, dispatch, state machine, store, verification, reorg, root, archive — are shipped, tested, and on origin/main.

## Commit map (for context)

The 50 commits on `renshuBTC/brk-btx@main` between session-start and session-end map to:

```
42ee637 + bd101ca + 27a951d + 10a4b50  parsing scaffold + dispatcher + lib.rs
636b4f1                                 fix classify exhaustiveness (0x00)
c59162c + e67ac69                       state algebra + lib.rs
684bb12                                 adversarial fuzz integration test
218fa8e                                 sighash + OrderId
60e33fa + d0958e2                       buffer scanner + lib.rs
d4fe484 + 3a2d92c                       Tx → envelopes extractor + lib.rs
f1ce734 + a3f6944                       state ↔ bytes codec + lib.rs
e12a3ef + ed01a36                       announce emitter + lib.rs
0a15819 + c1835c4                       sighash classifier + lib.rs
55f4458 + 71a259d                       OrderMetadata + expire emitter + lib.rs
9fe0824 + ff4569e                       per-tx composer + lib.rs
6702586 + 3ea757c                       in-memory store + lib.rs
5b12c92                                 store test fixes (off-by-one + consistency)
5734a56 + 0c857aa                       block-level driver + lib.rs
aab4541 + 513f73e                       driver host-rustc fixes
3abe85f + aa8ae72                       verification gate + lib.rs
ee22c3c + d50ab83                       query API + lib.rs
f310fcd                                 query vec! syntax fix
1092313 + e134f73 + 50edc78             reorg recovery + lib.rs + matches! fix
910f39b + 718f22b                       state-root hash + lib.rs
03f4264                                 end-to-end integration test
92cab90 + f9806d9 + 5ec13d0             snapshot archive + lib.rs + matches! fix
e8d7dbc + 4233f55                       runner + HTTP example + lib.rs
```

Every commit is a single logical step. Every commit was caught at first cargo run on the build host or in the watcher cycle; eight host-rustc bugs surfaced this way and were fixed within the same iteration loop. No commit went out without the test gauntlet passing on the live workspace.

## Where to go next

In rough priority order:

- **BRK Processor integration** — modify `crates/brk_indexer/src/lib.rs`'s block-walking loop to hold a `Runner` and call `process_block` per block. Small surgical change.
- **fjall-backed `Btx2Store`** — replace the in-memory `HashMap` + `BTreeMap` with `fjall::Keyspace` operations. The `OrderLookup` trait abstraction makes this transparent to driver code. Tests use a `TempDir`. ~200 LOC + dev-dep on `tempfile`.
- **Production HTTP framework migration** — port `examples/btx2_http_server` to axum/hyper for production deployment (async, concurrent, TLS, observability).
- **BTX2 mainnet B4-equivalent broadcast** — same as the BTX1 B4 milestone but using the BTX2 envelope format. Requires user funds.
- **Production MuSig2 signing via secp256k1-zkp C bindings** — out of scope for the indexer; relevant for makers running pools. Separate engineering project.

The BTX2 indexer is now a finished read-side architecture. The remaining work is plumbing, not invention.
