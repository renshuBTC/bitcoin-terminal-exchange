# Changelog

All notable changes to Bitcoin Terminal Exchange are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/); this project is a research preview and versions are
not yet semver-stable. Commit hashes reference the `bitcoin-terminal-exchange` repo unless prefixed `brk-btx:`
(the companion BRK fork that does the on-chain indexing/serving).

## [B4 SHIPPED] — 2026-06-02 — first mainnet envelope broadcast

Closes the last open BLOCKER from `BTX-mainnet-readiness-2026-05-31.md`. A test-rune order
announce was broadcast via the witness-envelope carrier on Bitcoin mainnet on 2026-06-02 ~04:40
UTC and confirmed in block 952071 at 04:46:32 UTC (~6 minutes broadcast-to-confirmation).

- **Commit txid**: `199ac25126f363ecb0380a84419ad15399a57bb5ed8d7bd258212cb0a2ed633e`
- **Reveal txid**: `8acf6c70b2c1d75153374ab52f57b6da69ae7606a5931ba295d8cb5dd477f84c`
- **Block**: 952071 (`000000000000000000017f61a793597418f69b967626d48b1e3bca3d85c1e29f`)
- **Propagation observed by**: mempool.space, blockstream.info, bitaps.com (three independent
  third-party node operators, all confirmed same block)
- **Witness verification**: BTX1 magic `42545831` found at byte offset 38 of the reveal's
  witness[1] tapscript, with artifact head `425458310201007f969800010001...` (BTX1 v2,
  runestone-flag). The consensus layer accepted the script-path Taproot spend carrying the
  207-byte BTX artifact under default Bitcoin Core v30 mainnet relay policy.
- **Total mainnet cost**: 568 sats fees (165 commit + 403 reveal) + 5,460 commit dust returned
  as 5,057-sat reveal output. Net spent ≈ 971 sats.

The technical mainnet-readiness case is empirically closed. See `BTX-B4-mainnet-broadcast-runbook.md`
"Record of execution" for the full forensic record, and `BTX-post-B4-playbook.md` for what comes
next operationally. Commits `e6e33f0` (v30 `getbalances` preflight fix) and `41cd324` (B4 SHIPPED
doc updates) ship alongside this milestone.

## [0.2.19] — 2026-05-31 — bundle bumped to Bitcoin Core v30.2

Bumps the bundled `bitcoind` + `bitcoin-cli` from v29.1.0 to v30.2 (released 2026-01-10), the
first safe v30-series release after v30.0 and v30.1 were RECALLED by the Core devs for a
catastrophic wallet-deletion bug. (bitcoincore.org removed the v30.0/v30.1 binaries entirely;
don't bundle either.)

### What v30.2 changes in practice for BTX

- Default `-datacarriersize` is 100,000 bytes (was 83). BTX's ~208-byte OP_RETURN artifact now
  relays under v30 default policy with massive headroom, vs. being rejected under v29.1 default.
  The envelope carrier is unchanged (witness data, not subject to datacarriersize).
- Multiple OP_RETURN outputs per tx are admitted by default. BTX still emits one per envelope/
  publish tx, so no concrete change in our emit path.
- `btxd.h_order_create`'s envelope-on-mainnet default **stays** — operator-restricted nodes that
  set `-datacarriersize=83` to keep pre-v30 behavior (Knots-style configs) still need the witness
  path for cross-node relay guarantees.
- Supervisor's `-datacarriersize=240` flag stays as defensive intent (more restrictive than v30
  default, exactly fits BTX's 208-byte artifact + margin, protects against any future Core
  defaulting back down). No-op effectively on v30.2 but harmless.
- Cargo.toml / RPC API: no breaks. v30.2 release notes are wallet-migration + IPC fixes; no flag
  removals or RPC schema changes affect us. Brk_rpc uses `getblockcount`, `getblock`,
  `getblockheader`, `getblockhash`, `gettxout`, `getrawmempool`, `getrawtransaction`,
  `getblockchaininfo` — all stable across the v29→v30 boundary.

### What you need to do (WSL, on your Windows host)

Sandbox can't download the tarball + verify Core signing keys, so this is a host-side step.
**Verify the GPG signature** against the Bitcoin Core release signatures — never skip this.

```bash
# 1. Download v30.2 tarball + the signed SHA256SUMS
cd $HOME && mkdir -p bitcoin-30.2-stage && cd bitcoin-30.2-stage
curl -LO https://bitcoincore.org/bin/bitcoin-core-30.2/bitcoin-30.2-x86_64-linux-gnu.tar.gz
curl -LO https://bitcoincore.org/bin/bitcoin-core-30.2/SHA256SUMS
curl -LO https://bitcoincore.org/bin/bitcoin-core-30.2/SHA256SUMS.asc

# 2. (RECOMMENDED) Verify the GPG signature on SHA256SUMS. The canonical key-
#    acquisition flow lives at https://bitcoincore.org/en/download/ — follow
#    that page for the up-to-date trusted-key list rather than auto-importing
#    via third-party mirrors. If you already have the Core release keys from
#    a prior install, this step is just `gpg --verify SHA256SUMS.asc SHA256SUMS`.
#    The pragmatic minimum (TLS + SHA256 only, no GPG) is to skip step 2 and
#    rely on HTTPS to bitcoincore.org + the SHA256 check below — acceptable
#    for a research build, NOT acceptable before shipping to real users.

# 3. SHA256-verify the tarball against the published SHA256SUMS
grep 'bitcoin-30.2-x86_64-linux-gnu.tar.gz$' SHA256SUMS | sha256sum -c -   # MUST say "OK"

# 4. Extract into the path BTX's collect_linux_bins.sh expects
cd $HOME
tar -xzf bitcoin-30.2-stage/bitcoin-30.2-x86_64-linux-gnu.tar.gz
mv bitcoin-30.2 $HOME/bitcoin-30.2     # rename matches BTX_CORE_DIR default

# 5. Re-stage the BTX bundle binaries (this also rebuilds brk_cli + strips)
cd /mnt/c/Users/Ren\ Shu/Documents/Claude/Projects/bitcoin-terminal-exchange/app
bash scripts/collect_linux_bins.sh

# 6. Verify the new manifest
cat bin/linux/VERSIONS.txt   # bitcoind should now say "Bitcoin Core daemon version v30.2.0"
cat bin/linux/SHA256SUMS
```

Then `cargo tauri build` from `app/` to re-produce the NSIS installer with the v30.2 binaries
baked in. The supervisor is unchanged — no Rust rebuild required if you only swap the bundled
binaries — but a new installer is what ships v30.2 to users.

### Files touched in this commit

- `app/Cargo.toml`, `app/tauri.conf.json`: version `0.2.18` → `0.2.19`.
- `app/scripts/collect_linux_bins.sh`: `BTX_CORE_DIR` default `$HOME/bitcoin-29.1` →
  `$HOME/bitcoin-30.2`; comments updated; warning about v30.0/v30.1 recall added.
- `README.md`, `DEPENDENCIES.md`, `BTX-bundle-recipe.md`: bundled bitcoind version line updated to
  v30.2, with recall warning where the bundle composition is enumerated.
- `app/bin/linux/VERSIONS.txt` + `SHA256SUMS`: NOT updated here — they get regenerated when you
  run `collect_linux_bins.sh` against the new v30.2 install. The current contents reflect v29.1
  until you re-stage.
- Historical audit docs (`BTX-e2e-audit-results.md`, `BTX-end-to-end-audit-prompts.md`,
  `BTX-phase*.md`, `BTX-case-study.md`, etc.) intentionally left alone — they describe what was
  empirically proven against v29.1 and that history doesn't change. The v30 watchlist note above
  the e2e result matrix (added 2026-05-31) already explains how Prompt 10's frozen v29.1 snapshot
  maps onto v30 reality.

## [brk-btx 2026-05-31] — Indexer stale-tip auto-recovery (all chains)

Companion fix in the brk-btx indexer (`8a197f3` in brk-btx) extending v0.2.18's recovery story to
mainnet and signet — the chains that v0.2.18 explicitly couldn't help.

When bitcoind's dbcache rolls back below brk_indexer's last-indexed tip, the first
`getblockheader` inside `get_closest_valid_height` errors `-5 "Block not found"` and the indexer
process exits with no way to make progress short of a full state wipe. v0.2.18 caught this on the
*supervisor* side for regtest by detecting the error in the brk_cli log and `rm -rf`-ing the brk
state dir, but a full re-index from genesis on mainnet would take days, so signet/mainnet got the
"manual recovery" caveat.

The new fix lives inside `brk_indexer::index_` (brk-btx). Before calling `get_closest_valid_height`,
the indexer reconciles its stored tip against bitcoind by walking its OWN stored blockhash vec
backward — exponential backoff to find a recognized ancestor, then binary-search refinement to pin
down the most-recent recognized index so no progress is lost. Then it hands that hash to
`get_closest_valid_height` for the residual orphan→main-chain resolution. Typical small-divergence
cases (a few-block rollback) finish in a handful of RPCs; catastrophic full-divergence cases finish
in O(log N) and fall through to the same `full_reset` the existing length-inconsistency branch
already used.

`brk_rpc::Client::recognizes_block(&hash)` is the new helper that specifically translates RPC -5
into `Ok(false)` and propagates every other error as `Err` so transport/auth failures don't get
silently misclassified as chain divergence.

The v0.2.18 supervisor-side log-tail wipe stays as a belt-and-suspenders catch for the narrower
case where the indexer process is killed before its normal startup path runs at all (e.g. SIGKILLed
mid-handshake), and stays regtest-only so we never wipe mainnet/signet state from outside the
indexer. Comment narrowed in `app/src/supervisor.rs` to reflect the new layering.

**Build note:** the brk_indexer change needs a `cargo check -p brk_indexer -p brk_rpc` (and a
`cargo build --release -p brk_cli` if you want to re-bundle) from the Windows host — the sandbox
doesn't have cargo. CARGO_TARGET_DIR should still point at ext4 per the existing build memo.

## [docs 2026-05-31] — Bitcoin Core v30 OP_RETURN policy: BTX implications

Doc-only update resolving the [VERIFY] watchlist tag left in `btx_carrier.py` about 2026 carrier
standardness. Bitcoin Core v30 shipped 2025-10-10 with the default `datacarriersize` raised from 83
bytes to 100,000 bytes and multiple OP_RETURN outputs per tx allowed. For BTX (~208-byte v2
artifact):

- **OP_RETURN carrier** now relays under v30 default policy with massive headroom (was rejected
  under v29.1 default at 83 bytes). No code change — the artifact size hasn't moved.
- **Envelope carrier** (Taproot script-path witness, `btx_envelope_publish.py`) is unaffected; not
  subject to `datacarriersize` at all.
- **Envelope stays the mainnet default in `btxd.h_order_create`.** Operators can still set
  `-datacarriersize=83` to keep pre-v30 behavior (Knots-style configurations), so envelope is the
  policy-safest choice for cross-node relay guarantees. BTX no longer *needs* the relaxed
  datacarrier, but doesn't *depend* on v30 either.
- **E2E Prompt 10's PASS is now a frozen v29.1 snapshot.** Under v30 default, the same `OP_RETURN
  100B` probe would flip to `allowed=true`; the v29.1 boundary observation is still accurate for
  v29.1.
- **Bundled bitcoind is still v29.1.0.** Bumping the bundled Core to v30 is a candidate for v0.2.19
  and tracked separately.

Updated: `btx_carrier.py` doc-comment (removed [VERIFY]), `BTX-mainnet-hardening.md` §1
(replaced "recent Bitcoin Core has debated" parenthetical with v30 watchlist note),
`BTX-e2e-audit-results.md` (v30 watchlist note above the result matrix).

## [0.2.18] — 2026-05-31 — brk_cli stale-state auto-recovery (regtest)

A recurring developer-loop papercut: after the bundled regtest bitcoind crashes or restarts without
a clean shutdown, dbcache rollback can drop it to a height below brk_cli's indexed tip. On the next
brk_cli startup, its stored tip-hash is no longer in bitcoind's main chain, so
`client.get_closest_valid_height(stored_tip_hash)?` propagates bitcoind RPC error `-5 "Block not
found"` and brk_cli exits. The supervisor restarts it, same state, same crash — a hard loop that
required manual `rm -rf ~/.btx/brk-regtest` four times in the previous session before any further
work could proceed.

- **Pre-flight log-tail detection + recovery.** Mirroring v0.2.6's ord stale-redb-lock recovery,
  brk_cli's `wsl_command` now tails the last 50 lines of `/tmp/btx-brk_cli.log` before exec. If
  `'Block not found'` appears AND the chain is regtest, it `rm -rf $HOME/.btx/brk-{chain}` and lets
  the indexer rebuild from genesis (~seconds for a few hundred regtest blocks). The `tail -n 50`
  scope avoids false positives from incidental API 404 responses during normal operation — a
  startup crash leaves the error near the end of the previous log, but normal operation flushes
  subsequent output after any incidental query 404. Regtest-only by design: a full re-index from
  genesis on mainnet would take days, so signet/mainnet keep the manual-recovery path until a
  walk-back-through-stored-hashes fix lands inside `brk_indexer` itself. (supervisor.rs)

## [0.2.3 → 0.2.12] — 2026-05-30 — bundled-app polish, self-healing, E2E proof

A 10-commit run hardening the bundled Windows app (`app/`, Tauri shell + Rust supervisor) into a
working self-custodial DEX install. The trade rail is now provably executable end-to-end through the
GUI on regtest (etch → maker-sign → publish → book → fill → trades), the daemon stack is
self-healing across crashes/wedges, and chain state persists across closes. See
`BTX-bundled-app-e2e-runbook.md` for the reproducible walkthrough.

### Bundle / UX

- **CSS bundle fix.** `assets/btx.css` and `btx_order.html` were referenced by the
  book/trades/create/order pages but weren't being copied by `install_bundled_assets` — those four
  pages rendered as unstyled HTML with the nav concatenated into one blob. Added both to
  `bundle.resources` and the install script. Also switched the hardcoded brk_cli port from `3110`
  to the actual `3140` in book/trades/order pages. (`4b93c5c`, v0.2.3)
- **Wallet immature-balance metric.** The wallet stats row was only showing trusted +
  untrusted_pending, hiding the immature coinbase balance that `getbalances.mine.immature` reports.
  Added an Immature metric that auto-hides when 0 (so non-mining wallets stay clean) and shows the
  full amount when present — e.g. a regtest miner with 3675 BTC of maturing coinbases at block 202.
  (`ac6d5f5`, v0.2.4)

### Daemon supervisor

- **Graceful shutdown.** The original shutdown wiring listened to `WindowEvent::Destroyed`, which
  fires AFTER the OS window is already torn down — the supervisor's async `stop_all` then raced the
  Tauri process exit and bitcoind got SIGKILLed on the way out, losing its dbcache (up to 300MB of
  unflushed chain state). Reproduced this session: the regtest chain was wiped to genesis after every
  close. Switched to `WindowEvent::CloseRequested` + `api.prevent_close()`: intercept the close, run
  the full SIGTERM-then-wait chain on a dedicated tokio runtime in a worker thread, then explicitly
  call `window.destroy()` once every daemon has cleanly exited. Verified: bitcoind at block 202 with
  5100 BTC trusted + 3675 BTC immature → window-X close → all four daemons logged SIGTERM/stopped in
  reverse dep order → relaunch sees the same 202/5100/3675 state. (`a7863b5`, v0.2.5)
- **ord stale-lock auto-recovery.*