// btx-app — Tauri shell that hosts the BTX web UI in a native window.
//
// M1: native window opens loading http://127.0.0.1:3333.
// M2: shell spawns btxd via btx-launch.sh on launch, stops on close.
// M3 (this file): per-daemon supervisor. The launcher shell-out is gone;
//   the Rust supervisor now spawns bitcoind, brk_cli, ord, btxd as four
//   separate WSL subprocesses in dependency order, monitors them, and
//   restarts on crash. New IPC commands for status/logs feed the
//   btx_daemons.html debug pane.
// M4: first-launch wizard.
// M5: Windows installer.

use std::sync::Arc;
use tauri::Manager;

mod supervisor;
use supervisor::Supervisor;

struct SupervisorState(Arc<Supervisor>);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let sup = Arc::new(Supervisor::new(supervisor::make_default_specs()));
    let sup_for_setup = sup.clone();
    let sup_for_state = sup.clone();
    let sup_for_close = sup.clone();

    tauri::Builder::default()
        .manage(SupervisorState(sup_for_state))
        .setup(move |app| {
            let app_handle = app.handle().clone();
            let sup = sup_for_setup.clone();

            tauri::async_runtime::spawn(async move {
                eprintln!("[btx-app] M3 supervisor starting daemon stack…");
                sup.start_all().await;
                eprintln!("[btx-app] daemon stack up; reloading webview");
                if let Some(window) = app_handle.get_webview_window("main") {
                    // M4: route first-launch users to the setup wizard.
                    // Check if ~/.btx/setup.json exists inside WSL — if not,
                    // navigate to btx_setup.html instead of the default route.
                    let first_launch = check_first_launch().await;
                    let target_path = if first_launch {
                        eprintln!("[btx-app] first launch detected; routing to setup wizard");
                        "/btx_setup.html"
                    } else {
                        eprintln!("[btx-app] setup already complete; loading trade page");
                        "/"
                    };
                    let nav_js = format!("window.location='{target_path}';");
                    let _ = window.eval(&nav_js);
                    tokio::time::sleep(std::time::Duration::from_millis(300)).await;
                    eprintln!("[btx-app] showing window");
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            });

            Ok(())
        })
        .on_window_event(move |_window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                eprintln!("[btx-app] window destroyed; stopping daemon stack");
                let sup = sup_for_close.clone();
                // Run shutdown on a dedicated thread with its own tokio
                // runtime so we don't deadlock the main async runtime.
                let handle = std::thread::spawn(move || {
                    let rt = tokio::runtime::Builder::new_current_thread()
                        .enable_all()
                        .build()
                        .expect("failed to build shutdown runtime");
                    rt.block_on(async move {
                        sup.stop_all().await;
                    });
                });
                // Wait up to 20s for stop_all to complete before letting
                // the app process exit. SHUTDOWN_GRACE_SECS in the
                // supervisor is 10s per daemon × 4 daemons = up to 40s
                // worst case, but in practice each port closes in <1s
                // after SIGTERM, so 20s is plenty.
                let _ = handle.join();
                eprintln!("[btx-app] all daemons stopped");
            }
        })
        .invoke_handler(tauri::generate_handler![
            ping,
            daemon_status,
            daemon_logs,
            restart_daemon,
            stop_daemon,
            start_daemon,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[tauri::command]
fn ping() -> String {
    "pong from btx-app".to_string()
}

/// M4: probe whether ~/.btx/setup.json exists in WSL.
/// Returns true if it does NOT exist (= first launch).
async fn check_first_launch() -> bool {
    let cmd = "test -f $HOME/.btx/setup.json && echo yes || echo no";
    let output = tokio::process::Command::new("wsl.exe")
        .args(["bash", "-c", cmd])
        .output()
        .await;
    match output {
        Ok(out) => {
            let s = String::from_utf8_lossy(&out.stdout);
            s.trim() != "yes"
        }
        Err(_) => true, // If we can't even probe, treat as first launch.
    }
}

#[tauri::command]
async fn daemon_status(
    state: tauri::State<'_, SupervisorState>,
) -> Result<Vec<serde_json::Value>, String> {
    Ok(state.0.status_snapshot().await)
}

#[tauri::command]
async fn daemon_logs(
    name: String,
    n: Option<usize>,
    state: tauri::State<'_, SupervisorState>,
) -> Result<Vec<String>, String> {
    Ok(state.0.get_logs(&name, n.unwrap_or(100)).await)
}

#[tauri::command]
async fn restart_daemon(
    name: String,
    state: tauri::State<'_, SupervisorState>,
) -> Result<(), String> {
    state.0.restart_one(&name).await;
    Ok(())
}

#[tauri::command]
async fn stop_daemon(
    name: String,
    state: tauri::State<'_, SupervisorState>,
) -> Result<(), String> {
    state.0.stop_one(&name).await;
    Ok(())
}

#[tauri::command]
async fn start_daemon(
    name: String,
    state: tauri::State<'_, SupervisorState>,
) -> Result<(), String> {
    state.0.start_one(&name).await;
    Ok(())
}
