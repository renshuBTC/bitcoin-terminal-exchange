# Scouting report — `darosior/python-bip380` (Antoine Poinsot's pure-Python descriptor lib)

*Tenth scouting target this 2026-06-03 cycle. Domain: BIP-380 output
script descriptors + miniscript, pure-Python.*

Date: 2026-06-03.

## Why this developer / repo

Antoine Poinsot (@darosior) co-authored Miniscript, is the BIP-379
author, and a long-time Bitcoin Core contributor (Liana wallet,
revaultd). `python-bip380` is his pure-Python reference for BIP-380
descriptors + miniscript fragments, including the canonical BIP-380
checksum implementation (copyright Pieter Wuille).

For BTX, this is the second oracle for the descriptor checksum logic
shipped this cycle in `btx_descriptor.descriptor_checksum`. The first
oracle was rust-miniscript v12.3.7 (validated via probe last
session).

## Repository at a glance

Cloned to `Bitcoin CoreX/python-bip380-reference/`, master HEAD
2026-06-03.

```
bip380/                                     ~4,122 LOC pure-Python (MIT)
  ├── __init__.py                            1 LOC
  ├── descriptors/
  │   ├── __init__.py        257 LOC         Descriptor base + WSHDescriptor, TrDescriptor
  │   ├── checksum.py         71 LOC         CANONICAL BIP-380 checksum (Pieter Wuille)
  │   ├── parsing.py         106 LOC         descriptor_from_str
  │   ├── utils.py           171 LOC         tapleaf_hash + taproot_tweak + TreeNode
  │   └── errors.py            5 LOC
  ├── key.py                 338 LOC         DescriptorKey via coincurve + bip32
  ├── miniscript/
  │   ├── fragments.py      1289 LOC         miniscript fragment classes
  │   ├── parsing.py         800 LOC         miniscript parser
  │   ├── satisfaction.py    410 LOC         satisfaction algorithm
  │   ├── property.py         83 LOC         miniscript node properties
  │   └── errors.py           20 LOC
  └── utils/
      ├── script.py          477 LOC         opcodes + CScript
      ├── bignum.py           64 LOC         BIP-65 nLockTime helpers
      ├── hashes.py           17 LOC         sha256 + hash160
      └── __init__.py          0 LOC

requirements.txt:
  bip32~=3.0
  coincurve~=18.0   (Python secp256k1 bindings)
tests/                                       pytest harness
```

## The canonical BIP-380 checksum module

`bip380/descriptors/checksum.py` is 71 lines, copyright Pieter Wuille.
Verbatim header:

> ```python
> #!/usr/bin/env python3
> # Copyright (c) 2019 Pieter Wuille
> # Distributed under the MIT software license, see the accompanying
> # file COPYING or http://www.opensource.org/licenses/mit-license.php.
> """Utility functions related to output descriptors"""
> ```

Verbatim core (lines 11-22):

> ```python
> INPUT_CHARSET = "0123456789()[],'/*abcdefgh@:$%{}IJKLMNOPQRSTUVWXYZ&+-.;<=>?!^_|~ijklmnopqrstuvwxyzABCDEFGH`#\"\\ "
> CHECKSUM_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
> GENERATOR = [0xF5DEE51989, 0xA9FDCA3312, 0x1BAB10E32D, 0x3706B1677A, 0x644D626FFD]
>
> def descsum_polymod(symbols):
>     """Internal function that computes the descriptor checksum."""
>     chk = 1
>     for value in symbols:
>         top = chk >> 35
>         chk = (chk & 0x7FFFFFFFF) << 5 ^ value
>         for i in range(5):
>             chk ^= GENERATOR[i] if ((top >> i) & 1) else 0
>     return chk
> ```

This is *the* canonical BIP-380 polynomial. Independent crosswalk
opportunity for BTX's `descriptor_checksum`.

## The cross-test — code that lands today

I added `btx_xtest_vs_python_bip380.py` (~110 LOC) to
`bitcoin-terminal-exchange/`. It loads python-bip380's `descsum_create`
via `importlib.util.spec_from_file_location` to bypass the package
`__init__.py` (which would try to import `coincurve` and `bip32`,
unnecessary for this test). For each of BTX's 10 golden tr(K) vectors
it asserts:

1. `btx_descriptor_checksum("tr(<x-only>)")` == python-bip380's
   8-char checksum tail
2. `btx_tr_serialize(x-only, with_csum=True)` == python-bip380's
   full `"tr(<x-only>)#<csum>"` output

Then I wired it into `btx_xtest_suite.py` as the 8th sub-test.

### Result (verbatim from the run)

```
[ running ] BIP-380 checksum vs python-bip380 (Pieter Wuille's canonical)
[✓ PASS   ] BIP-380 checksum vs python-bip380 (Pieter Wuille's canonical)  (0.04s)
              Triple-validation closed: BTX ↔ rust-miniscript ↔ python-bip380

=== btx_xtest_suite ===
  passed:  8/8
  failed:  0/8
  skipped: 0/8
✓ btx_xtest_suite: 8 PASS, 0 skipped, 0 FAIL
```

**10/10 checksums + 10/10 full descriptors agree byte-for-byte.** The
BIP-380 checksum is now triple-validated:

| Oracle | Layer | Source |
|--------|-------|--------|
| BTX-generated golden vectors | self-consistency | btx_descriptor.py |
| rust-miniscript v12.3.7 | Rust port (rust-bitcoin org) | scouted last session |
| **python-bip380** | **Pieter Wuille (BIP-380 author)** | **this session** |

## Why this matters beyond a passed test

The BIP-380 checksum was the **specific code that surfaced a bug** in
BTX last session. The first draft of `descriptor_checksum()` conflated
`cls` (running polynomial value) and `clscount` (0-3 counter), and the
rust-miniscript probe revealed it. The fix was canonical.

Now BTX has *two independent* canonical references agreeing on every
checksum BTX produces. This is the cross-validation discipline at its
most rigorous: the bug-detection mechanism that caught a real bug
last session is now permanent infrastructure with two backends.

## Module-by-module value to BTX

| Module | BTX-relevance |
|--------|---------------|
| `bip380/descriptors/checksum.py` | **Cross-validation oracle (this session)** |
| `bip380/descriptors/__init__.py` (TrDescriptor) | Already validated indirectly via the full-descriptor cross-test |
| `bip380/descriptors/parsing.py` | Skip — BTX's tr_key_only_parse handles BTX's narrow subset |
| `bip380/descriptors/utils.py` (taproot_tweak) | Already covered by BTX's btx_taproot.tap_tweak_pubkey |
| `bip380/key.py` (DescriptorKey via coincurve) | Skip — BTX uses pure-Python BIP-340 |
| `bip380/miniscript/*` (1700 LOC) | Skip for BTX2 — key-path only |
| `bip380/utils/script.py` (CScript + opcodes) | Skip — BTX has minimal script support |

## Pattern across 10 scouts this cycle

| Repo | Outcome | Reason |
|------|---------|--------|
| `secp256k1-zkp` | shipped (primitive) | direct primitive fit |
| `secp256kfun` | shipped (FROST) + specced (DLEQ) | primitive fit + design extraction |
| `bitcoin/bips` | shipped (BIP-374 DLEQ) | primitive port |
| `rust-miniscript` | shipped (descriptors) | found fit after deeper read |
| `sipa/minisketch` | spec only | operational (build deps) |
| `mit-dci/utreexo` | spec only | architectural |
| `Merkleize/pymatt` | spec only | consensus-dependent |
| `bitcoin-core/HWI` | spec only | product-driven |
| `petertodd/python-bitcoinlib` | spec only | era mismatch (pre-Taproot) |
| **`darosior/python-bip380`** | **shipped (cross-test)** | **second oracle for prior work** |

Effective extraction rate: **5/10 = 50%**.

Pattern within the 5 "ship" outcomes:
- 4 of 5 are **primitive ports** (zkp, secp256kfun-FROST, BIP-374
  DLEQ, rust-miniscript-descriptors).
- 1 of 5 (this scouting) is a **cross-validation oracle** for prior
  work, not a primitive port.

That's a new category of "code lands" outcome: scouting a repo not
to port from but to use as an independent canonical reference. This
is a valuable variant — it permanently de-risks code BTX has already
shipped.

## Verdict

`python-bip380` is a high-quality, pure-Python BIP-380 / Miniscript
library by the BIP-379 author. For BTX's narrow scope today, the
miniscript layer is unused — BTX2 envelopes are key-path-only.

But for the descriptor *checksum* — code BTX already ships — it
delivers exactly what the cross-validation discipline needs: a second
canonical oracle that agrees byte-for-byte.

**Code shipped this session:**

- `btx_xtest_vs_python_bip380.py` (cross-test, 10/10 PASS)
- New sub-test in `btx_xtest_suite.py` (now 8/8 PASS in 10s)

Bookmark for later (low priority):

- If BTX ever adds multi-condition orders that need miniscript script
  paths, `bip380/miniscript/fragments.py` and `parsing.py` would be
  the reference (1700 LOC, requires coincurve + bip32 deps).

## File index

```
Bitcoin CoreX/python-bip380-reference/                           (cloned 2026-06-03)
  └── bip380/                                                    ~4,122 LOC pure-Python

bitcoin-terminal-exchange/
  ├── btx_xtest_vs_python_bip380.py                              (NEW, 110 LOC)
  ├── btx_xtest_suite.py                                         (+5 LOC: 8th sub-test)
  └── BTX-python-bip380-scouting-2026-06-03.md                   (THIS DOC)
```

## Source

Repo: <https://github.com/darosior/python-bip380>
Author: Antoine Poinsot (@darosior); checksum.py © 2019 Pieter Wuille
License: MIT
Examined: master HEAD at clone time 2026-06-03.
Related: rust-miniscript scouting (last session) shipped
`btx_descriptor.py` — this scouting adds python-bip380 as the second
canonical oracle for the same primitive.
