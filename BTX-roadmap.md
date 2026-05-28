# BTX roadmap — features to borrow from the fully-on-chain DEXes

*Forward-looking roadmap of features worth adopting from BTX's closest fully-on-chain peers
(Counterparty, Omni Layer MetaDEx, Saturn BTC), each filtered through BTX's values so adopting it
**strengthens** the thesis rather than diluting it. Complements `BTX-vs-light-pools.md` (design
benchmark + Casey's rubric), `BTX-frontrunning-threat-model.md`, and `BTX-utxo-hygiene-audit.md`.*

Date: 2026-05-27.

## The values filter (anything adopted must pass all of these)

1. **Nothing off-chain** — no relay, gossip network, server, or website. The order book propagates
   over Bitcoin's own relay and is reconstructed locally from raw blocks.
2. **No native token** — no protocol token required for any operation. Counter-asset is an issuer's
   Rune.
3. **UTXO-native** — asset state is Runes (UTXO-bound), never an address-balance side-ledger.
4. **Atomic single-tx settlement** — a fill is one Bitcoin transaction that settles fully or not at
   all. No two-phase match→settle, no free-option gap.
5. **Self-custody throughout** — signing only ever via the user's own Bitcoin Core wallet.

Every item below is either a read-side determinism over chain data, or a composition of pre-signed
atomic swaps — so each passes all five.

## Ranked adoptions

> **Status update (2026-05-27): all five items below are now SHIPPED and tested.** This section is
> kept as the design rationale; each item carries a **Status:** line recording what landed and how it
> was proven. Summary: #1 deterministic book + a native Rust consensus hash proven byte-identical to
> the Python reference *and* to a fully independent chain reconstruction on live regtest; #2 batch
> fills (offline crypto-proof + GUI); #3 indexer-enforced expiry, now matched by the independent
> scanner; #4 rune↔rune via the addressed path, proven live + hardened against a cenotaph attack;
> #5 best-bid/ask + divisibility-normalized prices. All on `bitcoin-terminal-exchange/main` and `brk-btx/btx`.

### 1. Deterministic, consensus-equivalent order-book spec  *(from Counterparty)*
**Source strength:** Counterparty's real innovation is that the order book is *consensus state* —
every node parsing the same chain computes a byte-identical book by a fully-specified rule. That is
what makes an on-chain DEX *trustworthy*, not merely *on-chain*.
**Adopt:** write a fully-specified BTX book state-transition so any two indexers produce identical
books — canonical ordering by `(block height, tx index)`, deterministic price-time priority,
deterministic drop-on-offer-spend. Turns BTX's *reconstructed* book into a *verifiable* one.
**On-values:** pure read-side determinism. No token, nothing off-chain.
**Effort:** moderate. **Priority: highest** (foundational for everything else).
**Status: SHIPPED (2026-05-27).** Deterministic price-time book in `btx_orderbook.py` +
`book_hash` (order-set-independent sha256). Hoisted into the brk-btx Rust indexer as true consensus
state: `brk_indexer::btx::book_hash_from_views` + `GET /api/v1/btx/book-hash`, golden-tested
byte-identical to the Python reference, and **proven live**: an independent Python chain reconstruction
and the Rust indexer produced the *same* hash (`2f9902b3…`) on regtest with a real published order —
two independent implementations agreeing, which is exactly Counterparty's consensus-state property.

### 2. Batch / multi-offer fills  *(from Saturn-category platforms)*
**Source strength:** modern rune order-book platforms let a taker sweep multiple maker offers at
once, aggregating thin liquidity.
**Adopt:** let one taker fill several maker offers in a single transaction — multiple maker
`SIGHASH_SINGLE|ANYONECANPAY` inputs (each committing to its own payout output) plus taker funding
and per-offer rune edicts. Pre-signatures are self-contained, so they compose.
**On-values:** stays atomic and nothing-offchain. **Effort:** moderate. **Priority: high** (biggest
liquidity/UX win BTX currently lacks).
**Status: SHIPPED (2026-05-27).** `build_batch_taker_swap_unsigned` + `transplant_maker_witnesses` +
`cmd_batch_fill` + `/api/swap/batch-fill` + a multi-select "Batch fill" UI in the terminal. The
load-bearing property — each maker's `0x83` pre-sig stays valid at input index *k* as long as its
payout sits at output *k* — is proven by recomputing the real BIP143 sighash at each offer's true
index (offline test, 16 checks). Surfaced + fixed a real bug along the way: `runestone_spk` must
encode the edict tx as **absolute** (not a delta) when the rune block changes, else a negative delta
looped `leb128` forever — which also hardens any multi-rune-block batch.

### 3. Indexer-enforced, block-height order expiry  *(from Counterparty)*
**Source strength:** Counterparty orders expire after N blocks.
**Adopt:** make BTX's existing `expiry` field canonical and indexer-enforced — the book drops an
order past its expiry height. Bonus: short expiries shrink the front-running/MEV window identified in
`BTX-frontrunning-threat-model.md`.
**On-values:** read-side rule over chain data. **Effort:** easy. **Priority: high.**
**Status: SHIPPED (2026-05-27).** The brk-btx indexer drops orders where `tip > expiry` at read
time (`open_orders_from_records`). The independent Python `btx.py book scan` was found to *diverge*
(it kept expired-unspent orders OPEN) — an audit-caught consensus bug that would have split the book
hash — and fixed via `--tip-height` so it applies the identical `tip > expiry` rule. The two
reconstructions now agree (verified in the live cross-hash check, item #1).

### 4. Rune↔rune pairs via the addressed-swap mode  *(from Omni MetaDEx)*
**Source strength:** Omni's MetaDEx matched token↔token, not just token↔BTC.
**Adopt:** support rune-A↔rune-B swaps. **Design note (important):** rune↔rune **cannot** ride the
open `0x83` order — the maker's `SIGHASH_SINGLE|ACP` signature commits to output 0's value/script but
**not** to the inbound-rune edict (which lives in the taker-controlled `OP_RETURN`), so a taker could
route the maker's incoming rune elsewhere and stiff them. It **does** work in the **addressed-swap
mode** (already shipped), where the maker signs `SIGHASH_ALL` and thus commits to the edict too. So
rune↔rune is a natural extension of the addressed path, not the open book.
**On-values:** UTXO-native, atomic. **Effort:** moderate. **Priority: medium** (new market; falls out
of the `SIGHASH_ALL` path already built).
**Status: SHIPPED (2026-05-27).** `btx_rune_swap.py` (`build_addressed_rune_swap_unsigned`, a Runes
allocator, `verify_addressed_rune_tx`) + CLI `addressed-rune-propose`/`-countersign` + btxd routes +
a Rune↔Rune GUI panel. **Proven live on regtest:** maker received the counter-rune at output 0, taker
got the offered rune + change at output 1, ord-confirmed. The maker-side verifier was **hardened by an
audit**: it now rejects any edict whose output index exceeds the output count — ord treats that as a
cenotaph and burns all input runes, so without the check a taker could grief the maker into burning
their offered rune (regression-tested).

### 5. Best-bid/ask + divisibility-normalized prices  *(from Saturn UX)*
**Source strength:** clean rune-trading views with a real top-of-book.
**Adopt:** surface best bid/ask and depth per rune from the deterministic book (#1), with prices
normalized by rune divisibility (pulled from ord). Makes the GUI a usable trading view.
**On-values:** read-side GUI polish. **Effort:** easy. **Priority: medium.**
**Status: SHIPPED (2026-05-27).** `btx_orderbook.build_book` attaches `unit_price` (sats per base
unit) and, with an ord divisibility map, `norm_price` (sats per whole rune) per level; btxd builds
the divmap from ord and the terminal book rows show the normalized price. These are **additive display
fields only** — proven (test) not to change `book_hash`, so the consensus hash / cross-indexer match
is untouched. Best bid/ask already surfaced from the deterministic book (#1).

## Explicitly rejected (would violate the values)

- **Native protocol token** (Counterparty XCP, Omni OMNI) — never. Casey's "cumbersome, extractive."
- **Two-phase match→BTCPay settlement** (Counterparty) — BTX's atomic single-tx fill is strictly
  better; the two-phase model carries the free-option / non-settlement gap.
- **Address-balance side-ledger** (Counterparty/Omni) — stay UTXO/Runes-native.
- **Hosted platform / website / relay** (Saturn) — the book must keep propagating over Bitcoin's relay
  and reconstructing locally.

## Status of prior backlog items (from the other memos)

- Front-running / snipe-resistance → **shipped** as the opt-in addressed-swap mode (CLI + btxd API +
  GUI), proven live (regtest BTC-only + rune-bearing; the open-order path proven on signet). The
  threat model is now also **closed analytically** (`BTX-frontrunning-threat-model.md` §7): open-order
  snipe-resistance is *logically incoherent* — "anyone can fill" is "anyone can outbid the filler," and
  no covenant (CTV/APO) can resolve it because snipe-resistance requires committing to a taker while
  openness forbids it. The only real residual harm is the mispriced-resting-order free option, which is
  not unique to BTX (every resting limit order on any venue has it).
- Etch cenotaph pre-validation (ported from ord `rune.rs`) → **shipped**.
- UTXO hygiene → **audited clean** (`BTX-utxo-hygiene-audit.md`).
- Cheaper/replaceable orders (RBF the announce; prefer witness-envelope carrier) → still open; pairs
  well with #3 (expiry) to manage stale orders.
- Funding hardening (both **shipped** 2026-05-27, surfaced while proving the addressed swap on signet):
  (a) swap funding now accepts **Taproot (P2TR) UTXOs**, not just P2WPKH — `_pick_p2wpkh_utxo` was
  silently dropping taproot change (Core's modern default), so a wallet with rune-free BTC in taproot
  change couldn't fund a swap; offer-selection stays P2WPKH-only for the maker-sig path.
  (b) `btx_etch` now **locks rune-bearing UTXOs before the commit's `sendtoaddress`** (when an ord
  oracle is given) — Core's rune-blind coin selection had pulled a stray rune into the commit, routing
  it into the premine and producing a dual-rune offer on signet.

## Grounded design notes (from the cloned reference repos, 2026-05-27)

Cloned `CounterpartyXCP/counterparty-core`, `OmniLayer/omnicore`, and `SaturnBTC/arch-typescript-sdk`
into `*-reference/` (gitignored) and read the matching engines. Findings that sharpen the items above:

**Saturn correction (affects the competitive framing).** Saturn BTC is built on **Arch Network — an
external VM with verifier nodes** ("smart contract functionalities, atomic swaps, and liquidity pools
by utilizing the Arch Network's virtual machine and verifier nodes"). It is therefore **not** a
fully-on-chain Bitcoin-L1 system and does not belong in BTX's L1 peer group; the genuine
fully-on-chain-L1 peers are only **Counterparty** and **Omni** (both token-gated + address-ledger).
The Saturn-attributed items below (#2 batch fills, #5 best-bid/ask) stand on their own merit as L1
compositions — they are not "borrowed from an L1 peer." (The generic `saturn-network`/`SaturnDAO`
repos are an unrelated older Ethereum/EOS-era DEX; the Bitcoin one is the `SaturnBTC` org.)

**For #1 — Omni's MetaDEx is the reference design** (`omnicore-reference/src/omnicore/mdex.{h,cpp}`):
- Book = `map<property → map<price → set ordered by (block, idx)>>` (`md_PropertiesMap`). Price levels
  sorted by the map; time priority by `(block, idx)` within a level (`MetaDEx_compare::operator()`,
  mdex.cpp:449 — `lhs.block==rhs.block ? lhs.idx<rhs.idx : lhs.block<rhs.block`).
- **Exact rational prices**, never floats: `unitPrice = rational_t(amount_desired, amount_forsale)`
  (mdex.cpp:386), with 256-bit `DivideAndRoundUp` for fill math (`getAmountToFill`, mdex.cpp:400).
  BTX must do the same — exact integer/rational price keys — or two indexers will disagree.
- Partial fills tracked via `amount_remaining` + a status enum (`TRADE_OPEN`, `OPEN_PART_FILLED`,
  `FILLED`, mdex.h:24-30).
- **Consensus state hash:** `saveOffer()` writes each order's fields into a `CHash256` hasher
  (mdex.cpp:427) — that's how Omni nodes *prove* they computed an identical book. BTX's #1 should
  produce the same: a deterministic hash over the serialized book so any two indexers can verify
  agreement. This is the single most valuable thing to copy.
- **Do NOT copy** Omni's `x_Trade` auto-matching engine (mdex.cpp:133) — protocol-driven matching that
  presumes a settlement step. BTX keeps taker-initiated atomic fills; it adopts only the book
  *structure*, *ordering*, and *state hash*.

**For #3 — Counterparty's expiry** (`counterparty-reference/.../lib/messages/order.py`): orders carry
an `expiration` block count; the indexer expires the order (and any pending order-match) at that
height and refunds `give_remaining`. Counterparty also needs `cancel_order_match` +
`reopen_order_when_btcpay_expires` machinery — the two-phase BTCPay free-option problem. **BTX's
expiry is strictly simpler:** nothing is ever escrowed (the offer UTXO stays the maker's, spendable
anytime), so expiry is just "drop from the book past the expiry height" — no refunds, no reopen logic,
no match state. That simplicity is a direct dividend of atomic single-tx settlement.

**For #4 — rune↔rune** maps onto Omni's any-property-for-any-property MetaDEx (`property` ↔
`desired_property`), confirming the model is sound; BTX realizes it via the addressed `SIGHASH_ALL`
path (so the maker commits to the inbound-rune edict), as noted above.

**Magic Eden `me-foundation/runestone-lib` (TypeScript) — rune layer is now triple-validated.** Read
`runestone-lib-reference/src/rune.ts` and confirmed it is byte-identical in spec to ord's `rune.rs`
and BTX's port: the same 28-entry `STEPS` table, `RESERVED = 6402364363415443603228541259936211926`,
`getMinimumAtHeight` (offset `height+1`, `INTERVAL = SUBSIDY_HALVING_INTERVAL/12 = 17500`, same
interpolation), the same 16-byte LE-trailing-zeros-stripped `commitment`, and the same modified
base-26 name↔number. So three independent implementations — **ord (Rust), Magic Eden (TypeScript),
BTX (Python)** — agree exactly. BTX's rune layer (validated against ord plus encoder/decoder
round-trip and the runestone-lib cross-check `btx_runes_xcheck.py`) is now triple-confirmed
spec-correct; **no rune-encoding change is needed.**
Magic Eden's marketplace itself is closed-source and architecturally off-BTX-values (centralized,
off-chain order book), so it contributes no product features — but its `src/indexer/` is a useful
*second* runes-indexing reference (alongside Omni's MetaDEx) to validate roadmap #1's book state
machine and BTX's brk-side decoder against.

### Low-priority parity item
- **Overflow-checked name parsing.** ord (`checked_mul`/`checked_add`) and Magic Eden
  (`checkedMultiply`/`checkedAdd`) error mid-parse on a name whose number exceeds u128; BTX's
  `rune_number` uses Python bigints and instead catches it afterward in `validate_name`
  (`num > U128_MAX`). Functionally equivalent (the gate rejects it), but adding the guard inside
  `rune_number` would give exact parity. Cosmetic; low priority.

## The honest throughline

None of these manufactures the one thing BTX most lacks — **liquidity**. But #1, #2, and #4 are the
features that make liquidity *worth* having if it arrives, and all five tighten BTX's claim to be the
most Bitcoin-native of the fully-on-chain DEXes rather than diluting it.
