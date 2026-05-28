# BTX — publishing an order via the Taproot witness-envelope carrier (on-node)

This runs the **second carrier** end-to-end: instead of an `OP_RETURN` output, the BTX artifact rides
in the **witness** of a Taproot script-path spend (inscription-style commit→reveal). Witness data is
not subject to `-datacarriersize`, so this carrier needs no relaxed datacarrier policy.

What this proves that the OP_RETURN path didn't:
- the BIP340 Schnorr signature over the **BIP341 script-path sighash** is accepted by **consensus**
  (the node validates `OP_CHECKSIG` in the revealed leaf — any sighash/sig/control-block error =
  `mandatory-script-verify-flag-failed`);
- the brk-btx indexer extracts the artifact from the **witness** (`btx::extract_from_witness`), not
  just from an output script.

> Status: **PROVEN end-to-end on signet 2026-05-24.** Offline: BIP340 sign/verify matches all official
> vectors and the BIP341 TapSighash matches all 7 keyPathSpending vectors (every sighash type). On-node
> (this runbook): a real envelope reveal (txid `56234a0d…`, commit `76729a0d…:1`) was accepted by
> `sendrawtransaction`, confirmed in block 121, and the order was reconstructed **entirely from the
> reveal's witness** and served at `/api/v1/btx/orders` (offer `5519b9a5…:0`, no OP_RETURN).

## Prerequisites (reuse the persistent signet from `BTX-signet-validation.md`)
- `bitcoind` running on the custom signet, datadir `~/sig-btx`, wallet `btx` loaded & funded,
  `-txindex=1`. Binaries at `~/bitcoin-29.1/bin`.
- `brk_cli` running with `BRK_BLOCK_MAGIC=54d26fbd`, serving on `:3110`.
- The Rust change must be built: in the brk-btx repo, `cargo build -p brk_cli` (and
  `cargo test -p brk_indexer btx` should pass, including the new `envelope_tests`).

All commands below run inside WSL. Set a shortcut:

```bash
BIN=~/bitcoin-29.1/bin
CLI="$BIN/bitcoin-cli -signet -datadir=$HOME/sig-btx -rpcwallet=btx"
cd "/mnt/c/Users/Ren Shu/Documents/Claude/Projects/Bitcoin Terminal Exchange"
```

## Step 1 — maker-sign an order, selecting the envelope carrier

```bash
# pick a funded P2WPKH UTXO as the offer (or let maker-sign choose one):
$CLI listunspent 1 | python3 -c "import sys,json;[print(u['txid'],u['vout'],u['amount']) for u in json.load(sys.stdin) if u['scriptPubKey'].startswith('0014')]"

python3 btx_wallet.py maker-sign \
  --bitcoin-cli "$BIN/bitcoin-cli" --chain signet --datadir "$HOME/sig-btx" --wallet btx \
  --offer-txid <OFFER_TXID> --offer-vout <N> --price-btc 0.002 --carrier envelope
# -> JSON with "artifact_hex": "42545831...". Copy it. (maker-sign also locks the offer UTXO.)
```

## Step 2 — publish via the envelope carrier (funds commit, builds + broadcasts reveal)

```bash
python3 btx_envelope_publish.py publish \
  --artifact-hex <ARTIFACT_HEX> \
  --bitcoin-cli "$BIN/bitcoin-cli" --chain signet --datadir "$HOME/sig-btx" --wallet btx \
  --commit-amount-btc 0.0005 --fee-sats 2000 \
  --broadcast
# -> JSON with commit_txid, commit_vout, reveal_txid, envelope_tapscript_hex, control_block_hex, ...
```

What happens: `sendtoaddress` funds the P2TR commit output, then the reveal spends it with the witness
`[schnorr_sig, envelope_tapscript, control_block]` and is broadcast. **If the reveal is accepted, the
script-path sighash is correct** (consensus just verified it). If it is rejected with
`mandatory-script-verify-flag-failed`, the sighash/sig is wrong — capture the error.

Tip: run once with `--dry-run` first to print the commit address + scriptPubKey without spending.

## Step 3 — confirm the reveal, then index + serve

```bash
# mine one block so the reveal confirms (custom-signet miner; see BTX-signet-validation.md):
cd ~/btc-src && python3 contrib/signet/miner --cli="$BIN/bitcoin-cli -signet -datadir=$HOME/sig-btx" \
  generate --grind-cmd="$BIN/bitcoin-util grind" --address "$($CLI getnewaddress)" \
  --min-nbits --set-block-time $(date +%s)
cd "/mnt/c/Users/Ren Shu/Documents/Claude/Projects/Bitcoin Terminal Exchange"

$CLI getrawtransaction <REVEAL_TXID> true | python3 -c "import sys,json;print('confirmations', json.load(sys.stdin).get('confirmations'))"

# brk_cli auto-indexes the new block; then:
curl -s http://127.0.0.1:3110/api/v1/btx/orders | jq
# the order announced via the witness envelope should now be OPEN in the served book.
```

## What this proves vs. what remains
- **Proved (signet 2026-05-24):** envelope commit/reveal is consensus-valid (Schnorr over the BIP341
  script-path sighash) and the indexer reconstructs an order from witness data — the envelope carrier
  works end-to-end on a live node.
- **Does NOT prove (custom signet only):** cross-node propagation under a *foreign* node's default
  relay policy. The envelope is the same mechanism ordinals use, so it is well-exercised on mainnet,
  but the public-network propagation test still belongs to `BTX-seeding-runbook.md` (public signet).

## Relay-policy dependencies (why this propagates under default relay)

Measured on a real 207-byte BTX v2 artifact (envelope leaf 246 B; reveal witness `[sig, leaf,
control_block]` = 3 items, **no annex**; reveal ≈ 825 WU). Every standardness rule the publish tx
touches, and how close it is:

| Rule | Limit | This tx | Applies? |
|---|---|---|---|
| `MAX_STANDARD_TX_WEIGHT` | 400,000 WU | ~825 WU (~485× under) | yes — clear |
| `MAX_STANDARD_P2WSH_SCRIPT_SIZE` | 3,600 B | leaf 246 B | **NO** — P2WSH (witness v0) only; BIP342 dropped script-size/opcode caps for tapscript (witness v1), which is why inscriptions/BTX use script-path |
| Taproot annex | non-standard if present | none (3-item witness) | yes — BTX never adds an annex |
| Sigops (taproot budget) | 50 + witness weight | 1 `OP_CHECKSIG` | yes — clear |
| `MAX_SCRIPT_ELEMENT_SIZE` | 520 B/push | 207 B → 1 chunk | conventional chunking; not binding |
| `-datacarriersize` | OP_RETURN data only | envelope uses **witness** | **NO — doesn't apply** (this is why "no `-datacarriersize` needed") |

Largest order body: bounded only by `MAX_STANDARD_TX_WEIGHT` (~100 kB of witness), ~3 orders of
magnitude above the ~150–300 B artifact. N is never near any limit.

**Signet ↔ mainnet parity.** Default signet uses mainnet-equivalent mempool/standardness policy (the
signet difference is the block-signature challenge, not relay). Witness weight, taproot script-path
acceptance, annex non-standardness, the sigop budget, and the datacarrier default are identical on
default signet and mainnet — so the signet propagation result transfers to mainnet default relay.
Caveat: a *custom* signet with bespoke `-signetchallenge`/policy, or any node running
`-acceptnonstdtxn` / a raised `-datacarriersize`, is not a parity test; the default config is.

**Fallback ladder if a future Core filters inscription-style envelopes** (note: 2024–2025 proposals to
content-filter witness data were largely rejected by Core as unworkable, and the trend ran toward
*relaxing* the OP_RETURN cap — but plan for it):
1. **OP_RETURN carrier** (`btx_carrier.op_return_carrier`, carrier-agnostic reconstruction) — but the
   207 B artifact exceeds the historical 80 B datacarrier, so it default-relays **only** with
   `-datacarriersize` raised/relaxed. Helps precisely in the "envelopes filtered, datacarrier relaxed"
   world (the likelier one).
2. **Direct miner submission** — relay policy ≠ consensus; a non-standard-but-valid reveal still confirms
   if it reaches a miner. The ultimate escape hatch; degrades the nothing-offchain default gracefully.

**`[VERIFY]` — the exact 2026 mainnet `-datacarriersize` default is beyond this audit's confirmation**
(Core's datacarrier default has been in active flux); verify against the running mainnet release before
relying on the OP_RETURN fallback being default-standard. The witness-envelope path does not depend on it.

## Cleanup
Unlock the offer UTXO if you want to reuse it: `$CLI lockunspent true '[{"txid":"<OFFER_TXID>","vout":<N>}]'`.
