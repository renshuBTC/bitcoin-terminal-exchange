# Build + reinstall + launch BTX, then tail the stderr log.
#
# Usage from PowerShell:
#   cd C:\Users\Ren Shu\Documents\Claude\Projects\bitcoin-terminal-exchange\app
#   .\rebuild.ps1
#
# This is the canonical dev loop. Don't paste these commands into WSL bash —
# PowerShell cmdlets like Stop-Process / Start-Sleep don't exist there, and
# `cargo tauri build` in WSL would target Linux (libdbus-sys error).

$ErrorActionPreference = "Stop"

Write-Host "[rebuild] stopping any running btx-app..."
Get-Process btx-app -ErrorAction SilentlyContinue | Stop-Process -Force

Write-Host "[rebuild] cargo tauri build..."
cargo tauri build
if ($LASTEXITCODE -ne 0) { throw "cargo tauri build failed" }

# Derive the installer path from Cargo.toml so the script self-updates with version bumps.
$cargo = Get-Content .\Cargo.toml -Raw
if ($cargo -notmatch 'version\s*=\s*"([\d.]+)"') { throw "couldn't find version in Cargo.toml" }
$version = $Matches[1]
$installer = ".\target\release\bundle\nsis\BTX_${version}_x64-setup.exe"
if (-not (Test-Path $installer)) { throw "installer not found: $installer" }

Write-Host "[rebuild] uninstalling previous BTX..."
$uninst = "$env:LOCALAPPDATA\BTX\uninstall.exe"
if (Test-Path $uninst) {
    & $uninst /S
    Start-Sleep 3
}

Write-Host "[rebuild] installing $installer..."
& $installer /S
Start-Sleep 5

$logPath = "$env:TEMP\btx-app.stderr.log"
Write-Host "[rebuild] launching btx-app, stderr -> $logPath"
$proc = Start-Process -FilePath "$env:LOCALAPPDATA\BTX\btx-app.exe" `
    -RedirectStandardError $logPath -PassThru
Write-Host "[rebuild] btx-app PID: $($proc.Id)"

Write-Host "[rebuild] waiting 30s for daemon stack..."
Start-Sleep 30

Write-Host ""
Write-Host "=== last 20 stderr lines ==="
Get-Content $logPath -Tail 20
