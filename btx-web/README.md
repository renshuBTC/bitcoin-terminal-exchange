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

## Environment variables

| Var | Default | What it does |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:3110` | brk-btx base URL. Set to your prod endpoint (e.g. `https://api.btx.exchange`) for deploys. |
| `NEXT_PUBLIC_BTC_NETWORK` | `mainnet` | Which Bitcoin network this deployment is for. Wallets connected to a different network see a red "Network mismatch · sign disabled" banner and can't sign. Valid values: `mainnet`, `signet`, `testnet`. |

## Layout (one page; full component tree)

```
src/
  app/
    globals.css                  — BTX design tokens (#000 / #ff8c00 / Source Code Pro)
    layout.tsx                   — minimal shell (just <body>)
    page.tsx                     — server component: fetches + composes the trade page
  components/
    TopNav                       — BT[X] logo + Trade indicator + Docs + connect button host
    WalletPicker                 — Popover with 4 detected wallets + network chip on connected button
    WalletProvider               — React context: connect/disconnect/balance, dispatches by adapter id
    StatsHeader                  — pair + Mark (live BRK) / Last / Indexer / Height / Wallet / Stream Hash
    Chart                        — Sparkline backed by BRK price_close/day1 with offline fallback
    OrderBook                    — Asks + spread + bids; "synthetic" chip until OrderView gains fields
    TradePanel                   — Publish / Fill / OTC tabs; sign round-trip + result strips + copy
    SelectedOrderProvider        — React context: which row was clicked, with nonce for repeat-clicks
    SelectedOrderDetail          — Preview card above Fill artifact input (Side/Rune/Amount/Price/Maker)
    BottomTable                  — 5 tabs: Open Orders / Pending / Trade History / Balances / My Activity
    StatusBar                    — Polling indicator + tip height + open count + state root + age + Source
    MainGrid                     — 3-column layout wrapper for Chart + OrderBook + TradePanel
  lib/
    api.ts                       — Typed client: all 11 BTX2 routes + BRK price_close + address balance
    wallet.ts                    — BitcoinWallet adapter interface (network, signMessage, signPsbt, …)
    network.ts                   — EXPECTED_NETWORK + tone helper (mainnet → green, others → orange)
    attestations.ts              — localStorage log of BIP-322 publish/fill signatures (v1 schema, 50-row cap)
    wallets/
      unisat.ts                  — UniSat adapter (window.unisat) — direct-method API
      xverse.ts                  — Xverse adapter (window.XverseProviders.BitcoinProvider) — request-dispatch
      leather.ts                 — Leather adapter (window.LeatherProvider) — JSON-RPC-ish envelope
      okx.ts                     — OKX adapter (window.okxwallet.bitcoin) — direct-method API
  scripts/
    audit.py                     — Pre-commit static audit (3 checks, no node_modules required)
    install-precommit.sh         — One-shot hook installer (opt-in; writes .git/hooks/pre-commit)
```

There is no `transparency/` route. The cross-indexer trust info lives
in the StatusBar (state root prefix + click-to-verify on Source).

## Pre-commit audit (recommended)

The repo ships a tiny pure-Python static audit at
`scripts/audit.py`. It catches three classes of bugs that have actually
broken master in this project:

1. **Tailwind tokens.** Every `bg-foo` / `text-foo` / `border-foo`
   class in a `.tsx` file must correspond to a token declared in
   `tailwind.config.ts`. Catches typos like `bg-menu` when only
   `menu-soft` was declared.
2. **Named imports vs exports.** Every `import { X } from './Y'`
   must resolve to a real named export of `Y`. Catches typos and
   the `useSelectedOrder` regression where a hook went missing.
3. **Bracket balance.** Every `.ts` / `.tsx` file must have
   matching `{}`, `()`, `[]` counts, parsed against strings /
   template literals / comments. Catches silent mid-file
   truncation by a linter/auto-formatter (the bug that ate
   `api.ts` and `Chart.tsx` in commits `c372488` / `fd18901`
   before this check existed).

Install once, then it runs automatically on every commit that
touches `btx-web/`:

```sh
bash btx-web/scripts/install-precommit.sh
```

You can bypass with `git commit --no-verify` when you need to.
Standalone run: `npm run audit` from `btx-web/`.

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
