# BTX is a single-page app — both installer and website (2026-06-04)

**Decision.** BTX has exactly one user-facing page: the trade page. Both
the installer-bundled version (rendered locally by `btxd`) and the
hosted website version (`btx-web/`) ship only this page. No nav links
to secondary pages, no marketing landing, no separate Book / Trades /
Create / Attest / Wallet / Activity pages.

## What this means concretely

### Installer (the local bundle)

- `index.html` is now a `meta refresh` + `window.location.replace` to
  `btx_trade.html`. Any user landing on `/` ends up on the trade page
  in under 100ms.
- `btx_trade.html` is the only page in the user-visible nav. The
  navlinks block contains just the BTX logo, the (active) `Trade`
  indicator, and a `Docs` external link.
- The status bar at the bottom is trimmed to just the `Source` link;
  the `Recent on-chain fills` and `Home` links are removed because
  there's no second page to go to.
- `app/src/install.rs` BUNDLED_HTML is slimmed from 9 pages to 3:
  - `btx_trade.html` (the user-facing UI)
  - `btx_daemons.html` (bootstrap-only, shown during launch by the
    Tauri host while bitcoind/ord/btxd start up)
  - `btx_setup.html` (first-run wizard, shown when no wallet exists)
- The orphaned `btx_book.html`, `btx_trades.html`, `btx_create.html`,
  `btx_attest.html`, `btx_wallet.html`, `btx_activity.html`,
  `btx_order.html` files remain in the repo for historical reference
  but are no longer shipped to users.

### Website (hosted)

- `btx-web/preview.html` ships exactly the same single page.
- The future Next.js app (`btx-web/src/app/page.tsx`) becomes the only
  route. The `/transparency` page is folded into a collapsible section
  in the trade page footer rather than a separate URL.

## Why

The Hyperliquid pattern that BTX is positioning against has one main
page. The orderbook + chart + trade panel + your-orders table all live
on the same screen because that's where a user spends 100% of their
time. Splitting into Book / Trades / Create / Wallet / Activity tabs is
inherited from the prototype phase when each feature was scaffolded
independently; it doesn't reflect how the product is actually used.

Every existing secondary page is reachable from inside the trade page:

| Old page | Where the same functionality lives now |
| --- | --- |
| Book | left-column orderbook in `btx_trade.html` |
| Trades | "Trade History" tab in the bottom table |
| Create | "Publish" tab in the right-column trade panel |
| Attest | folded into the publish flow (BIP-322 maker attestation) |
| Wallet | "Balances" tab in the bottom table + Wallet metric in stats strip |
| Activity | "Pending" tab in the bottom table |
| Order detail | clicking a row in the orderbook auto-loads the artifact into the Fill tab |

So no functionality is lost. The user just stops navigating between
pages and instead does everything on one screen.

## What this enables for the website (`btx-web`)

The Next.js architecture becomes radically simpler — one route, one
component tree. Wallet integration (build plan §5) hooks into the same
trade panel rather than a separate `/wallet` page. The build plan
§4's "key pages" list collapses from 5 entries to 1 + a transparency
section.

## What this DOESN'T change

- The HTTP API surface (11 routes in `crates/brk_server/src/api/btx2.rs`).
  The website still reads from `/api/v1/btx2/orders`, `/stats`,
  `/state_root`, etc. — the consolidation is purely a UI choice.
- The wallet trust model. Keys still stay in the user's wallet; the
  frontend never holds keys.
- The state-root cross-verification path. The trust indicator still
  shows in the bottom status bar (where the "live · sync · oracle"
  pills already live).

## Companion commits

- `btx_trade.html`: navlinks stripped to Trade + Docs; status bar
  trimmed.
- `index.html`: replaced with `meta refresh` to `btx_trade.html`.
- `app/src/install.rs`: BUNDLED_HTML slimmed from 9 pages to 3 (trade,
  daemons, setup).
- `btx-web/preview.html`: navlinks + status bar match the installer.

## What to do if a future feature needs a separate page

Don't add one. Add a tab in one of the existing card-tab strips:

- New trading mode? Add to the panel-modes toggle (`Open · 0x83 /
  Addressed · PSBT`).
- New chart? Add a tab to the chart `ch-tabs` strip.
- New table view? Add a tab to the bottom `btabs` strip.

If a genuinely new top-level page becomes unavoidable (rare), the
right path is to add it as a navlink in `btx_trade.html`'s `navlinks`
div explicitly — but treat that as a design red flag, not a default.
