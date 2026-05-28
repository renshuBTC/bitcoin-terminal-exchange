#!/usr/bin/env python3
"""btx_rune_swap.py — rune<->rune addressed swaps (roadmap #4). Pure: no node, no network.

WHY ADDRESSED-ONLY (the load-bearing design finding).
A trustless OPEN (pre-signed, non-interactive) rune<->rune swap is IMPOSSIBLE under BTX's
SIGHASH_SINGLE|ANYONECANPAY (0x83) offer model. SINGLE pins the maker's offer input to exactly ONE
output (output 0). A rune<->rune deal needs the maker to commit to TWO things at once:
  (a) the OP_RETURN runestone that ROUTES the counter-rune to the maker, and
  (b) the scriptPubKey of the OUTPUT that actually receives it.
Those are two distinct outputs; SINGLE can pin only one. So a malicious taker could publish a
runestone that keeps the counter-rune for themselves while still spending the maker's offer (which
IS edicted to the taker) — the maker gets nothing. The only trustless construction is SIGHASH_ALL:
the maker signs the WHOLE finished transaction, so the maker can verify the runestone routing AND
their receiving output together before countersigning. That is exactly the existing addressed
(interactive, two-message PSBT) flow; this module builds and verifies its rune<->rune variant.

Layout of the rune<->rune swap (maker sells rune A for the taker's rune B):
  in0  = maker offer UTXO   (holds A, exactly amount_a)         <- maker SIGHASH_ALL-signs the whole tx
  in1  = taker funding UTXO (holds B >= amount_b, plus sats for dust+fee)
  out0 = maker receive  (dust, maker_recv_spk)   <- receives amount_b of rune B
  out1 = taker receive  (dust, taker_recv_spk)   <- receives all of rune A + any rune B change
  out2 = taker BTC change (taker_change_spk)      (omitted if it would be dust)
  outN = runestone OP_RETURN with edicts:  A:amount_a -> out1 ,  B:amount_b -> out0 ,  B:rest -> out1
Edicts are sorted by rune id (delta encoding requires ascending ids). The B "rest -> out1" edict
(amount 0 = all remaining) keeps the taker's rune-B change off output 0, while UNALLOCATED runes
still default to the first non-OP_RETURN output (= out0, the maker) — which only ever benefits the
maker, never the taker, so it is safe for the party who pre-commits.
"""
from collections import defaultdict

from bitcoin.core import (COIN, lx, b2x, COutPoint, CMutableTxIn, CMutableTxOut,
                          CMutableTransaction)
from bitcoin.core.script import CScript

import btx_runes as runes
import btx_runes_decode as rd

DUST = 546                    # conservative dust floor: == P2PKH 546, >= P2TR 330 / P2WPKH 294, so a
                              # rune-bearing output of ANY script type clears Bitcoin Core's relay dust
                              # threshold (intentionally over-provisioned for P2TR receivers by ~216 sat)
DEFAULT_FEE = 10000


def _rid(rune_id):
    """('840000:7' | (840000,7)) -> (block, tx) ints."""
    if isinstance(rune_id, (tuple, list)):
        return int(rune_id[0]), int(rune_id[1])
    b, t = str(rune_id).split(":")
    return int(b), int(t)


def build_addressed_rune_swap_unsigned(offer_txid, offer_vout, offer_sats,
                                       fund_txid, fund_vout, fund_sats,
                                       maker_recv_spk, taker_recv_spk, taker_change_spk,
                                       rune_a, amount_a, rune_b, amount_b, fee=DEFAULT_FEE):
    """Build the unsigned rune<->rune swap tx (see module docstring for the layout). Returns
    (CMutableTransaction, meta) where meta records the runestone output index + edicts for tests."""
    a_blk, a_tx = _rid(rune_a)
    b_blk, b_tx = _rid(rune_b)
    if amount_a <= 0 or amount_b <= 0:
        raise ValueError("both rune amounts must be positive")
    if amount_a > (1 << 64) - 1 or amount_b > (1 << 64) - 1:
        raise ValueError("rune amount exceeds u64::MAX (BTX artifacts store amount as u64)")
    i0 = CMutableTxIn(COutPoint(lx(offer_txid), offer_vout))
    i1 = CMutableTxIn(COutPoint(lx(fund_txid), fund_vout))
    o0 = CMutableTxOut(DUST, CScript(bytes(maker_recv_spk)))    # maker receives rune B
    o1 = CMutableTxOut(DUST, CScript(bytes(taker_recv_spk)))    # taker receives rune A (+ B change)
    outs = [o0, o1]
    change = offer_sats + fund_sats - 2 * DUST - fee
    if change >= DUST:
        outs.append(CMutableTxOut(change, CScript(bytes(taker_change_spk))))   # out2 (BTC change)
    elif change < 0:
        raise ValueError(f"inputs too small: offer {offer_sats} + fund {fund_sats} cannot cover "
                         f"2 dust ({2*DUST}) + fee {fee}")
    # edicts: A->out1 (all), B amount_b->out0 (maker), B rest->out1 (taker). Sorted by rune id.
    edicts = [(a_blk, a_tx, amount_a, 1), (b_blk, b_tx, amount_b, 0), (b_blk, b_tx, 0, 1)]
    edicts.sort(key=lambda e: (e[0], e[1]))     # stable: keeps the two B edicts in (b,0)->0 then ->1 order
    rs_index = len(outs)
    outs.append(CMutableTxOut(0, runes.runestone_spk(edicts)))                  # runestone OP_RETURN
    tx = CMutableTransaction([i0, i1], outs)
    meta = {"runestone_index": rs_index, "edicts": edicts, "maker_out": 0, "taker_out": 1,
            "rune_a": f"{a_blk}:{a_tx}", "rune_b": f"{b_blk}:{b_tx}"}
    return tx, meta


def allocate_runes(edicts, input_runes, n_outputs, op_return_indices, pointer=None):
    """Minimal Runes allocator matching ord's edict semantics, sufficient to VERIFY a tx we built.
      edicts: list of {"id","block","tx","amount","output"} (as decoded by btx_runes_decode)
      input_runes: {"block:tx": total_amount_in_inputs}
      Returns {output_index: {rune_id: amount}}.
    Rules applied: an edict amount of 0 means "all remaining of that rune"; an edict whose output ==
    n_outputs splits evenly across the non-OP_RETURN outputs; after edicts, any unallocated rune goes
    to `pointer` (if set) else the first non-OP_RETURN output."""
    bal = {k: int(v) for k, v in input_runes.items()}
    out = defaultdict(lambda: defaultdict(int))
    nonop = [i for i in range(n_outputs) if i not in op_return_indices]
    for e in edicts:
        rid, amount, output = e["id"], int(e["amount"]), int(e["output"])
        avail = bal.get(rid, 0)
        if avail <= 0:
            continue
        if output == n_outputs:                       # "all outputs" (== output count): valid in ord
            if not nonop:
                continue
            if amount == 0:                           # divide the remaining balance evenly
                per, extra = divmod(avail, len(nonop))
                for k, ti in enumerate(nonop):
                    out[ti][rid] += per + (1 if k < extra else 0)
                bal[rid] = 0
            else:                                     # ord: EACH output gets `amount` (not a split),
                rem = avail                           # in sequence, capped by the remaining balance
                for ti in nonop:
                    g = min(amount, rem)
                    out[ti][rid] += g
                    rem -= g
                    if rem == 0:
                        break
                bal[rid] = rem
        elif output in op_return_indices:
            bal[rid] = avail - (avail if amount == 0 else min(amount, avail))  # edict to OP_RETURN burns
        else:
            give = avail if amount == 0 else min(amount, avail)
            out[output][rid] += give                  # output < n_outputs (output > n is rejected upstream)
            bal[rid] = avail - give
    # Leftover (unallocated) runes go to the pointer output if set, else the FIRST non-OP_RETURN output
    # (ord). CRITICAL — match ord EXACTLY, do NOT fall back to nonop[0]: ord allocates leftover to the
    # pointer's output even when that output is an OP_RETURN (then burns runes sitting on any OP_RETURN
    # output), and a pointer >= n_outputs is a cenotaph that burns everything. The old `pointer in nonop
    # else nonop[0]` redirected a pointer→OP_RETURN (or out-of-range) leftover onto the first
    # non-OP_RETURN output (often the maker's output 0), so a taker could leave the counter-rune
    # unallocated with a pointer→OP_RETURN and the verifier would see output 0 "receiving" a rune the
    # network burns (snipe). So: only credit leftover to a dst that is IN RANGE and NOT an OP_RETURN;
    # any other pointer (OP_RETURN / out-of-range) burns the leftover, exactly like ord.
    if pointer is not None:
        dst = pointer if pointer < n_outputs else None
    else:
        dst = nonop[0] if nonop else None
    if dst is not None and dst not in op_return_indices:
        for rid, rem in bal.items():
            if rem > 0:
                out[dst][rid] += rem
    return out


def _decoded_outputs(decoded_tx):
    """Pull (scriptPubKey hex, n_outputs, op_return_indices, runestone_decode) from a decodepsbt/
    decoderawtransaction-style dict (vout[i].scriptPubKey.hex)."""
    vout = decoded_tx.get("vout", []) if isinstance(decoded_tx, dict) else []
    spks = [(o.get("scriptPubKey") or {}).get("hex", "") for o in vout]
    op_idx = {i for i, s in enumerate(spks) if s.startswith("6a")}
    rs, rs_i = None, None
    for i in sorted(op_idx):
        d = rd.decode_runestone(spks[i])
        if d.get("is_runestone"):
            rs, rs_i = d, i
            break
    return spks, len(vout), op_idx, rs, rs_i


def verify_addressed_rune_tx(decoded_tx, offer_txid, offer_vout,
                             maker_recv_spk_hex, rune_b_id, amount_b, input_runes):
    """Maker-side check before countersigning a rune<->rune swap (pure; no node). Confirms:
      - input 0 is the agreed offer outpoint;
      - the tx carries a (non-cenotaph) runestone;
      - after allocation, OUTPUT 0 receives >= amount_b of rune B AND its scriptPubKey is the maker's
        receiving spk.
    `input_runes` ({"block:tx": amount}) is what the maker believes the inputs hold for each rune —
    in production the offer balance (amount_a) is known and the funding's rune-B balance must be
    confirmed via the maker's own ord oracle. Returns (ok, reason)."""
    vin = decoded_tx.get("vin", []) if isinstance(decoded_tx, dict) else []
    if not vin or vin[0].get("txid") != offer_txid or int(vin[0].get("vout", -1)) != int(offer_vout):
        got = f"{vin[0].get('txid')}:{vin[0].get('vout')}" if vin else "<none>"
        return False, f"input 0 is {got}, not the agreed offer {offer_txid}:{offer_vout}"
    spks, n_out, op_idx, rs, rs_i = _decoded_outputs(decoded_tx)
    if rs is None:
        return False, "no runestone output found"
    if rs.get("cenotaph"):
        return False, f"runestone is a cenotaph: {rs.get('cenotaph_reasons')}"
    # ord treats an edict whose output index EXCEEDS the output count as a CENOTAPH and BURNS ALL input
    # runes (ordinals edict.rs: `output > tx.output.len()` -> Flaw::EdictOutput). Our decoder does not
    # flag this, so we must: otherwise a taker could append such an edict after a valid B->out0 edict,
    # pass this check, and have ord burn the maker's offered rune on broadcast. `output == n_out` is the
    # valid "all outputs" case and is allowed.
    for e in rs.get("edicts", []):
        if int(e.get("output", 0)) > n_out:
            return False, (f"edict output {e.get('output')} > {n_out} outputs — ord would treat this as "
                           f"a cenotaph and burn ALL input runes")
    # Same class for the POINTER: ord treats a pointer >= the output count as a CENOTAPH that burns ALL
    # input runes (runestone.rs: pointer is validated against tx.output.len()). The payload-only decoder
    # can't know n_out, so check it here — else a taker sets pointer huge, the maker's leftover counter-
    # rune appears to land on output 0, the maker signs, and ord burns everything on broadcast (snipe).
    ptr = rs.get("pointer")
    if ptr is not None and int(ptr) >= n_out:
        return False, (f"runestone pointer {ptr} >= {n_out} outputs — ord treats this as a cenotaph "
                       f"and burns ALL input runes")
    if not spks or spks[0] != maker_recv_spk_hex:
        return False, f"output 0 scriptPubKey {spks[0] if spks else None} is not the maker receive spk"
    alloc = allocate_runes(rs.get("edicts", []), input_runes, n_out, op_idx, rs.get("pointer"))
    b_blk, b_tx = _rid(rune_b_id)
    rid = f"{b_blk}:{b_tx}"
    got_b = alloc.get(0, {}).get(rid, 0)
    if got_b < int(amount_b):
        return False, f"output 0 receives {got_b} of rune {rid}, need >= {amount_b}"
    return True, "ok"
