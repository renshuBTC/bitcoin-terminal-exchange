# BTX Prompt 4 — host-side broadcast closure runbook

The sandbox-side sweep (`btx_artifact_adversarial.py`) empirically proves:

- **L1** (`parse_artifact`) is *total* on arbitrary bytes — 200K random buffers, 0 leaked exceptions; 7 named structural-rejection cases all raise clean `ValueError`; 4 structurally-valid cases admitted (defense moves to L2/L3).
- **L2** (`verify_maker_sig`) rejects 4 forgery shapes: non-P2WPKH offer_spk, truncated spk, pubkey-doesn't-own-offer, junk DER sig.

What this runbook closes: the **L3 indexer admission gate** — proves the BRK indexer (`brk_cli`) refuses to admit a parseable-but-forged artifact when it appears on a real regtest chain. No PASS-by-equivalence: the artifact is built, broadcast via the envelope carrier, mined, indexed, and the `/api/v1/btx/orders` endpoint must return `[]`.

## Prereqs

Same stack as the rename-audit Prompt 5 / E2E Prompt 6: bitcoind v29.1 regtest, a funded wallet, `brk_cli` against the regtest chain, `btxd` on port 3333 (optional — we'll query `brk_cli` directly).

## Step 0 — Stack up, fresh regtest

```bash
# Assume bitcoind regtest is running with a funded wallet mined to maturity.
# Replace these with your actual paths from the rename-audit runbook.
export BITCOIN_DATADIR="$HOME/.bitcoin-regtest"
export BTX_DIR="/mnt/c/Users/Ren Shu/Documents/Claude/Projects/bitcoin-terminal-exchange"
export BRK_DIR="/mnt/c/Users/Ren Shu/Documents/Claude/Projects/brk-btx"
export BRK_OUT="$HOME/.brk-btx-prompt4"

# Bitcoind ready check
bitcoin-cli -regtest -datadir="$BITCOIN_DATADIR" getblockcount
```

## Step 1 — Build a forged artifact (junk DER sig, otherwise well-formed)

```bash
cd "$BTX_DIR"
python3 - <<'PY'
# Take the canonical good artifact and replace just the maker_sig with junk bytes of the same length.
# Result: parses cleanly (L1 admits), L2 sig-verify FAILS, must be rejected by the indexer.
import btx_0b as btx
GOOD_HEX = ("4254583102010040d10c000100e80300000000000080f0fa020000000000ca9a3b0000000000000000"
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa00000000160014"
            "e9dd842d95a053c513315291f4d3f93b5a41059a2102bbfcf90b65934a165af1508d129cd749e764"
            "3bf75c66bd7f209a15f0b1497d7a8347304402205be5b4425958d1d6e0f8eb67cf4a7a2dc091d5d5"
            "f1ea08bc776896a03d8bfb3102205e6433b48f725d819e039749bd427299d33e4ba28b4e8ebb231d"
            "2574dc35577f83")
good = bytes.fromhex(GOOD_HEX)
parsed = btx.parse_artifact(good)
sig_len = len(parsed["maker_sig"])
# Replace the LAST sig_len bytes with junk (preserving the leading sig_len byte and 0x83 sighash flag positions)
forged = bytearray(good)
forged[-sig_len:] = bytes([0x30, 0x44]) + b"\x00" * (sig_len - 3) + bytes([0x83])
# Sanity: still parses
assert btx.parse_artifact(bytes(forged))["amount"] == parsed["amount"]
print("FORGED_HEX=" + bytes(forged).hex())
PY
```

Copy the `FORGED_HEX=...` line and export it:

```bash
export FORGED_HEX=<paste hex here>
```

## Step 2 — Publish via the envelope carrier

```bash
cd "$BTX_DIR"
python3 btx_envelope_publish.py publish \
  --artifact-hex "$FORGED_HEX" \
  --chain regtest \
  --datadir "$BITCOIN_DATADIR" \
  --wallet default \
  --broadcast \
  --state-file /tmp/btx-prompt4-state.json

# The script prints the commit + reveal txids. Mine two blocks to confirm.
bitcoin-cli -regtest -datadir="$BITCOIN_DATADIR" -generate 2
```

## Step 3 — Re-index with `brk_cli` and check the order book

```bash
# Start brk_cli (or restart if already running) against the same chain.
# Use the exact invocation from BTX-rename-audit-prompts.md Prompt 5 — flags must be --brkdir / --blocksdir / --rpccookiefile.
cd "$BRK_DIR"
CARGO_TARGET_DIR=$HOME/.cargo-target-brk-btx cargo run --release --bin brk_cli -- run \
  --brkdir "$BRK_OUT" \
  --blocksdir "$BITCOIN_DATADIR/regtest/blocks" \
  --rpccookiefile "$BITCOIN_DATADIR/regtest/.cookie" \
  --rpcurl http://127.0.0.1:18443 \
  --webserverport 3119 &
BRK_PID=$!
sleep 8

# Query the orders endpoint.
echo "=== /api/v1/btx/orders ===" ; curl -s http://127.0.0.1:3119/api/v1/btx/orders
echo ; echo "=== brk_cli log tail ===" ; tail -50 ~/.brk_cli/logs/*.log 2>/dev/null || true

# Stop brk_cli when done.
kill $BRK_PID
```

## Pass criteria

- `bitcoin-cli sendrawtransaction` / `btx_envelope_publish.py --broadcast` succeeds — the carrier tx is valid Bitcoin (forged artifact bytes are opaque payload to mempool).
- After re-index, `GET /api/v1/btx/orders` returns **`[]`** (empty array, NOT including the forged offer).
- `brk_cli` log contains **no** `panicked at` / `unwrap` / `RUST_BACKTRACE` traces — parsing the malformed artifact didn't crash the indexer.

## What this proves

| Layer | Before this runbook | After this runbook |
|---|---|---|
| L1 — parser totality | Sandbox sweep PASS | (unchanged) |
| L2 — sig refusal | Sandbox sweep PASS | (unchanged) |
| **L3 — indexer admission gate on a real chain** | Inferred from Rust unit tests | **Empirically PASS** |

Plus: confirms the *Rust indexer parser is total* under real chain data (the rejected artifact actually went through Rust's `parse_artifact` + `verify_maker_sig` path, not a synthetic input).

## Optional extensions

If you have time, repeat with two more shapes from the audit doc:

1. **Wrong MAGIC (FFFFFFFF prefix)** — confirms L1 path. Expect the indexer to skip the envelope without panic; orders should still be `[]`.
2. **Zero-amount artifact** (admits at L1, must refuse at L3) — confirms the indexer's semantic admission rule.

Each repeat costs ~30 seconds of regtest activity. Three different rejections = three independent empirical confirmations of the indexer's defense in depth.
