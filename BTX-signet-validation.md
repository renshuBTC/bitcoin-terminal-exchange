# BTX — signet validation runbook

**Goal:** take BTX from "proven on regtest" to "proven on a real public-policy network."
Regtest can't test the two things that actually decide whether BTX works in the wild:

1. **Carrier standardness / propagation** — will the on-chain order artifact actually relay and get
   mined under real relay policy?
2. **Real timing & fees** — the lifecycle under ~10-minute blocks and real fee estimation.

Signet gives both with throwaway coins. It does **not** test mainnet economics, liquidity, or
adversarial conditions — don't over-read a green run here.

> Status of this doc: a plan to execute, not yet run. Items marked **[verify]** depend on your
> Bitcoin Core version / current network state — check them on your machine before relying.

---

## Carrier standardness — the key fact (current as of 2026)

**Bitcoin Core v30 (released 2025-10-10) raised the default `OP_RETURN` (`-datacarriersize`) limit
from 83 bytes to ~100,000 bytes** and now relays multiple OP_RETURN outputs. BTX's BTX artifact is
~206 bytes, so:

- **On a v30+ node with default policy → the OP_RETURN carrier is standard and relays.** The old
  "206 B won't relay" problem is gone on current software.
- **It's a policy change, and contested** (the Core/Knots split). Knots and pre-v30 / restrictively
  configured nodes still reject >83-byte OP_RETURN, so propagation across the network isn't
  guaranteed — it depends on the node mix and, critically, on whether the miner that includes your
  tx accepts it.
- **Your local `/tmp/bitcoin-29.1` is pre-v30** → its default is 83 B, so it will reject the 206 B
  OP_RETURN locally unless you pass `-datacarriersize=240` (or upgrade to v30). **[verify]** v29.1's
  exact default.
- **The Taproot witness-envelope carrier** (`btx_taproot.py`) puts the artifact in *witness* data,
  which is not governed by `-datacarriersize` and is broadly standard — so it's the carrier least
  dependent on the OP_RETURN policy debate. Test both; the envelope is the robust fallback.

This validation should **test both carriers and observe which actually propagates and confirms** on
the chosen signet.

---

## Choose an environment

### Option A — custom signet (recommended for a controlled full-cycle test)
A signet you run yourself with your own challenge. You get **real default relay policy** *and* the
ability to **produce blocks on demand** (like regtest), and it starts essentially empty so indexing
is fast. The catch: the network magic differs from public signet and you must compute it.

- The signet block-message magic = first 4 bytes of `sha256d( <pushdata-prefix> || <challenge-script> )`.
  For a 36/37-byte challenge the prefix is the corresponding push opcode (e.g. `0x25` for 37 bytes).
  So `BRK_BLOCK_MAGIC` for your custom signet is **not** `0a03cf40` — derive it from your challenge.
  **[verify]** compute it once and confirm against your node's debug log / `getblockchaininfo`.
- Blocks are produced by Bitcoin Core's signet miner (`contrib/signet/miner`) using your signer key.
  **[verify]** exact invocation for v29.1.

### Option B — public signet (for real propagation realism)
The shared public signet (magic **`0a03cf40`**). Realistic propagation across many real nodes, but:
you **cannot mine your own blocks** (a fixed signer produces them ~every 10 min), you need coins from
a **signet faucet** **[verify it's live]**, and full sync is ~250k+ blocks (heavier than regtest).
Use this once the custom-signet cycle passes, to confirm real-world propagation.

---

## Custom-signet walk-through (Option A)

Shared vars (adjust paths; `$BRK` = the brk-btx clone):
```bash
SD=/tmp/sig-btx                      # signet datadir
BRKDIR=/tmp/brk-btx-signet
BIN=/tmp/bitcoin-29.1/bin               # or a v30 build for default OP_RETURN relay
BCLI="$BIN/bitcoin-cli -datadir=$SD"    # note: chain flag set via signet config below
```

1. **Create a challenge + config.** Make a wallet/key, derive a 1-of-1 signet challenge, and set it
   in `$SD/bitcoin.conf` (`signet=1`, `signetchallenge=<scriptHex>`, `datacarriersize=240` if pre-v30,
   `fallbackfee=0.0002`, `server=1`, `txindex=1`). **[verify]** the exact challenge-construction steps
   for your version (Bitcoin Core docs: "Custom Signet").
2. **Compute the magic** from the challenge (see above) and note it for `BRK_BLOCK_MAGIC`.
3. **Start `bitcoind -signet -datadir=$SD`**, create a wallet, and **mine initial blocks** with
   `contrib/signet/miner` to get spendable coins (coinbase maturity applies).
4. **Fund a P2WPKH offer UTXO**, then maker-sign and publish — reuse the proven tooling, just pointed
   at signet (it talks plain `bitcoin-cli`):
   ```bash
   cd "<Bitcoin Terminal Exchange folder>"
   python3 btx_wallet.py maker-sign --bitcoin-cli "$BIN/bitcoin-cli" --chain signet \
     --datadir $SD --wallet btx --offer-txid <txid> --offer-vout <n> --price-btc 0.5
   ```
5. **Publish via each carrier and observe relay:**
   - OP_RETURN: build/fund/sign/send the carrier tx; if `sendrawtransaction` errors with
     `scriptpubkey`/`datacarrier`, the node's policy rejected it (pre-v30 default, or Knots) → either
     raise `-datacarriersize`, use a v30 node, or fall back to the envelope.
   - Taproot envelope (`btx_taproot.py` / `btx_carrier.py`): expected to relay regardless.
   - **Mine a block** (custom signet) to confirm; record which carrier the *miner's* policy accepted.
6. **Run brk-btx against the signet:**
   ```bash
   cd "$BRK"
   BRK_BLOCK_MAGIC=<your-custom-magic> cargo run -p brk_cli -- \
     --brkdir $BRKDIR --blocksdir $SD/signet/blocks \
     --rpcconnect 127.0.0.1 --rpcport 38332 \
     --rpccookiefile $SD/signet/.cookie --brkport 3110
   ```
   (Public signet uses `BRK_BLOCK_MAGIC=0a03cf40` and the same `signet/` paths; RPC port 38332.)
7. **Serve + fill** exactly as in `btx_live_verify.sh`: `curl /api/v1/btx/orders` shows the OPEN
   order; `btx_wallet.py taker-fill --broadcast`; mine/await a block; re-query → order leaves the
   open book (FILLED). This proves the full lifecycle under real policy.

The existing guards already cover signet: the price-less distribution guard (brk_computer) and the
short-chain vecdb guard both apply, so brk_cli should run on a small custom signet the same way it
did on regtest.

---

## What a successful run establishes

- The order artifact **propagates and confirms under real relay policy** (and *which* carrier does).
- brk-btx **indexes a non-regtest chain** correctly (magic, blocks dir, RPC) and serves the book.
- The **full publish → serve → fill → FILLED lifecycle** holds off regtest.

## Open risks to watch

- **Propagation ≠ local acceptance.** Your node accepting the tx doesn't mean peers/miner will. On
  public signet, if the miner rejects the OP_RETURN, it never confirms — the envelope carrier or a
  v30-policy network is the answer.
- **Public-signet sync weight** (~250k blocks) and the lack of self-mining make Option B slow; prefer
  Option A for the controlled cycle.
- **Custom-signet magic** must be computed correctly or brk_reader sees zero blocks (the regtest
  symptom: "INDEXED_HEIGHT 0").
- Still **not** mainnet: no real economics, fees, or liquidity tested.

## Next after signet

If both carriers behave and the lifecycle holds on signet, the remaining real-world unknowns are
mainnet economics and the strategic questions (differentiator, monetization) already recorded in
`BTX-phase0-STATUS.md` — not engineering.
