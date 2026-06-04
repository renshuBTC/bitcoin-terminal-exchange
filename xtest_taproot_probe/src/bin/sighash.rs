// rb_sighash_probe — stdin/stdout bridge for cross-testing BTX's
// pure-Python BIP-341 keyPathSpending TapSighash against
// rust-bitcoin's bitcoin::sighash::SighashCache.
//
// Protocol: one whitespace-separated record per stdin line:
//
//   <tx_hex> <input_index> <sighash_byte> <num_prevouts>
//   <spk_hex_0> <amount_sats_0> [<spk_hex_1> <amount_sats_1> ...]
//
// Emits one line per record on stdout:
//
//   <tap_sighash_hex>   (32 bytes hex)

use bitcoin::consensus::encode;
use bitcoin::sighash::{Prevouts, SighashCache, TapSighashType};
use bitcoin::{Amount, ScriptBuf, Transaction, TxOut};
use std::io::{self, BufRead, Write};

fn main() {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();

    for line in stdin.lock().lines() {
        let line = line.unwrap();
        if line.is_empty() {
            continue;
        }
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() < 4 {
            continue;
        }
        let tx_hex = parts[0];
        let input_index: usize = parts[1].parse().expect("bad input_index");
        let sighash_byte: u8 = parts[2].parse().expect("bad sighash_byte");
        let num_prevouts: usize = parts[3].parse().expect("bad num_prevouts");
        let mut prevouts: Vec<TxOut> = Vec::with_capacity(num_prevouts);
        for i in 0..num_prevouts {
            let spk_bytes = hex::decode(parts[4 + i * 2]).expect("bad spk hex");
            let spk = ScriptBuf::from_bytes(spk_bytes);
            let amt_sats: u64 = parts[5 + i * 2].parse().expect("bad amount");
            prevouts.push(TxOut {
                script_pubkey: spk,
                value: Amount::from_sat(amt_sats),
            });
        }
        let tx_bytes = hex::decode(tx_hex).expect("bad tx hex");
        let tx: Transaction = encode::deserialize(&tx_bytes).expect("bad tx");
        let mut cache = SighashCache::new(&tx);
        let sht =
            TapSighashType::from_consensus_u8(sighash_byte).expect("bad sighash_type");
        let sh = cache
            .taproot_key_spend_signature_hash(input_index, &Prevouts::All(&prevouts), sht)
            .expect("sighash failed");
        // TapSighash deref/as_ref gives 32 bytes
        let bytes: &[u8] = sh.as_ref();
        writeln!(out, "{}", hex::encode(bytes)).unwrap();
    }
}
