// First-run asset installer.
//
// On startup the supervisor calls install_bundled_assets() before
// start_all(). On the very first launch of an installed BTX this:
//
//   1. Locates the resources dir that Tauri's NSIS installer dropped
//      next to the .exe (Windows path), and converts it to a /mnt/c/...
//      path that WSL can reach.
//   2. Verifies SHA256SUMS over the four bundled Linux binaries.
//   3. Copies the binaries to $HOME/.btx/bin/ inside WSL with chmod +x.
//      This is required because the install dir lives on NTFS via
//      /mnt/c — the executable bit is not reliably preserved there
//      unless the WSL `metadata` mount option is on. Copying to ext4
//      ($HOME) sidesteps that and is also ~2x faster at exec.
//   4. Copies btxd.py + its Python modules + the HTML pages to
//      $HOME/.btx/app/ so the supervisor's btxd spawn doesn't need to
//      `cd` into the install dir (much faster process start on ext4,
//      and means uninstall/move doesn't break a running daemon).
//   5. Drops a sentinel file at $HOME/.btx/.installed-v<version> so
//      subsequent launches skip all of the above.
//
// On version upgrade the sentinel changes name, so the copy runs again
// (idempotent — `cp -f` overwrites, no separate cleanup needed).
//
// M5b.3 of the bundle work.

use std::path::PathBuf;
use tokio::process::Command;

const APP_VERSION: &str = env!("CARGO_PKG_VERSION");

const BUNDLED_BINS: &[&str] = &["bitcoind", "bitcoin-cli", "brk_cli", "ord"];
const BUNDLED_PYTHON: &[&str] = &[
    "btxd.py",
    "btx_0b.py",
    "btx_carrier.py",
    "btx_envelope_publish.py",
    "btx_etch.py",
    "btx_orderbook.py",
    "btx_rune_swap.py",
    "btx_runes.py",
    "btx_runes_decode.py",
    "btx_runes_xcheck.py",
    "btx_taproot.py",
    "btx_wallet.py",
];
const BUNDLED_HTML: &[&str] = &[
    // Trade page is the only user-facing UI (consolidation decision 2026-06-04).
    "btx_trade.html",
    // Bootstrap-only pages shown during launch / first-run (not in user nav).
    "btx_daemons.html",
    "btx_setup.html",
];

/// Shared CSS file from assets/. Lives in a parallel `assets/` subdir
/// under ~/.btx/app/ so the existing <link href="assets/btx.css"> in
/// each page resolves cleanly. Without this, btx_book/trades/create/order
/// render as unstyled plain HTML.
const BUNDLED_ASSETS: &[&str] = &["btx.css"];

/// Spawn a WSL Command suppressing the console window on Windows.
/// Mirrors supervisor::wsl_command — duplicated to keep this module
/// standalone (no `pub(crate)` cycle with supervisor).
fn wsl_command() -> Command {
    #[allow(unused_mut)]
    let mut cmd = Command::new("wsl.exe");
    #[cfg(target_os = "windows")]
    cmd.creation_flags(0x08000000);
    cmd
}

/// Convert a Windows path like `C:\Users\Alice\AppData\Local\BTX\resources`
/// to a WSL path like `/mnt/c/Users/Alice/AppData/Local/BTX/resources`.
///
/// Handles Windows's `\\?\` extended-length prefix that Tauri 2's
/// `resource_dir()` returns — Win32 canonicalize wraps long-enabled paths
/// in `\\?\C:\...` form, which strips off here. Returns None for paths
/// we can't parse (no drive letter prefix).
pub fn win_path_to_wsl(p: &std::path::Path) -> Option<String> {
    let s = p.to_string_lossy().to_string();
    // Strip the extended-length prefix Tauri returns:
    //   \\?\C:\Users\...  ->  C:\Users\...
    //   \\?\UNC\server\.. ->  None (we don't try to reach UNC paths from WSL)
    let s: &str = if let Some(rest) = s.strip_prefix(r"\\?\UNC\") {
        let _ = rest;
        return None;
    } else if let Some(rest) = s.strip_prefix(r"\\?\") {
        rest
    } else {
        &s
    };
    let bytes = s.as_bytes();
    if bytes.len() < 3 {
        return None;
    }
    if !bytes[0].is_ascii_alphabetic() || bytes[1] != b':' {
        return None;
    }
    let drive = (bytes[0] as char).to_ascii_lowercase();
    let rest = s[2..].replace('\\', "/");
    // Strip leading slash to avoid /mnt/c//Users
    let rest = rest.trim_start_matches('/');
    Some(format!("/mnt/{drive}/{rest}"))
}

#[derive(Debug)]
pub enum InstallError {
    BadResourceDir(String),
    WslFailed(String),
    ChecksumMismatch(String),
}

impl std::fmt::Display for InstallError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            InstallError::BadResourceDir(s) => write!(f, "bad resource dir: {s}"),
            InstallError::WslFailed(s) => write!(f, "WSL command failed: {s}"),
            InstallError::ChecksumMismatch(s) => write!(f, "checksum mismatch: {s}"),
        }
    }
}

/// Install bundled assets into $HOME/.btx/{bin,app}/ on first launch
/// of this version. Idempotent — subsequent calls are no-ops unless the
/// version has changed since the last install.
///
/// `resources_dir` is the Windows path where Tauri put the bundled
/// files (typically `<install_dir>\resources\`). Pass the result of
/// `tauri::path::PathResolver::resource_dir()`.
pub async fn install_bundled_assets(resources_dir: PathBuf) -> Result<(), InstallError> {
    let resources_wsl = win_path_to_wsl(&resources_dir)
        .ok_or_else(|| InstallError::BadResourceDir(resources_dir.display().to_string()))?;

    eprintln!("[install] resources at {resources_wsl}");

    // Check sentinel.
    let sentinel = format!("$HOME/.btx/.installed-v{APP_VERSION}");
    let check_cmd = format!("test -f {sentinel} && echo yes || echo no");
    let out = wsl_command()
        .args(["bash", "-c", &check_cmd])
        .output()
        .await
        .map_err(|e| InstallError::WslFailed(e.to_string()))?;
    let already = String::from_utf8_lossy(&out.stdout).trim() == "yes";
    if already {
        eprintln!("[install] v{APP_VERSION} already installed; skipping");
        return Ok(());
    }

    eprintln!("[install] installing v{APP_VERSION}…");

    // Build the copy script. One WSL invocation does the whole thing so we
    // don't pay the wsl.exe startup cost per-file (≈300ms each on a cold
    // system, which adds up to ~7s for 23 files).
    let mut script = String::new();
    script.push_str("set -e\n");
    script.push_str("mkdir -p $HOME/.btx/bin $HOME/.btx/app\n");

    // Verify SHA256SUMS if present; non-fatal if absent (dev builds).
    script.push_str(&format!(
        "if [ -f '{resources_wsl}/bin/linux/SHA256SUMS' ]; then \
           cd '{resources_wsl}/bin/linux' && sha256sum -c SHA256SUMS || \
           {{ echo 'SHA256SUMS mismatch' >&2; exit 2; }}; \
         fi\n"
    ));

    // Copy + chmod +x the Linux binaries.
    for bin in BUNDLED_BINS {
        script.push_str(&format!(
            "cp -f '{resources_wsl}/bin/linux/{bin}' $HOME/.btx/bin/{bin}\n"
        ));
        script.push_str(&format!("chmod +x $HOME/.btx/bin/{bin}\n"));
    }

    // Copy Python sources. Tauri's NSIS bundle normalizes `../<file>`
    // resource entries by placing them in a `_up_/` subdirectory of the
    // install dir (one level up from tauri.conf.json maps to `_up_`),
    // so the resources we declared as "../btxd.py" actually land at
    // <install_dir>/_up_/btxd.py at runtime.
    for py in BUNDLED_PYTHON {
        script.push_str(&format!(
            "cp -f '{resources_wsl}/_up_/{py}' $HOME/.btx/app/{py}\n"
        ));
    }

    // Copy HTML pages — same `_up_/` convention. btxd serves these from
    // cwd, so they need to live alongside btxd.py in ~/.btx/app/.
    for page in BUNDLED_HTML {
        script.push_str(&format!(
            "cp -f '{resources_wsl}/_up_/{page}' $HOME/.btx/app/{page}\n"
        ));
    }

    // Copy shared CSS into ~/.btx/app/assets/ so the <link href="assets/btx.css">
    // tags in btx_book/trades/create/order pages resolve. Without this they
    // render as unstyled HTML with the nav links concatenated into one blob.
    script.push_str("mkdir -p $HOME/.btx/app/assets\n");
    for asset in BUNDLED_ASSETS {
        script.push_str(&format!(
            "cp -f '{resources_wsl}/_up_/assets/{asset}' $HOME/.btx/app/assets/{asset}\n"
        ));
    }

    // Wipe old sentinels so a clean dir reports the right version.
    script.push_str("rm -f $HOME/.btx/.installed-v*\n");
    script.push_str(&format!("touch {sentinel}\n"));
    script.push_str("echo installed\n");

    let out = wsl_command()
        .args(["bash", "-c", &script])
        .output()
        .await
        .map_err(|e| InstallError::WslFailed(e.to_string()))?;

    if !out.status.success() {
        let stderr = String::from_utf8_lossy(&out.stderr).to_string();
        if stderr.contains("SHA256SUMS") {
            return Err(InstallError::ChecksumMismatch(stderr));
        }
        return Err(InstallError::WslFailed(format!(
            "install script exit={}: {stderr}",
            out.status.code().unwrap_or(-1)
        )));
    }

    eprintln!(
        "[install] v{APP_VERSION} installed: {} bins, {} python, {} html",
        BUNDLED_BINS.len(),
        BUNDLED_PYTHON.len(),
        BUNDLED_HTML.len()
    );
    Ok(())
}

/// Reads ~/.btx/setup.json. Returns None if missing / unreadable; the
/// caller treats that as "use defaults".
pub async fn load_setup() -> Option<Setup> {
    let out = wsl_command()
        .args(["bash", "-c", "cat $HOME/.btx/setup.json 2>/dev/null"])
        .output()
        .await
        .ok()?;
    if !out.status.success() || out.stdout.is_empty() {
        return None;
    }
    serde_json::from_slice::<Setup>(&out.stdout).ok()
}

/// Blocking version of load_setup for use during process startup,
/// before the tokio runtime is fully spun up. Costs ~300ms cold but
/// avoids restructuring the entire setup hook around an async load.
/// Falls back to default Setup on any failure.
pub fn load_setup_sync() -> Setup {
    use std::process::Command;
    #[cfg(target_os = "windows")]
    use std::os::windows::process::CommandExt;

    let mut cmd = Command::new("wsl.exe");
    #[cfg(target_os = "windows")]
    cmd.creation_flags(0x08000000);

    let out = match cmd
        .args(["bash", "-c", "cat $HOME/.btx/setup.json 2>/dev/null"])
        .output()
    {
        Ok(o) => o,
        Err(_) => return Setup::default(),
    };
    if !out.status.success() || out.stdout.is_empty() {
        return Setup::default();
    }
    serde_json::from_slice::<Setup>(&out.stdout).unwrap_or_default()
}

#[derive(Debug, Clone, serde::Deserialize)]
pub struct Setup {
    pub chain: Option<String>,
    pub wallet: Option<String>,
    /// Optional WSL-form path to an existing Bitcoin Core datadir,
    /// used for mainnet to avoid re-syncing from scratch.
    pub datadir_override: Option<String>,
}

impl Default for Setup {
    fn default() -> Self {
        Setup {
            chain: Some("signet".to_string()),
            wallet: Some("btx".to_string()),
            datadir_override: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wsl_path_basic() {
        let p = std::path::Path::new(r"C:\Users\Alice\AppData\Local\BTX\resources");
        assert_eq!(
            win_path_to_wsl(p).unwrap(),
            "/mnt/c/Users/Alice/AppData/Local/BTX/resources"
        );
    }

    #[test]
    fn wsl_path_with_spaces() {
        let p = std::path::Path::new(r"C:\Users\Ren Shu\AppData\Local\BTX");
        assert_eq!(
            win_path_to_wsl(p).unwrap(),
            "/mnt/c/Users/Ren Shu/AppData/Local/BTX"
        );
    }

    #[test]
    fn wsl_path_lowercase_drive() {
        let p = std::path::Path::new(r"d:\foo\bar");
        assert_eq!(win_path_to_wsl(p).unwrap(), "/mnt/d/foo/bar");
    }

    #[test]
    fn wsl_path_rejects_unc() {
        let p = std::path::Path::new(r"\\server\share\file");
        assert!(win_path_to_wsl(p).is_none());
    }

    #[test]
    fn wsl_path_strips_extended_prefix() {
        // Tauri returns this form on Windows.
        let p = std::path::Path::new(r"\\?\C:\Users\Ren Shu\AppData\Local\BTX");
        assert_eq!(
            win_path_to_wsl(p).unwrap(),
            "/mnt/c/Users/Ren Shu/AppData/Local/BTX"
        );
    }

    #[test]
    fn wsl_path_rejects_extended_unc() {
        let p = std::path::Path::new(r"\\?\UNC\server\share\file");
        assert!(win_path_to_wsl(p).is_none());
    }
}
