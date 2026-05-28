# BTX — Dependencies & Supply Chain (SBOM note)

*Records the dependency surface, version pinning, reproducibility status, and low-bus-factor trust
assumptions, from the supply-chain audit (2026-05-27). The authoritative machine-readable lists are
`brk/Cargo.lock` (Rust, 391 packages, exact-pinned) and `requirements.txt` (Python runtime).
"Latest-patched / known-advisory" status is NOT asserted here — it must be refreshed with the tool
commands at the bottom, since it changes over time.*

## Surface at a glance

BTX is two codebases plus bundled binaries:
- **brk-btx (Rust indexer + HTTP server):** transitive deps fully pinned in `brk/Cargo.lock`
  (391 packages). Built from source (`cargo build --release -p brk_cli`).
- **BTX Python tooling (CLI + btxd orchestrator):** ONE third-party runtime dep —
  `python-bitcoinlib`; everything else is stdlib. PyInstaller is build-time only. See `requirements.txt`.
- **Bundled runtime binaries:** `bitcoind` 29.1, `ord` 0.27.1, `brk_cli` (from source) — see
  `package-linux.sh`.

## Security-relevant dependencies (versions from Cargo.lock / code)

| Dependency | Version | Class | Pinned | Bus factor |
|------------|---------|-------|--------|------------|
| bitcoin (rust-bitcoin) | 0.32.9 | crypto (tx/sighash) | yes | rust-bitcoin org — strong |
| secp256k1 | 0.29.1 | crypto (production ECDSA verify) | yes | rust-bitcoin org / libsecp256k1 — strong |
| bitcoin_hashes | 0.14.1 | crypto (hashing) | yes | rust-bitcoin org — strong |
| ring | 0.17.14 | crypto (via rustls TLS) | yes | lead-dev-concentrated; widely audited |
| rustls | 0.23.40 | crypto/network (TLS) | yes | rustls org — strong |
| axum | 0.8.9 | network (HTTP API) | yes | tokio org — strong |
| hyper | 1.9.0 | network (HTTP) | yes | hyper/tokio — strong |
| tokio | 1.52.2 | network (async runtime) | yes | tokio org — strong |
| ureq | 3.3.0 | network (bitcoind RPC client) | yes | small team — moderate |
| **fjall** | 3.0.4 | storage (order store) | yes | **single-maintainer — LOW** |
| **byteview** | 0.10.1 | storage (kv bytes) | yes | **single-maintainer (fjall author) — LOW** |
| **vecdb** | vendored | storage | in-tree (`brk/vendor/vecdb`) | **brk first-party, ~single author — LOW** |
| brk_* crates | workspace | indexer/server/rpc | yes | **brk first-party, ~single author — LOW** |
| serde / schemars | 1.0.228 / 1.2.1 | serialization | yes | strong / moderate |
| **python-bitcoinlib** | 0.12.2 | crypto (Py ECDSA) + serialization | yes (requirements.txt) | **Peter Todd — single-maintainer, LOW; on crypto path** |
| pyinstaller (build only) | 6.20.0 | build (freeze CLI) | yes (requirements note) | small team |

Hand-rolled crypto: `btx_taproot.py` implements BIP340 Schnorr + BIP341/342 sighash in **pure Python
with no library** (because python-bitcoinlib 0.12.2 predates Taproot and uses an OpenSSL ECDSA backend,
not libsecp256k1). It is audited against the official BIP340/BIP341 vectors and is NOT constant-time
(inherent to pure Python; scoped to single-use ephemeral keys — see `BTX-threat-model.md`).

## (a) Pinning
- Rust: **fully pinned** via `Cargo.lock` (exact versions + hashes for all 391 packages).
- Python: **pinned** via `requirements.txt` (python-bitcoinlib==0.12.2; pyinstaller==6.20.0 build-only).

## (b) Latest-patched / advisories

**Audit result 2026-05-27 — both BTX dependency trees are CLEAN of known advisories:**
- **Rust:** `cargo audit` over all **391** `Cargo.lock` crates against the RustSec DB (1098 advisories
  loaded) reported **0 vulnerabilities and 0 unmaintained/yanked warnings** (exit 0). This covers the
  crypto/network/storage crates that matter most: `secp256k1` 0.29.1, `bitcoin` 0.32.9, `ring` 0.17.14,
  `rustls` 0.23.40, `hyper`/`tokio`/`ureq`, and `fjall`/`byteview` — none flagged.
- **Python:** `python-bitcoinlib` 0.12.2 (the sole BTX runtime dep) is **not** flagged by `pip-audit`.

Caveat — scope and freshness: a *full-interpreter* `pip-audit` on a dev machine will also surface
advisories in unrelated installed packages (e.g. `cryptography`, `twisted`, `urllib3`, `certifi`) — those
are **environment hygiene, not BTX dependencies** (BTX imports only `bitcoin` + stdlib; none of those
is a transitive dep of python-bitcoinlib 0.12.2). And advisory status changes over time, so re-run the
commands below before any release rather than trusting this date.

## (c) Crypto/network sub-dependencies
Crypto enters via `bitcoin → secp256k1, bitcoin_hashes` and `rustls → ring`, and via
`python-bitcoinlib` (OpenSSL-backed ECDSA). Network enters via the brk server stack
(`axum → hyper → tokio`) and the bitcoind RPC client (`ureq` + `rustls`/`ring` for TLS).

## (d) Reproducibility
- Rust **crate graph**: reproducible (Cargo.lock pins exact versions + hashes).
- `brk_cli` **binary**: built from source on the host; no deterministic/Guix build configured → not
  bit-reproducible as shipped.
- BTX Python tools: **PyInstaller-frozen → not reproducible** (bundles host Python + libs); no bundle
  hash manifest.
- Bundled `bitcoind` 29.1 / `ord` 0.27.1: copied from the host; **provenance not asserted** — verify
  against the official release checksums / Guix attestations before trusting a distributed bundle.

## (e) Low-bus-factor dependencies (accepted, flagged)
`fjall`, `byteview`, `vecdb`, the `brk_*` crates, and `python-bitcoinlib` are single-maintainer /
first-party-single-author. The storage layer (fjall/byteview/vecdb) holds the reconstructed order
store; `python-bitcoinlib` is on the Python crypto path. These are accepted trust assumptions for a
research preview and are recorded here so they are explicit, not implicit.

## Refresh the audit (run these; they need network / the installed env)
```bash
# Rust: known advisories across all 391 transitive crates (install once: cargo install cargo-audit)
cd brk && cargo audit

# Python: advisories for the pinned runtime dep (install once: pip install pip-audit)
pip-audit -r requirements.txt
pip show python-bitcoinlib   # confirm the installed version + location

# Bundled binaries: verify provenance against official release checksums
bin/bitcoind --version ; bin/ord --version
# then compare sha256 against the published bitcoincore.org / ordinals release hashes
```
