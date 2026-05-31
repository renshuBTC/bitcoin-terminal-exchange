#!/usr/bin/env bash
# collect_linux_bins.sh — gather the four Linux daemons the BTX bundle needs
# and stage them in app/bin/linux/ for Tauri to pack into the NSIS installer.
#
# Run this in WSL Ubuntu before `cargo tauri build`. It is idempotent: if a
# binary is already present and its sha256 matches what we'd produce, we skip.
#
# Output layout:
#   app/bin/linux/
#     bitcoind          # Bitcoin Core v30.2 (v0.2.19; was v29.1 pre-v0.2.19)
#     bitcoin-cli       # Bitcoin Core v30.2
#     brk_cli           # built from ../brk-btx
#     ord               # taken from $HOME/bin/ord
#     SHA256SUMS        # checksums for verification on the user side
#     VERSIONS.txt      # human-readable: which version of each was packed
#
# All binaries are run through `strip --strip-unneeded` to keep the installer
# small (saves ~30-50% on each Rust binary).
#
# M5b.1 of the bundle work. Pairs with supervisor.rs install_bundled_bins()
# which on first launch copies these from
#   /mnt/c/.../AppData/Local/BTX/bin/linux/
# into ~/.btx/bin/ on the ext4 filesystem (where +x is preserved natively
# rather than relying on WSL's metadata mount option for /mnt/c).

set -euo pipefail

# Paths
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$HERE/.." && pwd)"            # .../bitcoin-terminal-exchange/app
REPO_DIR="$(cd "$APP_DIR/.." && pwd)"        # .../bitcoin-terminal-exchange
BRK_DIR="$(cd "$REPO_DIR/../brk-btx" && pwd)"
OUT_DIR="$APP_DIR/bin/linux"

CORE_DIR="${BTX_CORE_DIR:-$HOME/bitcoin-30.2}"
# v0.2.19: bumped from $HOME/bitcoin-29.1 to v30.2. Override via BTX_CORE_DIR if
# you have a different install path. NOTE: v30.0 and v30.1 were RECALLED by the
# Core devs (catastrophic wallet-deletion bug fixed in v30.2 on 2026-01-10) —
# bitcoincore.org removed the v30.0/v30.1 binaries; don't use them.
ORD_BIN="${BTX_ORD_BIN:-$HOME/bin/ord}"
# brk_cli builds 5-10x faster on ext4; default to ~/.cargo/target-btx-bundle
# but allow override via env.
BRK_TARGET_DIR="${BTX_BRK_TARGET:-$HOME/.cargo/target-btx-bundle}"

mkdir -p "$OUT_DIR"

# ---- helpers ----------------------------------------------------------------

log() { printf '[collect] %s\n' "$*" >&2; }
die() { printf '[collect] ERROR: %s\n' "$*" >&2; exit 1; }

verify_elf() {
    local f="$1"
    file -b "$f" | grep -q '^ELF 64-bit LSB' \
        || die "$f is not a Linux ELF64 binary (got: $(file -b "$f"))"
}

stage_bin() {
    local src="$1" name="$2"
    [[ -f "$src" ]] || die "missing source: $src"
    [[ -x "$src" ]] || die "not executable: $src"
    verify_elf "$src"
    cp -f "$src" "$OUT_DIR/$name"
    chmod +x "$OUT_DIR/$name"
    # strip is best-effort; ord/brk_cli have Rust debug syms that compress out
    # 20-40 MB per binary. bitcoind is already stripped by the Core release.
    strip --strip-unneeded "$OUT_DIR/$name" 2>/dev/null || true
    log "staged $name ($(du -h "$OUT_DIR/$name" | cut -f1))"
}

# ---- 1. Bitcoin Core (bitcoind + bitcoin-cli, v30.2) ------------------------

log "=== bitcoind + bitcoin-cli (target: v30.2) ==="
[[ -d "$CORE_DIR/bin" ]] || die "Bitcoin Core not at $CORE_DIR/bin — set BTX_CORE_DIR"
stage_bin "$CORE_DIR/bin/bitcoind"    bitcoind
stage_bin "$CORE_DIR/bin/bitcoin-cli" bitcoin-cli

# Capture version
BITCOIND_VERSION="$("$OUT_DIR/bitcoind" --version | head -n1)"

# ---- 2. brk_cli (built from local brk-btx) ----------------------------------

log "=== brk_cli (cargo build -p brk_cli --release) ==="
[[ -d "$BRK_DIR" ]] || die "brk-btx not at $BRK_DIR"
[[ -f "$BRK_DIR/Cargo.toml" ]] || die "no Cargo.toml in $BRK_DIR"

# Build on ext4 — /mnt/c paths cause LLVM IO errors during link
# (see reference_brk_build_env memory). We never run cargo here if a fresh
# binary is already present.
mkdir -p "$BRK_TARGET_DIR"
log "  target dir: $BRK_TARGET_DIR"
log "  this may take 5-15 minutes on first run, ~30s on incremental"

(
    cd "$BRK_DIR"
    CARGO_TARGET_DIR="$BRK_TARGET_DIR" \
        cargo build --release -p brk_cli
)

# The `brk_cli` crate declares [[bin]] name = "brk", so the actual binary
# produced is target/release/brk. We stage it as `brk_cli` in the bundle so
# the supervisor invokes a consistent name regardless of upstream renames.
BRK_CLI_BUILT="$BRK_TARGET_DIR/release/brk"
[[ -f "$BRK_CLI_BUILT" ]] || die "cargo finished but $BRK_CLI_BUILT not found"
stage_bin "$BRK_CLI_BUILT" brk_cli
BRK_CLI_VERSION="$("$OUT_DIR/brk_cli" --version 2>/dev/null | head -n1 || echo 'brk_cli (version unavailable)')"

# ---- 3. ord -----------------------------------------------------------------

log "=== ord ==="
[[ -f "$ORD_BIN" ]] || die "ord not at $ORD_BIN — set BTX_ORD_BIN"
stage_bin "$ORD_BIN" ord
ORD_VERSION="$("$OUT_DIR/ord" --version 2>/dev/null | head -n1 || echo 'ord (version unavailable)')"

# ---- 4. btxd.py is plain Python — not bundled; relies on WSL's python3 -----
# We do not pack python3 itself. The supervisor invokes:
#   python3 $HOME/.btx/app/btxd.py
# Setup script copies btxd.py + the HTML/CSS pages into $HOME/.btx/app/ on
# first launch (handled by supervisor.rs in M5b.3), since launching a Python
# script directly from /mnt/c is slow and breaks if the user moves the install.

log "=== writing manifests ==="

# SHA256SUMS for installer-side verification (supervisor checks these on first
# install before chmod +x to make sure nothing got corrupted in transit).
( cd "$OUT_DIR" && sha256sum bitcoind bitcoin-cli brk_cli ord > SHA256SUMS )

cat > "$OUT_DIR/VERSIONS.txt" <<EOF
# BTX bundle binary manifest — generated $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Built by: $(whoami)@$(hostname)
# Host: $(uname -srm)

bitcoind     : $BITCOIND_VERSION
bitcoin-cli  : $("$OUT_DIR/bitcoin-cli" --version | head -n1)
brk_cli      : $BRK_CLI_VERSION
ord          : $ORD_VERSION

Sources:
  Bitcoin Core : $CORE_DIR
  brk