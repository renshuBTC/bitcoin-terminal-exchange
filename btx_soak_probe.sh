#!/usr/bin/env bash
# btx_soak_probe.sh — periodic health snapshot for the O4 1-week signet soak.
#
# Captures one line of state per invocation to a long-running CSV log:
#   timestamp_utc,btx_app_alive,bitcoind_height,bitcoind_progress,bitcoind_ibd,
#   ord_alive,btxd_alive,brk_cli_alive,btxd_health_json,btxd_chain_height,btxd_ord_height,
#   bitcoind_mem_mb,btxd_mem_mb,brk_cli_mem_mb,ord_mem_mb,recent_errors
#
# Recovery semantics: if any daemon is down, the supervisor in btx-app should
# respawn it automatically. The probe records the state but does NOT intervene
# — the whole point of a soak is to observe what the supervisor actually does
# over time.
#
# Usage:
#   bash btx_soak_probe.sh                        # one snapshot
#   while true; do bash btx_soak_probe.sh; sleep 3600; done   # hourly
#
# Override paths via env:
#   BTX_HOME=$HOME/.btx (default)
#   BTX_LOG=$BTX_HOME/soak.log (default — append-only CSV)
#   BTX_BIN=$BTX_HOME/bin/bitcoin-cli (default)

set -u

BTX_HOME=${BTX_HOME:-$HOME/.btx}
BTX_LOG=${BTX_LOG:-$BTX_HOME/soak.log}
BTX_BIN=${BTX_BIN:-$BTX_HOME/bin/bitcoin-cli}
BTX_DATADIR=${BTX_DATADIR:-$BTX_HOME/data/signet}

TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# --- Process liveness via PowerShell ---
PS='/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'

# Returns "1,<mem_mb>" if process alive, "0,0" if not
proc_state() {
    local NAME=$1
    $PS -Command "
        \$p = Get-Process $NAME -ErrorAction SilentlyContinue
        if (\$p) {
            \$mem = [math]::Round((\$p | Measure-Object WorkingSet -Sum).Sum / 1MB, 1)
            Write-Output \"1,\$mem\"
        } else { Write-Output \"0,0\" }
    " 2>/dev/null | tr -d '\r' | head -1
}

# Returns "1" if TCP port open, "0" otherwise
port_open() {
    local P=$1
    $PS -Command "
        \$r = Get-NetTCPConnection -LocalPort $P -State Listen -ErrorAction SilentlyContinue
        if (\$r) { Write-Output 1 } else { Write-Output 0 }
    " 2>/dev/null | tr -d '\r' | head -1
}

BTX_APP=$(proc_state btx-app)
BTX_APP_ALIVE=$(echo "$BTX_APP" | cut -d, -f1)

# --- bitcoind state via bundled bitcoin-cli ---
if [ -x "$BTX_BIN" ]; then
    CHAIN_JSON=$("$BTX_BIN" -datadir="$BTX_DATADIR" -chain=signet getblockchaininfo 2>/dev/null)
    if [ -n "$CHAIN_JSON" ]; then
        BITCOIND_HEIGHT=$(echo "$CHAIN_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("blocks",0))' 2>/dev/null || echo 0)
        BITCOIND_PROGRESS=$(echo "$CHAIN_JSON" | python3 -c 'import sys,json; print(round(json.load(sys.stdin).get("verificationprogress",0),4))' 2>/dev/null || echo 0)
        BITCOIND_IBD=$(echo "$CHAIN_JSON" | python3 -c 'import sys,json; print(int(json.load(sys.stdin).get("initialblockdownload",True)))' 2>/dev/null || echo 1)
    else
        BITCOIND_HEIGHT=0; BITCOIND_PROGRESS=0; BITCOIND_IBD=1
    fi
else
    BITCOIND_HEIGHT=0; BITCOIND_PROGRESS=0; BITCOIND_IBD=1
fi

# --- daemon liveness ---
ORD_ALIVE=$(port_open 38332)
BTXD_ALIVE=$(port_open 9777)
BRK_CLI_ALIVE=$(port_open 3140)

# --- btxd health (only meaningful when btxd is up) ---
if [ "$BTXD_ALIVE" = "1" ]; then
    BTXD_HEALTH=$(curl -sS --max-time 3 http://localhost:9777/api/health 2>/dev/null | tr -d '\n' | head -c 400)
    BTXD_CHAIN_HEIGHT=$(echo "$BTXD_HEALTH" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("bitcoind_height",-1))' 2>/dev/null || echo -1)
    BTXD_ORD_HEIGHT=$(echo "$BTXD_HEALTH" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("ord_height",-1))' 2>/dev/null || echo -1)
else
    BTXD_HEALTH=""; BTXD_CHAIN_HEIGHT=-1; BTXD_ORD_HEIGHT=-1
fi

# --- per-daemon memory footprint via WSL-side ps ---
# The bundled daemons are Linux ELF binaries running inside WSL (supervisor launches
# them via cmd.exe + WSL interop), so they appear in the WSL process list, NOT in
# Windows Get-Process. We use ps -eo to read RSS in KB and convert to MB.
mem_mb() {
    local NAME=$1
    local KB
    KB=$(ps -eo rss=,comm= 2>/dev/null | awk -v n="$NAME" '$2 == n { sum += $1 } END { print sum+0 }')
    awk -v kb="$KB" 'BEGIN { printf "%.1f", kb / 1024 }'
}
BITCOIND_MEM=$(mem_mb bitcoind)
BTXD_MEM=$(mem_mb python3)   # btxd is a python script, hard to disambiguate from other py; conservative
BRK_CLI_MEM=$(mem_mb brk)
ORD_MEM=$(mem_mb ord)

# --- error tail: count "error" lines in recent logs (rough wedge indicator) ---
ERR_COUNT=0
for L in "$BTX_HOME/data/signet/debug.log" "$BTX_HOME/btxd.log" "$BTX_HOME/brk_cli.log" "$BTX_HOME/ord.log"; do
    if [ -f "$L" ]; then
        # count error lines in the last 200 lines (recent window)
        N=$(tail -200 "$L" 2>/dev/null | grep -ciE "(^|\W)error|panic|stalled|wedge" 2>/dev/null || echo 0)
        ERR_COUNT=$((ERR_COUNT + N))
    fi
done

# --- write CSV header on first probe, then append the line ---
if [ ! -f "$BTX_LOG" ]; then
    echo "timestamp_utc,btx_app_alive,bitcoind_height,bitcoind_progress,bitcoind_ibd,ord_alive,btxd_alive,brk_cli_alive,btxd_chain_height,btxd_ord_height,bitcoind_mem_mb,btxd_mem_mb,brk_cli_mem_mb,ord_mem_mb,recent_error_lines" > "$BTX_LOG"
fi

echo "$TS,$BTX_APP_ALIVE,$BITCOIND_HEIGHT,$BITCOIND_PROGRESS,$BITCOIND_IBD,$ORD_ALIVE,$BTXD_ALIVE,$BRK_CLI_ALIVE,$BTXD_CHAIN_HEIGHT,$BTXD_ORD_HEIGHT,$BITCOIND_MEM,$BTXD_MEM,$BRK_CLI_MEM,$ORD_MEM,$ERR_COUNT" >> "$BTX_LOG"

# Echo summary for ad-hoc visibility
echo "[$TS] app=$BTX_APP_ALIVE bitcoind=h$BITCOIND_HEIGHT/$BITCOIND_PROGRESS (ibd=$BITCOIND_IBD) ord=$ORD_ALIVE btxd=$BTXD_ALIVE(h$BTXD_CHAIN_HEIGHT) brk_cli=$BRK_CLI_ALIVE mem={bitcoind=${BITCOIND_MEM}MB,btxd=${BTXD_MEM}MB,brk=${BRK_CLI_MEM}MB,ord=${ORD_MEM}MB} err=$ERR_COUNT"
