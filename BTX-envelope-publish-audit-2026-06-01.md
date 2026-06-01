# BTX `btx_envelope_publish.py` mainnet-safety audit — 2026-06-01

*Adversarial pass before B4 (the first real mainnet broadcast). Previous audits
covered btxd.py, brk_indexer, and the artifact format; this module is the
"actually puts a tx on the network" layer and hasn't been hostilely re-read since
the proof-of-functionality in `BTX-envelope-publish-runbook.md` (2026-05-24).*

Methodology: read every function with subprocess / network / file-system side
effects, every error path, every place where user input flows into an action.
Quote first, analyze second.

## Findings

| # | Severity | Area | Finding | Status |
|---|----------|------|---------|--------|
| F1 | MEDIUM | recovery | KeyboardInterrupt between commit broadcast and reveal broadcast does NOT print the recovery JSON, so if the user didn't pass `--state-file` the ephemeral seckey is lost forever and the commit funds are permanently stranded | **fix proposed below** |
| F2 | LOW | UX | No sanity warning when `--fee-sats` is set absurdly low (e.g. 50 sats). The dust guard catches negative output but not unrelayable fee-rate | deferred — B4 runbook handles by spec'ing 200 |
| F3 | VERY LOW | error msg | `if a.state_file:` (line 167) silently no-ops when state-file is missing — no warning to the user that they're losing their safety net | informational |

## Strengths to preserve

These are defenses-in-depth that the audit re-validated; preserve when editing:

1. **Pure `build_reveal()`** (line 71-117) — node-free, offline-testable, has 11
   checks in `selftest()` covering witness shape, signature verification, sighash,
   tapscript, control block parity, dust floor, and tamper detection. The on-node
   step only adds consensus proof.
2. **Dust guard** (line 85-88): `if out_value < 546` — catches the case where
   `fee_sats > commit_value_sats` (negative output) AND the below-dust case in
   one check. The 546-sat floor is the conservative P2SH dust threshold.
3. **State-file recovery flow** (line 164-191): writes ephemeral key + commit
   refs to a 0o600 JSON file BEFORE the reveal try block, so a crash mid-flow
   is recoverable via `publish-reveal --state-file`. The catch block also
   re-emits the recovery info to stdout so the user has a second chance.
4. **0o600 perms** on the state file (line 168 `os.O_CREAT` + line 171 explicit
   `chmod`) — defends against curious-roommate / shared-machine attacks.
5. **Argv-style subprocess** (line 60 `subprocess.run([cli, ...])`) — no
   `shell=True`, no string interpolation, can't be tricked into shell
   injection regardless of input.
6. **Internal byte order conversion** (`lx(commit_txid)` at line 89) — the
   public RPC txid is little-endian-string, the consensus internal byte order
   is big-endian-bytes. This conversion is the most common mistake in custom
   Bitcoin tx-building tooling; it's done correctly.
7. **Fresh `aux_rand`** per signature (line 102-104) — defense-in-depth
   against fault/side-channel attacks on the Schnorr key. BIP340 is secure
   without it, but the cost is zero and the hardening is real.

## F1 — KeyboardInterrupt between commit and reveal loses the seckey

**Where.** `btx_envelope_publish.py:172-191`:

```python
try:
    # 2) build the reveal back to a fresh wallet address
    out_addr = a.out_addr or cli("getnewaddress", "", "bech32")
    out_spk = bytes.fromhex(cli("getaddressinfo", out_addr)["scriptPubKey"])
    res = build_reveal(artifact_hex=a.artifact_hex, seckey=seckey, commit_txid=commit_txid, ...)
    res.update({"commit_txid": commit_txid, "commit_vout": commit_vout, ...})
    # 3) broadcast the reveal (the commit is already in the mempool from sendtoaddress)
    if a.broadcast:
        res["reveal_txid"] = cli("sendrawtransaction", res["reveal_hex"])
except Exception as e:
    recovery["error"] = f"reveal failed after commit {commit_txid} was broadcast: {e}"
    recovery["recovery"] = (
        "commit funds are spendable ONLY by seckey_hex above; recover with: ..."
        + (f"  (or --state-file {a.state_file})" if a.state_file else " — SAVE seckey_hex now"))
    print(json.dumps(recovery, indent=2)); sys.exit(1)
```

**Issue.** `except Exception` does NOT catch `KeyboardInterrupt` (which inherits
from `BaseException`, not `Exception`). If the user presses Ctrl+C between the
commit broadcast (line 149) and the reveal broadcast (line 183):

- KeyboardInterrupt fires, control bypasses the except block
- Python prints a traceback to stderr
- The recovery JSON is NEVER printed
- If `--state-file` was NOT passed, the ephemeral seckey vanishes from memory
- The commit's P2TR output is spendable ONLY by that seckey
- **The commit funds are permanently lost.**

The state file at line 167-171 IS the primary safety net, and the B4 runbook
does specify it. But the audit's job is to flag landmines for the cases the
runbook didn't anticipate (or future tooling that calls `cmd_publish` without
passing state-file).

**Fix.** Two equally valid options:

**Option A (smaller diff):** Change `except Exception as e:` to
`except BaseException as e:`. This catches KeyboardInterrupt too. The recovery
JSON is printed, then `sys.exit(1)`. Slightly unusual but a deliberate
defensive choice given the asymmetric stakes (lost commit funds vs. slightly
chatty Ctrl+C output).

```python
except BaseException as e:
    recovery["error"] = f"interrupted/failed after commit {commit_txid} was broadcast: {type(e).__name__}: {e}"
    recovery["recovery"] = (...)
    print(json.dumps(recovery, indent=2)); sys.exit(1)
```

**Option B (more thorough):** Always write a state file, defaulting to a
temp path if user didn't pass one, AND print the path on commit success so
the user knows where to find it on a crash.

```python
# Always have a recovery file — auto-name one if user didn't specify.
state_path = a.state_file or os.path.join(tempfile.gettempdir(),
    f"btx-publish-state-{commit_txid}.json")
fd = os.open(state_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump(recovery, f, indent=2)
os.chmod(state_path, 0o600)
if not a.state_file:
    print(f"# recovery state written to {state_path} (auto-named; pass --state-file to choose)",
          file=sys.stderr)
```

Option A is safer (avoids the silent-state-file-creation surprise) and is
what I'd recommend. Option B is more thorough but introduces a new failure
mode (state file accumulating in /tmp).

**For B4:** The runbook DOES pass `--state-file "$STATE_FILE"` so the user is
protected even with the current code. F1 is the safety net for *future*
callers (e.g., a GUI that doesn't know to pass state-file).

## F2 — No fee-rate sanity warning

**Where.** `btx_envelope_publish.py:281`:

```python
pub.add_argument("--fee-sats", type=int, default=DEFAULT_FEE)
```

`DEFAULT_FEE = 2000`. The B4 runbook uses `--fee-sats 200` (1 sat/vB for a
~200vB reveal — the relay floor). At 200 sats:
- If mainnet's `mempoolminfee` is currently above 1 sat/vB, the reveal won't
  propagate. The commit IS in the mempool already (it went through the
  wallet's fee estimation in `sendtoaddress`), but the reveal would sit in
  the local mempool only and never reach miners.
- If the user typo'd `--fee-sats 20`, the reveal would be 0.1 sat/vB which
  is unrelayable on every realistic mainnet config. No warning fires.

The dust guard at line 85 catches `fee_sats > commit_value_sats - 546` but
doesn't catch "fee is too low to relay".

**Fix.** Add a sanity check:

```python
if a.fee_sats < 300:
    print(f"# WARNING: --fee-sats {a.fee_sats} is unusually low; "
          f"mainnet relay floor is typically ~1 sat/vB and a 200vB reveal needs "
          f">= 200 sats. Reveal may not propagate.", file=sys.stderr)
```

Or call `estimatesmartfee` and compare:

```python
fr = cli("estimatesmartfee", 6).get("feerate")  # BTC/kvB
floor_sats = int(fr * COIN / 1000) * 200 if fr else 200  # 200vB reveal
if a.fee_sats < floor_sats * 0.8:
    print(f"# WARNING: --fee-sats {a.fee_sats} is below estimatesmartfee "
          f"(~{floor_sats} sats). Reveal may not propagate.", file=sys.stderr)
```

**For B4:** Not a runbook blocker. The runbook's 200-sat fee is at the floor
for current mainnet conditions (verify via `mempool.space/api/v1/fees/recommended`
before broadcasting). Could be raised to 500 for headroom.

## F3 — Silent no-op when `--state-file` is omitted

**Where.** `btx_envelope_publish.py:167-171`:

```python
if a.state_file:
    fd = os.open(a.state_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(recovery, f, indent=2)
    os.chmod(a.state_file, 0o600)
```

If the user doesn't pass `--state-file`, the recovery file is silently NOT
written. The user gets no warning that they're forgoing the safety net.
Compounded by F1 (KeyboardInterrupt path), this is a real footgun for the
case where the user just wanted to try publishing without thinking about
recovery.

**Fix.** Either Option A from F1 (which makes the safety net work even
without state-file), or just warn:

```python
if not a.state_file:
    print("# NOTE: --state-file not set; if the reveal fails or is interrupted, "
          "you'll need to recover via the recovery JSON printed below "
          "(KEEP IT or commit funds are stranded).", file=sys.stderr)
```

**For B4:** Runbook passes `--state-file`, so not relevant.

## Out of scope

- **Crypto correctness of `btx_taproot.py` + `carrier.envelope_tapscript`** —
  separate audits cover these (BTX-v0.2.18-19-audit.md and the original
  envelope publish runbook's proven-on-signet result).
- **Wallet-side fee estimation in `sendtoaddress`** — that's bitcoind/wallet
  behavior; if you don't trust your wallet's fee estimation, override via
  `-fallbackfee` or similar.
- **Network-level propagation** — covered by the BTX-seeding-runbook.md
  pattern + the actual B4 broadcast.

## Recommendation summary

- **For B4 (immediate):** runbook is correct; the audit doesn't change the
  steps. Just verify `--fee-sats` is reasonable vs. current mempool floor
  before Step 5 (the broadcast).
- **For follow-up (not B4-blocking):** ship F1 Option A as a one-line change
  (`except Exception` → `except BaseException`) plus F2 warning. ~10 lines
  total. Could land in a future commit alongside any other publisher tweaks.
- **For very-future:** if BTX gains a GUI button for "publish envelope" that
  doesn't think about recovery, F3 and F1 become much more important. Today
  the only caller is this runbook, which IS careful.
