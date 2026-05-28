//! BTX order-artifact parser + order-book state machine, for slotting into a BRK-style indexer.
//!
//! HONEST SCOPE NOTE
//! -----------------
//! I do not have BRK's internal Rust API memorized (module layout, how it yields blocks/txs,
//! its storage engine), so I deliberately wrote the parser and state machine with ZERO external
//! dependencies. Everything BRK- or rust-bitcoin-specific is isolated behind ONE trait,
//! `ChainAccess`. You implement that trait against BRK + rust-bitcoin; leave the rest as-is.
//!
//! This file has NOT been compiled (no rustc in the authoring environment). Treat it as a
//! reviewed sketch. The `tests` module parses a real artifact emitted by `btx_0b.py`, so the
//! wire format is cross-checked against the Python serializer once you `cargo test`.
//!
//! Wire format mirrors btx_0b.py::serialize_artifact, all integers little-endian:
//!   magic "BTX1"(4) | ver(1) | msg_type(1) | side(1) | rune_block(u32) | rune_tx(u16) |
//!   amount(u64) | price(u64) | expiry(u32) | offer_txid(32, internal order) | offer_vout(u32) |
//!   spk_len(1)+payout_spk | pub_len(1)+maker_pubkey(33) | sighash_flag(1) | sig_len(1)+maker_sig

use std::collections::HashMap;

pub const MAGIC: [u8; 4] = *b"BTX1";

#[derive(Debug, Clone)]
pub struct BtxArtifact {
    pub ver: u8,
    pub msg_type: u8, // 1 = new order, 2 = cancel
    pub side: u8,     // 0 = sell asset for BTC, 1 = buy asset with BTC
    pub rune_block: u32,
    pub rune_tx: u16,
    pub amount: u64,  // asset base units offered
    pub price: u64,   // sats per asset unit
    pub expiry: u32,  // block height after which the order is dead
    pub offer_txid: [u8; 32], // internal byte order (as stored in the tx)
    pub offer_vout: u32,
    pub payout_spk: Vec<u8>,   // where the maker is paid (output 0)
    pub maker_pubkey: Vec<u8>, // 33-byte compressed pubkey behind the offer P2WPKH
    pub sighash_flag: u8,      // expected 0x83 = SINGLE|ANYONECANPAY
    pub maker_sig: Vec<u8>,    // DER signature + trailing sighash byte
}

#[derive(Debug, PartialEq)]
pub enum ParseError {
    TooShort,
    BadMagic,
    Truncated,
}

// ---- little-endian readers with bounds checks (no deps) ----
fn take<'a>(b: &'a [u8], o: &mut usize, n: usize) -> Result<&'a [u8], ParseError> {
    if *o + n > b.len() {
        return Err(ParseError::Truncated);
    }
    let s = &b[*o..*o + n];
    *o += n;
    Ok(s)
}
fn rd_u8(b: &[u8], o: &mut usize) -> Result<u8, ParseError> {
    Ok(take(b, o, 1)?[0])
}
fn rd_u16(b: &[u8], o: &mut usize) -> Result<u16, ParseError> {
    let s = take(b, o, 2)?;
    Ok(u16::from_le_bytes([s[0], s[1]]))
}
fn rd_u32(b: &[u8], o: &mut usize) -> Result<u32, ParseError> {
    let s = take(b, o, 4)?;
    Ok(u32::from_le_bytes([s[0], s[1], s[2], s[3]]))
}
fn rd_u64(b: &[u8], o: &mut usize) -> Result<u64, ParseError> {
    let s = take(b, o, 8)?;
    let mut a = [0u8; 8];
    a.copy_from_slice(s);
    Ok(u64::from_le_bytes(a))
}

pub fn parse_artifact(buf: &[u8]) -> Result<BtxArtifact, ParseError> {
    if buf.len() < 4 {
        return Err(ParseError::TooShort);
    }
    if buf[..4] != MAGIC {
        return Err(ParseError::BadMagic);
    }
    let mut o = 4usize;
    let ver = rd_u8(buf, &mut o)?;
    let msg_type = rd_u8(buf, &mut o)?;
    let side = rd_u8(buf, &mut o)?;
    let rune_block = rd_u32(buf, &mut o)?;
    let rune_tx = rd_u16(buf, &mut o)?;
    let amount = rd_u64(buf, &mut o)?;
    let price = rd_u64(buf, &mut o)?;
    let expiry = rd_u32(buf, &mut o)?;
    let mut offer_txid = [0u8; 32];
    offer_txid.copy_from_slice(take(buf, &mut o, 32)?);
    let offer_vout = rd_u32(buf, &mut o)?;
    let spk_len = rd_u8(buf, &mut o)? as usize;
    let payout_spk = take(buf, &mut o, spk_len)?.to_vec();
    let pub_len = rd_u8(buf, &mut o)? as usize;
    let maker_pubkey = take(buf, &mut o, pub_len)?.to_vec();
    let sighash_flag = rd_u8(buf, &mut o)?;
    let sig_len = rd_u8(buf, &mut o)? as usize;
    let maker_sig = take(buf, &mut o, sig_len)?.to_vec();
    Ok(BtxArtifact {
        ver, msg_type, side, rune_block, rune_tx, amount, price, expiry,
        offer_txid, offer_vout, payout_spk, maker_pubkey, sighash_flag, maker_sig,
    })
}

/// Pull a BTX artifact out of an output scriptPubKey. Works for the OP_RETURN carrier
/// (0x6a <pushdata> <payload>) and is liberal: it locates the MAGIC and parses from there.
/// For a Taproot witness-envelope carrier, call `parse_artifact` on the reassembled envelope
/// payload instead; the parser is identical.
pub fn extract_from_script(spk: &[u8]) -> Option<BtxArtifact> {
    spk.windows(4)
        .position(|w| w == MAGIC)
        .and_then(|i| parse_artifact(&spk[i..]).ok())
}

// ============================ order book ============================

#[derive(Debug, Clone, PartialEq)]
pub enum OrderStatus {
    Open,
    Filled,
    Cancelled,
    Expired,
}

#[derive(Debug, Clone)]
pub struct Order {
    pub art: BtxArtifact,
    pub status: OrderStatus,
    pub announce_height: u32,
    pub last_event_height: u32,
}

pub type OutPoint = ([u8; 32], u32);

#[derive(Default)]
pub struct OrderBook {
    orders: HashMap<OutPoint, Order>,
}

impl OrderBook {
    pub fn new() -> Self {
        Self { orders: HashMap::new() }
    }

    /// Admit a validated new-order artifact. Caller (see `index_block`) has already verified the
    /// maker signature and that the offer UTXO is unspent.
    pub fn on_new_order(&mut self, art: BtxArtifact, height: u32) {
        let key = (art.offer_txid, art.offer_vout);
        self.orders.insert(
            key,
            Order { art, status: OrderStatus::Open, announce_height: height, last_event_height: height },
        );
    }

    /// Called for every spent input in a block. If it spends an order's offer UTXO the order is
    /// resolved: a swap-shaped spend (pays the committed payout) => Filled; otherwise (maker
    /// spending the offer UTXO back to self) => Cancelled.
    pub fn on_spend(&mut self, spent: &OutPoint, looks_like_swap: bool, height: u32) {
        if let Some(ord) = self.orders.get_mut(spent) {
            if ord.status == OrderStatus::Open {
                ord.status = if looks_like_swap { OrderStatus::Filled } else { OrderStatus::Cancelled };
                ord.last_event_height = height;
            }
        }
    }

    /// Expire still-open orders whose expiry height has passed.
    pub fn expire(&mut self, height: u32) {
        for ord in self.orders.values_mut() {
            if ord.status == OrderStatus::Open && height > ord.art.expiry {
                ord.status = OrderStatus::Expired;
                ord.last_event_height = height;
            }
        }
    }

    /// Reorg handling: roll the book back to `height`. The book is a projection of chain state,
    /// so drop orders announced above `height` and re-open events that happened above it.
    pub fn revert_to(&mut self, height: u32) {
        self.orders.retain(|_, o| o.announce_height <= height);
        for ord in self.orders.values_mut() {
            if ord.status != OrderStatus::Open && ord.last_event_height > height {
                ord.status = OrderStatus::Open;
                ord.last_event_height = ord.announce_height;
            }
        }
    }

    pub fn open_orders(&self) -> impl Iterator<Item = &Order> {
        self.orders.values().filter(|o| o.status == OrderStatus::Open)
    }
}

// ===================== the single BRK / rust-bitcoin seam =====================

pub trait ChainAccess {
    /// (value_sats, scriptPubKey) of an UNSPENT output; None if spent or absent.
    /// Wire to BRK's UTXO set (or `gettxout` while prototyping).
    fn get_utxo(&self, txid: &[u8; 32], vout: u32) -> Option<(u64, Vec<u8>)>;

    /// Full maker-signature validation using rust-bitcoin + secp256k1. Must check BOTH:
    ///   1. hash160(art.maker_pubkey) equals the offer UTXO's P2WPKH witness program (`offer_spk`)
    ///   2. the BIP143 SINGLE|ANYONECANPAY sighash over the partial tx
    ///      [ offer-input , (art.price, art.payout_spk) as output 0 ] verifies against maker_pubkey
    /// (Mirror btx_0b.py::verify_maker_sig.)
    fn verify_maker_sig(&self, art: &BtxArtifact, offer_value_sats: u64, offer_spk: &[u8]) -> bool;
}

/// Is this parsed artifact a live, authorized OPEN order against current chain state?
pub fn validate<C: ChainAccess>(chain: &C, art: &BtxArtifact, height: u32) -> bool {
    if art.msg_type != 1 {
        return false; // only new-order artifacts open orders
    }
    if height > art.expiry {
        return false;
    }
    match chain.get_utxo(&art.offer_txid, art.offer_vout) {
        Some((val, spk)) => chain.verify_maker_sig(art, val, &spk),
        None => false, // offer UTXO already spent/absent -> not a live order
    }
}

/// EXACT fill classifier (not a heuristic). A confirmed tx spending the offer UTXO is a FILL iff the
/// output AT THE OFFER'S INPUT INDEX equals exactly `(art.price, art.payout_spk)`. The maker's
/// SINGLE|ANYONECANPAY signature consensus-enforces the output at the SAME index as its input, so any
/// confirmed spend that USES the maker's pre-signature must carry the committed payout there; a spend
/// lacking it can only be the maker spending their own UTXO with a different signature => CANCEL.
/// IMPORTANT: pass the output at the offer's input index, NOT always output 0 — a batch fill puts
/// offer_k at input k and payout_k at output k, so output 0 is the committed payout only at input 0.
/// (Mirrors classify_test.py and brk-btx btx.rs pass 2.)
pub fn is_fill(spend_output_at_input_index: Option<(u64, &[u8])>, art: &BtxArtifact) -> bool {
    match spend_output_at_input_index {
        Some((value, spk)) => value == art.price && spk == art.payout_spk.as_slice(),
        None => false,
    }
}

/// Drive this from BRK's per-block hook.
/// - `new_artifacts`: every artifact you extracted from this block's output scripts
///   (run `extract_from_script` over each output's scriptPubKey).
/// - `spends`: for every input in the block, its prevout plus the fill flag computed by
///   `is_fill(spending_tx_output0, &order.art)` — true => Filled, false => maker self-cancel.
pub fn index_block<C: ChainAccess>(
    book: &mut OrderBook,
    chain: &C,
    height: u32,
    new_artifacts: &[BtxArtifact],
    spends: &[(OutPoint, bool)],
) {
    for art in new_artifacts {
        if validate(chain, art, height) {
            book.on_new_order(art.clone(), height);
        }
    }
    for (op, is_swap) in spends {
        book.on_spend(op, *is_swap, height);
    }
    book.expire(height);
}

// ============================ tests ============================
#[cfg(test)]
mod tests {
    use super::*;

    // Real artifact emitted by `btx_0b.py artifact ...` (offer txid = 0xaa*32, price 0.5 BTC).
    const ARTIFACT_HEX: &str = "4254583101010040d10c000100e80300000000000080f0fa020000000000ca9a3baaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa00000000160014e9dd842d95a053c513315291f4d3f93b5a41059a2102bbfcf90b65934a165af1508d129cd749e7643bf75c66bd7f209a15f0b1497d7a83483045022100bf64c8956b722549d05acc98fdc0d834d6fa4d8ee2038d2a160476b58d848c0c022067458f34124bdd0ed6a1cb5b63f0a70b9f8ea011d75df51ea4cc937e20cfc6b983";

    fn unhex(s: &str) -> Vec<u8> {
        (0..s.len()).step_by(2).map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap()).collect()
    }

    #[test]
    fn parses_python_artifact() {
        let a = parse_artifact(&unhex(ARTIFACT_HEX)).expect("parse");
        assert_eq!(a.ver, 1);
        assert_eq!(a.msg_type, 1);
        assert_eq!(a.side, 0);
        assert_eq!(a.rune_block, 840_000);
        assert_eq!(a.rune_tx, 1);
        assert_eq!(a.amount, 1000);
        assert_eq!(a.price, 50_000_000); // 0.5 BTC
        assert_eq!(a.expiry, 1_000_000_000);
        assert_eq!(a.offer_txid, [0xaa; 32]);
        assert_eq!(a.offer_vout, 0);
        assert_eq!(a.payout_spk.len(), 22); // P2WPKH: OP_0 <20-byte hash>
        assert_eq!(a.maker_pubkey.len(), 33);
        assert_eq!(a.sighash_flag, 0x83); // SINGLE|ANYONECANPAY
    }

    #[test]
    fn rejects_bad_magic() {
        assert_eq!(parse_artifact(b"XXXXrest").unwrap_err(), ParseError::BadMagic);
    }

    #[test]
    fn fill_then_reorg_reopens() {
        let a = parse_artifact(&unhex(ARTIFACT_HEX)).unwrap();
        let key = (a.offer_txid, a.offer_vout);
        let mut book = OrderBook::new();
        book.on_new_order(a, 100);
        book.on_spend(&key, true, 105); // filled at height 105
        assert_eq!(book.open_orders().count(), 0);
        book.revert_to(104); // reorg below the fill
        assert_eq!(book.open_orders().count(), 1); // order is open again
    }

    #[test]
    fn classifies_fill_vs_cancel() {
        let a = parse_artifact(&unhex(ARTIFACT_HEX)).unwrap();
        // output 0 == committed (price, payout_spk) => FILL
        assert!(is_fill(Some((a.price, a.payout_spk.as_slice())), &a));
        // payout spk but wrong (low) amount => cannot be the maker's pre-signed fill => CANCEL
        assert!(!is_fill(Some((a.price - 1, a.payout_spk.as_slice())), &a));
        // maker self-spend to some other script => CANCEL
        assert!(!is_fill(Some((a.price, b"\x00\x14".as_slice())), &a));
        // no outputs => CANCEL
        assert!(!is_fill(None, &a));
    }
}
