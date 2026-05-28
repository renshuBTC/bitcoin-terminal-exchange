# BTX end-to-end audit prompts

These 14 prompts audit the entire BTX system from scratch — independent of the
2026-05-28 CoreX→BTX rename. The companion file [`BTX-rename-audit-prompts.md`](./BTX-rename-audit-prompts.md)
audits the *equivalence* of the rename; this file audits whether BTX itself
works, end to end, at every layer the codebase exposes.

Ordered cheapest → most expensive:

1. Offline test suite (full sweep) — seconds
2. Property fuzz at scale, multi-seed — under 2 minutes
3. Cross-implementation consensus-hash agreement (Python ↔ Rust) on adversarial corpora — minutes
4. Artifact-format adversarial / parser-DoS sweep — seconds
5. Runestone-decoder cenotaph adversarial cases — seconds
6. Live regtest publish → fill happy path, **both** carriers — ~5 minutes
7. Rune-backed offer end-to-end with ord oracle, positive + negative — ~10 minutes
8. Reorg rollback AND reopen (FILLED → OPEN restoration) — ~5 minutes
9. Indexer durability — restart from fjall, state recovers — ~5 minutes
10. Mempool standardness under **default** Core v29.1 policy, both carriers — ~5 minutes
11. `btxd` security guards — exhaustive (Host / Origin / Method / CSRF) — ~5 minutes
12. Light-client follower agrees with the BRK indexer on the cumulative event hash — ~5 minutes
13. GUI Merkle-proof verification — adversarial tamper (✓ on valid, ✗ on tampered) — ~10 minutes
14. Live **public** signet propagation — third-party node accepts the envelope under its default policy — ~30 minutes

Conventions:

- **PASS** = every listed pass criterion is observed empirically. No PASS-by-equivalence: each prompt must be run independently, not inferred from another's result.
- Each prompt is self-contained: goal, exact commands, pass criteria, and *why this matters*. Skip none; later prompts assume earlier ones have passed.
- If a command's flag or endpoint name has drifted since this doc was written, treat that as a finding ("doc out of sync with code") — *don't* paper over it by guessing the new name.

---

## Prompt 1 — Offline test suite (full sweep)

**Goal:** Confirm every offline test layer is green. These are the cheapest gates and any failure here invalidates the rest of the audit.

**Do:**

```bash
cd ~/Documents/Claude/Projects/bitcoin-terminal-exchange
python3 btx_test_all.py
python3 btx_selftest.py
python3 btx_xcheck.py
python3 btx_runes_xcheck.py

cd ~/Documents/Claude/Projects/brk-btx
cargo test -p brk_indexer btx::
```

**Pass criteria:**

- `btx_test_all.py` — all green, exit 0
- `btx_selftest.py` — all green, exit 0
- `btx_xcheck.py` — all green, exit 0 (Python ↔ Rust corpus agreement)
- `btx_runes_xcheck.py` — all green, exit 0 (rune decode/encode cross-check)
- `cargo test btx::` — `0 failed`

Record the actual pass counts; drift from earlier runs is itself an audit finding.

**Why this matters:** these tests pin the canonical event/leaf strings, the hash-domain tag bytes (`0x00` leaf, `0x01` node, `0x03` event), and parser/serializer symmetry. They're the foundation everything else stands on.

---

## Prompt 2 — Property fuzz at scale, multi-seed

**Goal:** Beyond example-based goldens, the six security-critical invariants in `btx_fuzz.py` must hold over millions of random inputs across independent seeds — not just the default seed.

**Do:**

```bash
cd ~/Documents/Claude/Projects/bitcoin-terminal-exchange
BTX_FUZZ_ITERS=200000 BTX_FUZZ_SEED=1234  python3 btx_fuzz.py
BTX_FUZZ_ITERS=50000  BTX_FUZZ_SEED=99999 python3 btx_fuzz.py
BTX_FUZZ_ITERS=50000  BTX_FUZZ_SEED=2026  python3 btx_fuzz.py
```

**Pass criteria:** for each invocation, all six campaigns report `[PASS]` and the run ends with `ALL CLEAN`. Total: ≥1.8M property assertions across:

1. Runestone decoder does not raise on arbitrary bytes (indexer DoS resistance).
2. Runes allocator is conservative, non-negative, and deterministic.
3. `book_hash` is order-set-independent and stable.
4. Artifact `serialize` ↔ `parse` round-trip preserves every field.
5. Taker-swap builder conserves value, places `(price, payout_spk)` at output 0, RBF-signals the funding input, and rejects sub-dust taker outputs.
6. Runestone `encode` ↔ `decode` round-trips clean (not flagged cenotaph).

**Why this matters:** the rename audit verified equivalence on a fixed corpus. End-to-end safety needs property-style coverage so a malicious input the corpus didn't think of can't crash the indexer or steal a maker's funds.

---

## Prompt 3 — Cross-implementation consensus-hash agreement on adversarial corpora

**Goal:** `book_hash`, `book_root`, and `cumulative_event_hash` must agree byte-for-byte between Python (`btx_orderbook.py`, `btx_light_client.py`) and Rust (`brk_indexer btx::`) not just on the canonical golden corpus, but on adversarially-shaped inputs: empty books, single-order books, large books, duplicate orders, edge values (`amount = 0`, `price = u64::MAX`, `announce_height = 0`).

**Do:**

```bash
cd ~/Documents/Claude/Projects/bitcoin-terminal-exchange
python3 btx_xcheck.py        # baseline corpus
python3 btx_eventhash_test.py # cumulative event-hash cross-check
```

Additionally, construct a one-off adversarial driver: generate ~1000 random order books with sizes 0 … 200, run Python `book_hash`, then drive the same orders through the Rust indexer (or its `btx_book` example) and compare the resulting `/api/v1/btx/book-hash` byte-for-byte.

**Pass criteria:**

- Every adversarial book yields identical hex strings between Python and Rust.
- A test case at `n = 0` (empty book) yields the empty-SHA-256 sentinel `e3b0c44298…`.
- Duplicate orders are handled identically in both implementations (either both dedupe, or both don't).

**Why this matters:** the consensus hash is what lets two independent indexers prove agreement. If Python and Rust diverge on any input — even one no real chain has produced yet — a future order could split the network of indexers. This is BTX's main "do we have consensus?" property.

---

## Prompt 4 — Artifact-format adversarial / parser-DoS sweep

**Goal:** A malicious artifact must NEVER crash the indexer, leak memory, or be admitted to the book. Construct malformed artifacts and assert each is rejected (returned as `None` / error / skipped), not parsed or stored.

**Do:** In `bitcoin-terminal-exchange/`, write a short driver that hands each of these to `btx_0b.parse_artifact`:

1. Wrong MAGIC: prepend `FF FF FF FF` instead of `42 54 58 31`.
2. Truncated body: BTX1 MAGIC followed by 4 bytes (no version/fields).
3. Over-long body: 100 KB random bytes after BTX1 MAGIC.
4. Sub-dust price: `price = 0`, `price = 545`.
5. Zero amount: `amount = 0`.
6. Bogus `sighash_flag`: `0x00`, `0x01`, `0xFF` (not `0x83`).
7. DER-malformed `maker_sig`: random 71 bytes that don't decode as DER.
8. `payout_spk` empty (zero-length).
9. `maker_pubkey` not 33 bytes (32, 34, 65 bytes).
10. Inconsistent rune fields: `rune_block = 0` but `rune_tx > 0`.

Then for the subset that *can* be broadcast on regtest (those that pass policy at the carrier level), publish them via OP_RETURN, mine, and run `brk_cli` against the chain.

**Pass criteria:**

- Every malformed input returns falsy / raises a defined error from `btx_0b.parse_artifact` (no Python tracebacks, no panics).
- After indexing the chain that contains the broadcast-able subset, `GET /api/v1/btx/orders` returns `[]`.
- Indexer logs contain no `panicked at` / `unwrap` traces.

**Why this matters:** the artifact parser is the BTX-side trust boundary against untrusted chain data. A panic here = indexer DoS; an admit-by-accident = a forged order in the book.

---

## Prompt 5 — Runestone-decoder cenotaph adversarial cases

**Goal:** `btx_runes_decode.decode_runestone` must correctly classify malformed runestones as cenotaphs and return non-empty `cenotaph_reasons`. False-accepts (treating a cenotaph as a clean runestone) are a consensus risk: the BRK indexer would credit runes that ord wouldn't.

**Do:** Feed `decode_runestone` each of these:

1. Varint overflow in an edict's `amount` field (more than 18 bytes).
2. Unrecognized tag in even position (per ord rune protocol: even-tag unknown = cenotaph).
3. Edict block-delta that overflows `u32` when added to the previous block.
4. Truncated OP_RETURN: `6a 5d` with no payload.
5. Multiple OP_PUSHDATA frames inside one runestone with mismatched lengths.

**Pass criteria:** for every input, `d.get("cenotaph") is True` AND `d.get("cenotaph_reasons")` is a non-empty list with a human-readable reason. No false-clean classifications.

**Why this matters:** ord and the BTX indexer share the rune-credit semantics. If BTX's decoder is laxer than ord's (treats a cenotaph as clean), BTX would back orders with runes that don't exist per the canonical ord view. This was a real fix earlier in the project (audit task #116) — re-verify it stuck.

---

## Prompt 6 — Live regtest publish → fill, both carriers

**Goal:** A complete maker-publish → indexer-ingest → taker-fill → FILLED-detection lifecycle works on a real (regtest) chain via *each* carrier, independently.

**Do:** For each carrier ∈ {`op_return`, `envelope`}:

1. Start a fresh regtest `bitcoind` v29.1; create a wallet; mine 101 blocks to maturity.
2. `btx_wallet.py maker-sign` an offer (sell 1000 sats for 100_000 sats, P2WPKH payout).
3. Verify the signed artifact: `artifact_hex` starts with `42545831` (BTX1 MAGIC). Maker self-sig verifies (no node call required).
4. Publish:
   - OP_RETURN carrier: broadcast via `bitcoin-cli sendrawtransaction`.
   - Envelope carrier: `btx_envelope_publish.py publish --broadcast …` (commits + reveals).
5. Mine 1 block, run `brk_cli` to ingest. Confirm `GET /api/v1/btx/orders` returns exactly 1 OPEN order with the right `announce_height`, `price`, `amount`, `offer_txid:offer_vout`.
6. `btx_wallet.py taker-fill` (or batch-fill with N=1) to settle on-chain.
7. Mine 1 block; re-index. Confirm `GET /api/v1/btx/orders` now returns `[]` (FILLED detection fired).
8. Cancel test (optional but recommended): publish a second order, then double-spend the offer UTXO via `bitcoin-cli`. After re-index, that order disappears too (cancel-by-double-spend).

**Pass criteria:** each carrier independently completes steps 1 – 7 end-to-end with zero manual intervention; the FILLED transition is observed via API, not inferred from chain state.

**Why this matters:** the two carriers represent different policy surfaces (OP_RETURN ≤80B, Taproot witness envelope ≤400 kWU effective). Both must be production-ready; betting on only one is a single point of policy failure.

---

## Prompt 7 — Rune-backed offer with ord oracle, positive + negative

**Goal:** When a maker offers runes (not just sats), the indexer must verify the offer UTXO actually holds the advertised rune quantity per the canonical ord oracle. Over-advertising must be refused at sign-time and at the indexer.

**Do:** With ord 0.27.1 + bitcoind v29.1 on regtest:

1. `btx_etch.py etch --rune BTXAUDITRUNES --premine 1000 --broadcast` (rune name must be ≥13 chars at height 101).
2. After ord indexes it, find the rune id and the premine UTXO.
3. **Positive:** `btx_wallet.py maker-sign --ord-url http://… --require-rune-backing --amount-units 1000 …` signs.
4. **Negative:** repeat with `--amount-units 1001`. The call MUST refuse with the message `assert_offer_backs_rune` and quote the actual vs advertised quantity.
5. Publish the positive artifact, taker-fill, mine. Query ord: taker output holds the runes, maker output holds the BTC, offer UTXO is null.

**Pass criteria:**

- Negative case errors out with a clear refusal message; nothing is broadcast.
- Positive case completes; ord's post-fill state confirms the rune redistribution.

**Why this matters:** without this check, a maker could publish a 1M-rune offer backed by 0 runes and steal taker BTC. The ord oracle is the BTX-side defense.

---

## Prompt 8 — Reorg rollback AND reopen

**Goal:** The rename audit verified `Stores::rollback_btx_orders` removes orders when their announce block is invalidated. The end-to-end audit must additionally verify the *reopen* path: when a fill block is invalidated, the order goes FILLED → OPEN.

**Do:**

1. Bring up regtest. Publish an offer (call its height `H_a`).
2. Mine to height `H_a + 1`. Confirm `GET /api/v1/btx/orders` → 1 OPEN.
3. Taker-fill. Mine to `H_a + 2 = H_f`. Confirm orders → `[]` (FILLED).
4. `bitcoincli invalidateblock <H_f>` and mine 2 empty blocks to outweigh the orphan.
5. Re-run `brk_cli`. Look at the BTX reorg log line.
6. Confirm `GET /api/v1/btx/orders` → 1 OPEN again.

**Pass criteria:**

- Indexer logs a `BTX rollback @ height H_f: removed 0 order(s), reopened 1` line (i.e. `reopened > 0`).
- Post-rollback API returns the order with its original `announce_height = H_a`.

**Why this matters:** reorgs that strand a fill in an orphan must restore the offer to the book; otherwise a deep reorg would silently delete liquidity. This is a strictly harder property than rollback-of-announce (which is what `run_btx_reorg.sh` and the rename audit cover).

---

## Prompt 9 — Indexer durability across restart

**Goal:** The on-disk fjall `btx_orders` store survives a clean `brk_cli` restart with no state loss.

**Do:**

1. Publish an offer, mine, index. Confirm `GET /api/v1/btx/orders` → 1 OPEN with the right fields.
2. Send SIGTERM to `brk_cli`; wait for clean shutdown.
3. Start `brk_cli` again with the same `--brkdir`.
4. Confirm `GET /api/v1/btx/orders` → 1 OPEN, with identical `announce_height`, `price`, `amount`, `offer_txid`, `offer_vout`, `book_hash`.
5. Repeat with a hard kill (SIGKILL) mid-operation to test crash recovery.

**Pass criteria:** API state pre-restart === post-restart for every observable field. `book_hash` is byte-identical across restart. No fjall corruption messages in logs.

**Why this matters:** an indexer that loses state on restart is unusable in production — it would re-scan from genesis and could have a window during which the API returns an inconsistent / empty book.

---

## Prompt 10 — Mempool standardness under default Core v29.1 policy, both carriers

**Goal:** Both carriers must be accepted by a Bitcoin Core v29.1 node started with **default** mempool policy — no `-datacarriersize=240`, no `-acceptnonstdtxn`. This is what determines whether a third-party relay will propagate a BTX publish.

**Do:**

1. Start `bitcoind -regtest` with **no** custom policy flags.
2. Build the OP_RETURN carrier tx (≤80 B datacarrier limit applies).
3. Build the envelope carrier tx (Taproot script-path witness, no OP_RETURN).
4. For each: `bitcoin-cli testmempoolaccept '[<hex>]'`.

**Pass criteria:**

- OP_RETURN tx with body ≤80 B: `allowed: true`.
- Envelope reveal tx with the BTX1-magic artifact (any size in policy budget): `allowed: true`.
- Same OP_RETURN tx with body >80 B: `allowed: false` AND `reject-reason: scriptpubkey` or similar — this confirms the policy boundary is observed, not skipped.

**Why this matters:** "we work if you set this flag" is not a production claim. The audit must show BTX is mempool-policy-compatible against a stock node.

---

## Prompt 11 — btxd security guards — exhaustive

**Goal:** Beyond the 200/403/403 happy/forged-Host/forged-Origin probe, every protective layer in `btxd.py` is in force on every route.

**Do:** Start `btxd.py --port 3333` against a minimal stack. Then:

1. **Host-allowlist (DNS rebinding):** `curl -H 'Host: 127.0.0.1:3333' http://127.0.0.1:3333/api/config` → 200. Same URL with `Host: evil.example` → 403. Repeat the forged-Host test against `/api/v1/btx/orders`, `/api/dex/book`, `/api/order/create`. All 403.
2. **Origin-allowlist (CSRF):** POST to `/api/order/create` with `Origin: https://attacker.com` → 403. POST with no `Origin` header at all → 403 (browsers always set it for cross-origin POSTs; absence = suspicious). POST with `Origin: http://127.0.0.1:3333` → 200 (or a defined business-logic error code, not 403).
3. **Method allowlist:** `OPTIONS` to a POST route returns either a 200 preflight with an explicit `Access-Control-Allow-Methods` whitelist, or 405. Never a 200 with `*`.
4. **No secret leak:** every 403 / 405 / 500 response body contains no session id, no API key, no internal path.
5. **No `eval` / `Function` in served JS:** `grep -rn "eval(\|new Function(" *.html` returns no hits in any served page.

**Pass criteria:** every route enforces Host + Origin + Method allowlists; no secret leaks across any error path; no dynamic-code-evaluation in served pages.

**Why this matters:** `btxd` is a localhost bridge between a user's browser and their wallet/node. DNS rebinding and CSRF are the realistic attacks on that surface; this prompt verifies the defenses cover every route, not just the ones tested earlier.

---

## Prompt 12 — Light-client follower agrees with the BRK indexer

**Goal:** `btx_light_client.py` consumes `/event-stream` and reconstructs the cumulative event hash *from events alone* — no chain access. It must agree byte-for-byte with the BRK indexer's `cumulative_event_hash`, across an announce + fill + cancel lifecycle.

**Do:**

1. Bring up the full stack (bitcoind regtest + `brk_cli` + `btxd`).
2. Drive a sequence of events: publish 3 offers, fill 1, cancel-by-double-spend 1. Mine after each step.
3. After each block, query `/api/v1/btx/cumulative-event-hash` (or equivalent) on the BRK side.
4. Independently, run `btx_light_client.py` against `/event-stream`. After each block, get its computed cumulative hash.
5. Compare the two streams of hashes.

**Pass criteria:** at every block, the two cumulative hashes match byte-for-byte. The light client never has to call the node directly.

**Why this matters:** BTX's light-client claim is that someone running only a phone-grade follower can verify the book state without trusting the indexer. If the follower and indexer disagree, that claim is false.

---

## Prompt 13 — GUI Merkle-proof verification, adversarial tamper

**Goal:** The browser-side Merkle verifier in the trade terminal must reject tampered proofs and tampered roots — not just accept the valid ones.

**Do:** With the full stack up and the trade terminal open in a browser:

1. **Baseline:** publish an order, mine. Confirm the order row renders `✓ order verified in root`. Confirm `book_hash` shown in the panel matches `GET /api/v1/btx/book-hash`.
2. **Tamper the proof:** in DevTools, intercept the response from `/api/dex/order-proof` (or whatever the trade page calls). Flip one bit in the sibling-hash chain. Re-render. The verifier MUST switch to `✗ proof invalid` (or equivalent), NOT `✓`.
3. **Tamper the root:** point the page at a fabricated `book_root` value. Verifier MUST reject.
4. **Empty book:** with no orders, the panel should show `e3b0c44298…` (empty-SHA-256). Adding 1 order then removing it (fill) should return to that exact sentinel.

**Pass criteria:** every tamper produces ✗. The empty-book sentinel is preserved across publish → fill round-trips. The browser is verifying, not rendering.

**Why this matters:** a GUI that only renders a server-supplied "✓" is theater. The verifier has to *fail* on bad input for the badge to mean anything.

---

## Prompt 14 — Live public signet propagation

**Goal:** The strongest possible real-world acceptance test: a BTX envelope publish broadcast from one node propagates across the public signet to a node we don't control, under that node's default policy.

**Do:**

1. Bring up two signet nodes:
   - Node A: your machine, default policy.
   - Node B: any reachable public signet node — a friend's, an Umbrel, a signet block explorer's mempool endpoint, or rent a VPS and run stock `bitcoind -signet`. The point is **Node B is not under your config control.**
2. Connect A to B as a peer; confirm with `getpeerinfo`.
3. On Node A, `btx_envelope_publish.py publish --network signet --broadcast` an offer artifact.
4. On Node B (only), `bitcoin-cli getrawmempool` should show the reveal tx within ~10 seconds.
5. Mine 1 signet block (faucet / mining pool). The tx confirms.
6. (Optional, slow) Run `brk_cli` against public signet to ingest, then `GET /api/v1/btx/orders` should show the order.

**Pass criteria:**

- Node B's mempool contains the reveal txid that Node A broadcast.
- No `-datacarriersize`, `-acceptnonstdtxn`, or similar flag on Node B.
- A block miner accepted the tx into a signet block (i.e. miners' default mempool policy admits it too).

**Why this matters:** propagation under default policy across an out-of-your-network node is the empirical version of the policy-compatibility claim. The OP_RETURN carrier has had this since signet day-1; the envelope carrier needs this proof too. Without it, "BTX runs on Bitcoin without changes" is unproven.

---

## Recording results

For each prompt, capture in a results file (e.g. `BTX-end-to-end-audit-results.md`):

- Prompt number and one-line outcome (`PASS` / `FAIL` / `BLOCKED — <reason>`).
- The exact commands run (so the audit is reproducible).
- Key on-chain identifiers (txids, block hashes, heights) for the live prompts.
- Any finding that wasn't covered by the prompt itself (e.g. doc-out-of-sync notes from Prompt 1's "drift" check, or a third-party node owner's quote for Prompt 14).

The audit is closed when all 14 are empirically PASS with no PASS-by-equivalence and no untriaged findings.
