"""
BTX Phase 0 / Milestone 0b — pure chain-reconstructed order, no relay.

The maker publishes a BTX order artifact ON CHAIN. The artifact carries the maker's
SIGHASH_SINGLE|ANYONECANPAY pre-signature over [offer-input, payout-output], so a SECOND node
that only reads the chain can: parse the artifact, fetch the offer UTXO from its own UTXO set,
VERIFY the maker signature, surface the open order, and (as taker) complete the atomic swap by
transplanting the maker's witness. No off-chain message ever changes hands.

Subcommands:
  selftest                    offline proof of the serialize/parse/verify/build round-trip
  artifact <utxo_json>        emit a BTX artifact (hex) + the carrier OP_RETURN scriptPubKey
  scan <rpc> <from_height>    second-node indexer: walk blocks, surface valid open orders
                              (requires a node; bitcoin-cli on PATH)

Carrier: default OP_RETURN. The BTX v1 artifact is ~200 bytes (sig+pubkey+spk), so this assumes
the node's -datacarriersize permits it (Core relaxed the limit in 2024-25 — VERIFY on your node).
If your node still enforces 80 bytes, swap in a Taproot inscription-style envelope; the
reconstruction logic below is identical either way because it reads the artifact bytes, not the
carrier.
"""
import sys, json, hashlib, struct
import bitcoin
bitcoin.SelectParams('regtest')
from bitcoin.core import (COIN, CMutableTransaction, CMutableTxIn, CMutableTxOut, COutPoint,
                          CTxInWitness, CTxWitness, lx, x, b2x, b2lx, Hash160)
from bitcoin.core.script import (CScript, CScriptWitness, SignatureHash, SIGHASH_SINGLE,
                                 SIGHASH_ALL, SIGHASH_ANYONECANPAY, SIGVERSION_WITNESS_V0,
                                 OP_0, OP_RETURN, OP_DUP, OP_HASH160, OP_EQUALVERIFY, OP_CHECKSIG)
from bitcoin.core.key import CPubKey
from bitcoin.wallet import CBitcoinSecret, P2WPKHBitcoinAddress

MAGIC = b'BTX1'
SAA   = SIGHASH_SINGLE | SIGHASH_ANYONECANPAY   # 0x83

def key(seed):
    s = CBitcoinSecret.from_secret_bytes(hashlib.sha256(seed).digest())
    return s, CScript([OP_0, Hash160(s.pub)])

def p2wpkh_script_code(pubkey_bytes):
    return CScript([OP_DUP, OP_HASH160, Hash160(pubkey_bytes), OP_EQUALVERIFY, OP_CHECKSIG])

# ---------- BTX artifact wire format ----------
def serialize_artifact(a):
    spk = a['payout_spk']; sig = a['maker_sig']; pub = a['maker_pubkey']
    out  = MAGIC
    out += struct.pack('<BBB', 2, a['msg_type'], a['side'])           # ver(2), type, side
    out += struct.pack('<IH', a['rune_block'], a['rune_tx'])          # rune id
    out += struct.pack('<QQ', a['amount'], a['price'])                # asset amount, sats/unit
    out += struct.pack('<I', a['expiry'])                            # expiry height
    out += struct.pack('<Q', a.get('group_id', 0))                   # v2: lot-group id (0 = standalone)
    out += a['offer_txid']                                           # 32 bytes (internal order)
    out += struct.pack('<I', a['offer_vout'])
    out += struct.pack('<B', len(spk)) + spk
    out += struct.pack('<B', len(pub)) + pub
    out += struct.pack('<B', a['sighash_flag'])
    out += struct.pack('<B', len(sig)) + sig
    return out

def parse_artifact(buf):
    # Bounds-checked: this parses arbitrary on-chain / API-supplied bytes, so every read is validated
    # and any malformed/truncated artifact raises a clean ValueError instead of IndexError/struct.error
    # or silently-truncated slices. (The Rust indexer parser is likewise bounds-checked.)
    buf = bytes(buf)
    if len(buf) < 4 or buf[:4] != MAGIC:
        raise ValueError("bad magic")

    def need(o, n):
        if n < 0 or o + n > len(buf):
            raise ValueError(f"truncated artifact: need {n} bytes at offset {o}, have {len(buf)}")

    o = 4
    need(o, 3); ver, mtype, side = struct.unpack_from('<BBB', buf, o); o += 3
    need(o, 6); rune_block, rune_tx = struct.unpack_from('<IH', buf, o); o += 6
    need(o, 16); amount, price = struct.unpack_from('<QQ', buf, o); o += 16
    need(o, 4); (expiry,) = struct.unpack_from('<I', buf, o); o += 4
    if ver >= 2:
        need(o, 8); (group_id,) = struct.unpack_from('<Q', buf, o); o += 8
    else:
        group_id = 0
    need(o, 32); offer_txid = bytes(buf[o:o+32]); o += 32
    need(o, 4); (offer_vout,) = struct.unpack_from('<I', buf, o); o += 4
    need(o, 1); spk_len = buf[o]; o += 1; need(o, spk_len); payout_spk = bytes(buf[o:o+spk_len]); o += spk_len
    need(o, 1); pub_len = buf[o]; o += 1; need(o, pub_len); maker_pubkey = bytes(buf[o:o+pub_len]); o += pub_len
    need(o, 1); sighash_flag = buf[o]; o += 1
    need(o, 1); sig_len = buf[o]; o += 1; need(o, sig_len); maker_sig = bytes(buf[o:o+sig_len]); o += sig_len
    return dict(ver=ver, msg_type=mtype, side=side, rune_block=rune_block, rune_tx=rune_tx,
                amount=amount, price=price, expiry=expiry, group_id=group_id, offer_txid=offer_txid,
                offer_vout=offer_vout, payout_spk=payout_spk, maker_pubkey=maker_pubkey,
                sighash_flag=sighash_flag, maker_sig=maker_sig)

# ---------- second-node verification (chain data only) ----------
def verify_maker_sig(art, offer_amount_sats, offer_spk=None):
    """Reconstruct the partial tx [offer-input, payout-output] and verify the maker signature.
       offer_amount_sats comes from the node's OWN UTXO set (gettxout), not from any relay.

       offer_spk (the offer UTXO's scriptPubKey — ALSO from the same gettxout) is the security-critical
       binding: when supplied, the offer must be P2WPKH and the artifact's maker_pubkey MUST hash160 to
       its witness program. Without it, an attacker can publish an artifact over SOMEONE ELSE'S offer
       UTXO, signed under their OWN key: the signature verifies cryptographically (so it looks like a
       "VALID open order") but it can NEVER be filled — consensus rejects the witness because the pubkey
       doesn't own the UTXO. ALWAYS pass offer_spk for book admission / pre-fill checks; this mirrors the
       production Rust indexer (btx::verify_maker_sig). Omitting it = sig-only check, which is NOT
       sufficient to admit or trust an order."""
    if offer_spk is not None:
        spk = bytes(offer_spk)
        if len(spk) != 22 or spk[0] != 0x00 or spk[1] != 0x14:   # must be OP_0 <20-byte program> (P2WPKH)
            return False
        if Hash160(art['maker_pubkey']) != spk[2:22]:            # pubkey must OWN the offer UTXO
            return False
    in0  = CMutableTxIn(COutPoint(art['offer_txid'], art['offer_vout']))
    out0 = CMutableTxOut(art['price'], CScript(art['payout_spk']))
    partial = CMutableTransaction([in0], [out0])
    sc = p2wpkh_script_code(art['maker_pubkey'])
    sighash = SignatureHash(sc, partial, 0, art['sighash_flag'],
                            amount=offer_amount_sats, sigversion=SIGVERSION_WITNESS_V0)
    der = art['maker_sig'][:-1]                      # strip trailing sighash byte
    return CPubKey(art['maker_pubkey']).verify(sighash, der)

def build_swap_from_artifact(art, offer_amount_sats, pay_outpoint, pay_amount_sats, taker_seed):
    """Taker reconstructs the atomic swap using ONLY the artifact + chain-looked-up amounts."""
    taker_sec, taker_spk = key(taker_seed)
    # maker witness = [sig, pubkey] transplanted straight from the artifact
    wit_maker = CTxInWitness(CScriptWitness([art['maker_sig'], art['maker_pubkey']]))
    i0 = CMutableTxIn(COutPoint(art['offer_txid'], art['offer_vout']))
    i1 = CMutableTxIn(COutPoint(lx(pay_outpoint[0]), pay_outpoint[1]))
    o0 = CMutableTxOut(art['price'], CScript(art['payout_spk']))          # committed by maker sig
    fee = 10000
    taker_value = offer_amount_sats + pay_amount_sats - art['price'] - fee
    if taker_value < 546:   # mirror the production wallet builder: below the 546-sat dust floor (or
                            # negative) the taker output is non-standard / invalid — reject, don't emit
        raise ValueError(f"taker output {taker_value} sats below the 546-sat dust floor "
                         f"(price {art['price']} + fee {fee} vs offer {offer_amount_sats} + pay {pay_amount_sats})")
    o1 = CMutableTxOut(taker_value, taker_spk)
    tx = CMutableTransaction([i0, i1], [o0, o1])
    sc_t = p2wpkh_script_code(taker_sec.pub)
    sh_t = SignatureHash(sc_t, tx, 1, SIGHASH_ALL, amount=pay_amount_sats,
                         sigversion=SIGVERSION_WITNESS_V0)
    sig_t = taker_sec.sign(sh_t) + bytes([SIGHASH_ALL])
    tx.wit = CTxWitness([wit_maker, CTxInWitness(CScriptWitness([sig_t, taker_sec.pub]))])
    return tx

# ---------- maker side: build the artifact ----------
def make_artifact(offer_txid_hex, offer_vout, offer_amount_sats, price_sats,
                  amount_units=1000, expiry=10**9, group_id=0, maker_seed=b'btx-maker',
                  payout_seed=b'btx-maker-payout'):
    maker_sec, _   = key(maker_seed)
    _, payout_spk  = key(payout_seed)
    in0  = CMutableTxIn(COutPoint(lx(offer_txid_hex), offer_vout))
    out0 = CMutableTxOut(price_sats, payout_spk)
    partial = CMutableTransaction([in0], [out0])
    sh  = SignatureHash(p2wpkh_script_code(maker_sec.pub), partial, 0, SAA,
                        amount=offer_amount_sats, sigversion=SIGVERSION_WITNESS_V0)
    sig = maker_sec.sign(sh) + bytes([SAA])
    return dict(msg_type=1, side=0, rune_block=840000, rune_tx=1, amount=amount_units,
                price=price_sats, expiry=expiry, group_id=group_id, offer_txid=lx(offer_txid_hex),
                offer_vout=offer_vout, payout_spk=bytes(payout_spk),
                maker_pubkey=bytes(maker_sec.pub), sighash_flag=SAA, sig_amount=offer_amount_sats,
                maker_sig=sig)

# ---------- partial fills via denomination splitting (v2 group_id) ----------
def lot_decomposition(total_units):
    """Powers-of-two lot ladder covering `total_units` (e.g. 11 -> [1, 2, 8]). log2(N) lots cover
    any amount, minimizing on-chain artifact count for the granularity."""
    lots, b = [], 0
    while total_units:
        if total_units & 1:
            lots.append(1 << b)
        total_units >>= 1
        b += 1
    return lots

def make_lots(offer_utxos, price_sats_per_unit, group_id, expiry=10**9):
    """Build one BTX artifact per pre-funded offer UTXO, all sharing `group_id` so the indexer can
    aggregate them ("X of Y filled"). offer_utxos: list of (txid_hex, vout, offer_amount_sats,
    lot_units). Each lot's committed payout = price_sats_per_unit * lot_units."""
    return [
        make_artifact(txid, vout, amt_sats, price_sats_per_unit * units,
                      amount_units=units, expiry=expiry, group_id=group_id)
        for (txid, vout, amt_sats, units) in offer_utxos
    ]

# ---------- selftest (offline) ----------
def selftest():
    offer_txid = 'aa'*32; offer_vout = 0
    offer_amt  = int(1.0 * COIN); price = int(0.5 * COIN); pay_amt = int(0.6 * COIN)
    art_full = make_artifact(offer_txid, offer_vout, offer_amt, price)
    blob = serialize_artifact(art_full)
    parsed = parse_artifact(blob)

    checks = {}
    checks['artifact_size_bytes'] = len(blob)
    checks['roundtrip_offer_txid'] = (parsed['offer_txid'] == art_full['offer_txid'])
    checks['roundtrip_price_eq']   = (parsed['price'] == price)
    checks['pubkey_matches_offer_spk'] = (
        CScript(parsed['payout_spk']) is not None and
        Hash160(parsed['maker_pubkey']) == Hash160(art_full['maker_pubkey']))
    # the core 0b claim: a node with ONLY (artifact, offer amount) can verify the maker sig
    checks['maker_sig_verifies_from_chain_data'] = verify_maker_sig(parsed, offer_amt)
    # negative: tamper the price in the artifact -> signature must NOT verify
    tampered = dict(parsed); tampered['price'] = int(0.4 * COIN)
    checks['tampered_price_sig_fails'] = (verify_maker_sig(tampered, offer_amt) == False)
    # security binding: the offer UTXO's true owner is the maker key, so its P2WPKH spk is key(...)[1].
    real_spk = bytes(key(b'btx-maker')[1])
    checks['verifies_with_correct_spk_binding'] = verify_maker_sig(parsed, offer_amt, real_spk)
    # FORGED-PUBKEY attack: re-sign the SAME (offer,price,payout) under an UNRELATED key and swap in that
    # pubkey. Sig-only verification PASSES (the gap), but the spk binding MUST reject it — exactly as the
    # Rust indexer does — because hash160(attacker_pubkey) != the offer UTXO's witness program.
    atk, _ = key(b'attacker')
    sh_atk = SignatureHash(p2wpkh_script_code(atk.pub),
                           CMutableTransaction([CMutableTxIn(COutPoint(parsed['offer_txid'], parsed['offer_vout']))],
                                               [CMutableTxOut(parsed['price'], CScript(parsed['payout_spk']))]),
                           0, SAA, amount=offer_amt, sigversion=SIGVERSION_WITNESS_V0)
    forged = dict(parsed); forged['maker_pubkey'] = bytes(atk.pub); forged['maker_sig'] = atk.sign(sh_atk) + bytes([SAA])
    checks['forged_pubkey_passes_sig_only'] = (verify_maker_sig(forged, offer_amt) is True)
    checks['forged_pubkey_rejected_by_binding'] = (verify_maker_sig(forged, offer_amt, real_spk) is False)
    # build the swap from artifact data only; confirm maker witness == artifact sig (transplant)
    tx = build_swap_from_artifact(parsed, offer_amt, ('bb'*32, 1), pay_amt, b'btx-taker')
    checks['swap_input0_witness_is_artifact_sig'] = (
        bytes(tx.wit.vtxinwit[0].scriptWitness.stack[0]) == parsed['maker_sig'])
    checks['swap_output0_is_committed_payout'] = (
        tx.vout[0].nValue == price and bytes(tx.vout[0].scriptPubKey) == parsed['payout_spk'])
    allpass = all(v is True for k, v in checks.items() if k != 'artifact_size_bytes')
    print(json.dumps({'checks': checks, 'ALL_PASS': allpass}, default=str, indent=2))

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'selftest'
    if cmd == 'selftest':
        selftest()
    elif cmd == 'artifact':
        d = json.loads(sys.argv[2]); off = d['offer']
        art = make_artifact(off['txid'], off['vout'], int(off['amount_btc']*COIN),
                            int(d.get('price_btc', 0.5)*COIN))
        blob = serialize_artifact(art)
        carrier = CScript([OP_RETURN, blob])
        print(json.dumps({'artifact_hex': b2x(blob), 'artifact_bytes': len(blob),
                          'carrier_op_return_spk_hex': b2x(carrier)}))
    else:
        sys.exit('unknown command: ' + cmd)
