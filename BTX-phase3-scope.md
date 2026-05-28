# Scope — Phase 3: one-installer bundle + unified GUI

**From the roadmap (`BTX-architecture-and-build-sequence.md`).** *One installer; GUI surfaces node
status, mining controls (`getblocktemplate`/`submitblock`), wallet, and a DEX panel reading from the
local indexer.* **Exit criterion:** a non-developer can install once and complete a signet trade from
the GUI.

This realizes the project's one-line vision: **one downloadable program doing "everything Bitcoin"** —
full node + self-custody wallet + solo-mining controls + the chain-reconstructed on-chain order-book
DEX — with no website/server/middleman. Locked architecture decision: a **one-installer bundle, NOT a
bitcoin-qt fork.**

---

## What we already have (reuse, not rebuild)

- **Full node:** Bitcoin Core v29.1 (`bitcoind`), proven on regtest/signet/public-signet.
- **Indexer + HTTP API:** `brk-btx` (`brk_cli`) serving `/api/v1/btx/{orders,groups,history,swaps,trades}`.
- **Wallet + DEX tooling (proven):** `btx_wallet.py` (maker-sign / taker-fill), `btx_envelope_publish.py`
  (commit/reveal publish), `btx.py` (CLI over the primitives). BTX never holds keys — Core's wallet signs.
- **Web UI (read-only today):** `index.html`, `btx_book.html`, `btx_order.html`, `btx_create.html`
  (a *command builder*), `btx_trades.html`. These fetch the indexer API; they don't execute actions.

So ~80% of the *functionality* exists. Phase 3 is about **orchestration, a unified GUI, GUI-driven
actions, and packaging** — not new protocol work.

## What's new (the Phase-3 work)

1. **A local orchestrator backend ("btxd").** A small local service (bound to 127.0.0.1) that the GUI
   calls for everything the static HTML can't do:
   - **node status** — `getblockchaininfo` / `getpeerinfo` / `getnetworkinfo` (sync %, height, peers).
   - **mining controls** — `getblocktemplate` / `submitblock` (and a "mine N" button on regtest/signet).
   - **wallet** — `getbalances`, `listunspent`, `getnewaddress`, send.
   - **DEX actions** — `POST /order/create` and `POST /order/fill` that *execute* the proven
     `btx_wallet.py` / `btx_envelope_publish.py` flows server-side (this is what turns the
     command-builder pages into one-click actions).
   - serves the static UI.
   Lowest-effort path: a Python service (FastAPI/Flask) that imports the existing tooling (it's already
   Python and proven). A Rust rewrite would package more cleanly into one binary but duplicates working code.
2. **A unified GUI (dashboard).** One app shell tying together: node-status header, wallet panel,
   mining panel, and the DEX panel (the existing book/trades/create pages, re-pointed at `btxd`).
3. **GUI-driven trade flow.** `btx_create.html` stops being a command builder and instead POSTs to
   `btxd` to sign + publish; fills likewise. This is what the exit criterion actually tests.
4. **One-installer packaging (the hard tail).** Bundle `bitcoind` + `brk_cli` + `btxd` + the UI into a
   single installable that launches them together and opens the GUI. This is the riskiest part — see costs.

## Recommended approach: local launcher + browser GUI

A single launcher executable that starts `bitcoind` + `brk_cli` + `btxd`, then opens the browser (or a
thin webview) at `btxd`'s local UI. This matches the "bundle, not a qt-fork" decision, **reuses the
entire existing web UI and Python tooling**, and is incrementally buildable/testable. (A native
Tauri/Electron shell is a later polish, not needed to hit the exit criterion.)

## Sub-phasing (cheap → expensive, each independently testable)

- **3a — orchestrator `btxd` (the keystone).** Build the local backend: node-status + wallet + mining
  proxies, and `POST /order/{create,fill}` executing the proven tooling. Test on signet from `curl`.
  Everything else depends on this.
- **3b — unified GUI dashboard.** A single page wiring node-status/wallet/mining/DEX to `btxd`; fold
  the existing pages into it. Test in a browser against `btxd`.
- **3c — GUI-driven trade on signet.** Make create + fill one-click through the GUI; complete a real
  signet trade end-to-end from the browser (no CLI). This is the **exit criterion** (minus the installer).
- **3d — one-installer packaging.** The single-download bundle + launcher. Tackle last, after 3a–3c prove
  the app works wired-up.

## Honest cost / risk — read before committing

- **This is the largest remaining phase.** It's an application + packaging effort, not a per-function
  increment. 3a–3c are bounded and buildable; 3d is open-ended.
- **Packaging is genuinely hard, especially cross-platform.** Today the node + indexer run in **WSL** on
  your Windows machine. A true "non-dev installs once on Windows" bundle means either shipping a native
  Windows build of `brk_cli` (you currently build it in WSL — native Windows build unverified) or
  shipping the whole thing inside a WSL/container, both of which add real friction. Realistic first
  target: a **single-OS bundle** (pick Linux/WSL *or* Windows) rather than universal.
- **I can't run a GUI/desktop in this environment.** I build `btxd` + the UI; you run the launcher +
  browser in WSL/Windows to verify. (Same model as the Rust work: I write, you run.)
- **Self-custody wallet UX is sensitive.** A GUI that triggers real signing/sending needs care
  (confirmations, no key exposure) — `btxd` must keep using Core's wallet to sign and never touch keys,
  exactly as the CLI tooling already does.

## Recommendation

Start with **3a — the `btxd` orchestrator.** It's the keystone every other piece needs, it's bounded,
and it's testable on your existing signet node via `curl` before any GUI or packaging. Defer **3d
(packaging)** until 3a–3c prove the wired-up app completes a signet trade from the browser. We can decide
the single-OS packaging target when we get there.

*Open question for you:* Python `btxd` (fastest — imports the proven tooling) or a Rust `btxd`
(cleaner single-binary packaging later, but reimplements working code)? My recommendation: **Python
first** to hit the exit criterion, with a Rust rewrite as an optional packaging-time optimization.
