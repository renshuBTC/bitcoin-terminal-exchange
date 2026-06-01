# BTX `btxd.py` adversarial audit — 2026-05-31

*Static review of `btxd.py` (1217 lines, the local HTTP gateway daemon). Last security-focused
audit was 2026-05 (memory: `project_corex_security_audit`, which fixed: CSRF High, batch-fill +
carrier Medium, DNS-rebinding High, terminal innerHTML XSS). Today's pass hunts for things that
have drifted since.*

Methodology: read every route handler, every helper with subprocess / file-system / network side
effects, every guard. Quote first, analyze second. Don't re-find prior-audit fixes — those are in
the codebase, this is for net-new issues.

## Findings

| # | Severity | Area | Finding | Status |
|---|----------|------|---------|--------|
| F1 | LOW–MEDIUM | info leak | `Handler._guard` returns `str(e)` for any non-`KeyError` exception → leaks file paths, RPC error fragments, subprocess strings to the client | **fixed** below |
| F2 | LOW | DoS | `/api/supervisor/logs` calls `readlines()` on the WHOLE log file before slicing to `[-n:]` — a buggy daemon writing a multi-GB log can OOM btxd | **fixed** below |
| F3 | VERY LOW | consistency | `h_rune_etch` does an `ord_get("/rune/<NAME>")` lookup without calling `ord_synced()` first, unlike the other rune handlers. Regtest-only path, so practical impact ~zero | **comment landed 2026-06-01** (btxd.py:706-714) flagging the deferral; add `ord_synced()` if/when h_rune_etch generalizes off regtest |

## Strengths worth recording

These are things to **preserve** when touching `btxd.py`. Each represents a defense-in-depth call
that the audit re-validated:

1. **Host allowlist** applied to BOTH `do_GET` (line 962) and `do_POST` (line 1087). Blocks
   DNS-rebinding wallet-driving (the closed `project_corex_security_audit` High finding).
2. **Origin allowlist** (CSRF guard) applied to every `do_POST` after Host check (line 1089).
   Closes the cross-origin POST + text/plain-no-preflight vector.
3. **Wallet-mutating POSTs serialized** under `_WALLET_LOCK` (line 1123). Closes the funding-UTXO
   TOCTOU between concurrent fills.
4. **All subprocess invocations are argv-style** — `bcli` (line 70), `run_tool` (line 100), no
   `shell=True` anywhere. `bcli` normalizes `FileNotFoundError` → `RuntimeError` so a missing
   `bitcoin-cli` doesn't escape as an unhandled exception (line 76-77).
5. **`_send_file` path traversal** uses the strict prefix-and-`os.sep` containment check (line
   941). The looser `startswith(root)` form would have admitted `/x/btx-secrets` for `UI_DIR=/x/btx`
   — the comment on line 939-940 documents exactly that closed case.
6. **Daemon-name allowlist** on `/api/supervisor/logs` (line 1071). Prevents path traversal via
   `?name=../../etc/passwd`.
7. **Series path-component validation** on `/api/brk/series/...` (line 1005). Each segment is
   `isalnum() or '_'`; the trailing tail is `{data,latest,len}`. Proxy cannot be tricked into an
   unrelated brk_cli route.
8. **Order-proof param shape check** on `/api/dex/order-proof/{txid}/{vout}` (line 1020). txid =
   64 hex; vout = digits. brk_cli re-validates downstream.
9. **POST body size cap** before allocation (line 1093). Closes the unbounded-read DoS at the
   reader, not the parser.
10. **`h_setup_complete` `datadir_override` shell-safety check** (line 240). The supervisor wraps
    this value unquoted inside `bash -c "..."`, so the forbidden-char set explicitly includes
    `\x00 \` `` $ " ' ; | & < > ( ) { } * ? [ ] \ \n \r` — the comment on line 233-236 documents
    *why*. Don't loosen this.
11. **`h_wallet_send` input validation** (line 390-424): address rejects whitespace/control chars
    and length-bounds at 90; amount float-coerced and bounded `(0, 21_000_000]`; fee_rate bounded
    `(0, 10_000]`; label ≤ 255. Pre-flight trusted-balance check is UX, not security, but it's the
    correct call.
12. **`ord_synced()` gate** correctly applied on all rune-touching handlers EXCEPT `h_rune_etch`
    (F3 above) — `h_order_create` line 596, `h_addressed_propose` line 770, `h_rune_propose` line
    815, `h_rune_countersign` line 839. The conditional gates (`if rune_block or rune_tx`) on the
    first two are correct: BTC-only orders don't trust ord for safety-critical state.
13. **`h_health` uses raw socket with `settimeout(1)`** per the `reference-urllib-timeout-sigstop`
    memory finding. The previous urllib path would not have fired on a SIGSTOPped ord. Don't
    revert this.

## F1 — `Handler._guard` info leak

**Where.** `btxd.py:952-959`:

```python
def _guard(self, fn):
    try:
        return fn()
    except KeyError as e:
        self._send({"error": f"missing field {e}"}, 400)
    except Exception as e:  # noqa
        self._send({"error": type(e).__name__, "detail": str(e)}, 500)
    return None
```

**Issue.** `str(e)` on an arbitrary exception can include:

- File paths (`FileNotFoundError`, `PermissionError` embed the path)
- `bitcoin-cli` RPC error messages (passed through verbatim by `bcli` line 79)
- Cookie file paths (when bitcoin-cli reports an auth failure)
- Subprocess stderr fragments

btxd binds only loopback (`127.0.0.1`), so an unauthenticated remote attacker can't reach this.
But ANY local process on the box can hit btxd and harvest internal paths — useful for fingerprinting
prior to a different attack. Defense-in-depth says: log the detail to stderr (operators want it
for debugging), return a generic `{"error": "internal error"}` to the client.

**Fix.** Wrap the detail in a stderr log, strip it from the client response:

```python
def _guard(self, fn):
    try:
        return fn()
    except KeyError as e:
        # KeyError on body[k] is a CLIENT error (missing field) — the field name is the
        # client's own input, not internal state. Safe to echo.
        self._send({"error": f"missing field {e}"}, 400)
    except Exception as e:  # noqa
        # Internal errors: log detail to stderr (operators need it), return a generic
        # message to the client. Avoids leaking file paths, RPC error fragments, or
        # subprocess output to local processes that hit btxd over loopback.
        sys.stderr.write(f"btxd: handler {type(e).__name__}: {str(e)[:500]}\n")
        self._send({"error": "internal error", "type": type(e).__name__}, 500)
    return None
```

The exception **type** is still surfaced (it's classification, not content) so the GUI can render
a distinct error class; the message is dropped.

## F2 — `/api/supervisor/logs` whole-file read OOM

**Where.** `btxd.py:1073-1081`:

```python
def _tail():
    path = f"/tmp/btx-{name}.log"
    try:
        with open(path, "r") as f:
            lines = f.readlines()
        return {"lines": [l.rstrip("\n") for l in lines[-n:]]}
    except OSError:
        return {"lines": []}
```

**Issue.** `f.readlines()` reads the entire file into a list before `[-n:]` slices the tail. With
n capped at 2000 (line 1067), the response is bounded — but the *read* is not. If a daemon writes
a 2 GB log (e.g. a runaway `info!()` in a loop), btxd allocates 2 GB to slice the last 2000 lines.
For a daemon serving local APIs that's an OOM and process exit.

**Fix.** Tail-read from the end of the file with a bounded byte budget. 2000 lines × ~500 bytes per
line ≈ 1 MB upper budget; cap at a safe 2 MB to be defensive:

```python
def _tail():
    path = f"/tmp/btx-{name}.log"
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)            # seek to end
            size = f.tell()
            # Read at most 2 MB from the tail. n*~500B ≈ 1 MB for n=2000, so 2 MB is a
            # safe upper budget that catches up to ~4000 lines of typical log content
            # without unbounded allocation if the file is multi-GB.
            budget = min(size, 2 * 1024 * 1024)
            f.seek(size - budget, 0)
            buf = f.read(budget).decode("utf-8", errors="replace")
        # If we started mid-line, drop the partial first line (it would be unreadable
        # on its own anyway). Then return at most the last n complete lines.
        lines = buf.splitlines()
        if budget < size and lines:
            lines = lines[1:]
        return {"lines": lines[-n:]}
    except OSError:
        return {"lines": []}
```

This caps both memory and the number of lines, regardless of how big the underlying log gets.

## F3 — `h_rune_etch` missing `ord_synced()` (deferred)

**Where.** `btxd.py:708-713`:

```python
try:
    existing = ord_get(f"/rune/{rune}")
    if existing and existing.get("id"):
        return {"error": f"rune '{rune}' is already etched (id {existing['id']}) — pick another name"}, 400
except Exception:
    pass  # 404 / not found = name is free = good
```

If ord is lagging the chain tip, `ord_get("/rune/<NAME>")` may 404 on a rune that has in fact
already been etched, leading the caller to issue an etch that ends up as a cenotaph (no premine
minted, BTC wasted on commit + reveal txs). Inconsistent with the rune handlers that DO gate on
`ord_synced()`.

But `h_rune_etch` early-returns with `400` if `CFG["chain"] != "regtest"` (line 695-696). On
regtest the chain is tiny and ord is trivially synced; this code path can never observe a stale
ord in practice. The audit notes it as a deferred consistency cleanup, not a real bug. If
`h_rune_etch` ever gets generalized off regtest, add the gate then.

## Out of scope

- **Dynamic / runtime testing.** This is a static review. No CSRF/rebinding fuzz, no concurrent
  load test, no probe of the Host allowlist via a forged Host header — those were done in E2E
  Prompt 11 (`BTX-e2e-audit-results.md` line 25) and don't need re-running unless btxd's guard
  code changes.
- **Crypto correctness of btx_taproot.py / btx_envelope_publish.py.** Out of `btxd.py`'s scope;
  those have their own audits in `project_corex_security_audit`.
- **brk_cli (Rust) side.** Audited 2026-05-31 in `BTX-v0.2.18-19-audit.md`. The walk-back +
  recognizes_block code is the new surface there; not this audit.
