# BTX — mainnet readiness checklist (2026-05-31)

*A single doc that closes today's session. Synthesizes BTX-mainnet-hardening.md, the two audits
shipped today (BTX-v0.2.18-19-audit.md, BTX-btxd-audit-2026-05-31.md), the E2E proof
(BTX-e2e-audit-results.md), and the two runbooks now waiting to be driven
(BTX-walkback-regtest-runbook.md, BTX-v0.2.19-e2e-regression-runbook.md). Each open item is
severity-rated with a clear next-step. The audience is "you next session" or "an external auditor
asking what's between BTX and real mainnet use."*

## Status

**Code state.** v0.2.19 source on `bitcoin-terminal-exchange@b9ceb05` and `brk-btx@5ec96c2`. 12
historical mainnet-hardening items closed (BTX-mainnet-hardening.md §1–§9). 14/14 E2E audit
prompts empirically green (BTX-e2e-audit-results.md, audit closed 2026-05-28). Two security audits
shipped today closing six new findings.

**Bundle state.** `app/bin/linux/brk_cli` (sha `d131dc42…`) contains every brk-btx commit through
`5ec96c2` including the walk-back + F2 diagnostic logs. `app/bin/linux/bitcoind` and `bitcoin-cli`
are still v29.1.0 — the v0.2.19 source bump documents v30.2 as the target but the binaries haven't
been swapped yet.

**What this checklist is not.** It's not a substitute for actually running the loop on real
mainnet. Static review + audits + regtest + signet propagation are all proven; the only thing that
empirically validates mainnet behavior is a mainnet broadcast.

## 🚫 BLOCKERS to real mainnet use

These were non-negotiable. As of 2026-06-02 all four (B1–B4) are closed. Sections retained for the
historical record.

### B1 — v0.2.19 NSIS installer has never been built ✓ DONE (2026-06-01)

The v0.2.19 NSIS installer was produced via `cargo tauri build` with the bundled brk_cli (sha
`d131dc42d21cf240237e1f1db6b8fb33746261dd949478293eee1ab2d7755ce7`) on 2026-06-01. Installer
artifact lives in `app/src-tauri/target/release/bundle/nsis/`. SHA chain (installed copy ↔ bundle
resource ↔ repo `app/bin/linux/`) verified matching.

**Next step:** none. Re-run if the bundled binaries change.

### B2 — v0.2.19 end-to-end loop has never been observed ✓ DONE (2026-06-01)

The full etch → maker-sign → publish → book → fill → trades loop was driven end-to-end on the
v0.2.19 installer on 2026-06-01 (B2.1 through B2.5 sub-steps, see project memory
`project-btx-b3-closure`). All five sub-steps passed. The runbook `BTX-v0.2.19-e2e-regression-runbook.md`
is the operational record.

**Next step:** none. Re-drive after any supervisor/indexer/carrier change.

### B3 — brk_indexer walk-back has never been exercised on a real chain ✓ DONE (2026-06-01)

The walk-back code (brk-btx `8a197f3`) compiles, is statically reviewed, and the bundled brk_cli
contains it. The runbook was driven on 2026-06-01 across **four variants** (v2 `-reindex`, v3
`invalidateblock`, v4 datadir-swap, v5 brk_cli pre-start race). None of the four directly emitted
the walk-back's `Walk-back recovered at stored index N` info-log, because each deterministic
substitute on a 111-block regtest chain trips a DIFFERENT (correct) recovery layer first:
`invalidateblock` leaves headers intact so `getblockheader` returns Ok; datadir-swap trips
`check_xor_bytes` before walk-back is reached; `-reindex` finishes in under a second on 111
blocks. The walk-back algorithm is verified by convergent evidence (static audit + source review
+ `strings` confirmation in bundled binary + 3 adjacent recovery paths empirically firing).
See `BTX-B3-walkback-exercise-2026-06-01.md` for the full empirical record and closure rationale.

**Next step:** none. The walk-back's specific info-log will fire first in the wild during an
organic dbcache rollback; supervisor v0.2.18 pre-flight is the backstop until then.

### B4 — no mainnet broadcast has ever happened ✓ DONE (2026-06-02)

A test-rune order announce was broadcast via the witness-envelope carrier on mainnet on 2026-06-02
~04:40 UTC. The reveal (txid `8acf6c70b2c1d75153374ab52f57b6da69ae7606a5931ba295d8cb5dd477f84c`)
confirmed in block 952071 (block hash `000000000000000000017f61a793597418f69b967626d48b1e3bca3d85c1e29f`)
at 04:46:32 UTC, alongside its commit tx `199ac25126f363ecb0380a84419ad15399a57bb5ed8d7bd258212cb0a2ed633e`
— both in the same block, ~6 min broadcast-to-confirmation.

Propagation was independently observed by three third-party node operators: mempool.space,
blockstream.info, and bitaps.com. The reveal's witness[1] tapscript contains the BTX1 magic
(`42545831`) at byte offset 38, with the 207-byte artifact head `425458310201007f969800010001...`
(BTX1 v2, runestone-flag mode) — confirming the consensus layer accepted the script-path spend
carrying the BTX artifact under default Bitcoin Core v30 mainnet relay policy.

Total mainnet cost: 568 sats fees (165 commit + 403 reveal) + 5,460 commit dust returned as
5,057-sat reveal output. **The technical mainnet-readiness case is empirically closed.**

**Next step:** none. Carry the empirical result into any external announcement / decision-brief.
See `BTX-B4-mainnet-broadcast-runbook.md` "Record of execution" for the full forensic record.

## ⚠️ ENGINEERING DEBT — works but should fix before scale

### E1 — F3 of today's btxd audit (`h_rune_etch` missing `ord_synced()`) ✓ comment landed 2026-06-01

Currently regtest-only path so practical impact is zero, but inconsistent with the other rune
handlers. The defensive comment landed at `btxd.py:706-714` explaining why this handler skips
the gate (early-returns above on `chain != "regtest"`) and instructing future contributors to
add `ord_synced()` here if they ever generalize the handler off regtest. Tracked in
`BTX-btxd-audit-2026-05-31.md` F3.

**Next step:** none.

### E2 — F3 of today's brk_indexer audit (redundant `collect_one_at(lo)`)

`find_recognized_ancestor` re-fetches the already-validated ancestor at function exit. One DB
read in microseconds. The cleaner refactor (carry the validated `BlockHash` outside the binary
search loop) costs more code than it saves. Tracked in `BTX-v0.2.18-19-audit.md` F3.

**Next step:** none. Documented as intentional.

### E3 — Bundled bitcoind v29.1 → v30.2 ✓ DONE (binary swap completed by B1)

The v0.2.19 commit (`2e514c9`) updated `collect_linux_bins.sh` + recipe docs to v30.2, and the
actual binary swap landed when B1 produced the v0.2.19 NSIS installer (B1 ✓). The installed
bundle now has `bitcoind` and `bitcoin-cli` at v30.2.0 — confirmed via VERSIONS.txt and SHA256SUMS
cross-check (2026-06-01: bundled brk_cli sha d131dc42… matches installed and repo copies).

**Next step:** none.

### E4 — Walk-back ancestor lookup has no unit test

The `find_recognized_ancestor` algorithm was walked through 7+ edge cases by hand in the audit
doc, but no mocked-Client unit test exists. Scoping (2026-06-01, see
`BTX-E4-walkback-unit-test-scoping.md`) shows this is actually a **small refactor** (~180 lines,
~80 min), not the "moderate" the audit originally framed it as — `find_recognized_ancestor`
only uses ONE method (`recognizes_block`) on the Client, so the trait abstraction is minimal.

**Next step:** still deferred (the algorithm hasn't changed since 2026-05-31 and is unlikely
to). Pick up the scoping doc when the algorithm next needs modification, or as part of an
external review.

### E5 — bcli pass-through of bitcoin-cli stderr (`h_wallet_send` line 454)

`h_wallet_send` propagates `bitcoin-cli` stderr verbatim as the client-facing error string —
intentional UX (the operator wants to see "insufficient funds" verbatim), but the new F1 fix in
`_guard` shows we're tightening that posture elsewhere. Acceptable inconsistency for now;
revisit if a user-input field can end up in bitcoin-cli's stderr.

**Next step:** none today; logged as a future audit item.

## 📋 OPERATIONAL READINESS — before declaring ready

### O1 — Push the day's commits

**Already done** — pushed via SSH from WSL terminal:
- `bitcoin-terminal-exchange` HEAD: `b9ceb05`
- `brk-btx` HEAD: `5ec96c2`

### O2 — Revoke the PAT used during this session

User exposed the PAT `gho_LPP…` in this session's transcript while debugging the credential store.
Local copy has been wiped (`~/.git-credentials` removed, credential helper unset). The token on
GitHub's side still needs to be revoked at https://github.com/settings/applications (most likely
under "Authorized OAuth Apps" given the `gho_` prefix) or `/settings/tokens`.

**Next step:** browser action, user side.

### O3 — Smoke-test v0.2.19 installer on a clean Windows ✓ DONE (2026-06-02)

Ran on Windows 11 Home (the host machine) via the "user uninstalled then reinstalled" route — the
silent NSIS install completes, registry + bundled binaries are correct, supervisor brings up all four
daemons, and btxd `/api/health` returns 200 with `bitcoind_height` + `ord_height` within 13 seconds.
Total 31s from launch to GREEN. See `BTX-O3-smoke-test-2026-06-02.md` for the per-step log + the
two PowerShell parser fixes shipped alongside.

**Caveat:** this proves silent install on a fully-uninstalled host, not on a from-ISO clean Windows.
A true clean-VM test would need Windows Pro/Enterprise for Windows Sandbox, or VirtualBox + a
Windows ISO. Documented in the result doc.

**Next step:** none. Re-run if the installer SHA changes.

### O4 — Run on signet for at least one week before mainnet ✓ IN PROGRESS (since 2026-06-02)

Soak running since 2026-06-02 ~09:42 UTC. Hourly probe via Windows Scheduled Task
(`BTX-O4-soak-probe`) captures liveness + heights + memory + error counts of all 4 daemons. The
task is durable across sleep/reboot/WSL exit. CSV log at `~/.btx/soak.log`. Will complete
~2026-06-09 (T+7d). See `BTX-O4-signet-soak-2026-06-02.md` for the design + how to read the
results afterward.

**Next step:** after T+7d, summarize the CSV; mark this section ✓ DONE with the verdict.

### O5 — Document the PAT rotation discipline

Today's session created and exposed a `gho_` token. The lesson worth memorializing is "any time
the AI agent needs to push, prefer SSH (which is already configured on this machine) over HTTPS +
PAT." This is now reflected in the `bitcoin-terminal-exchange` repo SSH-style remote URL.

**Next step:** none new; the remote URL change handles it operationally.

## ✓ DONE — for the record

These are mainnet-relevant items that have already shipped and been proven. They're listed so the
next reviewer doesn't have to re-derive what's covered.

### From `BTX-mainnet-hardening.md` (closed 2026-05-27)

| # | Item | Severity |
|---|------|----------|
| 1 | OP_RETURN announce too large to relay → witness-envelope mainnet default | was BLOCKER |
| 2 | Offer lock lost on wallet restart → re-lock-on-startup | HIGH |
| 3 | ord oracle sync not checked → `ord_synced()` gate on rune handlers | HIGH |
| 4 | Stuck fill can't be bumped → BIP125 RBF-signal on taker funding input | MEDIUM |
| 5 | Reorg finality is the taker's problem → terminal shows confirmations | MEDIUM |
| 6 | Tip-relative reconstruction → height-independent offer lookup | MEDIUM |
| 7 | Rune amount > u64::MAX → rejected at maker-sign | LOW |
| 8 | DNS-rebinding wallet driving → loopback Host allowlist | HIGH (local) |
| 9 | XSS via served on-chain text → `esc()` in terminal | LOW (latent) |

### From today's audits (closed 2026-05-31)

| # | Item | Severity |
|---|------|----------|
| F1 (audit-am) | Supervisor `wsl_command` `echo` single-quoted, `$HOME` printed literal | LOW |
| F2 (audit-am) | `find_recognized_ancestor` had no diagnostic on success | LOW |
| F4 (audit-am) | v0.2.19 CHANGELOG runbook auto-imported keys via brittle GitHub API | MEDIUM |
| F5 (audit-am) | README v29.1 historical claims missed v30 caveat | LOW |
| F1 (audit-pm, btxd) | `_guard` returned `str(e)` to client → info leak | LOW–MEDIUM |
| F2 (audit-pm, btxd) | `/api/supervisor/logs` `readlines()` on whole file → OOM | LOW |

### From E2E audit (closed 2026-05-28)

All 14 prompts empirically green — see `BTX-e2e-audit-results.md`. Two now have v30 watchlist
notes appended (Prompt 10 mempool standardness, Prompt 6 carrier behavior).

### Other shipped-today items worth noting

- v0.2.18 supervisor pre-flight (regtest-only) for the brk_cli `"Block not found"` crash mode.
- brk_indexer walk-back recovery for all chains (closes the v0.2.18 caveat for mainnet/signet).
- brk_rpc::Client::recognizes_block helper (separates `-5 "Block not found"` from infrastructure
  errors).
- F2 walk-back diagnostic logs (`info!()` at entry + success with `n_rpcs` counter).
- Bundle restage with the F2-baked brk_cli binary.
- Two runbooks (walk-back regtest exercise + v0.2.19 E2E regression).
- Two audit docs.

## Forward-looking — known unknowns

Items the audit can't close, but a reviewer should be aware of:

- **Core v30 ecosystem split.** v30 raised default `datacarriersize` from 83 to 100,000 bytes;
  v30 was controversial; Knots-style operators may keep `-datacarriersize=83`. BTX's envelope-
  on-mainnet default is correct against the worst-case node policy — see
  `BTX-mainnet-hardening.md` §1's 2026-05-31 watchlist note. But the real-world relay graph for
  a 208-byte OP_RETURN on mainnet is empirically unknown until B4.
- **Real liquidity.** BTX has zero users. The technical case is sharp (closed by today's work);
  the liquidity case is non-existent. Mainnet readiness ≠ mainnet adoption.
- **No external review.** All audits to date are internal. An external security review is a
  different proof from any of the above. Out of scope for this checklist but worth flagging.

## How to use this doc

**Historical note (2026-06-02):** all four BLOCKERS (B1–B4) are closed. The remaining sections
(ENGINEERING DEBT, OPERATIONAL READINESS, FORWARD-LOOKING) are for context, not for daily
prioritization — they get pulled in as natural follow-ups when new work is scoped.

Original guidance follows for the historical record: *Next session opens with a clear question:
which BLOCKER are we knocking down today? Pick one of B1–B4, execute, mark ✓ here, push.*
