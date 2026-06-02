#!/usr/bin/env bash
# b4_watch_funding.sh — poll a funding address until BTC arrives.
#
# Usage: bash b4_watch_funding.sh <address>
#   bash b4_watch_funding.sh bc1q3puzym7yydnkaqe0hw2zpq9fa7k9g65xuwa5gc
#
# Polls every 30s via mempool.space (no node required) until:
# - mempool: detects unconfirmed tx → prints txid, keeps polling for confirmation
# - confirmed: 1+ confirmation → exits 0 and prints "ready to run b4_execute.sh"
#
# Override poll interval: BTX_POLL_SEC=15 bash b4_watch_funding.sh <addr>

set -u

ADDR=${1:-}
if [ -z "$ADDR" ]; then
    echo "usage: bash b4_watch_funding.sh <bc1q...>" >&2
    exit 2
fi
POLL_SEC=${BTX_POLL_SEC:-30}
TIMEOUT_SEC=${BTX_TIMEOUT_SEC:-7200}  # 2h default cap

note()   { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()     { printf '\033[32m[OK]\033[0m %s\n' "$*"; }
status() { printf '\033[2m[%s]\033[0m %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }

printf '\n==> Watching for funding on %s\n' "$ADDR"
echo "  poll every ${POLL_SEC}s, give up after ${TIMEOUT_SEC}s"
echo "  Ctrl+C to stop"

START=$(date +%s)
LAST_STATE="empty"
SEEN_TXID=""

while true; do
    NOW=$(date +%s)
    ELAPSED=$((NOW - START))
    if [ "$ELAPSED" -gt "$TIMEOUT_SEC" ]; then
        echo
        echo "TIMEOUT after ${TIMEOUT_SEC}s. No funding detected. Did the send go through?"
        exit 1
    fi

    # Probe via mempool.space
    JSON=$(curl -sS --max-time 8 "https://mempool.space/api/address/$ADDR" 2>&1)
    if [ -z "$JSON" ] || ! echo "$JSON" | python3 -c 'import sys,json;json.load(sys.stdin)' >/dev/null 2>&1; then
        status "mempool.space probe failed; retrying in ${POLL_SEC}s"
        sleep $POLL_SEC
        continue
    fi

    SUMMARY=$(echo "$JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
cs = d.get('chain_stats', {})
ms = d.get('mempool_stats', {})
print(f\"{cs.get('funded_txo_count',0)} {cs.get('funded_txo_sum',0)} {ms.get('funded_txo_count',0)} {ms.get('funded_txo_sum',0)}\")
")
    set -- $SUMMARY
    CONF_COUNT=${1:-0}
    CONF_SATS=${2:-0}
    MEMPOOL_COUNT=${3:-0}
    MEMPOOL_SATS=${4:-0}

    if [ "$CONF_COUNT" -gt 0 ]; then
        echo
        ok "CONFIRMED — $CONF_SATS sats received in $CONF_COUNT tx(s)"
        # Get the txid for record
        TXID=$(echo "$JSON" | python3 -c "
import sys, json, urllib.request
# fetch the txs themselves
addr = '$ADDR'
url = f'https://mempool.space/api/address/{addr}/txs'
with urllib.request.urlopen(url, timeout=8) as r:
    txs = json.loads(r.read())
if txs:
    print(txs[0].get('txid','?'))
" 2>&1)
        ok "funding txid: $TXID"
        echo
        echo "  Next step:"
        echo "    cd /mnt/c/Users/Ren\\ Shu/Documents/Claude/Projects/bitcoin-terminal-exchange"
        echo "    bash b4_execute.sh"
        exit 0
    elif [ "$MEMPOOL_COUNT" -gt 0 ]; then
        if [ "$LAST_STATE" != "mempool" ]; then
            status "SEEN in mempool: $MEMPOOL_SATS sats in $MEMPOOL_COUNT tx(s). Waiting for 1 confirmation..."
            LAST_STATE="mempool"
        else
            status "still in mempool, waiting for confirmation..."
        fi
    else
        status "no funding yet (waited ${ELAPSED}s)"
    fi
    sleep $POLL_SEC
done
