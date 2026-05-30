# btx-app — Tauri shell

The native-window wrapper for BTX. Eventually this becomes the one application
that ships to end users (Bitcoin Core + brk_cli + ord + btxd + UI in one
installable program). M1 just opens the existing web UI in a native window.

## M1 — what worked

A native Windows / Linux / macOS window that loads `http://127.0.0.1:3333` —
the URL where `btxd` already serves the BTX UI. **Verified working on
Windows 11.**

## M2 — what worked

The shell started `bash btx-launch.sh` as a single fire-and-forget
subprocess, waited for btxd's port 3333 to become reachable, then
opened the window. On close, ran `bash btx-launch.sh stop`.

## M3 — what works now (current milestone)

The single launcher shell-out is gone. The shell now spawns each
daemon as its own WSL subprocess, in dependency order, and monitors
them continuously. Crash detection + auto-restart with backoff is
wired in. A new `btx_daemons.html` debug pane exposes live status
and per-daemon logs via the Tauri IPC bridge.

The 4 daemons and the dependency chain:

```
bitcoind  (:38332)
  └─ brk_cli  (:3140)
  └─ ord      (:3349)
      └─ btxd  (:3333)   ← shows window once this port responds
```

What happens when you open the app:

1. Shell starts `bitcoind` via `wsl.exe bash -c "exec $BIN/bitcoind …"`,
   redirecting stdout/stderr inside WSL to `/tmp/btx-bitcoind.log`.
2. Polls `127.0.0.1:38332` every second for up to 90s.
3. Once bitcoind's RPC port responds, starts `brk_cli` and `ord` (in
   sequence — could be parallel later, but sequential keeps logs clean).
4. Once both are ready, starts `btxd`.
5. Once btxd's port 3333 responds, shows the native window.

Health watcher tasks run every 3 seconds per daemon. If a port stops
responding, the watcher:
- Marks the daemon `Crashed`
- Sleeps an exponentially backed-off interval (1s, 2s, 4s, 8s, 16s)
- Restarts the daemon
- Resets after one successful restart cycle
- Gives up after 5 consecutive failures, marking it `Dead` (manual
  restart via the debug pane is then the only way back)

On window close: `stop_all()` walks reverse dependency order, sends
`SIGTERM` to each daemon's process, waits up to 10 seconds for the
port to close, then `SIGKILL`s if needed. Run via `wsl.exe bash -c
"pkill -TERM -x bitcoind"` etc.

### Debug pane

Open inside the BTX app shell:

```
http://127.0.0.1:3333/btx_daemons.html
```

Each row is one daemon: name, state badge, port, response status,
restart count, consecutive failures, uptime, action buttons (Start /
Restart / Stop). Click a row to expand its live log tail (last ~120
lines, refreshed every 2 seconds). The debug pane uses the Tauri IPC
bridge (`window.__TAURI__.core.invoke('daemon_status')` etc.), so it
ONLY functions inside the bundled app — opening it in a plain browser
shows a "browser mode" notice and inert UI.

### IPC commands exposed

| Command | Args | Returns |
|---|---|---|
| `ping` | — | "pong from btx-app" |
| `daemon_status` | — | `[{name, state, ready_port, port_responding, restart_count, consecutive_failures, uptime_secs, depends_on}, …]` |
| `daemon_logs` | `{name, n}` | `[String, …]` |
| `start_daemon` | `{name}` | `null` |
| `stop_daemon` | `{name}` | `null` |
| `restart_daemon` | `{name}` | `null` |

### Honest scope of M3

- WSL bridge still hard-coded. Linux/macOS would need different
  daemon command strings — M3 only ships the Windows path.
- Daemon paths (bin, datadir, brk dir) hard-coded in
  `supervisor::make_default_specs()`. Chain is hard-coded to signet.
  M4's first-launch wizard writes these to a config file.
- Logs live inside WSL at `/tmp/btx-<name>.log` — tailed via
  `wsl.exe bash -c "tail -n N …"` for the IPC. M5's native bundle
  reads them directly via `std::fs`.
- The watcher uses port polling, not `child.wait()` — when wsl.exe's
  Windows process exits, the WSL grandchild may live on, so we can't
  trust the parent-child relationship. Polling the daemon's own port
  is the reliable signal.

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
