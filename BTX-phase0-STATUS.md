# BTX Phase 0 — Status (2026-05-23)

Locked decisions: **one-installer bundle**, **pure chain-reconstructed** order book,
**USD-stablecoin** counter-asset (Runes used as the prototype asset), **full node**.
See `BTX-architecture-and-build-sequence.md` and `BTX-phase0-spec.md` for the why.

## Proven this session (machine-verified)

| What | How verified | Evidence |
|---|---|---|
| **Settlement primitive (0a).** Maker pre-signs `[offer-in, payout-out]` with SINGLE\|ANYONECANPAY; taker appends input+output and completes. Honest swap settles in **one txid**; payout-shaving is **rejected** (`mandatory-script-verify-flag-failed`). | Real **Bitcoin Core v29.1 regtest** | `swap_test.py`, `run_swap.sh`, `swap_0a_result.log` |
| **Runes asset leg (encoding + indexing).** Byte-accurate runestone (`6a5d…`, LEB128 edict) rides in the swap; minimal indexer moves 1000 RUNE to the taker output, 0 to maker, 0 unallocated. The taker-supplied edict, not the maker, directs the rune. | Pure Python (byte-decode + indexer) | `btx_runes.py`, `runes_leg_result.log` |
| **Chain-reconstruction logic (0b).** A party with **only the on-chain artifact + the offer amount** verifies the maker signature; tampering the price breaks it; swap rebuilt from artifact data alone. | Offline `selftest` (ALL_PASS) | `btx_0b.py`, `BTX-0b-runbook.md` |
| **Fill/Cancel classification is exact.** Confirmed spend of the offer UTXO = FILL iff output0 == `(price, payout_spk)` (consensus-enforced by the maker sig), else CANCEL. Adversarial wrong-amount spend → CANCEL. | Offline | `classify_test.py`, `btx_index.rs::is_fill` |
| **BTX wire format is consistent across implementations.** Rust parser parses the exact bytes the Python serializer emits. | Cross-impl (Python parse == Rust test asserts) | `btx_index.rs` tests |

## Verified on-node since (WSL, Bitcoin Core v29.1, Rust 1.95.0 — 2026-05-23)

- **Runestone-bearing swap accepted by real consensus** (`run_runes.sh`): `allowed=true`, settled
  one txid, rune moved to taker output #1 (1000), 0 to maker — the previously-argued point, now run.
- **Milestone 0b chain-reconstruction** (`run_0b.sh`): maker published the BTX artifact on-chain;
  a second party verified the maker sig **from chain data only** and completed the swap
  (`allowed=true`, payout 0.5 BTC @1 conf, offer UTXO consumed). No relay. Single-node form.
- **BRK integration compiles + tests pass in-tree**: `mod btx;` added, `cargo check -p brk_indexer`
  clean (0 errors), `cargo test -p brk_indexer btx::` → 2/2 pass. The `ChainAccess` seam is wired
  to `brk_rpc::get_tx_out` and the rust-bitcoin verifier; standalone crate also confirmed a
  python-signed artifact verifies under the same code.

- **Two-datadir, P2P-only 0b (STRICT exit gate)** verified (`run_0b_twonode.sh`): node B received
  the order via block propagation only, verified the maker sig from its own chain, and completed
  the swap — no shared files, no relay. The no-externality thesis holds in its strongest form.

- **Double-take race** verified (`run_doubletake.sh`): two takers each built a valid swap from the
  same offer UTXO; both individually `allowed=true`, but the second broadcast was rejected
  (`-26`, conflict) and exactly one confirmed. Confirms "first valid spender wins / no price-time
  priority" — the chain-reconstructed model's stated cost.

- **Option B (persisted order store)** implemented + compiling + btx tests pass: fjall
  `Store<BtxOfferKey,CxoOrderRecord>` wired into `Stores` (all methods + `rollback_btx_orders`),
  store-backed `index_block_orders` in the sync loop. Survives restarts, commits/rolls back with
  BRK. Unit tests 4/4 pass. **Live-indexer reorg test PASSED** (`run_btx_reorg.sh` + the
  network-magic fix in `brk_reader`): RUN1 indexed the announce → 1 OPEN order in the persisted
  store; after invalidating the announce block + 2 empty blocks, RUN2 re-index → store count 0,
  i.e. `rollback_btx_orders` correctly dropped the orphaned order on a real reorg. brk_reader was
  made magic-configurable via env `BRK_BLOCK_MAGIC` (mainnet default unchanged) to enable regtest
  indexing.

## Maker/taker CLI (product layer — 2026-05-23)
- **`btx.py`** is a single argparse CLI over the proven primitives — it imports `btx_0b.py`
  and `btx_runes.py` and adds **no new protocol logic** (those stay the single source of truth).
  Subcommands: `order create` (sign + emit artifact + carrier OP_RETURN), `order lots` (powers-of-two
  ladder sharing a group_id), `order inspect` (decode artifact → readable fields), `order verify`
  (verify maker sig from artifact + on-chain offer amount), `swap build` (taker assembles the atomic
  swap, witness transplanted), `book summary` (total/filled/open per group_id), `book scan`
  (reconstruct the OPEN/FILLED/CANCELLED book from raw txs), `runestone` (emit byte-accurate
  runestone spk). All flows verified offline 2026-05-23: round-trip OK; correct offer amount → VALID,
  wrong amount → INVALID; taker witness == artifact maker sig; lot ladder 11→[1,2,8]; book summary
  aggregates 1/11 filled; multi-edict runestone reproduces the ord-validated bytes
  `6a5d0f00e701010100000002010000e50702` exactly.
- **`book scan` = chain-reconstruction read path at the CLI level** (mirrors btx.rs
  extract_from_script + index_block_orders). Given raw tx hexes in confirmation order it pulls BTX
  artifacts from OP_RETURN carriers (handles OP_PUSHDATA1 for the ~208-byte blob), records spent
  outpoints + each tx's output0, then classifies every order by the consensus-exact rule: offer UTXO
  spent AND spending output0 == (price, payout_spk) → FILLED, spent otherwise → CANCELLED, unspent →
  OPEN (and verifies the maker sig if --utxos gives the offer amount). Verified offline against
  fabricated announce/fill/cancel txs: FILLED (is_fill true, payout 0.5 BTC), OPEN (sig verifies),
  CANCELLED (is_fill false, wrong output0 0.4 BTC) — ALL_SCAN_TESTS_PASS.
- **PROTOTYPE keys only**: every signing path still uses the deterministic test seeds from the
  proven scripts. Real maker/taker keys must come from the wallet — that wallet integration is the
  next product step, not done here.
- Caveat seen during testing: a stale `__pycache__/btx_0b.cpython-310.pyc` shadowed the updated
  source under the WSL mount (mtime-invalidation didn't fire on the mounted FS), hiding
  `lot_decomposition`/`make_lots`. Run with a clean cache (or `PYTHONDONTWRITEBYTECODE=1`) if you
  see `AttributeError` on those.

## Pluggable carrier — Taproot witness envelope (2026-05-23)
- **`btx_carrier.py`** makes the on-chain carrier pluggable so BTX does NOT depend on a relaxed
  `-datacarriersize`. Two carriers: (1) OP_RETURN (`op_return_carrier`), and (2) an inscription-style
  **Taproot witness envelope** (`envelope_tapscript`/`parse_envelope`): the artifact rides in a
  tapscript `<xonly-pubkey> OP_CHECKSIG OP_FALSE OP_IF <chunk…> OP_ENDIF` inside the WITNESS of a
  script-path spend. Witness data is exempt from datacarrier limits and each push can be 520 bytes —
  the exact mechanism ordinals use, so it's well-exercised on mainnet. `tapleaf_hash` computes the
  BIP341 leaf per spec.
- **Proven offline (`btx_carrier.py` selftest, ALL_PASS):** envelope round-trips for a 208-byte
  single-chunk artifact AND a 1304-byte multi-chunk one; a non-envelope script returns None; tapleaf
  hash is 32 bytes + deterministic; extracted payload keeps the BTX magic.
- **`book scan` is now carrier-agnostic**: `_extract_btx_from_tx` scans OP_RETURN outputs AND every
  witness-stack element for an envelope. Verified offline — a reveal-style segwit tx whose witness
  carried a 246-byte tapscript (207-byte artifact) was scanned and surfaced as an OPEN order with the
  maker sig verified; the OP_RETURN FILLED/OPEN/CANCELLED scenarios still pass (no regression).
- **Still [VERIFY] on a node**: that a real commit/reveal Taproot spend carrying the envelope is
  accepted by consensus + relay. Encoding + extraction + tapleaf are proven offline; the actual
  P2TR commit/reveal needs the wallet to fund the commit output (the BIP341 output-key tweak from
  internal key + tapleaf), so it's left for the on-node runbook.

## Wallet integration — real Bitcoin Core keys (2026-05-23)
- **`btx_wallet.py`** replaces the deterministic prototype seeds with REAL wallet keys. The maker's
  `SINGLE|ANYONECANPAY` pre-signature is produced by Core itself (`signrawtransactionwithwallet`
  with sighashtype `"SINGLE|ANYONECANPAY"`); the taker funds + signs with the wallet. BTX never
  holds a private key. Thin `bitcoin-cli` RPC layer (configurable chain/datadir/wallet, `--dry-run`)
  + PURE assembly/parse helpers. Subcommands: `simulate` (offline), `maker-sign`, `taker-fill`.
- **Offline `simulate` ALL_PASS** — stands in for Core's signer with python-bitcoinlib and exercises
  the new, error-prone plumbing: lifted sig sighash == 0x83; lifted pubkey == maker; assembled
  artifact verifies under `btx_0b.verify_maker_sig`; tampered price fails; taker witness transplant
  puts the maker sig in input0 while preserving the wallet's funding sig in input1; output0 == the
  committed payout. `--dry-run maker-sign` emits the exact `signrawtransactionwithwallet … 
  SINGLE|ANYONECANPAY` command.
- **On-node confirmation is documented, not yet run**: `BTX-wallet-runbook.md` is the WSL/regtest
  procedure (throwaway datadir, scoped kill) that closes the only thing the sim can't: that a
  wallet-produced sig verifies under BTX's verifier AND the assembled swap is consensus-accepted
  and settles in one txid. The single new on-node assertion is `maker_sig_self_verifies: true` from
  `maker-sign`. Offer UTXO must be P2WPKH; OP_RETURN carrier needs `-datacarriersize=240` (or the
  envelope path).

## Regression suite — one green-light command (2026-05-23)
- **`btx_selftest.py`** runs the ENTIRE offline-provable surface in one command and exits nonzero
  on any failure: btx_0b round-trip+tamper, btx_carrier envelope/tapleaf, btx_wallet
  `simulate` (wallet plumbing), the ord-validated runes byte vectors (single + multi-edict), and the
  btx.py CLI entry points (order create→verify VALID/INVALID, book scan FILLED/OPEN/CANCELLED for
  OP_RETURN **and** a Taproot witness-envelope announce). **12/12 PASS** on 2026-05-23. Run this
  before/after any change to the protocol code. On-node checks are deliberately excluded — they live
  in the runbooks.
- **Finding: the BTX artifact size is NOT fixed — it varies ~206-209 bytes.** python-bitcoinlib signs
  via OpenSSL with non-deterministic ECDSA, so the DER signature is 70-72 bytes. The runbook's
  `-datacarriersize=240` has comfortable margin. (A future hardening step: switch maker signing to
  libsecp256k1 / RFC6979 low-S for deterministic, minimal sigs — but Core's wallet already produces
  low-S sigs, so the real maker path via `btx_wallet.py` is fine.)

## Taproot commit/reveal — envelope carrier is now publishable (2026-05-23)
- **`btx_taproot.py`** implements the BIP340/341 crypto needed to actually PUBLISH an order via the
  witness-envelope carrier: minimal pure-Python secp256k1 (no libsecp/coincurve dep — pblib 0.12.2
  predates Taproot), `tapleaf_hash`, `tapbranch_hash`, the `TapTweak` output-key tweak,
  `p2tr_scriptpubkey`, `control_block`, and a BIP350 `bech32m` encoder. `commit_for_envelope(internal_key,
  envelope_tapscript)` returns the P2TR commit scriptPubKey + address to fund and the control block to
  reveal with.
- **Verified offline against the OFFICIAL BIP341 wallet test vectors** (fetched from the bitcoin/bips
  repo, stored in `bip341_vectors_subset.json`). `btx_taproot.py` selftest = ALL_PASS across 3
  vectors × {merkle root, tweak scalar, tweaked output key, scriptPubKey, bech32m address, control
  block} + EC-engine internal consistency (G on curve, nG=∞, scalar-mul == repeated-add). Demonstrated
  end-to-end on a real BTX envelope: produced a regtest `bcrt1p…` commit address + control block, and
  confirmed the envelope still extracts the artifact and the output key is reproducible from
  internal-key + leaf.
- **Now in the regression suite**: `btx_selftest.py` is **13/13** (added the BIP341 vector check).
- **Remaining [VERIFY] (node only)**: funding the commit output and broadcasting the reveal tx, i.e.
  consensus/relay acceptance of a real envelope-carrying reveal. All the crypto/encoding it depends on
  is now proven offline; only the funded on-chain spend is left for the runbook.

## BRK order-book query API — serve the reconstructed book over HTTP (2026-05-23)
- Added a read/serving layer in the BRK fork so a UI/client can fetch the chain-reconstructed order
  book. Three crates touched:
  - **`brk_indexer/src/btx.rs`**: serializable views `OpenOrderView` / `GroupSummaryView`
    (derive `serde::Serialize` + `schemars::JsonSchema`) and pure read fns
    `open_orders_from_records` / `group_summaries_from_records` (+ thin `*_from_store` wrappers).
    OPEN list filters status==OPEN and drops orders past expiry at the current tip; group summaries
    aggregate per non-zero group_id ("X of Y filled"). Two new unit tests use the real v2 artifact
    fixture (group_id 7, amount 1000): status/expiry filtering + group aggregation.
  - **`brk_query/src/impl/btx.rs`**: `Query::btx_open_orders()` / `btx_group_summaries()` read
    `self.indexer().stores.btx_orders` (the persisted store rides the Ro indexer on the serve path).
  - **`brk_server/src/api/btx.rs`**: aide/axum endpoints `GET /api/v1/btx/orders` and
    `GET /api/v1/btx/groups`, registered via `add_btx_routes()` (OpenAPI-documented like the rest).
  - **`brk_indexer/Cargo.toml`**: enabled `serde`'s `derive` feature (was off; needed for the views).
- **COMPILED + TESTED in WSL 2026-05-23**: `cargo test -p brk_indexer btx::` → **7/7 pass**
  (incl. the two new view tests `open_orders_view_filters_status_and_expiry` and
  `group_summaries_view_aggregates_and_skips_standalone`); `cargo check -p brk_query -p brk_server`
  → clean (only pre-existing unrelated `brk_computer` warnings). Full path now live:
  chain → indexer → `btx_orders` store → `Query::btx_open_orders`/`btx_group_summaries` →
  `GET /api/v1/btx/orders` + `/api/v1/btx/groups`.

## Client loop closed — btx.py talks to the served book (2026-05-23)
- **`btx.py client orders` / `client groups`** query the running BRK server over HTTP
  (`GET /api/v1/btx/orders` and `/api/v1/btx/groups`, default `--api-base http://127.0.0.1:3110`),
  so discovery runs against the served, chain-reconstructed book instead of a local `book scan`.
  Pure stdlib `urllib` (no new deps). `--json` for raw, `--group-id` to filter, `--timeout` for the
  request. Verified offline against a localhost mock serving the exact OpenOrderView/GroupSummaryView
  JSON: table render, group filter, raw json, and group summary ("300/1000 filled") all correct;
  the offline suite still passes 13/13 (no regression).
- Full maker→taker loop now expressible end-to-end: maker `order create`/`maker-sign` → publish →
  BRK indexes → `client orders` discovers → `swap build`/`taker-fill` completes. The remaining gap is
  only running it live (node + BRK server up), not code.
- **`artifact_hex` added to `OpenOrderView`** (2026-05-23) so a discovered order is *fillable as-is*:
  the served order now includes the full serialized BTX artifact (with the maker pre-signature), so a
  taker can pipe `client orders --json` straight into `swap build --artifact-hex` / `taker-fill`
  without fetching the artifact from anywhere else. Unit test extended to assert the hex round-trips
  to the stored artifact. **Confirmed in WSL 2026-05-23**: `cargo test -p brk_indexer btx::` → 7/7,
  `cargo check -p brk_query -p brk_server` → clean.
- **`btx.py swap build --from-api --offer txid:vout`** (2026-05-23): one-step discover+fill — fetches
  the order from the served book (`/api/v1/btx/orders`), pulls its `artifact_hex`, and builds the swap,
  so a taker never handles the artifact out-of-band. `--artifact-hex` remains the manual alternative.
  Verified offline (mocked fetch): known offer → valid swap (input0 witness == maker sig, output0 =
  committed 0.5 BTC); unknown offer → clean exit. Offline suite still 13/13.

## Live regtest run — BRK started, BTX indexed clean; brk_computer panics on regtest (2026-05-23)
- Ran `brk_cli` against a regtest node (BRK_BLOCK_MAGIC=fabfb5da, blocksdir/cookie/rpcport pointed at
  the regtest datadir). BRK connected, **indexed blocks 0–102 cleanly** (btx::index_block_orders ran
  on every block, no error) and started the server on :3110.
- Then it **panicked in `brk_computer`/`vecdb`**, NOT in BTX: `vendor/vecdb/.../compute/transforms.rs`
  `compute_indirect_sequential` — `unwrap()` on `None` while computing windowed analytics
  (`height_to_input_count_*` 24h/1w/1m). Root cause: BRK's mainnet-style time-window/indirection math
  on a 103-block regtest chain with degenerate near-identical timestamps (cursor past end / first-key
  gap-fill). Orthogonal to BTX; `brk_cli` has no skip-compute flag, so the full HTTP server can't
  run on regtest as-is.
- **Workaround to validate the BTX query path on live data without brk_computer**: new indexer-only
  example `crates/brk_indexer/examples/btx_book.rs` — indexes the chain then prints
  `open_orders_from_store` / `group_summaries_from_store` (the exact functions behind
  `/api/v1/btx/orders` and `/api/v1/btx/groups`). Run:
  `BRK_BLOCK_MAGIC=fabfb5da cargo run -p brk_indexer --example btx_book -- http://127.0.0.1:18443 \
   /tmp/rt-btx/regtest/.cookie /tmp/rt-btx/regtest/blocks /tmp/brk-btx-book`
- NOTE for the run: in the crashed attempt the maker order was **never published** (offer funded only),
  so the book was empty regardless. Publish first (btx_wallet.py maker-sign → OP_RETURN carrier).
- **LIVE END-TO-END VALIDATION PASSED 2026-05-23** via `btx_book`: published a real order (maker-sign
  → OP_RETURN carrier, mined block 104), re-indexed, and `/api/v1/btx/orders` showed **1 OPEN order**
  (offer df14…:1, rune 840000:1, amount 1000, price_sats 50000000, group_id 0, announce_height 104,
  full artifact_hex) — reconstructed purely from chain data through the exact query fn the HTTP
  endpoint calls. Confirms chain → btx::index_block_orders (extract + gettxout + verify maker sig +
  insert) → store → open_orders_from_store, on a real node.
- **Real product lesson (now proven on-node):** the maker MUST fund the carrier (and any later tx)
  from coins OTHER than the offer UTXO. First publish attempt failed because `fundrawtransaction`
  spent the offer UTXO to pay the carrier fee → BRK correctly rejected the order (offer UTXO gone via
  gettxout). Fix in the flow: `lockunspent` the offer outpoint before funding the carrier. The
  maker-side tooling should lock/avoid the offer UTXO automatically.
- **FIXED 2026-05-23:** `btx_wallet.py maker-sign` now `lockunspent`-locks the offer UTXO by default
  (emits `offer_locked: true`; `--no-lock-offer` to opt out), so funding can't spend it and the
  collision can't recur. Also makes the live-demo-runbook publish flow correct without a manual lock
  step. Cancel an order via `lockunspent true [outpoint]`. (Host file verified intact; the WSL mount
  served truncated copies to the sandbox during testing — a sandbox-only artifact.)
  **VERIFIED LIVE 2026-05-23:** re-published with the simplified flow (no manual lock) — maker-sign
  reported `offer_locked: true`, no collision, and `/api/v1/btx/orders` then showed **2 OPEN orders**
  (announce heights 104 + 105), each with full artifact_hex. Maker flow is now collision-safe by
  construction; multi-order book confirmed on a live node.
- **DONE 2026-05-23 (pending user rebuild):** guarded the two `unwrap()`s in vecdb's
  `compute_indirect_sequential` (`vendor/vecdb/src/variants/eager/compute/transforms.rs`). Replaced
  `cursor.next().unwrap()` and `last_v.clone().unwrap()` with carry-forward of `last_v` (the same
  gap-fill semantic the duplicate-key arm uses), falling back to a graceful `return Ok(())` only if
  there's no prior value at the very first element. **Mainnet-safe by construction**: on a normal
  chain every indirection target is in range, so `cursor.next()` is always `Some` and the new arm is
  unreachable → identical behavior; it only changes the degenerate short-chain (regtest) path that
  used to panic, and it preserves vec length (so it can't move the panic downstream). This should let
  `brk_cli` run its full indexer+computer+server on regtest and serve `/api/v1/btx/*` over HTTP.
  Rebuild required (vecdb is a core dep): `cargo run -p brk_cli -- …`. If brk_computer surfaces a
  DIFFERENT regtest unwrap, guard that one the same way.
- **2nd regtest panic (guarded 2026-05-23):** after the vecdb guard, brk_computer got through ALL the
  windowed analytics but then panicked in `distribution/compute/block_loop.rs:93` — `range end index
  106 out of range for slice of length 0`. Root cause is architectural, not a one-off: BRK's
  distribution/cost-basis analytics are **price-dependent**, and regtest has **no price oracle**, so
  `cached_prices`/`cached_timestamps` are empty and the per-block `[start..last+1]` slices blow up.
  Guarded `process_blocks` to skip the price-dependent distribution pass when the price/timestamp
  cache is empty/short (mainnet-unreachable; only affects price-less chains like regtest).
- **HONEST CAVEAT:** this is whack-a-mole — brk_computer assumes a mainnet-scale chain WITH a price
  feed, and regtest violates that in several places. The 2 guards clear the 2 panics we hit, but
  there may be more downstream (skipping distribution could leave a later pass expecting its outputs).
  **The clean path for a live HTTP demo is to run BRK on SIGNET/MAINNET** (where price data exists and
  brk_computer runs normally) — the BTX endpoints serve there without any of these guards. The BTX
  query path itself is already proven live on regtest via the indexer-only `btx_book` example (2 open
  orders). Forcing the full brk_cli server onto regtest is a BRK-core regtest-support effort
  orthogonal to BTX; if a 3rd panic appears, prefer signet over more guards.
- **BOTH GUARDS HELD — full brk_cli SERVER RUNS ON REGTEST 2026-05-23.** After the two guards,
  brk_cli computed through the entire suite (distribution pass skipped with the expected
  `distribution: skipping price-dependent compute` warning) and reached `Waiting for new blocks...`
  — i.e. indexer + computer + axum server all up, listening on :3110. No 3rd panic. The literal HTTP
  endpoint `GET /api/v1/btx/{orders,groups}` responds **200 OK** with valid JSON.
- **OPEN BUG (persistence) — CORRECTION TO EARLIER CLAIM.** The served book is **empty** (`[]`), and a
  fresh-process read of the server's brkdir via `btx_book` shows **0 orders** → `btx_orders` is NOT
  durably persisted to disk. Earlier "validated live end-to-end (2 orders)" was OVER-CLAIMED: the
  `btx_book` example re-indexed the new block each run and read the store **in-memory within the same
  process**, which is NOT durable cross-process persistence. The BTX *query functions* are correct
  (they return the right view from an in-memory-populated store); the bug is in the Option-B store
  WIRING — `index_block_orders` writes to `Store::puts`, but those writes are not landing durably in
  the fjall keyspace via the indexer's flush path (so the server's separate read-only query handle and
  any fresh reader both see empty). Root cause not yet pinned — needs hands-on debugging in WSL (can't
  run instrumented builds from the agent sandbox, and the sandbox's BRK source view has been unreliable
  all session). Added a TEMP `tracing::info!` in `index_block_orders` (logs artifact-found / get_tx_out
  result / verify / INSERT during indexing) to localize on the next fresh run. **This is the one real
  unfinished item; the BTX protocol layer itself remains fully proven offline + unit-tested.**
- **ROOT CAUSE PINNED 2026-05-23 (temp tracing, since reverted).** On a fresh brk_cli run the hook
  logged exactly the right thing during the server's own index:
  `BTX h=104 get_tx_out=Some verify=true INSERTED`, `BTX h=105 … INSERTED`, and h=103 (the collided
  first order) correctly `get_tx_out=None`. So the BTX hook + verify + insert all work live. The
  bug is **store flush timing in brk_indexer**: inserts go to `Store::puts`; stores commit to the
  shared keyspace/disk only via (a) the synchronous in-loop `export`, which fires only every
  `SNAPSHOT_BLOCK_RANGE = 1000` blocks (NEVER on a 105-block regtest), and (b) a deferred background
  task (`vecs.db.run_bg`, 3s sleep) that in a never-exiting server effectively flushes on drop/exit.
  Net on a sub-1000-block long-running server: `btx_orders` writes stay in the writer's in-memory puts
  and are never committed to the keyspace the read-only query clone reads → served `[]`. **This does
  NOT affect mainnet/signet** (the 1000-block export fires constantly). Fix options: (1) add a
  synchronous `self.stores.commit(lengths.height)?` at end of `index_` so the final indexed state is
  durable + query-visible immediately (mainnet-safe: just makes the already-async commit synchronous
  at end-of-index; minor perf cost) — a BRK-core flush-behavior change to review/test; or (2) just run
  on signet/mainnet, where it works unchanged. BTX hook is confirmed correct on a live node.
- **DIAGNOSIS CORRECTED 2026-05-23 (full source read, no compiler — supersedes the "flush-timing"
  conclusion above).** Read the real write/read path end-to-end via the host source of truth (Read/Grep,
  not the unreliable sandbox mount). Findings, each cited:
  - Fix option (1) was applied and **is on disk**: `brk_indexer/src/lib.rs:336` calls
    `self.stores.commit(lengths.height)?` synchronously at end of `index_`, before
    `take_all_pending_ingests`.
  - That commit IS durable AND query-visible: `Stores::commit` (`stores.rs:187-198`) runs
    `par_iter_any_mut().commit` then `self.db.persist(PersistMode::SyncData)`. `Store::commit`
    (`brk_store/src/lib.rs:362-380`) ingests `puts` into the **keyspace**. The query's
    `read_only_clone` (`lib.rs:401-409`) does `stores: self.stores.clone()`; `Store` derives `Clone`
    and its `keyspace: Keyspace` is an Arc-backed fjall partition handle, so the clone **shares the
    same live partition** — once `commit` ingests, the query clone's `iter()` sees it (no extra
    persist needed for in-process visibility; persist is only for cross-process durability).
  - Therefore the live `[]` is **NOT a persistence/flush bug**. With fix (1) compiled, a committed
    order would be both durable and served. The only way the API returns `[]` is that the order was
    **never inserted**.
  - Real cause of the empty book: `index_block_orders` (`btx.rs:486-487`) inserts only when
    `chain.offer_utxo(...)` returns `Some`, and `offer_utxo` (`btx.rs:294-301`) calls
    `get_tx_out` → Bitcoin Core `gettxout` (`brk_rpc/src/methods.rs:235-262`), which queries the UTXO
    set **as of the node's current tip** (tip-relative, not height-relative). The temp-tracing run's
    `BTX h=103 get_tx_out=None` is exactly this: at index time the first order's offer UTXO was already
    spent (the funding collision, before the maker-sign auto-lock fix) → `gettxout=None` → order
    **correctly rejected**, never inserted. (h=104/105 logged `Some`+INSERTED only because their offers
    were still unspent in-process at that moment.) So the served `[]` was the protocol working, plus a
    spent-offer input — not a store bug.
  - **Action:** with the maker-sign auto-lock now keeping the offer unspent, a clean rebuild + fresh
    regtest re-run should index and serve the order. Verify on the user's machine (the agent sandbox
    has no compiler and an unreliable source-mount, so this cannot be confirmed here).
- **ROOT CAUSE PROVEN ON A LIVE NODE 2026-05-23 (instrumented, evidence below).** Built a one-shot
  harness `btx_live_verify.sh` (throwaway regtest, two offer-unspent checkpoints) + temp `BTX-DIAG`
  logging. A clean run produced, in order:
  `h=103 found MAGIC msg_type=1 (height<=expiry=true)` → `offer_utxo=Some(val=100000000) verify_maker_sig=true`
  → `INSERTED into store.puts` → `post-commit btx_orders keyspace count = 1` (WRITER) →
  `query: tip=105 reader_keyspace_count=0` (READER) → API `[]`.
  So the hook, gettxout, signature verify, insert, commit, and `db.persist` ALL work (writer keyspace=1),
  `tip` is correct (105), and the read-side expiry filter passes. The defect is solely that the HTTP
  query reads a **leaked read-only clone of the Indexer** (`brk_query/src/lib.rs:46`
  `Box::leak(Box::new(indexer.read_only_clone()))`, taken at `brk_cli/src/main.rs:63` BEFORE the index
  loop). `Indexer::read_only_clone` does `stores: self.stores.clone()` (`brk_indexer/src/lib.rs:405`);
  cloning the fjall-backed `Store` does NOT yield a handle that tracks the writer's subsequent writes, so
  the served handle is a stale snapshot (count 0). This is the FIRST query endpoint that reads `stores`
  live-incrementally — `addr.rs:137` also reads stores but only works in release because the
  `#[cfg(not(debug_assertions))]` initial full sync (main.rs:41-57) populates the data BEFORE the clone
  is taken; orders announced AFTER startup (the order-book use case) are invisible to the frozen clone.
  Earlier "gettxout tip-relative" framing was NOT the cause here (offer was unspent throughout, verified
  by checkpoints A+B). **Fix direction:** make the btx read path see current state — re-open/refresh the
  `btx_orders` store from the durably-persisted db at query time (commit already calls
  `db.persist(SyncData)`), confirmed by reading the same dir with the `btx_book` example after stopping
  the server. (DIAG lines are temporary, marked `BTX-DIAG`, to be removed once fixed.)
- **RESOLVED + VERIFIED LIVE 2026-05-23.** Two BRK-core fixes landed and the end-to-end loop now works:
  node publishes an on-chain order -> brk_cli indexes it -> `GET /api/v1/btx/orders` returns the order
  JSON (verified via `btx_live_verify.sh`: `PASS: served 1 open order(s)`).
  - Fix 1 — durability: `brk_store::Store::commit_journaled` (+ called from `Stores::commit` for
    `btx_orders`) writes through fjall's normal journaled `insert`/`remove` instead of bulk
    `start_ingestion`. `db.persist(SyncData)` only fsyncs the journal, which the ingestion path
    bypasses, so ingested rows were not durable; journaled rows are. Proven: a fresh process re-opening
    the brkdir now reads the order.
  - Fix 2 — live serving: `check_xor_bytes` now skips `full_reset` when the index is empty
    (`blockhash.collect_last().is_none()`). On a fresh brkdir the missing `xor.dat` triggered a
    pointless `full_reset` that `remove_dir_all`'d the stores dir and re-opened the fjall `Database`
    on new files mid-run — orphaning the leaked read-only query clone onto the old, deleted DB (writer
    saw 1, query saw 0). With the guard, writer and query share the same `Database`; fjall `Keyspace`
    is `Arc`-shared so the clone sees committed writes. Query reverted to direct
    `self.indexer().stores.btx_orders` access (no per-request re-open needed).
  - Temporary `BTX-DIAG` instrumentation removed from btx.rs / lib.rs / brk_query.
  - Residual: a mid-run `full_reset` on an already-populated index (real xor change / "data
    inconsistency" branch in `index_`) would still orphan the clone until a restart — rare/pathological,
    not handled here. The robust long-term answer is refreshing the query clone after a reset.
- **GENUINE DESIGN LIMITATION (not a bug), filed as task #30.** Because `gettxout` is tip-relative, a
  fresh **full sync from scratch** will see `gettxout=None` at the announcement height for any order
  whose offer UTXO was later legitimately filled/cancelled, so it will **not** insert that order — the
  historical order book can't be fully reconstructed on initial sync. Live incremental indexing is fine
  (the announce block arrives while the offer is still unspent). Options to weigh on-machine: (a)
  validate the offer against the indexer's own output/UTXO vecs as of `height` instead of live
  `gettxout`; (b) accept live-only semantics and document it; (c) record announce-time validity
  separately from current spend status.

## Still remaining (genuinely)
- **`ord` cross-validation → DONE 2026-05-23, PASSED.** Installed ord 0.27.1, used `ord env` to spin
  a regtest bitcoind+ord, etched a real rune (COREXTESTRUNEAAA, id 231:1) via `ord wallet batch`,
  then built a transfer with `btx_runes.py`'s hand-encoded runestone (`6a5d0700e70101e80700` =
  edict 231:1 → 1000 → output 0). `ord`'s own index reported 1000 of the rune on output 0 — i.e.
  canonical ord interprets the BTX runestone exactly as intended. Runes encoding is fidelity-validated.
  Also validated a MULTI-edict runestone (`6a5d0f00e701010100000002010000e50702`): split the rune into
  lots 1/2/997 across outputs 0/1/2 in one tx; ord reported exactly that — so the delta-encoding of
  repeated edicts is correct, and maker-side lot-splitting works end-to-end on-chain.
- **Partial fills via denomination splitting** — design done (`BTX-partial-fills-design.md`).
  `group_id` field IMPLEMENTED: BTX artifact bumped to **v2** (group_id u64 after expiry, 0 =
  standalone), Python + both Rust parsers updated, fixtures regenerated, all tests pass incl.
  python-signed-v2-verifies-under-Rust. Lot aggregation is now a pure read-side query (the full
  artifact is in each CxoOrderRecord). Remaining: a maker-side "split into lots" helper + the
  query that groups by group_id. **DONE 2026-05-23:** maker-side `make_lots`/`lot_decomposition`
  (powers-of-two ladder sharing a group_id) in btx_0b.py, and read-side `group_summary`/
  `group_summary_from_store` in btx.rs (total/filled/open per group) — both unit-tested
  (Rust 5/5; Python decomp(11)=[1,2,8], lots share group_id). Partial fills are fully expressible.
- ~~Regulatory review (MAS)~~ — **cancelled by Renshu 2026-05-23** (not a tracked item).

## Known facts to carry forward
- BTX v1 artifact ≈ **200 bytes** (incl. 33-byte pubkey + ~72-byte DER sig) → needs relaxed
  `-datacarriersize` (e.g. 240) **or** a Taproot witness envelope. Carrier standardness in 2026
  is marked **[VERIFY]** in the spec.
- Several Runes specifics ([VERIFY]) are at/past the May-2025 knowledge cutoff — confirm against
  the live `ord`/Runes spec before relying on them.

## To resume on the node
1. `pip install python-bitcoinlib --break-system-packages`; copy the `.py` files over.
2. Run `run_swap.sh` (re-confirm 0a) then `run_runes.sh` (close the runestone-acceptance gap).
3. Work through `BTX-0b-runbook.md` two-node procedure → the Phase 0 exit gate.
4. Validate rune movement with `ord`, then wire `btx_index.rs::ChainAccess` to BRK.

## File index
- `BTX-architecture-and-build-sequence.md` — full architecture + phased plan
- `BTX-phase0-spec.md` — Phase 0 spec + all empirical-result sections
- `BTX-0b-runbook.md` — two-node no-relay exit-gate procedure
- `swap_test.py`, `run_swap.sh`, `swap_0a_result.log` — Milestone 0a (on-node)
- `btx_runes.py`, `run_runes.sh`, `runes_leg_result.log` — Runes asset leg
- `btx_0b.py` — artifact serialize/parse, on-chain verify, swap build, selftest
- `classify_test.py` — fill/cancel classifier proof
- `btx_index.rs` — BTX parser + order-book state machine + BRK seam (uncompiled sketch)
