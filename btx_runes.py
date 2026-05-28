"""
BTX Phase 0 — Runes asset leg.
Two modes:
  build  <utxo_json>            -> emits the SINGLE|ANYONECANPAY swap tx that ALSO carries a
                                   byte-accurate Runes runestone (taker-supplied edict).
  verify <rawtx_json> <supply>  -> minimal Runes edict indexer: parses the runestone from the
                                   on-chain tx and confirms the rune moved offer->taker output.

NOTE: the indexer is a faithful-at-the-byte-level but SIMPLIFIED model of Runes (single rune,
single transfer edict, explicit amounts). It is not the canonical `ord` implementation:
cenotaph rules, etching/mint, divisibility, default-output edge cases are out of scope.
"""
import sys, json, hashlib
import bitcoin
bitcoin.SelectParams('regtest')
from bitcoin.core import (COIN, CMutableTransaction, CMutableTxIn, CMutableTxOut,
                          COutPoint, CTxInWitness, CTxWitness, lx, b2x, x, Hash160)
from bitcoin.core.script import (CScript, CScriptWitness, SignatureHash, SIGHASH_SINGLE,
                                 SIGHASH_ALL, SIGHASH_ANYONECANPAY, SIGVERSION_WITNESS_V0,
                                 OP_0, OP_RETURN, OP_13, OP_DUP, OP_HASH160, OP_EQUALVERIFY,
                                 OP_CHECKSIG)
from bitcoin.wallet import CBitcoinSecret, P2WPKHBitcoinAddress

RUNE_BLOCK, RUNE_TX = 840000, 1     # rune id (seeded; Core doesn't track runes)
SUPPLY = 1000                       # whole rune units offered

def key(seed):
    s = CBitcoinSecret.from_secret_bytes(hashlib.sha256(seed).digest())
    return s, CScript([OP_0, Hash160(s.pub)])

def script_code(sec):
    return CScript([OP_DUP, OP_HASH160, Hash160(sec.pub), OP_EQUALVERIFY, OP_CHECKSIG])

def leb128(n):
    if n < 0:
        raise ValueError(f"leb128 cannot encode negative {n} (Runes varints are u128) — likely an "
                         f"edict tx delta gone negative; edicts must be sorted and use absolute tx on "
                         f"a block change")
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        if n: out.append(b | 0x80)
        else:
            out.append(b); break
    return bytes(out)

def leb128_decode_all(buf):
    vals, n, shift, started = [], 0, 0, False
    for byte in buf:
        started = True
        n |= (byte & 0x7f) << shift
        if byte & 0x80:
            shift += 7
        else:
            vals.append(n); n, shift = 0, 0
    return vals

def runestone_spk(edicts):
    # payload = Tag::Body(0) then, per edict, the Runes id encoding: edicts MUST be sorted by rune id
    # (block, tx) ascending. When the block is unchanged we emit (0, tx_delta); when the block changes
    # we emit (block_delta, ABSOLUTE tx) — NOT a tx delta. (Matches btx_runes_decode: h==0 -> txi+=t,
    # else blk+=h; txi=t.) Encoding tx as a delta across a block change can go negative when tx
    # decreases, which would make leb128 loop forever on a negative int — so absolute-tx is required,
    # not just nicer. Sorting here makes the function correct regardless of caller order.
    ints = [0]
    prev_block, prev_tx = 0, 0
    for (b, t, a, o) in sorted(edicts, key=lambda e: (e[0], e[1])):
        if b == prev_block:
            ints += [0, t - prev_tx, a, o]
        else:
            ints += [b - prev_block, t, a, o]      # new block: tx is absolute, not a delta
        prev_block, prev_tx = b, t
    payload = b''.join(leb128(i) for i in ints)
    return CScript([OP_RETURN, OP_13, payload])

# ---------------- BUILD ----------------
def build(utxo_json):
    data = json.loads(utxo_json)
    maker_sec, maker_spk   = key(b'btx-maker')
    taker_sec, taker_spk   = key(b'btx-taker')
    _,         payout_spk  = key(b'btx-maker-payout')
    offer, pay = data['offer'], data['pay']
    offer_sats = int(round(offer['amount_btc'] * COIN))
    pay_sats   = int(round(pay['amount_btc']   * COIN))
    price_sats = int(round(0.5 * COIN))
    fee_sats   = int(round(0.0001 * COIN))

    SAA = SIGHASH_SINGLE | SIGHASH_ANYONECANPAY
    # maker pre-signs ONLY [input0, output0]
    in0  = CMutableTxIn(COutPoint(lx(offer['txid']), offer['vout']))
    out0 = CMutableTxOut(price_sats, payout_spk)
    partial = CMutableTransaction([in0], [out0])
    sh = SignatureHash(script_code(maker_sec), partial, 0, SAA,
                       amount=offer_sats, sigversion=SIGVERSION_WITNESS_V0)
    sig = maker_sec.sign(sh) + bytes([SAA])
    wit_maker = CTxInWitness(CScriptWitness([sig, maker_sec.pub]))

    # taker assembles full tx: out0 maker payout (committed), out1 taker rune dest,
    # out2 runestone edict -> output index 1, out3 taker btc change region folded into out1
    i0 = CMutableTxIn(COutPoint(lx(offer['txid']), offer['vout']))
    i1 = CMutableTxIn(COutPoint(lx(pay['txid']),   pay['vout']))
    taker_btc = offer_sats + pay_sats - price_sats - fee_sats - 330  # 330 sat dust to rune-dest
    o0 = CMutableTxOut(price_sats, payout_spk)          # index 0  maker payout (no rune)
    o1 = CMutableTxOut(330 + taker_btc, taker_spk)      # index 1  taker: receives the rune + btc
    o2 = CMutableTxOut(0, runestone_spk([(RUNE_BLOCK, RUNE_TX, SUPPLY, 1)]))  # index 2 runestone
    tx = CMutableTransaction([i0, i1], [o0, o1, o2])
    sh_t = SignatureHash(script_code(taker_sec), tx, 1, SIGHASH_ALL,
                         amount=pay_sats, sigversion=SIGVERSION_WITNESS_V0)
    sig_t = taker_sec.sign(sh_t) + bytes([SIGHASH_ALL])
    wit_taker = CTxInWitness(CScriptWitness([sig_t, taker_sec.pub]))
    tx.wit = CTxWitness([wit_maker, wit_taker])

    print(json.dumps({
        "tx_hex": b2x(tx.serialize()),
        "runestone_spk_hex": b2x(runestone_spk([(RUNE_BLOCK, RUNE_TX, SUPPLY, 1)])),
        "taker_addr": str(P2WPKHBitcoinAddress.from_scriptPubKey(taker_spk)),
        "payout_addr": str(P2WPKHBitcoinAddress.from_scriptPubKey(payout_spk)),
        "rune_dest_output_index": 1,
        "supply": SUPPLY, "rune_id": f"{RUNE_BLOCK}:{RUNE_TX}",
    }))

# ---------------- VERIFY (minimal indexer) ----------------
def verify(rawtx_json, supply):
    tx = json.loads(rawtx_json)
    offer_outpoint = (tx['vin'][0]['txid'], tx['vin'][0]['vout'])
    # seed: input0 (maker offer outpoint) carries SUPPLY of the rune
    input_runes = {f"{RUNE_BLOCK}:{RUNE_TX}": int(supply)}
    # find + parse runestone
    runestone = None
    for vout in tx['vout']:
        asm = vout['scriptPubKey']['asm']
        hexs = vout['scriptPubKey']['hex']
        if hexs.startswith('6a5d'):           # OP_RETURN OP_13
            runestone = bytes.fromhex(hexs)
            break
    assert runestone is not None, "no runestone found"
    # strip OP_RETURN(6a) OP_13(5d) and the push opcode (single push, len in 1 byte)
    body = runestone[2:]
    push_len = body[0]
    payload = body[1:1+push_len]
    ints = leb128_decode_all(payload)
    assert ints[0] == 0, "expected Tag::Body(0)"
    rest = ints[1:]
    # decode delta edicts (block, tx, amount, output)
    edicts, pb, pt = [], 0, 0
    for i in range(0, len(rest), 4):
        db, dt, amt, out = rest[i:i+4]
        pb += db; pt += dt
        edicts.append((pb, pt, amt, out))
    # allocate
    n_out = len(tx['vout'])
    balances = {i: {} for i in range(n_out)}
    remaining = dict(input_runes)
    for (b, t, amt, out) in edicts:
        rid = f"{b}:{t}"
        give = remaining.get(rid, 0) if amt == 0 else min(amt, remaining.get(rid, 0))
        balances[out][rid] = balances[out].get(rid, 0) + give
        remaining[rid] = remaining.get(rid, 0) - give
    print(json.dumps({
        "edicts": edicts,
        "rune_balances_by_output": {str(k): v for k, v in balances.items() if v},
        "rune_on_output_1": balances[1].get(f"{RUNE_BLOCK}:{RUNE_TX}", 0),
        "rune_on_output_0_maker": balances[0].get(f"{RUNE_BLOCK}:{RUNE_TX}", 0),
        "unallocated": {k: v for k, v in remaining.items() if v},
    }))

if __name__ == "__main__":
    if sys.argv[1] == "build":   build(sys.argv[2])
    elif sys.argv[1] == "verify": verify(sys.argv[2], sys.argv[3])
