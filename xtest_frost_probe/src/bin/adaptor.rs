// secp256kfun adaptor signing probe. Per stdin line: <msg_hex>.
// Emits: <signing_xonly_pubkey> <decryption_key_hex> <final_sig_hex>
// (after encrypt-then-decrypt round-trip via the adaptor scheme).

use schnorr_fun::{Schnorr, Message, adaptor::{EncryptedSign, Adaptor}, fun::Scalar};
use sha2::Sha256;
use schnorr_fun::nonce::Deterministic;
use std::io::{self, BufRead, Write};

fn main() {
    let schnorr = Schnorr::<Sha256, Deterministic<Sha256>>::default();
    let mut rng = rand::thread_rng();
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();

    for line in stdin.lock().lines() {
        let line = line.unwrap();
        if line.is_empty() { continue; }
        let msg_bytes = hex::decode(line.trim()).expect("bad msg hex");

        // Fresh signing + decryption keys
        let signing_keypair = schnorr.new_keypair(Scalar::random(&mut rng));
        let decryption_key = Scalar::random(&mut rng);
        let encryption_key = schnorr.encryption_key_for(&decryption_key);

        let message = Message::raw(&msg_bytes);
        let encrypted_sig = schnorr.encrypted_sign(
            &signing_keypair, &encryption_key, message,
        );
        let final_sig = schnorr.decrypt_signature(
            decryption_key.public(), encrypted_sig,
        );

        let xpub = signing_keypair.public_key().to_xonly_bytes();
        let dkey = decryption_key.to_bytes();
        let sig_bytes = final_sig.to_bytes();
        writeln!(out, "{} {} {}",
            hex::encode(xpub),
            hex::encode(dkey),
            hex::encode(sig_bytes),
        ).unwrap();
    }
}
