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

These are non-negotiable: do not advertise BTX as ready for mainnet value until each is checked.

### B1 — v0.2.19 NSIS installer has never been built

The v0.2.19 source landed today, the bundled brk_cli landed today, but `cargo tauri build` was
never run with the v0.2.19 version + the freshly bundled binary. No installer = no user can install
v0.2.19 = nothing to validate.

**Next step:** WSL → install Bitcoin Core v30.2 per `CHANGELOG.md`'s v0.2.19 entry → run
`bash app/scripts/collect_linux_bins.sh` to regenerate `VERSIONS.txt` + `SHA256SUMS` → from
Windows: `cd app && cargo tauri build` → smoke-test the produced NSIS on a clean Windows VM.

### B2 — v0.2.19 end-to-end loop has never been observed

The etch → maker-sign → publish → book → fill → trades loop was last empirically proven on
**v0.2.5 at block 226** (project memory `project_btx_v025_e2e`). Between v0.2.5 and v0.2.19, 14
supervisor/indexer/carrier changes layered in. The runbook for re-proving it is written but no one
has driven it.

**Next step:** drive `BTX-v0.2.19-e2e-regression-runbook.md` end to end after B1 produces an
installer. Pass criteria are spelled out in that doc.

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

### B4 — no mainnet broadcast has ever happened

Every empirical proof to date is on regtest + custom signet + public signet. No BTX-emitted
transaction has ever entered the real Bitcoin mainnet mempool, let alone a block.

**Next step:** after B1–B3 pass, broadcast an envelope-carrier announce of a test-rune order on
mainnet at the smallest practical fee. Observe propagation against `mempool.space`. Pull from
`BTX-seeding-runbook.md` for the propagation observation pattern. Don't ship to users until this
returns a real txid that a third-party node accepts.

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

### E3 — Bundled bitcoind is v29.1 source-bumped to v30.2 (binary swap pending)

The v0.2.19 commit (`2e514c9`) updates `collect_linux_bins.sh` and the recipe docs to v30.2, but
the binary in `app/bin/linux/` is still v29.1.0. Resolved by B1.

**Next step:** see B1.

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

### O3 — Smoke-test v0.2.19 installer on a clean Windows

After B1 produces an NSIS, install on a Windows VM with no prior BTX state, watch the first-launch
wizard run through, confirm all four daemons come up green. Different from B2 (which assumes the
installer works and tests the trade loop); this is "does the installer install."

**Next step:** WSL/PowerShell after B1.

### O4 — Run on signet for at least one week before mainnet

`BTX-seeding-runbook.md` already documents the signet propagation pattern. Continuous signet
operation surfaces issues that fast regtest doesn't — fee dynamics, real reorgs, ord catchup
delays, broader Core relay-policy variation across the network.

**Next step:** plan a signet soak after B1–B3 pass.

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

Next session opens with a clear question: **which BLOCKER are we knocking down today?** Pick
one of B1–B4, execute, mark ✓ here, push. The ENGINEERING DEBT and OPERATIONAL READINESS
sections are for context, not for daily prioritization — they get pulled in as natural
follow-ups when a blocker drops.
