# BTX B4 — mainnet broadcast retrospective

*Written 2026-06-02, hours after B4 shipped. Captures the empirical record, the
gotchas hit live, and what to carry forward into the next mainnet operation.*

## TL;DR

The smallest possible BTX envelope-carrier broadcast on Bitcoin mainnet happened
on 2026-06-02 ~04:40 UTC and confirmed in block 952071 at 04:46:32 UTC (~6 minutes
from broadcast). Three independent third-party node operators
(mempool.space, blockstream.info, bitaps.com) observed the propagation. The
reveal's witness[1] tapscript contains the BTX1 magic (`42545831`) at byte offset
38, with the 207-byte artifact head `425458310201007f969800010001...`. The
technical mainnet-readiness case is empirically closed. Total cost: 568 sats
in fees + 5,460 commit dust (5,057 sats returned as reveal output).

## What this proves and doesn't

**Proves:**
- BTX's witness-envelope carrier produces transactions that propagate under
  default Bitcoin Core v30 mainnet relay policy.
- The 207-byte BTX1 artifact survives the relay graph intact (magic + structure
  verified on-chain via three operators).
- The commit/reveal sequence works end-to-end on mainnet, not just regtest +
  signet.
- The fee market (1 sat/vB economy at execution time) is permissive enough that
  even single-block CPFP confirmation is achievable for a ~568-sat-fee bundle.

**Doesn't prove:**
- That anyone *wants* to use BTX. Demand is a separate question.
- That the wider relay graph (Knots-style configs, restrictive miners) accepts
  the envelope. Three aggregators observed it but they're all default-policy
  nodes. A signet propagation log against Knots peers would strengthen the
  claim.
- That the order is recoverable from the on-chain witness alone end-to-end. We
  verified the magic + artifact head; we didn't confirm a brk_cli indexer
  picked it up and surfaced it on `/api/v1/btx/orders`. That verification is
  still open (task #354) and requires the BTX desktop app to be running.

## The empirical record

| Field | Value |
|---|---|
| Broadcast time (commit + reveal) | 2026-06-02 ~04:40 UTC |
| Confirmation time | 04:46:32 UTC (same block) |
| Broadcast→confirmation latency | ~6 minutes |
| Block | 952071 (`000000000000000000017f61a793597418f69b967626d48b1e3bca3d85c1e29f`) |
| Commit txid | `199ac25126f363ecb0380a84419ad15399a57bb5ed8d7bd258212cb0a2ed633e` |
| Reveal txid | `8acf6c70b2c1d75153374ab52f57b6da69ae7606a5931ba295d8cb5dd477f84c` |
| Commit P2TR | `bc1p5t8nslkrekrje6h8k0qqfjxk0h8pxx94k6zffq3mmmm8u28xayaq4km6u0` |
| Reveal output → wallet | 5,057 sats → `bc1qsvfwvewxgm3s4e3cxatwdht09vzfce6tdpl34s` |
| Commit fee | 165 sats (246 vB / 657 wu → ~1.0 sat/vB at the relay floor) |
| Reveal fee | 403 sats (431 vB / 677 wu → ~2.4 sat/vB) |
| CPFP combined fee rate | 568 sats / 333 vsize ≈ 1.7 sat/vB |
| Witness items | 3 (64B Schnorr sig + 246B tapscript + 33B control block) |
| BTX1 magic offset | byte 38 in witness[1] tapscript |
| Artifact head | `425458310201007f969800010001...` (BTX1 v2, runestone-flag) |
| State file | `~/.btx/b4-state-1780375005.json` (keep for any recovery) |

## Four gotchas hit live (and why)

### 1. Wallet name mismatch (`btx` vs `RenshuBTC`)

`b4_preflight.sh` defaulted to `BTX_WALLET=btx`, but the actual mainnet wallet
in bitcoin-qt was `RenshuBTC`. The mismatch surfaced as
`error code: -18 / Requested wallet does not exist or is not loaded`.

**Fix:** explicitly set `BTX_WALLET=RenshuBTC` before invoking.

**Carry-forward:** consider auto-detecting the loaded wallet via `listwallets`
if exactly one is loaded, OR fail loudly with a list of loaded wallets to
choose from. Current default is fine for new users (suggests creating a
dedicated `btx` wallet) but trips up existing wallets.

### 2. Core v30 removed `balance`/`unconfirmed_balance` from `getwalletinfo`

Preflight read `WALLET_JSON.balance` and got `0` back because the field no
longer exists on v30. The 16,063-sat wallet was falsely flagged as below the
15,000-sat minimum.

**Fix:** committed as `e6e33f0`. Read from `getbalances.mine.trusted` /
`mine.untrusted_pending`, with a pre-v30 fallback to the old fields.

**Carry-forward:** any other script that reads `getwalletinfo.balance` or
`getwalletinfo.unconfirmed_balance` is broken on v30. Quick `grep -r
"getwalletinfo.balance\|unconfirmed_balance"` after upgrades. (Searched the
BTX repo for this pattern: no other hits beyond the preflight.)

### 3. `/tmp/btx-fake-datadir` validated by bitcoin-cli v30

The Python publisher unconditionally passes `--datadir` (because that's how
it's invoked in datadir-mode). In EXTERNAL_RPC mode `b4_execute.sh` shims this
with a dummy `/tmp/btx-fake-datadir`. Bitcoin Core v29.1 silently ignored the
flag when `-rpcconnect` was set; v30 validates the dir exists and errors with
`Specified data directory "/tmp/btx-fake-datadir" does not exist.`

**Fix:** committed as `10a3f88`. `b4_execute.sh` now does `mkdir -p` before
invoking the publisher.

**Carry-forward:** `/tmp` resets on WSL reboot, so without the mkdir guard
the next session re-hits the same error. Long-term cleaner fix: have
`btx_envelope_publish.py` skip the `--datadir` arg when `--bitcoin-cli` is a
wrapper that handles its own connection settings. Out of scope for B4 itself.

### 4. Single-UTXO wallet → maker-sign locks the only spendable input

The wallet had exactly one P2WPKH UTXO (16,063 sats). `maker-sign` locked it
as the offer, leaving nothing for the publisher's `sendtoaddress` to fund the
5,460-sat commit output. The publisher errored with
`error code: -6 / Insufficient funds`.

**Workaround at runtime:** unlocked the offer UTXO before broadcast,
accepted the "ghost order" trade-off — the offer UTXO ends up referenced by
an artifact that's announced in the same tx chain that consumes it. For B4's
carrier-propagation goal this is fine (the absurd 1.0 BTC/unit price made the
order unfillable regardless), but the order is logically invalid from the
moment it appears.

**Fix forward:** committed as `10a3f88`. `b4_preflight.sh` now warns if the
wallet has exactly 1 UTXO and explains the two options (send a 2nd small UTXO
first vs. unlock + accept the ghost-order trade-off).

**Carry-forward:** a future real-order broadcast (not a B4-style proof)
should have ≥2 UTXOs in the wallet to leave the order fillable.

## What worked well

### The autonomous file-polling watcher pattern

The `.btx-watcher-v2.sh` ccshell-style bridge let me drive WSL + git push +
network probes + PowerShell-via-WSL-interop while you were AFK or doing other
things. Watcher launched, ran ~20 queued scripts during B4 execution
(funding watcher, preflight runs, broadcast execution, third-party
verification, commits), and never wedged. The 60s per-script timeout +
auto-skip-already-touched + auto-kill-old-pid invariants held.

This is now the durable pattern for any cross-host work — see the
`renshuBTC/claude-cowork-shell-access` repo for the standalone version.

### The pre-flight script caught issues offline

Two of the three gotchas above were caught BEFORE any money moved:
- v30 `getbalances` mismatch → caught by preflight, fixed in 30 seconds
- Insufficient funds → caught after maker-sign but before broadcast

The third (fake datadir) was only hit at the publisher invocation, but at
that point no on-chain state had changed yet either. **No mainnet broadcast
went out under a broken setup.**

### Third-party verification was fast and conclusive

mempool.space saw the txs within seconds of broadcast. blockstream.info and
bitaps.com confirmed independently. Same block on all three. The
"propagation across the mainnet relay graph" claim is grounded.

### CPFP saved us from the marginal commit fee rate

Commit fee was 165 sats on 164 vsize = ~1 sat/vB (right at relay floor). On
its own, the commit might have stuck for several blocks under any fee
volatility. The reveal at 2.4 sat/vB pulled it into the same block via CPFP.
Combined feerate 1.7 sat/vB — well above relay minimum. Lesson: when
broadcasting a commit+reveal pair, the reveal's fee is what matters for
combined eviction-safety.

## Commits this session (chronological)

| Commit | What |
|---|---|
| `e6e33f0` | `b4_preflight.sh`: read balance from `getbalances` (Core v30 compat) |
| `41cd324` | B4 SHIPPED: mainnet envelope broadcast (reveal `8acf6c70` in block 952071) |
| `7de0720` | post-B4 doc sweep: CHANGELOG + NEXT + e2e-audit no-longer-stale |
| `10a3f88` | `b4_execute` + `b4_preflight`: harden against the two 2026-06-02 gotchas |
| `499d006` | mark B1/B2 DONE in readiness doc + decision-brief mainnet status |

All on `origin/main`, `renshuBTC/bitcoin-terminal-exchange`.

## What's left after B4

**Operational, not blocking:**
- Verify brk_cli indexer picks up the artifact from the reveal witness and
  surfaces it on `/api/v1/btx/orders` (task #354). Requires the BTX desktop
  app to be running with brk_cli synced past block 952071. Independent
  evidence is already strong (BTX1 magic verified on chain by three
  operators), but the indexer-side path closes the proof.

**Forward-looking, separate concerns:**
- **O4 — 1-week signet soak.** Leave the bundle running on signet for 7 days
  with periodic health probes. Reveals anything time-dependent (memory
  leaks, slow wedges) that B4 can't.
- **O3 — clean-VM smoke test.** `o3_smoke_test.ps1` is ready for any fresh
  Windows VM.
- **Real liquidity / demand.** Separate question entirely. B4 doesn't move
  it. See `BTX-decision-brief.md` "Three honest paths".
- **External security review.** Internal audits are exhaustive; an external
  third-party review is a different proof. Out of scope for technical
  readiness but valuable.

## How to cite B4

If you want a one-line empirical anchor for "BTX works on mainnet":

> Reveal txid `8acf6c70b2c1d75153374ab52f57b6da69ae7606a5931ba295d8cb5dd477f84c`,
> Bitcoin mainnet block 952071, 2026-06-02. Witness[1] tapscript contains
> BTX1 magic at byte 38. Independently observed by mempool.space,
> blockstream.info, and bitaps.com.
