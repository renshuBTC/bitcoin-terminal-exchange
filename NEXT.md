# What's next — pick one when you're back

*Status snapshot as of 2026-06-01 evening. Generated after the autonomous
de-risk run. Five commits shipped today; everything except B4 itself is
either done or ready for you to execute.*

## B4 is the only remaining BLOCKER, and it's primed

Run these two commands when you're ready:

```bash
# 1. Pre-flight (8 checks; should return GREEN)
cd /mnt/c/Users/Ren\ Shu/Documents/Claude/Projects/bitcoin-terminal-exchange
bash b4_preflight.sh

# 2. If GREEN, walk through BTX-B4-mainnet-broadcast-runbook.md
#    The only step I can't do for you is Step 5 (the actual broadcast).
```

Total exposure ≤ $3.50. The runbook + the publisher's F1 fix mean the only
way to lose money is a script-verify rejection (extremely unlikely given the
2026-05-24 signet result + 14/14 offline tests + 32/32 Rust tests all green).

After broadcast: follow `BTX-post-B4-playbook.md` to verify, record txids,
and update the readiness doc.

## Mainnet fee market (snapshot taken 2026-06-01)

- minimumFee / economyFee / hourFee: **1 sat/vB**
- fastestFee (next block): **3 sat/vB**
- mempool depth: ~120k txs (calm)

The runbook's `--fee-sats 200` = 1 sat/vB which is at the floor. If you check
the fee market again before broadcasting and it's higher than 1 sat/vB, use
`--fee-sats <new_floor_in_sats_per_vB * 200>` for headroom. The pre-flight
script does this check too.

## Other open items (none B4-blocking)

| Item | Status | What to do |
|---|---|---|
| **O2: PAT revoke** | Browser action by you | https://github.com/settings/applications — revoke the `gho_` token from earlier. Then confirm SSH push works (it does — proven this session by 5 commits). |
| **O3: clean-VM smoke test** | Script ready (`o3_smoke_test.ps1`) | When you spin up a Windows VM, copy the installer there + run the script. Returns GREEN/YELLOW/RED in ~2 min. |
| **O4: signet soak (≥1 week)** | Pending | Standing pattern: leave the bundle running on signet for 7 days; record any wedges/restarts. Not B4-blocking but valuable for confidence. |
| **E4: walk-back unit test** | Scoped (180 lines / 80 min) | Open `BTX-E4-walkback-unit-test-scoping.md` and implement if/when the algorithm needs to change. Otherwise deferred. |

## What I shipped today (chronological)

1. **`59a4040`** — B3 closure + initial B4 runbook + E1 comment + E4 scoping
2. **`c898a16`** — restored `btx_carrier.py` (silent test failure since `1e15ce5`)
3. **`f2420c0`** — B4 de-risk: `b4_preflight.sh` + envelope publish audit + F1 (KeyboardInterrupt → seckey loss) + fixed `--rune-tx` u16 overflow in runbook
4. **`5692e77`** — cleanup tracked `_etch_state_test.json`
5. **`d2f3342`** — post-B4 playbook + O3 smoke-test PowerShell script + stale v29.1 fixes

Net: **+1,500 lines of docs + scripts**, **~30 lines of code fixes**,
**zero net new dependencies**, **14/14 offline + 32/32 Rust tests still green**.

## How autonomous I am now

| Channel | What it covers |
|---|---|
| Sandbox bash | File ops in /mnt/c, web fetches, sandbox-local compute |
| WSL bash via watcher | Linux shell, daemons, git SSH push, anything Unix |
| PowerShell via WSL interop | Windows-side: registry, processes, `cargo tauri build`, `taskkill`, anything Windows-shell |

Hard rules still in effect (will not bypass):
- **No mainnet broadcasts** (B4's actual `sendrawtransaction`)
- **No typing into your focused terminal window** via computer-use
  keystrokes — but PowerShell interop makes this a non-issue

## State summary

- **BTX desktop app:** running, pid 28596, all 4 daemons up (bitcoind +
  brk_cli + ord + btxd), regtest tip 111, btxd /api/health returns
  `{"ord_height":111,"bitcoind_height":111}`
- **Watcher v2:** running in your WSL terminal (pid 1105319), idle
- **Repo state:** `origin/main` at `d2f3342`, working tree clean
- **Mainnet bitcoind:** not running (you reverted to signet in
  project_btx_mainnet_bringup_2026-05-29). Pre-flight script for B4 expects
  you to start it (`-chain=main`) before running B4.

When you're back: open this file. Decide between B4 (the actual final
mainnet broadcast) or O3 (the clean-VM smoke test) or just calling it
done for the day. Both are de-risked enough that they'd be ~30 min each.
