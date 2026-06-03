# Scouting report — `bitcoin/bips bip-0388` (Salvatore Ingala — Wallet Policies)

*Fourteenth scouting target this 2026-06-03 cycle. Domain:
hardware-wallet-friendly representation of descriptors.*

Date: 2026-06-03.

## Why this BIP / repo

BIP-388 by Salvatore Ingala (@bigspider, also author of pymatt
scouted earlier this cycle) defines **wallet policies** — a compact
"template + keys" representation of descriptors specifically
designed for hardware-wallet display constraints. Used by Ledger's
Bitcoin app since 2022.

Status: `Complete`, Version 1.1.0, BSD-2-Clause.

## What's defined

A wallet policy is a tuple `(descriptor_template, keys_info)` where:

- `descriptor_template` is a descriptor with `@N` placeholders
  instead of inline keys. For example:
  `tr(@0/<0;1>/*)`
- `keys_info` is a list of strings, one per `@N` slot. For example:
  `["[fingerprint/86'/0'/0']xpub..."]`

`to_descriptor()` substitutes the keys back in; `from_descriptor()`
extracts the template + keys from a "reasonable" descriptor.

Reference impl `bip-0388/wallet_policies.py` (202 LOC, pure-Python,
in the bitcoin/bips repo).

## BTX-fit analysis

BTX's descriptors are *the simplest possible form*:

```
tr(<32-byte x-only pubkey hex>)
```

No key origin info `[fingerprint/path]`. No xpub. No derivation
suffix `/0/*`. No musig. No script tree.

What happens if BTX runs its descriptors through BIP-388
`from_descriptor()`?

```
descriptor: tr(d6889cb081036e0faefa3a35157ad71086b123b2b144b649798b494c300a961d)
becomes:
  descriptor_template: tr(@0)
  keys_info:           ["d6889cb081036e0faefa3a35157ad71086b123b2b144b649798b494c300a961d"]
```

**Zero compression** — the only key reference is a single literal
x-only, and the template adds 3 characters (`@0`) for the slot
indirection.

The compression benefit of wallet policies materialises only when:

1. Descriptors have **multiple repeated keys** (e.g.,
   `multi(2, key1, key2, key1)` → `multi(2, @0, @1, @0)`)
2. Descriptors include **complex derivation paths** (e.g.,
   `tr([fp/86'/0'/0']xpub.../<0;1>/*)`)
3. Descriptors include **MuSig2 aggregations** (e.g.,
   `tr(musig(key1, key2)/<0;1>/*)`)

BTX has none of these today. BTX2 BATCH_ANNOUNCE may use MuSig2
internally but the descriptor on-chain is the aggregated x-only
output key, not the MuSig2 composition.

## Module-by-module value to BTX

| Module / concept | BTX-relevance today |
|------------------|---------------------|
| `WalletPolicy.to_descriptor` | None — BTX descriptors have no template slots to fill |
| `WalletPolicy.from_descriptor` | None — round-trip is trivial for BTX's bare form |
| `@N` slot syntax | None — BTX has 1 key per descriptor |
| Multipath `/<0;1>/*` syntax | None — BTX uses no derivation |
| `musig(...)` expansion | Bookmark — if BTX exposes MuSig2-aggregated descriptors |
| Hardware-wallet display considerations | Bookmark — for hardware-wallet maker desks |

## Verdict

`bip-0388` is the canonical hardware-wallet-friendly descriptor
representation, well-engineered for Ledger's screen and RAM
constraints. For BTX's `tr(<x-only>)` descriptors, **no code lands**:
the compression benefit is zero because BTX descriptors have no
repeated keys, no xpubs, no derivation paths, and no musig
sub-expressions.

This is the **scope-mismatch** outcome: BTX's descriptors are simpler
than the minimum complexity tier where BIP-388 adds value. Different
from era-mismatch (python-bitcoinlib is wrong era) and
architectural-protocol (electrs is wrong stack) — here the tool is
contemporaneous and architecturally compatible, just unnecessary for
BTX's current descriptor complexity.

### Defer reason category — refinement

Previously I called this the "product-timing" category (alongside
ChillDKG). On closer look, BIP-388 is subtly different:

- **product-timing** (ChillDKG): right tool, BTX wants it later when
  product has more users.
- **scope-mismatch** (BIP-388): right tool, BTX descriptors are
  simpler than the minimum complexity where the tool helps. May
  never become relevant if BTX stays single-key-per-order.

Splitting these gives **8 defer-reason categories** total in this
cycle's taxonomy.

## Trigger conditions for revisiting

| Trigger | Justification |
|---------|---------------|
| BTX adds xpub-derived maker addresses (`tr([fp/path]xpub/<0;1>/*)`) | Hardware wallets need wallet-policy display |
| BTX exposes MuSig2-aggregated descriptors externally | `musig()` template gives hardware wallets clean display |
| BTX integrates with Ledger Bitcoin app | Ledger uses BIP-388 as its descriptor exchange format |

## Updated pattern across 14 scouts

| # | Repo / BIP | Outcome | Reason category |
|---|------------|---------|------------------|
| 1 | secp256k1-zkp | shipped | — |
| 2 | secp256kfun | shipped + specced | — |
| 3 | bitcoin/bips (BIP-374 DLEQ) | shipped | — |
| 4 | rust-miniscript | shipped | — |
| 5 | sipa/minisketch | spec | operational |
| 6 | mit-dci/utreexo | spec | architectural-no-use |
| 7 | Merkleize/pymatt | spec | consensus |
| 8 | bitcoin-core/HWI | spec | product |
| 9 | petertodd/python-bitcoinlib | spec | era |
| 10 | darosior/python-bip380 | shipped xtest | — |
| 11 | BlockstreamResearch/bip-frost-dkg | spec | product-timing |
| 12 | romanz/electrs | spec | architectural-protocol |
| 13 | bitcoin/bips (BIP-322) | shipped | — |
| 14 | **bitcoin/bips (BIP-388)** | **spec** | **scope-mismatch (NEW)** |

Extraction rate: 6/14 ≈ 43%.

Now 8 distinct defer reason categories. Each subsequent scout
either ships code or sharpens the taxonomy. Both are useful
artifacts.

## Sibling BIPs noticed (not separately scouted)

While locating BIP-388 in the bips tree, I noticed BIPs in the same
descriptor family are also present:

```
bip-0380.mediawiki  (descriptors core)              — covered by python-bip380 scout
bip-0381.mediawiki  (key expressions)               — covered
bip-0382.mediawiki  (wsh)                            — out of scope (no script wallet)
bip-0383.mediawiki  (multi/sortedmulti)             — out of scope
bip-0384.mediawiki  (combo)                          — out of scope
bip-0385.mediawiki  (raw/addr)                       — out of scope
bip-0386.mediawiki  (tr() descriptors)              — covered (this is BTX's form)
bip-0387.mediawiki  (tapscript multi_a)             — out of scope (no script-path)
bip-0388.mediawiki  (wallet policies)               — THIS SCOUT
bip-0389.mediawiki  (multipath /<0;1>)              — bookmark (used by python-bip380 internally)
```

BIP-389 (multipath `<M;N>` derivation) might be a useful future
scout for BTX if BTX adds maker-address derivation, but again
that's a product feature BTX doesn't have today.

## Files

```
Bitcoin CoreX/bitcoin-bips-reference/
  └── bip-0388/wallet_policies.py    202 LOC reference impl

bitcoin-terminal-exchange/
  └── BTX-BIP388-scouting-2026-06-03.md     (THIS DOC, no code lands)
```

## Source

BIP: <https://github.com/bitcoin/bips/blob/master/bip-0388.mediawiki>
Reference: `bip-0388/wallet_policies.py` in the same repo
Author: Salvatore Ingala (@bigspider)
License: BSD-2-Clause
Examined: master HEAD of bitcoin/bips clone, 2026-06-03.
Production reference: Ledger Bitcoin app (since 2022).
