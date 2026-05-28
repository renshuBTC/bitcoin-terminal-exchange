//! Standalone compile+behavior check of the BTX verify path against real bitcoin 0.32.9.
use bitcoin::hashes::Hash as _;
use bitcoin::sighash::SighashCache;
use bitcoin::{
    Amount, EcdsaSighashType, OutPoint as BtcOutPoint, ScriptBuf, Sequence, Transaction, TxIn,
    TxOut, Txid, Witness, absolute::LockTime, transaction::Version,
};
use secp256k1::{Message, PublicKey, Secp256k1, ecdsa::Signature};

pub const MAGIC: [u8; 4] = *b"BTX1";

#[derive(Debug, Clone)]
pub struct BtxArtifact {
    pub ver: u8, pub msg_type: u8, pub side: u8, pub rune_block: u32, pub rune_tx: u16,
    pub amount: u64, pub price: u64, pub expiry: u32, pub group_id: u64, pub offer_txid: [u8; 32], pub offer_vout: u32,
    pub payout_spk: Vec<u8>, pub maker_pubkey: Vec<u8>, pub sighash_flag: u8, pub maker_sig: Vec<u8>,
}

#[derive(Debug, PartialEq)]
pub enum ParseError { TooShort, BadMagic, Truncated }

fn take<'a>(b: &'a [u8], o: &mut usize, n: usize) -> Result<&'a [u8], ParseError> {
    if *o + n > b.len() { return Err(ParseError::Truncated); }
    let s = &b[*o..*o + n]; *o += n; Ok(s)
}
fn rd_u8(b: &[u8], o: &mut usize) -> Result<u8, ParseError> { Ok(take(b, o, 1)?[0]) }
fn rd_u16(b: &[u8], o: &mut usize) -> Result<u16, ParseError> { let s = take(b, o, 2)?; Ok(u16::from_le_bytes([s[0], s[1]])) }
fn rd_u32(b: &[u8], o: &mut usize) -> Result<u32, ParseError> { let s = take(b, o, 4)?; Ok(u32::from_le_bytes([s[0], s[1], s[2], s[3]])) }
fn rd_u64(b: &[u8], o: &mut usize) -> Result<u64, ParseError> { let s = take(b, o, 8)?; let mut a=[0u8;8]; a.copy_from_slice(s); Ok(u64::from_le_bytes(a)) }

pub fn parse_artifact(buf: &[u8]) -> Result<BtxArtifact, ParseError> {
    if buf.len() < 4 { return Err(ParseError::TooShort); }
    if buf[..4] != MAGIC { return Err(ParseError::BadMagic); }
    let mut o = 4usize;
    let ver = rd_u8(buf, &mut o)?; let msg_type = rd_u8(buf, &mut o)?; let side = rd_u8(buf, &mut o)?;
    let rune_block = rd_u32(buf, &mut o)?; let rune_tx = rd_u16(buf, &mut o)?;
    let amount = rd_u64(buf, &mut o)?; let price = rd_u64(buf, &mut o)?; let expiry = rd_u32(buf, &mut o)?;
    let group_id = if ver >= 2 { rd_u64(buf, &mut o)? } else { 0 };
    let mut offer_txid = [0u8; 32]; offer_txid.copy_from_slice(take(buf, &mut o, 32)?);
    let offer_vout = rd_u32(buf, &mut o)?;
    let spk_len = rd_u8(buf, &mut o)? as usize; let payout_spk = take(buf, &mut o, spk_len)?.to_vec();
    let pub_len = rd_u8(buf, &mut o)? as usize; let maker_pubkey = take(buf, &mut o, pub_len)?.to_vec();
    let sighash_flag = rd_u8(buf, &mut o)?;
    let sig_len = rd_u8(buf, &mut o)? as usize; let maker_sig = take(buf, &mut o, sig_len)?.to_vec();
    Ok(BtxArtifact { ver, msg_type, side, rune_block, rune_tx, amount, price, expiry, group_id, offer_txid, offer_vout, payout_spk, maker_pubkey, sighash_flag, maker_sig })
}

pub fn verify_maker_sig(art: &BtxArtifact, offer_value_sats: u64, offer_spk: &[u8]) -> bool {
    if offer_spk.len() != 22 || offer_spk[0] != 0x00 || offer_spk[1] != 0x14 { return false; }
    let pkh = bitcoin::hashes::hash160::Hash::hash(&art.maker_pubkey);
    if pkh.to_byte_array()[..] != offer_spk[2..22] { return false; }
    if art.maker_sig.is_empty() { return false; }
    let txid = Txid::from_byte_array(art.offer_txid);
    let input = TxIn { previous_output: BtcOutPoint { txid, vout: art.offer_vout }, script_sig: ScriptBuf::new(), sequence: Sequence::MAX, witness: Witness::new() };
    let output = TxOut { value: Amount::from_sat(art.price), script_pubkey: ScriptBuf::from_bytes(art.payout_spk.clone()) };
    let tx = Transaction { version: Version::ONE, lock_time: LockTime::ZERO, input: vec![input], output: vec![output] };
    let spk = ScriptBuf::from_bytes(offer_spk.to_vec());
    let mut cache = SighashCache::new(&tx);
    let sighash = match cache.p2wpkh_signature_hash(0, &spk, Amount::from_sat(offer_value_sats), EcdsaSighashType::SinglePlusAnyoneCanPay) {
        Ok(s) => s, Err(_) => return false,
    };
    let der = &art.maker_sig[..art.maker_sig.len() - 1];
    let sig = match Signature::from_der(der) { Ok(s) => s, Err(_) => return false };
    let pk = match PublicKey::from_slice(&art.maker_pubkey) { Ok(p) => p, Err(_) => return false };
    let msg = Message::from_digest(sighash.to_byte_array());
    Secp256k1::verification_only().verify_ecdsa(&msg, &sig, &pk).is_ok()
}

pub fn p2wpkh_spk_from_pubkey(pubkey: &[u8]) -> Vec<u8> {
    let pkh = bitcoin::hashes::hash160::Hash::hash(pubkey);
    let mut spk = vec![0x00u8, 0x14u8];
    spk.extend_from_slice(&pkh.to_byte_array());
    spk
}

#[cfg(test)]
mod tests {
    use super::*;
    // EXACT artifact emitted by python-bitcoinlib (btx_0b.py): offer amount was 1.0 BTC.
    const ARTIFACT_HEX: &str = "4254583102010040d10c000100e80300000000000080f0fa020000000000ca9a3b0000000000000000aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa00000000160014e9dd842d95a053c513315291f4d3f93b5a41059a2102bbfcf90b65934a165af1508d129cd749e7643bf75c66bd7f209a15f0b1497d7a8347304402205be5b4425958d1d6e0f8eb67cf4a7a2dc091d5d5f1ea08bc776896a03d8bfb3102205e6433b48f725d819e039749bd427299d33e4ba28b4e8ebb231d2574dc35577f83";
    const OFFER_AMOUNT_SATS: u64 = 100_000_000; // 1.0 BTC

    fn unhex(s: &str) -> Vec<u8> {
        (0..s.len()).step_by(2).map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap()).collect()
    }

    #[test]
    fn python_signed_artifact_verifies_in_rust() {
        let art = parse_artifact(&unhex(ARTIFACT_HEX)).unwrap();
        let offer_spk = p2wpkh_spk_from_pubkey(&art.maker_pubkey);
        assert!(verify_maker_sig(&art, OFFER_AMOUNT_SATS, &offer_spk),
                "python-bitcoinlib signature must verify under the Rust verifier");
    }

    #[test]
    fn tampered_price_fails() {
        let mut art = parse_artifact(&unhex(ARTIFACT_HEX)).unwrap();
        let offer_spk = p2wpkh_spk_from_pubkey(&art.maker_pubkey);
        art.price -= 1; // changes output 0 -> sighash no longer matches the signature
        assert!(!verify_maker_sig(&art, OFFER_AMOUNT_SATS, &offer_spk));
    }

    #[test]
    fn wrong_offer_amount_fails() {
        let art = parse_artifact(&unhex(ARTIFACT_HEX)).unwrap();
        let offer_spk = p2wpkh_spk_from_pubkey(&art.maker_pubkey);
        assert!(!verify_maker_sig(&art, OFFER_AMOUNT_SATS + 1, &offer_spk));
    }
}

// ===== order book + per-tx indexing (mirrors btx.rs; tx slice instead of block.txdata) =====
use std::collections::HashMap;

pub fn extract_from_script(spk: &[u8]) -> Option<BtxArtifact> {
    spk.windows(4).position(|w| w == MAGIC).and_then(|i| parse_artifact(&spk[i..]).ok())
}

#[derive(Debug, Clone, PartialEq)]
pub enum OrderStatus { Open, Filled, Cancelled, Expired }

#[derive(Debug, Clone)]
pub struct Order { pub art: BtxArtifact, pub status: OrderStatus, pub announce_height: u32, pub last_event_height: u32 }

pub type Op = ([u8; 32], u32);

#[derive(Default)]
pub struct OrderBook { orders: HashMap<Op, Order> }

impl OrderBook {
    pub fn new() -> Self { Self { orders: HashMap::new() } }
    pub fn on_new_order(&mut self, art: BtxArtifact, height: u32) {
        let key = (art.offer_txid, art.offer_vout);
        self.orders.insert(key, Order { art, status: OrderStatus::Open, announce_height: height, last_event_height: height });
    }
    pub fn resolve_spend(&mut self, spent: &Op, spend_output0: Option<(u64, &[u8])>, height: u32) {
        if let Some(ord) = self.orders.get_mut(spent) {
            if ord.status == OrderStatus::Open {
                let filled = match spend_output0 { Some((v, s)) => v == ord.art.price && s == ord.art.payout_spk.as_slice(), None => false };
                ord.status = if filled { OrderStatus::Filled } else { OrderStatus::Cancelled };
                ord.last_event_height = height;
            }
        }
    }
    pub fn expire(&mut self, height: u32) {
        for ord in self.orders.values_mut() {
            if ord.status == OrderStatus::Open && height > ord.art.expiry { ord.status = OrderStatus::Expired; ord.last_event_height = height; }
        }
    }
    pub fn revert_to(&mut self, height: u32) {
        self.orders.retain(|_, o| o.announce_height <= height);
        for ord in self.orders.values_mut() {
            if ord.status != OrderStatus::Open && ord.last_event_height > height { ord.status = OrderStatus::Open; ord.last_event_height = ord.announce_height; }
        }
    }
    pub fn open_orders(&self) -> impl Iterator<Item = &Order> { self.orders.values().filter(|o| o.status == OrderStatus::Open) }
    pub fn get(&self, key: &Op) -> Option<&Order> { self.orders.get(key) }
}

/// Same body as btx.rs::index_block_brk, but over a tx slice with a closure UTXO source.
pub fn index_txs<F>(book: &mut OrderBook, get_utxo: F, txs: &[bitcoin::Transaction], height: u32)
where F: Fn(&[u8; 32], u32) -> Option<(u64, Vec<u8>)> {
    for tx in txs {
        for txout in &tx.output {
            if let Some(art) = extract_from_script(txout.script_pubkey.as_bytes()) {
                if art.msg_type == 1 && height <= art.expiry {
                    if let Some((val, spk)) = get_utxo(&art.offer_txid, art.offer_vout) {
                        if verify_maker_sig(&art, val, &spk) { book.on_new_order(art, height); }
                    }
                }
            }
        }
    }
    for tx in txs {
        if tx.is_coinbase() { continue; }
        let out0 = tx.output.first().map(|o| (o.value.to_sat(), o.script_pubkey.as_bytes().to_vec()));
        for txin in &tx.input {
            let key: Op = (txin.previous_output.txid.to_byte_array(), txin.previous_output.vout);
            if book.get(&key).is_some() {
                let o0 = out0.as_ref().map(|(v, s)| (*v, s.as_slice()));
                book.resolve_spend(&key, o0, height);
            }
        }
    }
    book.expire(height);
}

#[cfg(test)]
mod book_tests {
    use super::*;
    use bitcoin::{Amount, OutPoint, ScriptBuf, Sequence, Transaction, TxIn, TxOut, Txid, Witness, absolute::LockTime, transaction::Version};

    const ARTIFACT_HEX: &str = "4254583102010040d10c000100e80300000000000080f0fa020000000000ca9a3b0000000000000000aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa00000000160014e9dd842d95a053c513315291f4d3f93b5a41059a2102bbfcf90b65934a165af1508d129cd749e7643bf75c66bd7f209a15f0b1497d7a8347304402205be5b4425958d1d6e0f8eb67cf4a7a2dc091d5d5f1ea08bc776896a03d8bfb3102205e6433b48f725d819e039749bd427299d33e4ba28b4e8ebb231d2574dc35577f83";
    // OP_RETURN carrier for that artifact (6a 4cc8 = OP_RETURN PUSHDATA1 200) from btx_0b.py.
    const CARRIER_HEX: &str = "6a4cc84254583102010040d10c000100e80300000000000080f0fa020000000000ca9a3b0000000000000000aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa00000000160014e9dd842d95a053c513315291f4d3f93b5a41059a2102bbfcf90b65934a165af1508d129cd749e7643bf75c66bd7f209a15f0b1497d7a8347304402205be5b4425958d1d6e0f8eb67cf4a7a2dc091d5d5f1ea08bc776896a03d8bfb3102205e6433b48f725d819e039749bd427299d33e4ba28b4e8ebb231d2574dc35577f83";
    fn unhex(s: &str) -> Vec<u8> { (0..s.len()).step_by(2).map(|i| u8::from_str_radix(&s[i..i+2],16).unwrap()).collect() }

    fn announce_tx() -> Transaction {
        Transaction { version: Version::TWO, lock_time: LockTime::ZERO, input: vec![],
            output: vec![TxOut { value: Amount::from_sat(0), script_pubkey: ScriptBuf::from_bytes(unhex(CARRIER_HEX)) }] }
    }
    fn spend_tx(payout_value: u64, payout_spk: Vec<u8>) -> Transaction {
        let offer = OutPoint { txid: Txid::from_byte_array([0xaa;32]), vout: 0 };
        Transaction { version: Version::TWO, lock_time: LockTime::ZERO,
            input: vec![TxIn { previous_output: offer, script_sig: ScriptBuf::new(), sequence: Sequence::MAX, witness: Witness::new() }],
            output: vec![TxOut { value: Amount::from_sat(payout_value), script_pubkey: ScriptBuf::from_bytes(payout_spk) }] }
    }

    #[test]
    fn end_to_end_open_then_fill_then_reorg() {
        let art = parse_artifact(&unhex(ARTIFACT_HEX)).unwrap();
        let offer_spk = p2wpkh_spk_from_pubkey(&art.maker_pubkey);
        let payout = art.payout_spk.clone();
        let osp = offer_spk.clone();
        let get_utxo = move |txid: &[u8;32], _v: u32| -> Option<(u64, Vec<u8>)> {
            if *txid == [0xaa;32] { Some((100_000_000, osp.clone())) } else { None }
        };
        let mut book = OrderBook::new();
        // block 100: announce -> verified open order
        index_txs(&mut book, &get_utxo, &[announce_tx()], 100);
        assert_eq!(book.open_orders().count(), 1, "python-signed order opens after on-chain verify");
        // block 101: spend with committed payout -> FILL
        index_txs(&mut book, &get_utxo, &[spend_tx(50_000_000, payout.clone())], 101);
        assert_eq!(book.open_orders().count(), 0);
        // reorg back below the fill -> reopen
        book.revert_to(100);
        assert_eq!(book.open_orders().count(), 1);
        // wrong payout amount spend -> CANCEL (not a valid maker-signed fill)
        index_txs(&mut book, &get_utxo, &[spend_tx(40_000_000, payout.clone())], 102);
        assert_eq!(book.open_orders().count(), 0);
        let _ = offer_spk;
    }
}
