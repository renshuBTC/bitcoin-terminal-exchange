# BTX — Threat Model (pre-audit)

*Structured threat model produced before code review. Scope: the nothing-offchain, Bitcoin-L1,
self-custody DEX. Maker pre-signs an offer as an on-chain artifact (`SIGHASH_SINGLE|ANYONECANPAY` over
offer-input-0 + payout-output-0); taker funds + `SIGHASH_ALL`-signs one settlement tx; the brk-btx
indexer reconstructs the book from chain; `btxd` is a localhost orchestrator the browser terminal
drives; `ord` is a read-only rune oracle. Point-in-time. Complements
`BTX-frontrunning-threat-model.md` (open-order sniping) and `BTX-mainnet-hardening.md`. Date: 2026-05-27.*

---

## (a) Principals

Core: **Maker**, **Taker**, **Indexer operator**, **Miner**, **Relay node**, **Third-party wallet**,
**Mempool attacker** (no privileged position), **Relay-path attacker** (privileged network position).

Added (surfaced by the architecture): **ord-oracle operator** (trusted rune-state source), **Local
host / browser** (btxd is a localhost HTTP service with no auth; the terminal is a web page),
**Supply-chain / bundle provider** (ships bitcoind/ord/brk + frozen tools).

---

## (b) Per-principal: can / cannot / gain from misbehavior

### Maker
- **Can:** pre-sign an offer (0x83 commits output-0 = price + payout_spk); publish on-chain (OP_RETURN
  or Taproot witness envelope); cancel by spending the offer UTXO before a fill confirms; re-price by
  RBF-ing the unconfirmed announce; set an advisory `expiry` (indexer-enforced, not consensus).
- **Cannot:** alter a published order's committed output-0 without re-signing; force or choose which
  taker fills (open mode); receive less than `price`; prevent anyone from filling a published order.
- **Gains from misbehavior:** *renege* — double-spend the offer out from under a taker's unconfirmed
  fill (free option; finality is confirmation only); publish an **unbacked rune order** (gated by the
  ord backing check when ord is present, else possible); spam the book.

### Taker
- **Can:** discover an order (indexer or raw artifact); build a fill (funding + rune edict + fee);
  broadcast; RBF own fill; in addressed mode, propose a fully-specified PSBT.
- **Cannot:** take the rune without reproducing output-0 = (price, payout_spk); alter the maker payout;
  be made to overpay within a tx they `SIGHASH_ALL`-signed; in addressed rune↔rune, get the maker to
  sign a tx that misroutes the counter-rune (`verify_addressed_rune_tx`).
- **Gains:** *snipe / fill-race* (lift the maker's public 0x83 input, higher fee — profitable only on
  mispriced orders); *cenotaph grief* of the maker in rune↔rune (closed in the verifier); fund from a
  stray-rune UTXO (self-harm).

### Indexer operator (brk-btx, `/api/v1/btx/*`)
- **Can:** omit orders (censor), inject fake orders, or report wrong prices to clients that trust the
  served data without re-verifying.
- **Cannot:** forge a maker signature → an injected order **can't be filled** (a fill rebuilds a real
  tx the maker sig must validate; `taker-fill` re-verifies the maker sig against the offer UTXO before
  building); cannot make a taker overpay; cannot steal funds.
- **Gains:** censorship; false book to *passive viewers*; the consensus hash lets a client *detect* a
  divergent book only if they cross-check (own indexer / compare hashes).
- **UNCERTAIN:** whether the terminal ever acts on a displayed-only (unverified) order; a taker who
  *acts* re-verifies, a viewer who *reads* trusts the indexer.

### Miner
- **Can:** pick which fill of a race to mine (incl. **self-filling** the maker's public input — the
  ultimate sniper); reorder/censor; reorg to orphan a fill.
- **Cannot:** forge sigs; take the rune without paying output-0; alter the maker payout.
- **Gains:** MEV on mispriced orders; reorg-recapture of a shallow fill.

### Relay node (P2P path)
- **Can:** drop/delay an announce or fill (censor); see mempool first.
- **Cannot:** alter a signed tx; forge orders.
- **Gains:** censorship; info/MEV edge (on-chain artifacts are public anyway).

### Third-party wallet (counterparty / external PSBT signer in addressed mode)
- **Can:** hand the other party a PSBT to sign.
- **Cannot (if protocol holds):** get the counterparty to sign value/routing they didn't agree to
  (`verify_addressed_tx` / `verify_addressed_rune_tx`).
- **Gains:** craft a PSBT that misroutes the counter-rune / underpays, hoping the victim signs without
  running the verify step.

### Mempool attacker (no privileged position)
- **Can:** observe broadcast fills + artifacts; build competing fills from the maker's public input;
  RBF-race; attempt pinning.
- **Cannot:** forge sigs; alter the maker payout; touch a confirmed fill.
- **Gains:** capture mispriced orders; grief takers (waste their broadcast).

### Relay-path attacker (privileged position — partial eclipse)
- **Can:** suppress/delay the victim's announces/fills; widen the snipe/double-spend window; feed a
  stale mempool view.
- **Cannot:** rewrite the victim's local chain (full-node validated); forge txs.
- **Gains:** censorship; eclipse-enabled double-spend windows; info advantage.
- **UNCERTAIN:** eclipse feasibility depends on peer diversity (standard-Bitcoin scope).

### ord-oracle operator / compromised ord (added)
- **Can:** misreport rune balances, divisibility, or sync height to btxd.
- **Cannot:** forge maker sigs or alter on-chain txs.
- **Gains:** induce a maker to publish an order it wrongly thinks is backed (or block legit rune ops);
  skew normalized prices. The rune↔rune verifier also runs the allocator over the *actual* runestone
  and ord-sync is gated, but ord remains a **trusted oracle for "what rune does this UTXO hold."**

### Local host / browser (added — notable)
- **Can:** any **local process** can POST to `127.0.0.1:<btxd port>` to drive wallet-signing actions
  (publish, fill, batch-fill, etch, swaps). btxd now enforces a **loopback `Host:` allowlist** (added
  2026-05-27) that blocks the cross-origin / DNS-rebinding browser path, so a remote web page can no
  longer drive it; a local process on the machine still can (there is no per-action consent gate — see
  "Key material & blast radius" below). Mutating POSTs are serialized behind one wallet lock.
- **Cannot:** read wallet keys directly (in Bitcoin Core), but can *drive* the wallet to sign/spend.
- **Gains:** make the user's node publish/fill/spend without the user's intent (local processes only).

### Supply-chain / bundle provider (added)
- **Can:** ship a tampered bitcoind/ord/brk_cli or frozen tool → total compromise.
- **Mitigation (intended, NOT yet enforced):** today this is a *pure trust assumption*. The standard
  reductions — reproducible builds, pinned/verified binary hashes for the bundled bitcoind/ord/brk_cli,
  and signature verification of the frozen Python tools — are documented here as the intended hardening,
  not claimed as shipped. Until they are, the bundle provider is fully trusted.

### Regulator / coercion (added)
- **Can:** compel an *indexer operator* to censor or misreport (see "Indexer operator" — detectable via
  the consensus hash, and an injected/omitted order is unfillable); compel the *supply-chain provider*
  (above); coerce the *user* directly (rubber-hose — out of scope for any software).
- **Cannot:** force a maker to be underpaid, forge a sig, alter a confirmed tx, or **create a single
  chokepoint to shut the market down** — the book is reconstructed from the public chain by ANY indexer,
  so coercing one operator censors only that operator's clients, not the protocol.
- **Net (censorship-resistance conclusion, made explicit):** BTX has **no central operator, custodian,
  or relay to coerce** — its strongest property. Residual coercion surfaces: (1) a coerced *indexer*
  (bypass: self-host / cross-check the consensus hash), (2) a coerced *supply chain* (bypass:
  reproducible builds, above), (3) base-layer miner/relay censorship (standard-Bitcoin scope). None stops
  a maker+taker who can reach the chain.

### Network observer / chain-analysis (added — privacy)
- **Can:** correlate a maker's orders — offer UTXO, payout address, and order parameters are all public —
  into a cluster (UTXO chain-analysis, payout-address reuse), and link the P2P broadcast of an
  announce/fill to the maker's IP (non-Tor). Profile a maker's pairs/sizes/timing and tie it to a KYC'd
  funding source.
- **Cannot:** forge or alter orders — this is observation, not tampering.
- **Gains:** **deanonymization** — the privacy cost of an on-chain, nothing-offchain book is that order
  flow is maximally public. **Mitigation (operator hygiene, not enforced by code):** fund offer UTXOs
  from un-reused / CoinJoin'd coins, don't reuse payout addresses, broadcast over Tor. Recorded here
  because the model previously treated "public anyway" as a shrug, not a named privacy risk.

---

## (c) Trust boundaries

**Signed (cryptographically committed):**
- Maker offer — `SIGHASH_SINGLE|ANYONECANPAY` over **only** the offer input's outpoint + output-0
  (value + scriptPubKey). Commits the maker payout exactly; commits **nothing else** — not other
  inputs, the taker output, the runestone/edicts, change, or any input `nSequence`.
- Taker funding — `SIGHASH_ALL` over the whole fill tx as the taker built it.
- Addressed mode (incl. rune↔rune) — maker signs `SIGHASH_ALL` over the whole finished tx (so it *does*
  commit the runestone routing + the maker's receiving output).
- Envelope carrier — BIP340 Schnorr over the BIP341 script-path sighash of the reveal tx.

**Verified (software checks vs chain data):**
- Indexer: each candidate order's maker sig verified against the offer UTXO's value+spk before it
  enters the book; fill/cancel by output-0 == (price, payout_spk); reorg rollback; order-set-independent
  consensus hash.
- Taker-fill: re-verifies the maker sig against `gettxout` before building.
- rune↔rune maker: `verify_addressed_rune_tx` — decode runestone, run allocator, output-0 must receive
  ≥ agreed counter-rune, must not be a cenotaph (output-bounds / rune-id-overflow / unrecognized-flag),
  output-0 spk == maker.
- Offer amounts come from the node's **own UTXO set** (`gettxout`), never from relay.

**Assumed honest:**
- The user's **own Bitcoin Core node + wallet** (validates chain, holds keys, signs honestly).
- The local **ord** oracle for rune balances/divisibility.
- **btxd is reached only by the legitimate local user** — localhost bind, no auth (weak).
- The chain (PoW, longest valid).
- For a passive viewer: the queried indexer, unless self-hosted / hash-cross-checked.
- The shipped binaries/tools (supply chain).

---

## (d) Attack surface by entry point

**On-chain / mempool data (primary BTX-specific untrusted input):** attacker-crafted artifacts
(OP_RETURN bytes, witness envelopes), runestones, and witnesses parsed by the indexer, carrier
extractors, and runes decoder. Where bugs concentrate (parser bounds-safety; runestone cenotaph
false-accepts; fill classification). Via confirmed blocks (indexer) and the mempool scan.

**RPC:** btxd → `bitcoin-cli` via `subprocess` **arg-lists (no `shell=True`)** → no shell injection;
worst case a malformed RPC arg (handled by Core). btxd → ord/brk HTTP responses are parsed JSON from
local-but-potentially-compromised/malformed services → parser robustness matters.

**P2P:** announce/fill propagation, mempool sniping, relay censorship, reorgs — standard Bitcoin P2P;
BTX order availability + fill finality ride on it.

**File:** the etch `--state-file` JSON **holds the reveal `seckey_hex`** (local FS-read → recover the
reveal key); the persisted fjall `btx_orders` store + datadir (local tamper); `BtxOfferKey` /
`CxoOrderRecord` ByteView deserialization assumes well-formed stored bytes (UNCERTAIN: panic-safety on
a corrupted store — local-tamper only); the bundle's binaries/HTML/frozen tools (supply chain).

**User input:** prices/amounts/rune-ids/outpoints/addresses flow into artifact fields, RPC args, and
runestone construction; numeric (u64) + dust bounds guarded; the artifact parser also treats *all
on-chain bytes* as adversarial input.

**Network response → terminal (browser):** btxd has **no Origin/Host/CORS/auth check** → any local
process or browser page can issue locality-authenticated POSTs (CSRF / DNS-rebinding) that drive
wallet-signing actions. The terminal renders served fields via **`innerHTML` with string
interpolation**; today only numeric/hex fields (`rune_id`="block:tx", txid, price, amount) → low XSS
risk, but the pattern is XSS-prone if a free-text served field (e.g., an ord rune name/symbol) is ever
rendered the same way.

---

## Explicitly uncertain (flagged for the audit)

*(Post-audit status, 2026-05-27. The audit pass driven by this model resolved #3 and #4 and shipped
code for the surfaces behind #1–#2; see `BTX-mainnet-hardening.md` items 8–9.)*

1. Whether the terminal ever acts on a *displayed-only* (not re-verified) order; whether any free-text
   field reaches `innerHTML` (XSS). **PARTIALLY RESOLVED:** audited every `innerHTML` interpolation —
   today *all* served fields that reach it are numeric or hex (`rune_id`="block:tx", txid hex,
   `artifact_hex` hex, price/amount numeric); **no free-text field is fetched or rendered anywhere**, so
   there is no live XSS. The latent pattern (a future rune-name/symbol column, plus `artifact_hex`
   embedded in an `onclick` attribute) is now closed defensively with an `esc()` HTML-entity escaper on
   the on-chain/indexer-derived fields. The "acts on a displayed-only order" half stands as designed: a
   taker who *fills* always re-verifies the maker sig against `gettxout` (`taker-fill`), so a fake
   injected order can be *displayed* but never *filled* — only a passive viewer trusts the served book.
2. btxd's DNS-rebinding exposure (no `Host:` validation observed); whether any deployment binds
   non-localhost. **RESOLVED (code) / RESIDUAL (deployment):** confirmed btxd had **no `Host:`/Origin
   check** — a real DNS-rebinding vector to drive wallet-signing actions. Now closed with a loopback
   `Host:` allowlist on every `do_GET`/`do_POST` (rejects non-loopback `Host:` with 403; the browser
   can't forge `Host:` to a loopback name). The *deployment* question — whether anyone binds btxd to a
   non-localhost interface — is an operator decision outside the code; the default is `127.0.0.1` and it
   should stay that way (no auth token beyond the loopback+Host guard).
3. ByteView deserialization panic-safety on a corrupted local store (local-tamper only). **RESOLVED:**
   confirmed both `From<ByteView>` impls (`BtxOfferKey`, `CxoOrderRecord`) indexed the buffer unchecked
   → panic on a truncated/corrupted entry. Now bounds-safe: short buffers degrade to inert values (a
   zeroed key that matches no outpoint; an empty-artifact/sentinel-status record skipped by every read
   path) instead of panicking. Test covers every sub-minimum length. (brk-btx `c33bddad5`.)
4. Completeness of "every subprocess call is an arg-list" across all tools (spot-checked, not
   exhaustive). **RESOLVED:** swept all six `subprocess.run` sites (`btxd.bcli`, `btxd.run_tool`,
   `btx_wallet`, `btx_envelope_publish`, `btx_test_all`, `btx_selftest`) — every one builds an
   arg-list with per-argument `str()` stringification, and a repo-wide search for `shell=` finds nothing.
   No shell interpretation anywhere; `btx_etch.py`/`btx.py` don't shell out at all.
5. Eclipse feasibility (peer-diversity dependent; standard-Bitcoin scope). **UNCHANGED:** not
   BTX-specific — it rides on standard Bitcoin P2P peer diversity; out of scope for the application
   code.

---

## Key material & blast radius (accepted architecture, 2026-05-27)

From the key-material trust-boundary audit. Two of these are deliberate design properties of a
self-custody **hot-wallet orchestrator**, recorded here as *accepted* (not bugs) so the trust model
is explicit rather than assumed.

**Two classes of key material:**
- **Class A — funds-bearing keys** (maker offer key, taker funding key, the wallet that pays
  announce/commit fees): live **only in Bitcoin Core**. Every production signing is a Core wallet RPC
  (`signrawtransactionwithwallet` / `walletprocesspsbt`); the application never holds, derives, imports,
  exports, or logs these keys (`dumpprivkey`/`importprivkey`/`signrawtransactionwithkey` appear nowhere).
  **Single trust boundary = Core wallet RPC.** Consequence: a compromise can *drive* signing but cannot
  *exfiltrate the seed*.
- **Class B — ephemeral Taproot internal keys** for the envelope/etch commit-reveal: generated in app
  memory (`os.urandom(32)`) and signed by the in-process `schnorr_sign`. They control **only the
  throwaway commit UTXO**, never the wallet. The envelope key is used once and not persisted; the etch
  reveal key is persisted to `--state-file` for resume — now written **owner-only (`0o600`)** so it is
  not a world-readable local-FS-read path (bitcoin-terminal-exchange `91d7a62`).

**ACCEPTED — (d) no per-action consent gate.** btxd signs whatever a local caller POSTs; the only
barrier is the loopback bind + `Host:` allowlist (blocks remote/rebinding) plus the serializing wallet
lock. There is no per-transaction confirmation prompt. This is intentional for a single-user local
orchestrator; the protocol checks (`verify_maker_sig`, output-0 commitment) bound *what* a valid tx is
(no overpay, no fake-order fill), not *whether* a local process can trigger a sign.

**ACCEPTED — (e) hot-wallet blast radius.** A compromised `btxd` (or any local process that can POST
to it) can construct and sign an arbitrary spend via Core's wallet RPCs and **drain the entire loaded
hot wallet**; `lockunspent` is no barrier (it can be released), and there is no amount cap, spend limit,
or hot/cold split (the bundle's default wallet is unencrypted, so no passphrase gate). The bound is that
keys stay in Core: the attacker can spend while btxd runs against the wallet, but cannot steal the
seed — moving funds to a wallet Core doesn't auto-load stops the bleeding. Operational guidance: run
BTX against a **dedicated thin wallet**, not a primary store of value. A per-action consent step or a
btxd spend cap would change this profile but is a product decision, not shipped.
