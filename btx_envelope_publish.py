#!/usr/bin/env python3
"""
btx_envelope_publish.py — publish a BTX order via the Taproot witness-envelope carrier.

`btx_carrier.py` proved the envelope ENCODING and `btx_taproot.py` proved the BIP340/341 crypto
(commit address, output-key tweak, control block, Schnorr sign, TapSighash — all against official
vectors). This module is the missing runnable piece: it funds the commit output and builds + signs +
broadcasts the reveal transaction, so an order can be announced ENTIRELY in witness data — with no
relaxed -datacarriersize (witness bytes are not subject to the datacarrier limit).

Flow (BIP341 script-path, single leaf):
  1. derive a reveal key d -> x-only P; build the envelope tapscript `<P> OP_CHECKSIG OP_FALSE OP_IF
     <artifact chunks> OP_ENDIF`.
  2. commit: pay a P2TR output whose output key = tweak(P, tapleaf(envelope)).
  3. reveal: spend that output; witness = [schnorr_sig, envelope_tapscript, control_block]. OP_CHECKSIG
     in the leaf verifies `schnorr_sig` under `P` over the BIP341 script-path sighash, then the
     OP_FALSE OP_IF .. OP_ENDIF data is skipped. The brk-btx indexer reads the artifact straight out
     of the revealed tapscript (btx::extract_from_witness).

`build_reveal` is PURE (no node) and is what the offline selftest exercises. `publish` drives a live
node over bitcoin-cli. The script-path sighash's final proof is on-node acceptance: if any byte of the
sighash/sig/control-block is wrong, the network rejects the reveal with a script-verify error.
"""
import sys, os, json, subprocess, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import btx_taproot as T
import btx_carrier as carrier
from bitcoin.core import (COIN, b2x, x, lx, b2lx, CMutableTransaction, CTransaction,
                          CMutableTxIn, CMutableTxOut, COutPoint, CTxInWitness, CTxWitness)
from bitcoin.core.script import CScript, CScriptWitness

# bech32 human-readable part by chain (for the commit address)
_HRP = {"regtest": "bcrt", "signet": "tb", "testnet": "tb", "test": "tb", "testnet4": "tb",
        "main": "bc", "mainnet": "bc"}
DEFAULT_FEE = 2000          # sats for the reveal tx
DEFAULT_COMMIT_BTC = 0.0005  # funds the commit output (must cover reveal out + fee, above dust)


# ----------------------------- thin RPC over bitcoin-cli -----------------------------
class CLI:
    _CHAIN_FLAG = {"regtest": "-regtest", "signet": "-signet", "testnet": "-testnet",
                   "test": "-testnet", "testnet4": "-testnet4", "main": "-chain=main",
                   "mainnet": "-chain=main"}

    def __init__(self, cli="bitcoin-cli", chain="regtest", datadir=None, wallet=None, dry=False):
        self.base = [cli, self._CHAIN_FLAG.get(chain, f"-chain={chain}")]
        if datadir:
            self.base.append(f"-datadir={datadir}")
        self.wallet = wallet
        self.dry = dry

    def __call__(self, *args):
        c = list(self.base)
        if self.wallet:
            c.append(f"-rpcwallet={self.wallet}")
        c += [str(a) for a in args]
        if self.dry:
            print("DRY-RUN:", " ".join(repr(a) if " " in a else a for a in c))
            return None
        r = subprocess.run(c, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"bitcoin-cli failed: {r.stderr.strip()}")
        s = r.stdout.strip()
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return s


# ----------------------------- pure reveal construction (offline-testable) -----------------------------
def build_reveal(*, artifact_hex, seckey, commit_txid, commit_vout, commit_value_sats,
                 out_spk, fee_sats=DEFAULT_FEE, hrp="bc"):
    """Build the signed reveal tx that carries `artifact_hex` in a Taproot witness envelope, spending
    the commit output (commit_txid:commit_vout, value commit_value_sats) to a single `out_spk`. Returns
    a dict with reveal_hex plus all the intermediate commitments (so callers/tests can cross-check)."""
    blob = bytes.fromhex(artifact_hex)
    px, _point = T.xonly_pubkey(seckey)
    ts_bytes = bytes(carrier.envelope_tapscript(blob, internal_xonly_pubkey=px))
    commit = T.commit_for_envelope(px, ts_bytes, hrp=hrp)
    commit_spk = bytes.fromhex(commit["commit_scriptPubKey_hex"])
    tapleaf = bytes.fromhex(commit["tapleaf_hex"])
    cb = bytes.fromhex(commit["control_block_hex"])

    out_value = commit_value_sats - fee_sats
    if out_value < 546:   # below the 546-sat dust floor (or negative) the reveal output is non-standard /
                          # won't relay; mirror the dust guard the other BTX tx builders enforce
        raise ValueError(f"reveal output {out_value} sats is below the 546-sat dust floor "
                         f"(commit {commit_value_sats} - fee {fee_sats}) — raise --commit-amount-btc or lower --fee-sats")
    txid_internal = lx(commit_txid)                       # internal byte order
    txin = CMutableTxIn(COutPoint(txid_internal, commit_vout), nSequence=0xffffffff)
    txout = CMutableTxOut(out_value, CScript(bytes(out_spk)))
    tx = CMutableTransaction([txin], [txout], nVersion=2, nLockTime=0)

    sighash = T.tap_sighash(
        version=2, locktime=0,
        vin=[(bytes(txid_internal), commit_vout, 0xffffffff)],
        spent_amounts=[commit_value_sats], spent_spks=[commit_spk],
        vout=[(out_value, bytes(out_spk))], input_index=0,
        hash_type=T.SIGHASH_DEFAULT, ext_flag=1, tapleaf_hash=tapleaf,
    )
    # fresh aux_rand per signature (BIP340 §"Default Signing"): the scheme is secure with aux_rand=0,
    # but supplying fresh randomness hardens against fault/side-channel attacks at zero cost. The sig
    # stays valid and the witness still round-trips to the artifact (which is independent of the sig).
    sig = T.schnorr_sign(sighash, seckey, aux_rand=os.urandom(32))  # 64 bytes => SIGHASH_DEFAULT
    tx.wit = CTxWitness([CTxInWitness(CScriptWitness([sig, ts_bytes, cb]))])
    return {
        "reveal_hex": b2x(tx.serialize()),
        "internal_xonly_hex": px.hex(),
        "commit_address": commit["commit_address"],
        "commit_scriptPubKey_hex": commit["commit_scriptPubKey_hex"],
        "envelope_tapscript_hex": ts_bytes.hex(),
        "tapleaf_hex": commit["tapleaf_hex"],
        "control_block_hex": commit["control_block_hex"],
        "sighash_hex": sighash.hex(),
        "schnorr_sig_hex": sig.hex(),
        "out_value_sats": out_value,
    }


def _new_seckey(seckey_hex=None):
    if seckey_hex:
        sk = bytes.fromhex(seckey_hex)
    else:
        sk = os.urandom(32)
    d = int.from_bytes(sk, "big")
    if not (1 <= d < T.N):
        raise ValueError("derived secret key out of range; retry")
    return sk


# ----------------------------- on-node publish -----------------------------
def cmd_publish(a):
    cli = CLI(a.bitcoin_cli, a.chain, a.datadir, a.wallet, a.dry_run)
    hrp = _HRP.get(a.chain, "bc")
    seckey = _new_seckey(a.seckey)
    px, _ = T.xonly_pubkey(seckey)
    ts_bytes = bytes(carrier.envelope_tapscript(bytes.fromhex(a.artifact_hex), internal_xonly_pubkey=px))
    commit = T.commit_for_envelope(px, ts_bytes, hrp=hrp)

    if a.dry_run:
        print(json.dumps({"commit_address": commit["commit_address"],
                          "commit_scriptPubKey_hex": commit["commit_scriptPubKey_hex"],
                          "internal_xonly_hex": px.hex(),
                          "note": "dry-run: would sendtoaddress then build+broadcast the reveal"},
                         indent=2))
        return

    # 1) fund the commit output
    commit_txid = cli("sendtoaddress", commit["commit_address"], f"{a.commit_amount_btc:.8f}")
    raw = cli("getrawtransaction", commit_txid, "true")
    commit_vout, commit_value = None, None
    for vo in raw["vout"]:
        if vo["scriptPubKey"]["hex"] == commit["commit_scriptPubKey_hex"]:
            commit_vout = vo["n"]
            commit_value = int(round(vo["value"] * COIN))
            break
    if commit_vout is None:
        sys.exit(f"could not locate commit output in {commit_txid}")

    # The commit is now broadcast and funds a P2TR spendable ONLY by `seckey`. That key is otherwise
    # only in memory, so a crash / RPC failure before the reveal broadcasts would strand the commit
    # funds forever. Persist a recovery record (0o600, mirrors etch) BEFORE the reveal so a hard crash
    # is recoverable via `publish-reveal --state-file`, and re-emit it on any caught failure.
    recovery = {"artifact_hex": a.artifact_hex, "seckey_hex": seckey.hex(), "chain": a.chain,
                "commit_txid": commit_txid, "commit_vout": commit_vout,
                "commit_value_sats": commit_value, "fee_sats": a.fee_sats}
    if a.state_file:
        fd = os.open(a.state_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(recovery, f, indent=2)
        os.chmod(a.state_file, 0o600)
    try:
        # 2) build the reveal back to a fresh wallet address
        out_addr = a.out_addr or cli("getnewaddress", "", "bech32")
        out_spk = bytes.fromhex(cli("getaddressinfo", out_addr)["scriptPubKey"])
        res = build_reveal(artifact_hex=a.artifact_hex, seckey=seckey, commit_txid=commit_txid,
                           commit_vout=commit_vout, commit_value_sats=commit_value,
                           out_spk=out_spk, fee_sats=a.fee_sats, hrp=hrp)
        res.update({"commit_txid": commit_txid, "commit_vout": commit_vout,
                    "commit_value_sats": commit_value, "out_addr": out_addr})
        # 3) broadcast the reveal (the commit is already in the mempool from sendtoaddress)
        if a.broadcast:
            res["reveal_txid"] = cli("sendrawtransaction", res["reveal_hex"])
    except Exception as e:
        recovery["error"] = f"reveal failed after commit {commit_txid} was broadcast: {e}"
        recovery["recovery"] = (
            "commit funds are spendable ONLY by seckey_hex above; recover with: "
            "btx_envelope_publish.py publish-reveal --seckey <seckey_hex> --artifact-hex <artifact> "
            "--commit-txid <txid> --commit-vout <vout> --commit-value-sats <sats> --broadcast"
            + (f"  (or --state-file {a.state_file})" if a.state_file else " — SAVE seckey_hex now"))
        print(json.dumps(recovery, indent=2)); sys.exit(1)
    print(json.dumps(res, indent=2))


def cmd_publish_reveal(a):
    """Finish (or retry) an envelope publish from a saved recovery state — used when the commit was
    broadcast but the reveal didn't, so the commit funds aren't stranded. Reads `--state-file` (written
    by `publish`) or the equivalent flags, rebuilds the reveal with the saved ephemeral key, and
    broadcasts it to a fresh wallet address."""
    cli = CLI(a.bitcoin_cli, a.chain, a.datadir, a.wallet, a.dry_run)
    if a.state_file:
        with open(a.state_file) as f:
            st = json.load(f)
    else:
        need = {"seckey": a.seckey, "artifact_hex": a.artifact_hex, "commit_txid": a.commit_txid,
                "commit_vout": a.commit_vout, "commit_value_sats": a.commit_value_sats}
        missing = [k for k, v in need.items() if v is None]
        if missing:
            sys.exit("need --state-file, or all of: " + ", ".join("--" + m.replace("_", "-") for m in missing))
        st = {"seckey_hex": a.seckey, "artifact_hex": a.artifact_hex, "commit_txid": a.commit_txid,
              "commit_vout": a.commit_vout, "commit_value_sats": a.commit_value_sats,
              "fee_sats": a.fee_sats, "chain": a.chain}
    hrp = _HRP.get(st.get("chain", a.chain), "bc")
    seckey = bytes.fromhex(st["seckey_hex"])
    out_addr = a.out_addr or cli("getnewaddress", "", "bech32")
    out_spk = bytes.fromhex(cli("getaddressinfo", out_addr)["scriptPubKey"])
    res = build_reveal(artifact_hex=st["artifact_hex"], seckey=seckey, commit_txid=st["commit_txid"],
                       commit_vout=int(st["commit_vout"]), commit_value_sats=int(st["commit_value_sats"]),
                       out_spk=out_spk, fee_sats=int(st.get("fee_sats", DEFAULT_FEE)), hrp=hrp)
    res.update({"commit_txid": st["commit_txid"], "out_addr": out_addr})
    if a.broadcast:
        res["reveal_txid"] = cli("sendrawtransaction", res["reveal_hex"])
    print(json.dumps(res, indent=2))


# ----------------------------- offline selftest (no node) -----------------------------
def selftest():
    """OFFLINE proof of build_reveal against a synthetic commit: the reveal witness is
    [schnorr_sig, tapscript, control_block]; the tapscript round-trips to the artifact; the 64-byte
    Schnorr sig verifies under the internal key over the BIP341 script-path sighash; and the commit
    scriptPubKey equals p2tr(tweak(P, tapleaf)) with matching parity. Prints JSON; returns bool.
    (The one thing this can't prove is consensus acceptance — that's the on-node runbook.)"""
    from bitcoin.core import CTransaction
    ARTIFACT_HEX = ("4254583102010040d10c000100e80300000000000080f0fa020000000000ca9a3b0000000000000000"
                    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa00000000160014"
                    "e9dd842d95a053c513315291f4d3f93b5a41059a2102bbfcf90b65934a165af1508d129cd749e764"
                    "3bf75c66bd7f209a15f0b1497d7a8347304402205be5b4425958d1d6e0f8eb67cf4a7a2dc091d5d5"
                    "f1ea08bc776896a03d8bfb3102205e6433b48f725d819e039749bd427299d33e4ba28b4e8ebb231d"
                    "2574dc35577f83")
    seckey = bytes.fromhex("11" * 32)
    commit_value, fee = 100000, 2000
    out_spk = bytes.fromhex("0014" + "22" * 20)
    res = build_reveal(artifact_hex=ARTIFACT_HEX, seckey=seckey, commit_txid="ab" * 32, commit_vout=1,
                       commit_value_sats=commit_value, out_spk=out_spk, fee_sats=fee, hrp="bcrt")
    checks = {}
    tx = CTransaction.deserialize(x(res["reveal_hex"]))
    stack = [bytes(s) for s in tx.wit.vtxinwit[0].scriptWitness.stack]
    checks["witness_three_items"] = (len(stack) == 3)
    sig, ts, cb = stack[0], stack[1], stack[2]
    checks["envelope_roundtrips_to_artifact"] = (carrier.parse_envelope(ts) == bytes.fromhex(ARTIFACT_HEX))
    px = bytes.fromhex(res["internal_xonly_hex"])
    checks["sig_is_64_bytes"] = (len(sig) == 64)
    checks["sig_verifies_under_internal_key"] = T.schnorr_verify(bytes.fromhex(res["sighash_hex"]), px, sig)
    checks["control_block_len_33"] = (len(cb) == 33)
    checks["control_block_carries_internal_key"] = (cb[1:33] == px)
    checks["control_block_leaf_version"] = ((cb[0] & 0xfe) == 0xc0)
    parity, outkey = T.taproot_tweak_pubkey(px, bytes.fromhex(res["tapleaf_hex"]))
    checks["commit_spk_matches_output_key"] = (T.p2tr_scriptpubkey(outkey).hex() == res["commit_scriptPubKey_hex"])
    checks["control_block_parity_matches"] = ((cb[0] & 1) == parity)
    checks["reveal_output_value"] = (tx.vout[0].nValue == commit_value - fee)
    checks["wrong_sighash_rejected"] = (T.schnorr_verify(bytes(32), px, sig) is False)
    allpass = all(checks.values())
    print(json.dumps({"checks": checks, "ALL_PASS": allpass}, indent=2))
    return allpass


def build_parser():
    p = argparse.ArgumentParser(prog="btx_envelope_publish",
                                description="Publish a BTX order via the Taproot witness-envelope carrier")
    sub = p.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("selftest", help="offline proof of build_reveal (no node)")
    st.set_defaults(func=lambda a: sys.exit(0 if selftest() else 1))
    pub = sub.add_parser("publish", help="fund commit + build/broadcast reveal carrying the artifact")
    pub.add_argument("--artifact-hex", required=True, help="BTX artifact hex (from btx_wallet maker-sign)")
    pub.add_argument("--bitcoin-cli", default="bitcoin-cli")
    pub.add_argument("--chain", default="regtest")
    pub.add_argument("--datadir")
    pub.add_argument("--wallet")
    pub.add_argument("--seckey", help="reveal-key hex (default: random ephemeral key)")
    pub.add_argument("--commit-amount-btc", type=float, default=DEFAULT_COMMIT_BTC)
    pub.add_argument("--fee-sats", type=int, default=DEFAULT_FEE)
    pub.add_argument("--out-addr", help="reveal output address (default: a fresh wallet address)")
    pub.add_argument("--state-file", help="JSON file to write the ephemeral reveal key + commit info "
                                          "(0o600) so a crash between commit and reveal is recoverable")
    pub.add_argument("--broadcast", action="store_true")
    pub.add_argument("--dry-run", action="store_true")
    pub.set_defaults(func=cmd_publish)

    rev = sub.add_parser("publish-reveal", help="finish/retry a publish from a saved recovery state "
                                                "(commit was broadcast but the reveal didn't)")
    rev.add_argument("--bitcoin-cli", default="bitcoin-cli")
    rev.add_argument("--chain", default="regtest")
    rev.add_argument("--datadir")
    rev.add_argument("--wallet")
    rev.add_argument("--state-file", help="recovery state written by `publish`")
    rev.add_argument("--seckey", help="reveal-key hex (if not using --state-file)")
    rev.add_argument("--artifact-hex", help="BTX artifact hex (if not using --state-file)")
    rev.add_argument("--commit-txid", help="commit txid (if not using --state-file)")
    rev.add_argument("--commit-vout", type=int, help="commit vout (if not using --state-file)")
    rev.add_argument("--commit-value-sats", type=int, help="commit output value sats (if not using --state-file)")
    rev.add_argument("--fee-sats", type=int, default=DEFAULT_FEE)
    rev.add_argument("--out-addr", help="reveal output address (default: a fresh wallet address)")
    rev.add_argument("--broadcast", action="store_true")
    rev.add_argument("--dry-run", action="store_true")
    rev.set_defaults(func=cmd_publish_reveal)
    return p


def main(argv=None):
    build_parser().parse_args(argv).func(build_parser().parse_args(argv))


if __name__ == "__main__":
    args = build_parser().parse_args()
    args.func(args)
