#!/usr/bin/env bash
# b4_preflight.sh — one-shot pre-flight before B4 (smallest mainnet broadcast).
#
# Verifies every prerequisite from BTX-B4-mainnet-broadcast-runbook.md so the
# user can run B4 confident that the only thing not yet validated is the
# broadcast itself. Returns "GREEN ready to broadcast" or "RED <reason>".
#
# Usage:
#   bash b4_preflight.sh                  # uses defaults below
#   BTX_BIN=/path/to/bin bash b4_preflight.sh
#
# Output is structured: each check has [OK]/[WARN]/[FAIL] prefix. If any FAIL,
# script exits 1. If only WARNs, exits 0 but verdict is YELLOW.

set -u

# ---- defaults; override via env ----
BTX_BIN=${BTX_BIN:-$HOME/.btx/bin}
BTX_DATADIR=${BTX_DATADIR:-$HOME/.bitcoin}    # standard mainnet datadir (datadir mode)
BTX_WALLET=${BTX_WALLET:-btx}
BTX_REPO=${BTX_REPO:-/mnt/c/Users/Ren Shu/Documents/Claude/Projects/bitcoin-terminal-exchange}

# External-RPC mode (talks to a bitcoind running on a different host, e.g. Windows-side
# bitcoin-qt from WSL). If BTX_RPCCONNECT is set, the script uses -rpcconnect/-rpcport/
# -rpcuser/-rpcpassword instead of -datadir. Matches the EXTERNAL_RPC pattern in
# btx-launch.sh (project_btx_mainnet_bringup_2026-05-29).
BTX_RPCCONNECT=${BTX_RPCCONNECT:-}
BTX_RPCPORT=${BTX_RPCPORT:-8332}
BTX_RPCUSER=${BTX_RPCUSER:-}
BTX_RPCPASSWORD=${BTX_RPCPASSWORD:-}

# Cost ceiling: the absurd-price order's offer + fees should be tiny.
MAX_OFFER_SATS=${MAX_OFFER_SATS:-10000}      # warn if picked UTXO > 10k sats

BCLI_BIN="$BTX_BIN/bitcoin-cli"
if [ -n "$BTX_RPCCONNECT" ]; then
    # External-RPC mode
    BCLI="$BCLI_BIN -rpcconnect=$BTX_RPCCONNECT -rpcport=$BTX_RPCPORT -rpcuser=$BTX_RPCUSER -rpcpassword=$BTX_RPCPASSWORD -rpcwallet=$BTX_WALLET"
    printf '\n==> Mode: EXTERNAL_RPC to %s:%s as user=%s wallet=%s\n' "$BTX_RPCCONNECT" "$BTX_RPCPORT" "$BTX_RPCUSER" "$BTX_WALLET"
else
    # Datadir / cookie mode
    BCLI="$BCLI_BIN -datadir=$BTX_DATADIR -rpcwallet=$BTX_WALLET"
fi

FAILS=0
WARNS=0

ok()   { printf '\033[32m[OK]\033[0m %s\n' "$1"; }
warn() { printf '\033[33m[WARN]\033[0m %s\n' "$1"; WARNS=$((WARNS+1)); }
fail() { printf '\033[31m[FAIL]\033[0m %s\n' "$1"; FAILS=$((FAILS+1)); }

printf '\n==> BTX B4 pre-flight (%s)\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ---- 1. binaries present ----
[ -x "$BCLI_BIN" ] && ok "bitcoin-cli present at $BCLI_BIN" \
                   || fail "bitcoin-cli not found at $BCLI_BIN (set BTX_BIN)"

# ---- 2. mainnet bitcoind RPC reachable ----
CHAIN_JSON=$($BCLI getblockchaininfo 2>&1)
if [ $? -ne 0 ]; then
    fail "bitcoin-cli getblockchaininfo failed: $(echo "$CHAIN_JSON" | head -1)"
else
    CHAIN=$(echo "$CHAIN_JSON" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("chain",""))')
    BLOCKS=$(echo "$CHAIN_JSON" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("blocks",0))')
    PROG=$(echo "$CHAIN_JSON" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(round(d.get("verificationprogress",0),4))')
    HDRS=$(echo "$CHAIN_JSON" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("headers",0))')

    if [ "$CHAIN" = "main" ]; then
        ok "bitcoind chain=main, height=$BLOCKS (headers=$HDRS, progress=$PROG)"
        if [ "$(echo "$PROG >= 0.9999" | bc -l 2>/dev/null || echo 0)" = "1" ]; then
            ok "mainnet fully synced (progress >= 0.9999)"
        else
            fail "mainnet NOT fully synced (progress=$PROG); broadcasting on an unsynced node is unsafe"
        fi
    else
        fail "bitcoind chain=$CHAIN — B4 requires chain=main. Did you point at the wrong datadir?"
    fi
fi

# ---- 3. wallet loaded ----
# NOTE: Core v30 removed `balance`/`unconfirmed_balance` from getwalletinfo;
# they now live in getbalances.mine.trusted/untrusted_pending. We try
# getbalances first and fall back to the old field names for pre-v30 nodes.
WALLET_JSON=$($BCLI getwalletinfo 2>&1)
if [ $? -ne 0 ]; then
    fail "wallet '$BTX_WALLET' not loaded ($WALLET_JSON | head -1)"
else
    BALANCES_JSON=$($BCLI getbalances 2>&1)
    BAL=$(echo "$BALANCES_JSON" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    mine = d.get("mine", {})
    print(mine.get("trusted", 0))
except Exception:
    print(0)
' 2>&1)
    UNCONF=$(echo "$BALANCES_JSON" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    mine = d.get("mine", {})
    print(mine.get("untrusted_pending", 0))
except Exception:
    print(0)
' 2>&1)
    # Pre-v30 fallback: if getbalances returned 0 but getwalletinfo has balance, use that
    if [ "$BAL" = "0" ]; then
        OLDBAL=$(echo "$WALLET_JSON" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("balance",0))' 2>&1)
        if [ "$OLDBAL" != "0" ]; then BAL=$OLDBAL; fi
    fi
    ok "wallet '$BTX_WALLET' loaded; confirmed=$BAL BTC, unconfirmed=$UNCONF BTC"
    BAL_SATS=$(python3 -c "print(int(round($BAL * 100000000)))")
    if [ "$BAL_SATS" -lt 15000 ]; then
        fail "wallet balance ($BAL BTC = $BAL_SATS sats) is below the 15,000-sat minimum for B4 (offer + commit + reveal fees)"
    fi
fi

# ---- 4. a usable P2WPKH UTXO exists ----
UTXO_JSON=$($BCLI listunspent 1 9999999 2>&1)
if [ $? -ne 0 ]; then
    fail "listunspent failed"
else
    PICKED=$(echo "$UTXO_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
target_max = $MAX_OFFER_SATS / 100000000
best = None
for u in d:
    if u['scriptPubKey'].startswith('0014') and u['amount'] >= 0.00005 and u['amount'] <= target_max * 2:
        if best is None or u['amount'] < best['amount']:
            best = u
print(json.dumps(best) if best else '')
")
    if [ -z "$PICKED" ]; then
        fail "no suitable P2WPKH UTXO found (need >= 5,000 sats, prefer < 20,000 sats to bound exposure)"
    else
        OUTXO=$(echo "$PICKED" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["txid"]+":"+str(d["vout"]))')
        OAMT=$(echo "$PICKED" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["amount"])')
        OAMT_SATS=$(python3 -c "print(int(round($OAMT * 100000000)))")
        if [ "$OAMT_SATS" -gt "$MAX_OFFER_SATS" ]; then
            warn "smallest suitable UTXO is $OAMT BTC ($OAMT_SATS sats) — above the $MAX_OFFER_SATS-sat target. Larger exposure if order somehow gets filled."
        fi
        ok "candidate offer UTXO: $OUTXO = $OAMT BTC ($OAMT_SATS sats)"
    fi
fi

# ---- 5. fee market check ----
FEE_JSON=$($BCLI estimatesmartfee 6 2>&1)
if [ $? -ne 0 ]; then
    warn "estimatesmartfee failed; check fee market manually at mempool.space before broadcasting"
else
    FR=$(echo "$FEE_JSON" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("feerate",0))' 2>&1)
    if [ "$FR" = "0" ]; then
        warn "estimatesmartfee returned 0 feerate (insufficient data); check mempool.space"
    else
        FR_SATSVB=$(python3 -c "print(round($FR * 100000000 / 1000, 2))")
        # 200vB reveal at this fee rate:
        FR_FEE=$(python3 -c "print(int(round($FR * 100000000 / 1000 * 200)))")
        ok "estimatesmartfee 6-block: $FR BTC/kvB ≈ $FR_SATSVB sat/vB"
        echo "      → at this rate, the 200vB reveal needs ~$FR_FEE sats fee"
        if [ "$FR_FEE" -gt 200 ]; then
            warn "fee market is higher than the runbook's --fee-sats 200 default; consider --fee-sats $((FR_FEE + 200))"
        fi
    fi
fi

# ---- 6. mempool.space reachable (for post-broadcast verification) ----
if curl -sf --max-time 5 https://mempool.space/api/v1/fees/recommended >/dev/null 2>&1; then
    MP_FEES=$(curl -s --max-time 5 https://mempool.space/api/v1/fees/recommended 2>&1)
    MP_MIN=$(echo "$MP_FEES" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("minimumFee","?"))' 2>&1)
    ok "mempool.space reachable; minimumFee = $MP_MIN sat/vB"
else
    warn "mempool.space unreachable; you'll need a different way to verify propagation after broadcast"
fi

# ---- 7. publisher selftest passes ----
cd "$BTX_REPO" 2>/dev/null || true
SELFTEST=$(python3 -c 'import btx_envelope_publish as p; ok=p.selftest()' 2>&1 | tail -3)
if echo "$SELFTEST" | grep -q 'ALL_PASS": true'; then
    ok "btx_envelope_publish offline selftest passes"
else
    fail "btx_envelope_publish offline selftest FAILED — do NOT broadcast until investigated"
    echo "$SELFTEST" | head -5
fi

# ---- 8. no stale state files from prior runs that could confuse recovery ----
STALE=$(ls $HOME/.btx/b4-state-*.json 2>/dev/null | head -3)
if [ -n "$STALE" ]; then
    warn "found previous B4 state file(s) at: $STALE"
    echo "      review or delete them before running B4 fresh"
fi

# ---- VERDICT ----
echo
if [ "$FAILS" -gt 0 ]; then
    printf '\033[31m=== RED — %d failure(s), %d warning(s). DO NOT broadcast. ===\033[0m\n' "$FAILS" "$WARNS"
    exit 1
elif [ "$WARNS" -gt 0 ]; then
    printf '\033[33m=== YELLOW — 0 failures, %d warning(s). Review warnings before broadcast. ===\033[0m\n' "$WARNS"
    exit 0
else
    printf '\033[32m=== GREEN — all checks passed. Ready to execute BTX-B4-mainnet-broadcast-runbook.md ===\033[0m\n'
    exit 0
fi
