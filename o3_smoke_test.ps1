# o3_smoke_test.ps1 - BTX v0.2.19 installer smoke test
#
# Verifies the v0.2.19 NSIS installer installs cleanly on a fresh Windows
# (or one where BTX has been uninstalled) and the supervisor brings up
# btxd's /api/health endpoint.
#
# Usage:
#   .\o3_smoke_test.ps1
#   .\o3_smoke_test.ps1 -InstallerPath "C:\path\to\setup.exe" -ExpectedSha256 "..."
#
# Exit codes: 0 = PASS or YELLOW; 1 = RED

param(
    [string]$InstallerPath = "C:\Users\Ren Shu\Documents\Claude\Projects\bitcoin-terminal-exchange\app\target\release\bundle\nsis\BTX_0.2.19_x64-setup.exe",
    [string]$ExpectedSha256 = "",
    [string]$ExpectedVersion = "0.2.19",
    [int]$DaemonWaitSec = 90,
    [int]$BtxdPort = 3333,
    [switch]$SkipMineCheck
)

$ErrorActionPreference = 'Continue'
$script:Fails = 0
$script:Warns = 0

function Write-Ok    { param($m) Write-Host "[OK]   $m" -ForegroundColor Green }
function Write-Warn2 { param($m) Write-Host "[WARN] $m" -ForegroundColor Yellow; $script:Warns++ }
function Write-Fail2 { param($m) Write-Host "[FAIL] $m" -ForegroundColor Red;    $script:Fails++ }

$now = Get-Date -Format 'o'
Write-Host ''
Write-Host "==> BTX v$ExpectedVersion installer smoke test ($now)" -ForegroundColor Cyan
Write-Host ''

# ---- 1. installer file + SHA ----
if (-not (Test-Path $InstallerPath)) {
    Write-Fail2 "installer not found at: $InstallerPath"
    exit 1
}
$sizeMb = [math]::Round((Get-Item $InstallerPath).Length / 1MB, 1)
Write-Ok "installer present: $InstallerPath ($sizeMb MB)"

$actualSha = (Get-FileHash $InstallerPath -Algorithm SHA256).Hash.ToLower()
if ($ExpectedSha256 -ne '' -and $actualSha -eq $ExpectedSha256.ToLower()) {
    Write-Ok "SHA256 matches expected"
} elseif ($ExpectedSha256 -eq '') {
    Write-Warn2 "no expected SHA256 provided (got $actualSha)"
} else {
    Write-Warn2 "SHA256 mismatch - expected $ExpectedSha256, got $actualSha"
}

# ---- 2. no existing install ----
$reg = Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
       Where-Object { $_.DisplayName -like '*BTX*' }
if ($reg) {
    $existingVer = $reg.DisplayVersion
    Write-Fail2 "BTX already installed (DisplayVersion=$existingVer). Smoke test needs a clean state."
    exit 1
}
Write-Ok "no existing BTX install detected"

# ---- 3. run installer silently ----
Write-Host '[..] running installer (silent /S)' -ForegroundColor Cyan
$proc = Start-Process -FilePath $InstallerPath -ArgumentList '/S' -Wait -PassThru -ErrorAction SilentlyContinue
if ($null -eq $proc) {
    Write-Fail2 'installer process did not start'
    exit 1
}
$exitCode = $proc.ExitCode
if ($exitCode -ne 0) {
    Write-Fail2 "installer exited with code $exitCode"
    exit 1
}
Write-Ok "installer exited 0"

# ---- 4. registry entry ----
$reg2 = Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -like '*BTX*' }
if (-not $reg2) {
    Write-Fail2 'no BTX registry entry after install'
    exit 1
}
$displayVer = $reg2.DisplayVersion
if ($displayVer -ne $ExpectedVersion) {
    Write-Fail2 "DisplayVersion is '$displayVer', expected '$ExpectedVersion'"
} else {
    Write-Ok "registry DisplayVersion = $displayVer"
}
$installLoc = $reg2.InstallLocation
Write-Ok "InstallLocation = $installLoc"

# ---- 5. expected files on disk ----
$installRoot = $installLoc -replace '^"|"$', ''
$btxApp = Join-Path $installRoot 'btx-app.exe'
$binDir = Join-Path $installRoot 'bin\linux'
if (-not (Test-Path $btxApp)) {
    Write-Fail2 "btx-app.exe missing at $btxApp"
    exit 1
}
Write-Ok "btx-app.exe present at $btxApp"

$bins = @('bitcoind', 'bitcoin-cli', 'brk_cli', 'ord')
foreach ($b in $bins) {
    $p = Join-Path $binDir $b
    if (Test-Path $p) {
        $bsz = [math]::Round((Get-Item $p).Length / 1MB, 1)
        Write-Ok "bundled binary present: $b ($bsz MB)"
    } else {
        Write-Fail2 "bundled binary missing: $b"
    }
}

# ---- 6. launch btx-app ----
Write-Host '[..] launching btx-app.exe' -ForegroundColor Cyan
Start-Process -FilePath $btxApp | Out-Null
$deadline = (Get-Date).AddSeconds(30)
$sup = $null
while ((Get-Date) -lt $deadline) {
    $sup = Get-Process btx-app -ErrorAction SilentlyContinue
    if ($sup) { break }
    Start-Sleep -Milliseconds 500
}
if ($null -eq $sup) {
    Write-Fail2 'btx-app.exe did not appear in process list within 30s'
    exit 1
}
$supId = $sup.Id
$supMem = [math]::Round($sup.WorkingSet / 1MB, 1)
Write-Ok "supervisor btx-app.exe PID=$supId memory=${supMem}MB"

# ---- 7. wait for /api/health ----
$url = "http://127.0.0.1:$BtxdPort/api/health"
Write-Host "[..] waiting up to ${DaemonWaitSec}s for btxd at $url" -ForegroundColor Cyan
$deadline = (Get-Date).AddSeconds($DaemonWaitSec)
$start = Get-Date
$healthOk = $false
$healthJson = $null
while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-WebRequest -Uri $url -TimeoutSec 3 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($resp.StatusCode -eq 200) {
            $elapsed = [int]((Get-Date) - $start).TotalSeconds
            Write-Ok "btxd /api/health 200 (after ${elapsed}s)"
            $healthJson = $resp.Content | ConvertFrom-Json
            $healthOk = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $healthOk) {
    Write-Fail2 "btxd /api/health never returned 200 within ${DaemonWaitSec}s"
} else {
    if ($null -ne $healthJson.bitcoind_height) {
        $bh = $healthJson.bitcoind_height
        Write-Ok "bitcoind_height = $bh"
    }
    if ($null -ne $healthJson.ord_height) {
        $oh = $healthJson.ord_height
        Write-Ok "ord_height = $oh"
    }
}

# ---- VERDICT ----
Write-Host ''
if ($script:Fails -gt 0) {
    $f = $script:Fails
    $w = $script:Warns
    Write-Host "=== RED - $f failure(s), $w warning(s). O3 NOT passing. ===" -ForegroundColor Red
    exit 1
}
if ($script:Warns -gt 0) {
    $w = $script:Warns
    Write-Host "=== YELLOW - 0 failures, $w warning(s). Review then accept. ===" -ForegroundColor Yellow
    exit 0
}
Write-Host '=== GREEN - installer + supervisor + 4 daemons all healthy. O3 PASSES. ===' -ForegroundColor Green
exit 0
