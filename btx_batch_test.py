#!/usr/bin/env python3
"""Offline test for batch fills (roadmap #2): sweep N open asks in ONE taker tx. Pure, no node.

The load-bearing claim this locks in: a maker's SIGHASH_SINGLE|ANYONECANPAY (0x83) pre-signature —
made over a partial tx of [offer@input0, payout@output0] — stays valid when the offer is placed at
input index k>0 in a batch, PROVIDED its payout sits at output index k. We don't just assert tx
shape; we recompute the real BIP143 sighash at each offer's actual index in the assembled batch and
verify the maker's untouched pre-sig against it. That is the property batching depends on.

Run in WSL: python3 btx_batch_test.py
"""
import sys, os, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bitcoin
bitcoin.SelectParams("regtest")
from bitcoin.core import (COIN, CTransaction, CMutableTransaction, b2x, x, Hash160,
                          COutPoint, CTxWitness, CTxInWitness)
from bitcoin.core.script import (CScript, CScriptWitness, SignatureHash, SIGHASH_ALL,
                                 SIGVERSION_WITNESS_V0, OP_DUP, OP_HASH160, OP_EQUALVERIFY,
                                 OP_CHECKSIG, OP_0)
from bitcoin.core.key import CPubKey
from bitcoin.wallet import CBitcoinSecret

import btx_wallet as W
import btx_0b as btx
import btx_runes as runes

OK = True
def check(name, cond, detail=""):
    global OK; OK = OK and bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))

def key(seed):
    s = CBitcoinSecret.from_secret_bytes(hashlib.sha256(seed).digest())
    return s, CScript([OP_0, Hash160(s.pub)])
def sc(pub):
    return CScript([OP_DUP, OP_HASH160, Hash160(pub), OP_EQUALVERIFY, OP_CHECKSIG])

# ---- three makers, each pre-signs its own offer with SINGLE|ANYONECANPAY (offer@0, payout@0) ----
# offer[2] carries a rune (block 840000, tx 7) -> must be edicted to the taker, not default-routed.
specs = [
    # (seed, offer_txid, price_sats, offer_amount_sats, rune_block, rune_tx, rune_units)
    (b"m0", "a0" * 32, int(0.10 * COIN), int(0.30 * COIN), 0, 0, 0),
    (b"m1", "a1" * 32, int(0.25 * COIN), int(0.40 * COIN), 0, 0, 0),
    (b"m2", "a2" * 32, int(0.05 * COIN), int(0.20 * COIN), 840000, 7, 5000),
]

arts, offer_amts, makers = [], [], []
for seed, otxid, price, oamt, rb, rt, runits in specs:
    maker, _ = key(seed)
    _, payout_spk = key(seed + b"-payout")
    partial = W.build_partial_tx(otxid, 0, price, payout_spk)
    sh = SignatureHash(sc(maker.pub), partial, 0, W.SAA, amount=oamt, sigversion=SIGVERSION_WITNESS_V0)
    sig = maker.sign(sh) + bytes([W.SAA])
    partial.wit = CTxWitness([CTxInWitness(CScriptWitness([sig, maker.pub]))])
    msig, mpub = W.extract_maker_witness_from_signed_tx(b2x(partial.serialize()))
    art = W.assemble_artifact(otxid, 0, price, payout_spk, mpub, msig, group_id=0,
                              amount_units=runits, rune_block=rb, rune_tx=rt)
    parsed = btx.parse_artifact(btx.serialize_artifact(art))
    arts.append(parsed); offer_amts.append(oamt); makers.append((maker, payout_spk, price))

N = len(arts)

# ---- build the batch swap: [offer_0..offer_{N-1}, funding] -> [payout_0..N-1, taker, runestone] ----
taker, taker_spk = key(b"taker")
fund_txid, fund_vout, fund_amt = "ff" * 32, 3, int(1.0 * COIN)
per_offer_fee = 10000
fee = per_offer_fee * N
unsigned = W.build_batch_taker_swap_unsigned(arts, offer_amts, fund_txid, fund_vout, fund_amt,
                                             taker_spk, fee=fee)

# structural checks
check("N offer inputs + 1 funding input", len(unsigned.vin) == N + 1, str(len(unsigned.vin)))
check("offer inputs are first, in order",
      all(unsigned.vin[k].prevout == COutPoint(arts[k]["offer_txid"], arts[k]["offer_vout"])
          for k in range(N)))
check("funding input is last",
      unsigned.vin[N].prevout == COutPoint(W.lx(fund_txid), fund_vout))
check("payout_k at output index k (value + spk)",
      all(unsigned.vout[k].nValue == arts[k]["price"]
          and bytes(unsigned.vout[k].scriptPubKey) == arts[k]["payout_spk"] for k in range(N)))
total_price = sum(a["price"] for a in arts)
expect_taker = sum(offer_amts) + fund_amt - total_price - fee
check("taker output at index N with correct value",
      unsigned.vout[N].nValue == expect_taker, f"{unsigned.vout[N].nValue} vs {expect_taker}")
# exactly one rune offer here -> exactly one runestone output at index N+1
check("runestone appended at index N+1 (one rune offer present)", len(unsigned.vout) == N + 2)

# ---- THE load-bearing check: every maker's untouched 0x83 pre-sig verifies at its real index k ----
for k in range(N):
    sh_k = SignatureHash(btx.p2wpkh_script_code(arts[k]["maker_pubkey"]), unsigned, k, W.SAA,
                         amount=offer_amts[k], sigversion=SIGVERSION_WITNESS_V0)
    der = arts[k]["maker_sig"][:-1]
    valid = CPubKey(arts[k]["maker_pubkey"]).verify(sh_k, der)
    check(f"maker[{k}] SINGLE|ACP pre-sig verifies at input index {k}", valid)

# control: a maker sig must FAIL if its payout is moved off its own index (proves the binding is real)
swapped = CMutableTransaction.from_tx(unsigned)
swapped.vout[0], swapped.vout[1] = swapped.vout[1], swapped.vout[0]  # move payout_0 away from index 0
sh_bad = SignatureHash(btx.p2wpkh_script_code(arts[0]["maker_pubkey"]), swapped, 0, W.SAA,
                       amount=offer_amts[0], sigversion=SIGVERSION_WITNESS_V0)
check("maker[0] sig FAILS when payout_0 is moved off index 0 (SINGLE binding is real)",
      not CPubKey(arts[0]["maker_pubkey"]).verify(sh_bad, arts[0]["maker_sig"][:-1]))

# ---- rune routing: the lone rune offer (k=2) must be edicted to the taker output (idx N), not maker 0 ----
runestone_spk = bytes(unsigned.vout[N + 1].scriptPubKey)
expect_edict_spk = bytes(runes.runestone_spk([(840000, 7, 5000, N)]))
check("runestone edicts the rune to the taker output (idx N)", runestone_spk == expect_edict_spk)

# ---- taker funds with SIGHASH_ALL over the whole tx, then transplant all maker witnesses ----
sh_t = SignatureHash(sc(taker.pub), unsigned, N, SIGHASH_ALL, amount=fund_amt,
                     sigversion=SIGVERSION_WITNESS_V0)
sig_t = taker.sign(sh_t) + bytes([SIGHASH_ALL])
wit = [CTxInWitness(CScriptWitness([])) for _ in range(N)] + [CTxInWitness(CScriptWitness([sig_t, taker.pub]))]
unsigned.wit = CTxWitness(wit)
wallet_signed_hex = b2x(unsigned.serialize())
final_hex = W.transplant_maker_witnesses(wallet_signed_hex, arts)
final = CTransaction.deserialize(x(final_hex))
check("transplant put each maker sig on its offer input",
      all(bytes(final.wit.vtxinwit[k].scriptWitness.stack[0]) == arts[k]["maker_sig"] for k in range(N)))
check("transplant preserved the taker's funding witness",
      bytes(final.wit.vtxinwit[N].scriptWitness.stack[0]) == sig_t)
# the taker's SIGHASH_ALL sig commits to the WHOLE tx -> recompute and verify it still holds
sh_t2 = SignatureHash(sc(taker.pub), final, N, SIGHASH_ALL, amount=fund_amt, sigversion=SIGVERSION_WITNESS_V0)
check("taker SIGHASH_ALL funding sig verifies over the final tx",
      CPubKey(bytes(taker.pub)).verify(sh_t2, sig_t[:-1]))

# ---- dust guard: taker_value = sum(offers) + fund - sum(prices) - fee must clear 546 ----
# drive it sub-dust with a lone offer, zero offer sats, and funding just over price+fee.
try:
    W.build_batch_taker_swap_unsigned([arts[0]], [0], fund_txid, fund_vout,
                                      arts[0]["price"] + per_offer_fee + 100, taker_spk, fee=per_offer_fee)
    check("undersized funding raises (dust guard)", False, "expected ValueError")
except ValueError:
    check("undersized funding raises (dust guard)", True)

# ---- single offer is just a degenerate batch (no runestone for a BTC-only lone offer) ----
solo = W.build_batch_taker_swap_unsigned([arts[0]], [offer_amts[0]], fund_txid, fund_vout,
                                         int(0.5 * COIN), taker_spk, fee=per_offer_fee)
check("solo BTC batch = 2 inputs / 2 outputs (no runestone)",
      len(solo.vin) == 2 and len(solo.vout) == 2)

print("ALL_PASS" if OK else "FAILURES ABOVE")
sys.exit(0 if OK else 1)
