# Scouting report — `petertodd/python-bitcoinlib` (Peter Todd's Bitcoin SAK)

*Ninth scouting target this 2026-06-03 cycle. Domain: foundational
pure-Python Bitcoin library.*

Date: 2026-06-03.

## Why this developer / repo

Peter Todd is a long-time Bitcoin Core contributor: author of
replace-by-fee (BIP-125), OpenTimestamps, and many influential
technical proposals. `python-bitcoinlib` is his ~10-year-old
"low-level, ground-up" Bitcoin library — Wladimir J. van der Laan
called it *"the Swiss Army Knife of the Bitcoin protocol."*

It predates many Python Bitcoin tooling efforts and is widely cited
as a reference implementation of Bitcoin primitives.

## Repository at a glance

Cloned to `Bitcoin CoreX/python-bitcoinlib-reference/`, master HEAD
2026-06-03.

```
LICENSE / README.md / setup.py / runtests.sh
bitcoin/
  ├── __init__.py             96 LOC   chain params (mainnet/testnet/signet)
  ├── base58.py              144 LOC   Base58Check
  ├── bech32.py               73 LOC   Bech32 wrapper (NO BECH32M)
  ├── segwit_addr.py         122 LOC   BIP-173 only (NO BIP-350)
  ├── bloom.py               183 LOC   Bloom filters (BIP-37, incomplete)
  ├── messages.py            531 LOC   P2P wire messages
  ├── net.py                 200 LOC   network helpers
  ├── rpc.py                 836 LOC   Bitcoin Core RPC client
  ├── signature.py            53 LOC   ECDSA signature container (NO SCHNORR)
  ├── signmessage.py          60 LOC   legacy Bitcoin signed messages
  ├── wallet.py              387 LOC   address + privkey (legacy only)
  └── core/
      ├── __init__.py        988 LOC   CTransaction / CTxIn / CTxOut / CBlock
      ├── _bignum.py         104 LOC   integer helpers
      ├── key.py             630 LOC   ECC pubkeys via OpenSSL (NO BIP-340)
      ├── script.py         1179 LOC   opcodes (NO OP_CHECKSIGADD)
      ├── scripteval.py      840 LOC   script interpreter (NO TAPSCRIPT)
      └── serialize.py       369 LOC   compact-size, ser_string, uint256
```

Total ~6,795 LOC pure-Python.

## The critical finding — this is a pre-Taproot library

`grep -rn "schnorr\|taproot\|bip340\|bip341\|BIP340\|BIP341" --include="*.py"`
returns **zero matches**.

`grep -rn "OP_CHECKSIG\|tap\|x-only\|xonly\|bech32m\|p2tr" --include="*.py"`
returns only legacy `OP_CHECKSIG` occurrences and no Taproot-era
identifiers.

Verbatim from `bitcoin/segwit_addr.py` line 45:

> ```python
> def bech32_verify_checksum(hrp, data):
>     return bech32_polymod(bech32_hrp_expand(hrp) + data) == 1
> ```

That equality `== 1` is BIP-173 bech32 only. BIP-350 bech32m, used
for Taproot addresses, checks against `BECH32M_CONST = 0x2bc830a3`.
The library does not implement it.

Similarly, `bitcoin/core/key.py` (630 LOC) is full ECDSA via OpenSSL
(`libssl-dev` required per the README). No BIP-340 Schnorr. No
x-only pubkeys. No tagged hashes.

## Why this is a divergence for BTX

BTX is **Taproot-first**:

- BTX envelope carrier uses BIP-341 commit+reveal
- BTX uses x-only Taproot internal keys throughout (`btx_taproot.py`)
- BTX addresses are bc1p... (BIP-350 bech32m)
- BTX signs everything with BIP-340 Schnorr
- BTX2 uses tagged hashes (`BTX2/order/sighash`, etc.)

python-bitcoinlib supports none of this.

## Module-by-module value to BTX TODAY

| Module | BTX-relevance |
|--------|---------------|
| `bitcoin.core` (CTransaction etc.) | Marginal — BTX has its own minimal tx struct via `btx_taproot` |
| `bitcoin.core.key` (ECDSA via OpenSSL) | None — BTX uses BIP-340 Schnorr |
| `bitcoin.core.script` (opcodes) | None — BTX uses Taproot key-path; no script eval |
| `bitcoin.core.scripteval` | None — same reason |
| `bitcoin.core.serialize` | Marginal — BTX has its own compact-size + ser_string |
| `bitcoin.base58` | Skip — BTX doesn't generate base58 addresses |
| `bitcoin.bech32` | Skip — BTX needs bech32m, not bech32 |
| `bitcoin.segwit_addr` | Skip — same reason |
| `bitcoin.wallet` | None — pre-Taproot wallet code |
| `bitcoin.signmessage` | None — legacy message signing |
| `bitcoin.messages` / `net.py` | None — BTX doesn't talk Bitcoin P2P |
| `bitcoin.rpc` | Bookmark — `brk_indexer` uses bitcoin Core RPC; could borrow patterns |
| `bitcoin.bloom` (BIP-37, "incomplete") | None |

## Could it serve as a cross-validation oracle?

For BTX's overlapping primitives (compact-size, ser_string, base58-ish
checks): yes, in principle. But there's nothing to cross-validate that
isn't already covered by Bitcoin Core's own test vectors used in BTX's
existing xtest suite (BIP-340 CSV, BIP-341 wallet vectors, BIP-374
DLEQ, etc.).

For the parts BTX actually uses (Taproot, Schnorr, bech32m, tagged
hashes): python-bitcoinlib has no implementation to compare against.

## What this tells us about the scouting cycle

This is the **fifth** "no code lands" outcome. Different reason from
the previous four:

| Scout | Reason for spec-only |
|-------|---------------------|
| `minisketch` | Operational — couldn't build (sudo deps) |
| `utreexo` | Architectural — no BTX UTXO use case |
| `pymatt` | Consensus — CCV not on mainnet |
| `HWI` | Product — no hardware-wallet user today |
| **`python-bitcoinlib`** | **Era mismatch — pre-Taproot library** |

This is the cleanest "right tool, wrong decade" outcome. The library
is well-engineered for Bitcoin **circa 2017**. BTX is Bitcoin
**circa 2026** — Taproot, Schnorr, bech32m, tagged hashes. The two
sets don't intersect on the primitives that matter.

## Verdict

`python-bitcoinlib` is the canonical pre-Taproot Python Bitcoin
library, deservedly called the SAK of Bitcoin. For BTX's
Taproot-native scope, **nothing extractable lands today**.

Trigger conditions for revisiting:

- Peter Todd publishes a Taproot update (no signal of this; the
  library appears to be in long-term maintenance mode)
- BTX adds legacy P2PKH / P2SH support (out of scope — BTX is
  Taproot-only by design)
- BTX needs Bitcoin P2P protocol support (out of scope — BTX talks
  to Bitcoin Core via RPC, not P2P)

## File index

```
Bitcoin CoreX/python-bitcoinlib-reference/    (cloned 2026-06-03)
  ├── bitcoin/                                 ~6,795 LOC pure-Python
  ├── examples/                                spend-p2sh-txout etc.
  ├── doc/                                     reference docs
  └── runtests.sh                              unittest runner

bitcoin-terminal-exchange/
  └── BTX-python-bitcoinlib-scouting-2026-06-03.md   (THIS DOC)
```

## Updated 9-scout pattern table

| Repo | Outcome | Reason |
|------|---------|--------|
| `secp256k1-zkp` | shipped (primitive) | direct primitive fit |
| `secp256kfun` | shipped (FROST) + specced (DLEQ) | primitive fit + design extraction |
| `bitcoin/bips` | shipped (BIP-374 DLEQ) | primitive port |
| `rust-miniscript` | shipped (descriptors) | found fit after deeper read |
| `sipa/minisketch` | spec only | operational |
| `mit-dci/utreexo` | spec only | architectural |
| `Merkleize/pymatt` | spec only | consensus-dependent |
| `bitcoin-core/HWI` | spec only | product-driven |
| **`petertodd/python-bitcoinlib`** | **spec only** | **era mismatch (pre-Taproot)** |

Effective extraction rate: 4/9 ≈ 44%. The deferred half now has 5
distinct reason categories — a useful taxonomy for future scouting.

## Source

Repo: <https://github.com/petertodd/python-bitcoinlib>
Author: Peter Todd and contributors
License: LGPLv3
Examined: master HEAD at clone time 2026-06-03.
Description per README: *"The Swiss Army Knife of the Bitcoin
protocol."* — Wladimir J. van der Laan
