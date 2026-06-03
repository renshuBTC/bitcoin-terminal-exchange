// rb_taproot_probe — stdin/stdout bridge for cross-testing BTX's pure-
// Python BIP-341 Taproot tweak against rust-bitcoin's bitcoin::taproot.
//
// Protocol: one whitespace-separated record per stdin line:
//
//   <internal_xonly_hex> [merkle_root_hex]
//
// (merkle_root is optional; if omitted/empty, key-path-only tweak)
//
// Emits one line per record on stdout:
//
//   <output_xonly_hex> <parity_bool> <tap_tweak_hash_hex>
//
// Parity is "true" if Odd, "false" if Even.
//
// Build with: `cargo build --release` (output at target/release/rb_taproot_probe).
// Run from btx_xtest_vs_rust_bitcoin_taproot.py — that test will find
// the binary at one of the known locations or skip gracefully.

use bitcoin::key::TapTweak;
use bitcoin::secp256k1::{Secp256k1, XOnlyPublicKey};
use bitcoin::taproot::TapNodeHash;
use bitcoin::TapTweakHash;
use std::io::{self, BufRead, Write};
use std::str::FromStr;

fn main() {
    let secp = Secp256k1::new();
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();

    for line in stdin.lock().lines() {
        let line = line.unwrap();
        if line.is_empty() {
            continue;
        }
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.is_empty() {
            continue;
        }
        let xonly_bytes = hex::decode(parts[0]).expect("bad xonly hex");
        let internal = XOnlyPublicKey::from_slice(&xonly_bytes).expect("bad xonly");
        let merkle_root: Option<TapNodeHash> = if parts.len() > 1 && !parts[1].is_empty() {
            Some(TapNodeHash::from_str(parts[1]).expect("bad TapNodeHash"))
        } else {
            None
        };
        let (output_key, parity) = internal.tap_tweak(&secp, merkle_root);
        let tweak = TapTweakHash::from_key_and_tweak(internal, merkle_root);
        writeln!(
            out,
            "{} {} {}",
            hex::encode(output_key.serialize()),
            parity == bitcoin::secp256k1::Parity::Odd,
            tweak.to_string(),
        )
        .unwrap();
    }
}
