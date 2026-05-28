# BTX vs. Light Pools — how to be the most Bitcoin-native L1 DEX

*Working design memo. Grounds BTX's direction in Casey Rodarmor's own writing (the creator of
Ordinals and Runes) and in the ord codebase. Goal: identify where BTX is already more
Bitcoin-native than the state of the art, and a concrete backlog to push further.*

Date: 2026-05-27. Sources are quoted verbatim and cited inline.

---

## 1. The source material (verbatim)

### 1.1 Casey's criteria for a good Bitcoin protocol (from the Runes announcement)

From [Runes, 2023-09-25](https://rodarmor.com/blog/runes/), Casey lists the axes on which token
protocols differ:

> - Complexity: How complex is the protocol? Is it easy to implement? Is it easy to adopt?
> - User experience: … protocols that rely on off-chain data have a lighter on-chain footprint, but
>   introduce a great deal of complexity, and require users to either run their own servers, or
>   discover and interact with existing servers.
> - State model: Protocols that are UTXO-based fit more naturally into Bitcoin and promote UTXO set
>   minimization by avoiding the creation of "junk" UTXOs.
> - Native token: Protocols with a native token which is required for protocol operations are
>   cumbersome, extractive, and naturally less widely adopted.

And his closing self-assessment of Runes:

> "It's about as simple as possible, does not rely on off-chain data, does not have a native token,
> and fits nicely into Bitcoin's native UTXO model."

These four axes — **simplicity, no off-chain dependency, UTXO-native state, no native token** — are
the rubric the rest of this memo scores BTX against. They are Casey's, not ours, which is what
makes them useful: they are the design taste of the person who built the asset layer BTX rides on.

### 1.2 Casey's own DEX design — "Light Pools"

From [Light Pools, 2024-04-12](https://rodarmor.com/blog/light-pools/):

> "However, these assets still suffer from a lack of decentralized trading venues."

> "Bitcoin lacks the Turing-complete smart contracts necessary for implementing AMMs."

> "The idea behind light pools is simple. Users who wish to offer swaps … run nodes which quote
> prices for swaps. These quotes are signed messages, gossiped between other light pool nodes.
> Quotes must include BIP-322 signatures of the UTXOs that contains the asset offered in trade.
> Requiring signed quotes eliminates spam, since quotes can be rate-limited on a per-UTXO basis.
> Additionally, when UTXOs are spent, corresponding offers can be dropped."

> "When a market taker wants to accept the quote … they use the information in the quote to
> construct a PSBT which includes their signatures, and broadcast it … The maker receives this
> message, possibly asyncronously, countersigns, and broadcasts it to the Bitcoin network to be
> mined."

> "These PSBTs and transactions are not vulnerable to mempool sniping, since signatures commit to
> all inputs and outputs."

> "Someone will need to write an implementation of the gossip network, quote message format, and
> PSBT construction and finalization."

> "Prices can update in real time, between blocks, without any on-chain activity."

---

## 2. The central thesis

**BTX is a strictly more Bitcoin-native point in the design space than Light Pools, because it
applies Casey's own Runes rubric to the *order book*, which Light Pools does not.**

Light Pools settles swaps on-chain but keeps the **order book off-chain** — a gossip network of
BIP-322-signed quotes. By Casey's own Runes criteria, that is the weak axis: "protocols that rely on
off-chain data … introduce a great deal of complexity, and require users to either run their own
servers, or discover and interact with existing servers." Light Pools needs a brand-new P2P layer
("the gossip network, quote message format") that has to be built, secured, and bootstrapped.

BTX makes the opposite choice: the order is a ~207-byte **BTX artifact published on-chain** (OP_RETURN
or a Taproot witness envelope), and the book is **reconstructed from the chain by an indexer**. The
consequences map directly onto Casey's rubric:

| Casey's axis | Light Pools | BTX |
|---|---|---|
| No off-chain data | ✗ order book lives on a gossip network | ✓ order book is on-chain, indexer-reconstructed |
| Order propagation | needs a bespoke gossip network | ✓ free — rides Bitcoin's own block/mempool relay |
| No native token | ✓ | ✓ (counter-asset is an issuer's Rune stablecoin, not a BTX token) |
| UTXO-native state | ✓ (PSBT swaps) | ✓ (offer is a UTXO; fill spends it; OP_RETURN is provably unspendable, no UTXO bloat) |
| Simplicity | medium — must build gossip + quote format + PSBT finalize | medium — no gossip layer at all, but needs an indexer |
| Maker liveness | maker must be online to **countersign** each fill | ✓ maker pre-signs once (SIGHASH_SINGLE\|ACP); can be fully offline |
| Mempool sniping | ✓ immune — sigs commit to all inputs/outputs | ⚠ open question — see §4.1 |
| Real-time price updates | ✓ free, between blocks | ✗ each new price is a new on-chain artifact (the cost of nothing-offchain) |

Two genuine BTX wins worth stating loudly:

1. **No gossip network to build.** Casey explicitly flags that Light Pools requires someone to
   implement "the gossip network, quote message format, and PSBT construction and finalization."
   BTX deletes the entire first half of that sentence: Bitcoin's existing relay *is* the gossip
   network, and the blockchain *is* the persistence layer. Less to build, nothing to bootstrap,
   no liveness assumption on a side network.

2. **Non-interactive open orders.** In Light Pools the maker must be online to countersign every
   fill. BTX's pre-signed `SIGHASH_SINGLE|ANYONECANPAY` offer lets any taker fill at any time with
   the maker offline. That is both more decentralized (no maker-liveness requirement) and better UX.

The honest cost of BTX's position is in the last two rows: **every order and every re-price is a
real transaction.** Light Pools' off-chain quotes update for free between blocks; BTX orders cost
sats to publish and to amend. This is the deliberate price of "nothing off-chain," and the memo does
not pretend otherwise.

---

## 3. Where BTX already aligns with Casey's taste

- **No native token.** BTX has none; the counter-asset is an issuer-pegged Rune stablecoin (the
  peg is the asset issuer's concern, not a BTX dependency). This is the axis Casey calls out as
  "cumbersome, extractive" — BTX and Runes both score clean.
- **UTXO-native.** The offer is a UTXO carrying the rune; filling it spends it; cancellation is just
  spending it. The announce carrier is OP_RETURN (provably unspendable — does not bloat the UTXO
  set), matching Casey's "avoid junk UTXOs" value.
- **Asset layer is Runes itself**, which already satisfies the rubric. BTX inherits that.

---

## 4. Improvement backlog (borrow from Light Pools + ord)

Ranked by how much each moves BTX toward "most Bitcoin-native L1 DEX," with the idea each draws on.

1. **Resolve the mempool-sniping / front-running question (highest priority — it's the one axis
   where Casey's design is provably better).** Light Pools is "not vulnerable to mempool sniping,
   since signatures commit to all inputs and outputs." BTX's `SIGHASH_SINGLE|ANYONECANPAY` offer
   deliberately does *not* commit to all inputs/outputs — that is what makes it an open order. We
   must analyze precisely:
   - The maker is protected on price (output 0 = the maker payout is committed by the maker's sig).
   - The taker's own funding inputs are `SIGHASH_ALL`, so a third party cannot redirect the taker's
     change.
   - The real exposure is a **race**: a watcher can pull the maker's pre-signed input out of a
     broadcast fill and rebroadcast their *own* fill at a higher fee, winning the offer and wasting
     the original taker's effort. This is inherent to open, publicly-published orders.
   - *Action:* write this up rigorously (it is a correctness/threat-model gap, not just docs), and
     decide whether to (a) accept it as the nature of open orders, (b) offer an optional
     "addressed" fully-committed-PSBT mode à la Light Pools for makers who want one counterparty, or
     (c) add a taker-protection convention (e.g. anchor the taker's first input + fee-bump policy).
     This is the single most important item because it is the one place the incumbent design is
     ahead.

2. **Make the BTX Runes encoder bit-exact against ord, with pre-flight validation.** We hit the
   duplicate-name cenotaph live (re-etching a taken name mints nothing). Reading `ord`'s actual
   runestone/`Runestone`/`Etching`/`Cenotaph` code (now cloning to `ord-reference/`) lets BTX
   *pre-validate* before broadcasting: reject names already etched, names below the current
   minimum-rune unlock length, and reserved names. Casey's spec note in the Runes post anticipates
   exactly this gate:
   > "only allow assignment of symbols above a certain length, with that length decreasing over
   > time … to avoid short, desirable symbols being assigned in the early days."
   *Action:* port ord's name-eligibility + cenotaph rules into a `btx_etch` pre-check so the etch
   button can never silently no-op.

3. **Lean into "zero gossip" as the headline property.** Casey frames the gossip network as work to
   be done; BTX's differentiator is that it needs none. *Action:* document and benchmark order
   propagation purely over Bitcoin relay (we already saw cross-node propagation on signet), and make
   it a first-class claim in the README/case study.

4. **UTXO hygiene audit.** Casey prizes UTXO-set minimization. *Action:* verify BTX never leaves
   dust/junk UTXOs: the offer is consumed on fill, the OP_RETURN announce is unspendable, and the
   Taproot envelope is spent in the reveal. Confirm the taker fill doesn't strand sub-dust change.

5. **Cheaper / replaceable orders to narrow the re-pricing gap.** The one real BTX disadvantage is
   that re-pricing costs an on-chain tx. *Action:* (a) prefer the Taproot witness-envelope carrier
   (witness-discounted) over OP_RETURN for the announce where size matters; (b) support RBF of the
   announce so a maker can re-price by replacing an unconfirmed announce rather than publishing a
   second order (we saw duplicate 0.001 orders pile up on signet — RBF replacement would prevent
   that). This will never be free like Light Pools, but it can be cheap.

6. **Optional BIP-322 for off-chain-free intents.** Light Pools uses BIP-322 sigs of the offered
   UTXO. BTX's on-chain publish already provides spam resistance (you pay to publish) and
   cancellation (you spend the offer), so BIP-322 is not load-bearing — but it could enable a signed
   "cancel intent" or order metadata broadcastable in the mempool without spending. Low priority;
   listed for completeness so we have a considered answer when asked "why not BIP-322 like Casey?"

---

## 5. Verified against the ord source (`ord-reference/crates/ordinals/src/`)

### 5.1 BTX's rune encoding is already bit-exact with ord — confirmed

- **Commitment** (`rune.rs:127-137`): ord's `Rune::commitment()` is the u128 in little-endian with
  trailing zero bytes stripped. BTX's `btx_etch.rune_commitment` is
  `rune_num.to_bytes(16,'little').rstrip(b'\x00')` — identical. ord's own tests (`rune.rs:452-466`)
  give `1 -> [1]`, `256 -> [0,1]`, `65536 -> [0,0,1]`, `u128::MAX -> [255;16]`; BTX matches all.
- **Name ↔ number** (`rune.rs:140-186`): ord's `Display`/`FromStr` is the modified base-26 over
  `A..Z`. BTX's `rune_number` / `rune_name` round-trip against it (already in our selftest). ord
  adds **overflow guards** (`checked_mul`/`checked_add` → `Error::Range`); BTX should mirror that so
  an absurdly long name errors cleanly instead of producing a huge int.

So the live signet etch worked because the encoder was right; the only real gap is **pre-flight
validation**, below.

### 5.2 The full etch-eligibility rules (so the etch button can never silently no-op)

These are the conditions ord enforces; BTX should check all of them *before* broadcasting the
commit (and ideally grey out the button with the reason):

1. **Charset / range** — name is `A..Z` only and parses without overflow (`rune.rs:167-186`).
2. **Not reserved** — `Rune::RESERVED = 6402364363415443603228541259936211926`
   (= `"AAAAAAAAAAAAAAAAAAAAAAAAAAA"`, 27 A's, `rune.rs:9`). A name whose number `>= RESERVED` is
   reserved (`is_reserved`, `rune.rs:115-117`) and can't be user-etched. In practice any name of ≤26
   letters is fine; the guard matters only for pathological inputs.
3. **Unlocked at the etch height** — the name's number must be `>= Rune::minimum_at_height(network,
   height)` (`rune.rs:61-89`). The schedule is fully client-computable from the `STEPS` table
   (`rune.rs:15-44`), `UNLOCKED = 12`, `UNLOCK_INTERVAL = SUBSIDY_HALVING_INTERVAL / 12` (= 17 500),
   and `first_rune_height` (`rune.rs:50-59`: mainnet `210000*4 = 840000`, **signet/regtest `0`**,
   testnet `210000*12`).
   - *Why our signet tests "just worked":* on signet `first_rune_height = 0`, so the minimum decays
     to `Rune(0)` = `"A"` by height `210000`. Our etch was at ~306 135 (> 210 000), so the minimum is
     literally `"A"` — any name length passes. ord's own tests confirm signet height 0 minimum is
     `"ZZYZXBRKWXVA"` and it only falls from there (`rune.rs:391-395`). **On mainnet this is a real
     gate** — BTX must compute it, because a too-short name there is a silent cenotaph.
4. **Name not already etched** — the one rule that requires a runtime lookup: query the ord oracle
   `/rune/<NAME>`; if it resolves, the name is taken → refuse. This is exactly the duplicate-name
   case we hit live (re-etching `BTXUSDTESTS` minted nothing). The fix that's already shipped
   (unique random names) sidesteps it; this check makes a *user-chosen* name safe too.
5. **Runestone well-formed** — no `Flaw` (`flaw.rs`): the decode-level cenotaph reasons are
   `EdictOutput` (edict output index > tx output count), `EdictRuneId`, `InvalidScript`, `Opcode`
   (non-pushdata in the OP_RETURN), `SupplyOverflow`, `TrailingIntegers`, `TruncatedField`,
   `UnrecognizedEvenTag`, `UnrecognizedFlag`, `Varint`. BTX builds the runestone itself so it
   controls these, but the taker-swap **edict** must keep `OUTPUT` ≤ the actual output count
   (`EdictOutput`) — worth an explicit assert in `btx_wallet.build_taker_swap_unsigned`.

*Action for backlog item #2:* port rules 1-3 and 5 into a pure `btx_etch.validate_name(name,
network, height)` + a runestone self-check, and wire rule 4 into `h_rune_etch` (ord lookup) so both
the CLI and the GUI refuse a doomed etch with a precise reason instead of silently producing a
cenotaph.

### 5.3 Still worth a look (not yet read)

- `runestone/` subdir (the decipher state machine) — to confirm BTX/brk match ord on the
  **Pointer** field and default routing ("unassigned runes → first non-OP_RETURN output") in the
  presence of an OP_RETURN. Our signet fill empirically routed 1000 units to output 1 correctly, so
  this is confirmation-grade, not a known gap.
- `edict.rs` / `runestone.rs` encode path — to byte-compare against BTX's `etching_payload`.

---

## 6. One-line summary

Casey designed Runes to need **no off-chain data, no native token, and to live in Bitcoin's UTXO
model** — then built a DEX (Light Pools) that breaks the first rule with an off-chain gossip order
book. BTX keeps all three rules at the trading layer too, which is precisely what lets it claim the
"most Bitcoin-native L1 DEX" title. The work that remains is mostly about *matching* Light Pools on
the two axes where an off-chain book is genuinely better — sniping-resistance and free re-pricing —
without giving up the on-chain book that is BTX's whole point.
