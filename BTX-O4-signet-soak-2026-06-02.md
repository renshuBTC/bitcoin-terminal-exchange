# O4 — BTX 1-week signet soak

*Started 2026-06-02 ~09:42 UTC, after B4 mainnet milestone. Goal: leave the
bundled BTX desktop running on signet for ≥ 7 days under normal-use
conditions and record any wedge, crash, restart, or resource regression. The
soak is one of the operational readiness items from
[`BTX-mainnet-readiness-2026-05-31.md`](./BTX-mainnet-readiness-2026-05-31.md);
B4 closes the technical mainnet-readiness case, this soak closes the
"stays alive for a week" case.*

## Soak design

**What is being soaked**

- BTX desktop app installed at `%LOCALAPPDATA%\BTX\btx-app.exe` (v0.2.19 NSIS
  installer, the same artifact mainnet broadcast was performed against).
- Configured via `~/.btx/setup.json` for `chain=signet, wallet=btx,
  datadir_override=null`.
- Supervisor spawns all four bundled daemons inside WSL: `bitcoind`, `ord`,
  `brk_cli`, `btxd`.
- Wallet "btx" is auto-created on first launch (per `project-btx-v021-and-m7-ord-wedge`
  memory's recorded behavior).

**What is observed**

A periodic probe (`btx_soak_probe.sh`) captures one line of CSV state per
invocation:

```
timestamp_utc,
btx_app_alive,
bitcoind_height,
bitcoind_progress,
bitcoind_ibd,
ord_alive,
btxd_alive,
brk_cli_alive,
btxd_chain_height,
btxd_ord_height,
bitcoind_mem_mb,
btxd_mem_mb,
brk_cli_mem_mb,
ord_mem_mb,
recent_error_lines
```

The probe **does not intervene**. If a daemon goes down, the supervisor in
btx-app should respawn it automatically (per the v0.2.6 / v0.2.8 / v0.2.12
restart paths). The probe records what the supervisor actually does over time.

**Cadence**

Hourly via a Windows Scheduled Task (`BTX-O4-soak-probe`) that invokes a
small `.cmd` wrapper at `%LOCALAPPDATA%\BTX\run-soak-probe.cmd`. The wrapper
runs `wsl.exe -e bash -lc "bash <probe-path> >> /tmp/btx-soak.out 2>&1"`.

Trigger: every 1 hour for 7 days (`-RepetitionDuration 7d`), with
`-StartWhenAvailable`, `-AllowStartIfOnBatteries`, `-DontStopIfGoingOnBatteries`.
Survives sleep, reboot, and WSL session exit — Task Scheduler is Windows-level.

Output log: `~/.btx/soak.log` (CSV, append-only — WSL filesystem).
Stdout: `/tmp/btx-soak.out` (per-probe summary lines — WSL `/tmp`, ephemeral).

**Stopping conditions**

- Natural end at 168 hours (one-week `RepetitionDuration`).
- Manual stop: `Unregister-ScheduledTask -TaskName 'BTX-O4-soak-probe' -Confirm:$false`
  via PowerShell on Windows.
- Pause without unregistering: `Disable-ScheduledTask -TaskName 'BTX-O4-soak-probe'`.

**Why the scheduled task over a nohup loop**

Initially launched as `nohup bash -c '...'` inside WSL. That works while WSL
has at least one active terminal but dies when WSL shuts down entirely
(no attached sessions, machine sleep into hibernate, etc.). For a true
multi-day soak we need Windows-level scheduling. The Scheduled Task wakes
WSL on demand if it isn't running and runs the probe.

## What counts as "passing" the soak

The signal we are looking for, in priority order:

1. **No daemon stays down longer than one probe interval.** A transient
   restart-and-recover is fine; a daemon down for ≥ 2 consecutive hourly
   probes is a wedge.
2. **No btx-app process restart.** The supervisor wraps the daemons; the
   whole btx-app should stay up.
3. **`btxd_chain_height` tracks `bitcoind_height` within one block** once IBD
   completes (`bitcoind_ibd=0`). A growing gap suggests an indexer wedge.
4. **No unbounded memory growth.** Watch the `_mem_mb` columns. Signet is a
   low-volume chain so memory should plateau within ~24h of IBD completing.
5. **`recent_error_lines` count stays at the same order of magnitude across
   probes.** A jump suggests something started failing.

If any of these break, the post-mortem evidence is the CSV row(s) preceding
the break + the daemon's own debug log under `~/.btx/data/signet/debug.log`
(bitcoind) or wherever the supervisor wrote `~/.btx/{btxd,brk_cli,ord}.log`.

## Baseline (T+0)

Initial probe immediately after launch, before IBD completion:

```
2026-06-02T09:44:17Z,1,263693,0.5583,1,1,0,1,-1,-1,0,0,0,0,0
```

- btx-app: alive ✓
- bitcoind: alive, height 263693, progress 55.83%, **in IBD**
- ord: alive ✓
- brk_cli: alive ✓ (came up while bitcoind is still syncing — expected)
- btxd: not yet alive (supervisor waits for brk_cli health before spawning btxd)
- 0 errors in any log

Pre-existing state notes:

- `~/.btx/data/signet/` was 4.2 GB at start — chain was previously synced to
  some height by earlier sessions, so this is **not** a from-zero IBD. The
  bundled bitcoind picked up from disk where the prior shutdown left off.
- `~/.btx/.installed-v0.2.19` sentinel present → supervisor will NOT re-install
  the binaries, just spawn them from `~/.btx/bin/`. This isolates the soak from
  any install-side issues.
- `setup.json` rewritten from `chain=regtest` (from the B3 walk-back work) to
  `chain=signet`. The chain-switching message in
  [[project-btx-v021-and-m7-ord-wedge]] notes this can be messy — flagging in
  case we see early wedges that are switch-artifacts rather than soak-relevant.

## How to read the soak afterward

After 7 days, generate a summary:

```bash
SLOG=$HOME/.btx/soak.log
echo "total probes:"
wc -l < "$SLOG"
echo
echo "daemon liveness counts (1 = up):"
awk -F, 'NR>1 { ba+=$2; bd+=$5; o+=$6; bx+=$7; b+=$8 } END {
    printf "  btx_app=%d/%d  bitcoind_ibd=%d/%d  ord=%d/%d  btxd=%d/%d  brk_cli=%d/%d\n",
    ba, NR-1, bd, NR-1, o, NR-1, bx, NR-1, b, NR-1
}' "$SLOG"
echo
echo "height progression (first/middle/last):"
awk -F, 'NR>1 { h=$3 } END { print "  last_height="h }' "$SLOG"
awk -F, 'NR>1 && NR<=3 { print "  early "$1" height="$3 }' "$SLOG"
echo
echo "max recent_error_lines:"
awk -F, 'NR>1 && $NF+0 > max { max=$NF } END { print "  "max }' "$SLOG"
```

A successful soak reads as: high btx_app/ord/btxd/brk_cli counts (close to
N-probes), bitcoind_ibd flips from 1 to 0 within the first few hours,
btxd_chain_height tracks bitcoind_height after that, all `_mem_mb` columns
plateau, `recent_error_lines` stays in single digits per probe.

## State files for later reference

- Hourly CSV: `~/.btx/soak.log`
- Per-probe summary: `/tmp/btx-soak.out`
- Watcher pid: `/tmp/btx-soak-watcher.pid`
- Probe script: `btx_soak_probe.sh` (this repo)
- BTX install root: `%LOCALAPPDATA%\BTX\` (Windows)
- Bundled-daemon datadir: `~/.btx/data/signet/` (WSL)
- Setup config: `~/.btx/setup.json` (WSL)

## What this soak does NOT cover

- **Mainnet behavior.** Already covered by B4 (single-shot broadcast). A
  multi-day mainnet soak would be a separate exercise — needs different
  resource estimates given mainnet block sizes.
- **Active trading load.** This is a baseline-of-life soak: no orders are
  being published, no fills are happening. A separate "active load soak"
  would publish + fill orders on a synthetic schedule.
- **Adversarial conditions.** No fuzzing, no fault injection. The soak
  observes what the system does under normal conditions only.

These are out of scope. If they become relevant they'd be O5, O6, O7.
