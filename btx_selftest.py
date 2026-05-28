#!/usr/bin/env python3
"""
btx_selftest.py — aggregate OFFLINE regression suite for the whole BTX protocol layer.

Runs every check that does NOT require a node, in one command, and exits 0 iff all pass. Use this
as the green-light before/after any change to the protocol code. The on-node steps (real wallet
sig acceptance, consensus settlement, Taproot reveal) are NOT here — they live in the runbooks
(BTX-0b-runbook.md, BTX-wallet-runbook.md) because they need a live regtest node.

Covers:
  1. btx_0b.py        — artifact serialize/parse/verify/build round-trip + tamper (subprocess)
  2. btx_carrier.py   — envelope round-trip (single+multi-chunk), tapleaf, non-envelope (subprocess)
  3. btx_wallet.py    — wallet-integration plumbing simulate: witness lift/assemble/transplant
  3b. btx_taproot.py  — BIP340 Schnorr sign/verify + BIP341 TapSighash vs official vectors
  3c. btx_envelope_publish.py — build_reveal round-trip (witness carries artifact; sig verifies)
  4. runes encoding     — multi-edict runestone reproduces the ord-validated byte vector
  5. btx.py order     — create -> verify (valid VALID, wrong amount INVALID)
  6. btx.py book scan  — OP_RETURN announce+fill=FILLED, announce-only=OPEN, announce+cancel=
                           CANCELLED, AND a Taproot witness-envelope announce=OPEN (carrier-agnostic)
"""
import sys, os, json, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PY = sys.executable

import btx_0b as btx
import btx_runes as runes
import btx_carrier as carrier
import btx_wallet as wallet
import btx_etch as etch
import btx_runes_decode as rdec
from bitcoin.core import (COIN, b2x, lx, CMutableTransaction, CMutableTxIn, CMutableTxOut,
                          COutPoint, CTxInWitness, CTxWitness)
from bitcoin.core.script import CScript, CScriptWitness, OP_RETURN, OP_0

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))


def _run(args, inp=None):
    r = subprocess.run([PY] + args, capture_output=True, text=True, cwd=HERE)
    return r.returncode, r.stdout, r.stderr


def _run_json(args):
    rc, out, err = _run(args)
    if rc != 0:
        return None, err
    try:
        return json.loads(out), None
    except json.JSONDecodeError:
        # some scripts print prose after JSON; take the first JSON object
        try:
            return json.loads(out[out.index("{"):out.rindex("}") + 1]), None
        except Exception as e:
            return None, f"{e}: {out[:200]}"


def _ser(tx):
    return b2x(tx.serialize())


def main():
    print("== 1. btx_0b selftest ==")
    # call selftest() directly (robust whether or not the module has a __main__ block)
    d, err = _run_json(["-c", "import btx_0b; btx_0b.selftest()"])
    check("btx_0b ALL_PASS", d and d.get("ALL_PASS") is True, err or "")

    print("== 2. btx_carrier selftest ==")
    d, err = _run_json(["btx_carrier.py"])
    check("btx_carrier ALL_PASS", d and d.get("ALL_PASS") is True, err or "")

    print("== 3. btx_wallet simulate ==")
    d, err = _run_json(["btx_wallet.py", "simulate"])
    check("btx_wallet simulate ALL_PASS", d and d.get("ALL_PASS") is True, err or "")

    print("== 3b. btx_taproot vs BIP340/BIP341 vectors ==")
    d, err = _run_json(["-c", "import btx_taproot; btx_taproot.selftest()"])
    check("btx_taproot ALL_PASS (BIP340 + BIP341 vectors)", d and d.get("ALL_PASS") is True, err or "")

    print("== 3c. btx_envelope_publish build_reveal (offline) ==")
    d, err = _run_json(["-c", "import btx_envelope_publish as p; p.selftest()"])
    check("btx_envelope_publish ALL_PASS (reveal round-trip)", d and d.get("ALL_PASS") is True, err or "")

    print("== 4. runes encoding vector (ord-validated) ==")
    spk = b2x(runes.runestone_spk([(231, 1, 1, 0), (231, 1, 2, 1), (231, 1, 997, 2)]))
    check("multi-edict runestone == ord vector", spk == "6a5d0f00e701010100000002010000e50702",
          f"got {spk}")
    spk1 = b2x(runes.runestone_spk([(231, 1, 1000, 0)]))
    check("single-edict runestone == ord vector", spk1 == "6a5d0700e70101e80700", f"got {spk1}")

    print("== 5. btx.py order create -> verify ==")
    d, err = _run_json(["btx.py", "order", "create", "--offer-txid", "aa" * 32,
                        "--offer-vout", "0", "--offer-amount-btc", "1.0", "--price-btc", "0.5"])
    art_hex = d["artifact_hex"] if d else None
    # artifact size varies ~206-209 B: the DER sig is 70-72 B (OpenSSL non-deterministic ECDSA).
    # The 240-byte -datacarriersize in the runbook has ample margin for this.
    nbytes = d.get("artifact_bytes") if d else None
    check("order create emits ~207-byte artifact (206-210)",
          nbytes is not None and 206 <= nbytes <= 210, f"got {nbytes}")
    if art_hex:
        dv, e = _run_json(["btx.py", "order", "verify", "--artifact-hex", art_hex,
                           "--offer-amount-btc", "1.0"])
        check("order verify correct amount = VALID", dv and dv.get("maker_sig_verifies") is True, e or "")
        dw, e = _run_json(["btx.py", "order", "verify", "--artifact-hex", art_hex,
                           "--offer-amount-btc", "0.9"])
        check("order verify wrong amount = INVALID", dw and dw.get("maker_sig_verifies") is False, e or "")

    print("== 6. btx.py book scan (both carriers) ==")
    OFFER = "aa" * 32
    art = btx.make_artifact(OFFER, 0, int(1.0 * COIN), int(0.5 * COIN), amount_units=1000, group_id=7)
    blob = btx.serialize_artifact(art)
    parsed = btx.parse_artifact(blob)
    # OP_RETURN announce
    ann = CMutableTransaction([CMutableTxIn(COutPoint(lx("cc" * 32), 0))],
                              [CMutableTxOut(0, CScript([OP_RETURN, blob])),
                               CMutableTxOut(99000000, CScript([OP_0, b"\x11" * 20]))])
    fill = btx.build_swap_from_artifact(parsed, int(1.0 * COIN), ("bb" * 32, 1), int(0.6 * COIN), b"btx-taker")
    cancel = CMutableTransaction([CMutableTxIn(COutPoint(lx(OFFER), 0))],
                                 [CMutableTxOut(int(0.4 * COIN), CScript([OP_0, b"\x22" * 20]))])

    def scan(txs, utxos=None):
        args = ["btx.py", "book", "scan", "--txs", json.dumps(txs)]
        if utxos:
            args += ["--utxos", json.dumps(utxos)]
        return _run_json(args)

    A, e = scan([_ser(ann), _ser(fill)])
    check("scan: announce+fill = FILLED", A and A.get("filled") == 1 and A["orders"][0]["is_fill"] is True, e or "")
    B, e = scan([_ser(ann)], {f"{OFFER}:0": int(1.0 * COIN)})
    check("scan: announce-only = OPEN + sig verifies",
          B and B.get("open") == 1 and B["orders"][0].get("maker_sig_verifies") is True, e or "")
    C, e = scan([_ser(ann), _ser(cancel)])
    check("scan: announce+cancel = CANCELLED", C and C.get("cancelled") == 1 and C["orders"][0]["is_fill"] is False, e or "")

    # Taproot witness-envelope announce
    tapscript = bytes(carrier.envelope_tapscript(blob))
    reveal = CMutableTransaction([CMutableTxIn(COutPoint(lx("dd" * 32), 0))],
                                 [CMutableTxOut(330, CScript(parsed["payout_spk"]))])
    reveal.wit = CTxWitness([CTxInWitness(CScriptWitness([b"\x00" * 64, tapscript, b"\xc0" + b"\x02" * 32]))])
    E, e = scan([_ser(reveal)], {f"{OFFER}:0": int(1.0 * COIN)})
    check("scan: witness-envelope announce = OPEN (carrier-agnostic)",
          E and E.get("orders_found") == 1 and E["orders"][0].get("maker_sig_verifies") is True, e or "")

    print("== 7. rune-aware taker swap edicts the asset to the taker ==")
    # A BTC<->rune order: the offer UTXO holds 1000 of rune 840000:1. The settlement MUST carry a
    # runestone edict moving that rune to the taker (output 1), or Runes' default routing would send
    # it to output 0 (the maker). Build the swap and assert the edict + that output 0 is untouched.
    payout_spk = b"\x00\x14" + b"\x11" * 20
    taker_spk  = b"\x00\x14" + b"\x22" * 20
    rune_art = dict(offer_txid=lx("aa" * 32), offer_vout=0, price=50_000_000,
                    payout_spk=payout_spk, amount=1000, rune_block=840000, rune_tx=1)
    swap = wallet.build_taker_swap_unsigned(rune_art, 100_000, "bb" * 32, 1, 60_000_000,
                                            taker_spk, fee=10_000)
    check("rune swap: 3 outputs (payout, taker, runestone)", len(swap.vout) == 3,
          f"got {len(swap.vout)} outputs")
    check("rune swap: output 0 = maker payout, untouched",
          swap.vout[0].nValue == 50_000_000 and bytes(swap.vout[0].scriptPubKey) == payout_spk,
          f"val={swap.vout[0].nValue}")
    check("rune swap: output 1 value = offer+fund-price-fee",
          swap.vout[1].nValue == 100_000 + 60_000_000 - 50_000_000 - 10_000,
          f"val={swap.vout[1].nValue}")
    runestone = swap.vout[-1].scriptPubKey
    pushes = [op for op in runestone if isinstance(op, bytes)]
    ints = runes.leb128_decode_all(pushes[-1]) if pushes else []
    # payload = [Body tag 0, block-delta, tx-delta, amount, output] for a single edict from zero
    check("rune swap: runestone is OP_RETURN", bytes(runestone)[:1] == b"\x6a",
          f"first byte {bytes(runestone)[:1].hex()}")
    check("rune swap: edict moves full amount (1000) to taker output (idx 1)",
          ints == [0, 840000, 1, 1000, 1], f"decoded {ints}")
    # Backward-compat: a BTC-only order (no rune) must stay 2 outputs, no runestone.
    btc_art = dict(offer_txid=lx("cc" * 32), offer_vout=0, price=50_000_000,
                   payout_spk=payout_spk, amount=0, rune_block=0, rune_tx=0)
    swap_btc = wallet.build_taker_swap_unsigned(btc_art, 100_000, "dd" * 32, 1, 60_000_000,
                                                taker_spk, fee=10_000)
    check("btc-only swap: still 2 outputs (no runestone)", len(swap_btc.vout) == 2,
          f"got {len(swap_btc.vout)} outputs")

    print("== 8. maker-side rune-backing guard (validate-before-advertise) ==")
    # The oracle is stubbed here (a dict); on a live node it is an ord query. The guard must enforce
    # the EXACTLY-amount invariant: too little can't be honored, too much would leak the remainder to
    # the maker (output 0) on settlement.
    def stub(have):
        return lambda outpoint, rune_id: have.get(rune_id, 0)
    def refuses(lookup, amt):
        try:
            wallet.assert_offer_backs_rune(lookup, "aa" * 32, 0, "840000:1", amt)
            return False
        except ValueError:
            return True
    check("guard: exact backing -> publishes",
          wallet.assert_offer_backs_rune(stub({"840000:1": 1000}), "aa" * 32, 0, "840000:1", 1000) is True)
    check("guard: too little -> refuses", refuses(stub({"840000:1": 999}), 1000))
    check("guard: missing rune -> refuses", refuses(stub({}), 1000))
    check("guard: too much (remainder would leak to maker) -> refuses", refuses(stub({"840000:1": 1001}), 1000))

    print("== 9. ord rune-oracle parsing (grounded in real ord 0.27.1 JSON) ==")
    # Real /rune/1:0 response captured from a live ord server (UNCOMMON*GOODS):
    rune_json = {"entry": {"block": 1, "divisibility": 0, "spaced_rune": "UNCOMMON•GOODS",
                           "symbol": "⧉", "premine": 0, "turbo": True}, "id": "1:0",
                 "mintable": True, "parent": None}
    name = wallet._rune_name_from_entry(rune_json)
    check("oracle: resolves rune id -> spaced name", name == "UNCOMMON•GOODS", f"got {name}")
    # Real /output of a SPENT holder (runes empty) -> 0:
    spent_out = {"runes": {}, "spent": True, "value": 546}
    check("oracle: spent/empty output -> 0", wallet._output_rune_amount(spent_out, name) == 0)
    # An UNSPENT holder mirrors ord's Pile shape {amount, divisibility, symbol}; amount = base units:
    held_out = {"runes": {name: {"amount": 25403, "divisibility": 0, "symbol": "⧉"}},
                "spent": False, "value": 546}
    check("oracle: reads base-unit amount from runes pile",
          wallet._output_rune_amount(held_out, name) == 25403)
    # End-to-end via the guard with an ord-shaped lookup:
    lookup = lambda outpoint, rid: wallet._output_rune_amount(held_out, name) if rid == "1:0" else 0
    check("oracle+guard: exact match publishes",
          wallet.assert_offer_backs_rune(lookup, "aa" * 32, 1, "1:0", 25403) is True)

    print("== 10. rune ETCHING encoder (validated vs UNCOMMON•GOODS protocol constants) ==")
    # UNCOMMON•GOODS is the Runes protocol-genesis rune (hard-coded in ord source, not etched by a tx).
    # ALL five encoder fields now match UNCOMMON•GOODS's authoritative ord-docs values (api.md):
    # name "UNCOMMONGOODS" (rune number 0), spacers 128 (display "UNCOMMON•GOODS"), divisibility 0,
    # premine 0, symbol "⧉" (U+29C9). Decoder is independently validated by btx_runes_xcheck.py
    # (Magic Eden runestone-lib goldens), so encoder→decoder→protocol-constants is end-to-end real.
    ucgn = etch.rune_number("UNCOMMONGOODS")
    et = rdec.decode_payload(etch.etching_payload(ucgn, divisibility=0, premine=0,
                                                  symbol="⧉", spacers=128)).get("etching")
    check("etch: UNCOMMON•GOODS etching round-trips (name/div/premine/spacers/symbol)",
          et and et["name"] == "UNCOMMONGOODS" and et["divisibility"] == 0
          and et["premine"] == 0 and et["spacers"] == 128 and et["symbol"] == "⧉", str(et))
    cn = etch.rune_number("BTXUSDTESTS")
    check("etch: rune name<->number inverse", rdec.rune_name(cn) == "BTXUSDTESTS")
    check("etch: commitment is minimal-LE and round-trips to the number",
          int.from_bytes(etch.rune_commitment(cn), "little") == cn)

    print("== 11. on-node etch reveal construction (offline structure) ==")
    import btx_taproot as T
    from bitcoin.core import x as _x, CTransaction
    cn = etch.rune_number("BTXUSDTESTS")
    r = etch.build_etch_reveal(seckey=bytes.fromhex("11" * 32), rune_num=cn, commit_txid="ab" * 32,
                               commit_vout=1, commit_value_sats=100000,
                               premine_spk=bytes.fromhex("0014" + "22" * 20),
                               divisibility=0, premine=1000, symbol="$", fee_sats=2000, hrp="bcrt")
    rtx = CTransaction.deserialize(_x(r["reveal_hex"]))
    st = [bytes(s) for s in rtx.wit.vtxinwit[0].scriptWitness.stack]
    check("etch reveal: 2 outputs (premine dest + runestone)", len(rtx.vout) == 2)
    check("etch reveal: witness = [sig(64), tapscript, control_block(33)]",
          len(st) == 3 and len(st[0]) == 64 and len(st[2]) == 33)
    check("etch reveal: tapscript carries the rune commitment push", etch.rune_commitment(cn) in st[1])
    expect = etch.runestone_spk_bytes(etch.etching_payload(cn, divisibility=0, premine=1000, symbol="$"))
    check("etch reveal: output 1 == the expected etching runestone",
          bytes(rtx.vout[1].scriptPubKey) == expect)
    check("etch reveal: schnorr sig verifies under internal key over the script-path sighash",
          T.schnorr_verify(bytes.fromhex(r["sighash_hex"]), bytes.fromhex(r["internal_xonly_hex"]), st[0]))

    print("== 12. audit hardening (parse bounds + swap dust guard) ==")
    def raises(fn, exc=Exception):
        try:
            fn(); return False
        except exc:
            return True
    good = btx.serialize_artifact(dict(msg_type=1, side=0, rune_block=840000, rune_tx=1, amount=1000,
            price=1000000, expiry=10**9, group_id=0, offer_txid=b"\xaa" * 32, offer_vout=0,
            payout_spk=b"\x00\x14" + b"\x11" * 20, maker_pubkey=b"\x02" + b"\x33" * 32,
            sighash_flag=0x83, maker_sig=b"\x44" * 71))
    check("parse_artifact: valid round-trips", btx.parse_artifact(good)["amount"] == 1000)
    check("parse_artifact: truncated -> ValueError (not IndexError/struct.error)",
          raises(lambda: btx.parse_artifact(good[:len(good) - 12]), ValueError))
    check("parse_artifact: bad magic -> ValueError", raises(lambda: btx.parse_artifact(b"\x00" * 40), ValueError))
    # corrupt the payout_spk length byte (offset 77 for a v2 artifact) to claim 255 bytes -> overrun
    _bad = bytearray(good); _bad[77] = 0xff
    check("parse_artifact: declared-len overrun -> ValueError",
          raises(lambda: btx.parse_artifact(bytes(_bad)), ValueError))
    check("taker swap: dust/underfunded output -> refused",
          raises(lambda: wallet.build_taker_swap_unsigned(
              dict(offer_txid=lx("aa" * 32), offer_vout=0, price=50_000_000,
                   payout_spk=b"\x00\x14" + b"\x11" * 20, amount=0, rune_block=0, rune_tx=0),
              100, "bb" * 32, 1, 50_000_000, b"\x00\x14" + b"\x22" * 20, fee=2000), ValueError))

    print("== 13. second-audit fixes (funding rune-safety + exclude fallback) ==")
    # the `reject` hook must skip a rune-bearing funding UTXO even though it is the cheapest match
    funds = [{"txid": "11" * 32, "vout": 0, "amount": 1.0, "scriptPubKey": "0014" + "aa" * 20},   # "rune-bearing"
             {"txid": "22" * 32, "vout": 1, "amount": 2.0, "scriptPubKey": "0014" + "bb" * 20}]    # clean, larger
    picked = wallet._pick_p2wpkh_utxo(funds, want_sats=int(0.5 * COIN),
                                      reject=lambda op: op == f"{'11' * 32}:0")
    check("funding: reject skips the rune-bearing UTXO and picks the clean one",
          picked is not None and picked["txid"] == "22" * 32, str(picked and picked["txid"]))
    # exclude must apply even on the non-0014 `cands` fallback (was a double-spend risk)
    tap = [{"txid": "33" * 32, "vout": 0, "amount": 1.0, "desc": "tr(x)", "scriptPubKey": "5120" + "cc" * 32}]
    check("funding: exclude applies to the cands fallback (no double-spend of the offer)",
          wallet._pick_p2wpkh_utxo(tap, want_sats=int(0.5 * COIN), exclude={f"{'33' * 32}:0"}) is None)

    npass = sum(1 for _, ok, _ in RESULTS if ok)
    ntot = len(RESULTS)
    print(f"\n==== {npass}/{ntot} checks passed ====")
    if npass != ntot:
        print("FAILURES:")
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  - {name}: {detail}")
        sys.exit(1)
    print("ALL BTX OFFLINE CHECKS PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
