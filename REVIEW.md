# BTX — technical review guide

This is a reading map for an external technical reviewer. It points you at the
load-bearing, genuinely novel parts first, and is honest up front about what is
proven, what is heuristic, and where the weak spots are — so you can spend your
time breaking the interesting claims rather than rediscovering known limitations.

## What BTX is (one paragraph)

One local program: a Bitcoin full node + self-custody wallet + solo-mining controls
+ an on-chain, server-less order-book DEX (BTC vs. a Bitcoin-native asset, today
Runes). The one novel claim: **the entire order book is reconstructed purely from
confirmed chain data — there is no relay, server, or off-chain PSBT passing.** A
maker pre-signs their side of an atomic swap with `SIGHASH_SINGLE|ANYONECANPAY`
(0x83) and publishes a ~207-byte `BTX1` v2 artifact on-chain; any node's indexer
rebuilds the book; a taker appends their side and broadcasts; settlement is one
Bitcoin transaction. Resolution is **"first valid spender wins"** (no protocol-level
deterministic matching — see "Known limitations").

## Two repos

- **`renshuBTC/brk-btx`** (branch `main`) — the Rust indexer/serving fork (a fork
  of BRK / Bitcoin Research Kit). Contains the on-chain parsing, order-book state
  machine, Runes decoder, persisted store, and HTTP API.
- **`renshuBTC/bitcoin-terminal-exchange`** (branch `main`, this repo) — the Python tooling
  (maker/taker, carriers, Schnorr/Taproot, publisher), the local orchestrator +
  GUI, the design docs, and the validation runbooks.

## Start here (everyone)

1. `BTX-architecture-and-build-sequence.md` — read **§2** (order encoding +
   chain-reconstructed settlement) and **§2.2** (the crux: script-enforced offer
   vs. published pre-signature). BTX took path **(b)**, published pre-signature.
   The doc also states the prior art directly: on-chain order books (Counterparty
   DEx, Omni MetaDEx) existed and were *"largely abandoned"* — that context matters.

## Track A — Casey-style review (encoding + settlement + Runes correctness)

The interesting question: is the artifact format sound, is the pre-signed-swap
reconstruction actually completable by any indexer with no off-chain data, and is
the Runes parsing byte-correct?

- **`brk-btx` → `crates/brk_indexer/src/btx.rs`** — the core. The `BTX1` artifact
  parser, `verify_maker_sig` (the 0x83 maker pre-signature), `parse_envelope_payload`
  / `extract_from_witness` (the inscription-style `OP_FALSE OP_IF … OP_ENDIF`
  envelope reused as an order carrier), and the open/fill/cancel state machine.
- **`brk-btx` → `crates/brk_indexer/src/runes.rs`** and **`btx_runes_decode.py`**
  — the runestone decoder. Validated against Magic Eden's `runestone-lib`
  (`btx_runes_xcheck.py`: 18 golden vectors from a 805-case differential run,
  byte-equal cenotaph verdicts) plus encoder/decoder round-trip. **Known caveat:**
  `btx_runes.py` (the *encoder*) uses a `tx − prev_tx` edict delta even across
  blocks, which deviates from the canonical absolute-`tx`-when-block-delta≠0 rule;
  harmless because BTX emits single edicts, but called out so you don't have to
  find it.
- **`btx_wallet.py`** (maker-sign / taker-fill / witness transplant),
  **`btx_carrier.py`** (artifact + OP_RETURN and Taproot-envelope carriers),
  **`btx_taproot.py`** (dependency-free BIP340 Schnorr + BIP341 script-path
  TapSighash; reproduces the BIP test vectors), **`btx_envelope_publish.py`**
  (commit→reveal publisher).
- **Reorg safety:** `brk-btx → crates/brk_indexer/src/stores.rs` (the `btx_orders`
  store + rollback) and `crates/brk_indexer/examples/btx_reorg.rs`.
- **Two carriers:** OP_RETURN (needs `-datacarriersize=240` on pre-v30 nodes; the
  207-byte artifact exceeds the default 80-byte policy) and the Taproot witness
  envelope (relays under default policy — this is the carrier proven cross-node).

## Track B — Nym-style review (privacy + censorship-resistance thesis)

The interesting question: does replacing a relay with the chain actually buy
censorship-resistance, and at what privacy cost?

- `BTX-architecture-and-build-sequence.md` **§1.2** (the "no network surface — by
  design" claim) and the trust-boundary discussion.
- `brk-btx → crates/brk_indexer/src/btx.rs` and `btx_carrier.py` — read these to
  see *exactly what each order publishes permanently and publicly*: offer outpoint,
  rune id, price, amount, expiry, maker pubkey, and the maker pre-signature.
- **The honest weakness to pressure-test:** BTX removes the relay chokepoint
  (good for liveness/censorship-resistance — the book inherits Bitcoin's liveness)
  but has **no network-privacy layer**. Broadcasting the publish/fill tx leaks the
  broadcaster's IP and links funding UTXOs unless run over Tor; every order is
  permanent and public on-chain. On privacy this is strictly worse than an
  ephemeral relay (e.g. a Nostr-based book). At the settlement layer BTX and a
  Nostr DEX are identical (same PSBT) — the only difference is the advertising layer
  (chain vs. relay).

## What is proven vs. not (so you can calibrate)

- **Proven on signet, including public signet:** a witness-envelope order published
  on public signet (reveal `60e969a3…`) relayed across foreign nodes under default
  policy and was mined (block 305837); brk_cli indexed it and served it at
  `/api/v1/btx/orders`. Full publish→serve→fill→settle lifecycle runs on signet.
  See `BTX-signet-validation.md` and `BTX-seeding-runbook.md`.
- **Not run on mainnet.** No mainnet index exists; the live-trades feed
  (`/api/v1/btx/trades`) returns `[]` off-mainnet by design.
- **The trades/swaps feed is heuristic.** `brk-btx → crates/brk_indexer/src/trades.rs`
  detects "likely Runes-marketplace fill" as `0x83 pre-signed input + runestone
  edict`. Detection + rune/amount are solid (validated against a real UniSat fill,
  tx `974def98…`); buyer/seller attribution is best-effort.

## Known limitations (we already know these)

- **No deterministic matching.** Resolution is "first valid spender wins," which is
  weaker than Counterparty's protocol-level matching. Two valid takers race; the
  double-take case is handled (second spend is rejected `-26`, one confirms) but
  there is no fairness/ordering guarantee.
- **Cost/latency/scale/privacy** are all worse than an off-chain relay (a fee per
  order *and* per cancel, needs confirmations, ~7 tps ceiling, everything public).
  The intended edge is narrow: maximal-sovereignty / censorship-resistance.
- **Stablecoin counter-asset (Phase 5) is not built.** The asset layer is abstracted
  (Runes today; Taproot Assets / Liquid as pluggable backends) but a USD-stablecoin
  pairing — and its regulatory review — is deliberately deferred.

## How to run it

`BTX-live-demo-runbook.md` and `BTX-envelope-publish-runbook.md` (this repo)
give the WSL commands to bring up node → indexer → GUI and publish/fill an order.
The one-command launcher is `btx-launch.sh`; the single-download bundle is built
by `package-linux.sh`.
