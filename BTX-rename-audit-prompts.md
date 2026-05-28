# BTX rename — audit prompts

Standalone, copy-paste-ready prompts for verifying that **Bitcoin Terminal Exchange (BTX)** behaves exactly as **CoreX** did before the 2026-05-28 rename. Each prompt is self-contained: paste into a fresh Claude session (or run the commands yourself) and it should execute without additional context.

## Rename context (background for any auditor)

On 2026-05-28 the project was rebranded **CoreX → BTX** and moved into two new PRIVATE GitHub repos:

- `renshuBTC/bitcoin-terminal-exchange` (Python tooling + frontend; replaces public `bitcoin-corex`)
- `renshuBTC/brk-btx` (BRK fork with the BTX indexer + serving; replaces public `brk-corex`)

Local working trees:

- `~/Documents/Claude/Projects/bitcoin-terminal-exchange`
- `~/Documents/Claude/Projects/brk-btx`

Consensus-level changes from the rename:

- **MAGIC bytes:** `CXO1` → `BTX1` (hex `43584f31` → `42545831`)
- **Fjall on-disk store key:** `cxo_orders` → `btx_orders` (new repo starts with a fresh state dir)
- **HTTP routes:** `/api/v1/cxo/*` → `/api/v1/btx/*`
- **All filenames + Rust modules + Python identifiers:** `corex_*` → `btx_*`, `cxo` → `btx`

The rename was proven mechanical: post-rename `book_hash`, `book_root`, `cumulative_event_hash`, and `event_stream` goldens are **byte-identical** between Python and Rust, which is only possible if no `corex`/`cxo` literal sat inside any canonical event string.

Pre-rename anchors (numbers to match):

- Python: `btx_selftest.py` 43/43, `btx_test_all.py` 14/14 suites, `btx_xcheck.py` 8/8 corpus entries
- Rust: `cargo test -p brk_indexer btx::` 32/32 (including the 4 PYTHON_GOLDEN cross-tests)

Public-signet propagation proof (pre-rename): reveal `60e969a3ad65a182faabf8e61f0902aeb607b50c53f7ca1be56e483faf9a63e3`, mined in block **305,837** under default Core v29.1 relay policy.

---

## Tiered execution

| Tier | Cost | Confidence | Prompts |
|---|---|---|---|
| 1 — Offline | <5 min, no setup | Catches direct rename misses | 1, 2, 3, 4 |
| 2 — Single-node regtest | ~1 h, needs bitcoind + ord | Catches behavioral regressions | 5, 6, 7 |
| 3 — Local UI | ~30 min, needs running btxd | Catches surface-level wiring | 8, 9 |
| 4 — Multi-node signet | ~2 h, needs two nodes | Catches the strongest network claim | 10 |

Running 1–4 covers ~90% of rename risk. 5–7 catch behavioral regressions in the live lifecycle. 8–9 catch GUI/orchestrator surface wiring. 10 re-validates the public-signet relay claim.

---

## Prompt 1 — Offline test suite parity

```
Context: I renamed CoreX → BTX in two new private repos (bitcoin-terminal-exchange,
brk-btx) on 2026-05-28. MAGIC bytes changed CXO1→BTX1, store key cxo_orders→btx_orders.
At rename time, 43/43 btx_selftest, 14/14 btx_test_all, 8/8 btx_xcheck passed.

Goal: confirm those numbers haven't drifted.

Do:
  cd ~/Documents/Claude/Projects/bitcoin-terminal-exchange
  python3 btx_selftest.py
  python3 btx_test_all.py
  python3 btx_xcheck.py
  python3 btx_runes_xcheck.py

Pass: same counts (43/43, 14/14, 8/8) and any sub-suites that had specific
totals previously. If any drop, isolate which suite and read its first failing
assertion — that's where the rename touched something it shouldn't have.
```

---

## Prompt 2 — Rust indexer test parity

```
Context: post-rename, brk-btx Rust tests passed 32/32 in btx:: +
xcheck_corpus_matches_golden, including book_hash_matches_python_golden,
book_root_matches_python_golden_and_proofs_verify, cumulative_event_hash_matches_python_golden,
event_stream_matches_python_golden — the bit-identical cross-impl proof.

Goal: confirm those goldens still match. If any of the four PYTHON_GOLDEN tests
fails, the rename silently changed a canonical input — high-priority bug.

Do:
  cd ~/Documents/Claude/Projects/brk-btx
  CARGO_TARGET_DIR=$HOME/brk-btx-target cargo test -p brk_indexer btx::
  CARGO_TARGET_DIR=$HOME/brk-btx-target cargo test -p brk_indexer xcheck_corpus_matches_golden

Pass: 32/32 in btx::; xcheck corpus passes. Report any failure verbatim including
the assertion message — those messages tell you which byte diverged.
```

---

## Prompt 3 — Stragglers sweep (code + identifiers)

```
Context: the rename script substituted ~22 token rules. Anything it missed will
silently degrade. Looking for survivors.

Goal: zero references to old identifiers in either repo's tracked files.

Do (in both ~/Documents/Claude/Projects/bitcoin-terminal-exchange and ~/Documents/Claude/Projects/brk-btx):
  git ls-files | xargs grep -nE '\b(corex|cxo|CoreX|COREX|CXO)\b' 2>/dev/null
  git ls-files | xargs grep -n '43584f31' 2>/dev/null
  git ls-files | xargs grep -nE '/api/v1/cxo/' 2>/dev/null
  # Tag-split brand patterns: \bCoreX\b won't catch `Core<span>X</span>` because the
  # word "Core" isn't followed by "X" in the underlying text. Brand logos often style
  # the last letter differently. Catch those:
  git ls-files | xargs grep -nE '>Core<|Core<(b|i|span|em)' 2>/dev/null

Pass: zero hits across all three patterns in each repo. Any hit means the rename
left a survivor — report file + line, decide whether to substitute, leave (e.g.
comments about "the old code"), or treat as a real bug.
```

---

## Prompt 4 — Hash-stability against pre-rename goldens

```
Context: the strongest correctness claim of the rename is that book_hash,
book_root, cumulative_event_hash, and event_stream goldens are *byte-identical*
to the pre-rename CoreX values. The Rust tests anchor this on goldens shipped
in the repo. This prompt re-derives the same hashes from the Python side and
confirms they match the Rust goldens AND the pre-rename CoreX values
(reproducible from the old public bitcoin-corex repo).

Goal: prove the canonical event/leaf strings never carried a `cxo`/`corex` literal.

Do:
  cd ~/Documents/Claude/Projects/bitcoin-terminal-exchange
  python3 btx_eventhash_test.py
  python3 btx_orderbook_test.py
  # then compare the Python-emitted goldens to the corex_* equivalents in the
  # public bitcoin-corex repo (clone it read-only if you don't have it)
  diff <(python3 btx_eventhash_test.py 2>&1 | grep -E '^[0-9a-f]{64}$') \
       <(cd ~/path/to/bitcoin-corex && python3 corex_eventhash_test.py 2>&1 | grep -E '^[0-9a-f]{64}$')

Pass: empty diff. If non-empty, the rename changed a canonical input — find
which line in btx_orderbook.py or btx_light_client.py emits a different string.
```

---

## Prompt 5 — Live regtest publish → fill, both carriers

```
Context: rename verified offline + via golden hashes, but the full live-lifecycle
harness wasn't re-run end-to-end post-rename. The harness lives in btx_live_verify.sh
and exercises: bitcoind regtest → brk_cli → maker publishes (OP_RETURN, then envelope)
→ /api/v1/btx/orders serves it → taker fills → /history shows FILLED.

Goal: prove a real coin moved through the full pipeline.

Do:
  cd ~/Documents/Claude/Projects/bitcoin-terminal-exchange
  # arg is positional; valid values are bare "op_return" or "envelope" (default: op_return)
  ./btx_live_verify.sh op_return
  ./btx_live_verify.sh envelope

Prereqs:
  - bitcoind + bitcoin-cli on PATH (or in /tmp/bitcoin-*/bin or ~/bitcoin*/bin)
  - brk-btx repo cloned at $BRK (defaults to ~/Documents/Claude/Projects/brk-btx)
  - cargo available (the harness shells out to `cargo run -p brk_cli`)
  - btx tooling at $BTX (defaults to ~/Documents/Claude/Projects/bitcoin-terminal-exchange)

Pass: each run ends with "FILLED" and a single settlement txid. If anything
errors (subprocess args wrong, /api/v1/btx/orders 404, parse failure), the
rename missed a path — capture the exact error.
```

---

## Prompt 6 — Live regtest rune trade end-to-end (etch + addressed swap)

```
Context: the Phase 5 live trade proof (2026-05-26 regtest) etched a rune via
btx_etch.py, ord indexed it, maker-sign --ord-url validated backing, taker-fill
moved the rune via runestone edict. Post-rename: btx_etch.py is the renamed
corex_etch.py; ord doesn't know anything changed.

Goal: re-run the proof. If anything breaks here, the rename clipped a piece of
the ord-oracle or runestone-edict path.

Do:
  # Bring up regtest bitcoind + ord --index-runes server
  python3 btx_etch.py etch --rune BTXAUDITRUNES --premine 1000 --divisibility 0 --symbol '$' --chain regtest
  # confirm via ord that the rune indexed
  curl -s "http://127.0.0.1:8089/rune/BTXAUDITRUNES" | jq
  # maker-sign with --ord-url --require-rune-backing pointing at the etch's output 0
  # taker-fill, broadcast, confirm the rune lands at the taker

Pass: ord reports the etch + the post-trade /output/<swap>:1 shows BTXAUDITRUNES:1000
at the taker, /output/<swap>:0 shows runes:{} at the maker. Same shape as the
COREXUSDTESTS trade from before the rename.
```

---

## Prompt 7 — Reorg rollback safety

```
Context: btx_orders is a persistent fjall store. cxo_rollback_plan was renamed
to btx_rollback_plan and still drives store rollback on reorg. The example
crates/brk_indexer/examples/btx_reorg.rs drives a live reorg via invalidateblock.

Goal: prove a live reorg still removes the orphaned order. Pre-rename: RUN1 → 1 OPEN,
invalidateblock → RUN2 → 0 OPEN. Must reproduce.

Do:
  cd ~/Documents/Claude/Projects/bitcoin-terminal-exchange
  ./run_btx_reorg.sh
  # The wrapper drives: regtest bitcoind -> fund maker -> publish a BTX order ->
  # mine the announce -> build & run the btx_reorg example (RUN 1: prints the
  # btx_orders store) -> invalidateblock the announce + mine 2 empty blocks
  # (announce orphaned, not re-mined) -> re-run the example (RUN 2: exercises
  # Stores::rollback_btx_orders).

Pass: RUN 1 prints "BTX_ORDER_COUNT 1" and "BTX_ORDER offer=... status=OPEN
announce_height=H".  RUN 2 prints "BTX_ORDER_COUNT 0" (the orphaned order was
rolled back), plus a "BTX rollback ... removed N=1" log line proves
rollback_btx_orders fired.  Script ends with "DONE_BTX_REORG".
```

---

## Prompt 8 — btxd orchestrator + security guards

```
Context: btxd binds 127.0.0.1, enforces a Host: allowlist (DNS-rebinding guard),
an Origin allowlist on mutating POSTs (CSRF guard), and a --max-hot-balance-btc
rail. All of those were rename-touched (the binary is now btxd not corexd,
classes/functions renamed).

Goal: confirm the daemon still starts clean and the guards still work.

Setup:
  export PATH="$HOME/bitcoin-29.1/bin:$PATH"
  export RT="$HOME/btx-p8-regtest"; mkdir -p "$RT"
  CLI="bitcoin-cli -regtest -datadir=$RT"
  bitcoind -regtest -datadir="$RT" -fallbackfee=0.0002 -server -daemon; sleep 2
  $CLI createwallet btx 2>/dev/null || $CLI loadwallet btx
  $CLI generatetoaddress 1 "$($CLI -rpcwallet=btx getnewaddress "" bech32)" >/dev/null

Do:
  cd ~/Documents/Claude/Projects/bitcoin-terminal-exchange
  python3 btxd.py --bitcoin-cli "$(command -v bitcoin-cli)" --chain regtest \
      --datadir "$RT" --wallet btx --brk-url http://127.0.0.1:9999 \
      --port 3333 > /tmp/btxd-test.log 2>&1 &
  BTXD_PID=$!
  sleep 2

  # legitimate request (expect 200; /api/config is btxd-native, no proxy)
  curl -s -o /dev/null -w 'test1=%{http_code}\n' http://127.0.0.1:3333/api/config

  # forged Host (expect 403; DNS-rebinding guard)
  curl -s -H 'Host: evil.com' -o /dev/null -w 'test2=%{http_code}\n' http://127.0.0.1:3333/api/config

  # cross-origin POST without correct Origin (expect 403; CSRF guard).
  # /api/order/create is the actual mutating route.
  curl -s -X POST -H 'Origin: https://attacker.example' \
       -H 'Content-Type: application/json' -d '{}' \
       -o /dev/null -w 'test3=%{http_code}\n' http://127.0.0.1:3333/api/order/create

  # teardown
  kill $BTXD_PID 2>/dev/null
  $CLI stop 2>/dev/null
  rm -rf "$RT" /tmp/btxd-test.log

Pass: test1=200 / test2=403 / test3=403 in that order. Same outcome as before the
rename. Any deviation means the guard string-matching code now references the wrong
identifier (e.g., still checks "Host: corexd.local" instead of "btxd.local").

---

## Prompt 9 — Terminal (`btx_trade.html`) end-to-end smoke

```
Context: the trading terminal calls /api/v1/btx/orders, /book-hash, /book-root,
/order-proof, /event-stream — all renamed routes. It also computes the book root
in JS and verifies it matches the served root. Post-rename: every JS string
reaches a renamed Rust handler.

Goal: confirm a live book renders, the cross-indexer "agreement" badge flips green,
and a fill from the GUI completes.

Do:
  # bring up: bitcoind regtest + brk_cli + btxd + open btx_trade.html
  # publish an order via the GUI's "Publish" panel
  # observe: row appears in the order book, badge shows "indexer agreed", click row to
  # see "✓ order verified in root" (Merkle proof verification in-browser)
  # fill the row, confirm the row moves to /history with FILLED

Pass: all UI states (book row, agreement badge, proof badge, FILLED entry) light
up the same as before the rename. A red badge or missing row means a JS fetch
or a Rust route name didn't match.
```

---

## Prompt 10 — Custom-signet cross-node witness-envelope propagation

```
Context: the strongest network-facing claim is that a BTX witness-envelope order
relays under default Bitcoin Core v29.1 policy across foreign nodes (proven on
public signet at the rename time: reveal 60e969a3…, mined block 305837, by an
independent signer). The OP_RETURN carrier wouldn't have relayed because the
artifact is 207 bytes > 80-byte default. This proof relied on the carrier shape
under MAGIC=CXO1; post-rename MAGIC=BTX1, the envelope shape is identical (still
just opaque bytes inside an OP_FALSE OP_IF push), but it's worth re-running
because a single byte-length miscount would defeat the standardness check.

Goal: republish on custom signet (the cheaper proof) or public signet (the
strong proof), watch it relay.

Do:
  # set up two custom signet nodes (or one custom + one public)
  # publish a BTX1 envelope order from node A
  # confirm node B's mempool admits it via getrawmempool
  # mine a block on either side, confirm the reveal indexes into /api/v1/btx/orders
  # on a clean brk_cli sync from the same chain

Pass: the reveal tx appears in node B's mempool within seconds, mines into a block,
and the order surfaces from /api/v1/btx/orders on a clean re-index. If node B
rejects with "datacarrier" or "scriptpubkey" reasons, the envelope shape is wrong
post-rename.
```
