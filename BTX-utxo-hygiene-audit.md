# BTX UTXO-hygiene audit

*Backlog item #4 from `BTX-vs-light-pools.md`. Casey Rodarmor lists UTXO-set minimization as a core
virtue of a good Bitcoin protocol — "Protocols that are UTXO-based fit more naturally into Bitcoin and
promote UTXO set minimization by avoiding the creation of 'junk' UTXOs" ([Runes](https://rodarmor.com/blog/runes/)).
This audit walks every BTX transaction and asks: does it create junk/dust UTXOs or bloat the UTXO
set? Grounded in the code; lines cited.*

Date: 2026-05-27.

---

## Background: what counts as "bloat"

A transaction adds to the **UTXO set** only via its *spendable* outputs. Two things are free of
UTXO-set cost:

- **`OP_RETURN` outputs** are provably unspendable, so Bitcoin Core never adds them to the UTXO set.
- **Witness data** (Taproot script-path reveals) lives in the witness, which is pruned and never in
  the UTXO set.

So a protocol stays UTXO-clean if it (a) carries its data in `OP_RETURN`/witness rather than in
spendable outputs, (b) avoids gratuitous change outputs, and (c) never strands sub-dust UTXOs.

---

## Per-path analysis

### 1. Etch — commit + reveal (`btx_etch.py`)

- **Commit tx**: `sendtoaddress` funds the P2TR rune-commitment output, plus the wallet's normal
  change. The P2TR commit is spent by the reveal → net zero. Change is ordinary wallet change, not
  junk.
- **Reveal tx** (`build_etch_reveal`, `btx_etch.py:153`): exactly two outputs — `vout[0]` = the
  premine to a P2WPKH (this *is* the offer UTXO), `vout[1]` = the `OP_RETURN` runestone (unspendable).
- **UTXO-set delta**: +1 (the premine/offer). That output is the asset itself; it must exist to hold
  the rune, and there is exactly one of it. The runestone adds nothing to the set. **Clean.**

### 2. Publish — `OP_RETURN` carrier (`btxd.py` `h_order_create`, op_return branch)

- `createrawtransaction` with a single `{"data": artifact}` output, `fundrawtransaction` adds one
  funding input + change, sign, broadcast (`btxd.py:248-251`).
- The artifact rides in an `OP_RETURN` (unspendable → no UTXO). The only spendable output is the
  wallet's own change. The offer UTXO is **locked** during maker-sign (`btx_wallet.py` reserve
  step) so funding can't consume it.
- **UTXO-set delta**: net ~0 (consumes a funding UTXO, returns change). The order's data is off the
  UTXO set entirely. **Clean.**

### 3. Publish — Taproot witness-envelope carrier (`btx_envelope_publish.py`)

- **Commit**: funds a P2TR commit (+ wallet change), as in the etch.
- **Reveal** (`build_reveal`, `btx_envelope_publish.py:71-89`): spends the commit to a **single**
  output (`out_value = commit_value - fee`, back to the wallet). The ~207-byte artifact is in the
  reveal's **witness** (tapscript), which is pruned — there is no `OP_RETURN` and no data UTXO at all.
- **UTXO-set delta**: net ~0. This is the *cleanest* carrier — the order's data leaves zero footprint
  in either the UTXO set or the non-witness tx data going forward. **Clean (best).**

### 4. Open-order fill & 5. Addressed swap (`build_taker_swap_unsigned`, `btx_wallet.py:110-136`)

Both the open `0x83` fill and the addressed-swap PSBT build the *same* transaction shape:

```
inputs:  [0] offer UTXO   [1] taker funding
outputs: [0] maker payout (price)
         [1] taker receipt  ← rune + ALL leftover sats (offer + funding − price − fee)
         [2] OP_RETURN runestone edict   (only when a rune is involved; unspendable)
```

- **No separate change output.** `btx_wallet.py:129` makes `vout[1]` the taker's *combined* receipt
  and change in one output (`taker_value = offer + funding − price − fee`). This is a deliberate
  UTXO-minimizing choice: a naive design would emit receipt + change as two outputs; BTX emits one.
- **Dust guard**: `btx_wallet.py:126-128` refuses to build if `taker_value < 546`, so no sub-dust
  UTXO is ever created (and a rune-bearing output always clears the 546-sat floor it needs).
- The edict `OP_RETURN` (`vout[2]`) is unspendable → not in the UTXO set.
- **UTXO-set delta**: consumes 2 (offer + funding), creates 2 spendable (maker payout + taker
  receipt). Net ~0, and rune-bearing UTXOs stay **1:1** — one rune offer in, one rune output out, no
  proliferation. **Clean.**

---

## Verdict

**BTX scores well on Casey's UTXO-minimization axis. No path creates junk or dust UTXOs, and none
bloat the UTXO set with data.** Concretely:

- Every carrier keeps order/rune data off the UTXO set — `OP_RETURN` (unspendable) or witness
  (pruned). The envelope carrier is the cleanest (zero persistent data footprint).
- The swap merges the taker's receipt and change into a single output — fewer UTXOs than a naive
  build.
- A dust guard (`< 546`) prevents stranded sub-dust outputs everywhere a taker output is built.
- Rune UTXOs are 1:1: one offer in, one receipt out; runes never spray across outputs.

No fixes required. This is a confirmatory result — worth stating because "more Bitcoin-native" is the
project thesis, and UTXO hygiene is one of the four axes Casey uses to judge that.

## Minor observations (not defects)

1. **Single-UTXO funding.** `_pick_p2wpkh_utxo` (`btx_wallet.py:234`) selects *one* funding UTXO ≥
   `price + fee` rather than combining several. This is good for hygiene (no consolidation churn) but
   means a fill can fail if the taker lacks a single large-enough rune-free UTXO — exactly the
   "no spendable rune-free funding UTXO large enough" we hit on signet. That's a funding/UX
   limitation, not a hygiene problem; a future option could allow multi-UTXO funding for users whose
   balance is fragmented, at the cost of a slightly larger tx.
2. **Wallet change on commit/publish funding** is ordinary Bitcoin Core change, governed by the
   node's own coin selection — outside BTX's control and not junk.
3. **The premine/offer output** persists until the order is filled or cancelled (spent). That is the
   asset sitting on-chain, by design (the UTXO-native state model Casey praises), not a leak.
