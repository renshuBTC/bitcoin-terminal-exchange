// btx-app — Tauri shell that hosts the BTX web UI in a native window.
//
// M1: native window opens loading http://127.0.0.1:3333.
// M2: shell spawns btxd via btx-launch.sh on launch, stops on close.
// M3: per-daemon supervisor. The launcher shell-out is gone; the Rust
//   supervisor spawns bitcoind, brk_cli, ord, btxd as four separate
//   WSL subprocesses in dependency order, monitors them, and restarts
//   on crash. IPC commands for status/logs feed btx_daemons.html.
// M4: first-launch wizard.
// M5a: Windows NSIS installer (shell + supervisor only).
// M5b (this file's latest pass): self-contained installer — bundled
//   Linux binaries copied into ~/.btx/bin on first launch by
//   install::install_bundled_assets(), daemon specs read from the
//   user's persisted ~/.btx/setup.json instead of hardcoded dev paths.

use std::sync::Arc;
use tauri::Manager;

mod install;
mod supervisor;
use supervisor::Supervisor;

struct SupervisorState(Arc<Supervisor>);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // M5b.4: read the user's persisted setup synchronously so the
    // Supervisor is built with the right chain/wallet/datadir from the
    // start. Costs ~300ms cold for a wsl.exe round-trip; acceptable at
    // process boot. First-launch users get Setup::default() (signet,
    // wallet "btx", no datadir override).
    let setup = install::load_setup_sync();
    eprintln!(
        "[btx-app] setup: chain={:?} wallet={:?} datadir_override={:?}",
        setup.chain, setup.wallet, setup.datadir_override
    );

    let sup = Arc::new(Supervisor::new(supervisor::make_specs_from_setup(&setup)));
    let sup_for_setup = sup.clone();
    let sup_for_state = sup.clone();
    let sup_for_close = sup.clone();

    tauri::Builder::default()
        .manage(SupervisorState(sup_for_state))
        .setup(move |app| {
            let app_handle = app.handle().clone();
            let sup = sup_for_setup.clone();

            tauri::async_runtime::spawn(async move {
                // M5b.3: copy bundled binaries + Python + HTML into
                // ~/.btx/bin and ~/.btx/app before any daemon starts.
                // Idempotent across runs via ~/.btx/.installed-v<ver>.
                match app_handle.path().resource_dir() {
                    Ok(resources_dir) => {
                        eprintln!("[btx-app] resource dir: {}", resources_dir.display());
                        if let Err(e) = install::install_bundled_assets(resources_dir).await {
                            eprintln!("[btx-app] install_bundled_assets failed: {e}");
                            // Continue anyway — start_all will surface the
                            // spawn failures in the daemon pane.
                        }
                    }
                    Err(e) => {
                        eprintln!("[btx-app] cannot resolve resource dir: {e}");
                    }
                }

                eprintln!("[btx-app] M3 supervisor starting daemon stack…");
                sup.start_all().await;
                eprintln!("[btx-app] daemon stack up; reloading webview");
                if let Some(window) = app_handle.get_webview_window("main") {
                    // M4: route first-launch users to the setup wizard.
                    // Check if ~/.btx/setup.json exists inside WSL — if not,
                    // navigate to btx_setup.html instead of the default route.
                    //
                    // v0.2.1: previously navigated to "/" relative; the
                    // window's initial URL was http://127.0.0.1:3333 so the
                    // webview loaded the connection-refused page during the
                    // 30-60s daemon startup. Now the window starts at
                    // index.html (a bundled loading screen), and we use an
                    // ABSOLUTE URL here so the navigation crosses origins
                    // from tauri://localhost (frontendDist) to btxd's HTTP
                    // server. Without the absolute URL, "/" would resolve
                    // against tauri:// and fail.
                    let first_launch = check_first_launch().await;
                    let target_path = if first_launch {
                        eprintln!("[btx-app] first launch detected; routing to setup wizard");
                        "http://127.0.0.1:3333/btx_setup.html"
                    } else {
                        eprintln!("[btx-app] setup already complete; loading trade page");
                        "http://127.0.0.1:3333/"
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
    // CREATE_NO_WINDOW (0x08000000) suppresses the console window flash
    // when invoked from a release-mode .exe with no parent console.
    #[allow(unused_mut)]
    let mut command = tokio::process::Command::new("wsl.exe");
    #[cfg(target_os = "windows")]
    command.creation_flags(0x08000000);
    let output = command.args(["bash", "-c", cmd]).output().await;
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
