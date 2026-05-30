# btx-app — Tauri shell

The native-window wrapper for BTX. Eventually this becomes the one application
that ships to end users (Bitcoin Core + brk_cli + ord + btxd + UI in one
installable program). M1 just opens the existing web UI in a native window.

## M1 — what works right now

A native Windows / Linux / macOS window that loads `http://127.0.0.1:3333` —
the URL where `btxd` already serves the BTX UI. No daemons are bundled yet;
you still start them with `bash btx-launch.sh` in WSL the way you do today.
The point of M1 is to prove the shell itself works.

## Prerequisites

You need Rust + Tauri's system dependencies installed on the OS you want to
build for. Tauri 2.x is the target version.

### Windows (native — recommended for M1)

1. Install Rust from https://rustup.rs (run `rustup-init.exe`, accept defaults).
2. Install Microsoft Edge WebView2 if you don't have Windows 11 (Windows 10
   needs it explicitly — `MicrosoftEdgeWebView2RuntimeInstallerX64.exe`).
3. Install Microsoft C++ Build Tools (the Tauri installer warns if missing).
4. Install the Tauri CLI:
   ```
   cargo install tauri-cli --version "^2.0"
   ```

### Linux / WSL (alternative)

```
sudo apt update
sudo apt install -y libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
cargo install tauri-cli --version "^2.0"
```

WSL can run the dev build (a window appears via WSLg on Windows 11). For a
distributable Windows installer (M5) you'll need to build on Windows itself
or set up cross-compilation.

## Run the shell (dev mode)

In a terminal where `cargo` is on PATH:

```
cd "/path/to/bitcoin-terminal-exchange/app"
# Windows PowerShell example:
#   cd "C:\Users\Ren Shu\Documents\Claude\Projects\bitcoin-terminal-exchange\app"

# Make sure btxd is already running first (separate terminal in WSL):
#   bash btx-launch.sh

# Then start the Tauri shell:
cargo tauri dev
```

The first invocation will download and compile a few hundred crates — expect
5-15 minutes cold. After that, incremental builds are seconds.

What you should see: a native window titled "BTX — Bitcoin Onchain Exchange"
opens, showing the same page you'd see at http://127.0.0.1:3333/ in a browser.
The dark theme is requested up front so the title bar matches BTX's aesthetic
on Windows 11 / GNOME / macOS Big Sur+.

## Build a release binary

```
cargo tauri build
```

Produces a `.exe` on Windows, `.AppImage` / `.deb` on Linux, `.dmg` on macOS.
These are placed under `target/release/bundle/`. **Not yet the M5 installer**
— this just packages the shell itself. Bundled daemons land in M5.

## Verify the Rust↔frontend bridge

`src/lib.rs` exposes a `ping` IPC command. You can confirm IPC works by
opening DevTools in the shell window (right-click → Inspect, or F12) and
running:

```js
await window.__TAURI__.core.invoke('ping')
// → "pong from btx-app"
```

If you get the pong string, M1 is fully functional. From here we add
process supervision (M2 → M3), the first-launch wizard (M4), and the
Windows installer (M5).

## File layout

```
app/
├── Cargo.toml          # Rust package config
├── tauri.conf.json     # Tauri config (window, devUrl, bundle settings)
├── build.rs            # Generates Tauri metadata at compile time
├── README.md           # this file
├── .gitignore
├── icons/              # (M5) icon assets in all required sizes
└── src/
    ├── main.rs         # entry point — calls btx_app_lib::run()
    └── lib.rs          # Tauri Builder + IPC commands
```

`icons/` is currently empty — `cargo tauri build` will fail at the bundle
step without icons, but `cargo tauri dev` works fine without them. Real
icons land in M5 alongside the installer work.

## Where this is going (M2 onward)

- **M2**: `lib.rs::run()` spawns `btxd` (via `std::process::Command`) before
  the window opens. Window appears only after `/api/config` responds.
- **M3**: Same pattern extended to `bitcoind`, `brk_cli`, `ord`. Each gets a
  supervisor task that restarts it on crash and pipes stdout/stderr to a
  ring buffer exposed via a new IPC command (so the frontend can show
  "Daemon logs" in a Settings tab).
- **M4**: First-launch wizard at `btx_setup.html` — chain selection, wallet
  creation, sync progress UI with honest ETA.
- **M5**: Windows installer (NSIS via tauri-bundler) that ships pre-built
  `bitcoind.exe`, `brk_cli.exe`, `ord.exe`, plus an embedded Python runtime
  and `btxd.py`. Double-click installs everything.
