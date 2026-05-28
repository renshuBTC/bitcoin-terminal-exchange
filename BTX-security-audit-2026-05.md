# BTX adversarial security audit — 2026-05-28

A skeptic's pass whose goal was to *break* BTX, not confirm it: every "byte-identical across
implementations" claim was treated as a hypothesis to falsify, with claims checked against the actual
code (read with authoritative tooling, not the README) and, where runnable, against an independent
implementation or live differential. Scope: the consensus-reachable and wallet-driving surfaces —
`btx_taproot.py` / `btx_envelope_publish.py` (BIP340/341), `verify_maker_sig` + the artifact parser
(`btx_0b.py` / `btx.rs`), the consensus hash / Merkle / event-hash determinism (Python↔Rust), the
fill/cancel classifier + reorg invariants (`btx.rs`), the carrier parsers (`btx_carrier.py` /
`btx.rs`), and the `btxd` localhost trust boundary.

## Result

**1 High + 3 Medium real bugs found and fixed**, plus Informational/Low hardenings. No protocol-level
principal-loss path and no chain-consensus break were found; the maker price commitment, atomic
settlement, reorg / no-resurrection invariants, and BIP340/341 crypto are sound. The one unauthorized-
spend vector (a localhost CSRF) is closed. All three Medium bugs are cross-indexer **book-view
divergences** (Python reconstruction more liberal than the authoritative Rust indexer) — no funds at
risk, but each breaks the "byte-identical across implementations" claim until fixed. All fixes are
regression-tested where runnable (brk-btx `cargo test -p brk_indexer btx` 30/30; bitcoin-terminal-exchange
`btx_test_all.py` 12/12).

| # | Finding | Severity | Impact | Fix commit(s) |
|---|---|---|---|---|
| F-CSRF | btxd accepted cross-origin wallet-mutating POSTs (Host guard stops DNS rebinding but not a direct `fetch` to 127.0.0.1; a `text/plain` body skips the CORS preflight) | **High** | A page the user merely visits could drive order-fill/etch/swap signing → unauthorized on-chain spend | bitcoin-terminal-exchange `0de0940` |
| F-POINTER | The rune↔rune maker verifier (`verify_addressed_rune_tx` / `allocate_runes`) hardened malicious *edict* outputs but not the runestone **pointer**. `allocate_runes` sent leftover runes to `pointer if pointer in nonop else nonop[0]` — so a pointer→OP_RETURN (or pointer≥n_outputs) fell back to the first non-OP_RETURN output (the maker's output 0). ord instead allocates leftover to the pointer's output and burns runes on any OP_RETURN (and pointer≥n_outputs is a cenotaph that burns ALL) | **High** | Snipe-resistance break: a taker proposes a swap with rune B left unallocated and a pointer→OP_RETURN (or ≥n_outputs). The verifier computes output 0 "receiving" rune B and signs; on broadcast ord burns rune B while the maker's rune A goes to the taker — **maker loses their asset and receives nothing** | bitcoin-terminal-exchange (`allocate_runes` leftover rule = ord exactly + verifier pointer-range guard) — pending commit |
| F-FILL | Fill/cancel classifier compared every spent offer against **output 0**, but SIGHASH_SINGLE commits the output at the offer's **input index** | **Medium** | Batch-fill legs at input index ≥1 mislabeled FILLED→CANCELLED in `/history`, "X of Y filled", and the event-hash stream. Open book + consensus hash unaffected | brk-btx `38418ca07`, bitcoin-terminal-exchange `a2499f6` |
| F-CARRIER | Carrier extractors diverged: Rust scans every output / the envelope payload for MAGIC and parses from the first occurrence; Python required MAGIC at the start of an OP_RETURN push | **Medium** | An on-chain-valid carrier with junk before MAGIC (or a non-OP_RETURN carrier) is admitted by Rust, rejected by Python → two honest indexers reconstruct different books → `book_hash`/`book_root`/`event_hash` diverge (breaks the cross-indexer claim). No principal loss | bitcoin-terminal-exchange `ed45175` |
| F-ANNEX | Witness carrier extraction diverged: Python `_extract_btx_from_tx` scanned **every** witness stack element; Rust `extract_from_witness` reads **only the Taproot leaf script** (`taproot_leaf_script_bytes`, annex-aware) | **Medium** | An order-bearing envelope hidden in the BIP341 **annex** (arbitrary spender data) of any Taproot spend is admitted by the Python reconstruction but ignored by the Rust indexer → `book_hash`/`book_root`/`event_hash` diverge. No principal loss | bitcoin-terminal-exchange `fd68902` |
| F-BIND | Python `verify_maker_sig` verified the sig against the artifact-supplied pubkey without binding it to the offer UTXO's scriptPubKey (Rust already binds) | Low | Standalone Python reconstruction could mislabel a forged artifact over someone else's P2WPKH UTXO as a "VALID open order"; unfillable (consensus rejects), so griefing/display only, no fund loss | bitcoin-terminal-exchange `74ec794` |
| F-SIDE | Python canonical line committed the order's `side`; the authoritative Rust hardcodes `side=0` | Informational | Latent (unreachable today — served views omit `side`): a future bids feature or hashing side-bearing dicts would split the consensus hash | bitcoin-terminal-exchange `5ed3dc7` |
| F-TAP | BIP341 script-path (`ext_flag=1`) sighash had no offline independent vector; `tap_sighash` didn't reject invalid sighash types (§4.3) | Informational/Low | Coverage gap (production path was on-node-checked only) + latent foot-gun | bitcoin-terminal-exchange `03365b0` |
| F-CTSIGN | `schnorr_sign`'s scalar multiply (`point_mul`) is double-and-add branching on secret bits; `point_add`/`_inv`/Python bigints are all variable-time → the sign path is not constant-time | Informational/Low | A co-located attacker on a multi-tenant host could in principle timing-extract the signing scalar. **Scoped:** `schnorr_sign`'s only callers sign **single-use ephemeral** envelope/etch reveal keys (`os.urandom(32)`) that control just a commit UTXO spent in the next tx — never a maker funds key (offers are ECDSA via the wallet). Verify path takes only public inputs, so it leaks nothing. Blast radius = grief one in-flight publish, not key/fund theft | none — accepted (see below) |
| F-INJECT | Flat `book_hash` / `cumulative_event_hash` leaf+event encoding is delimiter-separated (`\|`,`:`,`\n`) with no length prefix; `_norm` took `rune_id`/`offer_txid` as free-form `str()` with no charset check. A non-chain dict with a `\n` smuggled into `offer_txid` makes ONE order serialize as TWO → a ~zero-cost structural collision in the **flat** hash | Informational/Low | **Not reachable from chain** (parser yields `rune_id='{u32}:{u16}'` + 64-hex `offer_txid`, no delimiters), and the **Merkle `book_root` is structurally immune** (per-leaf 0x00 domain tag). Only a defense-in-depth gap if `book_hash` is ever fed non-parser dicts (GUI/API/mempool) | bitcoin-terminal-exchange `c9d790b` (`_check_canonical_fields` in `btx_orderbook.py`) |
| F-SUPPLY | The runes decoder (`btx_runes_decode.py` + Rust `runes.rs`) implemented 8/10 ord cenotaph `Flaw`s but not `SupplyOverflow`: an etching whose `premine + cap*amount` overflows u128 was classified NOT-cenotaph, where ord/ME flag it. Found by differential-fuzz vs the ord `Flaw` set (the 805-case random run never hit a near-u128 etching) | Informational/Low | Decoder feeds the activity-feed classification, so a mainnet supply-overflow etching would be mislabeled (ord burns its runes; BTX showed a valid etching). **Swap path unaffected** — swaps are edict-only (no etching). No fund loss | both decoders now compute the checked supply (Py `btx_runes_decode.py`, Rust `runes.rs`) + golden vector — pending ME re-confirm |
| F-REORG-UTXO | `BrkChain::offer_utxo` fast path is confirmed-only (`get_tx_out` `include_mempool=false`), but its cold-reindex fallback `get_raw_transaction(txid, None)` resolves from **mempool + txindex**. During a reorg re-sync an announce can re-confirm while its offer-funding sits unconfirmed in mempool → the order is admitted on unconfirmed funding | Informational/Low | Order admission becomes a function of node-local, time-varying mempool, not the confirmed chain → two honest indexers re-syncing with different mempools could diverge (breaks "pure function of chain"). Phantom order is **unfillable** (offer UTXO not confirmed-spendable) and self-heals on confirm/expiry; **no fund loss**. Narrow window, untested | brk-btx (`tx_is_confirmed` gate in `offer_utxo`) — pending cargo verify |

## Detail

**F-CSRF (High) — localhost CSRF on wallet-signing POSTs.** `btxd`'s DNS-rebinding `Host:` allowlist
passes a direct cross-origin `fetch('http://127.0.0.1:<port>/api/order/fill', {method:'POST'})` (the TCP
target is loopback, so `Host: 127.0.0.1` is allowed), and a `text/plain` body is a CORS *simple request*
that skips the preflight, so the wallet-mutating action executes even though the browser blocks reading
the response. **Fix:** an Origin allowlist on mutating POSTs — browsers attach an unforgeable `Origin`
header on cross-origin requests, so reject any POST whose `Origin` is present and not loopback (absent
Origin = a non-browser CLI client, allowed; the served same-origin GUI sends `http://127.0.0.1:<port>`).
Verified: an `Origin: http://evil.com` POST returns **403**; a loopback-Origin POST passes the guard.

**F-FILL (Medium) — batch-fill misclassification.** BTX's batch builder places offer_k at input k and
its SIGHASH_SINGLE-committed payout_k at output k; the indexer compared all spent offers against output
0. **Fix:** classify offer-at-input-`i` against `tx.output[i]`, in both Rust index passes, the Python
`book scan`, and the `btx_index.rs` reference, with a regression test asserting both batch legs FILLED
(+ a control showing the old output-0 rule mis-cancels leg 1).

**F-CARRIER (Medium) — cross-indexer extraction divergence.** The Rust "scan for MAGIC anywhere, in any
output" behavior is intentional and tested (`extract_from_script_finds_embedded_artifact_and_ignores_garbage`),
so it is authoritative; the Python reference was aligned to it (scan every output's scriptPubKey and the
envelope payload for the first MAGIC, parse from there). Both envelope parsers were confirmed panic-safe
on hostile pushdata. *Design note (not a bug):* "scan anywhere in any output" is a broad carrier surface;
tightening both impls to OP_RETURN-only + MAGIC-at-start would shrink it, but that changes the tested
production rule and was left as a decision rather than an audit change.

**F-ANNEX (Medium) — annex-hidden order splits the book.** A confirmed Taproot script-path spend's
witness is `[sig, leaf_script, control_block, annex?]`; only the leaf script is the revealed tapscript
consensus executed. Rust reads exactly that (2nd-from-last, or 3rd when an annex — last element, first
byte `0x50` — is present). Python scanned all elements, so an attacker making an ordinary Taproot spend
with a benign leaf and an annex containing `OP_FALSE OP_IF <BTX1 artifact> OP_ENDIF` gets the order into
the Python reconstruction but not the Rust served book. **Fix:** Python now mirrors
`taproot_leaf_script_bytes` (leaf-only, annex-aware); verified the honest leaf-envelope still extracts
and the annex-hidden one is ignored.

**F-BIND, F-SIDE, F-TAP** — see the table; all fixed/hardened with regression coverage, none reachable
as a principal-loss or live consensus-divergence path.

## Follow-up re-audit round (2026-05-28) — deeper passes on already-fixed surfaces

Re-attacking the taproot, parser, and determinism surfaces (skeptic's second look) confirmed the fixes
held and added coverage/consistency hardenings (no new behavior, no new High/Medium beyond F-ANNEX):
- **BIP340 full vector set** — the embedded subset was expanded to the official 0–14 (32-byte-message)
  vectors, so the selftest now enforces rejection of every negative class (`R=∞`, `r`-not-on-curve,
  `r=field-size`, `s=curve-order`, pubkey-not-`lift_x`). Verified vs the authoritative
  `bip-0340/test-vectors.csv`; vectors 15–18 (variable-length msg) are out of scope for this 32-byte
  signer. bitcoin-terminal-exchange `e3ad947`.
- **Parser totality fuzz** — a continuous std-only fuzz test (`parser_fuzz_is_total_no_panic`) over
  `parse_artifact` / `extract_from_script` / `parse_envelope_payload` (truncations, byte-flips, oversized
  `u8` length-prefixes, 50k random + MAGIC-prefixed blobs, 1 MiB oversized input). brk-btx `c4567de05`.
  The Python mirror was fuzzed with ~300k inputs (0 non-`ValueError` escapes, bounded memory).
- **Reveal dust floor** — `build_reveal` now enforces the 546-sat floor (was `<= 0` only), mirroring the
  other tx builders. bitcoin-terminal-exchange `c60b278`.

**Standing rule (the root cause of all three Medium bugs):** any Python reconstruction path MUST match
the authoritative Rust indexer's *exact* admission rules — never a superset. All three divergences
(F-FILL, F-CARRIER, F-ANNEX) were Python being more liberal than Rust.

**Non-canonical-pushdata residual — discharged (2026-05-28 determinism pass).** Given the same leaf
script, Python `parse_envelope` and Rust `parse_envelope_payload` reassemble byte-identical payloads on
non-canonical pushdata. This is now covered by the shared `btx_xcheck.py` corpus across the full
push-opcode matrix: `envelope_pushdata2_noncanonical` (0x4d), `envelope_split_two_pushes` (multi-chunk
0x4c), and `envelope_pushdata4_noncanonical` (0x4e) — each frozen as a raw tx whose admitted offer-vout
the Rust `xcheck_corpus_matches_golden` test re-derives with its own extractors and asserts identical.
Both decoders read a push by its DECLARED opcode/length (no minimal-push enforcement) and concatenate
chunks identically. The one behavioral difference — a *truncated* push (declared length > script bytes):
Rust returns the partial payload collected so far, Python raises in `CScript.raw_iter` → `None` — is
**consensus-unreachable**: a script with an over-long push fails Bitcoin script parsing and cannot appear
in a confirmed tapscript. Caveat: the Python side of the new 0x4e case is verified here; the Rust array
entry must be confirmed with `cargo test -p brk_indexer btx` (no Rust toolchain in this env).

**F-INJECT (Informational/Low) — flat-hash delimiter injection.** The leaf encoding
`{rune_id}|0|{price}|{amount}|{announce_height}|{offer_txid}:{offer_vout}\n` (and the analogous event
line) is delimiter-separated with no length prefix, and `_norm` accepted `rune_id`/`offer_txid` as
free-form strings. Demonstrated: with a `\n` smuggled into `offer_txid`, a single order R serializes to
exactly `line(P)+line(Q)` of two other orders, so `book_hash([P,Q]) == book_hash([R])` — a structural
collision at ~zero cost (not 2^128). Two qualifiers: (1) **unreachable from chain** — `parse_artifact`
yields `rune_id='{u32}:{u16}'` and a 64-hex `offer_txid`, neither of which can hold a delimiter; (2) the
Merkle **`book_root` is immune** (each leaf is `sha256(0x00‖line)`, so one leaf can't equal two — verified
`book_root([P,Q]) != book_root([R])`). **Fix:** `_check_canonical_fields` in `btx_orderbook.py` fails
closed at the single point that emits hashed bytes (`_canonical_line` + `_event_line`), asserting
`rune_id` matches `^[0-9]+:[0-9]+$` and `offer_txid` matches `^[0-9a-f]{64}$` — exactly what chain data
always satisfies and what the Rust `OpenOrderView` already guarantees by construction, so no false
positives. Regression test added to `btx_orderbook_test.py`.

**F-REORG-UTXO (Informational/Low) — offer-UTXO resolution can depend on the mempool.** Audit of the
full reorg path (`Stores::rollback_if_needed` → `rollback_btx_orders` → `btx::btx_rollback_plan`) found
the rollback itself correct: a fill-block reorg reopens FILLED→OPEN with `last_event_height` reset to
`announce_height` (so a reopened record is byte-identical to a fresh never-filled sync, and `book_hash`/
`book_root`/`cumulative_event_hash` — all pure functions of the record set — roll back exactly); an
announce-block reorg removes the order entirely (`announce_height >= bound`); the light-client follower
re-syncs to the new cumulative and never trusts a stale root. The one issue is `BrkChain::offer_utxo`
(btx.rs): the fast path `get_tx_out(.., include_mempool=false)` is confirmed-only and deterministic, but
the cold-reindex fallback `get_raw_transaction(txid, None)` consults **mempool + txindex**. In the
funding-reorg scenario, an announce can re-confirm while its offer-funding tx is reorged out and sitting
in mempool — the fallback then resolves the offer from the mempool tx and admits the order on unconfirmed
funding. Because mempool state is node-local and time-varying, two honest indexers re-syncing at
different moments could disagree, violating the "pure function of the confirmed chain" invariant. Impact
is bounded (the phantom is unfillable; no fund loss; self-heals). **Fix:** gate the fallback on a new
`brk_rpc::Client::tx_is_confirmed` (getrawtransaction verbose, `confirmations >= 1`) so `offer_utxo`
resolves only CONFIRMED creating txs — preserving the cold-reindex feature (a spent offer's funding is
always confirmed) while removing the mempool dependence.

## BIP340 Schnorr deep-dive pass (2026-05-28) — vectors + adversarial constructions + side-channel

A targeted re-audit of the dependency-free BIP340 implementation (`btx_taproot.py`), run against the
live module (not the README). Functionally **clean**; one accepted Informational/Low side-channel note
(F-CTSIGN above).

- **All 15 embedded vectors pass, including the 10 rejecting ones (v5–v14).** Instrumenting
  `schnorr_verify` to report the rejecting branch confirms each negative class hits the *intended* guard,
  not an accidental earlier one: v5/v14 → `lift_x` reject (pubkey not on curve / x ≥ field size); v6/v7 →
  `not _has_even_y(R)`; v8/v11 → `R.x != r`; **v9/v10 → `R is None` (point-at-infinity guard genuinely
  exercised, not dead code)**; v12 → `r >= P`; v13 → `s >= N`. Signing vectors reproduce the official
  signatures byte-for-byte.
- **Hand-built adversarial signatures all reject:** `s = 0`, `s = N`, `s = N+1` (s≥N guard, line 250);
  `r = P`, `r = 2²⁵⁶−1` (r≥P guard); `r = 0`; `R = ∞` (vectors 9/10); a pubkey that isn't a valid
  `lift_x`; and the 63/31-byte length-guard cases. Note `s = 0` / `r = 0` are caught by the final
  `R[0] == r` equation, not a special-case guard — spec-correct, matches the BIP340 reference (which also
  doesn't special-case them).
- **Even-y, not the obsolete QR rule.** Verify derives `R = s·G − e·P` and enforces `_has_even_y(R)`
  (line 254) — the final-BIP340 even-y convention, not the withdrawn 2018 "has_square_y / quadratic
  residue" rule. Correct.
- **Challenge tagged hash is byte-exact.** `tagged_hash` (lines 86–88) is `sha256(sha256(tag)·2 ‖ msg)`
  with the literal tag `"BIP0340/challenge"` (verify line 252, sign line 233); independently recomputed
  and matched. The `BIP0340/aux` and `BIP0340/nonce` tags are likewise correct, and the signer
  self-verifies before emitting (line 235) — fault-attack hardening.
- **Verify timing (indexer/light-client path):** non-issue. `schnorr_verify` consumes only public
  inputs (`msg`, `pubkey`, `sig`); the variable-time arithmetic leaks nothing secret.
- **Sign timing (F-CTSIGN):** `point_mul` (lines 62–69) is double-and-add conditioned on each secret
  scalar bit; `point_add` has data-dependent branches; `_inv` uses `pow` and Python bigints (both
  variable-time). The sign path is therefore **not constant-time**. Accepted rather than fixed because
  its only callers (`btx_envelope_publish.py:104`, `btx_etch.py:262`) sign single-use ephemeral
  reveal keys (default `os.urandom(32)`); the comment at `btx_envelope_publish.py:160–162` confirms the
  key exists only to spend the commit UTXO and is otherwise only in memory. **If a persistent, funded key
  is ever routed through `schnorr_sign`, this is upgraded to a real finding and should move to
  libsecp256k1.**

## Surfaces reviewed and found sound (no finding)

- **Maker price commitment / atomic settlement:** the `0x83` sig binds (offer-outpoint, price, payout,
  amount); tampering breaks it; the production Rust `verify_maker_sig` binds the maker pubkey to the
  on-chain offer UTXO, so forged orders can't enter the served book or be filled.
- **BIP340/341/342 crypto:** matches the official vectors (including SINGLE/ACP, where the reference
  library `embit` is itself wrong); the production script-path sighash independently confirmed.
- **Reorg / no-resurrection invariants:** `revert_to` / `btx_rollback_plan` / first-wins announce /
  re-announce-after-fill guards all hold.
- **btxd hardening:** static-file serving is path-traversal-safe, body cap + wallet-lock correct,
  subprocess calls are arg-lists (no shell), GET reads can't be read cross-origin (no CORS relaxation).

## Standing residual (accepted, not a finding)

btxd has no auth token — acceptable for a single-local-user tool now that **both** DNS rebinding and
cross-origin CSRF are blocked. A token would be the next step only if btxd were ever exposed beyond
loopback (it should not be). Blast radius is further bounded by the `--max-hot-balance-btc` thin-wallet
rail (see `BTX-mainnet-hardening.md`).
