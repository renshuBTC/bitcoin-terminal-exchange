"""
BTX Phase 0 / Milestone 0a empirical check (SIGHASH_SINGLE|ANYONECANPAY swap).

Models the swap signature mechanics with BTC-only UTXOs:
  - input0  = maker's "offer" UTXO (in production this carries the asset/rune)
  - output0 = maker's payout (the price the maker wants), committed by the maker's signature
Maker pre-signs input0 with SINGLE|ANYONECANPAY over a tx that has ONLY input0 + output0.
Taker later appends input1 (their payment) and output1 (their proceeds) and signs input1.
If the maker's transplanted witness still validates, the pre-signature survived the taker's
additions with no relay-time re-signing -> the core BTX settlement primitive works.

Reads UTXOs from argv[1] as JSON; prints the positive + negative final raw txs as hex.
"""
import sys, json, hashlib
import bitcoin
bitcoin.SelectParams('regtest')
from bitcoin.core import (COIN, CMutableTransaction, CMutableTxIn, CMutableTxOut,
                          COutPoint, CTxInWitness, CTxWitness, lx, b2x, Hash160)
from bitcoin.core.script import (CScript, CScriptWitness, SignatureHash, SIGHASH_SINGLE,
                                 SIGHASH_ALL, SIGHASH_ANYONECANPAY, SIGVERSION_WITNESS_V0,
                                 OP_0, OP_DUP, OP_HASH160, OP_EQUALVERIFY, OP_CHECKSIG)
from bitcoin.wallet import CBitcoinSecret, P2WPKHBitcoinAddress


def key(seed):
    s = CBitcoinSecret.from_secret_bytes(hashlib.sha256(seed).digest())
    spk = CScript([OP_0, Hash160(s.pub)])      # P2WPKH scriptPubKey
    return s, spk


def script_code(sec):
    # BIP143 segwit-v0 sighash uses the implied P2PKH script for the pubkey
    return CScript([OP_DUP, OP_HASH160, Hash160(sec.pub), OP_EQUALVERIFY, OP_CHECKSIG])


data = json.loads(sys.argv[1])
maker_sec,  maker_spk  = key(b'btx-maker')
taker_sec,  taker_spk  = key(b'btx-taker')
payout_sec, payout_spk = key(b'btx-maker-payout')

offer = data['offer']     # input0, owned by maker (the "asset")
pay   = data['pay']       # input1, owned by taker (the payment)
PRICE_BTC = 0.5           # maker wants 0.5 BTC at output0
FEE_BTC   = 0.0001

offer_sats = int(round(offer['amount_btc'] * COIN))
pay_sats   = int(round(pay['amount_btc']   * COIN))
price_sats = int(round(PRICE_BTC * COIN))
fee_sats   = int(round(FEE_BTC   * COIN))

SAA = SIGHASH_SINGLE | SIGHASH_ANYONECANPAY   # 0x83

# --- maker pre-signs over a partial tx that has ONLY input0 + output0 ---
in0  = CMutableTxIn(COutPoint(lx(offer['txid']), offer['vout']))
out0 = CMutableTxOut(price_sats, payout_spk)
partial = CMutableTransaction([in0], [out0])
sh_maker  = SignatureHash(script_code(maker_sec), partial, 0, SAA,
                          amount=offer_sats, sigversion=SIGVERSION_WITNESS_V0)
sig_maker = maker_sec.sign(sh_maker) + bytes([SAA])
wit_maker = CTxInWitness(CScriptWitness([sig_maker, maker_sec.pub]))


def build_final(price_to_maker_sats):
    """Taker assembles the full tx; the maker's pre-signed witness is transplanted unchanged."""
    i0 = CMutableTxIn(COutPoint(lx(offer['txid']), offer['vout']))
    i1 = CMutableTxIn(COutPoint(lx(pay['txid']),   pay['vout']))
    o0 = CMutableTxOut(price_to_maker_sats, payout_spk)                       # maker payout (index 0)
    taker_proceeds = offer_sats + pay_sats - price_to_maker_sats - fee_sats   # taker sweeps the rest
    o1 = CMutableTxOut(taker_proceeds, taker_spk)
    tx = CMutableTransaction([i0, i1], [o0, o1])
    sh_t  = SignatureHash(script_code(taker_sec), tx, 1, SIGHASH_ALL,
                          amount=pay_sats, sigversion=SIGVERSION_WITNESS_V0)
    sig_t = taker_sec.sign(sh_t) + bytes([SIGHASH_ALL])
    wit_taker = CTxInWitness(CScriptWitness([sig_t, taker_sec.pub]))
    tx.wit = CTxWitness([wit_maker, wit_taker])   # input0 reuses maker's PRE-signed witness, untouched
    return tx


tx_ok  = build_final(price_sats)                   # honest: output0 == committed price -> valid
tx_bad = build_final(int(round(0.4 * COIN)))       # attack: shave payout to 0.4 -> maker sig must fail

out = {}
out["maker_payout_addr"] = str(P2WPKHBitcoinAddress.from_scriptPubKey(payout_spk))
out["maker_offer_addr"]  = str(P2WPKHBitcoinAddress.from_scriptPubKey(maker_spk))
out["taker_addr"]        = str(P2WPKHBitcoinAddress.from_scriptPubKey(taker_spk))
out["tx_ok_hex"]         = b2x(tx_ok.serialize())
out["tx_bad_hex"]        = b2x(tx_bad.serialize())
out["price_sats"]        = price_sats
print(json.dumps(out))
