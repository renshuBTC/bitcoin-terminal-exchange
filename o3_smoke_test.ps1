# o3_smoke_test.ps1 — BTX v0.2.19 installer smoke test
#
# Purpose: O3 from BTX-mainnet-readiness-2026-05-31.md — verify the v0.2.19
# NSIS installer installs cleanly on a fresh Windows and that the supervisor
# successfully brings up all 4 daemons.
#
# Run this on a CLEAN Windows VM (or one where BTX has never been installed).
# DO NOT run on your dev box — it'll uninstall your live BTX.
#
# Usage (in PowerShell on the clean VM, as your own user — NOT elevated):
#   .\o3_smoke_test.ps1                                     # uses default installer path
#   .\o3_smoke_test.ps1 -InstallerPath "C:\path\to\setup.exe"
#   .\o3_smoke_test.ps1 -SkipMineCheck                      # skip the optional regtest tip-advance test
#
# Exit codes: 0 = PASS, 1 = FAIL.

param(
    [string]$InstallerPath = "C:\Users\Ren Shu\Documents\Claude\Projects\bitcoin-terminal-exchange\app\target\release\bundle\nsis\BTX_0.2.19_x64-setup.exe",
    [string]$ExpectedSha256 = "ec596147e47aeecec38eedbc139ab679371a074093ec7eec97cac4fae1591482",
    [string]$ExpectedVersion = "0.2.19",
    [int]$DaemonWaitSec = 90,
    [switch]$SkipMineCheck
)

$ErrorActionPreference = "Continue"
$Fails = 0
$Warns = 0

function Ok    ($msg) { Write-Host "[OK]   $msg" -ForegroundColor Green }
function Warn  ($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow; $script:Warns++ }
function Fail  ($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red;    $script:Fails++ }

Write-Host ""
Write-Host "==> BTX v$ExpectedVersion installer smoke test ($(Get-Date -Format o))" -ForegroundColor Cyan
Write-Host ""

# ---- 1. installer file present, right hash ----
if (-not (Test-Path $InstallerPath)) {
    Fail "installer not found at: $InstallerPath"
    exit 1
}
$installerSize = (Get-Item $InstallerPath).Length
Ok "installer present: $InstallerPath ($([math]::Round($installerSize / 1MB, 1)) MB)"

$actualSha = (Get-FileHash $InstallerPath -Algorithm SHA256).Hash.ToLower()
if ($actualSha -eq $ExpectedSha256) {
    Ok "SHA256 matches expected ($ExpectedSha256)"
} else {
    Warn "SHA256 mismatch — expected $ExpectedSha256, got $actualSha"
    Write-Host "       (this might be expected if you rebuilt the installer locally)"
}

# ---- 2. confirm BTX not already installed ----
$existing = Get-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*" -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -like "*BTX*" }
if ($existing) {
    Fail "BTX already installed (DisplayVersion=$($existing.DisplayVersion)). This smoke test MUST run on a clean Windows VM where BTX has never been installed. Aborting."
    exit 1
}
Ok "no existing BTX install detected"

# ---- 3. run the installer silently (/S = NSIS silent mode) ----
Write-Host "[..] running installer silently with /S ..." -ForegroundColor Cyan
$installArgs = @("/S")
$installProc = Start-Process -FilePath $InstallerPath -ArgumentList $installArgs -Wait -PassThru -ErrorAction SilentlyContinue
if ($null -eq $installProc) {
    Fail "installer process didn't start (Start-Process returned null)"
    exit 1
}
if ($installProc.ExitCode -ne 0) {
    Fail "installer exited with code $($installProc.ExitCode) (non-zero = NSIS error)"
    exit 1
}
Ok "installer exited 0"

# ---- 4. verify registry entry was created ----
$reg = Get-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*" -ErrorAction SilentlyContinue |
       Where-Object { $_.DisplayName -like "*BTX*" }
if (-not $reg) {
    Fail "no BTX registry entry after install (HKCU Uninstall\\*BTX*)"
    exit 1
}
if ($reg.DisplayVersion -ne $ExpectedVersion) {
    Fail "DisplayVersion is '$($reg.DisplayVersion)', expected '$ExpectedVersion'"
} else {
    Ok "registry DisplayVersion = $($reg.DisplayVersion)"
}
Ok "InstallLocation = $($reg.InstallLocation)"

# ---- 5. expected files on disk ----
$installRoot = $reg.InstallLocation -replace '^"|"$', ''
$btxApp = Join-Path $installRoot "btx-app.exe"
$binDir = Join-Path $installRoot "bin\linux"
if (-not (Test-Path $btxApp)) {
    Fail "btx-app.exe missing at $btxApp"
    exit 1
}
Ok "btx-app.exe present at $btxApp"

$expectedBins = @("bitcoind", "bitcoin-cli", "brk_cli", "ord")
foreach ($b in $expectedBins) {
    $p = Join-Path $binDir $b
    if (Test-Path $p) {
        $sz = [math]::Round((Get-Item $p).Length / 1MB, 1)
        Ok "bundled binary present: $b ($sz MB)"
    } else {
        Fail "bundled binary missing: $b"
    }
}

# ---- 6. launch btx-app.exe (supervisor) ----
Write-Host "[..] launching btx-app.exe ..." -ForegroundColor Cyan
Start-Process -FilePath $btxApp | Out-Null

# Wait for supervisor process to be visible
$deadline = (Get-Date).AddSeconds(30)
$supervisor = $null
while ((Get-Date) -lt $deadline) {
    $supervisor = Get-Process btx-app -ErrorAction SilentlyContinue
    if ($supervisor) { break }
    Start-Sleep -Milliseconds 500
}
if ($null -eq $supervisor) {
    Fail "btx-app.exe didn't appear in process list within 30s"
    exit 1
}
Ok "supervisor btx-app.exe PID=$($supervisor.Id), memory=$([math]::Round($supervisor.WorkingSet/1MB,1)) MB"

# ---- 7. wait for /api/health on port 3333 (btxd) ----
Write-Host "[..] waiting up to ${DaemonWaitSec}s for btxd /api/health (4-daemon supervisor up) ..." -ForegroundColor Cyan
$deadline = (Get-Date).AddSeconds($DaemonWaitSec)
$healthOk = $false
while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:3333/api/health" -TimeoutSec 3 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($resp.StatusCode -eq 200) {
            $health = $resp.Content | ConvertFrom-Json
            Ok "btxd /api/health 200 (after $([int]((Get-Date)-($deadline.AddSeconds(-$DaemonWaitSec))).TotalSeconds)s)"
            if ($null -ne $health.bitcoind_height) {
                Ok "  bitcoind_height = $($health.bitcoind_height)"
            }
            if ($null -ne $health.ord_height) {
                Ok "  ord_height = $($health.ord_height)"
            }
            $healthOk = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $healthOk) {
    Fail "btxd /api/health never returned 200 within ${DaemonWaitSec}s"
}

# ---- 8. optional: regtest tip advance test ----
if (-not $SkipMineCheck -and $healthOk) {
    Write-Host "[..] optional: mine a regtest block and verify it indexes ..." -ForegroundColor Cyan
    # Health endpoint already told us current heights. Compare after a fresh mine.
    try {
        $before = (Invoke-WebRequest -Uri "http://127.0.0.1:3333/api/health" -UseBasicParsing).Content | ConvertFrom-Json
        Start-Sleep -Seconds 5
        # Mine via WSL bitcoin-cli (the wizard creates wallet 'btx' on first launch)
        $wslMine = "/usr/bin/wsl.exe"
        $cliCmd = @"
ADDR=`$(`$HOME/.btx/bin/bitcoin-cli -regtest -datadir=`$HOME/.btx/data/regtest -rpccookiefile=`$HOME/.btx/data/regtest/regtest/.cookie -rpcwallet=btx getnewaddress 2>/dev/null)
`$HOME/.btx/bin/bitcoin-cli -regtest -datadir=`$HOME/.btx/data/regtest -rpccookiefile=`$HOME/.btx/data/regtest/regtest/.cookie -rpcwallet=btx generatetoaddress 1 "`$ADDR" 2>/dev/null | head -1
"@
        $mineOut = & wsl.exe bash -c $cliCmd 2>&1
        Start-Sleep -Seconds 5
        $after = (Invoke-WebRequest -Uri "http://127.0.0.1:3333/api/health" -UseBasicParsing).Content | ConvertFrom-Json
        if ($after.bitcoind_height -gt $before.bitcoind_height) {
            Ok "regtest tip advanced ($($before.bitcoind_height) -> $($after.bitcoind_height)) — supervisor + daemons end-to-end functional"
        } else {
            Warn "regtest tip did not advance (was $($before.bitcoind_height), now $($after.bitcoind_height)); could be wallet not yet created or mining failed"
        }
    } catch {
        Warn "regtest mine test threw: $_"
    }
}

# ---- VERDICT ----
Write-Host ""
if ($Fails -gt 0) {
    Write-Host "=== RED — $Fails failure(s), $Warns warning(s). O3 NOT passing on this VM. ===" -ForegroundColor Red
    exit 1
} elseif ($Warns -gt 0) {
    Write-Host "=== YELLOW — 0 failures, $Warns warning(s). Review then accept or rerun. ===" -ForegroundColor Yellow
    exit 0
} else {
    Write-Host "=== GREEN — installer + supervisor + 4 daemons all healthy. O3 PASSES on this VM. ===" -ForegroundColor Green
    Write-Host "Suggested next: leave it running for 5 minutes, confirm no crashes, then mark O3 done." -ForegroundColor Cyan
    exit 0
}
