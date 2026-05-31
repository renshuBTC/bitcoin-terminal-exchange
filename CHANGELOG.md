# Changelog

All notable changes to Bitcoin Terminal Exchange are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/); this project is a research preview and versions are
not yet semver-stable. Commit hashes reference the `bitcoin-terminal-exchange` repo unless prefixed `brk-btx:`
(the companion BRK fork that does the on-chain indexing/serving).

## [brk-btx 2026-05-31] — Indexer stale-tip auto-recovery (all chains)

Companion fix in the brk-btx indexer (`8a197f3` in brk-btx) extending v0.2.18's recovery story to
mainnet and signet — the chains that v0.2.18 explicitly couldn't help.

When bitcoind's dbcache rolls back below brk_indexer's last-indexed tip, the first
`getblockheader` inside `get_closest_valid_height` errors `-5 "Block not found"` and the indexer
process exits with no way to make progress short of a full state wipe. v0.2.18 caught this on the
*supervisor* side for regtest by detecting the error in the brk_cli log and `rm -rf`-ing the brk
state dir, but a full re-index from genesis on mainnet would take days, so signet/mainnet got the
"manual recovery" caveat.

The new fix lives inside `brk_indexer::index_` (brk-btx). Before calling `get_closest_valid_height`,
the indexer reconciles its stored tip against bitcoind by walking its OWN stored blockhash vec
backward — exponential backoff to find a recognized ancestor, then binary-search refinement to pin
down the most-recent recognized index so no progress is lost. Then it hands that hash to
`get_closest_valid_height` for the residual orphan→main-chain resolution. Typical small-divergence
cases (a few-block rollback) finish in a handful of RPCs; catastrophic full-divergence cases finish
in O(log N) and fall through to the same `full_reset` the existing length-inconsistency branch
already used.

`brk_rpc::Client::recognizes_block(&hash)` is the new helper that specifically translates RPC -5
into `Ok(false)` and propagates every other error as `Err` so transport/auth failures don't get
silently misclassified as chain divergence.

The v0.2.18 supervisor-side log-tail wipe stays as a belt-and-suspenders catch for the narrower
case where the indexer process is killed before its normal startup path runs at all (e.g. SIGKILLed
mid-handshake), and stays regtest-only so we never wipe mainnet/signet state from outside the
indexer. Comment narrowed in `app/src/supervisor.rs` to reflect the new layering.

**Build note:** the brk_indexer change needs a `cargo check -p brk_indexer -p brk_rpc` (and a
`cargo build --release -p brk_cli` if you want to re-bundle) from the Windows host — the sandbox
doesn't have cargo. CARGO_TARGET_DIR should still point at ext4 per the existing build memo.

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
  a loopback name, so