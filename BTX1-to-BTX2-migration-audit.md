# BTX1 → BTX2 format migration audit

*Followup table item from `BTX-secp256k1-zkp-scouting-2026-06-02.md`: "Audit
BTX1 → BTX2 format migration path with backward-compatibility (~1 week)".
This document closes that line by mapping the migration surface and stating
the backward-compat contract.*

Date: 2026-06-03.

## Scope

BTX1 is the on-chain artifact format proven on mainnet at the B4 broadcast
(2026-06-02, reveal `8acf6c70…` in block 952071). It carries one order per
envelope (`SINGLE_ORDER`-equivalent), magic `BTX1`, body layout per
`btx_0b.serialize_artifact`. ~207 bytes per order including the rune
runestone byte.

BTX2 is the new envelope format specified in `BTX-v2-spec-2026-06-02.md` and
implemented across both repos (see `BTX-v2-indexer-architecture-2026-06-03.md`).
Magic `BTX2`, supports three record types:

- `SINGLE_ORDER` (0x01) — opaque BTX1 payload, intentional pass-through
- `BATCH_ANNOUNCE` (0x02) — N orders + 32(N+1)-byte half-aggregated sig
- `CONDITIONAL_ORDER` (0x03) — order body + 33-byte T + 65-byte adaptor sig

The migration question is: how does the BTX indexer behave when both BTX1
and BTX2 envelopes are present on chain?

## Backward-compatibility contract

The indexer accepts BOTH formats indefinitely. There is no flag day. The
two formats are distinguished by the first 4 magic bytes of the envelope
payload:

| Magic   | Format | Decoder              | Indexer module          |
|---------|--------|----------------------|-------------------------|
| `BTX1`  | BTX1   | `btx_0b.parse_*`     | `brk_indexer::btx`      |
| `BTX2`  | BTX2   | `btx_v2::parse_envelope` | `brk_indexer::btx_v2_*` |
| other   | —      | rejected             | n/a                     |

`brk_indexer::btx_v2_scan` scans every transaction for both magics in the
same pass; either match is dispatched to the appropriate decoder.

## What stays the same

These properties carry from BTX1 to BTX2 unchanged:

- **The atomic-swap settlement primitive.** `SIGHASH_SINGLE|ANYONECANPAY`
  (`0x83`) is unchanged. BTX2 orders settle via the same 1-tx atomic swap as
  BTX1 orders. The `verify` step on the *settlement* tx is format-agnostic.
- **The carrier choice.** Both formats ride either an OP_RETURN carrier or
  a Taproot witness-envelope carrier. The B4 broadcast used the witness
  envelope, which is the recommended mainnet default. BTX2 does not change
  the carrier; it changes only the envelope *payload*.
- **The rune layer.** Rune issuance, edicts, and balance accounting are
  controlled by Bitcoin's runestone protocol, not by BTX. Both BTX1 and BTX2
  reference runes by `(rune_block, rune_tx)` identifier.
- **The maker pubkey model.** BTX2 still embeds an x-only pubkey in each
  order body. For pool-signed orders the pubkey is the MuSig2-aggregated
  one; the indexer treats it identically.
- **Atomicity.** No partial migration. An envelope is wholly BTX1 or wholly
  BTX2; there is no record-type that mixes the two.

## What changes

- **Multi-order packing.** BTX1 carries one order per envelope (~207 B per
  order). BTX2 `BATCH_ANNOUNCE` carries N orders with one half-aggregated
  signature footer. At N=10, this saves ~50% on the signature bytes
  (`32×(N+1)` vs `64×N`).
- **Conditional orders.** BTX1 has no conditional order type. BTX2
  `CONDITIONAL_ORDER` records embed an encryption point `T` + a 65-byte
  Schnorr adaptor pre-sig. The order settles only after the secret `t`
  matching `T = t·G` is revealed (oracle attestation, hashlock, cross-chain
  swap). BTX1 orders cannot become conditional retroactively.
- **Per-order sighash domain.** BTX2 uses
  `TaggedHash("BTX2/order/sighash", body_bytes)`. BTX1 used the order's
  artifact bytes as the message directly. The two namespaces are disjoint
  so a sig from one cannot be replayed in the other.
- **Sign-to-contract support.** New for BTX2 via `btx_s2c.py` and the
  delayed-reveal record type in `btx_s2c_envelope.py`. BTX1 had no covert-
  commitment story.
- **Maker-pool support.** BTX2 supports MuSig2-aggregated maker keys
  transparently via the existing format (the aggregated x-only pubkey
  occupies the same maker_pubkey field). BTX1 did not preclude pool
  signing, but lacked the tooling — `btx_pool_publish.py` was added in
  this session.

## Migration sequencing

1. **Now (2026-06-03).** BTX2 indexer ships in `brk-btx`; BTX2 publishers
   ship in `bitcoin-terminal-exchange` (incl. pool, S2C, DLC bridges). The
   BTX1 mainnet artifact at block 952071 remains the canonical proof that
   the *carrier* and *consensus accept* path works.
2. **Next.** First BTX2 publish to public signet, then mainnet. The B4
   playbook applies: small, observable, post-hoc validation. Recommended
   first BTX2 broadcast is a 2-order `BATCH_ANNOUNCE` to demonstrate the
   format under default policy.
3. **Steady state.** Both BTX1 and BTX2 orders coexist in the indexer. New
   publishers default to BTX2; old BTX1 orders continue to be indexed and
   settled. There is no deprecation date.

## Risks the migration introduces

- **Per-format consensus drift.** Any divergence in how the Python publisher
  encodes vs. how the Rust indexer decodes will produce orders that don't
  appear in the book. Mitigation: the byte-exact `envelope_v2_golden.json`
  cross-test in `brk-btx/crates/brk_indexer/tests/` was pinned this session;
  it covers SINGLE, BATCH, and CONDITIONAL records.
- **Order-id collision.** BTX1 used `(announce_txid, 0)` as order id. BTX2
  uses `(announce_txid, envelope_record_index, intra_record_order_index)`.
  For BTX1 orders carried inside a BTX2 SINGLE_ORDER record, the BTX2
  conventions apply. There is no risk of cross-format collision; the
  decoders run on disjoint magics.
- **Reorg semantics across formats.** Both BTX1 and BTX2 follow the same
  rule: announce / fill / cancel / expire events propagate to the indexer
  store; a reorg rolls back the affected blocks' events on both formats
  via `btx_v2_reorg::rewind_store` (which is format-agnostic — it operates
  on the stored events, not the wire format).
- **Tooling drift.** The publisher CLIs (`btx_envelope_publish.py`,
  `btx_pool_publish.py`, `btx_dlc_publish.py`) currently target BTX1 or
  BTX2 separately. A unified publisher with `--format btx1|btx2` is a
  followup; not load-bearing for indexing.

## What was NOT done in this audit

- A live regtest run of a BTX2 BATCH_ANNOUNCE alongside a BTX1 order. The
  cross-test golden vectors and pool publish selftest cover the format /
  crypto correctness; the live regtest is on the deployment backlog but
  outside this migration audit's scope.
- A network-policy review of BTX2 envelopes' default-relay acceptance. The
  Taproot witness envelope is already proven on mainnet (B4); BTX2 only
  changes the payload bytes, not the envelope structure. Mempool policy is
  unaffected.
- A formal compatibility test where the same on-chain order announces in
  both BTX1 and BTX2 simultaneously. Not a real-world scenario.

## Recommendation

Treat BTX2 as the new default for any maker tooling shipped from now on,
but **do not deprecate BTX1**. The B4 mainnet artifact will keep showing up
in the indexer because the chain doesn't forget. The cleanest migration
posture is: BTX2 is what we publish; BTX1 is what we still read.

Closes the followup-table item.

## Cross-references

- `BTX-v2-spec-2026-06-02.md` — full BTX2 wire format
- `BTX-v2-indexer-architecture-2026-06-03.md` — indexer module map
- `BTX-secp256k1-zkp-scouting-2026-06-02.md` — original scouting + followups
- `BTX-secp256k1-zkp-followup-2026-06-03.md` — primitive extraction closure
- `BTX-B4-case-study.md` — BTX1 mainnet proof at block 952071
- `brk-btx/crates/brk_indexer/tests/envelope_v2_golden.json` — Python ↔ Rust
  cross-validation for the BTX2 wire format
