# BTX — bundling recipe (Phase 3d: toward a single-download install)

The roadmap's Phase 3 exit is *"a non-developer installs once and completes a signet trade from the
GUI."* The trade-from-GUI half is done (`btxd` + `btx_app.html`, proven on signet). This doc covers
the **install-once** half honestly: what we have, the realistic packaging targets, and the genuine
friction.

## What's already done toward it
- **One-command launcher — `btx-launch.sh`.** Starts node → indexer → orchestrator → opens the GUI,
  idempotent, with `stop`. This collapses the multi-terminal bring-up into a single command. It is the
  *behavioural* core of "install once and run"; what remains is packaging the pieces so there's nothing
  to install or build by hand.
- **Auto first-run:** the launcher creates/loads the wallet; `btxd` auto-loads it; the GUI opens.

## What a real bundle must contain
1. `bitcoind` + `bitcoin-cli` (Bitcoin Core v29.1) — per-OS binaries (~40 MB).
2. `brk_cli` — the brk-btx indexer, a **native per-OS build** (today built in WSL; a native Windows
   build is unverified).
3. `btxd` + the BTX python tooling (`btx_wallet.py`, `btx_envelope_publish.py`, `btx_*`),
   plus their one dependency `python-bitcoinlib` — either a system `python3` or a **frozen** bundle
   (PyInstaller) so the user needs no Python.
4. The static UI (`btx_app.html`, `index.html`, `btx_*.html`).
5. `btx-launch.sh` (or a small native launcher) + a default config.

## Realistic packaging targets (pick ONE OS first — do not chase universal)
- **Linux / WSL single archive (most tractable):** PyInstaller-freeze `btxd` + the tooling into one
  executable; drop `bitcoind`, `bitcoin-cli`, `brk_cli`, the UI, and a `run` wrapper into a `tar.gz` (or
  an **AppImage**). User: download one file, extract, `./run` → the GUI opens. No system Python, no
  cargo, no manual node setup. **This is the recommended first deliverable** — it's a genuine
  "download-one-thing-and-run."
- **Windows (more friction):** needs native Windows builds of `bitcoind` (exists) **and** `brk_cli`
  (Rust → `x86_64-pc-windows-*` cross-compile, unverified) plus a frozen `btxd`. Alternatively ship
  the Linux bundle to run inside WSL/a container. A polished `.msi` + code-signing is real productionization.

## Honest friction / out of scope for a research preview
- **Node + indexer currently run in WSL** on your Windows box, so a true non-dev *Windows* one-click is
  the hard case — the cleanest near-term answer is the Linux/WSL archive above, or a containerized bundle.
- **Mainnet data.** A live mainnet BTX is a hundreds-of-GB initial sync; an installer can't hide that.
  Signet/regtest bundles are small and demoable; mainnet is a deliberate user choice.
- **Code signing, auto-update, crash handling, a native window** (vs. opening the system browser) are
  productionization, not preview-level.

## Recommended next concrete step
Build the **Linux/WSL `tar.gz` (or AppImage)**: PyInstaller-freeze `btxd`+tooling, assemble it with the
`bitcoind`/`brk_cli` binaries + UI + a `run` wrapper that calls the launcher logic, and verify a
non-developer flow: extract → `./run` → GUI opens → faucet a New address → publish + fill a signet trade.
That delivers the Phase-3 exit criterion as a single download for one OS; cross-platform installers come
after, if ever (they may not be worth it for a research preview).
