# btx-web

Frontend for BTX — the fully on-chain Bitcoin exchange. Per
`BTX-single-page-decision-2026-06-04.md`, this app has exactly one
page: the trade page. It mirrors the layout of `btx_trade.html` (the
installer's UI) so the website and the installer present the same
experience.

## What this is

A Next.js 14 + TypeScript + Tailwind app that talks to a `brk_server`
BTX2 API and displays the BTX trade page to a non-technical user.

## Run locally

```sh
npm install
npm run dev
```

Open <http://localhost:3000>.

Set `NEXT_PUBLIC_API_URL=https://api.btx.exchange` (or your own
indexer) before `npm run dev` to point at a remote API. Default is
`http://localhost:3110`, the development brk_server port.

## Layout (one page, eight components)

```
src/
  app/
    globals.css     — BTX design tokens (#000 / #ff8c00 / Source Code Pro)
    layout.tsx      — minimal shell (just <body>)
    page.tsx        — server component: fetches + composes the trade page
  components/
    TopNav          — BT[X] logo + Trade indicator + Docs + oracle/sync pills + Connect
    StatsHeader     — pair + Mark / Last / Indexer / Height / 24h Vol / Wallet / Stream Hash
    Chart           — TradingView-style sparkline (client component, SVG today)
    OrderBook       — 5 ask rows + spread + 5 bid rows with depth bars
    TradePanel      — Open / Addressed mode toggle, Publish / Fill / OTC tabs, full form
    BottomTable     — Open Orders / Pending / Trade History / Balances tabs (client component)
    StatusBar       — live dot + block height + state root prefix + Source link
  lib/
    api.ts          — typed client for all 11 BTX2 endpoints
    wallet.ts       — BitcoinWallet adapter interface (UniSat/Xverse/Leather/OKX)
```

There is no `transparency/` route. The cross-indexer trust info lives
in the StatusBar (state root prefix + click-to-verify on Source).

## API the frontend expects

All routes documented in
`crates/brk_server/src/api/btx2.rs` of the `brk-btx` repo (commits
`8b08c83` + `7eb3510`):

| Method | Path | Used by |
| --- | --- | --- |
| GET | `/api/v1/btx2/orders` | OrderBook + BottomTable |
| GET | `/api/v1/btx2/orders/{id}` | (Fill tab, week 9-10) |
| GET | `/api/v1/btx2/stats` | StatsHeader |
| GET | `/api/v1/btx2/state_root` | StatusBar + Stream Hash metric |
| GET | `/api/v1/btx2/healthz` | StatusBar live dot + StatsHeader |
| POST | `/api/v1/btx2/broadcast` | (Publish + Fill flows, weeks 9-11) |

## Trust commitments

Per build-plan §6, the trust UI is non-negotiable. Encoded:

1. **StatusBar shows the indexer endpoint and state root** prominently
   at the bottom of every screen.
2. **No custodial flows.** The TradePanel's Connect button hands off to
   the user's Bitcoin wallet (UniSat, Xverse, Leather, OKX); signing
   never happens in this app.
3. **Open source.** Both the API (brk-btx) and this frontend are on
   GitHub; anyone can fork either or stand up an alternative.

## Single-page rules

If a future feature seems to need a separate page: don't. Add a tab in
one of the existing card-tab strips:

- New trading mode? Add to the panel-modes toggle in TradePanel.
- New chart? Add a tab to the chart `ch-tabs` strip in Chart.
- New table view? Add a tab to BottomTable.

The single-page decision is documented at
`../BTX-single-page-decision-2026-06-04.md`. Treat exceptions as design
red flags.

## License

Same as the parent `bitcoin-terminal-exchange` repo. All open source.
