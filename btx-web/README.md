# btx-web

Frontend for BTX — the fully on-chain Bitcoin exchange. Built per the
12-week MVP plan in `../BTX-frontend-architecture-2026-06-04.md`.

## What this is

A Next.js 14 + TypeScript + Tailwind app that talks to a `brk_server`
BTX2 API and displays a Bitcoin-native orderbook to a non-technical
user.

**Status:** scaffold. The orderbook fetch + transparency page work
against any running `brk_server` BTX2 API. Wallet integration and trade
flows arrive in subsequent commits per the build plan.

## Run locally

```sh
npm install
npm run dev
```

Open <http://localhost:3000>.

Set `NEXT_PUBLIC_API_URL=https://api.btx.exchange` (or your own
indexer) before `npm run dev` to point at a remote API. The default
points at `http://localhost:3110`, the development brk_server port.

## API the frontend expects

All routes are documented in `crates/brk_server/src/api/btx2.rs` of the
`brk-btx` repo (commits `8b08c83` + `7eb3510`):

| Method | Path | Used by |
| --- | --- | --- |
| GET | `/api/v1/btx2/orders` | orderbook page |
| GET | `/api/v1/btx2/orders/{id}` | (BUY flow, week 9-10) |
| GET | `/api/v1/btx2/stats` | orderbook page top-of-summary |
| GET | `/api/v1/btx2/state_root` | transparency page + footer |
| GET | `/api/v1/btx2/healthz` | trust footer |
| POST | `/api/v1/btx2/broadcast` | (BUY / SELL flow, week 9-11) |

## Trust commitments encoded in this scaffold

Per build-plan §6, the trust UI is non-negotiable. The scaffold ships
them as load-bearing elements:

1. **Persistent footer** (`src/components/TrustFooter.tsx`) showing the
   connected indexer host + block height + state-root hash, plus
   "verify ↗" and "run your own ↗" links.

2. **Transparency page** (`src/app/transparency/page.tsx`) listing what
   the user is and isn't trusting, the current state root, and a
   side-by-side comparison with regular centralized exchanges.

3. **Honest MVP framing on the home page** (`src/app/page.tsx`):
   tells the user the wallet/buy/sell flows aren't wired yet rather
   than pretending they are.

The product credibility argument depends on these being correct, so
changes to them should be deliberate.

## Build plan reference

See `../BTX-frontend-architecture-2026-06-04.md`. Quick week map:

- **Week 1-2:** brk-btx HTTP API surface (shipped)
- **Week 3:** API hardening + deployment
- **Week 4-6:** Frontend MVP — read-only orderbook (this scaffold)
- **Week 7-8:** Wallet integration (UniSat / Xverse / Leather / OKX)
- **Week 9-10:** BUY flow (PSBT construction + signing + broadcast)
- **Week 11:** SELL flow (publish a maker order)
- **Week 12:** Polish + launch

## License

Same as the parent `bitcoin-terminal-exchange` repo. All open source.
