// btx-app — Tauri shell that hosts the BTX web UI in a native window.
//
// M1 (this milestone): the shell just opens a window pointed at
// http://127.0.0.1:3333 — btxd must already be running (start it with
// `bash btx-launch.sh` in WSL as usual). The shell wraps it in a native
// frame so the user sees one application, not a browser tab.
//
// M2: this same `run()` will spawn btxd as a child process and wait for
// its /api/config endpoint to respond before showing the window.
//
// M3: spawn all four daemons (bitcoind, brk_cli, ord, btxd) in dependency
// order, supervise restarts, surface logs.

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![ping])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// Minimal IPC sanity-check command. The frontend can call
/// `await window.__TAURI__.core.invoke('ping')` and get "pong" back —
/// proves the Rust ↔ webview bridge is wired. Useful for M1 verification.
#[tauri::command]
fn ping() -> String {
    "pong from btx-app".to_string()
}
