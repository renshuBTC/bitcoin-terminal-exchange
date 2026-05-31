# Bitcoin Terminal Exchange

A **server-less, on-chain order-book DEX for Bitcoin**. Makers publish `SIGHASH_SINGLE|ANYONECANPAY`
pre-signed offers as on-chain artifacts; the order book is reconstructed by the node's own indexer
from chain data — no exchange, no order-relay or gossip network, no server, no escrow (orders still
propagate over Bitcoin's own P2P relay like any transaction). Settlement is a single native Bitcoin
transaction. Trust-minimized to Bitcoin alone (no token, no middleman; first valid spender wins).

What it does today:

- **Open limit orders** — publish a pre-signed offer once, go offline; *any* taker fills it in one tx.
- **Batch fills** — one taker sweeps many maker offers in a single transaction (each maker's `0x83`
  pre-signature composes, since it commits only to its own offer-input + payout-output).
- **Rune↔BTC and rune↔rune** — sell a Rune for BTC (open order), or swap rune-A for rune-B via the
  addressed (interactive, snipe-resistant) path. Counter-asset is an issuer's Rune; no BTX token.
- **A verifiable, consensus-hashed book** — the `brk-btx` indexer reconstructs the book from chain
  and serves a content hash (`/api/v1/btx/book-hash`) that any independent indexer over the same chain
  reproduces identically. Demonstrated live on a real **regtest** book: an independent Python chain
  reconstruction and the Rust indexer produced the identical hash.
- **A Merkle-committed book + membership proofs** — beyond the flat hash, the book is committed to a
  SHA-256 Merkle **root** (`/api/v1/btx/book-root`), so a client can verify a single served order with a
  log-sized proof (`/api/v1/btx/order-proof/{txid}/{vout}`) — no full book download, no full node. The
  terminal verifies each row in-browser and flips the badge to "✓ order verified in root". Verified to
  produce the identical root across Python, Rust, and the browser JS on the golden fixtures
  (golden-cross-tested; the canonical-leaf byte layout is verified to match).
- **A cumulative event hash + per-block stream** — a rolling commitment over the whole
  announce/fill/cancel stream (`/api/v1/btx/event-hash`), plus a per-block listing
  (`/api/v1/btx/event-stream` → `[{height, block_hash, cumulative}]`) a light client folds to follow the
  book incrementally and resume from any checkpoint, detecting reorg/omission. Pure function of the
  chain; Python and Rust produce the identical hash on the golden fixtures (golden-cross-tested).
- **A Hyperliquid-style terminal** (`btx_trade.html`) — order book with depth, divisibility-
  normalized prices, multi-select batch fill, publish/fill/etch/OTC/rune↔rune panels, and a live
  cross-indexer "agreement" badge. Self-custody throughout (signs via your own Bitcoin Core wallet).
- **A live on-chain DEX-activity feed** — the indexer flags likely Runes marketplace fills
  (a `0x83` pre-signed input + a runestone edict) and pending mempool orders, so the terminal shows
  real on-chain trade flow, not just the BTX-native book. Heuristic; real data on a mainnet node.

This repo is the standalone front end + tooling + proofs. The on-chain indexing/serving lives in the
companion **`brk-btx`** fork (a BRK fork; the `btx` modules). The two are kept permanently separate
from Renshu's Bitcoin terminal analytics fork. See `BTX-phase0-STATUS.md` for the full, honest
status and `BTX-decision-brief.md` for where it stands strategically.

> Research preview. Proven end-to-end on **regtest, custom signet, and public signet** (Bitcoin Core
> v29.1) — incl. **cross-node propagation** of a witness-envelope order under default relay policy
> (public signet, 2026-05-24: reveal `60e969a3…a63e3`, mined in block 305837; on v29.1 the OP_RETURN
> carrier would *not* have relayed under default policy, the witness envelope did), a full **rune↔rune**
> addressed swap settled on regtest (ord-confirmed), and a live **cross-indexer consensus-hash match** on
> a regtest book (independent Python reconstruction == Rust indexer). Not production-hardened, no
> mainnet/economic testing. The order book is empty until orders are published.

## Web UI (open the HTML files in a browser, point them at a running `brk-btx` node)
- `btx_trade.html` — the **trading terminal** (Hyperliquid-style): live order book with depth and
  divisibility-normalized prices, a cross-indexer "book hash · indexer agreed" badge, multi-select
  **batch fill**, and Publish / Fill / Etch / OTC / **Rune↔Rune** panels. Driven by the `btxd`
  orchestrator, which signs only through your own Bitcoin Core wallet.
- `index.html` — landing page: what BTX is + routes to the pages below.
- `btx_book.html` — the order book: open orders, partial-fill groups, recent fills/cancels, and
  detected on-chain atomic swaps; rows link to the per-order page; "+ create order" links to the maker page.
- `btx_order.html?offer=<txid>:<vout>` — a shareable per-order page with the committed terms and
  copy-paste "how to fill" commands.
- `btx_create.html` — a maker page that builds the exact `maker-sign` + publish commands from a form
  (never touches keys).
- `btx_app.html` — the unified one-screen dashboard (node · wallet · mining · DEX) for the bundled
  install: node/sync status, wallet balance, and the DEX panels in a single operator view.
- `btx_trades.html` — a **live on-chain Runes-trades feed**: recent likely marketplace fills (a
  `SIGHASH_SINGLE|ANYONECANPAY` pre-signed input **and** a runestone edict — how Magic Eden / UniSat /
  OKX fills settle), with rune id, amount, BTC paid, and best-effort buyer/seller. Heuristic; shows real
  data on a mainnet-indexed node.

Served by the `brk-btx` node over: `/api/v1/btx/orders`, `/groups`, `/history`, `/swaps`,
`/trades`, `/mempool`, `/book-hash` (the cross-indexer consensus hash), `/book-root` +
`/order-proof/{txid}/{vout}` (the Merkle commitment + per-order membership proof), `/event-hash` (the
cumulative announce/fill/cancel commitment), and `/event-stream` (the per-block `[{height, block_hash,
cumulative}]` sequence a light client folds to follow the book incrementally).

## Bundled Windows app (`app/`, v0.2.x)

A native Windows .exe (Tauri + Rust supervisor) that bundles all four daemons inside it: an end user
double-clicks the installer, the supervisor spins up `bitcoind`, `brk_cli`, `ord`, and `btxd` inside
WSL, and the BTX trading terminal opens in a native window. No separate WSL setup, no daemon
management, no relay, no third-party server. Build via `app\rebuild.ps1` from PowerShell.

Self-healing, end-to-end:

- **First-launch setup wizard** picks chain (regtest/signet/mainnet) and wallet name, persists to
  `~/.btx/setup.json`. Mainnet users point at their existing Bitcoin Core datadir.
- **Bundled daemons** (bitcoind 30.2, brk_cli 0.3.0-beta.9, ord 0.27.1, btxd) are copied into
  `~/.btx/bin` and `~/.btx/app` on first launch via a version-sentinel; subsequent launches reuse
  them.
- **Per-daemon supervisor** spawns each in dependency order, monitors a TCP readiness probe, restarts
  on crash with backoff, and exposes status to `btx_daemons.html`.
- **Graceful shutdown** on window close: every daemon receives SIGTERM and gets 10s to flush before
  SIGKILL. Bitcoind's dbcache (up to 300MB) is preserved across closes — chain persists.
- **ord stale-lock auto-recovery** (v0.2.6): if ord's embedded redb says "Database already open" on
  startup (after a SIGKILL'd prior process left its OPEN flag set), the supervisor `rm`s the index
  subdir and lets ord rebuild. Only fires on regtest where reindex is cheap.
- **ord wedge auto-detection** (v0.2.10–v0.2.12): every 15s the supervisor reads ord's and bitcoind's
  current heights through `btxd /api/health` (Rust talks to btxd over the same `:3333` the WebView
  uses; this sidesteps a wsl.exe-from-Tauri subshell trap where `$()` substitutions silently return
  empty). When ord's height has been frozen for `stall_secs` while bitcoind has advanced more recently,
  `restart_one("ord")` fires. Thresholds: 60s regtest, 300s signet, 300s mainnet — the stall heuristic
  survives a legitimate cold-start reindex (ord IS advancing during it, the timer resets each tick) but
  catches a genuinely wedged ord.
- **Full E2E proven through the bundled GUI**: etch → maker-sign → publish via OP_RETURN → see in
  Book → fill → see in Trades. See `BTX-bundled-app-e2e-runbook.md` for the reproducible script.

## Maker/taker tooling
- `btxd.py` — local orchestrator the terminal talks to: proxies the `brk-btx` reads, runs the
  proven CLIs for actions (publish, fill, batch-fill, etch, addressed + rune↔rune swaps), and
  cross-checks its book hash against the indexer's native one. Loopback-only with a DNS-rebinding `Host:`
  allowlist **and** an `Origin` allowlist on mutating POSTs (CSRF guard); an optional
  `--max-hot-balance-btc` rail **refuses to start** against a wallet whose spendable balance already
  exceeds the cap — a startup *misconfiguration* guard (so you don't point btxd at a primary store of
  value), **not** a runtime cap or an anti-compromise control (a compromised btxd bypasses it).
  Operationalizes "use a dedicated thin wallet"; see `BTX-mainnet-hardening.md` blast radius.
- `btx.py` — CLI over the proven primitives (order create/lots/inspect/verify, swap build, book
  summary/scan with `--tip-height` for cross-indexer-exact expiry, runestone, HTTP client).
- `btx_0b.py` — chain-reconstruction core (sign/verify maker offers from chain data alone).
- `btx_wallet.py` — Bitcoin Core wallet integration: `maker-sign`, `taker-fill`, **`batch-fill`**
  (one tx, N offers), the **addressed-swap** handshake (`addressed-propose`/`-countersign`), the
  **rune↔rune** handshake (`addressed-rune-propose`/`-countersign`), and offline `simulate`.
- `btx_orderbook.py` — the deterministic price-time book + the order-set-independent `book_hash`
  (the Python side of the cross-indexer consensus check) + divisibility-normalized prices, plus the
  Merkle commitment (`book_root` / `merkle_prove` / `merkle_verify`) and the `cumulative_event_hash`
  (announce/fill/cancel stream) — the Python references the Rust indexer is golden-cross-tested against.
- `btx_rune_swap.py` — rune↔rune addressed swaps: tx builder, a Runes allocator, and a maker-side
  verifier that confirms (and only signs if) output 0 receives the agreed counter-rune.
- `btx_etch.py` — hand-built Runes etching (commit→maturity→reveal) with no `ord` wallet dependency;
  pre-validation ported from ord `rune.rs`.
- `btx_carrier.py` / `btx_taproot.py` — OP_RETURN and Taproot witness-envelope carriers (BIP341),
  incl. dependency-free BIP340 Schnorr sign/verify + the BIP341 script-path sighash (vector-checked).
- `btx_envelope_publish.py` — publishes an order via the witness envelope: funds the commit, builds +
  signs the reveal (`[schnorr_sig, tapscript, control_block]`), broadcasts. No `-datacarriersize` needed.
- `btx_runes.py` / `btx_runes_decode.py` — byte-accurate runestone encode/decode for the asset leg;
  `btx_runes_decode.py` is cross-validated against Magic Eden's `runestone-lib` (`btx_runes_xcheck.py`).
- `btx_trades.py` — heuristic Runes-marketplace-trade classifier: combines the `0x83` pre-signed-swap
  pattern with the runestone decoder to emit likely-trade records (rune, amount, BTC paid, seller/buyer)
  — the Python side of the live on-chain DEX-activity feed (Rust port lives in `brk-btx` `trades.rs`).
- `btx_signet_magic.py` — derive `BRK_BLOCK_MAGIC` for a custom signet (self-tested vs public signet).
- `btx_index.rs` — portable, dependency-free reference of the artifact parser + order-book state machine
  (the `brk-btx` `btx.rs` is the BRK-bound version).

## Proofs
- `btx_test_all.py` — one-command offline suite (12 suites): encoder/rune-name vectors, aggregate
  selftest, wallet plumbing, addressed-swap gate, signet-etch control-flow, funding (Taproot) regression,
  deterministic book + consensus hash, **batch fill** (verifies each maker's `0x83` pre-sig at its real
  input index k>0), **rune↔rune** swap + Runes allocator (incl. the cenotaph-rejection safety check),
  property fuzz (decoder/allocator/hash invariants), **Runes decoder cross-check** vs Magic Eden
  `runestone-lib` (18 golden vectors), and the **cumulative event hash** (golden + order-independence +
  omission-detection).
- Cross-indexer consensus hash, Merkle root, and event hash: **golden vector** tests in `brk_indexer::btx`
  assert the Rust `book_hash_from_views` / `book_root_from_views` / `cumulative_event_hash_from_views` are
  byte-identical to their Python `btx_orderbook` references; the flat hash is proven **live** by an
  independent Python chain reconstruction matching the Rust `/api/v1/btx/book-hash` on a real regtest book.
- `btx_verify_check/` — standalone Rust crate compiling `verify_maker_sig` against bitcoin 0.32.9 /
  secp256k1 0.29.1 and checking a python-signed artifact. Plus an adversarial test module in
  `brk_indexer::btx` (malformed-artifact / hostile-envelope panic-safety, fill-rule value+spk).
- `run_*.sh` — on-node regtest runbooks (atomic swap, runes leg, milestone 0b single- and two-node,
  double-take race, btx reorg).
- `btx_live_verify.sh` — one-shot full-lifecycle harness (regtest/custom-signet): publish → index with
  `brk-btx` → serve → taker-fill → confirm the order leaves the open book (FILLED).
- `*.log` — captured run results.

## Runbooks & docs
- `BTX-signet-validation.md` — validate on a custom signet (full lifecycle proven on real signet blocks).
- `BTX-seeding-runbook.md` — publish a first real order on public signet (+ mainnet caveats); tests
  cross-node propagation under default relay policy.
- `BTX-envelope-publish-runbook.md` — publish an order via the Taproot witness-envelope carrier
  (commit→reveal); on-node acceptance proves the BIP341 script-path sighash + witness extraction.
- `BTX-live-demo-runbook.md`, `BTX-wallet-runbook.md`, `BTX-0b-runbook.md` — on-node walkthroughs.
- `BTX-architecture-and-build-sequence.md`, `BTX-phase0-spec.md`, `BTX-brk-integration-design.md`,
  `BTX-partial-fills-design.md` — design.
- `BTX-phase0-STATUS.md` — proven-status record. `BTX-decision-brief.md` — honest strategic read.

## Security & audits
- `BTX-threat-model.md`, `BTX-attack-defense-matrix.md` — the threat model (principal-at-risk
  analysis, local/client surfaces) and the layered attack/defense matrix.
- `BTX-mainnet-hardening.md` — the mainnet-readiness record: the fixes from ~10 adversarial audit
  passes (hostile-input parser, crypto/key-material, consensus/standardness, concurrency, resource
  exhaustion, DNS-rebinding, ByteView panic-safety, …) plus the hot-wallet blast-radius mitigation.
- `BTX-frontrunning-threat-model.md` — why open orders are fill-race-able by construction (and why
  that risks no principal); the addressed mode is the snipe-resistant opt-out.
- `BTX-book-commitment-design.md` — the Merkle book commitment + cumulative-event-hash design.
- `BTX-ecosystem-research.md`, `BTX-competitive-landscape.md` — the 27-repo ecosystem scan +
  forward-looking watchlist, and where BTX sits against every comparable system.
- `DEPENDENCIES.md` — the supply-chain audit (pinned deps, `cargo audit` / `pip-audit` clean as of
  2026-05; re-run before each release).

## Project history

This codebase was previously developed in the open as **CoreX** (repositories `renshuBTC/bitcoin-corex`
+ `renshuBTC/brk-corex`). On 2026-05-28 it was rebranded **CoreX → BTX (Bitcoin Terminal Exchange)**
and moved into the current PRIVATE repos (`renshuBTC/bitcoin-terminal-exchange` + `renshuBTC/brk-btx`).
The old public repos are left online as historical artifacts and receive no new commits.

The rename was purely mechanical — Python identifiers, Rust modules, file names, HTTP routes
(`/api/v1/cxo/*` → `/api/v1/btx/*`), the on-disk fjall store key (`cxo_orders` → `btx_orders`),
and the artifact MAGIC bytes (`CXO1` → `BTX1`, hex `43584f31` → `42545831`). Because no
`corex`/`cxo` literal sat inside any canonical event/leaf string, the consensus hashes
(`book_hash`, `book_root`, `cumulative_event_hash`, `event_stream`) are **byte-identical** between
the new BTX implementations and the pre-rename CoreX — verified by an empirical diff against the
old `bitcoin-corex` checkout's hash test outputs.

The full equivalence is verified by the 10-prompt audit in `BTX-rename-audit-prompts.md`, all
empirically green: 117 offline assertions across Python + Rust (including 4 PYTHON_GOLDEN bit-identical
cross-tests); regtest publish→fill via both OP_RETURN and Taproot-envelope carriers; full rune trade
with `ord` oracle backing verification; reorg rollback (`Stores::rollback_btx_orders` fires on
invalidateblock); `btxd` security guards (Host-allowlist + Origin/CSRF guard return 200/403/403);
GUI publish/fill round-trip in the browser with in-browser Merkle proof verification ("✓ order
verified in root"); and `testmempoolaccept allowed=true` for the witness-envelope carrier under
strict default Bitcoin Core v29.1 mempool policy. No PASS-by-equivalence shortcuts.

## Honest positioning
The on-chain-reconstructed order book is not novel (Counterparty did it in 2014), the settlement
primitive is the industry-standard PSBT pattern, and a Nostr-based book delivers "no server" more
cheaply. BTX's one real differentiator is that the order book inherits Bitcoin's own
availability/censorship-resistance (no relay, no token) — a narrow edge at the cost of on-chain fees,
latency, and throughput. It's a proven sovereign-DEX implementation and skills showcase, not a
moat-bearing product. It does not manufacture the one thing it most lacks — **liquidity** — which is a
distribution problem, not an engineering one.

Two things are characterized honestly rather than hidden:

- **Open orders are fill-race-able, and that's not a defect.** Because a maker's `0x83` signature
  commits to only its offer-input + payout-output, anyone can complete a published order — so the
  *which-taker-wins* contest is a mempool fee auction. `BTX-frontrunning-threat-model.md` argues this
  is **irreducible for an open, single-transaction fill** under *any* per-transaction predicate (current
  script or any covenant — CTV/APO/TXHASH/Simplicity): "anyone can fill" *is* "anyone can outbid the
  filler," and no per-tx predicate can pick a winner from the global ordering of off-chain commitments.
  A first-to-commit auction is possible only by adding a sequencing/coordination layer — which forfeits
  the open / nothing-offchain property (it becomes a sequenced market), so it's a different design, not a
  snipe-proof open order.
  No principal is at risk **from the protocol or a counterparty** — the maker is price-protected and taker
  funds are `SIGHASH_ALL`-protected; a taker who *loses* a race pays no on-chain fee (an unconfirmed
  Bitcoin tx costs nothing — the loss is opportunity, not gas); and unfilled partial-fill lots stay the
  maker's unspent UTXOs. ("Principal" = funds held going in; defined in `BTX-frontrunning-threat-model.md`
  §5.) The one residual principal-loss path is taker *tooling* error, not theft: a taker who builds a
  malformed open fill (a cenotaph runestone) confirms a tx that pays the maker while the network burns the
  rune they were buying — `btx_wallet` builds a valid fill, but for an open order the taker constructs
  their own, so a correct builder is their responsibility. The real harms are liveness/griefing (incl.
  mempool **pinning**) and the mispriced-resting-order option — the same option every venue has, but
  **larger and harder to retract** on BTX because the on-chain cancel is itself race-able (a sniper can
  out-bid it up to the spread), so don't rest deep-mispriced orders. For deals you want bound to one
  counterparty, use the **addressed** mode: here *snipe-resistant* means **no third party can substitute
  themselves as the taker**, because the maker signs the whole tx with `SIGHASH_ALL` (no input/output
  substitution survives). That is by-construction for rune↔BTC; for **rune↔rune** it also relies on the
  maker-side allocation verifier (`verify_addressed_rune_tx`) correctly checking the runestone routing —
  a verifier that was hardened after a snipe was found in it (F-POINTER) — so it is "by construction **plus
  a correct verifier**," not purely structural.
- **Trust in the book reduces to "run an indexer, or trust one that publishes a commitment you can
  check."** The cross-indexer consensus hash makes that checkable (two independent implementations agree
  byte-for-byte, demonstrated live); the Merkle **root + membership proofs** sharpen it from whole-book to
  *per-order* — a light client verifies a single served order against the committed root with a log-sized
  proof, no full node — and the **cumulative event hash** lets it follow the book incrementally and detect
  reorg/omission. The remaining gap (does the root correspond to the real chain?) is the only thing a
  ZeroSync-style chain proof would close — tracked on the forward-looking watchlist in
  `BTX-ecosystem-research.md`. To be precise about provenance: this commitment-plus-proof pattern is
  **not novel** — RiemaLabs' Modular Indexer (Verkle checkpoints + challenge proofs) and OPI's verified
  hashes pioneered verifiable meta-protocol indexing for BRC-20/Bitmap. BTX's contribution is applying
  it to an on-chain *order book* with byte-identical Python/Rust/JS implementations, not inventing the
  primitive.
