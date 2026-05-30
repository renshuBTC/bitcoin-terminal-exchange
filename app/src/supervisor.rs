// Per-daemon supervisor for the BTX bundle.
//
// M3 of the bundle work (task #224). Replaces M2's "shell out to
// btx-launch.sh once" with: four independent daemons (bitcoind, brk_cli,
// ord, btxd) each spawned as its own subprocess, started in dependency
// order, monitored continuously, restarted on crash with backoff, and
// stopped in reverse dependency order on shutdown.
//
// Execution medium is still WSL (we call `wsl.exe bash -c "..."` for
// every operation). The daemons themselves are unchanged from the
// launcher — same commands, same flags, same log file locations — just
// driven from Rust per-daemon instead of from one shell script. M5
// replaces the WSL bridge with native Windows binaries.

use std::collections::{HashMap, HashSet};
use std::pin::Pin;
use std::process::Stdio;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::net::TcpStream;
use tokio::process::Command;
use tokio::sync::Mutex;
use tokio::time::{sleep, timeout};

/// Build a tokio::process::Command for wsl.exe that does NOT pop a
/// console window on Windows. When btx-app runs from `cargo tauri dev`
/// it has a parent console anyway, but the released .exe doesn't —
/// without this flag every WSL subprocess spawns its own cmd.exe
/// window. CREATE_NO_WINDOW = 0x08000000.
fn wsl_command() -> Command {
    #[allow(unused_mut)]
    let mut cmd = Command::new("wsl.exe");
    // tokio::process::Command exposes creation_flags as a direct method
    // on Windows targets — no trait import needed.
    #[cfg(target_os = "windows")]
    cmd.creation_flags(0x08000000);
    cmd
}

const MAX_FAILURES: u32 = 5;
// brk_cli may do an incremental cargo rebuild on first start; budget
// generously for that. Subsequent starts are fast (cached).
const READY_WAIT_SECS: u64 = 240;
const SHUTDOWN_GRACE_SECS: u64 = 10;
const HEALTH_POLL_SECS: u64 = 3;
const LOG_DIR_WSL: &str = "/tmp";

#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum State {
    /// Never started this session, or stopped cleanly.
    Stopped,
    /// Spawned, waiting for readiness probe to succeed.
    Starting,
    /// Ready port is responding.
    Running,
    /// Shutdown requested; SIGTERM sent, waiting for port to close.
    Stopping,
    /// Port stopped responding unexpectedly; restart pending.
    Crashed,
    /// Exceeded MAX_FAILURES consecutive restart attempts. Manual restart only.
    Dead,
}

#[derive(Clone)]
pub struct DaemonSpec {
    pub name: &'static str,
    /// Command line to run inside `wsl.exe bash -c "<this>"`.
    /// Should redirect stdout/stderr to a per-daemon log file under
    /// `LOG_DIR_WSL` so we can tail it for the UI debug pane.
    pub wsl_command: String,
    /// Command to run via `wsl.exe bash -c "<this>"` for shutdown.
    /// Typically `pkill -<sig> -x <binary>` or `pkill -<sig> -f <pattern>`.
    /// Will substitute the signal at runtime — write it as `pkill -SIG-…`
    /// and the supervisor swaps SIG for TERM (graceful) or KILL (force).
    pub stop_pattern: String,
    /// TCP port that must accept connections for the daemon to be
    /// considered ready / alive.
    pub ready_port: u16,
    /// Names of daemons that must be ready before this one starts.
    pub depends_on: Vec<&'static str>,
}

pub struct DaemonRuntime {
    pub spec: DaemonSpec,
    pub state: State,
    pub started_at: Option<Instant>,
    pub restart_count: u32,
    pub consecutive_failures: u32,
    /// Set when the supervisor is intentionally stopping this daemon.
    /// Watcher tasks check this so they don't treat clean shutdowns as
    /// crashes.
    pub stopping: bool,
}

#[derive(Clone)]
pub struct Supervisor {
    daemons: Arc<Mutex<HashMap<String, Arc<Mutex<DaemonRuntime>>>>>,
    shutting_down: Arc<Mutex<bool>>,
}

impl Supervisor {
    pub fn new(specs: Vec<DaemonSpec>) -> Self {
        let mut map = HashMap::new();
        for spec in specs {
            let name = spec.name.to_string();
            map.insert(
                name,
                Arc::new(Mutex::new(DaemonRuntime {
                    spec,
                    state: State::Stopped,
                    started_at: None,
                    restart_count: 0,
                    consecutive_failures: 0,
                    stopping: false,
                })),
            );
        }
        Self {
            daemons: Arc::new(Mutex::new(map)),
            shutting_down: Arc::new(Mutex::new(false)),
        }
    }

    /// Start all daemons in dependency order. Returns when the last
    /// daemon's readiness probe succeeds (or fails). Also kicks off the
    /// status-publishing task (writes JSON snapshot to a file inside WSL
    /// so the debug pane in btx_daemons.html can fetch() it via btxd —
    /// sidesteps Tauri 2's remote-URL permission system).
    pub async fn start_all(&self) {
        let order = self.topo_order().await;
        for name in order {
            eprintln!("[supervisor] starting {name}…");
            self.start_one(&name).await;
        }
        self.spawn_status_publisher();
    }

    /// Background task that serializes the current snapshot to a file
    /// inside WSL every 2 seconds. btxd reads this file when the debug
    /// pane asks for /api/supervisor/status.
    fn spawn_status_publisher(&self) {
        let sup = self.clone();
        let shutting_down = self.shutting_down.clone();
        tokio::spawn(async move {
            loop {
                if *shutting_down.lock().await {
                    return;
                }
                let snapshot = sup.status_snapshot().await;
                let payload = serde_json::json!({
                    "daemons": snapshot,
                    "ts": std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .map(|d| d.as_secs())
                        .unwrap_or(0),
                });
                // Write to a temp file inside WSL via wsl.exe. We use printf
                // through a heredoc to avoid quoting issues with the JSON
                // payload. The status file lives at /tmp/btx-supervisor.json.
                let body = serde_json::to_string(&payload).unwrap_or_else(|_| "{}".into());
                let cmd = format!(
                    "cat > /tmp/btx-supervisor.json <<'BTXJSONEOF'\n{body}\nBTXJSONEOF\n"
                );
                let _ = wsl_command()
                    .args(["bash", "-c", &cmd])
                    .stdout(std::process::Stdio::null())
                    .stderr(std::process::Stdio::null())
                    .spawn();
                tokio::time::sleep(Duration::from_secs(2)).await;
            }
        });
    }

    /// Stop all daemons in reverse dependency order. Sets the global
    /// shutting_down flag so watcher tasks suppress crash detection.
    pub async fn stop_all(&self) {
        *self.shutting_down.lock().await = true;
        let order: Vec<String> = self.topo_order().await.into_iter().rev().collect();
        for name in order {
            eprintln!("[supervisor] stopping {name}…");
            self.stop_one(&name).await;
        }
    }

    pub async fn start_one(&self, name: &str) {
        let arc = match self.lookup(name).await {
            Some(a) => a,
            None => return,
        };

        let (cmd_str, port) = {
            let mut rt = arc.lock().await;
            if matches!(rt.state, State::Starting | State::Running) {
                return;
            }
            rt.state = State::Starting;
            rt.stopping = false;
            (rt.spec.wsl_command.clone(), rt.spec.ready_port)
        };

        // Fire-and-forget WSL subprocess. Output is redirected inside
        // WSL to /tmp/btx-<name>.log so we can read it later.
        let spawn_res = wsl_command()
            .args(["bash", "-c", &cmd_str])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .stdin(Stdio::null())
            .spawn();

        if let Err(e) = spawn_res {
            eprintln!("[supervisor] {name}: spawn failed: {e}");
            let mut rt = arc.lock().await;
            rt.state = State::Crashed;
            rt.consecutive_failures += 1;
            return;
        }

        arc.lock().await.started_at = Some(Instant::now());

        // Wait for the port to accept connections.
        let ready = wait_for_port(port, READY_WAIT_SECS).await;
        if !ready {
            eprintln!(
                "[supervisor] {name}: not ready on :{port} after {READY_WAIT_SECS}s"
            );
            let mut rt = arc.lock().await;
            rt.state = State::Crashed;
            rt.consecutive_failures += 1;
            return;
        }

        eprintln!("[supervisor] {name}: ready on :{port}");
        {
            let mut rt = arc.lock().await;
            rt.state = State::Running;
            rt.consecutive_failures = 0;
        }

        // Spawn the health watcher. Sync call so start_one's future doesn't
        // depend on spawn_watcher's future being Send (which would create a
        // cycle: spawn_watcher's body calls start_one, start_one awaits
        // spawn_watcher, etc.).
        self.spawn_watcher(name.to_string(), arc.clone());
    }

    pub async fn stop_one(&self, name: &str) {
        let arc = match self.lookup(name).await {
            Some(a) => a,
            None => return,
        };

        let (stop_pattern, port) = {
            let mut rt = arc.lock().await;
            if matches!(rt.state, State::Stopped | State::Dead) {
                return;
            }
            rt.state = State::Stopping;
            rt.stopping = true;
            (rt.spec.stop_pattern.clone(), rt.spec.ready_port)
        };

        // Graceful: SIGTERM.
        let term_cmd = stop_pattern.replace("SIG", "TERM");
        eprintln!("[supervisor] {name}: SIGTERM");
        let _ = wsl_command()
            .args(["bash", "-c", &term_cmd])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn();

        // Wait up to SHUTDOWN_GRACE_SECS for the port to close.
        let start = Instant::now();
        while start.elapsed() < Duration::from_secs(SHUTDOWN_GRACE_SECS) {
            if !check_port(port).await {
                break;
            }
            sleep(Duration::from_millis(500)).await;
        }

        // If still up, SIGKILL.
        if check_port(port).await {
            let kill_cmd = stop_pattern.replace("SIG", "KILL");
            eprintln!("[supervisor] {name}: SIGKILL");
            let _ = wsl_command()
                .args(["bash", "-c", &kill_cmd])
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn();
            sleep(Duration::from_secs(2)).await;
        }

        let mut rt = arc.lock().await;
        rt.state = State::Stopped;
        rt.started_at = None;
        eprintln!("[supervisor] {name}: stopped");
    }

    /// Public restart: stop then start, regardless of current state.
    pub async fn restart_one(&self, name: &str) {
        self.stop_one(name).await;
        // Reset failure counter on manual restart.
        if let Some(arc) = self.lookup(name).await {
            let mut rt = arc.lock().await;
            rt.consecutive_failures = 0;
            rt.state = State::Stopped;
        }
        self.start_one(name).await;
    }

    /// Snapshot of all daemons' state, in dependency order, as JSON
    /// values for the IPC layer.
    pub async fn status_snapshot(&self) -> Vec<serde_json::Value> {
        let order = self.topo_order().await;
        let mut out = Vec::with_capacity(order.len());
        for name in order {
            if let Some(arc) = self.lookup(&name).await {
                let rt = arc.lock().await;
                let uptime_secs = rt.started_at.map(|t| t.elapsed().as_secs()).unwrap_or(0);
                let port_ok = check_port(rt.spec.ready_port).await;
                out.push(serde_json::json!({
                    "name": rt.spec.name,
                    "state": rt.state,
                    "ready_port": rt.spec.ready_port,
                    "port_responding": port_ok,
                    "restart_count": rt.restart_count,
                    "consecutive_failures": rt.consecutive_failures,
                    "uptime_secs": uptime_secs,
                    "depends_on": rt.spec.depends_on,
                }));
            }
        }
        out
    }

    /// Tail the daemon's log file inside WSL.
    pub async fn get_logs(&self, name: &str, n: usize) -> Vec<String> {
        let log_path = format!("{LOG_DIR_WSL}/btx-{name}.log");
        let cmd = format!("tail -n {n} '{log_path}' 2>/dev/null");
        let output = wsl_command()
            .args(["bash", "-c", &cmd])
            .output()
            .await;
        match output {
            Ok(out) => String::from_utf8_lossy(&out.stdout)
                .lines()
                .map(|s| s.to_string())
                .collect(),
            Err(_) => vec![],
        }
    }

    // ---- internals ----

    async fn lookup(&self, name: &str) -> Option<Arc<Mutex<DaemonRuntime>>> {
        self.daemons.lock().await.get(name).cloned()
    }

    async fn topo_order(&self) -> Vec<String> {
        let daemons = self.daemons.lock().await;
        let names: Vec<String> = daemons.keys().cloned().collect();
        drop(daemons);

        let mut order = Vec::new();
        let mut visited = HashSet::new();
        for name in names {
            self.visit(&name, &mut order, &mut visited).await;
        }
        order
    }

    fn visit<'a>(
        &'a self,
        name: &'a str,
        order: &'a mut Vec<String>,
        visited: &'a mut HashSet<String>,
    ) -> Pin<Box<dyn std::future::Future<Output = ()> + Send + 'a>> {
        Box::pin(async move {
            if visited.contains(name) {
                return;
            }
            visited.insert(name.to_string());

            let deps = {
                let daemons = self.daemons.lock().await;
                match daemons.get(name) {
                    Some(arc) => arc.lock().await.spec.depends_on.clone(),
                    None => return,
                }
            };

            for dep in deps {
                self.visit(dep, order, visited).await;
            }
            order.push(name.to_string());
        })
    }

    fn spawn_watcher(&self, name: String, arc: Arc<Mutex<DaemonRuntime>>) {
        let shutting_down = self.shutting_down.clone();
        let sup = self.clone();
        tokio::spawn(async move {
            loop {
                sleep(Duration::from_secs(HEALTH_POLL_SECS)).await;

                if *shutting_down.lock().await {
                    return;
                }

                let (state, stopping, port) = {
                    let rt = arc.lock().await;
                    (rt.state.clone(), rt.stopping, rt.spec.ready_port)
                };

                if stopping || !matches!(state, State::Running) {
                    return;
                }

                if check_port(port).await {
                    continue;
                }

                // Port stopped responding → daemon crashed.
                let failures = {
                    let mut rt = arc.lock().await;
                    rt.state = State::Crashed;
                    rt.consecutive_failures += 1;
                    rt.restart_count += 1;
                    rt.consecutive_failures
                };

                eprintln!(
                    "[supervisor] {name}: port :{port} stopped responding — \
                     crashed (consecutive failure {failures}/{MAX_FAILURES})"
                );

                if failures > MAX_FAILURES {
                    eprintln!("[supervisor] {name}: max failures exceeded — marking dead");
                    arc.lock().await.state = State::Dead;
                    return;
                }

                // Exponential backoff: 1, 2, 4, 8, 16, capped at 16s.
                let delay = (1u64 << (failures - 1)).min(16);
                eprintln!("[supervisor] {name}: restarting in {delay}s");
                sleep(Duration::from_secs(delay)).await;

                if *shutting_down.lock().await {
                    return;
                }

                sup.start_one(&name).await;
                return; // start_one spawns a new watcher
            }
        });
    }
}

/// Build the 4-daemon spec from the user's persisted setup.
///
/// M3 hardcoded everything for the dev box. M5b reads chain + wallet +
/// optional external datadir from `~/.btx/setup.json` (populated by the
/// first-launch wizard), uses bundled binaries from `~/.btx/bin/`
/// installed by `install::install_bundled_assets()`, and runs btxd from
/// `~/.btx/app/` (a freshly-installed BTX has no project checkout).
///
/// Chain → datadir defaults:
///   signet    → $HOME/.btx/data/signet     (pruned 2GB)
///   regtest   → $HOME/.btx/data/regtest    (no prune)
///   mainnet   → $datadir_override required (we don't sync from scratch)
///
/// If `setup.datadir_override` is set, it wins over the chain default
/// regardless of chain.
pub fn make_specs_from_setup(setup: &crate::install::Setup) -> Vec<DaemonSpec> {
    let chain = setup.chain.as_deref().unwrap_or("signet");
    let wallet = setup.wallet.as_deref().unwrap_or("btx");

    // Resolve datadir.
    let datadir: String = match (chain, setup.datadir_override.as_deref()) {
        (_, Some(d)) => d.to_string(),
        ("signet", None) => "$HOME/.btx/data/signet".to_string(),
        ("regtest", None) => "$HOME/.btx/data/regtest".to_string(),
        ("main" | "mainnet", None) => {
            // No override and no default — fall back to signet so the bundle
            // doesn't try to sync a 700GB chain from a clean state.
            // The wizard requires the user to pick an existing datadir
            // before completing setup, so this branch is the safety net.
            eprintln!(
                "[supervisor] WARNING: mainnet selected but no datadir_override; \
                 falling back to signet to protect the user's disk"
            );
            "$HOME/.btx/data/signet".to_string()
        }
        _ => "$HOME/.btx/data/signet".to_string(),
    };

    // Bitcoin Core chain-network flag + RPC port.
    let (chain_flag, rpc_port, prune_arg) = match chain {
        "signet" => ("-signet", 38332u16, "-prune=2000"),
        "regtest" => ("-regtest", 18443, "-prune=0"),
        "main" | "mainnet" => ("", 8332, ""),
        _ => ("-signet", 38332, "-prune=2000"),
    };

    // Bitcoin Core data subdir for blocks/cookie (differs by chain).
    let subdir = match chain {
        "signet" => "signet",
        "regtest" => "regtest",
        "main" | "mainnet" => "",
        _ => "signet",
    };
    let blocks_path = if subdir.is_empty() {
        format!("{datadir}/blocks")
    } else {
        format!("{datadir}/{subdir}/blocks")
    };
    let cookie_path = if subdir.is_empty() {
        format!("{datadir}/.cookie")
    } else {
        format!("{datadir}/{subdir}/.cookie")
    };

    // ord chain flag — ord uses different flag names than bitcoind.
    let ord_chain_flag = match chain {
        "signet" => "--chain signet",
        "regtest" => "--regtest",
        "main" | "mainnet" => "",
        _ => "--chain signet",
    };

    // brk_cli's chain magic. brk-btx pins these per chain in BRK_BLOCK_MAGIC
    // env var; 0a03cf40 is the signet magic baked into the project today.
    let brk_block_magic = match chain {
        "signet" => "0a03cf40",
        "regtest" => "fabfb5da",
        "main" | "mainnet" => "f9beb4d9",
        _ => "0a03cf40",
    };

    // Per-chain BRK index dir to avoid mixing chains in the same store.
    let brk_dir = format!("$HOME/.btx/brk-{chain}");

    // pkill -f patterns can match the supervisor's own grep, so we match on
    // the binary basename when possible.
    let bitcoind_pruning = if prune_arg.is_empty() {
        "".to_string()
    } else {
        format!(" {prune_arg}")
    };

    // Note: -txindex is incompatible with -prune. ord needs txindex to look
    // up arbitrary transactions (root cause of the M7 ord wedge — without
    // txindex, ord panics with bitcoind RPC error -5 "No such mempool
    // transaction. Use -txindex" the moment it tries to inspect a tx,
    // crash-loops via supervisor, and never advances its index).
    //
    // Resolution by chain:
    //   regtest: prune is OFF (set to 0), so -txindex=1 is compatible. We
    //            unconditionally enable it for trade-rail support.
    //   signet:  prune is ON (-prune=2000 for ~2GB cap) — incompatible with
    //            txindex. Trade-rail testing on signet remains broken from
    //            this layer; the historic signet trade flow (memory task
    //            #88) ran without prune. Tradeoff: small disk footprint vs.
    //            trade-rail support. For now, keep prune on signet — users
    //            who want to test the trade rail on signet can disable
    //            prune in their setup.json (datadir_override path) and
    //            run with txindex.
    //   mainnet: user's existing Core install via M5b.6 datadir_override —
    //            inherits whatever Core was already configured with.
    let bitcoind_txindex = match chain {
        "regtest" => " -txindex=1",
        _ => "",
    };

    vec![
        DaemonSpec {
            name: "bitcoind",
            wsl_command: format!(
                "mkdir -p {datadir} && \
                 exec $HOME/.btx/bin/bitcoind {chain_flag} -datadir={datadir}{bitcoind_pruning}{bitcoind_txindex} \
                 -datacarrier=1 -datacarriersize=240 \
                 -fallbackfee=0.0002 -dbcache=300 -server -printtoconsole \
                 > {LOG_DIR_WSL}/btx-bitcoind.log 2>&1"
            ),
            stop_pattern: "pkill -SIG -x bitcoind".to_string(),
            ready_port: rpc_port,
            depends_on: vec![],
        },
        DaemonSpec {
            name: "brk_cli",
            wsl_command: format!(
                "mkdir -p {brk_dir} && BRK_BLOCK_MAGIC={brk_block_magic} \
                 exec $HOME/.btx/bin/brk_cli \
                 --brkdir {brk_dir} \
                 --blocksdir {blocks_path} \
                 --rpcconnect 127.0.0.1 --rpcport {rpc_port} \
                 --rpccookiefile {cookie_path} \
                 --brkport 3140 \
                 > {LOG_DIR_WSL}/btx-brk_cli.log 2>&1"
            ),
            stop_pattern: "pkill -SIG -x brk_cli; pkill -SIG -x brk".to_string(),
            ready_port: 3140,
            depends_on: vec!["bitcoind"],
        },
        DaemonSpec {
            name: "ord",
            // v0.2.6: pre-flight stale-lock recovery. ord 0.27's embedded
            // redb sets an OPEN flag inside index.redb when the database is
            // opened, and clears it on clean shutdown. If ord crashes or is
            // SIGKILL'd, the flag stays set and the next ord process refuses
            // to start with "Database already open. Cannot acquire lock."
            // We detect this signature in the most recent /tmp/btx-ord.log
            // (which the previous attempt wrote on the way out) and rm the
            // chain-specific index subdir so the new ord rebuilds clean.
            // Only runs on regtest where reindex is cheap (~10s for ~200
            // blocks); signet/mainnet keep the manual-recovery path until
            // we wire wedge detection in v0.2.7+.
            wsl_command: format!(
                "if [ '{chain}' = 'regtest' ] && [ -f {LOG_DIR_WSL}/btx-ord.log ] && \
                    grep -q 'Database already open' {LOG_DIR_WSL}/btx-ord.log; then \
                     echo '[ord-recover] stale redb lock detected; rebuilding index'; \
                     rm -rf {datadir}/ord/{chain}; \
                 fi && \
                 mkdir -p {datadir}/ord && \
                 exec $HOME/.btx/bin/ord {ord_chain_flag} \
                 --bitcoin-data-dir {datadir} \
                 --cookie-file {cookie_path} \
                 --data-dir {datadir}/ord \
                 --index-runes server --http-port 3349 \
                 > {LOG_DIR_WSL}/btx-ord.log 2>&1"
            ),
            stop_pattern: "pkill -SIG -x ord".to_string(),
            ready_port: 3349,
            depends_on: vec!["bitcoind"],
        },
        DaemonSpec {
            name: "btxd",
            wsl_command: format!(
                "cd $HOME/.btx/app && exec python3 btxd.py \
                 --bitcoin-cli $HOME/.btx/bin/bitcoin-cli --chain {chain} \
                 --datadir {datadir} --wallet {wallet} \
                 --brk-url http://127.0.0.1:3140 \
                 --ord-url http://127.0.0.1:3349 \
                 --port 3333 \
                 > {LOG_DIR_WSL}/btx-btxd.log 2>&1"
            ),
            stop_pattern: "pkill -SIG -f 'python3 btxd.py'".to_string(),
            ready_port: 3333,
            depends_on: vec!["bitcoind", "brk_cli", "ord"],
        },
    ]
}

/// Back-compat shim — pre-M5b code referred to make_default_specs(). New
/// code should call make_specs_from_setup(). Defaults to signet with
/// wallet "btx" and no datadir override.
pub fn make_default_specs() -> Vec<DaemonSpec> {
    make_specs_from_setup(&crate::install::Setup::default())
}

// ---- helpers ----

async fn wait_for_port(port: u16, max_secs: u64) -> bool {
    let addr = format!("127.0.0.1:{port}");
    for _ in 0..max_secs {
        if matches!(
            timeout(Duration::from_millis(500), TcpStream::connect(&addr)).await,
            Ok(Ok(_))
        ) {
            return true;
        }
        sleep(Duration::from_secs(1)).await;
    }
    false
}

async fn check_port(port: u16) -> bool {
    let addr = format!("127.0.0.1:{port}");
    matches!(
        timeout(Duration::from_millis(300), TcpStream::connect(&addr)).await,
        Ok(Ok(_))
    )
}
