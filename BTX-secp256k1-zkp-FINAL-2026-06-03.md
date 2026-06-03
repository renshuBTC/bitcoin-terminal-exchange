# `BlockstreamResearch/secp256k1-zkp` — final closure

*Companion to `BTX-secp256k1-zkp-scouting-2026-06-02.md` (what to extract)
and `BTX-secp256k1-zkp-followup-2026-06-03.md` (primitives shipped).
This doc records that integration is also done — there is nothing left to
gain from the cloned repo.*

Date: 2026-06-03.

## Summary

Across two sessions (2026-06-02 and 2026-06-03) every load-bearing item
from `secp256k1-zkp` has been (1) extracted to BTX primitives, (2) ported
to both Python and Rust where applicable, (3) golden-cross-tested across
languages, and (4) wired into the BTX2 record format and publishing flow.

The two earlier docs cover (1)-(3). This doc closes (4) and records the
final state.

## Integrations shipped this session (2026-06-03 evening)

### Phase 1 — Half-aggregation wired into BTX2 BATCH_ANNOUNCE

ALREADY DONE before this session. Audit confirmed:
- Python: `btx_artifact_v2_demo.build_batch_announce` produces
  `N (u16 BE) || N × (BLEN u16 BE || BODY) || HALFAGG_SIG (32×(N+1) B)`
- Rust: `brk_indexer::btx_v2_records::BatchAnnounceBody` parses it;
  `brk_indexer::btx_v2_verify::verify_batch` calls `btx_halfagg::verify`
- Cross-test: `envelope_v2_golden.json` pins a Python-produced envelope
  with a real `BATCH_ANNOUNCE`; Rust verifies byte-for-byte

### Phase 2 — `btx_pool_publish.py` (NEW)

Bridges MuSig2 maker-pool signing to BTX2 BATCH_ANNOUNCE.

- `build_pool_batch_announce(orders)` accepts mixed-batches of solo
  (`seckey=...`) and pool (`seckeys=[...]`) orders
- Pool orders compute `pool_sign_trusted_aggregator(seckeys, sighash) →
  (agg_xonly, 64-byte sig)`. The aggregated pubkey is the order's
  `maker_pubkey`; the sig participates in the batch half-aggregation
  exactly like a solo signature
- Indexer-side verification is UNCHANGED — the existing
  `verify_batch_announce` accepts pool-signed orders identically. Tested
  via upstream verifier with two mixed batches: (1 solo + 1 pool N=2) and
  (pool N=3 + pool N=5). Both PASS.

### Phase 3 — `btx_s2c_envelope.py` (NEW)

The S2C delayed-reveal integration path.

- `build_reveal(commit_txid, input_idx, R0_x, c)` produces a
  `S2C1`-magic reveal record (75 + len(c) bytes)
- `parse_reveal(blob)` is the indexer-side decoder
- `verify_reveal_against_sig(reveal, commit_sig, commit_msg, pubkey)`
  is the cryptographic check
- 4 vectors PASS, including c_len=0 (smallest possible), c_len=28, 69,
  1024. Tampered c, tampered R0_x, and tampered commit_sig all REJECTED.

Implements the "delayed-reveal" path surveyed in the followup doc:
maker publishes a normal-looking Bitcoin tx with an S2C-committed sig;
later publishes a reveal record. Before stage B, the commit is privacy-
preserving; after stage B, the commit is cryptographically bound to `c`.

### Phase 4 — `btx_dlc_publish.py` (NEW)

Bridges the DLC primitives (`Oracle`, `maker_derive_T`, `attest`) to a real
BTX2 `CONDITIONAL_ORDER` record format.

- `build_oracle_conditional_order(order, oracle, event_id, outcome)` →
  CONDITIONAL_ORDER payload bound to a specific DLC outcome
- `completed_sig_from_adaptor(adaptor_pre_sig, s_o)` → BIP340 settlement sig
- 7-stage selftest PASSES end-to-end:
  - Stage C: upstream `verify_conditional_order` accepts the record
  - Stage F: completed sig is a valid BIP340 sig under maker_pubkey at the
    BTX2 sighash → the order CAN settle
  - Stage G: wrong-outcome attestation produces a sig that does NOT verify
    → the order CANNOT maliciously settle (anti-MEV holds)

### Phase 5 — `BTX1-to-BTX2-migration-audit.md` (NEW)

Closes the scouting-doc followup line "Audit BTX1 → BTX2 format migration
path with backward-compatibility". Documents:
- What stays the same (settlement primitive, carrier, rune layer)
- What changes (multi-order packing, conditional orders, sighash domain,
  S2C, maker pools)
- Migration sequencing (no flag day; both formats coexist indefinitely)
- Risks the migration introduces and mitigations

## Final state — what's where

```
SECPK1-ZKP MODULE          → BTX PYTHON              + BTX RUST                 + BTX2 INTEGRATION
─────────────────────────────────────────────────────────────────────────────────────────────────
schnorrsig_halfagg         → btx_halfagg.py          + btx_halfagg.rs           ✓ BATCH_ANNOUNCE
musig (KeyAgg)             → btx_musig2.py           + btx_musig2.rs (key_agg)  ✓ used for agg_xonly
musig (pool sign)          → btx_musig2.pool_sign_demo  + btx_musig2.rs
                                                       (pool_sign_trusted_agg.) ✓ btx_pool_publish.py
ecdsa_adaptor → schnorr    → btx_adaptor.py          + btx_adaptor.rs           ✓ CONDITIONAL_ORDER
musig + adaptor combo      → btx_musig2_adaptor.py   (Rust skipped — composable)
ecdsa_s2c → BIP340 S2C     → btx_s2c.py              + btx_s2c.rs               ✓ btx_s2c_envelope.py
DLC primitive composition  → btx_dlc_demo.py         (pure Python — composable) ✓ btx_dlc_publish.py
bppp / rangeproof /        → skipped (require CT)    skipped (require CT)       n/a — out of scope
surjection / whitelist /                                                         (Bitcoin mainnet has
generator / ellswift                                                              no Confidential Tx)
```

## Test totals — final

Across the secp256k1-zkp extraction work (both sessions combined):

| Component                    | Python tests           | Rust tests                |
|------------------------------|------------------------|---------------------------|
| btx_halfagg                  | 6 golden vectors       | golden Py↔Rust cross-test |
| btx_musig2 KeyAgg            | self-test              | 1 test (golden cross)     |
| btx_musig2 pool sign         | self-test              | byte-cross-test N=2,3,5   |
| btx_adaptor                  | 5 golden vectors       | golden Py↔Rust cross-test |
| btx_s2c                      | 5 golden vectors       | 4 tests (golden + 3 neg)  |
| btx_musig2_adaptor           | 3 vectors (N=2,3,5)    | not ported (composable)   |
| btx_dlc_demo                 | 6-stage flow           | not ported (composable)   |
| btx_pool_publish             | 2 batches (mixed/pool) | n/a — uses Rust verifier  |
| btx_s2c_envelope             | 4 vectors              | not ported (Py-only)      |
| btx_dlc_publish              | 7-stage flow           | not ported (uses Rust verifier) |
| BTX2 envelope (BATCH+COND)   | upstream verify        | envelope_v2_golden.json   |

## Nothing left to gain from the repo

Going through the secp256k1-zkp module tree one final time:

- `schnorrsig_halfagg` — extracted, integrated, indexer-verified at the
  BATCH_ANNOUNCE record level
- `musig` — extracted (KeyAgg + pool sign), integrated via
  btx_pool_publish.py
- `ecdsa_adaptor` — Schnorr-flavoured variant extracted, integrated at
  the CONDITIONAL_ORDER record level
- `schnorr_adaptor` — we ship a Schnorr adaptor derived from papers
  (Fournier's "One-Time Verifiably Encrypted Signatures"). Cross-validation
  against zkp's `schnorr_adaptor` C reference would mirror our Runes
  triple-validation discipline; not load-bearing
- `ecdsa_s2c` — extracted as BIP340 S2C (aligned with our Schnorr makers),
  integrated via btx_s2c_envelope.py delayed-reveal
- `bppp` — requires Confidential Transactions; not on Bitcoin mainnet
- `rangeproof` — requires CT; not on Bitcoin mainnet
- `surjection` — requires Confidential Assets; not on Bitcoin mainnet
- `whitelist` — niche; not BTX-relevant
- `generator` — niche; not BTX-relevant
- `ellswift` — Diffie-Hellman style ECDSA key exchange; BTX has no use case

The remaining items either ARE in BTX or CAN'T be in BTX without bigger
infrastructure changes (Confidential Transactions). The cloned repo's
extractable value for BTX is exhausted.

## Future work — *not* from this repo

Items that would push BTX further but don't come from secp256k1-zkp:

- BIP327 interactive 2-round signing in Rust (not needed for current
  trusted-aggregator pool use case)
- FROST t-of-n threshold (RFC 9591) — a separate spec
- CTV / OP_VAULT / OP_CTV / CCV soft fork integration (not active on
  mainnet as of 2026-06-03)
- ZeroSync light-client integration (separate project)
- BTX3 envelope design (if we ever want to ship S2C-as-default)

None of those come from the zkp repo. They're separate efforts that the
existing BTX watchlist already tracks
(`BTX-roadmap.md`, `BTX-ecosystem-research.md`).

## Closure verdict

The original scouting doc identified three "high strategic value" items:
adaptor signatures, MuSig2, and half-aggregation. Plus one
"flagged-but-not-built" item: sign-to-contract.

As of 2026-06-03:

- All four primitives are shipped in Python AND Rust
- All four primitives are golden-cross-tested across languages
- All four primitives are integrated into BTX2 record formats (BATCH_ANNOUNCE,
  CONDITIONAL_ORDER, S2C reveal record)
- Working end-to-end publisher tooling exists for each integration
  (`btx_pool_publish.py`, `btx_s2c_envelope.py`, `btx_dlc_publish.py`)
- A migration audit doc covers backward-compat

**There is nothing left to gain from the `BlockstreamResearch/secp256k1-zkp`
repository for BTX's current scope.** Anything beyond this is BTX-side
engineering (deploying the formats on signet/mainnet, wiring into the GUI,
running live DLC settlements) — not extraction work.

## File index — final state

```
bitcoin-terminal-exchange/
  Primitives (shipped 2026-06-02):
    btx_halfagg.py
    btx_musig2.py            (KeyAgg + pool_sign_demo)
    btx_adaptor.py           (Schnorr adaptor)
    btx_artifact_v2_demo.py  (BTX2 envelope prototype)
  Primitives (shipped 2026-06-03):
    btx_s2c.py               (BIP340 sign-to-contract)
    btx_musig2_adaptor.py    (MuSig2 + adaptor composition)
    btx_dlc_demo.py          (oracle → adaptor → settle abstract demo)
  Integrations (shipped 2026-06-03):
    btx_pool_publish.py      (Phase 2: MuSig2 → BTX2 BATCH_ANNOUNCE)
    btx_s2c_envelope.py      (Phase 3: S2C → delayed-reveal record)
    btx_dlc_publish.py       (Phase 4: DLC → BTX2 CONDITIONAL_ORDER)
  Documentation:
    BTX-secp256k1-zkp-scouting-2026-06-02.md   (what to extract)
    BTX-secp256k1-zkp-followup-2026-06-03.md   (primitive extraction closure)
    BTX1-to-BTX2-migration-audit.md            (Phase 5: backward-compat)
    BTX-secp256k1-zkp-FINAL-2026-06-03.md      (THIS DOC — integration closure)

brk-btx/crates/brk_indexer/
  Primitives:
    src/btx_halfagg.rs
    src/btx_musig2.rs        (key_agg + pool_sign_trusted_aggregator)
    src/btx_adaptor.rs
    src/btx_s2c.rs           (verifier-side)
  BTX2 indexer (existing):
    src/btx_v2*.rs           (19 modules)
    src/lib.rs               (module registry)
  Tests:
    tests/halfagg_golden.json
    tests/musig2_golden.json
    tests/musig2_pool_golden.json
    tests/adaptor_golden.json
    tests/s2c_golden.json
    tests/envelope_v2_golden.json
    tests/btx_v2_robustness.rs
    tests/btx_v2_end_to_end.rs
  Example HTTP server:
    examples/btx2_http_server.rs
```

End of extraction. The clone has been fully mined.
