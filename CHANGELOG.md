# Changelog

All notable changes to Bitcoin Terminal Exchange are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/); this project is a research preview and versions are
not yet semver-stable. Commit hashes reference the `bitcoin-terminal-exchange` repo unless prefixed `brk-btx:`
(the companion BRK fork that does the on-chain indexing/serving).

## [0.1.1] — 2026-05-27 — security & robustness hardening

A threat-model-driven audit pass. No protocol custody/theft hole was found (the maker stays
price-protected by its `SIGHASH_SINGLE|ANYONECANPAY` signature; taker funds stay `SIGHASH_ALL`-
protected). The fixes below close a local/client attack surface, an indexer panic-on-corruption, and
two startup-robustness gaps. See `BTX-threat-model.md` and `BTX-mainnet-hardening.md` (items 8–9).

### Security

- **btxd: DNS-rebinding guard.** `btxd` binds `127.0.0.1` but previously did no `Host:`/Origin
  validation, so a malicious web page could rebind DNS to loopback and `fetch()` wallet-signing actions
  (publish / fill / batch-fill / etch / swaps). Added a loopback `Host:` allowlist enforced on every
  `do_GET`/`do_POST` — non-loopback `Host:` is rejected with `403`. The browser cannot forge `Host:` to
  a loopback name, so this defeats rebinding while leaving the legitimate `127.0.0.1`/`localhost` GUI
  working. Verified live: `loopback → 200`, `Host: evil.com → 403`. (`13a373b`)
- **Terminal: XSS defense-in-depth.** No live XSS existed (every served field reaching `innerHTML` is
  numeric or hex). Added an `esc()` HTML-entity escaper on the on-chain/indexer-derived fields
  (`rune_id`, txid, and `artifact_hex` embedded in `onclick`) so a future free-text field (e.g. an ord
  rune name/symbol) cannot become stored XSS. (`13a373b`)
- **brk-btx: bounds-safe order-store deserialization.** `BtxOfferKey`/`CxoOrderRecord`
  `From<ByteView>` indexed the buffer unchecked, so a truncated/corrupted `btx_orders` entry (partial
  write, disk corruption, local tamper) panicked the indexer. Short buffers now degrade to inert values
  — a zeroed key (matches no outpoint) and an empty-artifact/sentinel-status record skipped by every
  read path — never a phantom order, never poisoning the consensus hash. (`brk-btx: c33bddad5`)

### Fixed

- **btxd: no longer crashes on startup when `bitcoin-cli` isn't runnable.** `bcli` now normalizes
  `FileNotFoundError`/`PermissionError` to `RuntimeError`, so the startup wallet auto-load, offer
  re-lock, and every `_guard`-wrapped handler degrade gracefully instead of an unhandled exception
  killing the daemon. (`8d0514a`)
- **btxd: clean message on port-bind failure** (`ThreadingHTTPServer` `OSError`, e.g. port already in
  use / btxd already running) instead of a raw bind traceback. (`01504d5`)

### Documentation

- Added `BTX-threat-model.md` — a structured pre-audit threat model (principals, trust boundaries,
  attack surface by entry point, explicit uncertainties). (`13a373b`)
- Marked threat-model uncertainties resolved after the audit (ByteView panic and subprocess-arg-list
  completeness confirmed; DNS-rebinding and XSS surfaces addressed in code). (`7c033ba`)
- Folded the two new surfaces into `BTX-mainnet-hardening.md` as items 8 (HIGH local — Host guard) and
  9 (LOW latent — `esc()`). (`13a373b`)

### Packaging

- Bundle bumped to **0.1.1** and rebuilt so the shipped artifacts carry the fixes: frozen `btxd`
  (Host guard + startup fix), `btx_trade.html` (`esc()`), and a recompiled `brk_cli` (ByteView fix).
  (`20bf95d`)

### Verification

- Offline suite `btx_test_all.py`: **10/10 green**.
- Indexer tests `cargo test -p brk_indexer btx`: **23/23 pass** (incl. a new corrupt-store
  no-panic test over every sub-minimum buffer length).
- Confirmed exhaustively (not spot-checked): all six `subprocess.run` sites pass arg-lists; no
  `shell=True` anywhere.

## [0.1.0] — 2026-05 — research-preview baseline

Initial server-less, on-chain order-book DEX for Bitcoin. Proven end-to-end on regtest, custom signet,
and public signet (Bitcoin Core v29.1).

- Maker pre-signs an offer (`SIGHASH_SINGLE|ANYONECANPAY`) as an on-chain artifact; any taker fills it
  in a single native Bitcoin transaction. No exchange, relay, server, escrow, or BTX token.
- Carriers: OP_RETURN and Taproot witness-envelope (commit/reveal); envelope is the mainnet default
  (not subject to `datacarriersize`). Cross-node propagation demonstrated on public signet (2026-05-24).
- Batch fills (one taker sweeps many offers in one tx); rune↔BTC open orders; rune↔rune via the
  addressed (interactive, snipe-resistant) path.
- `brk-btx` indexer reconstructs the book from chain and serves an order-set-independent consensus
  hash; an independent Python reconstruction and the Rust indexer produced byte-identical hashes on
  real chain data.
- `btxd` localhost orchestrator + Hyperliquid-style `btx_trade.html` terminal; signing always
  through the user's own Bitcoin Core wallet. One-download Linux/WSL bundle via `package-linux.sh`.

[0.1.1]: https://github.com/renshuBTC/bitcoin-terminal-exchange/releases/tag/v0.1.1
[0.1.0]: https://github.com/renshuBTC/bitcoin-terminal-exchange/tree/v0.1.0
