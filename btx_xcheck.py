#!/usr/bin/env python3
"""btx_xcheck.py — cross-implementation differential corpus for the BTX carrier-extraction layer.

Every Medium bug in the 2026-05 security audit (F-FILL, F-CARRIER, F-ANNEX; see
BTX-security-audit-2026-05.md) lived in the same gap: the Python reconstruction admitting a DIFFERENT
order set than the authoritative Rust indexer from the SAME chain bytes. The golden hash tests only cover
agreement on already-extracted views — they can't catch an extraction divergence. This harness closes
that: it builds an adversarial corpus of raw transactions exercising every known divergence class, runs
the Python extractor (`btx._extract_btx_from_tx`), and freezes the admitted offer-outpoint set per tx.

The SAME corpus (raw-tx hex + expected admitted outpoints) is embedded in the Rust test
`brk_indexer::btx::xcheck_corpus_matches_golden`, which runs the Rust extractors (`extract_from_script`
over every output + `extract_from_witness` over every input) and asserts the identical set. Two impls,
one corpus, byte-identical admission — a continuous differential that would have caught all three bugs.

Extraction is parse-only on both sides (sig verification is a separate, UTXO-dependent step), so the
corpus uses a well-formed *parseable* artifact whose offer_vout is patched per carrier to make each
admitted order distinguishable; no valid signature or live UTXO is needed.

Run:  python3 btx_xcheck.py            # build corpus, run Python extractor, assert == expected
      python3 btx_xcheck.py --emit     # also write btx_xcheck_corpus.json (the shared fixture)
"""
import sys, json, os
import btx_0b as btx
import btx_carrier as carrier
import btx as C
from bitcoin.core import (CMutableTransaction, CMutableTxIn, CMutableTxOut, COutPoint,
                          CTxInWitness, CTxWitness, b2x, b2lx)
from bitcoin.core.script import CScript, CScriptWitness, OP_RETURN, OP_CHECKSIG, OP_1

# A real, parseable v2 artifact (offer_txid = aa*32, vout 0). offer_vout is 4 LE bytes at offset 73.
_ART = bytes.fromhex(
    "4254583102010040d10c000100e80300000000000080f0fa020000000000ca9a3b0000000000000000"
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa00000000160014"
    "e9dd842d95a053c513315291f4d3f93b5a41059a2102bbfcf90b65934a165af1508d129cd749e764"
    "3bf75c66bd7f209a15f0b1497d7a8347304402205be5b4425958d1d6e0f8eb67cf4a7a2dc091d5d5"
    "f1ea08bc776896a03d8bfb3102205e6433b48f725d819e039749bd427299d33e4ba28b4e8ebb231d"
    "2574dc35577f83")
assert btx.parse_artifact(_ART) and _ART[:4] == btx.MAGIC


def _art(vout: int) -> bytes:
    """The artifact with its offer_vout patched (offset 73, 4 bytes LE) so each carrier is distinguishable."""
    b = bytearray(_ART)
    b[73:77] = int(vout).to_bytes(4, "little")
    assert btx.parse_artifact(bytes(b))["offer_vout"] == vout
    return bytes(b)


def _outpoint(vout: int) -> str:
    return f"{'aa' * 32}:{vout}"   # offer_txid is aa*32; display hex equals internal (all-same byte)


def _tx(vouts, witnesses=None):
    """Minimal tx: one dummy input per witness (or one input), the given outputs."""
    n_in = max(1, len(witnesses or []))
    tx = CMutableTransaction(
        [CMutableTxIn(COutPoint(bytes([i + 1]) * 32, i)) for i in range(n_in)],
        [CMutableTxOut(1000, CScript(spk)) for spk in vouts] or [CMutableTxOut(1000, CScript([OP_1]))])
    if witnesses:
        tx.wit = CTxWitness([CTxInWitness(CScriptWitness(w)) for w in witnesses])
    return tx


def build_corpus():
    """Each entry: (name, tx, expected_sorted_admitted_outpoints). Covers every divergence class the
    audit found, plus controls."""
    benign_leaf = bytes(CScript([b"\x11" * 32, OP_CHECKSIG]))               # tapscript with no envelope
    corpus = []

    # 1) clean OP_RETURN carrier -> admitted (vout 0)
    corpus.append(("op_return_clean",
                   _tx([bytes(CScript([OP_RETURN, _art(0)]))]),
                   [_outpoint(0)]))

    # 2) OP_RETURN with junk BEFORE the MAGIC inside the push -> admitted (Rust scans, Python now scans)
    corpus.append(("op_return_junk_prefix",
                   _tx([bytes(CScript([OP_RETURN, b"\x00\x99" + _art(1)]))]),
                   [_outpoint(1)]))

    # 3) NON-OP_RETURN output whose scriptPubKey contains the artifact -> admitted (both scan all outputs)
    corpus.append(("nonopreturn_output_carrier",
                   _tx([b"\x51" + _art(2)]),                                # OP_1 || artifact (raw spk)
                   [_outpoint(2)]))

    # 4) witness envelope IN THE LEAF script -> admitted (the honest envelope reveal shape)
    corpus.append(("witness_leaf_envelope",
                   _tx([bytes(CScript([OP_1]))],
                       witnesses=[[b"\x30" * 65, bytes(carrier.envelope_tapscript(_art(3))), b"\xc0" + b"\x22" * 32]]),
                   [_outpoint(3)]))

    # 5) envelope HIDDEN IN THE ANNEX, benign leaf -> NOT admitted (leaf-only; the F-ANNEX divergence)
    corpus.append(("witness_annex_hidden",
                   _tx([bytes(CScript([OP_1]))],
                       witnesses=[[b"\x30" * 65, benign_leaf, b"\xc0" + b"\x22" * 32,
                                   b"\x50" + bytes(carrier.envelope_tapscript(_art(4)))]]),
                   []))

    # 6) control: a plain tx with no artifact anywhere -> nothing admitted
    corpus.append(("no_artifact",
                   _tx([b"\x00\x14" + b"\x33" * 20],
                       witnesses=[[b"\x30" * 65, b"\x02" + b"\x44" * 32]]),
                   []))

    # 7-8) NON-CANONICAL PUSHDATA inside the witness-leaf envelope. This exercises the Python
    # `parse_envelope` vs Rust `parse_envelope_payload` byte-identical REASSEMBLY — the one residual the
    # audit could only check by inspection. Both decoders must read a push by its DECLARED opcode/length
    # (not enforce minimal-push) and concatenate multi-chunk payloads identically. (7) the artifact in ONE
    # non-minimal OP_PUSHDATA2 push; (8) the artifact SPLIT across two pushes.
    pd1 = lambda d: b"\x4c" + bytes([len(d)]) + d                  # OP_PUSHDATA1
    pd2 = lambda d: b"\x4d" + len(d).to_bytes(2, "little") + d      # OP_PUSHDATA2 (non-minimal for len<=255)
    pd4 = lambda d: b"\x4e" + len(d).to_bytes(4, "little") + d      # OP_PUSHDATA4 (non-minimal for any len)
    env_hdr = b"\x20" + b"\x02" * 32 + b"\xac\x00\x63"             # <pubkey> OP_CHECKSIG OP_FALSE OP_IF
    cb = b"\xc0" + b"\x22" * 32                                     # control block
    leaf_pd2 = env_hdr + pd2(_art(5)) + b"\x68"                     # one non-minimal PUSHDATA2 push
    a6 = _art(6)
    leaf_split = env_hdr + pd1(a6[:100]) + pd1(a6[100:]) + b"\x68"  # artifact split across two pushes
    leaf_pd4 = env_hdr + pd4(_art(7)) + b"\x68"                     # one non-minimal PUSHDATA4 push (0x4e)
    corpus.append(("envelope_pushdata2_noncanonical",
                   _tx([bytes(CScript([OP_1]))], witnesses=[[b"\x30" * 65, leaf_pd2, cb]]),
                   [_outpoint(5)]))
    corpus.append(("envelope_split_two_pushes",
                   _tx([bytes(CScript([OP_1]))], witnesses=[[b"\x30" * 65, leaf_split, cb]]),
                   [_outpoint(6)]))
    # 9) OP_PUSHDATA4 (0x4e) non-minimal — completes the push-opcode matrix (0x4c/0x4d/0x4e all exercised).
    #    Rust parse_envelope_payload reads the 4-byte LE length; Python CScript.raw_iter does the same;
    #    both reassemble the identical artifact -> identical admission.
    corpus.append(("envelope_pushdata4_noncanonical",
                   _tx([bytes(CScript([OP_1]))], witnesses=[[b"\x30" * 65, leaf_pd4, cb]]),
                   [_outpoint(7)]))
    return corpus


def python_admitted(tx):
    """Sorted set of offer outpoints the PYTHON extractor admits from a tx."""
    arts = C._extract_btx_from_tx(tx)
    return sorted({f"{b2lx(a['offer_txid'])}:{a['offer_vout']}" for (_carrier, a) in arts})


def main():
    corpus = build_corpus()
    rows, ok = [], True
    for name, tx, expected in corpus:
        got = python_admitted(tx)
        exp = sorted(expected)
        passed = got == exp
        ok = ok and passed
        rows.append({"name": name, "raw_tx_hex": b2x(tx.serialize()), "expected_admitted": exp})
        print(f"  [{'OK' if passed else 'FAIL'}] {name:26} python_admitted={got} expected={exp}")
    print(f"\n{'cross-impl corpus: Python side matches expected admission' if ok else 'PYTHON SIDE DIVERGES FROM EXPECTED'}")
    if "--emit" in sys.argv:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "btx_xcheck_corpus.json")
        json.dump({"note": "shared BTX extraction differential corpus; Rust test asserts identical admission",
                   "corpus": rows}, open(path, "w"), indent=2)
        print(f"wrote {path}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
