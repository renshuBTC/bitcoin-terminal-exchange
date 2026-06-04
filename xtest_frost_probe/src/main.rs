// Minimal FROST probe: generate 2-of-3 FROST key, sign a message,
// output (shared_xonly_pubkey, message_hash, final_signature) as hex.
// Reads one input per stdin line: <message_hex>.

use schnorr_fun::{
    frost,
    fun::Scalar,
    Message,
};
use sha2::Sha256;
use schnorr_fun::frost::chilldkg::encpedpop;
use schnorr_fun::frost::Fingerprint;
use schnorr_fun::frost::NonceKeyPair;
use std::collections::BTreeMap;
use std::io::{self, BufRead, Write};

fn main() {
    let frost = frost::new_with_deterministic_nonces::<Sha256>();
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();
    let mut rng = rand::thread_rng();

    for line in stdin.lock().lines() {
        let line = line.unwrap();
        if line.is_empty() { continue; }
        // Generate 2-of-3 FROST key fresh per request
        let (shared_key, secret_shares) = encpedpop::simulate_keygen(
            &frost.schnorr, 2, 3, 3, Fingerprint::NONE, &mut rng,
        );
        let xonly_shared = shared_key.into_xonly();
        let xpub_bytes = xonly_shared.public_key().to_xonly_bytes();
        let msg_bytes = hex::decode(line.trim()).expect("bad msg hex");
        let message = Message::raw(&msg_bytes);

        let ss0 = secret_shares[0].into_xonly();
        let ss1 = secret_shares[1].into_xonly();
        let mut rng0: rand_chacha::ChaCha20Rng = frost.seed_nonce_rng(secret_shares[0], b"probe-0");
        let mut rng1: rand_chacha::ChaCha20Rng = frost.seed_nonce_rng(secret_shares[1], b"probe-1");
        let n0 = frost.gen_nonce(&mut rng0);
        let n1 = frost.gen_nonce(&mut rng1);

        let nonces = BTreeMap::from_iter([
            (ss0.index(), n0.public()),
            (ss1.index(), n1.public()),
        ]);
        let coord = frost.coordinator_sign_session(&xonly_shared, nonces, message);
        let parties = coord.parties();
        let agg = coord.agg_binonce();
        let s0 = frost.party_sign_session(ss0.public_key(), parties.clone(), agg, message);
        let s1 = frost.party_sign_session(ss1.public_key(), parties, agg, message);
        let share0 = s0.sign(&ss0, n0);
        let share1 = s1.sign(&ss1, n1);
        let shares = BTreeMap::from_iter([
            (ss0.index(), share0),
            (ss1.index(), share1),
        ]);
        let combined = coord.verify_and_combine_signature_shares(&xonly_shared, shares)
            .expect("combine failed");
        let sig_bytes = combined.to_bytes();
        writeln!(out, "{} {}", hex::encode(xpub_bytes), hex::encode(sig_bytes)).unwrap();
    }
}
