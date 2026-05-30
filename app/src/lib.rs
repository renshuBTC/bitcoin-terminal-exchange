// btx-app — Tauri shell that hosts the BTX web UI in a native window.
//
// M1 (shipped): native window opens loading http://127.0.0.1:3333.
//   User starts btxd themselves via `bash btx-launch.sh` in WSL.
//
// M2 (this file): shell spawns the BTX launcher as a child process at
//   startup, waits for btxd's :3333 port to accept connections, THEN
//   shows the window. On window close, runs `btx-launch.sh stop` so
//   nothing is left running. User no longer needs to start anything
//   manually — opening the app brings the stack up.
//
// M3: shell becomes the per-daemon supervisor (separate processes for
//   bitcoind, brk_cli, ord, btxd; restart on crash; log pane).

use std::process::{Command, Stdio};
use std::time::Duration;
use tauri::Manager;
use tokio::net::TcpStream;
use tokio::time::{sleep, timeout};

/// Default port btxd serves on. Matches the launcher's BTXD_PORT default.
const BTXD_PORT: u16 = 3333;

/// Hard-coded for M2. The project lives at a known path on the dev box.
/// M3 will read this from a config file or auto-detect relative to the exe.
const PROJECT_DIR_WSL: &str = "/mnt/c/Users/Ren Shu/Documents/Claude/Projects/bitcoin-terminal-exchange";

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            // Fire-and-forget: kick off the launcher in the background.
            // The launcher is idempotent — if btxd is already running it's a no-op.
            if let Err(e) = spawn_launcher_start() {
                eprintln!("[btx-app] warning: failed to spawn launcher: {e}");
                eprintln!("[btx-app]   you can still start btxd manually in WSL with:");
                eprintln!("[btx-app]   bash btx-launch.sh");
            } else {
                eprintln!("[btx-app] launcher started; waiting for btxd on :{BTXD_PORT}…");
            }

            // Background task: poll until btxd responds, then unhide the window.
            let app_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let ready = wait_for_btxd_ready(60).await;
                if ready {
                    eprintln!("[btx-app] btxd ready; showing window");
                } else {
                    eprintln!("[btx-app] btxd did not become ready within 60s; showing window anyway");
                    eprintln!("[btx-app]   webview will show a connection error until btxd comes up");
                }
                if let Some(window) = app_handle.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // Window is gone — stop the daemons.
                eprintln!("[btx-app] window closed; stopping daemons");
                let _ = spawn_launcher_stop();
                // Brief wait so the stop subprocess at least gets scheduled
                // before the parent exits. Don't block longer than 1s.
                std::thread::sleep(Duration::from_secs(1));
                let _ = window;
            }
        })
        .invoke_handler(tauri::generate_handler![ping, daemon_status])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// Spawn the BTX launcher in WSL. The launcher detaches its daemon children
/// via nohup, so this command itself returns quickly — the daemons keep
/// running in the background.
#[cfg(target_os = "windows")]
fn spawn_launcher_start() -> std::io::Result<()> {
    Command::new("wsl.exe")
        .args([
            "bash",
            "-c",
            &format!("cd '{PROJECT_DIR_WSL}' && bash btx-launch.sh"),
        ])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map(|_| ())
}

#[cfg(not(target_os = "windows"))]
fn spawn_launcher_start() -> std::io::Result<()> {
    Command::new("bash")
        .args(["btx-launch.sh"])
        .current_dir(PROJECT_DIR_WSL)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map(|_| ())
}

/// Run `btx-launch.sh stop` to gracefully shut down the daemon stack.
#[cfg(target_os = "windows")]
fn spawn_launcher_stop() -> std::io::Result<()> {
    Command::new("wsl.exe")
        .args([
            "bash",
            "-c",
            &format!("cd '{PROJECT_DIR_WSL}' && bash btx-launch.sh stop"),
        ])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map(|_| ())
}

#[cfg(not(target_os = "windows"))]
fn spawn_launcher_stop() -> std::io::Result<()> {
    Command::new("bash")
        .args(["btx-launch.sh", "stop"])
        .current_dir(PROJECT_DIR_WSL)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map(|_| ())
}

/// Poll the btxd port up to `max_secs` times, sleeping 1s between attempts.
/// Returns true as soon as a TCP connection succeeds.
async fn wait_for_btxd_ready(max_secs: u64) -> bool {
    let addr = format!("127.0.0.1:{BTXD_PORT}");
    for _ in 0..max_secs {
        let connect = timeout(Duration::from_millis(500), TcpStream::connect(&addr)).await;
        if matches!(connect, Ok(Ok(_))) {
            return true;
        }
        sleep(Duration::from_secs(1)).await;
    }
    false
}

/// Minimal IPC sanity-check command. Lets the frontend confirm the
/// Rust↔webview bridge is wired. Useful for M1/M2 verification.
#[tauri::command]
fn ping() -> String {
    "pong from btx-app".to_string()
}

/// Returns a quick snapshot of whether btxd is currently reachable.
/// Frontend can poll this to show status badges.
#[tauri::command]
async fn daemon_status() -> serde_json::Value {
    let addr = format!("127.0.0.1:{BTXD_PORT}");
    let reachable = timeout(Duration::from_millis(300), TcpStream::connect(&addr))
        .await
        .map(|r| r.is_ok())
        .unwrap_or(false);
    serde_json::json!({
        "btxd_port": BTXD_PORT,
        "btxd_reachable": reachable,
    })
}
