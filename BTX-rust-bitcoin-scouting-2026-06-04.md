# Scouting report — `rust-bitcoin/rust-bitcoin`

*Twentieth scout. Domain: cross-language BIP-341 Taproot
implementation-independence (rust-bitcoin Rust ↔ BTX pure-Python).*

Date: 2026-06-04.

## Why this repo

`rust-bitcoin/rust-bitcoin` is the de-facto Rust Bitcoin types library.
It's used downstream by:
- Sparrow Wallet
- BDK (bitcoindevkit)
- electrs (block explorer backend)
- LDK (Lightning Dev Kit)
- BTX's own brk-btx indexer (transitively)

Scout 19 closed BIP-340 Schnorr to three-language saturation (Py + C
+ JS). BIP-341 Taproot had only **one** oracle (canonical wallet-
test-vectors.json). rust-bitcoin's `bitcoin::taproot` module
implements tap_tweak from scratch on top of secp256k1 (the C library)
and is the most heavily-used Rust BIP-341 implementation in
production. Cross-testing BTX against it adds a second BIP-341 oracle
in a third language.

The original plan for scout 20 was BIP-322 message signing — but
rust-bitcoin doesn't have BIP-322 (only the legacy BIP-137
`sign_message.rs`). Pivoted to BIP-341 which is genuinely under-
validated.

## Strategic verdict

| Surface                  | Verdict                                                                                       |
| ------------------------ | --------------------------------------------------------------------------------------------- |
| BIP-341 Taproot tweak    | **SHIPPED** — second BIP-341 oracle via `xtest_taproot_probe/` Rust binary                    |
| BIP-340 Schnorr          | DEFER — already 6 oracles incl. 2 implementation-independence; saturated                       |
| BIP-137 sign_message     | DEFER — legacy "Bitcoin Signed Message" format; BTX uses BIP-322                              |
| BIP-322 message signing  | NOT PRESENT — rust-bitcoin doesn't implement BIP-322 yet                                       |
| Bitcoin Script + sighash | DEFER — BTX validates on-chain via Bitcoin Core node, not via library                          |
| Address types            | DEFER — BTX's bech32m is already cross-tested via BIP-341 canonical vectors                    |

## Cross-test shipped this session

- `xtest_taproot_probe/Cargo.toml` + `src/main.rs` (~40 LOC of Rust)
  — small stdin/stdout bridge: reads `<internal_xonly_hex>
  [merkle_root_hex]` records, emits `<output_xonly_hex>
  <parity_bool> <tap_tweak_hash_hex>`. Build with `cargo build
  --release`.
- `btx_xtest_vs_rust_bitcoin_taproot.py` (~210 LOC) — auto-detects
  the probe binary at the build path or `/tmp/rb_target/`, batches
  random + canonical inputs in one subprocess invocation, compares
  to BTX byte-for-byte.
- Wired as 17th sub-test in `btx_xtest_suite.py`.

### Results

**A. Canonical BIP-341 `scriptPubKey` section (7 vectors):**
- BTX `taproot_tweak_pubkey(internal, merkle_root)` agrees with the
  spec's `intermediary.tweakedPubkey` byte-for-byte for all 7
  vectors.
- rust-bitcoin's `internal.tap_tweak(secp, merkle_root)` also
  agrees with the spec for all 7.
- BTX and rust-bitcoin produce identical output.

**B. 50 random `(internal_xonly, merkle_root)` round-trips:**
- Half key-path-only (merkle_root = empty), half script-path
  (random 32-byte merkle_root).
- BTX and rust-bitcoin agree on:
  - Tweaked output x-only key (32 bytes)
  - Output key parity (odd/even)
- 50/50 PASS.

Total: **7/7 + 50/50 = 57/57 PASS** byte-for-byte cross-language.

### What this rules out

Same class of bugs scout 18-19 ruled out for BIP-340: a hidden
algorithmic quirk shared between BTX and the reference Python
pseudocode that real production tools handle differently. rust-
bitcoin's tweak path is a from-scratch Rust implementation used by
Sparrow, BDK, and LDK — if BTX matches it on 50 arbitrary inputs,
BTX matches what every major Rust Bitcoin tool does.

## BIP-341 Taproot oracle count: 2

1. Canonical `bitcoin/bips` `wallet-test-vectors.json`
2. **`rust-bitcoin::taproot`** ← this scout (implementation
   independence, third language)

BIP-322 message signing oracle count remains at 1 (canonical only).
That open slot is bookmarked.

## Suite expansion this scout

- Pre-scout: 16 sub-tests
- Post-scout: **17 sub-tests** (17/17 green on this runner)

## Notable absence

`rust-bitcoin` master has no BIP-322 module. There's an open issue
tracking the addition; meanwhile production users wanting BIP-322
verification on the Rust side either use `bdk_wallet` (which has a
partial impl) or build it on top of rust-bitcoin's primitives.

This makes BIP-322 the cleanest remaining open slot for BTX's
cross-validation suite. Candidate scouts for the next BIP-322 oracle:
- `bitcoin-s` (Scala) — has BIP-322 verification, Nadav Kohen
- `BlueWallet/BlueWallet` (JS) — has a partial BIP-322 impl
- Build it on top of rust-bitcoin's primitives ourselves

## Setup notes for re-running

```
# In the repo root
cd xtest_taproot_probe
cargo build --release         # produces target/release/rb_taproot_probe
cd ..
python3 btx_xtest_vs_rust_bitcoin_taproot.py
```

The probe is a tiny build (~30s on a warm Rust install). The
binary is platform-specific and is gitignored.

## Cross-links

[[project-btx-scure-btc-signer-scout-2026-06-04]] — scout 19 (BIP-340
third-language closure).
[[project-btx-python-bitcointx-scout-2026-06-04]] — scout 18 (BIP-340
libsecp256k1).
[[project-btx-scouting-cycle-2026-06-03]] — the prior 15-scout cycle.

## Files

- `bitcoin-terminal-exchange/xtest_taproot_probe/Cargo.toml` (NEW)
- `bitcoin-terminal-exchange/xtest_taproot_probe/src/main.rs` (NEW, ~40 LOC)
- `bitcoin-terminal-exchange/btx_xtest_vs_rust_bitcoin_taproot.py` (NEW, ~210 LOC)
- `bitcoin-terminal-exchange/btx_xtest_suite.py` (+5 LOC, 17th sub-test)
- `bitcoin-terminal-exchange/BTX-rust-bitcoin-scouting-2026-06-04.md` (THIS DOC)

## Source

Repo: <https://github.com/rust-bitcoin/rust-bitcoin>
Crate examined: `bitcoin = "0.31"`
License: CC0-1.0
Examined: master HEAD at clone time 2026-06-04.
