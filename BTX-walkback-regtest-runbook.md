# BTX brk_indexer walk-back — regtest exercise runbook

*Companion to the v0.2.18-19 audit. Goal: observe the `brk_indexer::find_recognized_ancestor`
recovery path firing on a real bundled-regtest BTX install, rather than relying solely on the
static walk-through in `BTX-v0.2.18-19-audit.md`.*

## What this test proves (and what it doesn't)

**Proves:** the walk-back code is reachable, runs against a real `bitcoind` RPC, finds a recognized
ancestor, hands off to `get_closest_valid_height`, and resumes indexing without losing the chain
prefix.

**Doesn't prove:** deterministic recovery against every possible bitcoind-divergence scenario.
The original organic failure (dbcache rollback after unclean shutdown — `reference_brk_build_env`
memory) is hard to reproduce on demand because it depends on bitcoind's flush timing. We use
`-reindex` as a deterministic substitute: it puts bitcoind into a state where it doesn't recognize
brk_cli's stored tip, which is the same condition the walk-back was designed to handle. The code
path is the same; only the trigger differs.

## Prerequisites

- Bundled BTX installed at `%LOCALAPPDATA%\BTX` (any version that has the walk-back — i.e.,
  shipping the `brk_cli` binary built from brk-btx commit `8a197f3` or later; the v0.2.19
  installer with the re-bundled brk_cli on this session's `cargo build` qualifies).
- WSL Ubuntu with `bitcoin-cli` v30.2 available at `$HOME/bitcoin-30.2/bin/` OR `$HOME/.btx/bin/`
  (the bundled copy).
- A scratch terminal to watch the brk_cli log.

## Step 0 — reset to a known state

```bash
# WSL — make sure nothing's running
pkill -9 -x bitcoind || true
pkill -9 -x brk_cli || true
pkill -9 -x ord     || true
pkill -9 -f btxd.py || true
sleep 1

# Optional: wipe and start clean so we have a deterministic chain. ONLY on regtest;
# never run this on signet/mainnet datadir.
rm -rf $HOME/.btx/data/regtest        # bitcoind regtest datadir
rm -rf $HOME/.btx/brk-regtest    # brk_cli regtest state
rm -rf $HOME/.btx/data/regtest/ord    # ord regtest index (under data/regtest in v0.2.18+)
rm -f  /tmp/btx-*.log
```

## Step 1 — bring up bundled regtest BTX and index some blocks

Launch the BTX app from Windows (Start menu or shortcut). Pick **regtest** in the first-launch
wizard if it offers; otherwise launch as normal and confirm the active chain by:

```bash
# WSL
$HOME/.btx/bin/bitcoin-cli -regtest -datadir=$HOME/.btx/data/regtest \
  -rpccookiefile=$HOME/.btx/data/regtest/regtest/.cookie getblockchaininfo \
  | jq -r .chain
# → "regtest"
```

Mine ~50 blocks so brk_cli has a non-trivial chain to walk back through:

```bash
ADDR=$($HOME/.btx/bin/bitcoin-cli -regtest -datadir=$HOME/.btx/data/regtest \
       -rpccookiefile=$HOME/.btx/data/regtest/regtest/.cookie getnewaddress)
$HOME/.btx/bin/bitcoin-cli -regtest -datadir=$HOME/.btx/data/regtest \
       -rpccookiefile=$HOME/.btx/data/regtest/regtest/.cookie generatetoaddress 50 "$ADDR"
sleep 5   # let brk_cli catch up
```

Confirm brk_cli is up to date:

```bash
curl -s http://127.0.0.1:3140/api/v1/btx/blocks/info | jq '.height'
# → 50  (or thereabouts)
```

**Checkpoint:** brk_cli now has an indexed tip ~ block 50. Note it: `BTX_TIP=50`.

## Step 2 — trigger the divergence: bitcoind `-reindex`

This is the deterministic substitute for an organic dbcache rollback. On `-reindex`, bitcoind
wipes its chainstate and re-reads block files from disk, so for several seconds it does NOT
recognize the tip brk_cli has stored.

Close the BTX app (or just kill `bitcoind` directly):

```bash
pkill -TERM -x bitcoind
# wait for clean shutdown
while pgrep -x bitcoind >/dev/null; do sleep 0.2; done
```

Restart bitcoind manually with `-reindex`:

```bash
$HOME/.btx/bin/bitcoind -regtest \
  -datadir=$HOME/.btx/data/regtest \
  -reindex \
  -datacarrier=1 -datacarriersize=240 \
  -fallbackfee=0.0002 -dbcache=300 -server -printtoconsole \
  > /tmp/btx-bitcoind.log 2>&1 &
```

**While bitcoind is still re-indexing** (chainstate not yet rebuilt), start brk_cli manually
with the bundled command-line. The supervisor would normally do this, but running it manually
ensures the v0.2.18 pre-flight wipe doesn't fire and mask the result:

```bash
BRK_BLOCK_MAGIC=fabfb5da \
$HOME/.btx/bin/brk_cli \
  --brkdir $HOME/.btx/brk-regtest \
  --blocksdir $HOME/.btx/data/regtest/regtest/blocks \
  --rpcconnect 127.0.0.1 --rpcport 18443 \
  --rpccookiefile $HOME/.btx/data/regtest/regtest/.cookie \
  --brkport 3140 \
  2>&1 | tee /tmp/btx-walkback-test.log
```

(BRK_BLOCK_MAGIC for regtest is `fabfb5da`; signet is `0a03cf40`, mainnet is `f9beb4d9`. The
supervisor passes the right value automatically — only matters here because we're invoking by hand.)

## Step 3 — observe the walk-back

Watch `/tmp/btx-walkback-test.log` for the recovery path. With default tracing level (no
`RUST_LOG`), the relevant lines you'll see at `info!` level:

- **No walk-back triggered (bitcoind already caught up):** `Up to date, nothing to index.` —
  the test missed the divergence window because reindex was too fast. Repeat with a larger
  block count (200+) or restart faster.
- **Walk-back fell through to reset (catastrophic case):** `Indexer tip and all stored ancestors
  unrecognized by bitcoind (dbcache rollback / chain divergence); resetting indexer...` followed
  by re-indexing from height 0. This means the walk-back DID enter the catastrophic path — also
  a valid outcome. brk_cli re-indexes fast on regtest.
- **Walk-back succeeded (the case we want):** brk_cli pauses for a few seconds, then `Starting
  indexing...` from a height > 0. No `resetting indexer` message. This is the success path —
  brk_indexer walked back from `BTX_TIP=50` to some recognized ancestor (probably the genesis
  block or wherever bitcoind has finished re-indexing), and resumed.

To see the walk-back step-by-step:

```bash
RUST_LOG=brk_indexer=debug,brk_rpc=debug \
$HOME/.btx/bin/brk_cli ... (same command as Step 2)
```

At `debug!` level you'll see `Get closest valid height...` for each `recognizes_block` call inside
the walk-back. Multiple such calls in a row, followed by `Starting lengths set.`, is the
fingerprint of `find_recognized_ancestor` doing exponential-backoff search.

## Step 4 — clean up

```bash
pkill -TERM -x brk_cli
pkill -TERM -x bitcoind
```

Restart the BTX app to resume normal operation.

## Step 5 — record the outcome

Record in this doc (or in a session memory) which branch fired:

- [ ] Up to date — no recovery exercised
- [ ] Catastrophic full_reset
- [ ] Walk-back succeeded (highest recognized index visible in debug logs)

The third outcome is the one that empirically validates the new path. The second is the
fallback path (which was the only available behavior before today's brk-btx commit `8a197f3`)
and is equally valid as a system-level outcome, just not what we're testing.

## Notes / known limitations

- **The two-layer composition.** The v0.2.18 supervisor pre-flight is regtest-only and fires on
  `"Block not found"` in the previous run's `/tmp/btx-brk_cli.log`. Because the walk-back
  consumes the -5 RPC error silently (verified: `brk_rpc::recognizes_block` has no
  `tracing::*!` call along the false path), a successful walk-back does NOT leave that string
  in the log, so the supervisor pre-flight doesn't over-trigger on the next restart. The two
  layers compose cleanly.
- **Why no unit test?** A proper unit test of `find_recognized_ancestor` would mock the `Client`
  type. `brk_rpc::Client` is currently a concrete struct, not a trait, so a mock requires either
  introducing a trait abstraction (intrusive refactor) or a test-only fake bitcoind. Both are
  larger work than this exercise; deferred. The exponential-backoff + binary-search invariants
  were walked through by hand across 7+ cases in `BTX-v0.2.18-19-audit.md` §F2-context.
- **What this exercise also implicitly tests:** that the v0.2.19 bundle's bundled `brk_cli`
  binary actually contains the walk-back code (i.e., the cargo build + manual cp from earlier
  this session landed correctly). If `find_recognized_ancestor` weren't present, you'd see the
  original "Block not found" → process exit pattern instead of any of the three outcomes above.
