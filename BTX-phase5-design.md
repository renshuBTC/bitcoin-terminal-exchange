# BTX Phase 5 — counter-asset finalization (design)

Status: **COMPLETE — including the live on-node trade**, proven end-to-end on Bitcoin Core v29.1
(36/36 in `btx_selftest.py` + a full regtest BTC↔rune trade; see "Proven"). No ord wallet,
nothing offchain. This doc records the decision and
the design so reviewers (and future me) have the rationale.

## Decision: the counter-asset is a Bitcoin-native (rune) stablecoin

The original roadmap said "USD-stablecoin counter-asset." Combined with the hard constraint
**"nothing offchain,"** that resolves to a **stablecoin issued as a Rune** — not a fiat/Liquid/Fedimint
stablecoin. The reasoning is a two-layer split of any stablecoin:

- **Token layer** (issue / transfer / balance accounting). If the stablecoin is a Rune, this is 100%
  on Bitcoin L1. BTX handles it identically to any rune. **Zero offchain dependency in BTX's rails.**
  A Liquid or Fedimint stablecoin fails here — its token layer lives on a federated, offchain system.
- **Peg layer** (what makes 1 unit ≈ $1). This is a property of the *asset*, maintained by its issuer
  entirely outside BTX. BTX never reads, enforces, or depends on the peg — it trades the rune at
  the book price. So the issuer trust is the user's **opt-in choice of counter-asset** (exactly like any
  DEX listing USDT), not a dependency BTX's machinery imposes.

Honest statement BTX holds: *"BTX depends on nothing offchain; the asset you choose to trade may
have an issuer — that's your opt-in, not BTX's rail."* BTX validates that an offer UTXO holds N
units of rune R; it does **not** and cannot verify R is "worth $N" (the peg stays out of scope).

**Prefer BTC-backed rune stablecoins** (e.g. USDh / Hermetica — BTC-backed redeemable; UNIT / Ducat —
USD-peg on Runes) over fiat-backed ones (a USDC-as-rune). BTC collateral is on-chain-verifiable, so the
only residual offchain element is the peg's price oracle — the minimum-offchain form of a stablecoin.
These are live as of 2026 (verify exact backing/liquidity before relying on any one).

**Regulatory note (MAS paused — not an action item):** trading a *third-party* rune stablecoin is not
*issuing* one, so it does not trigger MAS's stablecoin-issuance framework. Different posture from
minting your own.

## Architecture: the Asset Layer Adapter

BTX trades the rune exactly as any Rune. Two correctness pieces make a BTC↔rune trade actually settle:

### Gap 1 — validate-before-advertise (maker side) — DONE (`eeca5c9`, `e400d9c`)
`maker-sign` refuses to publish a rune order unless the offer UTXO holds **exactly** the advertised
amount of the rune. The "exactly" invariant is load-bearing: the settlement edict moves `amount`, so a
remainder on the offer UTXO would default to output 0 (the maker), and too little can't be honored.

Bitcoin Core is rune-blind, so this needs a rune-balance oracle = **`ord`** (a local, chain-derived
index → nothing-offchain-clean). `btx_wallet.ord_rune_balance(ord_url)` resolves rune_id → spaced
name via `GET /rune/<block>:<tx>`, then reads `GET /output/<outpoint>.runes[name].amount` (the raw
base-unit integer — the same unit as the edict, so no divisibility conversion). Wired into `maker-sign`
as `--ord-url` (+ `--require-rune-backing`). Parser grounded against real ord 0.27.1 JSON
(`btx_selftest` §9). The oracle is a pluggable interface (`balance_lookup(outpoint, rune_id) -> int`),
so `ord` is the default backend but it's swappable.

### Gap 2 — settlement moves the rune to the taker — DONE (`9771cda`)
`build_taker_swap_unsigned` appends an OP_RETURN **runestone edict** moving the full `amount` from the
offer input to the taker's output (idx 1). Output 0 (the maker payout) is left untouched, so the maker's
`SIGHASH_SINGLE|ANYONECANPAY` pre-signature stays valid — the taker only *appends* outputs, which SINGLE
permits. Without this, Runes' default routing would send the rune to output 0 (the maker), keeping both
the BTC and the asset. BTC-only orders are unchanged (2 outputs). Verified in `btx_selftest` §7.

## Etching: BTX mints its own counter-asset rune (no ord wallet)
`ord 0.27.1`'s wallet etch fails on Bitcoin Core v29.1 ("commit tx recovery key import failed" — Core
v29 forbids importing a watch-only descriptor into a private-keys-enabled wallet, and 0.27.1 is the
latest ord). Rather than downgrade Core, BTX **hand-builds the etch with its own primitives**
(`btx_etch.py`): rune name↔number, the etching runestone (validated via encoder/decoder round-trip
against the runestone-lib-cross-checked decoder — `btx_runes_xcheck.py` golden vectors), the
rune-name commitment, and a commit→6-blocks→reveal driver reusing
`btx_taproot`'s BIP341 machinery. The reveal is signed with an **ephemeral key** and broadcast via
`sendrawtransaction` — no wallet import, so the v29 restriction never applies. `ord` is only a
read-only indexer. This keeps the latest Core and removes the ord-wallet dependency entirely.

## Proven
- **Offline (36/36, `btx_selftest.py`):** settlement edict (§7), maker-side guard incl. too-much/
  too-little (§8), ord oracle parser vs real ord 0.27.1 JSON (§9), the etching encoder round-trip via
  the runestone-lib-cross-checked decoder (§10), and the etch reveal construction (§11).
- **Live, end-to-end on Bitcoin Core v29.1 + ord 0.27.1 (regtest, 2026-05-26):**
  BTX etched `BTXUSDTESTS` (ord rune id `131:1`, premine 1000; reveal/etch tx `a8afd8fa…`) → ord
  indexed it → `maker-sign --ord-url --require-rune-backing` validated the offer UTXO holds exactly
  1000 of `131:1` (and refused an advertised 1001) → `taker-fill` swap `d8cf9f49…` settled: output 0 =
  maker payout 1,000,000 sats with `runes:{}` (no rune), output 1 = taker with `BTXUSDTESTS:1000`
  (via the runestone edict), offer `a8afd8fa…:0` spent. A fully on-chain, tokenless, issuer-less
  BTC↔rune trade with validated backing — no ord wallet, nothing offchain.

## How to reproduce the live trade
See `BTX-phase5-spike-runbook.md`: bring up a regtest node + `ord --index-runes server`, then
`python3 btx_etch.py etch --rune … --premine N` (the reveal's output 0 becomes the offer UTXO
holding exactly N), `maker-sign --ord-url … --require-rune-backing`, `taker-fill`, and confirm via
`ord /output/<swap>:1` that the rune landed at the taker and `/output/<swap>:0` that the maker got BTC.
No ord wallet, no relay, no token, no issuer.
