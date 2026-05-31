# v0.2.x supervisor/lifecycle audit (2026-05-31)

Clean-room review of today's bundled-app commits (v0.2.3 → v0.2.14) against
`app/src/supervisor.rs`, `app/src/lib.rs`, `btxd.py:h_health`, and
`app/src/install.rs`. Eight findings: one **critical** (must-fix before any
mainnet release), three notes (already correct, documenting expected
behavior), four no-issue (audited and clean).

## CRITICAL #1 — v0.2.14 pre-kill of `bitcoind` is mainnet-unsafe

**Location:** `supervisor.rs::start_one`, the v0.2.14 pre-kill that runs
`pkill -KILL -x bitcoind` (derived from the `stop_pattern` field).

**Problem:** `pkill -KILL -x bitcoind` matches **every** `bitcoind` process on
the WSL distro by binary basename, not just the one bound to our regtest/
signet ports. The mainnet wizard (M5b.6) explicitly supports `datadir_override`
pointing at the user's existing Bitcoin Core install. On mainnet, every
btx-app launch would SIGKILL the user's production mainnet bitcoind — a
process they may have been running for months with valuable in-memory state.

This is also true for the original `stop_one` graceful path (sends SIGTERM to
the same broad pattern); v0.2.14 just makes the breakage unconditional.

**Why it slipped:** v0.2.3 through v0.2.14 were all developed and tested
against regtest, where the user has no "real" bitcoind. The mainnet
datadir_override workflow has never been exercised against a co-resident
production bitcoind.

**Fix (v0.2.15):** Skip the bitcoind pre-kill (and ideally the stop_one
SIGTERM too) when `setup.datadir_override.is_some()`. On mainnet with
datadir_override the user owns the bitcoind process — the supervisor
should never touch it. brk_cli / ord / btxd remain safe to pkill (they
are bundle-managed).

**Tracking:** task #259 — v0.2.15: protect user's bitcoind from pre-kill.

## NOTE #2 — wedge detector correctly handles state transitions

**Location:** `supervisor.rs::spawn_ord_wedge_detector`, the
`ord_state != State::Running` reset branch.

**Audited:** During `restart_one("ord")`, ord's state walks
`Running → Stopping → Stopped → Starting → Running`. The detector ticks
every 15s. When state ≠ Running, all four trackers (`last_ord_h`,
`last_ord_advance`, `last_btc_h`, `last_btc_advance`) are reset so the
post-restart stall measurement starts from a clean slate. Verified during
v0.2.10 SIGSTOP testing.

**Found correct.**

## NOTE #3 — `stop_one`'s v0.2.11 Stopping guard prevents re-entrancy

**Location:** `supervisor.rs::stop_one`, the `matches!(rt.state, ... |
State::Stopping)` early-return.

**Audited:** A second `CloseRequested` firing mid-shutdown (Tauri sometimes
re-emits) re-enters `stop_one`. The Stopping guard makes the second call a
no-op; the first call runs to completion. Verified via v0.2.11 stderr test
where each daemon's stop line appears exactly once.

**Found correct.**

## NOTE #4 — `started_at` set before readiness probe

**Location:** `supervisor.rs::start_one`, line ~377.

**Audited:** `arc.lock().await.started_at = Some(Instant::now())` is set
between `spawn_res` success and `wait_for_port`. If the spawn succeeded but
the daemon crashes before opening its port, `started_at` stays set even
though state transitions to Crashed. This is the expected semantic —
"when did we try to start this" — and the state field carries the success
signal.

**Found correct.**

## LOW #5 — restart_one task is unaware of `shutting_down`

**Location:** `supervisor.rs::restart_one` (called by wedge detector or
the daemon-pane IPC).

**Scenario:** Wedge detector calls `restart_one("ord")` at T=0. The restart
task starts. At T=2s, the user clicks the X button — CloseRequested handler
runs `stop_all` on a separate thread, which sets `shutting_down = true` and
walks the daemon list. When stop_all reaches ord, ord's state is `Stopping`
(from the restart's in-flight `stop_one`) and the v0.2.11 guard makes
stop_all's call a no-op. The restart task continues — eventually finishes
its stop_one, then calls `start_one("ord")`, which spawns a fresh ord even
though btx-app is shutting down. The ord then gets killed when btx-app's
process tree dies.

**Impact:** Cosmetic. The user sees no visible misbehavior; the ord
process starts and dies in milliseconds. But it's a small race that
could surface as an orphaned ord on signet/mainnet where readiness
takes >0s.

**Fix:** In `start_one`, after the state check, also check
`*self.shutting_down.lock().await` and bail. ~5 lines. Worth doing in
v0.2.15 alongside the bitcoind fix.

## LOW #6 — `install.rs` sentinel doesn't clean stale bins on downgrade

**Location:** `install.rs::install_bundled_assets`.

**Scenario:** User installs v0.2.X, then downgrades to v0.2.X-1. The
v0.2.X sentinel still exists at `~/.btx/.installed-v0.2.X` but the v0.2.X-1
sentinel doesn't. Install runs and `cp -f`s the v0.2.X-1 bins over the
v0.2.X bins — but any files present in v0.2.X and removed in v0.2.X-1
(e.g., a deprecated python module) stay on disk.

**Impact:** Mostly harmless bloat. Could cause confusion if a deleted
module is loaded by name (Python won't, since we always run by file path).

**Fix:** Out of scope today. Note for a future major version.

## CLEAN #7 — `btxd.py:h_health` exception coverage complete

**Location:** `btxd.py::h_health`, the raw-socket block.

**Audited:** Catches `OSError` (covers `socket.timeout`/`TimeoutError`,
`socket.error`, `socket.gaierror`, `BlockingIOError`, etc. — all are
subclasses), `ValueError` (covers `int(...)` parse), `TypeError`
(defensive). No path leaks an exception to the HTTP server thread.

**Found correct.**

## CLEAN #8 — CloseRequested handler thread-safety

**Location:** `lib.rs`, the `on_window_event` handler.

**Audited:** Spawns a `std::thread` with its own tokio runtime, calls
`stop_all`, then `window.destroy()`. Per Tauri 2 docs, `Window` is `Send +
Sync` and `destroy()` can be called from any thread. The handler holds
`prevent_close()` so the window stays open until destroy fires.

If `stop_all` panics, the std::thread dies and `window.destroy()` is never
called — the user's window stays frozen until they Force Quit. Bounded
in practice: stop_all's only non-trivial work is spawning wsl.exe
processes (which can't trigger the panic) and awaiting tokio sleep/timeout
(also not panic-prone).

**Found correct.**

## Summary

| # | Severity | Status |
|---|---|---|
| 1 | **CRITICAL** | bitcoind pre-kill is mainnet-unsafe → task #259 (v0.2.15) |
| 2 | Note | wedge detector reset semantics correct |
| 3 | Note | stop_one Stopping guard correct |
| 4 | Note | started_at timing correct |
| 5 | Low | restart_one ignores shutting_down → fold into v0.2.15 |
| 6 | Low | install sentinel doesn't clean stale files on downgrade (defer) |
| 7 | Clean | h_health exception coverage |
| 8 | Clean | CloseRequested thread safety |

Two actionable items for v0.2.15 — both addressed by guarding `start_one`
on `(setup.datadir_override.is_some(), shutting_down)`. The other findings
either document expected behavior or are deferrable.
