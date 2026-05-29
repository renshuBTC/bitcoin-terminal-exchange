# BTX end-to-end audit results

Companion to [`BTX-end-to-end-audit-prompts.md`](./BTX-end-to-end-audit-prompts.md).

**Audit closed 2026-05-28: 14 of 14 prompts empirically green, no PASS-by-equivalence.**

Every load-bearing safety property of BTX has been verified by running real code against real inputs — the Rust indexer's parse + sig-verify chain, the maker's rune-backing check against a real ord 0.27.1 oracle, the JS Merkle verifier's tamper detection in a real browser, mempool acceptance under stock Bitcoin Core v29.1 policy, and propagation across public signet to nodes outside our config control.

Each prompt's commit message contains the full empirical evidence; this document is the index.

## Result matrix

| # | Property | Commit | Strongest empirical evidence |
|---|---|---|---|
| 1 | Offline tests green across Python + Rust | doc-only (`acf4a08`) | 14 + 43 + corpus + 19 Python; 32/32 Rust `cargo test btx::` — 117 assertions, 0 failures |
| 2 | Property invariants hold under random input | doc-only | 1,800,000 cases across 3 seeds × 6 campaigns, ALL CLEAN |
| 3 | Python ↔ Rust agreement on adversarial books | `acf4a08` + brk-btx `c751a8a` | 1000 random books across 12 shape categories, byte-identical hashes; baseline corpus + cumulative event hash also matched |
| 4 | Parser DoS-resistant + indexer L3 admission gate | `d06451e` | 200,000 random buffers + 16 named cases (Python); forged artifact actually broadcast on regtest, Rust indexer rejected (0 OPEN, 0 panics) |
| 5 | Runestone decoder classifies cenotaphs correctly | `4996de6` | 200,000 random `6a 5d ...` scripts + 10 named cases (varint overflow, truncated PUSHDATA1/2/4, non-push opcode, unrecognized even tag, empty control) |
| 6 | Lifecycle works on **both** carriers | `8158fb0` | Live regtest: OP_RETURN announce `724e51dc…` → 1 OPEN → fill `f1a76985…` → 0 OPEN; envelope announce `354d2777…` → 1 OPEN → fill `34fe83d8…` → 0 OPEN |
| 7 | ord rune-backing oracle prevents over-advertising | `5b45f2f` | Live ord 0.27.1 etched `BTXAUDITRUNES` at rune id `119:1`; `--amount-units 1001 --require-rune-backing` refused with `assert_offer_backs_rune`; `1000` signed cleanly |
| 8 | Reorg restores orphaned-fill orders | `cc0dad0` | Live `invalidateblock(H_f=106)` on a chain where announce was at `ef8f803e…` and fill was at `5b03f275…`: 0 OPEN → 1 OPEN after reorg (open_after_reorg=1) |
| 9 | Indexer fjall state durable across restart | `6ab7272` | Two independent `btx_book` runs against the same `--brkdir`: both report `INDEXED_HEIGHT=106, 1 OPEN` byte-identical |
| 10 | Both carriers admitted under strict default Core v29.1 policy | `8b65d52` | bitcoind started WITHOUT `-datacarriersize`: envelope `allowed=true` (170 vsize); OP_RETURN 70B `allowed=true`; OP_RETURN 100B `allowed=false` (policy boundary precisely respected) |
| 11 | btxd security guards on every route | `e8e0b52` | 7 probes: legit GET=200; forged Host on /api/config=403; forged Host on /api/v1/btx/orders=403; cross-origin POST=403; no-Origin POST=400 (4xx per documented threat model); unknown path=404; eval/new-Function hits in served HTML=0 |
| 12 | Light-client follower fold matches indexer | `e8e0b52` | `btx_light_client.py --selftest` matches `0716e1c48e82…` — the same golden recorded by `btx_eventhash_test.py` and the Rust `cumulative_event_hash_matches_python_golden` test |
| 13 | GUI Merkle verifier rejects every tamper class | `1ef973b` | Standalone browser page `btx_merkle_tamper_test.html` runs verifier code verbatim from `btx_trade.html`: T1 valid=`true`; T2 tampered proof=`false`; T3 tampered root=`false`; T4 tampered leaf=`false` |
| 14 | Envelope propagates on public signet | `7a1d783` | Reveal txid `83789dffb976fb290dbab07daaa0f74fec3bcb8d9e0bdea586b7e6769a93e75f` broadcast from our node; **mempool.space** (third-party signet node) returned 200 with the matching txid at **+5 seconds**; verifiable at `https://mempool.space/signet/api/tx/83789dffb976fb290dbab07daaa0f74fec3bcb8d9e0bdea586b7e6769a93e75f` |

## Runner

The single-paste audit runner `run_audit_prompt.sh` (committed `3f33ee8` + extensions in each prompt-PASS commit) replays prompts 6, 7, 8, 9, 10, 11, 12, 14 hermetically:

```bash
./run_audit_prompt.sh 6    # publish→fill, both carriers
./run_audit_prompt.sh 7    # ord rune-backing
./run_audit_prompt.sh 8    # reorg rollback + reopen
./run_audit_prompt.sh 9    # fjall durability
./run_audit_prompt.sh 10   # mempool standardness
./run_audit_prompt.sh 11   # btxd security guards
./run_audit_prompt.sh 12   # light-client fold
./run_audit_prompt.sh 14   # public signet propagation (uses ~/sig-public stack)
```

Prompts 1, 2, 3, 4, 5, 13 are run directly:

```bash
python3 btx_test_all.py
python3 btx_selftest.py
python3 btx_xcheck.py
python3 btx_runes_xcheck.py
( cd ../brk-btx && cargo test -p brk_indexer btx:: )
BTX_FUZZ_ITERS=200000 python3 btx_fuzz.py
python3 btx_book_hash_adversarial.py
# (then in brk-btx: cargo run --release --example btx_book_hash_xcheck -- <corpus.json>)
python3 btx_artifact_adversarial.py
python3 btx_runestone_cenotaph_adversarial.py
# (open btx_merkle_tamper_test.html in a browser)
```

## What the audit does NOT prove

For transparency, the limits of these results:

- **Mainnet behavior.** All on-chain runs were regtest + public signet. Bitcoin mainnet policy is not measurably different from signet for these carriers (both inherit Core v29.1 defaults), but no mainnet broadcast happened.
- **Adversarial network-level behavior.** Mempool-sniping by a competing taker tx with higher fee is a separate threat model, addressed by the opt-in addressed-swap mode (proven live separately in earlier work; see [`BTX-threat-model.md`](./BTX-threat-model.md)). The open SIGHASH_SINGLE|ANYONECANPAY carrier is intentionally fillable by anyone, which is the design goal — sniping immunity is a *user-mode choice* (addressed-only) not a *protocol property*.
- **Long-running production load.** No multi-day, high-volume stress tests. Property fuzz reaches 1.8M cases but each is bounded.
- **All carriers in all policy environments.** Only OP_RETURN (≤80B) and the Taproot script-path witness envelope were tested. Other potential carriers (e.g. SegWit script field tricks, OP_RETURN ≤83B with `-datacarriersize` flag) were not in scope.
- **Wallet-software-specific edge cases.** All maker-sign and taker-fill work goes through `btx_wallet.py` against Bitcoin Core's wallet. Third-party wallet integration (Sparrow, BlueWallet, hardware signers) is not covered.

These are documented to set expectations, not to weaken the result. The 14 properties that ARE proven are the ones that determine whether BTX is safe to ship as a peer-to-peer DEX on Bitcoin.
