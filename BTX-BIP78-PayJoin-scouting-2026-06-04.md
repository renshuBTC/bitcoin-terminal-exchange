# Scouting report — BIP-78 PayJoin (Nicolas Dorier)

*Sixteenth scout in the running cycle (15 + 1 originally; this is the
first new one in the "all five directions" continuation). Domain:
sender/receiver-cooperative coinjoin during a payment, breaking the
common-input-ownership heuristic.*

Date: 2026-06-04.

## Why this BIP

BIP-78 is **Deployed** (not Draft). Live in production via BTCPay
Server, Wasabi, JoinMarket, Sparrow. The author is Nicolas Dorier
(BTCPay maintainer). The protocol has been battle-tested for ~5 years
in real payment flows.

For BTX (a DEX), the relevant question is whether PayJoin's
sender-receiver-cooperative model applies to BTX's
maker-taker-cooperative swap.

## What BIP-78 specifies (verbatim, mediawiki §Specification)

> *"In a payjoin payment, the following steps happen:*
> *• The receiver of the payment, presents a BIP 21 URI to the sender*
>   *with a parameter `pj=` describing a payjoin endpoint.*
> *• The sender creates a signed, finalized PSBT with witness UTXO or*
>   *previous transactions of the inputs. We call this PSBT the `original`.*
> *• The receiver replies back with a signed PSBT containing his own*
>   *signed inputs/outputs and those of the sender. We call this PSBT*
>   *`Payjoin proposal`.*
> *• The sender verifies the proposal, re-signs his inputs and*
>   *broadcasts the transaction to the Bitcoin network."*

Strict constraints (BIP-78 lines 110-124):

> *"The payjoin proposal MUST:*
> *• Use all the inputs from the original PSBT.*
> *• Use all the outputs which do not belong to the receiver from*
>   *the original PSBT.*
> *• Only finalize the inputs added by the receiver…"*
>
> *"The payjoin proposal MUST NOT:*
> *• Shuffle the order of inputs or outputs…*
> *• Decrease the absolute fee of the original transaction."*

Plus a BIP-21 URI extension: `bitcoin:bc1q...?amount=0.01&pj=https://endpoint`.

## How BIP-78 maps to BTX

BTX swaps already have **both parties contributing inputs**, but the
mechanism is fundamentally different from BIP-78:

| Aspect | BIP-78 PayJoin | BTX SIGHASH_SINGLE|ACP swap |
|--------|----------------|------------------------------|
| Initiator | Sender | Maker (publishes pre-signed offer) |
| Coordination protocol | HTTP POST/response over TLS | None (on-chain envelope + taker fill) |
| What sender contributes | Signed finalized PSBT | n/a (no sender role) |
| What receiver contributes | Inputs + outputs, re-signed proposal | n/a (no receiver role) |
| Privacy property | Breaks common-input-ownership heuristic | Maker hides inside taker's tx; addressed mode further breaks pubkey-linking |
| Atomicity model | Cooperative HTTP round-trip | One-shot taker broadcasts |
| Failure mode | Sender can fall back to non-PayJoin tx | Maker offer stays open if taker doesn't fill |

BTX's existing SIGHASH_SINGLE|ACP swap is **structurally closer to BIP-78
than ordinary payments are**: both parties contribute inputs, breaking
the common-input heuristic. But BTX achieves this without any HTTP
coordination — the maker pre-signs once and the order book serves as
the coordination layer.

## BTX-specific privacy properties already in place

Per memory `project_btx_v2_stack_2026-06-02` and the threat model:

- **Maker pre-signature publishes on-chain in the envelope.** The
  envelope (Taproot witness or OP_RETURN carrier) doesn't reveal which
  on-chain output the maker holds until the taker fills.
- **Addressed-only mode** (memory:
  `project_btx_security_audit_2026-05`): when a maker publishes a
  rune-bearing offer, only an addressed taker output is accepted.
  This breaks "watch for swap-shaped patterns" snipers.
- **BTX2 BATCH_ANNOUNCE + MuSig2.** N maker pubkeys aggregate to one
  output key; the resulting on-chain footprint is indistinguishable
  from a single-signer Taproot key-path spend.

## Could PayJoin still add something for BTX?

Three possibilities, each evaluated:

### 1. Maker-side UTXO consolidation in the swap

Under BIP-78, the receiver (maker, in BTX terms) could attach an
additional input from a maker-controlled UTXO and consolidate it into
the swap. **BTX problem:** the maker's pre-signature is over the
specific (offer_input, offer_output) pair via SIGHASH_SINGLE; adding
inputs changes nothing on the maker's signed part. The maker COULD
post-attach a co-input by adding more taker-side machinery.

Verdict: **possible but BTX has no current driver** — makers don't
typically need to consolidate during a swap, and adding the
co-input would require an HTTP coordination layer BTX otherwise
avoids.

### 2. Taker-side input mixing for additional privacy

Under BIP-78, the receiver could insert their own inputs to inflate
the input set and break "the small-input set must be the swap"
identification. **BTX problem:** BTX is the receiver (the maker
publishes; the taker is the sender adding fee + funding). Asking the
indexer-side BTX to add inputs would require BTX to hold maker funds
— which it explicitly doesn't (per memory `feedback_nothing_offchain`).

Verdict: **conflicts with the BTX no-custody rule.** Out of scope.

### 3. Sender-side fallback if cooperation fails

BIP-78 specifies that if the receiver doesn't respond, the sender
broadcasts the original PSBT as a normal (non-PayJoin) tx.

BTX's analog: if the taker can't reach the BTX indexer, they can
still fill an order by parsing the on-chain envelope themselves.
This fallback already exists.

Verdict: **BTX already has the equivalent property** via the
fundamental on-chain order book design.

## Module-by-module value to BTX

The BIP-78 spec doesn't ship a reference Python/Rust implementation
in `bitcoin/bips/bip-0078/`. The implementations cited
(BTCPay Server, Wasabi, JoinMarket, BlueWallet, JS sender client)
are full applications. Direct code extraction isn't a clean fit
because:

- BIP-78 uses HTTP/TLS or .onion endpoints; BTX is local-loopback only.
- BIP-78 uses PSBTs; BTX uses bare-bytes envelopes (BIP-371 PSBT
  support is partial).
- BIP-78 has rigid input/output ordering and fee-floor rules that
  conflict with BTX's SIGHASH_SINGLE|ACP layout.

## Verdict — defer, with strong reasoning

**No code lands.** BTX's existing maker-taker swap mechanism already
provides PayJoin's primary privacy benefit (breaking
common-input-ownership) at a different layer — without HTTP coordination,
TLS, or custody risk. Bringing in PayJoin would:

- Add a custodial component (the maker's HTTP endpoint or BTX as
  receiver).
- Conflict with the no-offchain rule (memory:
  `feedback_nothing_offchain`).
- Duplicate properties BTX already has.

This is the **defer category: redundant** — distinct from the
existing 9 categories in the 15-scout cycle taxonomy. The tool
works, BTX doesn't need it because the property is already provided
by a different mechanism.

Triggers for revisiting:

- BTX adds custodial maker pools that hold inventory inside the BTX
  bundle (no current driver; memory says this is explicitly out of
  scope).
- BTX adds an HTTP coordination endpoint between maker and taker
  before commit (no driver).
- BIP-78 v2 (currently a [pre-draft on
  Delving Bitcoin](https://delvingbitcoin.org/t/payjoin-v2-bip77/));
  worth re-scouting when v2 is finalised.

## Updated 16-scout pattern

| # | Target | Outcome | Reason |
|---|--------|---------|--------|
| 1-15 | (see `BTX-scouting-cycle-summary-2026-06-03.md`) | 5 ship + 9 defer | (9 categories) |
| 16 | **`bitcoin/bips` (BIP-78 PayJoin)** | **spec only** | **redundant (NEW)** |

10 distinct defer categories now in the taxonomy:
- operational, architectural-no-use, consensus, product, era,
  product-timing, architectural-protocol, scope-mismatch,
  threat-model-mismatch, **redundant**.

## File index

```
Bitcoin CoreX/bitcoin-bips-reference/
  └── bip-0078.mediawiki    647 lines (Deployed BIP)

bitcoin-terminal-exchange/
  └── BTX-BIP78-PayJoin-scouting-2026-06-04.md   (THIS DOC)
```

## Source

BIP: <https://github.com/bitcoin/bips/blob/master/bip-0078.mediawiki>
Author: Nicolas Dorier (BTCPay Server)
License: BSD-2-Clause
Status: Deployed
Production references: BTCPay Server, Wasabi, JoinMarket, BlueWallet,
Sparrow Wallet.
PayJoin v2 (BIP-77) pre-draft: <https://delvingbitcoin.org/t/payjoin-v2-bip77/>
