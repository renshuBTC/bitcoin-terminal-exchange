#!/usr/bin/env python3
"""
btx_etch.py — hand-build a Runes ETCHING (runestone + rune-name commitment) with BTX's own
primitives, so BTX can mint its counter-asset rune on the LATEST Bitcoin Core (v29.1) with NO
ord-wallet dependency. ord is then only a read-only indexer/oracle — fully nothing-offchain.

This module is the PURE encoder (no node, no python-bitcoinlib):
  - rune name <-> number (inverse of btx_runes_decode.rune_name)
  - the etching runestone payload + scriptPubKey bytes
  - the commitment bytes ord requires in the reveal's tapscript
The commit->(6 blocks)->reveal broadcast reuses btx_envelope_publish's BIP341 machinery (driver,
added separately). Verified offline by round-tripping through the runestone-lib-cross-checked decoder
btx_runes_decode (encoder -> decoder -> assert the etching fields survive the round-trip; the decoder
is independently validated against Magic Eden's runestone-lib via btx_runes_xcheck.py).
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import btx_runes_decode as dec

TAG_BODY = 0; TAG_DIVISIBILITY = 1; TAG_FLAGS = 2; TAG_SPACERS = 3; TAG_RUNE = 4
TAG_SYMBOL = 5; TAG_PREMINE = 6; TAG_CAP = 8; TAG_AMOUNT = 10
FLAG_ETCHING = 1 << 0; FLAG_TERMS = 1 << 1; FLAG_TURBO = 1 << 2
OP_RETURN = 0x6a; OP_13 = 0x5d


def leb128(n):
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def rune_number(name):
    """Inverse of btx_runes_decode.rune_name: modified-base-26 NAME (A..Z) -> rune number (u128)."""
    name = name.upper()
    n = 0
    for c in name:
        if not ('A' <= c <= 'Z'):
            raise ValueError(f"rune name must be A-Z only, got {c!r}")
        n = n * 26 + (ord(c) - ord('A') + 1)
    return n - 1


def etching_payload(rune_num, divisibility=0, premine=0, symbol=None, spacers=0, turbo=False, terms=None):
    """Runestone PAYLOAD (the bytes after OP_RETURN OP_13) for an etching."""
    flags = FLAG_ETCHING | (FLAG_TERMS if terms else 0) | (FLAG_TURBO if turbo else 0)
    f = [TAG_FLAGS, flags, TAG_RUNE, rune_num]
    if divisibility:
        f += [TAG_DIVISIBILITY, divisibility]
    if spacers:
        f += [TAG_SPACERS, spacers]
    if symbol is not None:
        f += [TAG_SYMBOL, ord(symbol) if isinstance(symbol, str) else int(symbol)]
    if premine:
        f += [TAG_PREMINE, premine]
    if terms:
        if terms.get("amount") is not None:
            f += [TAG_AMOUNT, terms["amount"]]
        if terms.get("cap") is not None:
            f += [TAG_CAP, terms["cap"]]
    return b''.join(leb128(x) for x in f)


def runestone_spk_bytes(payload):
    """OP_RETURN OP_13 <payload> as raw scriptPubKey bytes."""
    if len(payload) < 76:
        push = bytes([len(payload)]) + payload
    elif len(payload) < 256:
        push = bytes([0x4c, len(payload)]) + payload
    else:
        push = bytes([0x4d]) + len(payload).to_bytes(2, 'little') + payload
    return bytes([OP_RETURN, OP_13]) + push


def rune_commitment(rune_num):
    """Commitment ord requires as a data push in the reveal's tapscript: the rune number as minimal
    little-endian bytes (trailing zero bytes elided). Validated on-node (ord must accept it).
    Bit-exact with ord's Rune::commitment() (ord crates/ordinals/src/rune.rs)."""
    return rune_num.to_bytes(16, 'little').rstrip(b'\x00')


# ----------------------------- rune-name eligibility (ported from ord rune.rs) -----------------------------
# A rune name that is reserved, not yet unlocked at the etch height, or malformed produces a CENOTAPH:
# the etch is mined but mints NOTHING (we hit this live with a duplicate name). These rules let BTX
# refuse a doomed etch up front with a precise reason instead of silently burning the commit. Ported
# verbatim from ord crates/ordinals/src/rune.rs so the gate matches the indexer exactly.
SUBSIDY_HALVING_INTERVAL = 210000
RUNE_UNLOCKED = 12
RUNE_UNLOCK_INTERVAL = SUBSIDY_HALVING_INTERVAL // RUNE_UNLOCKED   # 17500
U128_MAX = (1 << 128) - 1
# RUNE_STEPS[i] == rune number of the all-"A" name of length i+1 (ord rune.rs STEPS). STEPS[26] = RESERVED.
RUNE_STEPS = [
    0, 26, 702, 18278, 475254, 12356630, 321272406, 8353082582, 217180147158, 5646683826134,
    146813779479510, 3817158266467286, 99246114928149462, 2580398988131886038,
    67090373691429037014, 1744349715977154962390, 45353092615406029022166,
    1179180408000556754576342, 30658690608014475618984918, 797125955808376366093607894,
    20725274851017785518433805270, 538857146126462423479278937046, 14010285799288023010461252363222,
    364267430781488598271992561443798, 9470953200318703555071806597538774,
    246244783208286292431866971536008150, 6402364363415443603228541259936211926,
    166461473448801533683942072758341510102,
]
RUNE_RESERVED = RUNE_STEPS[26]   # 6402364363415443603228541259936211926


def first_rune_height(network):
    """Block height at which runes activate, per ord rune.rs::first_rune_height."""
    n = (network or "").lower()
    if n in ("main", "mainnet", "bitcoin"):
        return SUBSIDY_HALVING_INTERVAL * 4    # 840000
    if n == "testnet":
        return SUBSIDY_HALVING_INTERVAL * 12   # 2520000
    return 0                                   # signet, regtest


def minimum_at_height(network, height):
    """Smallest etchable rune NUMBER at `height` (names with a smaller number are not yet unlocked).
    Direct port of ord Rune::minimum_at_height. The minimum decays from a 13-letter floor down to
    Rune(0) ('A') across the halving interval after activation."""
    offset = height + 1
    start = first_rune_height(network)
    end = start + SUBSIDY_HALVING_INTERVAL
    if offset < start:
        return RUNE_STEPS[RUNE_UNLOCKED]
    if offset >= end:
        return 0
    progress = offset - start
    length = RUNE_UNLOCKED - (progress // RUNE_UNLOCK_INTERVAL)
    end_v = RUNE_STEPS[length - 1]
    start_v = RUNE_STEPS[length]
    remainder = progress % RUNE_UNLOCK_INTERVAL
    return start_v - ((start_v - end_v) * remainder // RUNE_UNLOCK_INTERVAL)


def validate_name(name, network, height=None):
    """Pre-flight check that an etch of `name` will actually MINT (not cenotaph). Returns (ok, reason).
    Checks charset, u128 range, the reserved range, and — when `height` is given — that the name is
    unlocked at that height. Does NOT check name-already-etched (that needs an ord lookup; btxd does
    it). Mirrors ord's issuance rules in rune.rs."""
    name = (name or "").upper()
    if not name:
        return False, "empty rune name"
    for c in name:
        if not ('A' <= c <= 'Z'):
            return False, f"rune name must be A-Z only, got {c!r}"
    num = rune_number(name)
    if num > U128_MAX:
        return False, "rune name out of range (exceeds u128 / longer than 'BCGDENLQRQWDSLRUGSNLBTMFIJAV')"
    if num >= RUNE_RESERVED:
        return False, "rune name is in the reserved range (>= 27 letters) and cannot be etched"
    if height is not None:
        minv = minimum_at_height(network, height)
        if num < minv:
            return (False, f"rune name not yet unlocked at height {height} on {network}: it is too short "
                           f"(minimum rune number {minv}); use a longer name")
    return True, "ok"


def selftest():
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))

    # 1) name <-> number round-trip (via the runestone-lib-cross-checked decoder's rune_name)
    for nm in ["A", "Z", "AA", "ZZ", "BTXUSDTESTS", "UNCOMMONGOODS"]:
        rt = dec.rune_name(rune_number(nm))
        check(f"name<->number round-trip: {nm}", rt == nm, f"got {rt}")

    # 2) encoder validated end-to-end against UNCOMMON•GOODS — the Runes protocol-genesis rune (hard-
    # coded in the ord source, not etched by a transaction, so the anchor is against the *protocol
    # constants*). ALL FIVE FIELDS THE CURRENT `etching_payload` ENCODES MATCH UNCOMMON•GOODS'S
    # AUTHORITATIVE VALUES per ord's own docs (`ord/docs/src/guides/api.md` UNCOMMON•GOODS API example):
    # name = "UNCOMMONGOODS" (rune number 0); divisibility = 0; premine = 0; symbol = "⧉" (U+29C9 TWO
    # JOINED SQUARES); spacers = 128 (bit 7, producing the "UNCOMMON•GOODS" display). The DECODER is
    # independently validated against Magic Eden's runestone-lib (btx_runes_xcheck.py: 18 golden
    # vectors), so encoder→decoder→protocol-constants is a real mainnet anchor end-to-end for every
    # field the encoder currently supports. (UNCOMMON•GOODS's `terms` (amount=1, cap=2^128-1,
    # height=[840000,1050000]) and `turbo=true` are NOT encoded by the current `etching_payload`; if/
    # when terms support is added, those values are independently verifiable in the same ord doc.)
    ucg = rune_number("UNCOMMONGOODS")
    payload = etching_payload(ucg, divisibility=0, premine=0, symbol="⧉", spacers=128)
    res = dec.decode_payload(payload)
    et = res.get("etching") if isinstance(res, dict) else None
    check("etch: decodes to an etching", et is not None, f"got {res}")
    if et:
        check("etch: name == UNCOMMONGOODS (UNCOMMON•GOODS protocol value)",
              et.get("name") == "UNCOMMONGOODS", str(et.get("name")))
        check("etch: display == UNCOMMON•GOODS (UNCOMMON•GOODS protocol value)",
              et.get("display_name") == "UNCOMMON•GOODS", str(et.get("display_name")))
        check("etch: divisibility 0 (UNCOMMON•GOODS protocol value)",
              et.get("divisibility") == 0, str(et.get("divisibility")))
        check("etch: premine 0 (UNCOMMON•GOODS protocol value)",
              et.get("premine") == 0, str(et.get("premine")))
        check("etch: spacers 128 (UNCOMMON•GOODS protocol value)",
              et.get("spacers") == 128, str(et.get("spacers")))
        check("etch: symbol ⧉ (UNCOMMON•GOODS protocol value per ord/docs/.../api.md)",
              et.get("symbol") == "⧉", str(et.get("symbol")))

    # 3) our spike rune BTX•USD•TESTS (div 0, premine 100000) round-trips clean
    c = rune_number("BTXUSDTESTS")
    p2 = etching_payload(c, divisibility=0, premine=100000, symbol="$")
    r2 = dec.decode_payload(p2)
    e2 = r2.get("etching") if isinstance(r2, dict) else None
    check("BTXUSDTESTS: name", e2 and e2.get("name") == "BTXUSDTESTS", str(e2))
    check("BTXUSDTESTS: premine 100000", e2 and e2.get("premine") == 100000, str(e2 and e2.get('premine')))
    check("BTXUSDTESTS: divisibility 0", e2 and e2.get("divisibility") == 0)

    # 4) commitment is minimal little-endian (no trailing zero bytes)
    com = rune_commitment(c)
    check("commitment: minimal LE (no trailing zero)", not com or com[-1] != 0, com.hex())
    check("commitment: round-trips to the number",
          int.from_bytes(com, 'little') == c, f"{int.from_bytes(com,'little')} vs {c}")

    # 5) rune-name eligibility, vs ord rune.rs test vectors (crates/ordinals/src/rune.rs)
    check("RESERVED == 27 A's", RUNE_RESERVED == rune_number("A" * 27))
    check("STEPS[i] == ('A'*(i+1))",
          all(RUNE_STEPS[i] == rune_number("A" * (i + 1)) for i in range(len(RUNE_STEPS))))
    check("signet minimum@0 == ZZYZXBRKWXVA",
          dec.rune_name(minimum_at_height("signet", 0)) == "ZZYZXBRKWXVA",
          dec.rune_name(minimum_at_height("signet", 0)))
    check("signet minimum@1 == ZZXZUDIVTVQA",
          dec.rune_name(minimum_at_height("signet", 1)) == "ZZXZUDIVTVQA",
          dec.rune_name(minimum_at_height("signet", 1)))
    check("regtest minimum@0 == ZZYZXBRKWXVA",
          dec.rune_name(minimum_at_height("regtest", 0)) == "ZZYZXBRKWXVA")
    check("late signet minimum decays to A (0)", minimum_at_height("signet", 210000) == 0)
    # validate_name behaviour
    check("valid: long name at late signet height", validate_name("BTXUSDTESTSIGNETA", "signet", 306135)[0])
    check("reject: short name at signet height 0", not validate_name("AB", "signet", 0)[0])
    check("reject: bad charset", not validate_name("AB3", "signet", 0)[0])
    check("reject: reserved (27 letters)", not validate_name("A" * 27, "signet", 100)[0])
    check("no-height: skips the unlock check", validate_name("ABCDEFGHIJKL", "signet", None)[0])
    check("mainnet gate is real (short name rejected at 840000)",
          not validate_name("AAA", "main", 840000)[0])

    print("ALL_PASS" if ok else "FAILURES ABOVE")
    return ok


# ----------------------------- on-node etch (commit -> 6 blocks -> reveal) -----------------------------
# Reuses btx_taproot's BIP341 commit/reveal. The reveal spends the commit via the script path,
# revealing a tapscript `<commitment> OP_DROP <P> OP_CHECKSIG` (ord finds the commitment push and, with
# the commit >=6 confs, accepts the etching), with outputs [premine dest (gets the premined rune by
# default routing), OP_RETURN etching runestone]. Bitcoin imports are LAZY so the pure encoder above
# stays importable without python-bitcoinlib.
def build_etch_reveal(*, seckey, rune_num, commit_txid, commit_vout, commit_value_sats, premine_spk,
                      divisibility=0, premine=0, symbol=None, spacers=0, fee_sats=2000, hrp="bc"):
    import btx_taproot as T
    from bitcoin.core import (b2x, lx, CMutableTransaction, CMutableTxIn, CMutableTxOut, COutPoint,
                              CTxInWitness, CTxWitness)
    from bitcoin.core.script import CScript, CScriptWitness, OP_DROP, OP_CHECKSIG
    px, _ = T.xonly_pubkey(seckey)
    ts_bytes = bytes(CScript([rune_commitment(rune_num), OP_DROP, px, OP_CHECKSIG]))
    commit = T.commit_for_envelope(px, ts_bytes, hrp=hrp)
    commit_spk = bytes.fromhex(commit["commit_scriptPubKey_hex"])
    tapleaf = bytes.fromhex(commit["tapleaf_hex"])
    cb = bytes.fromhex(commit["control_block_hex"])
    rune_spk = runestone_spk_bytes(etching_payload(rune_num, divisibility, premine, symbol, spacers))
    out0 = commit_value_sats - fee_sats
    if out0 <= 0:
        raise ValueError("fee exceeds commit value")
    vout = [(out0, bytes(premine_spk)), (0, rune_spk)]   # idx0 = premine dest (rune by default), idx1 = runestone
    txid_internal = lx(commit_txid)
    txin = CMutableTxIn(COutPoint(txid_internal, commit_vout), nSequence=0xffffffff)
    tx = CMutableTransaction([txin], [CMutableTxOut(v, CScript(spk)) for (v, spk) in vout],
                             nVersion=2, nLockTime=0)
    sighash = T.tap_sighash(version=2, locktime=0,
                            vin=[(bytes(txid_internal), commit_vout, 0xffffffff)],
                            spent_amounts=[commit_value_sats], spent_spks=[commit_spk],
                            vout=vout, input_index=0, hash_type=T.SIGHASH_DEFAULT,
                            ext_flag=1, tapleaf_hash=tapleaf)
    sig = T.schnorr_sign(sighash, seckey)
    tx.wit = CTxWitness([CTxInWitness(CScriptWitness([sig, ts_bytes, cb]))])
    return {"reveal_hex": b2x(tx.serialize()), "commit_address": commit["commit_address"],
            "commit_scriptPubKey_hex": commit["commit_scriptPubKey_hex"], "tapscript_hex": ts_bytes.hex(),
            "rune_runestone_spk_hex": rune_spk.hex(), "tapleaf_hex": commit["tapleaf_hex"],
            "control_block_hex": commit["control_block_hex"], "internal_xonly_hex": px.hex(),
            "sighash_hex": sighash.hex(), "out0_value_sats": out0}


def etch_commit(cli, *, rune_num, seckey, commit_amount_btc, hrp):
    """Fund + broadcast the rune-commitment P2TR. Returns the commit outpoint + value. Chain-agnostic:
    on signet/main the output simply sits in the mempool until a block confirms it (no mining here)."""
    import btx_taproot as T
    from bitcoin.core import COIN
    from bitcoin.core.script import CScript, OP_DROP, OP_CHECKSIG
    px, _ = T.xonly_pubkey(seckey)
    ts_bytes = bytes(CScript([rune_commitment(rune_num), OP_DROP, px, OP_CHECKSIG]))
    commit = T.commit_for_envelope(px, ts_bytes, hrp=hrp)
    commit_txid = cli("sendtoaddress", commit["commit_address"], f"{commit_amount_btc:.8f}")
    raw = cli("getrawtransaction", commit_txid, "true")
    cv, cval = None, None
    for vo in raw["vout"]:
        if vo["scriptPubKey"]["hex"] == commit["commit_scriptPubKey_hex"]:
            cv, cval = vo["n"], int(round(vo["value"] * COIN)); break
    if cv is None:
        sys.exit(f"could not locate commit output in {commit_txid}")
    return {"commit_address": commit["commit_address"], "commit_txid": commit_txid,
            "commit_vout": cv, "commit_value_sats": cval}


def _commit_confirmations(cli, commit_txid):
    """Best-effort confirmation count for the commit tx (0 if still in mempool / unknown)."""
    try:
        raw = cli("getrawtransaction", commit_txid, "true")
        return int(raw.get("confirmations", 0) or 0)
    except Exception:
        return 0


def _do_reveal(cli, st, hrp, *, mine_to=None, broadcast=True):
    """Build (and optionally broadcast) the reveal from etch state `st`. Assumes the commit is mature
    (>=6 confs). On any failure, surface seckey_hex + recovery so the committed funds aren't lost."""
    premine_addr = st.get("premine_addr") or cli("getnewaddress", "", "bech32")
    premine_spk = bytes.fromhex(cli("getaddressinfo", premine_addr)["scriptPubKey"])
    seckey = bytes.fromhex(st["seckey_hex"])
    res = dict(st); res["premine_addr"] = premine_addr
    try:
        res.update(build_etch_reveal(seckey=seckey, rune_num=st["rune_number"],
                                     commit_txid=st["commit_txid"], commit_vout=st["commit_vout"],
                                     commit_value_sats=st["commit_value_sats"], premine_spk=premine_spk,
                                     divisibility=st.get("divisibility", 0), premine=st.get("premine", 0),
                                     symbol=st.get("symbol", "$"), spacers=st.get("spacers", 0),
                                     fee_sats=st.get("fee_sats", 2000), hrp=hrp))
        if broadcast:
            res["reveal_txid"] = cli("sendrawtransaction", res["reveal_hex"])
            if mine_to:
                cli("generatetoaddress", 1, mine_to)
            res["offer_outpoint"] = f"{res['reveal_txid']}:0"
    except Exception as e:
        res["error"] = f"reveal failed after commit was broadcast: {e}"
        res["recovery"] = (f"commit funds are at {st['commit_txid']}:{st['commit_vout']} in a P2TR spendable "
                           f"only by seckey {st['seckey_hex']} — re-run `etch-reveal --state-file <saved> "
                           f"--seckey {st['seckey_hex']}` to retry")
        print(json.dumps(res, indent=2)); sys.exit(1)
    return res


def _etch_state(a, rune_num, seckey, commit):
    """Assemble the resumable etch state (everything etch-reveal needs to finish later)."""
    return {"rune": a.rune, "rune_number": rune_num, "chain": a.chain,
            "commit_txid": commit["commit_txid"], "commit_vout": commit["commit_vout"],
            "commit_value_sats": commit["commit_value_sats"], "commit_address": commit["commit_address"],
            "premine": a.premine, "divisibility": a.divisibility, "symbol": a.symbol, "spacers": a.spacers,
            "fee_sats": a.fee_sats, "premine_addr": a.premine_addr, "seckey_hex": seckey.hex()}


def _lock_rune_utxos(cli, ord_url):
    """Lock every wallet UTXO that ord reports as rune-bearing, so Core's (rune-blind) coin selection
    for the commit-funding `sendtoaddress` can't pull a rune into the commit — which would default-route
    into the etch premine and contaminate the offer (seen live on signet). Needs the ord oracle. Returns
    the count locked. Best-effort: an ord query failure just leaves that UTXO unlocked."""
    import urllib.request, json as _json
    try:
        unspent = cli("listunspent", 0)
    except Exception:
        return 0
    locked = 0
    for u in unspent or []:
        try:
            req = urllib.request.Request(ord_url.rstrip("/") + f"/output/{u['txid']}:{u['vout']}",
                                         headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = _json.loads(r.read().decode())
            if d.get("runes"):
                cli("lockunspent", "false", _json.dumps([{"txid": u["txid"], "vout": u["vout"]}]))
                locked += 1
        except Exception:
            pass
    return locked


def cmd_etch(a):
    """Etch a rune. Regtest: one-shot (mine commit -> 6 maturity blocks -> reveal -> mine) — this is the
    path the GUI button uses. Signet/main: broadcast the commit, then either --wait for >=6 real confs
    and reveal, or print the resumable state so `etch-reveal` can finish once the commit matures."""
    import os as _os, time as _time
    import btx_taproot as T
    from btx_envelope_publish import CLI
    from bitcoin.core.script import CScript, OP_DROP, OP_CHECKSIG
    cli = CLI(a.bitcoin_cli, a.chain, a.datadir, a.wallet, a.dry_run)
    hrp = {"regtest": "bcrt", "signet": "tb", "testnet": "tb", "main": "bc", "mainnet": "bc"}.get(a.chain, "bc")
    # Pre-flight: refuse a name that would cenotaph (reserved / not-yet-unlocked / malformed) BEFORE we
    # spend anything on the commit. Height-aware when we have a live node; charset+reserved otherwise.
    height = None
    if not a.dry_run:
        try:
            height = int(cli("getblockcount"))
        except Exception:
            height = None
    ok, reason = validate_name(a.rune, a.chain, height)
    if not ok:
        sys.exit(f"refusing to etch '{a.rune}': {reason}")
    rune_num = rune_number(a.rune)
    seckey = bytes.fromhex(a.seckey) if a.seckey else _os.urandom(32)
    if a.dry_run:
        px, _ = T.xonly_pubkey(seckey)
        ts_bytes = bytes(CScript([rune_commitment(rune_num), OP_DROP, px, OP_CHECKSIG]))
        commit = T.commit_for_envelope(px, ts_bytes, hrp=hrp)
        print(json.dumps({"rune": a.rune, "rune_number": rune_num, "commit_address": commit["commit_address"],
                          "commitment_hex": rune_commitment(rune_num).hex()}, indent=2)); return
    regtest = (a.chain == "regtest")
    # rune-safety: Core's sendtoaddress is rune-blind, so lock any rune-bearing wallet UTXO first — else
    # coin selection may pull a rune into the commit, where it default-routes into the premine and
    # contaminates the offer. Needs the ord oracle; skipped (with no protection) if --ord-url absent.
    if getattr(a, "ord_url", None):
        n = _lock_rune_utxos(cli, a.ord_url)
        if n:
            print(f"# locked {n} rune-bearing UTXO(s) so the commit funds from rune-free coins", file=sys.stderr)
    # 1) fund + broadcast the commit (chain-agnostic)
    commit = etch_commit(cli, rune_num=rune_num, seckey=seckey, commit_amount_btc=a.commit_amount_btc, hrp=hrp)
    st = _etch_state(a, rune_num, seckey, commit)
    if a.state_file:
        # The state holds the reveal `seckey_hex` (needed to resume the reveal), so it is sensitive key
        # material at rest — the Layer-0 threat model flags this file as a local FS-read path to the
        # ephemeral reveal key. Create it owner-only (0o600) atomically via os.open (mode applies at
        # creation, so there's no world-readable window), and chmod in case the path pre-existed with
        # looser perms. The key stays a Class-B ephemeral key — it controls only the etch commit UTXO,
        # never the wallet — but should not be world-readable on a shared host.
        fd = _os.open(a.state_file, _os.O_WRONLY | _os.O_CREAT | _os.O_TRUNC, 0o600)
        with _os.fdopen(fd, "w") as f:
            json.dump(st, f, indent=2)
        _os.chmod(a.state_file, 0o600)
    if regtest:
        # mine the commit in, mature it (ord requires >=6 confs before the reveal's block), reveal, mine
        mine_to = a.mine_to or cli("getnewaddress", "", "bech32")
        cli("generatetoaddress", 1, mine_to)
        cli("generatetoaddress", 6, mine_to)
        res = _do_reveal(cli, st, hrp, mine_to=mine_to, broadcast=a.broadcast)
        print(json.dumps(res, indent=2)); return
    # signet/main: the commit must reach >=6 confs on REAL blocks before the reveal is valid
    if not a.wait:
        st["next_step"] = ("commit broadcast — once it has >=6 confirmations run: btx_etch.py etch-reveal "
                           f"--state-file {a.state_file or '<state.json>'} --bitcoin-cli {a.bitcoin_cli} "
                           f"--chain {a.chain}" + (f" --wallet {a.wallet}" if a.wallet else "")
                           + (f" --datadir {a.datadir}" if a.datadir else ""))
        st["note"] = "SAVE seckey_hex — the commit funds are spendable only by it"
        print(json.dumps(st, indent=2)); return
    # --wait: poll until the commit matures, then reveal
    deadline = _time.time() + a.wait_timeout
    while _commit_confirmations(cli, commit["commit_txid"]) < 6:
        if _time.time() > deadline:
            st["error"] = (f"timed out after {a.wait_timeout}s waiting for commit maturity "
                           f"({_commit_confirmations(cli, commit['commit_txid'])}/6 confs)")
            st["next_step"] = "re-run `etch-reveal` with the saved state once the commit has >=6 confs"
            print(json.dumps(st, indent=2)); sys.exit(1)
        _time.sleep(a.poll_secs)
    res = _do_reveal(cli, st, hrp, mine_to=None, broadcast=True)
    print(json.dumps(res, indent=2))


def cmd_etch_reveal(a):
    """Finish a deferred etch: broadcast the reveal once the commit has matured (>=6 confs). Reads the
    resumable state from --state-file (preferred) or individual flags. Regtest matures by mining."""
    from btx_envelope_publish import CLI
    cli = CLI(a.bitcoin_cli, a.chain, a.datadir, a.wallet, getattr(a, "dry_run", False))
    hrp = {"regtest": "bcrt", "signet": "tb", "testnet": "tb", "main": "bc", "mainnet": "bc"}.get(a.chain, "bc")
    if a.state_file:
        with open(a.state_file) as f: st = json.load(f)
        if a.seckey: st["seckey_hex"] = a.seckey   # allow an override if state lacks/needs it
    else:
        need = {"seckey": a.seckey, "rune": a.rune, "commit_txid": a.commit_txid,
                "commit_vout": a.commit_vout, "commit_value_sats": a.commit_value_sats}
        missing = [k for k, v in need.items() if v in (None, "")]
        if missing:
            sys.exit("need --state-file, or all of: " + ", ".join("--" + m.replace("_", "-") for m in missing))
        st = {"rune": a.rune, "rune_number": rune_number(a.rune), "chain": a.chain, "seckey_hex": a.seckey,
              "commit_txid": a.commit_txid, "commit_vout": a.commit_vout,
              "commit_value_sats": a.commit_value_sats, "premine": a.premine, "divisibility": a.divisibility,
              "symbol": a.symbol, "spacers": a.spacers, "fee_sats": a.fee_sats, "premine_addr": a.premine_addr}
    regtest = (a.chain == "regtest")
    confs = _commit_confirmations(cli, st["commit_txid"])
    mine_to = None
    if confs < 6:
        if regtest:
            mine_to = a.mine_to or cli("getnewaddress", "", "bech32")
            cli("generatetoaddress", 6 - max(confs, 0), mine_to)
        else:
            sys.exit(f"commit {st['commit_txid']} has {confs}/6 confirmations — wait ~{6 - confs} "
                     f"more blocks and re-run this command")
    res = _do_reveal(cli, st, hrp, mine_to=mine_to, broadcast=True)
    print(json.dumps(res, indent=2))


def _add_etch_common(sp):
    """Etch fields shared by `etch` and `etch-reveal`."""
    sp.add_argument("--premine", type=int, default=1000, help="premine in base units (becomes the offer UTXO balance)")
    sp.add_argument("--divisibility", type=int, default=0)
    sp.add_argument("--symbol", default="$")
    sp.add_argument("--spacers", type=int, default=0)
    sp.add_argument("--bitcoin-cli", default="bitcoin-cli")
    sp.add_argument("--chain", default="regtest")
    sp.add_argument("--datadir")
    sp.add_argument("--wallet")
    sp.add_argument("--seckey", help="reveal-key hex (default random for etch; required for flag-driven reveal)")
    sp.add_argument("--fee-sats", type=int, default=2000)
    sp.add_argument("--premine-addr", help="P2WPKH addr to receive the premine (default: fresh wallet addr)")
    sp.add_argument("--mine-to", help="regtest miner addr (default: fresh wallet addr)")
    sp.add_argument("--state-file", help="JSON file to write (etch) / read (etch-reveal) the resumable etch state")


def _build_parser():
    import argparse
    p = argparse.ArgumentParser(prog="btx_etch", description="Hand-build a Runes etching with BTX primitives")
    sub = p.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("selftest", help="offline encoder proof (round-trip via the runestone-lib-cross-checked decoder)")
    st.set_defaults(func=lambda a: sys.exit(0 if selftest() else 1))
    e = sub.add_parser("etch", help="commit -> maturity -> reveal. regtest: one-shot (mines). signet/main: "
                                    "broadcast commit, then --wait or resume via etch-reveal")
    e.add_argument("--rune", required=True, help="rune name (A-Z), e.g. BTXUSDTESTS")
    _add_etch_common(e)
    e.add_argument("--commit-amount-btc", type=float, default=0.001)
    e.add_argument("--ord-url", help="ord oracle URL; when set, rune-bearing wallet UTXOs are locked "
                                     "before funding the commit so a rune can't contaminate the premine")
    e.add_argument("--broadcast", action="store_true", help="(regtest) broadcast the reveal; non-regtest always broadcasts the reveal it builds")
    e.add_argument("--wait", action="store_true", help="(signet/main) poll until the commit has >=6 confs, then reveal")
    e.add_argument("--wait-timeout", type=int, default=7200, help="max seconds to --wait for commit maturity")
    e.add_argument("--poll-secs", type=int, default=30, help="seconds between maturity polls when --wait")
    e.add_argument("--dry-run", action="store_true")
    e.set_defaults(func=cmd_etch)
    r = sub.add_parser("etch-reveal", help="finish a deferred etch: broadcast the reveal once the commit has matured")
    r.add_argument("--rune", help="rune name (A-Z); only needed if not using --state-file")
    _add_etch_common(r)
    r.add_argument("--commit-txid", help="commit txid (if not using --state-file)")
    r.add_argument("--commit-vout", type=int, help="commit vout (if not using --state-file)")
    r.add_argument("--commit-value-sats", type=int, help="commit output value in sats (if not using --state-file)")
    r.set_defaults(func=cmd_etch_reveal)
    return p


if __name__ == "__main__":
    import argparse
    # default to selftest when no subcommand (keeps `python3 btx_etch.py` = the offline proof)
    if len(sys.argv) == 1:
        sys.exit(0 if selftest() else 1)
    args = _build_parser().parse_args()
    args.func(args)
