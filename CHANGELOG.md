# Changelog

All notable changes to Bitcoin Terminal Exchange are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/); this project is a research preview and versions are
not yet semver-stable. Commit hashes reference the `bitcoin-terminal-exchange` repo unless prefixed `brk-btx:`
(the companion BRK fork that does the on-chain indexing/serving).

## [docs 2026-05-31] — Bitcoin Core v30 OP_RETURN policy: BTX implications

Doc-only update resolving the [VERIFY] watchlist tag left in `btx_carrier.py` about 2026 carrier
standardness. Bitcoin Core v30 shipped 2025-10-10 with the default `datacarriersize` raised from 83
bytes to 100,000 bytes and multiple OP_RETURN outputs per tx allowed. For BTX (~208-byte v2
artifact):

- **OP_RETURN carrier** now relays under v30 default policy with massive headroom (was rejected
  under v29.1 default at 83 bytes). No code change — the artifact size hasn't moved.
- **Envelope carrier** (Taproot script-path witness, `btx_envelope_publish.py`) is unaffected; not
  subject to `datacarriersize` at all.
- **Envelope stays the mainnet default in `btxd.h_order_create`.** Operators can still set
  `-datacarriersize=83` to keep pre-v30 behavior (Knots-style configurations), so envelope is the
  policy-safest choice for cross-node relay guarantees. BTX no longer *needs* the relaxed
  datacarrier, but doesn't *depend* on v30 either.
- **E2E Prompt 10's PASS is now a frozen v29.1 snapshot.** Under v30 default, the same `OP_RETURN
  100B` probe would flip to `allowed=true`; the v29.1 boundary observation is still accurate for
  v29.1.
- **Bundled bitcoind is still v29.1.0.** Bumping the bundled Core to v30 is a candidate for v0.2.19
  and tracked separately.

Updated: `btx_carrier.py` doc-comment (removed [VERIFY]), `BTX-mainnet-hardening.md` §1
(replaced "recent Bitcoin Core has debated" parenthetical with v30 watchlist note),
`BTX-e2e-audit-results.md` (v30 watchlist note above the result matrix).

## [0.2.18] — 2026-05-31 — brk_cli stale-state auto-recovery (regtest)

A recurring developer-loop papercut: after the bundled regtest bitcoind crashes or restarts without
a clean shutdown, dbcache rollback can drop it to a height below brk_cli's indexed tip. On the next
brk_cli startup, its stored tip-hash is no longer in bitcoind's main chain, so
`client.get_closest_valid_height(stored_tip_hash)?` propagates bitcoind RPC error `-5 "Block not
found"` and brk_cli exits. The supervisor restarts it, same state, same crash — a hard loop that
required manual `rm -rf ~/.btx/brk-regtest` four times in the previous session before any further
work could proceed.

- **Pre-flight log-tail detection + recovery.** Mirroring v0.2.6's ord stale-redb-lock recovery,
  brk_cli's `wsl_command` now tails the last 50 lines of `/tmp/btx-brk_cli.log` before exec. If
  `'Block not found'` appears AND the chain is regtest, it `rm -rf $HOME/.btx/brk-{chain}` and lets
  the indexer rebuild from genesis (~seconds for a few hundred regtest blocks). The `tail -n 50`
  scope avoids false positives from incidental API 404 responses during normal operation — a
  startup crash leaves the error near the end of the previous log, but normal operation flushes
  subsequent output after any incidental query 404. Regtest-only by design: a full re-index from
  genesis on mainnet would take days, so signet/mainnet keep the manual-recovery path until a
  walk-back-through-stored-hashes fix lands inside `brk_indexer` itself. (supervisor.rs)

## [0.2.3 → 0.2.12] — 2026-05-30 — bundled-app polish, self-healing, E2E proof

A 10-commit run hardening the bundled Windows app (`app/`, Tauri shell + Rust supervisor) into a
working self-custodial DEX install. The trade rail is now provably executable end-to-end through the
GUI on regtest (etch → maker-sign → publish → book → fill → trades), the daemon stack is
self-healing across crashes/wedges, and chain state persists across closes. See
`BTX-bundled-app-e2e-runbook.md` for the reproducible walkthrough.

### Bundle / UX

- **CSS bundle fix.** `assets/btx.css` and `btx_order.html` were referenced by the
  book/trades/create/order pages but weren't being copied by `install_bundled_assets` — those four
  pages rendered as unstyled HTML with the nav concatenated into one blob. Added both to
  `bundle.resources` and the install script. Also switched the hardcoded brk_cli port from `3110`
  to the actual `3140` in book/trades/order pages. (`4b93c5c`, v0.2.3)
- **Wallet immature-balance metric.** The wallet stats row was only showing trusted +
  untrusted_pending, hiding the immature coinbase balance that `getbalances.mine.immature` reports.
  Added an Immature metric that auto-hides when 0 (so non-mining wallets stay clean) and shows the
  full amount when present — e.g. a regtest miner with 3675 BTC of maturing coinbases at block 202.
  (`ac6d5f5`, v0.2.4)

### Daemon supervisor

- **Graceful shutdown.** The original shutdown wiring listened to `WindowEvent::Destroyed`, which
  fires AFTER the OS window is already torn down — the supervisor's async `stop_all` then raced the
  Tauri process exit and bitcoind got SIGKILLed on the way out, losing its dbcache (up to 300MB of
  unflushed chain state). Reproduced this session: the regtest chain was wiped to genesis after every
  close. Switched to `WindowEvent::CloseRequested` + `api.prevent_close()`: intercept the close, run
  the full SIGTERM-then-wait chain on a dedicated tokio runtime in a worker thread, then explicitly
  call `window.destroy()` once every daemon has cleanly exited. Verified: bitcoind at block 202 with
  5100 BTC trusted + 3675 BTC immature → window-X close → all four daemons logged SIGTERM/stopped in
  reverse dep order → relaunch sees the same 202/5100/3675 state. (`a7863b5`, v0.2.5)
- **ord stale-lock auto-recovery.** ord 0.27 sets an OPEN flag inside its `index.redb` when opening
  the database and clears it on clean shutdown. After a SIGKILL or an internal wedge, the flag stays
  set and the next ord process refuses to start with "Database already open. Cannot acquire lock."
  Embedded a pre-flight check in ord's wsl_command: before launching, if the previous attempt's
  `/tmp/btx-ord.log` shows the lock-error signature, `rm -rf` the chain-specific index subdir so the
  new ord rebuilds clean. Only fires on regtest where reindex is cheap (~10s for ~200 blocks).
  (`3aac5d0`, v0.2.6)
- **ord wedge auto-detection** (v0.2.10–v0.2.12). ord occasionally stops polling bitcoind for new
  blocks while its HTTP server stays up. Two design iterations:
  - v0.2.10 introduced a block-gap heuristic on regtest only: poll
    `btxd /api/health` every 15s, restart ord when its height lagged bitcoind by >5 for >60s.
    Required two infrastructure findings to land: `wsl.exe bash -c "..."` invocations from Tauri
    silently return empty for `$()` substitutions, so the supervisor can't reach ord/bitcoin-cli
    directly — routing through btxd (which runs inside WSL with full visibility) over its already-
    working `:3333` port works. And Python's `urllib.urlopen(timeout=1)` does NOT actually cap at 1s
    when the upstream HTTP server is SIGSTOPped — raw `socket.settimeout(1)` does. (`ac4b566`)
  - v0.2.12 rewrote the detector to **stall-based** logic: wedge = ord's height has not changed for
    `stall_secs` AND bitcoind has advanced more recently than ord. The block-gap heuristic tripped
    a false positive on signet/mainnet during legitimate cold-start reindex (ord can stay 1000+
    blocks behind but is advancing every tick); the stall heuristic survives that because the timer
    resets each tick. Now enabled across all three chains: 60s regtest, 300s signet, 300s mainnet.
    (`0c58f2d`)
- **Double-close dedupe.** A second `CloseRequested` firing mid-shutdown (Tauri occasionally
  re-emits the event during the `prevent_close` window) re-entered `stop_one` for each daemon,
  re-firing SIGTERM at processes already in their 10s grace period. Cosmetic but noisy — log
  lines showed each daemon's stop sequence twice. Added `State::Stopping` to the early-return set
  so the second invocation no-ops cleanly. (`3cd41bd`, v0.2.11)

### Build / DX

- **`app/rebuild.ps1`** — one-script build-install-launch helper so the dev loop is `.\rebuild.ps1`
  instead of an 8-line PowerShell paste. Documents the `-ExecutionPolicy Bypass` flag and the
  PowerShell-vs-WSL pitfall. (`64c6a99`)

### Documentation

- **`BTX-bundled-app-e2e-runbook.md`** — walks through the full trade rail as exercised through the
  bundled Windows app: launch, mine 101, etch a rune, maker-sign, publish via OP_RETURN, verify on
  the Book page, fill, verify on the Trades page. Mirrors the older `BTX-live-demo-runbook.md` but
  with the bundled stack instead of a hand-assembled bitcoind+brk_cli setup, and uses the GUI pages
  as the visual verification points. Every command in the runbook was run end-to-end during the
  2026-05-30 session and produced the expected GUI states. (`b93836b`)

### Verification

- **Full E2E proven through the bundled GUI.** At regtest block 226: 1B-unit BTXUSDONREGTESTAA
  premine → 207-byte maker-sign artifact (`maker_sig_self_verifies: true`) → OP_RETURN carrier tx
  confirmed at h=224 → brk_cli + btxd both report `n_orders: 1` with the same `book_hash`, "indexer
  agreed" and "order verified in root" badges green in the GUI → atomic SIGHASH_SINGLE|ANYONECANPAY
  swap tx confirmed at h=226, fee 10000 sats → Book page drops to 0 orders, Trades page shows the
  fill with correct seller/buyer attribution.
- **Self-healing chain verified.** SIGSTOP ord (simulates the internal wedge), mine N blocks, wait
  for the detector to fire, observe stall threshold trip, SIGTERM → SIGKILL → respawn → fresh ord at
  chain tip. New `/api/health` agrees: `{ord:N, bitcoind:N}`.

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

- Offline suite `btx_test_all.p