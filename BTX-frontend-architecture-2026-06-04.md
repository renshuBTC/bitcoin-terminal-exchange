# BTX frontend architecture + build sequence (2026-06-04)

**Purpose.** Make BTX accessible to non-technical users via a website (and
later a mobile app) while keeping the on-chain commitments that make BTX
meaningfully different from a centralized exchange. The Hyperliquid pattern
applies: one official frontend serves the convenience layer; the underlying
chain (Bitcoin, not a custom L1) carries the actual trades.

This document captures the architecture, the API surface, the frontend
stack, the deployment model, the trust-UI commitments, and the build
sequence. It is the spec a small team would execute against over 2–4
months.

---

## 1. Design constraints (from prior decisions)

These are settled, not up for re-debate in this doc:

- **Bitcoin only.** No custom L1, no sidechain, no rollup. The chain
  underneath is Bitcoin mainnet. Slower than Hyperliquid; that's the
  trade.
- **No custody.** Keys never leave the user's device. Signing happens
  in the wallet (browser extension on web; wallet app on mobile). The
  BTX frontend backend never sees a private key, ever.
- **Read API can be centralized.** Like Hyperliquid's API gateway, the
  BTX read API is one canonical service operated by the BTX team. Users
  can run their own indexer; most won't; that's the same compromise
  Hyperliquid makes with its L1 nodes.
- **Broadcasting forwarded, not gated.** Signed transactions submitted
  through the BTX API get forwarded directly to Bitcoin's mempool by
  the BTX-operated bitcoind. The BTX backend cannot inspect, modify,
  or hold the signed transaction beyond fast forwarding.
- **All code open source.** The indexer, the API, and the frontend are
  all open source so anyone can audit, fork, or stand up an alternative
  frontend. The credibility of the "convenience layer is not a chokepoint"
  pitch rests on this.

---

## 2. The architecture, in one diagram

```
                   ┌──────────────────────────────────────────────┐
                   │              Bitcoin mainnet                  │
                   │     (the actual chain; carries all state)     │
                   └────────▲───────────────────┬──────────────────┘
                            │                   │
                            │ blocks             │ signed tx
                            │                   │ (broadcast)
              ┌─────────────┴───────┐  ┌────────┴──────────┐
              │  bitcoind (BTX-op)  │  │  bitcoind (any)   │
              │  + ord  + brk_btx   │  │  user can self-   │
              │    indexer (Rust)   │  │  broadcast also   │
              │                     │  └───────────────────┘
              │  HTTP API (axum):   │
              │    GET  /v1/btx2/   │            ┌──────────────────┐
              │      orderbook      │ HTTPS      │  User's wallet   │
              │      orders         │◄───────────┤  (UniSat /       │
              │      stats          │            │  Xverse / Leather│
              │      state_root     │            │  / OKX) holds keys│
              │    POST /v1/btx2/   │            │  signs PSBTs     │
              │      broadcast      │ HTTPS      └───────▲──────────┘
              └─────────▲───────────┘                    │
                        │                                │
                        │ HTTPS (read)                   │ PSBT in/out
                        │                                │
              ┌─────────┴───────────┐                    │
              │  btx.exchange       │                    │
              │  (Next.js PWA)      │────────────────────┘
              │  one official       │
              │  frontend           │
              └─────────────────────┘
                        ▲
                        │
                        │ browser
                        │
                  ┌─────┴──────┐
                  │   user     │
                  └────────────┘
```

The three layers:

1. **Chain** — Bitcoin mainnet. Carries every BTX order, fill, cancel.
   This layer is untouched; BTX has no special status here.

2. **Indexer + API** — the `brk-btx` Rust indexer reading Bitcoin,
   exposing a clean HTTP read API via `brk_server` (axum 0.8.9, already
   on the dep graph; the existing `crates/brk_server/src/api/btx.rs`
   pattern is the template). One canonical instance runs at
   `api.btx.exchange`. Anyone can run another. The state-root endpoint
   lets clients cross-verify.

3. **Frontend** — Next.js PWA at `btx.exchange`. Reads from the API,
   talks to wallets for signing, submits broadcasts back through the
   API. The frontend never touches keys; the API never inspects signed
   payloads.

---

## 3. The HTTP API surface

The existing `crates/brk_server/src/api/btx.rs` defines BTX1 endpoints
(`/api/v1/btx/orders`, `/api/v1/btx/book-hash`, `/api/v1/btx/book-root`,
`/api/v1/btx/order-proof/{txid}/{vout}`, `/api/v1/btx/event-hash`,
`/api/v1/btx/event-stream`, `/api/v1/btx/groups`). The pattern is mature:
axum routes with `aide`-generated OpenAPI, `EtagCacheStrategy::Tip`
on every endpoint, JSON responses backed by per-domain View types from
`brk_indexer`.

The frontend backend needs BTX2 routes following the same pattern.
Promote the route set defined in `crates/brk_indexer/examples/btx2_http_server.rs`
into a new `crates/brk_server/src/api/btx2.rs` module:

| Route | Returns | Notes |
| --- | --- | --- |
| `GET /api/v1/btx2/orders` | `Vec<OrderView>` of state=OPEN | The default orderbook view |
| `GET /api/v1/btx2/orders/{order_id}` | `OrderView` or `null` | Single-order lookup by 36-byte hex id |
| `GET /api/v1/btx2/conditional` | `Vec<OrderView>` of state=CONDITIONAL | Oracle-attested orders awaiting trigger |
| `GET /api/v1/btx2/filled` | `Vec<OrderView>` of state=FILLED | Recent fills (paginated) |
| `GET /api/v1/btx2/cancelled` | `Vec<OrderView>` | For order-history views |
| `GET /api/v1/btx2/expired` | `Vec<OrderView>` | Cleanup tracking |
| `GET /api/v1/btx2/all` | `Vec<OrderView>` | Admin / debugging view; rate-limited |
| `GET /api/v1/btx2/stats` | `StateCounts` | Counts by state for top-of-page summary |
| `GET /api/v1/btx2/state_root` | `{root_hex, height, block_hash}` | The cross-indexer verification primitive |
| `GET /api/v1/btx2/healthz` | `{ok, tip_height, tip_blockhash}` | Liveness for monitoring |
| `POST /api/v1/btx2/broadcast` | `{txid, accepted, reason?}` | Forwards a raw signed tx to the BTX-operated bitcoind |

The `OrderView` type is already defined in `crates/brk_indexer/src/btx_v2_query.rs`:

```rust
pub struct OrderView {
    pub id: OrderId,
    pub state: OrderState,
    pub kind: OrderKind,          // SINGLE | BATCH | CONDITIONAL
    pub rune_id: Option<RuneId>,
    pub asset_amount: Option<u128>,
    pub price_sats_per_unit: Option<u64>,
    pub maker_pubkey: [u8; 32],
    pub expiry_height: Option<u32>,
    pub announce_height: u32,
    pub announce_txid: Txid,
    pub announce_vout: u32,
    // ... etc per existing struct
}
```

A `POST /broadcast` endpoint is the only mutating route. It accepts a
hex-encoded raw transaction, validates that it parses, forwards to the
BTX-operated bitcoind via JSON-RPC `sendrawtransaction`, returns the
txid on success or the bitcoind error verbatim on failure. **It does not
inspect or modify the transaction.** Documenting this commitment in the
API description is part of the trust pitch.

A WebSocket endpoint `WS /api/v1/btx2/stream` pushes the BTX2
state-update events (order added, filled, cancelled, expired) as JSON
messages, allowing the frontend to keep the UI live without polling.
This mirrors the existing `EventStreamBlockView` from BTX1 but pushes
incrementally rather than letting clients fetch.

---

## 4. The frontend (`btx-web`)

Repo: new `renshuBTC/btx-web` separate from brk-btx and bitcoin-terminal-exchange.
Justification: different language, different deploy lifecycle, different
maintainer model (anyone can fork the frontend without touching the
canonical indexer).

Stack:

- **Next.js 14+ (App Router)** — server-side rendering for SEO and
  fast initial loads; client-side React for interactive trading UI.
- **TypeScript** — type safety against the API schema; codegen the API
  types from the brk_server OpenAPI doc.
- **TanStack Query** — caches API responses, handles refetching, syncs
  with WebSocket updates.
- **Tailwind CSS + shadcn/ui** — component primitives without a heavy
  design-system commitment.
- **Wallet integrations**: UniSat, Xverse, Leather, OKX Wallet via
  their respective browser-extension APIs. All four implement standard
  PSBT-signing flows; the differences are namespace-level
  (`window.unisat` vs `window.XverseProviders.BitcoinProvider` etc).
  Library: `sats-connect` (Xverse-led but cross-wallet) or hand-rolled
  per-wallet adapters.
- **PWA via `next-pwa`** — installable on iOS and Android home screens.
  Mobile app comes later if there's demand for native UX.

Key pages:

- **`/`** — trading UI. Order book (bids + asks), depth chart, recent
  fills, order entry form (buy/sell BTC↔Rune), market selector.
- **`/orders`** — the connected wallet's own open orders + fills.
- **`/transparency`** — the API endpoint URL, state-root hash, last
  block processed, link to alternative indexers (when they exist), link
  to "run your own indexer" guide. Shown prominently in the footer too.
- **`/about`** — what BTX is, the trust model in plain language, links
  to source code on GitHub.
- **`/docs`** — protocol docs and the openapi.json for developers.

Page contracts (what each page reads from the API):

| Page | API calls | Update mechanism |
| --- | --- | --- |
| `/` orderbook | `GET /orders` + `WS /stream` | Initial fetch, then incremental events |
| `/` recent fills | `GET /filled?limit=50` | Polled every 10s + WS |
| `/` stats | `GET /stats` | Polled every 10s |
| `/orders` (logged in) | `GET /orders?maker_pubkey=<user_key>` | Polled on tab focus + WS |
| `/transparency` | `GET /state_root` + `GET /healthz` | Polled every 30s |

The frontend is fully bundled (no server-side state besides Next.js's
own SSR). Deployed as a static + edge-rendered build on Vercel,
Cloudflare Pages, or any static host. Zero backend state owned by the
frontend layer.

---

## 5. Wallet integration

**Read-only data is fetched without a wallet.** A user can browse the
orderbook, see fills, check market depth without connecting anything.

**Connecting a wallet enables three things:**

1. Show "your orders" (filter the orderbook by `maker_pubkey == <user pk>`).
2. Build and sign a BUY transaction (open-fill against an existing
   maker order).
3. Build and sign a SELL transaction (publish a new maker order).

**The signing flow for BUY:**

```
1. user clicks "buy 100 RUNE@<price>" against a specific maker order
2. frontend fetches the order's artifact bytes from /v1/btx2/orders/{id}
3. frontend constructs the open-fill PSBT:
     - input 0: maker's pre-signed offer UTXO (signature already included)
     - input 1+: user's funding UTXOs (chosen from wallet's getUtxos)
     - output 0: maker's payout (script_pubkey from artifact)
     - output 1: user's rune receipt UTXO
     - output 2: user's change UTXO
4. frontend calls wallet.signPsbt(psbt_hex, { signInputs: [1, ...] })
5. wallet UI pops up showing inputs/outputs; user reviews + approves
6. wallet returns signed PSBT
7. frontend finalizes PSBT into raw tx hex
8. frontend POSTs raw tx to /v1/btx2/broadcast
9. API forwards to bitcoind, returns txid
10. frontend shows "submitted, txid: ...", links to mempool.space
```

**The signing flow for SELL (publish a maker order):**

Same shape, with the user signing a SIGHASH_SINGLE|ANYONECANPAY (0x83)
input that becomes the offer UTXO, and the frontend constructing the
BTX2 artifact + envelope per the spec.

**Wallet abstraction layer.** A `useBitcoinWallet()` hook normalizes the
4+ wallet APIs into a single TypeScript interface:

```ts
interface BitcoinWallet {
  connect(): Promise<{address: string, pubkey: string, network: 'mainnet'|'signet'}>
  getUtxos(opts?: {minConfirmations?: number}): Promise<Utxo[]>
  signPsbt(psbtBase64: string, opts: {signInputs: number[], finalize: boolean}): Promise<string>
  // signMessage / signBip322 omitted from MVP; come later for maker attestation
}
```

Adapters for UniSat, Xverse, Leather, OKX wired behind that interface.

---

## 6. The trust UI — non-negotiable

Hyperliquid's trust pitch is implicit; BTX's must be explicit because
it's the differentiator.

**Persistent footer on every page:**

```
┌───────────────────────────────────────────────────────────────────────┐
│ Connected to btx.exchange API • Block 1,234,567 • State root abc1...  │
│                                                  [verify ↗]  [other ↗] │
└───────────────────────────────────────────────────────────────────────┘
```

- "verify" — opens transparency page with full state-root explanation
- "other" — picker for alternative indexer endpoints (initially empty;
  community-operated indexers added as they come online)
- block height + state root let advanced users sanity-check

**Transparency page sections:**

1. "What you're trusting right now" — the operator of `btx.exchange`,
   to display honest data, and the operator of `api.btx.exchange`, to
   not censor your broadcasts.
2. "What you are NOT trusting" — keys stay in your wallet; trades land
   on Bitcoin; the chain is the source of truth.
3. "Cross-verification" — explain state roots, show the current root,
   compare against alternative indexers (when N>1).
4. "Run your own" — one-paragraph + linked docs for spinning up a
   personal `brk-btx` indexer and pointing the website at it via URL
   parameter.
5. "Compare to centralized exchanges" — a small table showing what
   normal exchanges hold of yours vs what BTX touches. No FUD; just
   side-by-side facts.

**Broadcast safety.** Every confirmed broadcast page shows the txid,
a mempool.space link, and a "rebroadcast through your own node?"
optional flow for the paranoid. This costs nothing to implement and
buys real credibility.

---

## 7. Deployment model

**Indexer + API (`api.btx.exchange`):**

- Single VPS or cloud instance to start (e.g. Hetzner CX31 or similar,
  ~$20/month) running `bitcoind` + `ord` + `brk_btx` indexer + the
  axum server. Bitcoin pruned mode acceptable for the indexer's needs
  (txindex on, but historical blocks can be pruned past some depth).
- HTTPS via Caddy or nginx + Let's Encrypt.
- Rate limiting at the reverse proxy: generous on reads (e.g. 50/s/IP),
  strict on `/broadcast` (e.g. 5/min/IP) since each broadcast hits
  bitcoind.
- Health monitoring via `/healthz` + a UptimeRobot-style external
  prober.
- Backups: bitcoind's chainstate doesn't need backup (re-downloads).
  The indexer's `fjall` store can be backed up nightly to S3 for fast
  recovery vs full reindex.

**Frontend (`btx.exchange`):**

- Vercel deployment from the `btx-web` repo's `main` branch.
- Custom domain with Cloudflare in front for CDN + DDoS.
- Environment variable `NEXT_PUBLIC_API_URL=https://api.btx.exchange`
  defaults; advanced users can override via `?api=https://...` URL
  parameter for own-indexer use.
- No secrets in the frontend — the API URL is the only "config" and
  it's public.

**Total ongoing cost for MVP:** ~$30/month (VPS + domain + S3 backup).
Cloudflare and Vercel free tiers cover the frontend.

---

## 8. Build sequence (12-week MVP plan)

Aggressive but realistic for one focused engineer; double the estimate
for normal pace.

**Week 1–2: HTTP API in brk_server.**
- New `crates/brk_server/src/api/btx2.rs` module mirroring `btx.rs`
- Promote the routes from `examples/btx2_http_server.rs`
- Wire `add_btx2_routes` into `api/mod.rs`
- Add `POST /broadcast` that forwards to bitcoind
- Add `WS /stream` for live updates
- Integration tests against an in-memory store

**Week 3: API hardening + deployment.**
- Rate limiting middleware
- OpenAPI doc generation (already mostly free via `aide`)
- Single-instance deployment to a VPS
- TLS via Caddy
- Wired to a real mainnet bitcoind

**Week 4–6: Frontend MVP — read-only orderbook.**
- New `btx-web` repo, Next.js + TS + Tailwind + shadcn/ui scaffold
- Codegen TypeScript types from the OpenAPI doc
- Order book page (live, no trading yet)
- Recent fills page
- Transparency page with state-root display
- Deployed to vercel.app subdomain for review

**Week 7–8: Wallet integration.**
- `useBitcoinWallet` hook + 4 wallet adapters
- "Connect wallet" UI in the header
- "Your orders" filter view
- No signing yet — just identity + read

**Week 9–10: BUY flow.**
- PSBT construction in-browser for open-fill against a maker order
- `wallet.signPsbt` round-trip
- `POST /broadcast` integration
- "Submitted" success page with mempool.space link
- Manual testing on signet first, then a single mainnet trade with a
  small amount

**Week 11: SELL flow.**
- PSBT construction for publishing a maker order
- BTX2 artifact encoding (calls the existing Python tooling? or a port?)
- SIGHASH_SINGLE|ANYONECANPAY signing flow

**Week 12: Polish + launch.**
- Mobile-responsive sweep
- PWA install prompts
- Trust-UI prominence audit
- Public launch + announcement

**Post-MVP (months 4–6):**
- Native mobile app (React Native sharing UI components)
- Order history with txid links
- Cross-indexer comparison UI (requires at least one alternative
  indexer being operated)
- Maker pool ceremony coordinator UI (consumer of the Phase A/B work
  shipped 2026-06-04)

---

## 9. What this design does NOT include

Naming the omissions explicitly so they aren't accidentally added:

- **Custodial flows.** Never.
- **A BTX token.** Never. The architectural pitch dies if BTX
  introduces a token.
- **An off-chain order book.** Never. Orders are on Bitcoin.
- **A matching engine.** Open orders fill on first-valid-spender-wins;
  the frontend doesn't broker matches.
- **Fees collected by the BTX frontend operator.** The economic model
  is: the frontend is a public good; fees are Bitcoin's mining fees,
  paid by the broadcaster. If a fee model is ever added (e.g. premium
  features), it must be opt-in and not part of the trading path.
- **Account systems / email / KYC.** Wallet connection is the only
  identity. No registration, no profile.
- **Push notifications backed by a server.** Notifications can use
  Web Push, but the subscription lives in the user's browser, not
  associated with their wallet on the BTX backend.

---

## 10. Open questions for the implementer

Not blockers — things to decide as the work progresses:

1. **WebSocket vs SSE for `/stream`.** Both work; WebSocket is slightly
   nicer for the bidirectional case if "subscribe to specific market"
   gets added. SSE is simpler and survives more firewalls.
2. **Which wallet to prioritize.** UniSat has the largest install base
   for Ord/Runes users. Xverse has the cleanest API. Probably both,
   but if testing time is limited, UniSat first.
3. **State-root comparison fan-out.** Cross-verifying against one
   alternative indexer needs the alternative to exist. Plan: stand up
   a second indexer instance on a separate cloud provider as soon as
   the first is stable, even before any external operator joins.
4. **Network split.** Testnet → signet → mainnet rollout. Most of the
   testing happens on signet (which BTX has been on for months).
   Mainnet rollout is gated on at least one successful round-trip on
   signet for both BUY and SELL.
5. **Backend for the "your orders" filter.** Today the indexer doesn't
   index by `maker_pubkey`. Adding a secondary index is a small change
   to `Btx2Store`; do it during week 1–2.

---

## 11. Success criteria for the MVP

The launch is successful if:

1. A non-technical Bitcoin user can connect a wallet and see a live
   order book at btx.exchange.
2. The same user can place a small BUY against an existing maker order
   and see it confirm on Bitcoin (via mempool.space link).
3. A maker (likely the developer initially) can publish a maker order
   from the website and another user can fill it.
4. The transparency page makes clear what's trusted and what isn't,
   without being preachy.
5. The full stack is open source, documented, and someone external
   could in principle stand up a competing frontend in a weekend.

That's the bar. Volume, market depth, polished mobile UX, alternative
indexers — all come later. The MVP proves the architecture works
end-to-end.

---

*Authored 2026-06-04, after the BIP-327 multi-round verification port +
multi-org pool ceremony demos + decisions (commits 60ebb51 → 09b66aa).
This is the natural next layer: making the protocol-level work shipped
this session accessible to non-technical users via a Hyperliquid-style
website + future mobile app.*
