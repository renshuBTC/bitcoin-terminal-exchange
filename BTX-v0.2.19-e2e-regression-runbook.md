# BTX v0.2.19 — E2E regression runbook

*Re-prove the full trade rail on the bundled app at version 0.2.19. The loop was last empirically
proven on v0.2.5 (block 226, GUI-verified — see project memory `project_btx_v025_e2e`). Between
v0.2.6 and v0.2.19, 14 supervisor/indexer/carrier additions landed; this runbook tests that none
of them regressed the loop and that several new behaviors are reachable.*

Companion to:
- [`BTX-bundled-app-e2e-runbook.md`](./BTX-bundled-app-e2e-runbook.md) — the original v0.2.10-era
  walkthrough; reuse its etch/sign/publish/book/fill steps verbatim in Phase B below.
- [`BTX-walkback-regtest-runbook.md`](./BTX-walkback-regtest-runbook.md) — exercise the brk_indexer
  walk-back specifically (Phase C5 here is a lighter touch on the same code path).

## Scope — what's new since v0.2.5

Each row below is a thing you're testing didn't regress:

| Phase | Source | What this regression-tests |
|---|---|---|
| C1 | v0.2.5 `a7863b5` | Graceful close via X / `CloseRequested`; chain survives a relaunch |
| C2 | v0.2.6 `3aac5d0` | Ord stale-redb-lock pre-flight recovery on regtest |
| C3 | v0.2.10 / v0.2.12 / v0.2.16 / v0.2.17 | Ord wedge detector (stall-based, false-positive-immune) |
| C4 | v0.2.11 `3cd41bd` | No double-close SIGTERM artifact |
| C5 | v0.2.18 `e01e641` + brk-btx `8a197f3` | Stale-state recovery (supervisor pre-flight on regtest **or** brk_indexer walk-back inside the indexer) |
| C6 | v0.2.13 `0643ee8` | brk_cli `/api/v1/btx/orders?refresh=<any>` accepted |
| C7 | v0.2.14 `fb1e8a4` | Stale port-owner is pre-killed before spawn |
| D  | v0.2.15 `ac123a4` | `externally_managed` flag protects user's mainnet bitcoind (mainnet-only check; skip on regtest) |
| —  | brk-btx `5ec96c2` | F2 walk-back diagnostic logs visible in brk_cli output (entry + success) |

Phase B is the original v0.2.5 lifecycle (etch → maker-sign → publish → book → fill → trades). If
Phase B fails, Phase C and beyond are blocked.

## Prerequisites

- Bundled BTX v0.2.19 installed at `%LOCALAPPDATA%\BTX\btx-app.exe`. Verify the version chip in the
  app's title-bar; `bin/linux/brk_cli` should have sha256 starting `d131dc42…` (the F2-baked build).
- WSL Ubuntu with `bitcoin-cli` available (the bundle ships its own, at `~/.btx/bin/`).
- PowerShell + WSL bash side by side.
- Clean state: see Step 0 below to wipe regtest before starting (mandatory for deterministic Phase
  C results).

## Step 0 — wipe to a known state

```bash
# WSL
pkill -9 -x bitcoind || true
pkill -9 -x brk_cli  || true
pkill -9 -x ord      || true
pkill -9 -f btxd.py  || true
sleep 1

# ONLY regtest; never touch signet/mainnet datadirs from here.
rm -rf $HOME/.btx/regtest
rm -rf $HOME/.btx/brk-regtest
rm -rf $HOME/.btx/ord/regtest
rm -f  /tmp/btx-*.log
```

Then write `~/.btx/setup.json` to force regtest (same pattern as the original runbook):

```bash
cat > ~/.btx/setup.json <<'EOF'
{"chain":"regtest","wallet":"btx","datadir_override":null}
EOF
```

## Phase A — smoke test (target: ~2 min)

1. Launch via PowerShell:

   ```powershell
   Start-Process -FilePath "$env:LOCALAPPDATA\BTX\btx-app.exe"
   ```

2. Loading screen for ~30s, then trade page renders. Verify the four status chips top-right:
   `ORACLE ON · SYNC 100.0% · CONNECT` — all green.

3. **Cross-check the brk_cli log shows NO recovery activity:**

   ```bash
   grep -E 'walking back|Walk-back recovered|brk_cli-recover' /tmp/btx-brk_cli.log
   ```

   Expected: no matches. Clean state, no recovery needed, no false-positive triggered.

4. Cross-check ord brought up cleanly:

   ```bash
   grep -E 'Database already open|ord-recover' /tmp/btx-ord.log
   ```

   Expected: no matches.

**Phase A pass:** all four chips green, no recovery breadcrumbs in any log. If a chip is red, jump
to "Failure modes" before continuing.

## Phase B — original lifecycle loop (target: ~5-10 min)

Follow [`BTX-bundled-app-e2e-runbook.md`](./BTX-bundled-app-e2e-runbook.md) **Steps 2 through 7
verbatim**. They're unchanged between v0.2.5 and v0.2.19: etch a rune, fund, maker-sign + publish
via the Trade page, watch it appear on the Book page, fill it from WSL, confirm the atomic-swap
txid on the Trades page.

**Phase B pass criteria** (same as v0.2.5 proof):

| Page | Final state |
|---|---|
| Trade | `ORDER BOOK: book <hash>… · 0 orders · indexer agreed`, STREAM HASH advanced |
| Book  | 0 OPEN ORDERS, 1 RECENT FILL, 1 ATOMIC SWAP `<swap_txid>` h*N* |
| Trades| 1 trade leg: rune `<id>`, amount, paid BTC |

Note `<swap_txid>` and the final block height for the post-Phase-B checks below.

## Phase C — new edge cases (target: ~10-15 min total)

Each subsection is independent; you can run them in any order. They all assume Phase B passed.

### C1 — Graceful close survives a relaunch (v0.2.5)

1. Close BTX by clicking the window's X button (NOT via Task Manager).
2. From WSL, confirm all four daemons exited cleanly:
   ```bash
   pgrep -lf 'bitcoind|brk_cli|ord|btxd' || echo "all stopped"
   ```
3. Relaunch via PowerShell. After the loading screen, the Book page should still show the
   `<swap_txid>` from Phase B at the same block height.

**C1 pass:** chain survives, no `Database already open` on the next ord boot.

### C2 — Ord stale-redb-lock recovery (v0.2.6 / regtest only)

1. With BTX running, from PowerShell or Task Manager, **kill the `ord.exe` proxy** (or from WSL:
   `pkill -KILL -x ord`).
2. The supervisor's ord watcher restarts ord; the pre-flight grep for `Database already open`
   detects the redb-lock signature in `/tmp/btx-ord.log` and runs the `rm -rf` recovery:

   ```bash
   grep '\[ord-recover\] stale redb lock detected' /tmp/btx-ord.log
   ```

   Expected: at least one match.
3. Within ~30s the ORACLE ON chip should be green again.

**C2 pass:** ord recovered automatically, chip returns green, no manual intervention.

### C3 — Ord wedge detector (v0.2.10 / v0.2.12 / v0.2.16 / v0.2.17)

Hard to deterministically trigger. The lightweight proof: leave the app running for >60s on
regtest with bitcoind making no progress, and verify NO wedge fires (which would indicate the
v0.2.16 false-positive regression returned).

```bash
grep -c 'ord appears wedged' /tmp/btx-debug.log
```

Expected: `0` matches over a 60-second idle window after Phase B.

**C3 pass:** no spurious wedge reports.

### C4 — No double-close SIGTERM artifact (v0.2.11)

1. Close BTX via the X button. Observe in the WSL terminal that runs the supervisor (if you have
   the debug pane visible) that you see **exactly one** SIGTERM-and-shutdown sequence per daemon,
   not two.

(Hard to grep for from the log alone; this one is best verified by the absence of two
back-to-back shutdown banners.)

### C5 — Stale-state recovery (v0.2.18 + brk-btx 8a197f3)

The full deterministic version of this test is in
[`BTX-walkback-regtest-runbook.md`](./BTX-walkback-regtest-runbook.md). The light touch for the
regression runbook:

1. Close BTX cleanly.
2. From WSL, manually start bitcoind with `-reindex`:
   ```bash
   $HOME/.btx/bin/bitcoind -regtest -datadir=$HOME/.btx/regtest -reindex -daemon
   sleep 2
   ```
3. Relaunch BTX immediately. The supervisor brings up brk_cli, which on startup hits
   `find_recognized_ancestor` (brk-btx 8a197f3). With F2 logs (brk-btx 5ec96c2), look for:

   ```bash
   grep -E 'Indexer tip not recognized by bitcoind; walking back|Walk-back recovered at stored index' /tmp/btx-brk_cli.log
   ```

   Expected: **either** one of these matches (walk-back fired and recovered) OR the v0.2.18
   supervisor-side wipe fired first:

   ```bash
   grep '\[brk_cli-recover\] stale brk state vs bitcoind' /tmp/btx-brk_cli.log
   ```

   At least one of the two should be visible. Both are valid recovery outcomes; record which.

**C5 pass:** chain re-syncs and resumes; SYNC chip eventually returns to 100%. No `error -26` or
`fatal: ...` in the log.

### C6 — brk_cli `?refresh=<any>` accepted (v0.2.13)

```bash
curl -s -o /dev/null -w "%{http_code}\n" 'http://127.0.0.1:3140/api/v1/btx/orders?refresh=true'
curl -s -o /dev/null -w "%{http_code}\n" 'http://127.0.0.1:3140/api/v1/btx/orders?refresh=1'
curl -s -o /dev/null -w "%{http_code}\n" 'http://127.0.0.1:3140/api/v1/btx/orders?ignored=true'
```

Expected: `200`, `200`, `400`. The third probes the `EmptyOrRefresh` extractor's reject behavior
on a non-`refresh` query key.

### C7 — Stale port-owner pre-kill (v0.2.14)

Hard to trigger deterministically without leaving a binary running from a previous session. If
you've recently re-bundled brk_cli or btxd:

1. Note the PID of the running brk_cli.
2. Close BTX, immediately relaunch (within 1-2 seconds before any TIME_WAIT timeout).
3. The new supervisor's port-readiness probe sees :3140 occupied; the v0.2.14 pre-kill
   (`pkill -KILL -x brk_cli; pkill -KILL -x brk`) fires before the new spawn.

```bash
grep -E 'pre-kill stale port|spawned brk_cli' /tmp/btx-debug.log | tail -5
```

(Optional check; mostly relevant during repeated re-bundling cycles, not normal user flow.)

## Phase D — externally_managed bitcoind (mainnet-only; skip on regtest)

This phase only applies if you have a mainnet Bitcoin Core node already running and your BTX
`~/.btx/setup.json` has `datadir_override` pointing at it. v0.2.15 added an `externally_managed:
true` flag that prevents the supervisor from ever sending SIGTERM/SIGKILL to your production
node, even on shutdown or stale-state recovery.

If you're not testing this, skip. If you are:

1. Confirm your `~/.btx/setup.json` has the `datadir_override` set.
2. Launch BTX. Confirm `externally_managed: true` propagates through the supervisor by checking
   bitcoind is reached but never SIGTERM'd on close:

   ```bash
   # WSL
   pgrep -f bitcoind  # your prod node PID
   # ... (use BTX, close BTX) ...
   pgrep -f bitcoind  # SHOULD still show the SAME PID, unchanged
   ```

**Phase D pass:** your bitcoind PID is unchanged across a BTX open/close cycle.

## Pass criteria — overall

The regression test PASSES if all of:

- [ ] Phase A: all 4 chips green, no recovery breadcrumbs in any log on a clean launch
- [ ] Phase B: original lifecycle loop produces the v0.2.5 expected end states (book hash advances,
      RECENT FILL appears, ATOMIC SWAP txid surfaces)
- [ ] C1: graceful close + relaunch preserves chain state
- [ ] C2: ord stale-redb-lock auto-recovers without manual rm-rf
- [ ] C3: no spurious wedge reports during idle
- [ ] C4: single SIGTERM per daemon on close (no double-close artifact)
- [ ] C5: stale-state recovery fires (either supervisor pre-flight OR brk_indexer walk-back) and
      sync resumes
- [ ] C6: `?refresh=<value>` returns 200; non-refresh query key returns 400
- [ ] D (mainnet only, if testing): `externally_managed` bitcoind PID survives a BTX cycle

## Failure modes — what to do

| Symptom | Likely cause | Action |
|---|---|---|
| Loading screen stuck >2 min | One of the daemons crashed during init | Check `/tmp/btx-{bitcoind,brk_cli,ord,btxd}.log` for the latest error |
| SYNC chip stays red | bitcoind isn't responding to RPC | Verify cookie file at `~/.btx/regtest/regtest/.cookie` exists |
| ORACLE chip stays red | ord wedged or syncing | C2 above — if ord stale-lock didn't recover, `rm -rf ~/.btx/ord/regtest` manually |
| Trade page shows `book hash mismatch` | brk_cli vs indexer disagreement | Likely brk_cli is stale; C5 should fix it on next launch, or wipe `~/.btx/brk-regtest` manually |
| Phase C5 falls through to `full_reset` | bitcoind diverged from brk_cli's stored chain entirely | Valid outcome; brk_cli re-indexes from genesis (~seconds on regtest with a handful of blocks) |
| Phase D bitcoind PID changed | v0.2.15 protection regressed | **CRITICAL** — supervisor sent SIGTERM to externally-managed bitcoind. Open an audit ticket. |

## Recording results

Add a section to your local copy of this file (or capture in chat) with the per-phase outcome,
the brk_cli sha256 you tested (`d131dc42…` for the F2-baked build), and any unexpected log lines.
That snapshot is what closes the regression test for v0.2.19.
