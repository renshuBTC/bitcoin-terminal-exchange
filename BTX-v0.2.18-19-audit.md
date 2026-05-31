# BTX v0.2.18 / v0.2.19 adversarial audit

*Companion to `BTX-v0.2.x-audit.md` (2026-05-30). Same methodology: re-read every commit shipped
today as a hostile reviewer, hunt for off-by-one / panic surface / shell-escape / doc drift,
document findings with severity, ship the fixes that matter and explicitly defer the ones that
don't.*

Scope: today's 5 commits across two repos.

| Repo | Commit | Title |
|------|--------|-------|
| bitcoin-terminal-exchange | `e01e641` | v0.2.18: brk_cli stale-state auto-recovery on regtest |
| bitcoin-terminal-exchange | `1e15ce5` | docs: Core v30 OP_RETURN policy implications for BTX |
| bitcoin-terminal-exchange | `c72bc73` | docs+supervisor: narrow v0.2.18 scope after brk_indexer walk-back ships |
| bitcoin-terminal-exchange | `2e514c9` | v0.2.19: bundle Bitcoin Core v30.2 |
| brk-btx | `8a197f3` + `2840e71` | brk_indexer: walk-back recovery for stale tip vs bitcoind (+ AnyVec import fix) |

## Findings

| # | Severity | Area | Finding | Status |
|---|----------|------|---------|--------|
| F1 | LOW | shell quoting | `app/src/supervisor.rs` v0.2.18 recovery `echo` uses single quotes, so `$HOME` does not expand in the user-visible log line | **fixed** in v0.2.18-audit follow-up below |
| F2 | LOW | diagnostics | `brk_indexer::find_recognized_ancestor` emits no log on success — if walk-back runs for 30s nobody sees why | **fixed** in brk-btx `5ec96c2` (entry log when tip is not recognized + success log with recovered index and `n_rpcs` count) |
| F3 | nano | efficiency | Final `Ok(blockhash.collect_one_at(lo))` in `find_recognized_ancestor` re-fetches a hash already validated during binary search | deferred — single DB read, microseconds |
| F4 | MEDIUM | runbook reliability | v0.2.19 CHANGELOG runbook auto-imports Bitcoin Core release keys via the GitHub API parsed with `grep`/`cut`; brittle (rate-limit, schema drift) and security-sensitive (key acquisition path) | **fixed** in v0.2.19-audit follow-up below |
| F5 | LOW | narrative consistency | `README.md` historical "v29.1" claims are accurate-as-of-audit but read as stale next to the new "bundle ships v30.2" line; an inline caveat similar to the one added to `BTX-e2e-audit-results.md` keeps both the historical truth and the current state visible | **fixed** in v0.2.19-audit follow-up below |

## F1 — Single-quoted echo prevents `$HOME` expansion (LOW)

**Where.** `app/src/supervisor.rs`, the v0.2.18 brk_cli `wsl_command`:

```
echo '[brk_cli-recover] stale brk state vs bitcoind (dbcache rollback); wiping {brk_dir}';
rm -rf {brk_dir};
```

`{brk_dir}` is interpolated by Rust's `format!()` at compile time. After substitution:

```bash
echo '[brk_cli-recover] stale brk state vs bitcoind (dbcache rollback); wiping $HOME/.btx/brk-regtest';
rm -rf $HOME/.btx/brk-regtest;
```

The `rm -rf` is outside any quotes, so `$HOME` expands and the wipe works correctly (verified empirically across the 7-case shell test in v0.2.18). The `echo`, however, is inside single quotes — `$HOME` does **not** expand, so the user-visible log line reads `wiping $HOME/.btx/brk-regtest` literal, not the resolved path. Cosmetic; no behavioral impact, but confusing when debugging.

**Fix.** Switch the surrounding `'...'` to `"..."`. Parentheses, brackets, and semicolons inside the message are not special inside double quotes, so no other escaping needed.

**Verification approach.** A pre-vs-post `bash -c` of the rendered shell, with `$HOME` set to a fixed value, comparing the echoed line.

## F2 — Walk-back emits no diagnostic on success (LOW, fixed)

**Status update 2026-05-31, post-runbook:** the regtest exercise runbook
(`BTX-walkback-regtest-runbook.md`) made it concrete that operators driving the test would need
log breadcrumbs to know which of three outcomes fired. Shipped two `info!()` calls in brk-btx
`5ec96c2` along with an `n_rpcs: usize` counter so the success log reports the recovery cost.
Original deferral text retained below for context.



**Where.** `brk_indexer::find_recognized_ancestor` (brk-btx `8a197f3`).

The function silently walks the stored blockhash vec via exponential backoff + binary refine. On the catastrophic path (no ancestor recognized) the caller logs `"Indexer tip and all stored ancestors unrecognized by bitcoind ...; resetting indexer..."`. On the success path (walk-back finds a recognized ancestor) nothing is logged — the operator sees brk_cli pause silently for 5-30 seconds, then resume indexing, with no breadcrumb tying the pause to a recovery event.

**Suggested fix (deferred).** Add an `info!()` at the function entry when the tip is not recognized, and a second `info!()` at success with the recovered index and the number of RPCs used. Cheap; improves operator UX. Deferred because it doesn't affect correctness and brk_cli already has reasonable logging in the surrounding flow.

## F3 — Redundant final `collect_one_at` (nano, deferred)

**Where.** `brk_indexer::find_recognized_ancestor`, final line:

```rust
Ok(blockhash.collect_one_at(lo))
```

By the time we reach this line, `lo` has been validated by an earlier `collect_one_at(lo)` returning `Some` plus `recognizes_block` returning `true` (either in the exponential phase or inside the binary-search loop). The final fetch is redundant.

**Why deferred.** One DB read, microseconds. The cleaner refactor (carry the validated `BlockHash` outside the loop) costs more code than it saves runtime. The current code is correct and obvious; not worth churn.

## F4 — Brittle GPG-key auto-import in v0.2.19 runbook (MEDIUM)

**Where.** `CHANGELOG.md`, v0.2.19 entry, step 2 of "What you need to do":

```bash
curl -sSL https://api.github.com/repos/bitcoin-core/guix.sigs/contents/builder-keys \
  | grep download_url | cut -d'"' -f4 | xargs -I{} curl -sL {} | gpg --import -
```

Problems:
- **GitHub API rate-limits.** Unauthenticated requests get 60/hour; if the user hits the limit during setup the import silently produces no keys and `gpg --verify` fails with no clear cause.
- **Schema parsing with `grep`/`cut`.** The GitHub API JSON format is stable, but a parse pipeline relying on a literal `download_url` substring and double-quote splitting is fragile to whitespace, ordering, or additional fields.
- **Security model.** This pattern teaches a user to import *every* key in a third-party directory under the assumption that the directory is trustworthy. That trust assumption is OK for `bitcoin-core/guix.sigs`, but the runbook doesn't articulate it — someone copying this pattern to a different repo could import attacker-controlled keys.

**Fix.** Two options, neither perfect:

1. **Drop GPG, lean on HTTPS + SHA256SUMS only** — `bitcoincore.org` is HTTPS-served with a long-lived TLS cert, and the SHA256SUMS file pins every binary. This is what a casual user does in practice. Skip the `SHA256SUMS.asc` step entirely.
2. **Point at the canonical Bitcoin Core download guide** — `https://bitcoincore.org/en/download/` has the up-to-date key-acquisition instructions. The runbook can say "verify the GPG signature per the bitcoincore.org/en/download guide" instead of inlining a fragile auto-import.

Option 2 is more honest about the trust assumptions. Shipping that as the runbook fix.

## F5 — Bundled v30.2 vs README's historical v29.1 claims (LOW)

**Where.** `README.md` lines 43-49 (preview blurb) and line 211 (Prompt 10 description). Both describe empirical results that happened against Bitcoin Core v29.1 — they're accurate history. But the same README now also says the bundle ships v30.2 (line 87), so a reader sees both "tested on v29.1" and "ships v30.2" without context tying them together.

This is the same shape as the watchlist note added to `BTX-e2e-audit-results.md` on 2026-05-31. Applying the same fix to README is consistent.

**Fix.** Add a short inline parenthetical in the preview blurb explaining that the v29.1 OP_RETURN-non-relay observation is now historical (v30 default datacarriersize is 100,000) and that the envelope-on-mainnet default is kept for operator-restricted nodes (Knots-style configs that still set `-datacarriersize=83`).

## Out of scope

- **Walk-back runtime exercise.** This audit is static. Driving a real regtest scenario (mine blocks → SIGKILL bitcoind → restart and watch the walk-back path execute) is a separate task. The 5-case mental trace in this doc covers the cases I could enumerate; that's not the same as observing the path on a real chain.
- **brk_computer warnings.** `cargo build --release -p brk_cli` produced 3 warnings (`brk_types::Sats` unused, `BLOCK_WINDOW_LEN` dead constant, `held_age_state` field unread). All pre-date today's commits and live in `brk_computer`, untouched by this work. Not BTX's bug, not BTX's fix.
- **F2 + F3** as documented above.
