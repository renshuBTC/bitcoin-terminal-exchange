#!/usr/bin/env python3
"""Offline test for rune<->rune addressed swaps (roadmap #4). Pure, no node.

Locks in: the swap tx layout, the Runes allocator (counter-rune -> maker out0, offered rune ->
taker out1, rune-B change -> taker), the maker-side verifier accepting a correct tx, and — the
load-bearing safety check — the verifier REJECTING a tampered runestone that routes the counter-rune
away from the maker. Run in WSL: python3 btx_rune_swap_test.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bitcoin
bitcoin.SelectParams("regtest")
from bitcoin.core import b2x, CMutableTxOut
from bitcoin.core.script import CScript

import btx_rune_swap as S
import btx_runes as runes
import btx_runes_decode as rd

OK = True
def check(name, cond, detail=""):
    global OK; OK = OK and bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))

# maker sells rune A (840000:7, 5000 units) for taker's rune B (840100:3, 1200 units)
RUNE_A, AMT_A = "840000:7", 5000
RUNE_B, AMT_B = "840100:3", 1200
maker_spk = bytes.fromhex("0014" + "aa" * 20)
taker_spk = bytes.fromhex("0014" + "bb" * 20)
change_spk = bytes.fromhex("0014" + "cc" * 20)
offer_txid, fund_txid = "aa" * 32, "bb" * 32
offer_sats, fund_sats = S.DUST, int(0.01 * 1e8)   # offer holds rune A + dust; funding holds rune B + sats

tx, meta = S.build_addressed_rune_swap_unsigned(
    offer_txid, 0, offer_sats, fund_txid, 1, fund_sats,
    maker_spk, taker_spk, change_spk, RUNE_A, AMT_A, RUNE_B, AMT_B, fee=2000)

# --- structure ---
check("2 inputs (offer + funding)", len(tx.vin) == 2)
check("offer is input 0", b2x(tx.vin[0].prevout.hash) and tx.vin[0].prevout.n == 0)
check("output 0 is the maker receive spk (dust)",
      bytes(tx.vout[0].scriptPubKey) == maker_spk and tx.vout[0].nValue == S.DUST)
check("output 1 is the taker receive spk (dust)",
      bytes(tx.vout[1].scriptPubKey) == taker_spk and tx.vout[1].nValue == S.DUST)
rs_i = meta["runestone_index"]
check("last output is the runestone OP_RETURN (0 value)",
      tx.vout[rs_i].nValue == 0 and bytes(tx.vout[rs_i].scriptPubKey)[0] == 0x6a)
# edicts must be sorted by rune id (delta encoding needs ascending ids)
ids = [(e[0], e[1]) for e in meta["edicts"]]
check("edicts sorted by rune id", ids == sorted(ids), str(ids))

# --- decode the runestone we built and run the allocator (A offered fully, B funded with extra) ---
spk_hex = bytes(tx.vout[rs_i].scriptPubKey).hex()
dec = rd.decode_runestone(spk_hex)
check("built runestone decodes, not a cenotaph", dec.get("is_runestone") and not dec.get("cenotaph"),
      str(dec.get("cenotaph_reasons")))
B_FUNDED = AMT_B + 800     # taker funds MORE rune B than the price -> change must go to taker, not maker
input_runes = {RUNE_A: AMT_A, RUNE_B: B_FUNDED}
op_idx = {rs_i}
alloc = S.allocate_runes(dec["edicts"], input_runes, len(tx.vout), op_idx, dec.get("pointer"))
check("maker out0 receives exactly amount_b of rune B",
      alloc.get(0, {}).get(RUNE_B, 0) == AMT_B, str(alloc.get(0)))
check("maker out0 receives NO rune A", alloc.get(0, {}).get(RUNE_A, 0) == 0)
check("taker out1 receives all of rune A", alloc.get(1, {}).get(RUNE_A, 0) == AMT_A, str(alloc.get(1)))
check("taker out1 receives the rune B change (funded - price)",
      alloc.get(1, {}).get(RUNE_B, 0) == (B_FUNDED - AMT_B))

# --- build a decoded-tx dict (decodepsbt-shaped) and run the maker verifier ---
def decoded(tx):
    return {"vin": [{"txid": offer_txid, "vout": 0}, {"txid": fund_txid, "vout": 1}],
            "vout": [{"value": o.nValue / 1e8, "scriptPubKey": {"hex": bytes(o.scriptPubKey).hex()}}
                     for o in tx.vout]}

ok, reason = S.verify_addressed_rune_tx(decoded(tx), offer_txid, 0, maker_spk.hex(),
                                        RUNE_B, AMT_B, input_runes)
check("verifier ACCEPTS the correct swap", ok, reason)

# --- safety: a tampered runestone that routes rune B to the TAKER (out1) must be REJECTED ---
bad_edicts = [(840000, 7, AMT_A, 1), (840100, 3, AMT_B, 1)]   # B -> out1 (taker), maker gets nothing
bad_edicts.sort(key=lambda e: (e[0], e[1]))
tx_bad = tx
tx_bad.vout[rs_i] = CMutableTxOut(0, runes.runestone_spk(bad_edicts))
ok_bad, reason_bad = S.verify_addressed_rune_tx(decoded(tx_bad), offer_txid, 0, maker_spk.hex(),
                                                RUNE_B, AMT_B, input_runes)
check("verifier REJECTS a runestone that steals rune B from the maker", not ok_bad, reason_bad)

# --- safety: wrong output-0 scriptPubKey (taker substitutes their own addr) must be REJECTED ---
ok_spk, _ = S.verify_addressed_rune_tx(decoded(tx), offer_txid, 0, ("0014" + "ff" * 20),
                                       RUNE_B, AMT_B, input_runes)
check("verifier REJECTS a wrong maker receive spk", not ok_spk)

# --- under-funded rune B (taker funds less than the price) must be REJECTED ---
ok_under, _ = S.verify_addressed_rune_tx(decoded(tx), offer_txid, 0, maker_spk.hex(),
                                         RUNE_B, AMT_B, {RUNE_A: AMT_A, RUNE_B: AMT_B - 1})
check("verifier REJECTS when the funding holds < amount_b of rune B", not ok_under)

# --- safety (audit fix): an edict whose output index EXCEEDS the output count is a CENOTAPH in ord
# (edict.rs: output > tx.output.len() -> burns ALL input runes). A taker could append such an edict
# after a valid B->out0 edict to grief the maker's offered rune. The verifier must REJECT it even
# though output 0 superficially "receives" rune B. ---
txo, mo = S.build_addressed_rune_swap_unsigned(
    offer_txid, 0, offer_sats, fund_txid, 1, fund_sats,
    maker_spk, taker_spk, change_spk, RUNE_A, AMT_A, RUNE_B, AMT_B, fee=2000)
n_out_txo = len(txo.vout)
evil = sorted([(840000, 7, AMT_A, 1), (840100, 3, AMT_B, 0), (840100, 3, 0, n_out_txo + 5)],
              key=lambda e: (e[0], e[1]))
txo.vout[mo["runestone_index"]] = CMutableTxOut(0, runes.runestone_spk(evil))
def decoded_o(t):
    return {"vin": [{"txid": offer_txid, "vout": 0}, {"txid": fund_txid, "vout": 1}],
            "vout": [{"value": o.nValue / 1e8, "scriptPubKey": {"hex": bytes(o.scriptPubKey).hex()}}
                     for o in t.vout]}
ok_oob, reason_oob = S.verify_addressed_rune_tx(decoded_o(txo), offer_txid, 0, maker_spk.hex(),
                                                RUNE_B, AMT_B, input_runes)
check("verifier REJECTS an out-of-bounds-output edict (ord cenotaph burns all)", not ok_oob, reason_oob)

# --- safety: an edict whose rune id overflows u64 block / u32 tx is a CENOTAPH in ord (Flaw::EdictRuneId
# -> burns all input runes). The decoder must flag it so verify rejects, else a crafted overflow edict
# slips past (its garbage id won't match rune B, so the allocator would still credit out0) and griefs. ---
txc, mc = S.build_addressed_rune_swap_unsigned(
    offer_txid, 0, offer_sats, fund_txid, 1, fund_sats,
    maker_spk, taker_spk, change_spk, RUNE_A, AMT_A, RUNE_B, AMT_B, fee=2000)
ovf = sorted([(840000, 7, AMT_A, 1), (840100, 3, AMT_B, 0), (840100, 2 ** 33, 0, 1)],
             key=lambda e: (e[0], e[1]))  # tx 2**33 exceeds u32 -> EdictRuneId cenotaph
txc.vout[mc["runestone_index"]] = CMutableTxOut(0, runes.runestone_spk(ovf))
ok_ovf, reason_ovf = S.verify_addressed_rune_tx(decoded_o(txc), offer_txid, 0, maker_spk.hex(),
                                                RUNE_B, AMT_B, input_runes)
check("verifier REJECTS an edict with overflowing rune id (ord cenotaph)", not ok_ovf, reason_ovf)
# sanity: the decoder flags it as a cenotaph
import btx_runes_decode as _rd
_dec = _rd.decode_runestone(bytes(txc.vout[mc["runestone_index"]].scriptPubKey).hex())
check("decoder flags rune-id overflow as cenotaph", _dec.get("cenotaph") is True, str(_dec.get("cenotaph_reasons")))
# a stray Tag::Flags bit (e.g. FLAG_TERMS without FLAG_ETCHING) is UnrecognizedFlag -> cenotaph in ord
_dflag = _rd.decode_runestone(_rd._encode_runestone_spk(
    [_rd.TAG_FLAGS, _rd.FLAG_TERMS, _rd.TAG_BODY, 1, 1, 2, 0]).hex())
check("decoder flags stray flag bit (terms w/o etching) as cenotaph",
      _dflag.get("cenotaph") is True, str(_dflag.get("cenotaph_reasons")))

# --- CRITICAL (F-POINTER): the leftover counter-rune must follow ord's POINTER rule, never naively land
# on output 0. Two snipes a taker could craft so output 0 APPEARS to receive rune B while the network
# BURNS it: (1) pointer -> an OP_RETURN output (ord allocates leftover there, then burns runes on an
# OP_RETURN); (2) pointer >= n_outputs (ord cenotaph, burns ALL input runes). Rune B is left UNALLOCATED
# (no B edict), so only the leftover rule decides where it goes — both proposals must be REJECTED. ---
txp, mp = S.build_addressed_rune_swap_unsigned(
    offer_txid, 0, offer_sats, fund_txid, 1, fund_sats,
    maker_spk, taker_spk, change_spk, RUNE_A, AMT_A, RUNE_B, AMT_B, fee=2000)
rs_ip, n_p = mp["runestone_index"], len(txp.vout)
a_blk, a_tx = 840000, 7   # RUNE_A = "840000:7"; edict A -> out1 (all), B left unallocated
# (1) pointer -> the runestone's own OP_RETURN output (index rs_ip)
txp.vout[rs_ip] = CMutableTxOut(0, CScript(rd._encode_runestone_spk(
    [rd.TAG_POINTER, rs_ip, rd.TAG_BODY, a_blk, a_tx, 0, 1])))
ok_p1, r_p1 = S.verify_addressed_rune_tx(decoded_o(txp), offer_txid, 0, maker_spk.hex(),
                                         RUNE_B, AMT_B, input_runes)
check("verifier REJECTS pointer->OP_RETURN leftover snipe (ord burns rune B)", not ok_p1, r_p1)
# (2) pointer >= n_outputs -> ord cenotaph (burns ALL input runes)
txp.vout[rs_ip] = CMutableTxOut(0, CScript(rd._encode_runestone_spk(
    [rd.TAG_POINTER, n_p + 5, rd.TAG_BODY, a_blk, a_tx, 0, 1])))
ok_p2, r_p2 = S.verify_addressed_rune_tx(decoded_o(txp), offer_txid, 0, maker_spk.hex(),
                                         RUNE_B, AMT_B, input_runes)
check("verifier REJECTS pointer >= n_outputs (ord cenotaph burns all)", not ok_p2, r_p2)
# sanity: the honest no-pointer case still defaults leftover to the first non-OP_RETURN output (out0)
alloc_def = S.allocate_runes([{"id": RUNE_A, "amount": 0, "output": 1}], {RUNE_A: AMT_A, RUNE_B: AMT_B},
                             3, {2}, None)
check("no-pointer leftover defaults to first non-OP_RETURN output (out0)",
      alloc_def.get(0, {}).get(RUNE_B, 0) == AMT_B)

# --- allocator: an edict to output == n_outputs ("all outputs") with amount>0 gives EACH non-OP_RETURN
# output `amount` (ord semantics), not a split of amount. ---
alloc_all = S.allocate_runes([{"id": "9:9", "amount": 100, "output": 3}], {"9:9": 200}, 3, {2}, None)
check("all-outputs edict (output==n, amount>0) gives each output `amount`",
      alloc_all.get(0, {}).get("9:9") == 100 and alloc_all.get(1, {}).get("9:9") == 100)

print("ALL_PASS" if OK else "FAILURES ABOVE")
sys.exit(0 if OK else 1)
