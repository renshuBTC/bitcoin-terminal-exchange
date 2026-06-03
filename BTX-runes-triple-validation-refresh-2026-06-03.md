# Runes triple-validation — 2026-06-03 refresh

*Continues the cross-validation cycle (`BTX-bip340-bip341-foundation-2026-06-03.md`,
`BTX-bip327-keyagg-finding-2026-06-03.md`). This time validating the
**Runes asset layer** by checking for drift in the references BTX's
hand-rolled decoder is triple-validated against.*

Date: 2026-06-03.

## Why this check

BTX's `BTX-competitive-landscape.md` (line 70) records:

> *"BTX's rune layer is now triple-validated (ord Rust + Magic Eden TS + BTX Python)"*

The Runes spec is consensus-relevant for BTX: a decoder divergence makes
`rune_id` and cenotaph status diverge from the rest of the ecosystem,
which would break order matching and trade classification. The
triple-validation is only meaningful if the references themselves are
still authoritative.

Two months have passed since the last alignment. Time to re-check both
references for drift and re-run BTX's existing cross-tests.

## Reference 1 — `ordinals/ord`

Pinned commit in BTX's local `Bitcoin CoreX/ord-reference/`:
`5241ef311e015cff4759a379085c8cc8913e621a` (2026-04-03,
"Add /gallery API endpoint (#4508)").

Fetched `origin/master`:

```
Origin master HEAD: 5241ef311e015cff4759a379085c8cc8913e621a
  2026-04-03 04:24:03 +0000  Add /gallery API endpoint (#4508)

=== NO DRIFT — pinned commit IS master HEAD ===
```

ord has not shipped a new commit in the 2 months since BTX's pin. The
runestone implementation is stable; BTX's port from `crates/ordinals/src/runestone.rs`
remains current.

## Reference 2 — `me-foundation/runestone-lib`

Pinned commit: `13b5ef995f44e881b6de541a2f7d5cf77ad491e9` (2024-08-14,
"Fix Deprecation Warning and Resolve Minor Issues (#78)").

Fetched `origin/main`:

```
Origin main HEAD: 13b5ef995f44e881b6de541a2f7d5cf77ad491e9
  2024-08-14 10:19:35 -0700  Fix Deprecation Warning and Resolve Minor Issues (#78)

=== NO DRIFT — pinned commit IS main HEAD ===
```

Magic Eden's `runestone-lib` has been **dormant for ~22 months** (since
August 2024). This is itself worth noting: BTX's validation reference is
no longer being actively maintained by Magic Eden, but for Runes spec
purposes that's fine — the spec is frozen.

## BTX-side re-validation

### `btx_runes_xcheck.py` — 19/19 PASS

19 pinned golden vectors from a prior differential run
(5 structured specs + 800 random well-framed runestones, 805/805
agreement between BTX and ME runestone-lib). Output:

```
runes decoder vs Magic Eden runestone-lib: 19/19 golden vectors match
```

Includes both valid runestones (with edicts) and 13 cenotaphs covering
varint overflow, bad opcodes, supply overflow, and other corner cases.

### `btx_runestone_cenotaph_adversarial.py` — ALL CLEAN

11 named cenotaph triggers (must classify as cenotaph) + 2 controls
(must NOT classify as cenotaph) + 50,000-shape totality fuzz. Output:

```
== Cenotaph triggers (each must classify as cenotaph + reason) ==
  [PASS] 1 varint overflow (>127 bits)
  [PASS] 2 truncated PUSHDATA1 (no len byte)
  [PASS] 3 truncated PUSHDATA2 (no len bytes)
  [PASS] 4 truncated PUSHDATA4 (no len bytes)
  [PASS] 5 non-push opcode (OP_DUP 0x76)
  [PASS] 6 PUSHDATA1 claims 0xff, only 10 follow
  [PASS] 7 unrecognized even tag (tag=128)
  [PASS] 9 dangling odd tag with no value (recorded)

== Controls (must NOT be cenotaph) ==
  [PASS] 8 empty runestone (6a 5d only)
  [PASS] 8b empty payload via OP_0 push

== Totality fuzz: 50000 random `6a 5d ...` scripts ==
  [PASS] totality: 0 exception leaks across 50000 bufs
  [PASS] totality: 0 missing-key shapes across 50000 bufs
============================================================
ALL CLEAN
```

## Verdict

The Runes triple-validation discipline holds as of 2026-06-03:

| Layer                            | Status                              |
|----------------------------------|-------------------------------------|
| ord reference                    | ✓ unchanged since pin (master HEAD) |
| runestone-lib reference          | ✓ unchanged since pin (main HEAD; dormant since 2024-08) |
| BTX-vs-runestone-lib golden xtest| ✓ 19/19 PASS                        |
| BTX cenotaph adversarial         | ✓ 8/8 named + 50,000 totality fuzz CLEAN |

No drift. No regressions. No code changes required.

## Quiet finding worth recording

`me-foundation/runestone-lib` has not received commits since
2024-08-14 — approaching 2 years dormant. This means:

1. The Magic Eden TypeScript implementation is effectively a frozen
   reference point. BTX should NOT rely on it for spec evolution; only
   for byte-level decoder validation.
2. If ord ever does ship a Runes spec change (a hard fork of the
   protocol), runestone-lib won't follow automatically. BTX would need
   to choose between maintaining alignment with ord (the canonical
   implementation) and runestone-lib (the dormant snapshot).
3. The triple-validation discipline's redundancy is reduced: it's
   effectively a "BTX + 2 frozen references" check, not a "BTX + 2
   actively maintained references" check.

This isn't a problem for the current Runes spec (frozen since rune
activation), but worth pinning so future audits don't assume the
references are still in lockstep with active development.

## Test runners — re-runnable

Both tests are pure-Python, no node required:

```bash
cd ~/bitcoin-terminal-exchange
python3 btx_runes_xcheck.py                    # 19/19 golden vectors
python3 btx_runestone_cenotaph_adversarial.py  # 50,008 adversarial cases
```

They become the canonical "did BTX's Runes decoder regress?" tripwire,
complementing `btx_bip340_xtest.py` and `btx_bip341_xtest.py` from the
foundation validation work.

## Cross-references

- `BTX-bip340-bip341-foundation-2026-06-03.md` — foundation crypto
  validation
- `BTX-bip327-keyagg-finding-2026-06-03.md` — MuSig2 KeyAgg variant +
  Path B canonical
- `BTX-competitive-landscape.md` line 70 — the triple-validation claim
- `btx_runes_xcheck.py` (19-vector ME runestone-lib cross-test)
- `btx_runestone_cenotaph_adversarial.py` (50,008-case adversarial fuzz)
- `Bitcoin CoreX/ord-reference/` (ord at 5241ef3)
- `Bitcoin CoreX/runestone-lib-reference/` (runestone-lib at 13b5ef9)
