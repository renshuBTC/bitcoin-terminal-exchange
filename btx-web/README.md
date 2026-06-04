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
    layout.tsx                   — Minimal shell + OG / Twitter metadata + viewport
    page.tsx                     — Server component: parallel-fetches orders/health/state_root and composes the page
  components/
    TopNav                       — BT[X] logo + Trade indicator + Docs link + About popover + connect host
    AboutPopover                 — "?" button + popover explaining BTX (aria-expanded / aria-haspopup wired)
    WalletPicker                 — Dropdown listing 4 wallets + network chip on connected button (a11y annotated)
    WalletProvider               — React context: connect/disconnect/balance, dispatches by adapter id
    StatsHeader                  — Pair + Mark (live BRK close) / Last / Indexer / Height / Wallet / Stream Hash
    Chart                        — Sparkline backed by BRK price_close/day1 with offline fallback
    OrderBook                    — Asks + spread + bids; "synthetic" chip vanishes when OrderView is enriched
    TradePanel                   — Publish / Fill / OTC tabs; BIP-322 round-trip; copy-sig; fill_draft auto-preview
    SelectedOrderProvider        — React context: which row was clicked, with nonce for repeat-clicks
    SelectedOrderDetail          — Preview card above Fill artifact input (Side/Rune/Amount/Price/Maker)
    BottomTable                  — 5 tabs: Open Orders / Pending / Trade History / Balances / My Activity
    StatusBar                    — Polling /healthz every 30s; stale-poll detection; tip + open + state root + age
    MainGrid                     — 3-column layout wrapper for Chart + OrderBook + TradePanel
  lib/
    api.ts                       — Typed client: all 11 BTX2 routes + BRK price_close/address + fillDraft + body
    wallet.ts                    — BitcoinWallet adapter interface (network, signMessage, signPsbt, …)
    network.ts                   — EXPECTED_NETWORK + tone helper (mainnet → green, others → orange)
    attestations.ts              — localStorage log of BIP-322 publish/fill signatures (v1 schema, 50-row cap)
    wallets/
      unisat.ts                  — UniSat adapter (window.unisat) — direct-method API
      xverse.ts                  — Xverse adapter (window.XverseProviders.BitcoinProvider) — request-dispatch
      leather.ts                 — Leather adapter (window.LeatherProvider) — JSON-RPC-ish envelope
      okx.ts                     — OKX adapter (window.okxwallet.bitcoin) — direct-method API
  scripts/
    audit.py                     — Pre-commit static audit (4 checks; tsc skipped when node_modules absent)
    install-precommit.sh         — One-shot hook installer (opt-in; writes .git/hooks/pre-commit)
```

There is no `transparency/` route. The cross-indexer trust info lives
in the StatusBar (state root prefix + click-to-verify on Source).

## Pre-commit audit (recommended)

The repo ships a tiny pure-Python static audit at
`scripts/audit.py`. It catches four classes of bugs that have actually
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
4. **TypeScript type-check.** Runs `tsc --noEmit` when
   `node_modules/typescript` is present. Skipped gracefully on
   fresh shells without an install — so pre-commit still works
   right after clone. Catches everything the structural audits
   can't: wrong argument types, missing required props, mistaken
   `Promise<T>` vs `T`, undefined access.

Install once, then it runs automatically on every commit that
touches `btx-web/`:

```sh
bash btx-web/scripts/install-precommit.sh
```

You can bypass with `git commit --no-verify` when you need to.
Standalone run: `npm run audit` from `btx-web/`.

## API the frontend expects

Routes documented in `crates/brk_server/src/api/btx2.rs` of the
`brk-btx` repo (most recent commits in the brk-btx repo's
`COMMIT_*.md` files at the repo root).

| Method | Path | Used by |
| --- | --- | --- |
| GET | `/api/v1/btx2/orders` | OrderBook + BottomTable |
| GET | `/api/v1/btx2/orders/{id}` | Single-order detail |
| GET | `/api/v1/btx2/orders/{id}/body` | ActivityRow `fetch` button (commit B) |
| GET | `/api/v1/btx2/orders/{id}/fill_draft` | TradePanel structural fill preview (commit D) |
| GET | `/api/v1/btx2/conditional` | BottomTable Pending tab |
| GET | `/api/v1/btx2/filled` | BottomTable Trade History tab |
| GET | `/api/v1/btx2/stats` | StatsHeader |
| GET | `/api/v1/btx2/state_root` | StatusBar Stream Hash |
| GET | `/api/v1/btx2/healthz` | StatusBar live dot (polls every 30s) |
| POST | `/api/v1/btx2/broadcast` | (Publish + Fill broadcast — wallet-side TX assembly) |

Plus the standard BRK routes inherited by the fork:

| Method | Path | Used by |
| --- | --- | --- |
| GET | `/api/series/price_close/day1/data?limit=N` | Chart 90-day sparkline |
| GET | `/api/series/price_close/day1/latest` | StatsHeader live BTC mark |
| GET | `/api/address/{addr}` | WalletProvider balance (non-UniSat adapters) |

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
