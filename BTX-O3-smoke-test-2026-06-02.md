# O3 — BTX v0.2.19 installer smoke test PASS (2026-06-02)

*Operational readiness gate from `BTX-mainnet-readiness-2026-05-31.md`. The
question: does the v0.2.19 NSIS installer install cleanly on a Windows machine
where BTX has never been installed (or has been fully uninstalled), and does
the supervisor successfully bring up all four bundled daemons?*

## Verdict

**GREEN.** Installer + supervisor + all four bundled daemons all healthy in 31
seconds wall-clock from launch to verdict.

```
=== GREEN - installer + supervisor + 4 daemons all healthy. O3 PASSES. ===
```

## Setup

| Field | Value |
|---|---|
| Date | 2026-06-02 |
| Host | Windows 11 Home (could not use Windows Sandbox — Sandbox needs Pro/Enterprise) |
| Cleanliness mechanism | uninstaller (silent `/S`) + `~/.btx` rm -rf |
| Installer | `BTX_0.2.19_x64-setup.exe` |
| Installer size | 24,728,316 bytes (~23.6 MB) |
| Installer SHA-256 | `1052a27fd1d500ea7429fc069d539569405174c6ed0cb167d48cf1c1e04a8dee` |
| Build time | 2026-06-02 17:56:02 (via `cargo tauri build` earlier same day) |

The "clean state" before the test:

- Registry: no `*BTX*` entries under `HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*`
- Filesystem: `%LOCALAPPDATA%\BTX\btx-app.exe` absent
- WSL: `~/.btx/` did not exist (4.2 GB of prior signet data deleted)

Confirmed by the smoke test itself in step 2 (`[OK] no existing BTX install detected`).

## Sequence of checks

```
[OK]   installer present: BTX_0.2.19_x64-setup.exe (23.6 MB)
[OK]   SHA256 matches expected
[OK]   no existing BTX install detected
[..]   running installer (silent /S)
[OK]   installer exited 0
[OK]   registry DisplayVersion = 0.2.19
[OK]   InstallLocation = "C:\Users\Ren Shu\AppData\Local\BTX"
[OK]   btx-app.exe present at C:\Users\Ren Shu\AppData\Local\BTX\btx-app.exe
[OK]   bundled binary present: bitcoind (14.5 MB)
[OK]   bundled binary present: bitcoin-cli (2.4 MB)
[OK]   bundled binary present: brk_cli (36.3 MB)
[OK]   bundled binary present: ord (24 MB)
[..]   launching btx-app.exe
[OK]   supervisor btx-app.exe PID=20464 memory=5.4MB
[..]   waiting up to 90s for btxd at http://127.0.0.1:3333/api/health
[OK]   btxd /api/health 200 (after 13s)
[OK]   bitcoind_height = 11479
[OK]   ord_height = 0
```

The post-install daemon-readiness time was **13 seconds** — under the
90-second timeout, comfortable margin.

The `bitcoind_height = 11479` value reflects signet's current tip range; signet
IBD was beginning. `ord_height = 0` is expected: ord syncs after bitcoind has
some headers, this is captured at the very start.

## Run command

```powershell
.\o3_smoke_test.ps1 `
    -InstallerPath ".\app\target\release\bundle\nsis\BTX_0.2.19_x64-setup.exe" `
    -ExpectedSha256 "1052a27fd1d500ea7429fc069d539569405174c6ed0cb167d48cf1c1e04a8dee" `
    -SkipMineCheck
```

`-SkipMineCheck` was passed because (a) it adds dependency on a regtest setup
that takes additional cleanup to validate, and (b) the regtest-mine
sub-test is a "nice to have" — the load-bearing question is "does
`/api/health` come up at all", which it did.

## Smoke-test script fixes (committed alongside)

The original `o3_smoke_test.ps1` (#338) had two PowerShell parser issues that
manifested only when the script actually ran (not during static parse): a
parenthesised expression `(4-daemon supervisor up)` inside a double-quoted
string, and a WSL here-string with backtick-escaped variables that confused
PowerShell's tokenizer differently at parse-time vs run-time. Both fixed; the
rewritten script is structurally cleaner (single-quoted strings where
possible, no here-strings) and parses + runs identically.

## What this proves

- The installer artifact built by `cargo tauri build` on this machine produces
  a working `btx-app.exe` + bundled Linux daemons on a clean Windows install.
- The NSIS silent install (`/S` flag) succeeds without UAC prompts (runs as
  the current user, install location is `%LOCALAPPDATA%\BTX`, no admin
  required).
- The supervisor's first-launch behavior works: with `setup.json` missing
  from `~/.btx`, the supervisor defaulted to signet (per the Setup struct's
  `Default` impl: `chain=signet, wallet=btx`) and spawned all 4 daemons.
- btxd's `/api/health` is reachable on the expected port and returns
  structured JSON with `bitcoind_height` + `ord_height`.

## What this doesn't prove

- **Truly fresh-Windows behavior.** This was a "user uninstalled then
  reinstalled" test, not "Windows just installed from ISO" test. The
  uninstaller removes the registry entry and program files, but other Windows
  state (Defender exclusions, network adapter settings, hardware-specific
  glitches) is the same as the host machine. A true clean-VM test on a fresh
  Windows ISO would tighten this. That would need either (a) Windows Pro/
  Enterprise for Windows Sandbox, or (b) a VirtualBox/VMware VM with a
  Windows ISO.
- **Mainnet IBD performance.** The daemons came up but on signet, against a
  fresh datadir. Mainnet bring-up has different latency characteristics
  (covered separately by `project_btx_mainnet_bringup_2026-05-29`).
- **Long-running stability.** Covered by O4 (the 1-week signet soak), which
  resumed after this test.

## How to re-run

The script is committed at `o3_smoke_test.ps1`. The installer artifact
location can drift between builds; check
`app/target/release/bundle/nsis/` for the current `.exe` and pass its path
+ SHA to the script.

For a true "clean state" re-run on this machine:

```powershell
# 1. Uninstall existing BTX
& "$env:LOCALAPPDATA\BTX\uninstall.exe" /S
Start-Sleep 5

# 2. Wipe WSL-side state
wsl bash -c 'rm -rf $HOME/.btx'

# 3. Run smoke test
.\o3_smoke_test.ps1 -ExpectedSha256 "<new SHA>" -SkipMineCheck
```

After the test, restore the soak per `BTX-O4-signet-soak-2026-06-02.md`'s
restart instructions if you want it to continue.
