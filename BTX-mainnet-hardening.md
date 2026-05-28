# BTX — mainnet hardening audit

*What has to be true before BTX touches mainnet with real value. Grounded in the actual code
(lines cited); each item rated by severity and what specifically goes wrong on mainnet that does **not**
bite on regtest/signet. Date: 2026-05-27.*

The good news up front: **no item below is a *protocol* custody/theft hole.** The maker is
price-protected by its `0x83` signature and taker funds are `SIGHASH_ALL`-protected (see
`BTX-frontrunning-threat-model.md`), and the audit + adversarial passes closed the real bugs
(`runestone_spk`, the rune↔rune cenotaph false-accept, the book-scan expiry divergence). Items 1–7 are
about **orders failing to propagate, getting stuck, or being silently invalidated** — operational and
relay-policy hazards, plus two accuracy limitations of the indexer.

Items 8–9 (added by the 2026-05-27 threat-model-driven pass) are a **different class: local / client
attack surface**, not relay or consensus. One of them — btxd's missing `Host:` check — is the single
surface that *could* have driven unauthorized wallet actions (a malicious web page rebinding DNS to
`127.0.0.1` to make the user's own node publish/fill/etch). That is not a protocol custody hole (no
counterparty can steal a maker's price), but it is the closest thing to one in the codebase, so it is
called out explicitly. Both are now closed. Everything here is listed so it is fixed or accepted
*deliberately*.

## Must address before mainnet (summary)

| # | Item | Severity | State |
|---|------|----------|-------|
| 1 | OP_RETURN announce too large to relay under default policy | was BLOCKER | **fixed** — mainnet defaults to the witness-envelope carrier |
| 2 | Offer lock is in-memory; lost on wallet restart → offer can be spent out from under an open order | HIGH | **fixed** — `btxd` re-locks open offers on startup |
| 3 | ord oracle sync not checked before trusting rune balances | HIGH | **fixed** — rune ops gated on `ord_synced()` |
| 4 | Fee estimate has no RBF escape; a stuck fill can't be bumped | MEDIUM | **fixed** — taker funding input RBF-signals (BIP125) |
| 5 | Confirmation-depth / reorg finality is the taker's responsibility | MEDIUM | **fixed** — terminal shows confirmations on fills |
| 6 | Tip-relative reconstruction → cold-sync history is lossy (open book + hash still correct) | MEDIUM (accuracy) | **fixed** — height-independent offer lookup |
| 7 | Rune `amount` is u64; a rune with supply > u64::MAX can't be represented | LOW | **fixed** — rejected at maker-sign |
| 8 | btxd has no `Host:`/Origin check → DNS-rebinding lets a web page drive wallet-signing actions | HIGH (local) | **fixed** — loopback `Host:` allowlist on every request |
| 9 | terminal renders served fields via `innerHTML` → stored XSS if a free-text field is ever served | LOW (latent) | **fixed** — `esc()` on on-chain/indexer-derived fields |

*(2026-05-27: all items above are now fixed; per-item detail updated inline. Items 8–9 added by the
threat-model-driven pass — see `BTX-threat-model.md`.)*

---

### 1. Announce relay: OP_RETURN size vs `datacarriersize`  *(was BLOCKER — fixed)*

The BTX artifact is ~190 bytes. A bare `OP_RETURN` that large exceeds Bitcoin Core's historical
`datacarriersize` standardness limit (83 bytes), so on mainnet an OP_RETURN announce is unlikely to
relay or be mined across the many nodes that haven't raised the limit — even though the *publisher's
own* node (which the bundle starts with `-datacarriersize=240`) accepts it. We hit exactly this on a
freshly-restarted regtest node (`error -26 scriptpubkey`).

**Fix (shipped):** `btxd.h_order_create` now defaults the carrier to **`envelope`** on mainnet
(`CFG["chain"] in {main, mainnet}`), keeping `op_return` only on regtest/signet. The Taproot
witness-envelope carrier (`btx_envelope_publish.py`) puts the artifact in witness data, which is not
subject to `datacarriersize`, so it propagates under default relay policy (this is why the envelope
path was built — "No `-datacarriersize` needed"). **Residual:** the maker pays for a commit + reveal
(two txs) instead of one. Acceptable and correct. *(Note: recent Bitcoin Core has debated relaxing the
OP_RETURN limit, but cross-network relay + miner acceptance of large OP_RETURN is not something BTX
should assume; envelope is the safe default.)*

### 2. Offer lock is in-memory — lost on wallet restart  *(HIGH — fixed 2026-05-27)*

`btx_wallet.cmd_maker_sign` reserves the offer UTXO with `lockunspent false [outpoint]` so wallet
coin-selection can't spend the offer while the order is open (`btx_wallet.py` ~280). **Bitcoin Core's
locked-coin set is in-memory and cleared on wallet reload/restart.** On mainnet, where a node may
restart between publishing an order and its fill, after a restart Core's automatic coin selection can
pick the (now-unlocked) offer UTXO to fund some *other* transaction or as change — spending it out from
under the open order. The indexer then drops the order (its offer is gone), and the maker has
unexpectedly moved the asset.

**Fix (shipped):** `btxd.relock_open_offers()` runs on startup — reads `/api/v1/btx/orders` and
`lockunspent false` each offer outpoint the wallet owns (offers it doesn't own just error and are
skipped). Operationally, a maker can also keep offers in a dedicated wallet that funds nothing else.
(Bitcoin Core has no persistent-lock flag on `lockunspent`, so re-lock-on-startup is the mechanism.)

### 3. ord oracle sync state not checked  *(HIGH for rune orders — fixed 2026-05-27)*

Rune backing verification (`assert_offer_backs_rune`) and divisibility-normalized prices depend on a
**fully-synced, fully-rune-indexed `ord`**. A lagging or still-indexing ord returns stale/zero balances,
which can (a) let a maker publish a rune order the offer doesn't actually back (the backing check passes
against stale data) or (b) misroute/misprice. There is currently no check that ord's tip matches the
node's tip before trusting its answers.

**Fix (shipped):** `btxd.ord_synced(margin=2)` compares `ord /blockheight` to the node's
`getblockcount`; the rune-touching handlers (`h_order_create` rune path, `h_addressed_propose`
rune path, `h_rune_propose`, `h_rune_countersign`) return **503 "ord not synced"** if ord is more than
2 blocks behind. BTC-only orders are unaffected. *(On regtest/signet the chains are short so ord is
trivially synced — this only bites at mainnet scale, which is why it hadn't surfaced.)*

### 4. Fee estimation + no RBF escape on a stuck fill  *(MEDIUM, open)*

`btxd.estimate_fee_sats` is sound: `estimatesmartfee` (conf_target 6) → sat/vB × vsize, floored at
1 sat/vB, falling back to `DEFAULT_FEE=10000` when the estimator has no answer. The mainnet hazards:
- The `10000`-sat fallback for a ~300 vB swap ≈ 33 sat/vB — fine in calm conditions, too low in a fee
  spike (the fill sticks). A too-low fee **loses nothing** (the offer stays open; rebuild + rebroadcast),
  but it wastes a round-trip.
- The taker's funding input isn't explicitly RBF-signaled, so a stuck fill can't be cheaply fee-bumped;
  it must be rebuilt. The batch-fill fee is the heuristic `per_offer_fee × N`, not a true vsize estimate.

**Fix (shipped):** the taker **funding** input now RBF-signals (`nSequence = 0xfffffffd`, BIP125) in
both `build_taker_swap_unsigned` and `build_batch_taker_swap_unsigned`, so a stuck fill can be
fee-bumped instead of rebuilt. Safe by construction: the maker's `SINGLE|ANYONECANPAY` signature
zeroes `hashSequence`, so it does not commit to any input's sequence — the pre-sig stays valid.
Remaining as operational guidance: keep the node synced (estimator), review the fee in the GUI, and the
batch fee is still the conservative `per_offer × N` heuristic (a too-low fee only delays, never loses).

### 5. Confirmation depth / reorg finality  *(MEDIUM, accepted)*

An unconfirmed fill is never final — and a maker can double-spend (cancel) the offer until the fill
confirms (true of any standing pre-signed offer, incl. Light Pools). The indexer's reorg rollback is
implemented and tested (`btx_rollback_plan`; live 1-block regtest reorg), but mainnet reorgs are real.

**Fix (shipped) + guidance:** the terminal now shows a **confirmations badge** on each on-chain trade
(`TIP − height + 1`, amber under 6 confs, green at ≥6), so a low-conf fill is visibly not-final. The
taker should still wait for depth before treating a received rune as settled — standard Bitcoin
finality, now surfaced rather than implicit.

### 6. Tip-relative reconstruction → cold-sync history is lossy  *(MEDIUM, accuracy not safety)*

The indexer verifies an offer via `BrkChain::offer_utxo` = `get_tx_out`, which is **tip-relative**
(queries the node's *current* UTXO set). During a cold reindex with the node already at tip, an offer
that was announced and later spent reads as already-spent at the moment its announce block is processed,
so that order is never recorded and its historical fill/cancel is invisible.

**Consequence — bounded and benign for the parts that matter:** the **live open book is correct** (an
open order requires an unspent offer, which `get_tx_out` sees), and therefore the **consensus hash —
computed over open orders — is correct**. Only `history`/`trades` reconstructed from a *cold* sync were
incomplete. **Fix (shipped):** `BrkChain::offer_utxo` now falls back, when tip `get_tx_out` returns
None (offer already spent), to resolving the offer output from the transaction that *created* it via
`get_raw_transaction` (height-independent; needs the node's `-txindex=1`, which the bundle runs). Pass 2
then flips the recovered order to FILLED/CANCELLED, so a cold reindex's history matches a node that
indexed live. Without txindex it degrades to the old tip-only behavior — never wrong for the open book,
just less complete on cold history.

### 7. Rune `amount` is u64  *(LOW — fixed 2026-05-27)*

The artifact `amount` is `u64` in both the Python (`btx_0b`) and Rust (`btx.rs`) parsers. Runes
balances are `u128`; a rune whose traded amount exceeds `u64::MAX` (~1.8e19 base units — possible for a
very large supply at high divisibility) cannot be represented and would truncate.

**Fix (shipped):** `cmd_maker_sign` rejects `amount_units > u64::MAX` (and `price > u64::MAX`), and the
rune↔rune builder (`build_addressed_rune_swap_unsigned`) rejects either rune amount over the bound —
so a value that would desync the u64 Python/Rust parsers errors instead of truncating silently.

### 8. btxd has no `Host:`/Origin check — DNS-rebinding can drive wallet actions  *(HIGH local — fixed 2026-05-27)*

`btxd` is a stdlib `ThreadingHTTPServer` bound to `127.0.0.1` with **no auth, no CORS, and (pre-fix)
no `Host:`/Origin validation** in `do_GET`/`do_POST` (`btxd.py` ~618/~643). Binding to loopback stops
*direct* remote connections, but not **DNS rebinding**: a page the user visits at `http://evil.com/`
can re-resolve `evil.com` to `127.0.0.1` and then `fetch('http://evil.com:3333/api/order/fill', …)`.
The TCP connection lands on btxd, and because the same-origin policy now considers it same-origin,
the browser delivers the POST. The handlers drive wallet-signing actions — `/api/order/create`,
`/api/order/fill`, `/api/swap/batch-fill`, `/api/rune/etch`, the addressed-swap routes — so a hostile
web page could make the user's own node publish/fill/etch/spend **without the user's intent**. This is
not a protocol custody hole (no counterparty steals the maker's committed price), but it is the only
surface in BTX that could cause unauthorized on-chain wallet activity.

**Fix (shipped):** a loopback `Host:` allowlist (`btxd._allowed_hosts()` → `Handler._host_ok()`),
checked at the top of both `do_GET` and `do_POST`; anything whose `Host:` isn't `127.0.0.1` /
`localhost` / `::1` (with the configured `--port`) gets **403**. This is the standard rebinding guard
(bitcoind/geth do the same): the browser sets `Host:` from the URL and **cannot** forge it to a loopback
name (`Host` is a forbidden header), so a rebinding page sends `Host: evil.com:3333` and is rejected,
while the legitimate `127.0.0.1`/`localhost` GUI keeps working. `--port`/`--host` are now threaded into
`CFG` so the allowlist tracks a non-default port. Logic unit-tested (legit loopback hosts pass; rebinding
/ cross-site / wrong-port hosts rejected). *Residual:* still no auth token — acceptable for a
single-local-user tool now that cross-origin driving is blocked; a token would be the next step only if
btxd is ever exposed beyond loopback (it should not be).

### 9. Terminal renders served fields via `innerHTML`  *(LOW latent — fixed 2026-05-27)*

`btx_trade.html` builds order-book / mempool / trades / wallet rows with `innerHTML` and string
interpolation. **Today this is not exploitable:** every interpolated field is numeric or hex —
`rune_id` is `"block:tx"`, txids are hex, `price`/`amount` go through `toLocaleString`/`fmt`, and
`artifact_hex` is hex. No free-text field (an ord rune **name** or **symbol**) is fetched or rendered
anywhere. The latent risk is the pattern: the click handlers embed `artifact_hex` as
`onclick='loadFill(${JSON.stringify(art)})'`, which would break out of the single-quoted attribute on a
stray quote, and a rune-name column added later would be stored XSS (the served data originates from
adversary-crafted on-chain bytes).

**Fix (shipped):** an `esc()` HTML-entity escaper, applied to the on-chain/indexer-derived fields
(`rune_id`, txid, and the `JSON.stringify(artifact_hex)` inside every `onclick`). Verified it leaves
today's hex/numeric values byte-identical (no display regression) and fully neutralizes a hostile
free-text value — escaped quotes decode back correctly in the attribute context, so `loadFill` still
receives the right string while `'`/`"`/`<` can no longer break out. Defense-in-depth: it makes adding a
rune-name column safe by default rather than a latent XSS.

---

## Blast radius & hot-wallet mitigation  *(design + shipped misconfiguration rail, 2026-05-27)*

btxd drives the loaded wallet to sign/spend with **no per-action consent** — any local process that
can POST to the loopback API (or a compromised btxd itself) can publish/fill/etch/spend the *entire*
spendable balance (threat-model item e). The `Host:` rebinding guard (#8) closes the cross-origin browser
vector, but the underlying fact remains: **whatever the loaded wallet can spend, btxd can spend with no
prompt.** So the only real bound on damage is *how much value the wallet holds* and *what spending policy
guards it*. Three layers, honestly scoped:

**1. Dedicated thin wallet + balance cap — SHIPPED (operational rail).**
The near-term mitigation is purely operational: point btxd at a **dedicated wallet holding only the
trading float**, never a primary store of value. To make that hard to get wrong by accident, btxd now
takes `--max-hot-balance-btc` and, at startup (after wallet auto-load, before serving), reads
`getbalances.mine.trusted` and **refuses to boot** if spendable exceeds the cap. **What it is:** a
*misconfiguration* rail — you cannot accidentally aim btxd at a fat wallet. **What it is NOT:** an
anti-compromise control. A compromised btxd bypasses its own check, and the cap only gates *startup*,
not per-spend. It is off by default (set it on mainnet). The guardrail degrades gracefully (skips with a
one-line notice) if the balance RPC fails, so it never turns into a new startup-crash surface.

**2. 2-of-2 policy cosigner — the real near-term cryptographic bound (design).**
To bound blast radius *cryptographically* rather than operationally, the trading wallet's coins should
live under a **2-of-2** where btxd holds one key and an independent **policy cosigner** holds the
other. The cosigner — a tiny separate process/HSM/phone — applies the rules btxd cannot enforce on
itself: per-tx and daily spend ceilings, destination/whitelist checks, rate limits, "only co-sign txs
that look like a BTX fill/etch." A compromised btxd then cannot move funds the cosigner refuses to
sign. This is the standard hot-wallet pattern and needs no new consensus features — just miniscript
(`and(pk(btxd), pk(cosigner))`) and a cosigner daemon.

**Honest CAN/CANNOT on miniscript here:** miniscript expresses *spending conditions* — which keys, which
timelocks, which hashes — **not** velocity or amount caps. There is no `older(N)`-style opcode for "≤ X
sats per day." So the daily-limit / whitelist logic lives in the **cosigner's signing policy** (off-chain
code that decides whether to produce its signature), and miniscript's role is only to make that second
signature *mandatory* (the `and()` above). Don't oversell miniscript as the limiter; it is the *enforcer
of co-signing*, the cosigner is the *limiter*.

**3. Covenants (OP_VAULT / CTV) — the future on-chain bound (watch).**
If `OP_VAULT` (BIP-345) or `OP_CHECKTEMPLATEVERIFY` (BIP-119) activate, the float could sit in a vault
that *consensus-enforces* a withdrawal delay + a clawback path: a theft attempt becomes a visible,
revertible on-chain unvaulting rather than an instant drain. This is the only layer that bounds blast
radius **without any trusted second party** (the cosigner in layer 2 is trusted-but-separated). Neither
opcode is active on mainnet today, so this is a watchlist item, not a plan — but the thin-wallet + 2-of-2
design above is exactly the structure that a covenant later upgrades in place.

**Bottom line on blast radius:** shipped today = the thin-wallet misconfiguration rail (layer 1). The
honest residual is that a compromised btxd can spend its float; the cryptographic fix (layer 2 cosigner)
is a design, and the trustless fix (layer 3 covenant) waits on consensus. The mitigation that matters
*right now* is the smallest one: **don't load more than you're willing to lose to the local box.**

## Not issues (checked, fine on mainnet)

- **Dust floors.** `DUST = 546` clears every mainnet relay dust floor (P2WPKH 294, P2TR 330), so
  rune-bearing outputs always relay.
- **BTC amounts.** `price` is `u64` sats; mainnet values fit comfortably.
- **Sig verification.** `verify_maker_sig` is the standard P2WPKH BIP143 `0x83` check, cross-validated
  Python↔Rust; the maker's price commitment is absolute regardless of network.
- **Consensus hash.** Order-set-independent and proven byte-identical across two independent
  implementations on live data — unaffected by mainnet scale.

## Bottom line

**Every item in this audit is now fixed** — the relay BLOCKER (large-OP_RETURN → envelope carrier on
mainnet), both relay/operational HIGH items (re-lock offers on startup, gate rune ops on ord being
synced), the four MEDIUM/LOW items (RBF-signal the fill, surface confirmations, height-independent offer
lookup, u64 amount bound), and the two local/client surfaces from the threat-model pass (btxd
DNS-rebinding `Host:` guard, terminal `innerHTML` escaping). On the protocol side, what's left is
*operational discipline*, not code: keep the node + ord synced, review fees, wait for confirmations.
BTX's self-custody, no-escrow design means the *protocol* failure modes were always "an order doesn't
propagate / gets stuck / is dropped," never "a counterparty steals funds"; the one surface that could
have driven *unauthorized* wallet activity (DNS rebinding) is now closed. **Net: no remaining BLOCKER,
HIGH, MEDIUM, or LOW item — mainnet readiness is now gated on a real economic/liquidity decision, not on
missing safety code.** (The Python protocol changes are confirmed by `btx_test_all.py` — 10/10 green;
the indexer change by `cargo test -p brk_indexer`; the btxd `Host:` guard by an isolated logic test
and the terminal `esc()` by a behavior test, since the sandbox can't load the live btxd/HTML under
mount-lag.)
