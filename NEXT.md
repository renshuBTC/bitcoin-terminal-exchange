# What's next — pick one when you're back

*Status snapshot as of 2026-06-02 morning. B4 SHIPPED. The last BLOCKER from
`BTX-mainnet-readiness-2026-05-31.md` is closed. What follows are operational
items, not gates.*

## B4 — DONE ✓ (2026-06-02)

The smallest possible mainnet envelope broadcast happened on 2026-06-02 ~04:40
UTC and confirmed in block 952071 at 04:46:32 UTC.

- **Reveal txid**: `8acf6c70b2c1d75153374ab52f57b6da69ae7606a5931ba295d8cb5dd477f84c`
- **Commit txid**: `199ac25126f363ecb0380a84419ad15399a57bb5ed8d7bd258212cb0a2ed633e`
- **Propagation**: confirmed by mempool.space + blockstream.info + bitaps.com (three
  independent third-party operators, all same block)
- **Witness verification**: BTX1 magic `42545831` at byte offset 38 of reveal's witness[1]
  tapscript, artifact head `425458310201007f969800010001...` (BTX1 v2, runestone-flag)
- **Total cost**: 568 sats fees + 5,460 commit dust returned as 5,057-sat reveal output

The technical mainnet-readiness case is empirically closed. See `BTX-B4-mainnet-broadcast-runbook.md`
"Record of execution" and `BTX-mainnet-readiness-2026-05-31.md` B4 section for the full record.

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
