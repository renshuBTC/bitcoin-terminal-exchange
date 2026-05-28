#!/usr/bin/env python3
"""
btx_wallet.py — Bitcoin Core wallet integration for BTX maker/taker.

This replaces the deterministic PROTOTYPE seeds used by btx.py / btx_0b.py with REAL wallet
keys. The maker's SINGLE|ANYONECANPAY pre-signature is produced by Bitcoin Core itself
(`signrawtransactionwithwallet` with an explicit sighashtype), and the taker funds + signs with the
wallet too. BTX never sees a private key — it only assembles transactions and asks the node to
sign.

Two layers:
  * Thin RPC over `bitcoin-cli` (subprocess). Configurable chain/datadir/wallet. Only exercised
    against a live node. `--dry-run` prints the commands instead of running them.
  * PURE assembly/parse helpers (no node): build the partial tx the maker signs; lift the maker
    witness out of Core's signed-tx hex; assemble the BTX artifact from real wallet material; build
    the taker swap and transplant the maker witness into the wallet-signed funding tx. These are the
    new, error-prone pieces, and `simulate` proves them OFFLINE by standing in for Core's signer
    with python-bitcoinlib.

Subcommands:
  simulate       OFFLINE proof of the parse/assemble/transplant plumbing (no node)
  maker-sign     on-node: wallet signs the offer → emit BTX artifact (+ carrier)
  taker-fill     on-node: wallet funds+signs a swap from an artifact → emit final tx (+ broadcast)

ON-NODE PREREQS (see BTX-wallet-runbook.md): the offer UTXO must be P2WPKH (bech32). The maker
sig verifies under btx_0b.verify_maker_sig only for a P2WPKH offer whose pubkey is the witness
pubkey — that is the same code path proven in milestone 0a/0b.
"""
import sys, os, json, subprocess, argparse, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import btx_0b as btx
import btx_carrier as carrier
import btx_runes as runes
from bitcoin.core import (COIN, b2x, x, lx, b2lx, CMutableTransaction, CTransaction,
                          CMutableTxIn, CMutableTxOut, COutPoint, CTxInWitness, CTxWitness)
from bitcoin.core.script import CScript, CScriptWitness

SAA = 0x83
SAA_STR = "SINGLE|ANYONECANPAY"      # bitcoin-cli sighashtype string
DEFAULT_FEE = 10000
# BIP125 opt-in RBF: a tx is replaceable if any input has nSequence < 0xfffffffe. We set the TAKER
# FUNDING input to this so a stuck open-order fill can be fee-bumped on a busy mainnet mempool. The
# maker's SINGLE|ANYONECANPAY signature zeroes hashSequence, so it does NOT commit to any input's
# sequence — setting this never invalidates the maker pre-sig. (Mainnet hardening #4.)
RBF_SEQUENCE = 0xfffffffd
MAX_U64 = (1 << 64) - 1


# ----------------------------- thin RPC -----------------------------
class CLI:
    # Bare chain flags (e.g. -signet) are compatible with a datadir bitcoin.conf that sets the chain
    # (e.g. signet=1); -chain=signet on top of that conflicts ("Can use at most one of -signet/-chain").
    _CHAIN_FLAG = {"regtest": "-regtest", "signet": "-signet", "testnet": "-testnet",
                   "test": "-testnet", "testnet4": "-testnet4", "main": "-chain=main",
                   "mainnet": "-chain=main"}

    def __init__(self, cli="bitcoin-cli", chain="regtest", datadir=None, wallet=None, dry=False):
        self.base = [cli, self._CHAIN_FLAG.get(chain, f"-chain={chain}")]
        if datadir:
            self.base.append(f"-datadir={datadir}")
        self.wallet = wallet
        self.dry = dry

    def cmd(self, *args):
        c = list(self.base)
        if self.wallet:
            c.append(f"-rpcwallet={self.wallet}")
        return c + [str(a) for a in args]

    def __call__(self, *args):
        c = self.cmd(*args)
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


# ----------------------------- PURE assembly (offline-testable) -----------------------------
def build_partial_tx(offer_txid, offer_vout, price_sats, payout_spk):
    """The [offer-input, payout-output] partial tx the maker pre-signs with SINGLE|ANYONECANPAY."""
    i0 = CMutableTxIn(COutPoint(lx(offer_txid), offer_vout))
    o0 = CMutableTxOut(price_sats, CScript(bytes(payout_spk)))
    return CMutableTransaction([i0], [o0])


def extract_maker_witness_from_signed_tx(signed_tx_hex, vin=0):
    """Lift input `vin`'s witness = [sig, pubkey] out of the hex that signrawtransactionwithwallet
    returns for the partial tx. Valid for a P2WPKH offer (stack is exactly [sig, pubkey])."""
    tx = CTransaction.deserialize(x(signed_tx_hex))
    stack = list(tx.wit.vtxinwit[vin].scriptWitness.stack)
    if len(stack) < 2:
        raise ValueError("expected [sig, pubkey] witness on the offer input (P2WPKH)")
    sig, pub = bytes(stack[0]), bytes(stack[1])
    if sig and sig[-1] != SAA:
        raise ValueError(f"offer sig sighash byte is 0x{sig[-1]:02x}, expected 0x83 "
                         f"(sign with sighashtype '{SAA_STR}')")
    return sig, pub


def assemble_artifact(offer_txid, offer_vout, price_sats, payout_spk, maker_pub, maker_sig,
                      amount_units=1000, expiry=10**9, group_id=0, rune_block=840000, rune_tx=1):
    """Build the BTX artifact dict from REAL wallet material (same wire shape as btx_0b)."""
    return dict(msg_type=1, side=0, rune_block=rune_block, rune_tx=rune_tx, amount=amount_units,
                price=price_sats, expiry=expiry, group_id=group_id, offer_txid=lx(offer_txid),
                offer_vout=offer_vout, payout_spk=bytes(payout_spk), maker_pubkey=bytes(maker_pub),
                sighash_flag=SAA, maker_sig=bytes(maker_sig))


def build_taker_swap_unsigned(art, offer_amount_sats, fund_txid, fund_vout, fund_amount_sats,
                              taker_change_spk, fee=DEFAULT_FEE):
    """Full swap: [offer-in, funding-in] -> [maker payout (idx0), taker (idx1)] (+ runestone idx2
    when the offer carries a rune). Unsigned; the wallet signs the funding input, then
    transplant_maker_witness() drops in the maker's pre-sig.

    output 0 stays the maker payout, untouched: the maker's SINGLE|ANYONECANPAY signature commits
    exactly to (input0, output0), so the taker may append any further outputs without invalidating
    it. CRITICAL for the asset leg: when the offer UTXO holds a rune, Runes' default routing would
    send that rune to the first non-OP_RETURN output (== output 0, the MAKER) — i.e. the maker would
    keep the rune. So we MUST append a runestone edict moving the full rune balance from the offer
    input to the taker's output (idx 1). No rune -> 2 outputs, byte-identical to the BTC-only path."""
    i0 = CMutableTxIn(COutPoint(art["offer_txid"], art["offer_vout"]))
    i1 = CMutableTxIn(COutPoint(lx(fund_txid), fund_vout), CScript(), RBF_SEQUENCE)  # RBF-signal the fill
    o0 = CMutableTxOut(art["price"], CScript(bytes(art["payout_spk"])))       # idx0: maker payout (SINGLE-committed)
    taker_value = offer_amount_sats + fund_amount_sats - art["price"] - fee
    if taker_value < 546:    # would be dust (and a rune-bearing output must clear the 546-sat floor)
        raise ValueError(f"taker output {taker_value} sats is below the dust floor — funding too small "
                         f"for price {art['price']} + fee {fee} (offer {offer_amount_sats})")
    o1 = CMutableTxOut(taker_value, CScript(bytes(taker_change_spk)))          # idx1: taker (rune dest + change)
    outs = [o0, o1]
    rune_amt = int(art.get("amount", 0) or 0)
    rb, rt = int(art.get("rune_block", 0) or 0), int(art.get("rune_tx", 0) or 0)
    if rune_amt > 0 and (rb or rt):
        # idx2: runestone edicting the full rune balance from the offer input to the taker (output 1)
        outs.append(CMutableTxOut(0, runes.runestone_spk([(rb, rt, rune_amt, 1)])))
    return CMutableTransaction([i0, i1], outs)


def build_batch_taker_swap_unsigned(arts, offer_amounts_sats, fund_txid, fund_vout, fund_amount_sats,
                                    taker_change_spk, fee=DEFAULT_FEE):
    """Roadmap #2: sweep N open asks in ONE taker transaction.

      inputs : offer_0, offer_1, …, offer_{N-1}, funding
      outputs: payout_0, payout_1, …, payout_{N-1}, taker(change + all runes), [runestone]

    Why this is sound under the maker's pre-signature. Each maker signed its offer with
    SIGHASH_SINGLE|ANYONECANPAY (0x83) over a partial tx of [offer@in0, payout@out0]. Under BIP143:
      - ANYONECANPAY zeroes hashPrevouts/hashSequence, so the signature does NOT commit to the OTHER
        inputs — we may pack arbitrarily many sibling offers + funding alongside it.
      - SIGHASH_SINGLE commits input k only to the output at the SAME index k (hashOutputs =
        SHA256d(outputs[k])). The maker signed with hashOutputs = SHA256d(payout). So the pre-sig
        stays valid at ANY final input index k, provided payout_k is placed at output index k.
    Hence the invariant enforced here: offer_k at input index k, payout_k at output index k. The
    funding input goes LAST (its SIGHASH_ALL signature, added by the taker's wallet, commits to the
    whole tx — which is exactly what the taker wants).

    Runes: a rune on an offer input with NO edict default-routes to the first non-OP_RETURN output
    (output 0 = payout_0, the WRONG maker). So we emit one edict per rune-bearing offer moving its
    full balance to the single taker output (index N) — different rune IDs coexist on one output, and
    repeats of the same ID accumulate. BTC-only offers contribute no edict. No rune anywhere -> no
    runestone, byte-identical to a pure-BTC batch."""
    if not arts:
        raise ValueError("batch fill needs at least one offer")
    if len(offer_amounts_sats) != len(arts):
        raise ValueError("offer_amounts_sats must align 1:1 with arts")
    n = len(arts)
    ins = [CMutableTxIn(COutPoint(a["offer_txid"], a["offer_vout"])) for a in arts]
    ins.append(CMutableTxIn(COutPoint(lx(fund_txid), fund_vout), CScript(), RBF_SEQUENCE))  # funding LAST, RBF-signal
    outs = [CMutableTxOut(a["price"], CScript(bytes(a["payout_spk"]))) for a in arts]  # payout_k @ idx k
    total_price = sum(int(a["price"]) for a in arts)
    taker_idx = n                                                          # taker output sits after all payouts
    taker_value = sum(int(x) for x in offer_amounts_sats) + fund_amount_sats - total_price - fee
    if taker_value < 546:
        raise ValueError(f"taker output {taker_value} sats is below the dust floor — funding too "
                         f"small for total price {total_price} + fee {fee}")
    outs.append(CMutableTxOut(taker_value, CScript(bytes(taker_change_spk))))           # idx N: taker
    edicts = []
    for a in arts:
        rune_amt = int(a.get("amount", 0) or 0)
        rb, rt = int(a.get("rune_block", 0) or 0), int(a.get("rune_tx", 0) or 0)
        if rune_amt > 0 and (rb or rt):
            edicts.append((rb, rt, rune_amt, taker_idx))                   # full balance -> taker output
    if edicts:
        outs.append(CMutableTxOut(0, runes.runestone_spk(edicts)))         # idx N+1: runestone
    return CMutableTransaction(ins, outs)


# ----------------------------- rune oracle (Asset Layer Adapter, ord-backed) -----------------------------
# ord is a local, chain-derived index (nothing offchain). It keys an output's runes by SPACED NAME, so
# we resolve rune_id -> name via /rune/<id>, then read the Pile.amount (raw base-unit integer, the same
# unit BTX's edict uses) from /output/<outpoint>.runes[name]. Shapes confirmed against ord 0.27.1:
#   GET /rune/<block>:<tx>     -> {"entry":{"spaced_rune":"A•B","divisibility":0,...},"id":"1:0",...}
#   GET /output/<txid>:<vout>  -> {...,"runes":{"A•B":{"amount":N,"divisibility":d,"symbol":"x"}},"spent":bool}
def _rune_name_from_entry(rune_json):
    entry = rune_json.get("entry", rune_json) if isinstance(rune_json, dict) else {}
    return entry.get("spaced_rune") or entry.get("rune")


def _output_rune_amount(output_json, name):
    """Base-unit amount of rune `name` held by the output JSON (0 if absent/spent)."""
    pile = (output_json.get("runes") or {}).get(name) if isinstance(output_json, dict) else None
    if pile is None:
        return 0
    if isinstance(pile, dict):
        return int(pile.get("amount", 0))
    if isinstance(pile, (list, tuple)) and pile:           # tolerate [amount, ...] shape
        return int(pile[0])
    return int(pile)                                       # tolerate a bare integer


def _ord_get(ord_url, path):
    req = urllib.request.Request(ord_url.rstrip("/") + path, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def ord_output_has_runes(ord_url, outpoint):
    """True if `ord` reports ANY rune on this output. Used to keep rune-bearing UTXOs out of swap
    FUNDING — a rune on the funding input has no edict and would default-route to the maker (output 0).
    Fail-safe: if the query fails, return True (treat as unsafe) rather than risk spending a rune."""
    try:
        out = _ord_get(ord_url, f"/output/{outpoint}")
    except Exception:
        return True
    return bool(out.get("runes")) if isinstance(out, dict) else True


def ord_rune_balance(ord_url):
    """Return a `balance_lookup(outpoint, rune_id) -> int` (base units) backed by a local `ord server`."""
    def lookup(outpoint, rune_id):
        try:
            rune_json = _ord_get(ord_url, f"/rune/{rune_id}")
        except Exception as e:
            raise RuntimeError(f"ord rune lookup failed for {rune_id} at {ord_url} — is the rune "
                               f"indexed (ord --index-runes) and the server reachable? ({e})")
        name = _rune_name_from_entry(rune_json)
        if not name:
            raise RuntimeError(f"ord returned no name for rune {rune_id}")
        try:
            out_json = _ord_get(ord_url, f"/output/{outpoint}")
        except Exception as e:
            raise RuntimeError(f"ord output lookup failed for {outpoint} at {ord_url} ({e})")
        return _output_rune_amount(out_json, name)
    return lookup


def assert_offer_backs_rune(balance_lookup, offer_txid, offer_vout, rune_id, amount):
    """Validate-before-advertise (Asset Layer Adapter): refuse to publish a rune order unless the
    offer UTXO holds EXACTLY `amount` base units of `rune_id`.

    `balance_lookup(outpoint, rune_id) -> int` is the rune oracle — an `ord` query on a live node
    (Bitcoin Core does not track runes), or a stub in tests. The "exactly" invariant is load-bearing:
    the settlement edict moves `amount`, so if the offer UTXO held MORE, the remainder would default
    to output 0 (the maker); if it held LESS, the taker's fill can't be honored. Raises ValueError on
    mismatch so a maker can never sign an order they can't back."""
    held = int(balance_lookup(f"{offer_txid}:{offer_vout}", rune_id))
    if held != int(amount):
        raise ValueError(
            f"offer UTXO {offer_txid}:{offer_vout} holds {held} units of rune {rune_id}, but the "
            f"order advertises {amount} — refusing to publish an unbacked order (need EXACTLY {amount})")
    return True


def transplant_maker_witness(wallet_signed_tx_hex, art, offer_vin=0, fund_vin=1):
    """Take Core's signed swap (funding input signed, offer input empty) and transplant the maker's
    pre-signed witness into the offer input. Returns final broadcastable tx hex."""
    tx = CTransaction.deserialize(x(wallet_signed_tx_hex))
    n_in = len(tx.vin)
    w = [None] * n_in
    w[offer_vin] = CTxInWitness(CScriptWitness([art["maker_sig"], art["maker_pubkey"]]))
    # keep whatever the wallet produced for the funding input
    fund_w = tx.wit.vtxinwit[fund_vin] if fund_vin < len(tx.wit.vtxinwit) else CTxInWitness()
    w[fund_vin] = fund_w
    for i in range(n_in):
        if w[i] is None:
            w[i] = (tx.wit.vtxinwit[i] if i < len(tx.wit.vtxinwit) else CTxInWitness())
    mtx = CMutableTransaction.from_tx(tx)
    mtx.wit = CTxWitness(w)
    return b2x(mtx.serialize())


def transplant_maker_witnesses(wallet_signed_tx_hex, arts):
    """Batch variant of transplant_maker_witness: offer inputs occupy indices 0..N-1 (one per art, in
    order), funding input(s) follow. Drop each maker's pre-signed witness into its offer input and keep
    whatever the wallet produced for the trailing funding input(s)."""
    tx = CTransaction.deserialize(x(wallet_signed_tx_hex))
    n_in = len(tx.vin)
    n = len(arts)
    w = []
    for i in range(n_in):
        if i < n:
            w.append(CTxInWitness(CScriptWitness([arts[i]["maker_sig"], arts[i]["maker_pubkey"]])))
        else:
            w.append(tx.wit.vtxinwit[i] if i < len(tx.wit.vtxinwit) else CTxInWitness())
    mtx = CMutableTransaction.from_tx(tx)
    mtx.wit = CTxWitness(w)
    return b2x(mtx.serialize())


# ----------------------------- on-node commands -----------------------------
def _pick_p2wpkh_utxo(unspent, want_sats=None, exclude=None, reject=None, allow_taproot=False):
    """Pick the smallest spendable wallet UTXO >= want_sats, never one in `exclude`, and (lazily,
    cheapest-first) never one for which `reject(outpoint)` is true. `reject` is the rune-safety hook:
    swap FUNDING must not carry a rune (a rune on the funding input would default-route to the maker).

    Eligibility: P2WPKH (scriptPubKey `0014…`) always. With `allow_taproot=True`, P2TR (`5120…`) too —
    Bitcoin Core signs both, so FUNDING inputs may be either, but the OFFER must stay P2WPKH (the maker
    pre-sig path in btx_0b.verify_maker_sig is P2WPKH-specific), so offer-selection leaves this off.
    Taproot is the modern Core change default, so funding must accept it or wallets with taproot change
    can't fund a swap even when they hold plenty of rune-free BTC."""
    exclude = exclude or set()
    def eligible(u):
        spk = u.get("scriptPubKey", "")
        return spk.startswith("0014") or (allow_taproot and spk.startswith("5120"))
    pool = [u for u in unspent if eligible(u) and f"{u['txid']}:{u['vout']}" not in exclude]
    if want_sats is not None:
        pool = [u for u in pool if int(round(u["amount"] * COIN)) >= want_sats]
    pool.sort(key=lambda u: u["amount"])
    for u in pool:                          # cheapest first; only query `reject` until one passes
        if reject is None or not reject(f"{u['txid']}:{u['vout']}"):
            return u
    return None


def cmd_maker_sign(a):
    cli = CLI(a.bitcoin_cli, a.chain, a.datadir, a.wallet, a.dry_run)
    price = int(round(a.price_btc * COIN)) if a.price_btc is not None else a.price_sats
    # mainnet hardening #7: the BTX artifact serializes `amount` and `price` as u64. A rune with a very
    # large supply at high divisibility could exceed u64::MAX; reject rather than silently truncate
    # (the Rust + Python parsers both read u64, so a truncated value would desync them).
    if a.amount_units is not None and int(a.amount_units) > MAX_U64:
        sys.exit(f"amount {a.amount_units} exceeds u64::MAX ({MAX_U64}); BTX artifacts store amount as u64")
    if price is not None and int(price) > MAX_U64:
        sys.exit(f"price {price} sats exceeds u64::MAX ({MAX_U64})")
    # The maker payout is output 0 of every fill (committed by the 0x83 sig). If the price is below the
    # dust floor that output is dust -> the fill tx is non-standard -> the order can NEVER be filled
    # (and the announce fee is wasted). Reject up front. 546 is the conservative cross-script floor
    # (P2PKH 546 > P2WPKH 294 / P2TR 330), and it matches the taker-output floor the builders enforce.
    if not price or int(price) < 546:
        sys.exit(f"price {price} sats is below the 546-sat dust floor — the maker payout (output 0) "
                 f"would be dust and every fill non-standard / un-fillable")
    # 1) pick the offer UTXO
    if a.offer_txid:
        offer = {"txid": a.offer_txid, "vout": a.offer_vout}
        info = cli("gettxout", a.offer_txid, a.offer_vout) if not a.dry_run else None
        offer_amt = int(round(info["value"] * COIN)) if info else a.offer_amount_sats
        offer_spk = info["scriptPubKey"]["hex"] if info else None
    else:
        unspent = cli("listunspent", 1) or []
        u = _pick_p2wpkh_utxo(unspent, want_sats=price) if unspent else None
        if u is None and not a.dry_run:
            sys.exit("no spendable P2WPKH UTXO found to use as the offer")
        offer = {"txid": u["txid"], "vout": u["vout"]} if u else {"txid": "<offer>", "vout": 0}
        offer_amt = int(round(u["amount"] * COIN)) if u else None
        offer_spk = u.get("scriptPubKey") if u else None
    # 1b) RESERVE the offer UTXO in the wallet. The offer is what's being sold; it must stay UNSPENT
    #     while the order is open. Without this, `fundrawtransaction` (carrier, or any later tx) can
    #     pick the offer UTXO to pay a fee and spend it out from under the order — the indexer then
    #     rejects the order because `gettxout(offer)` is null (verified on-node 2026-05-23). Locking
    #     keeps wallet coin-selection off the offer until you cancel (`lockunspent true [outpoint]`).
    offer_locked = False
    if not a.dry_run and not a.no_lock_offer and offer["txid"] != "<offer>":
        try:
            cli("lockunspent", "false", json.dumps([{"txid": offer["txid"], "vout": offer["vout"]}]))
            offer_locked = True
        except RuntimeError:
            offer_locked = False  # best-effort; surfaced in output so the maker can lock manually
    # 2) payout address (where the maker receives the BTC proceeds)
    payout_addr = a.payout_addr or (cli("getnewaddress", "", "bech32") if not a.dry_run else "<payout>")
    payout_spk = (bytes.fromhex(cli("getaddressinfo", payout_addr)["scriptPubKey"])
                  if not a.dry_run else b"\x00\x14" + b"\x00" * 20)
    # 3) build partial tx and ask the WALLET to sign with SINGLE|ANYONECANPAY
    partial = build_partial_tx(offer["txid"], offer["vout"], price, payout_spk)
    partial_hex = b2x(partial.serialize())
    signed = cli("signrawtransactionwithwallet", partial_hex, "[]", SAA_STR)
    if a.dry_run:
        print("\n# next: extract witness from signed['hex'], assemble artifact, publish carrier")
        return
    sig, pub = extract_maker_witness_from_signed_tx(signed["hex"])
    # validate-before-advertise: a rune order must be backed by the offer UTXO actually holding the
    # rune. Bitcoin Core can't tell us rune balances, so this needs the `ord` oracle (wired in the
    # Phase 5 regtest spike). Until then: honor --require-rune-backing by erroring, else warn loudly.
    rune_id = f"{a.rune_block}:{a.rune_tx}"
    if a.amount_units and a.amount_units > 0 and (a.rune_block or a.rune_tx):
        oracle = ord_rune_balance(a.ord_url) if getattr(a, "ord_url", None) else None
        if oracle is not None:
            # refuses (SystemExit-style) if the offer UTXO doesn't hold EXACTLY amount_units of the rune
            assert_offer_backs_rune(oracle, offer["txid"], offer["vout"], rune_id, a.amount_units)
        elif getattr(a, "require_rune_backing", False):
            sys.exit(f"--require-rune-backing set but no --ord-url given — cannot confirm offer "
                     f"{offer['txid']}:{offer['vout']} holds {a.amount_units} of {rune_id}")
        else:
            print(f"# WARNING: rune backing for {rune_id} is NOT verified (no --ord-url). Publishing "
                  f"anyway, but a taker's fill will fail unless the offer UTXO truly holds exactly "
                  f"{a.amount_units} units. Pass --ord-url http://127.0.0.1:<port> to verify.",
                  file=sys.stderr)
    art = assemble_artifact(offer["txid"], offer["vout"], price, payout_spk, pub, sig,
                            amount_units=a.amount_units, expiry=a.expiry, group_id=a.group_id,
                            rune_block=a.rune_block, rune_tx=a.rune_tx)
    blob = btx.serialize_artifact(art)
    ok = btx.verify_maker_sig(btx.parse_artifact(blob), offer_amt) if offer_amt else None
    out = {"artifact_hex": b2x(blob), "artifact_bytes": len(blob),
           "offer_outpoint": f"{offer['txid']}:{offer['vout']}", "offer_amount_sats": offer_amt,
           "payout_addr": payout_addr, "maker_sig_self_verifies": ok, "offer_locked": offer_locked,
           "carrier_op_return_spk_hex": b2x(carrier.op_return_carrier(blob))}
    if a.carrier == "envelope":
        ts = carrier.envelope_tapscript(blob)
        out["envelope_tapscript_hex"] = b2x(bytes(ts))
        out["envelope_tapleaf_hex"] = carrier.tapleaf_hash(ts).hex()
    print(json.dumps(out, default=str, indent=2))


def cmd_taker_fill(a):
    cli = CLI(a.bitcoin_cli, a.chain, a.datadir, a.wallet, a.dry_run)
    art = btx.parse_artifact(bytes.fromhex(a.artifact_hex))
    offer_op = f"{b2lx(art['offer_txid'])}:{art['offer_vout']}"
    info = cli("gettxout", b2lx(art["offer_txid"]), art["offer_vout"]) if not a.dry_run else None
    offer_amt = int(round(info["value"] * COIN)) if info else a.offer_amount_sats
    # Bind the maker pubkey to the offer UTXO's scriptPubKey (from the SAME gettxout) — not just verify
    # the sig against the artifact-supplied key. Without this, a forged artifact over someone else's
    # P2WPKH UTXO verifies cryptographically but is unfillable; refusing here avoids a wasted fill.
    offer_spk = bytes.fromhex(info["scriptPubKey"]["hex"]) if info else None
    if not a.dry_run and offer_amt and not btx.verify_maker_sig(art, offer_amt, offer_spk):
        sys.exit(f"maker sig does NOT verify / pubkey not bound to offer UTXO {offer_op} @ {offer_amt} sats — refusing")
    # pick funding UTXO + change address. CRITICAL: the funding input must NOT carry a rune — a rune
    # on it has no edict in our runestone and would default-route to the maker (output 0). With an ord
    # oracle we exclude rune-bearing candidates; without one we can't tell, so we warn loudly.
    fee = getattr(a, "fee_sats", None) or DEFAULT_FEE
    unspent = cli("listunspent", 1) or []
    need = art["price"] + fee
    reject = None
    if getattr(a, "ord_url", None):
        reject = lambda op: ord_output_has_runes(a.ord_url, op)
    elif not a.dry_run:
        print("# WARNING: funding UTXOs are NOT checked for runes (no --ord-url). If your wallet holds "
              "runes, lock them first or pass --ord-url, or a rune on the funding input is lost to the "
              "maker.", file=sys.stderr)
    fu = _pick_p2wpkh_utxo(unspent, want_sats=need, exclude={offer_op}, reject=reject, allow_taproot=True) if unspent else None
    if fu is None and not a.dry_run:
        sys.exit("no spendable rune-free funding UTXO large enough for price + fee")
    fund_amt = int(round(fu["amount"] * COIN)) if fu else a.fund_amount_sats
    change_addr = a.change_addr or (cli("getnewaddress", "", "bech32") if not a.dry_run else "<change>")
    change_spk = (bytes.fromhex(cli("getaddressinfo", change_addr)["scriptPubKey"])
                  if not a.dry_run else b"\x00\x14" + b"\x11" * 20)
    unsigned = build_taker_swap_unsigned(
        art, offer_amt or 0, fu["txid"] if fu else "<fund>", fu["vout"] if fu else 0,
        fund_amt or 0, change_spk, fee=fee)
    unsigned_hex = b2x(unsigned.serialize())
    signed = cli("signrawtransactionwithwallet", unsigned_hex)
    if a.dry_run:
        print("\n# next: transplant maker witness into input0, then sendrawtransaction")
        return
    final_hex = transplant_maker_witness(signed["hex"], art)
    out = {"final_tx_hex": final_hex, "offer_outpoint": offer_op,
           "committed_payout_sats": art["price"], "funding_outpoint": f"{fu['txid']}:{fu['vout']}"}
    if a.broadcast:
        out["txid"] = cli("sendrawtransaction", final_hex)
    print(json.dumps(out, default=str, indent=2))


def cmd_batch_fill(a):
    """Roadmap #2: fill several open asks in ONE transaction. Each maker's 0x83 pre-sig commits only to
    its own (offer_k -> payout_k) leg, so we can pack N of them plus one funding input. Cheaper per fill
    (one tx, one fee) and atomic (all legs settle together or none do)."""
    cli = CLI(a.bitcoin_cli, a.chain, a.datadir, a.wallet, a.dry_run)
    arts = [btx.parse_artifact(bytes.fromhex(h)) for h in a.artifact_hex]
    if not arts:
        sys.exit("batch-fill needs at least one --artifact-hex")
    offer_ops, offer_amts = [], []
    for art in arts:
        op = f"{b2lx(art['offer_txid'])}:{art['offer_vout']}"
        offer_ops.append(op)
        info = cli("gettxout", b2lx(art["offer_txid"]), art["offer_vout"]) if not a.dry_run else None
        amt = int(round(info["value"] * COIN)) if info else (a.offer_amount_sats or 0)
        offer_amts.append(amt)
        ospk = bytes.fromhex(info["scriptPubKey"]["hex"]) if info else None
        # verify each maker pre-sig at its own (offer@0/payout@0) partial — position-independent under
        # SINGLE|ANYONECANPAY, so a per-offer check is sufficient before we place it at input index k.
        # Bind the maker pubkey to the offer UTXO's spk (from gettxout) so a forged artifact over an
        # unrelated UTXO can't smuggle an unfillable leg into the batch.
        if not a.dry_run and amt and not btx.verify_maker_sig(art, amt, ospk):
            sys.exit(f"maker sig does NOT verify / pubkey not bound to offer UTXO {op} @ {amt} sats — refusing batch")
    # a duplicate offer outpoint would mean two inputs spending the same UTXO — reject early
    if len(set(offer_ops)) != len(offer_ops):
        sys.exit(f"duplicate offer in batch: {offer_ops}")
    # fee scales with the batch: roughly one extra input+output per added offer vs. a single fill.
    fee = (getattr(a, "fee_sats", None) or DEFAULT_FEE) * len(arts)
    total_price = sum(int(art["price"]) for art in arts)
    need = total_price + fee
    reject = None
    if getattr(a, "ord_url", None):
        reject = lambda op: ord_output_has_runes(a.ord_url, op)
    elif not a.dry_run:
        print("# WARNING: funding UTXO is NOT checked for runes (no --ord-url). A rune on the funding "
              "input is lost to maker 0.", file=sys.stderr)
    unspent = cli("listunspent", 1) or []
    fu = _pick_p2wpkh_utxo(unspent, want_sats=need, exclude=set(offer_ops), reject=reject,
                           allow_taproot=True) if unspent else None
    if fu is None and not a.dry_run:
        sys.exit(f"no spendable rune-free funding UTXO large enough for total price {total_price} + "
                 f"fee {fee} ({need} sats)")
    fund_amt = int(round(fu["amount"] * COIN)) if fu else (a.fund_amount_sats or 0)
    change_addr = a.change_addr or (cli("getnewaddress", "", "bech32") if not a.dry_run else "<change>")
    change_spk = (bytes.fromhex(cli("getaddressinfo", change_addr)["scriptPubKey"])
                  if not a.dry_run else b"\x00\x14" + b"\x11" * 20)
    fund_txid = fu["txid"] if fu else "00" * 32      # valid placeholder hex for the dry-run path
    fund_vout = fu["vout"] if fu else 0
    unsigned = build_batch_taker_swap_unsigned(
        arts, offer_amts, fund_txid, fund_vout, fund_amt, change_spk, fee=fee)
    unsigned_hex = b2x(unsigned.serialize())
    signed = cli("signrawtransactionwithwallet", unsigned_hex)
    if a.dry_run:
        print(f"\n# next: transplant {len(arts)} maker witnesses into inputs 0..{len(arts)-1}, "
              f"then sendrawtransaction")
        return
    final_hex = transplant_maker_witnesses(signed["hex"], arts)
    out = {"final_tx_hex": final_hex, "n_offers": len(arts), "offer_outpoints": offer_ops,
           "committed_payout_sats_total": total_price, "fee_sats": fee,
           "funding_outpoint": f"{fu['txid']}:{fu['vout']}"}
    if a.broadcast:
        out["txid"] = cli("sendrawtransaction", final_hex)
    print(json.dumps(out, default=str, indent=2))


# ----------------------------- addressed (snipe-resistant) swaps -----------------------------
# Opt-in alternative to the open 0x83 order, for OTC / large trades. The maker signs SIGHASH_ALL over
# the WHOLE completed swap (not just input0+output0), so no third party can substitute a different
# taker in the mempool — Light Pools' anti-sniping property (see BTX-frontrunning-threat-model.md).
# The cost is interactivity: the maker can't pre-sign, so this is a two-message PSBT (BIP-174)
# handshake, with the PSBT exchanged out-of-band (no BTX relay/server):
#   1. taker `addressed-propose`     -> builds the full swap, signs its funding input, emits a PSBT
#   2. maker `addressed-countersign` -> verifies output 0 == agreed price, signs the offer input, broadcasts
def verify_addressed_tx(decoded_tx, offer_txid, offer_vout, price_sats, payout_spk_hex=None):
    """Maker-side check that a decoded PSBT's tx matches the agreed deal before countersigning.
    Pure (no node) so it is unit-testable. Returns (ok, reason)."""
    vin = decoded_tx.get("vin", []) if isinstance(decoded_tx, dict) else []
    vout = decoded_tx.get("vout", []) if isinstance(decoded_tx, dict) else []
    if not vin or vin[0].get("txid") != offer_txid or int(vin[0].get("vout", -1)) != int(offer_vout):
        got = f"{vin[0].get('txid')}:{vin[0].get('vout')}" if vin else "<none>"
        return False, f"input 0 is {got}, not the agreed offer {offer_txid}:{offer_vout}"
    if not vout:
        return False, "transaction has no outputs"
    o0 = vout[0]
    got_sats = int(round(float(o0.get("value", 0)) * COIN))
    if got_sats != int(price_sats):
        return False, f"output 0 pays {got_sats} sats, but the agreed price is {price_sats}"
    if payout_spk_hex:
        spk = (o0.get("scriptPubKey") or {}).get("hex")
        if spk != payout_spk_hex:
            return False, f"output 0 scriptPubKey {spk} is not the maker payout {payout_spk_hex}"
    return True, "ok"


def cmd_addressed_propose(a):
    cli = CLI(a.bitcoin_cli, a.chain, a.datadir, a.wallet, a.dry_run)
    price = int(round(a.price_btc * COIN)) if a.price_btc is not None else a.price_sats
    if price is None:
        sys.exit("need --price-btc or --price-sats")
    if int(price) < 546:   # output 0 (maker payout) would be dust -> non-standard / un-fillable
        sys.exit(f"price {price} sats is below the 546-sat dust floor (maker payout output would be dust)")
    fee = getattr(a, "fee_sats", None) or DEFAULT_FEE
    # the maker's offer is public; pull its amount + confirm it exists
    info = cli("gettxout", a.offer_txid, a.offer_vout) if not a.dry_run else None
    offer_amt = int(round(info["value"] * COIN)) if info else a.offer_amount_sats
    if not a.dry_run and info is None:
        sys.exit(f"offer {a.offer_txid}:{a.offer_vout} is unspent-set-missing (spent or wrong vout)")
    # taker self-protection: confirm via ord that the offer actually backs the rune before we fund it
    rune_id = f"{a.rune_block}:{a.rune_tx}"
    if not a.dry_run and a.amount_units and a.amount_units > 0 and (a.rune_block or a.rune_tx):
        if getattr(a, "ord_url", None):
            assert_offer_backs_rune(ord_rune_balance(a.ord_url), a.offer_txid, a.offer_vout,
                                    rune_id, a.amount_units)
        else:
            print("# WARNING: offer rune backing NOT verified (no --ord-url) — you may be paying for a "
                  "rune the offer doesn't hold.", file=sys.stderr)
    # maker payout script (the address the maker told you to pay) — validateaddress works for any addr
    payout_spk = (bytes.fromhex(cli("validateaddress", a.maker_addr)["scriptPubKey"])
                  if not a.dry_run else b"\x00\x14" + b"\x00" * 20)
    # pick rune-free funding to cover price + fee; never the offer, never a rune-bearing UTXO
    offer_op = f"{a.offer_txid}:{a.offer_vout}"
    reject = (lambda op: ord_output_has_runes(a.ord_url, op)) if getattr(a, "ord_url", None) else None
    unspent = cli("listunspent", 1) if not a.dry_run else []
    fu = _pick_p2wpkh_utxo(unspent, want_sats=price + fee, exclude={offer_op}, reject=reject, allow_taproot=True) if unspent else None
    if fu is None and not a.dry_run:
        sys.exit("no spendable rune-free funding UTXO large enough for price + fee")
    fund_amt = int(round(fu["amount"] * COIN)) if fu else a.fund_amount_sats
    recv_addr = a.taker_addr or (cli("getnewaddress", "", "bech32") if not a.dry_run else "<taker>")
    recv_spk = (bytes.fromhex(cli("getaddressinfo", recv_addr)["scriptPubKey"])
                if not a.dry_run else b"\x00\x14" + b"\x11" * 20)
    art = dict(offer_txid=lx(a.offer_txid), offer_vout=a.offer_vout, price=price, payout_spk=payout_spk,
               amount=a.amount_units, rune_block=a.rune_block, rune_tx=a.rune_tx)
    fund_txid = fu["txid"] if fu else "00" * 32       # valid placeholder hex for the dry-run path
    fund_vout = fu["vout"] if fu else 0
    unsigned = build_taker_swap_unsigned(art, offer_amt or 0, fund_txid, fund_vout,
                                         fund_amt or 0, recv_spk, fee=fee)
    unsigned_hex = b2x(unsigned.serialize())
    if a.dry_run:
        print(json.dumps({"unsigned_tx_hex": unsigned_hex,
                          "note": "dry-run: converttopsbt + walletprocesspsbt(SIGHASH_ALL) happen on-node"},
                         indent=2)); return
    # BIP-174: raw tx -> PSBT -> taker signs ITS funding input with SIGHASH_ALL (offer input stays open)
    psbt = cli("converttopsbt", unsigned_hex)
    proc = cli("walletprocesspsbt", psbt, "true", "ALL")
    print(json.dumps({
        "psbt": proc["psbt"], "taker_complete": proc.get("complete", False),
        "send_to_maker": "give this PSBT to the maker; they verify output 0 then countersign + broadcast",
        "deal": {"offer_outpoint": offer_op, "price_sats": price, "maker_addr": a.maker_addr,
                 "rune_id": rune_id, "amount_units": a.amount_units, "taker_receive_addr": recv_addr,
                 "funding_outpoint": f"{fu['txid']}:{fu['vout']}"},
        "snipe_resistant": "maker will sign SIGHASH_ALL over this exact tx — no substitution possible",
    }, default=str, indent=2))


def cmd_addressed_countersign(a):
    cli = CLI(a.bitcoin_cli, a.chain, a.datadir, a.wallet, a.dry_run)
    price = int(round(a.expect_price_btc * COIN)) if a.expect_price_btc is not None else a.expect_price_sats
    if price is None:
        sys.exit("need --expect-price-btc or --expect-price-sats (the price you agreed to receive)")
    dec = cli("decodepsbt", a.psbt)
    tx = dec["tx"]
    # verify output 0 pays the agreed price to the maker before signing anything
    payout_spk_hex = None
    if a.expect_maker_addr and not a.dry_run:
        payout_spk_hex = cli("validateaddress", a.expect_maker_addr)["scriptPubKey"]
    ok, reason = verify_addressed_tx(tx, a.offer_txid, a.offer_vout, price, payout_spk_hex)
    if not ok:
        sys.exit(f"refusing to countersign: {reason}")
    if a.dry_run:
        print(json.dumps({"verified": True, "would_sign": f"{a.offer_txid}:{a.offer_vout}",
                          "price_sats": price}, indent=2)); return
    # maker signs the offer input with SIGHASH_ALL -> commits to the WHOLE tx -> snipe-resistant
    proc = cli("walletprocesspsbt", a.psbt, "true", "ALL")
    fin = cli("finalizepsbt", proc["psbt"], "true")
    out = {"verified": True, "complete": fin.get("complete", False)}
    if not fin.get("complete"):
        out["psbt"] = proc["psbt"]
        out["note"] = "not fully signed yet (taker input may be unsigned) — return this PSBT to the taker"
    else:
        out["final_tx_hex"] = fin["hex"]
        if a.broadcast:
            out["txid"] = cli("sendrawtransaction", fin["hex"])
    print(json.dumps(out, default=str, indent=2))


# ----------------------------- rune<->rune addressed swaps (roadmap #4) -----------------------------
# A maker sells rune A for the taker's rune B. This MUST be addressed (SIGHASH_ALL): the maker has to
# commit to BOTH the runestone that routes rune B to them AND their receiving output, which
# SIGHASH_SINGLE cannot do (see btx_rune_swap.py). Same two-message PSBT handshake as above.
def _pick_rune_utxo(unspent, ord_url, rune_id, want_amount, min_sats=0, exclude=None):
    """Find a wallet UTXO holding >= want_amount base units of `rune_id` (and >= min_sats), via the ord
    oracle. Returns the utxo dict or None. Used to locate the taker's counter-rune funding input."""
    exclude = exclude or set()
    lookup = ord_rune_balance(ord_url)
    for u in unspent:
        op = f"{u['txid']}:{u['vout']}"
        if op in exclude or int(round(u["amount"] * COIN)) < min_sats:
            continue
        try:
            if lookup(op, rune_id) >= int(want_amount):
                return u
        except Exception:
            continue
    return None


def cmd_addressed_rune_propose(a):
    import btx_rune_swap as RS
    cli = CLI(a.bitcoin_cli, a.chain, a.datadir, a.wallet, a.dry_run)
    rune_a = f"{a.rune_a_block}:{a.rune_a_tx}"     # offered (maker sells)
    rune_b = f"{a.rune_b_block}:{a.rune_b_tx}"     # counter (taker pays)
    fee = getattr(a, "fee_sats", None) or DEFAULT_FEE
    info = cli("gettxout", a.offer_txid, a.offer_vout) if not a.dry_run else None
    offer_sats = int(round(info["value"] * COIN)) if info else (a.offer_amount_sats or RS.DUST)
    if not a.dry_run and info is None:
        sys.exit(f"offer {a.offer_txid}:{a.offer_vout} is unspent-set-missing (spent or wrong vout)")
    # taker self-protection: the offer UTXO must actually back rune A
    if not a.dry_run and a.ord_url:
        assert_offer_backs_rune(ord_rune_balance(a.ord_url), a.offer_txid, a.offer_vout, rune_a, a.amount_a)
    maker_recv_spk = (bytes.fromhex(cli("validateaddress", a.maker_addr)["scriptPubKey"])
                      if not a.dry_run else b"\x00\x14" + b"\x00" * 20)
    taker_addr = a.taker_addr or (cli("getnewaddress", "", "bech32") if not a.dry_run else "<taker>")
    taker_recv_spk = (bytes.fromhex(cli("getaddressinfo", taker_addr)["scriptPubKey"])
                      if not a.dry_run else b"\x00\x14" + b"\x11" * 20)
    change_addr = a.change_addr or (cli("getnewaddress", "", "bech32") if not a.dry_run else "<change>")
    change_spk = (bytes.fromhex(cli("getaddressinfo", change_addr)["scriptPubKey"])
                  if not a.dry_run else b"\x00\x14" + b"\x22" * 20)
    # the counter-rune funding input must also carry enough sats to cover dust+fee beyond the offer's
    min_sats = max(0, 2 * RS.DUST + fee - offer_sats)
    fu = None
    if not a.dry_run:
        if not a.ord_url:
            sys.exit("rune<->rune funding needs --ord-url to locate the counter-rune (rune B) UTXO")
        unspent = cli("listunspent", 1) or []
        fu = _pick_rune_utxo(unspent, a.ord_url, rune_b, a.amount_b, min_sats=min_sats,
                             exclude={f"{a.offer_txid}:{a.offer_vout}"})
        if fu is None:
            sys.exit(f"no funding UTXO holds >= {a.amount_b} of rune {rune_b} with >= {min_sats} sats "
                     f"(consolidate a rune-B UTXO with enough BTC for dust+fee first)")
    fund_txid = fu["txid"] if fu else "11" * 32
    fund_vout = fu["vout"] if fu else 0
    fund_sats = int(round(fu["amount"] * COIN)) if fu else (a.fund_amount_sats or (2 * RS.DUST + fee))
    tx, meta = RS.build_addressed_rune_swap_unsigned(
        a.offer_txid, a.offer_vout, offer_sats, fund_txid, fund_vout, fund_sats,
        maker_recv_spk, taker_recv_spk, change_spk, rune_a, a.amount_a, rune_b, a.amount_b, fee=fee)
    unsigned_hex = b2x(tx.serialize())
    deal = {"offer_outpoint": f"{a.offer_txid}:{a.offer_vout}", "sell_rune": rune_a,
            "amount_a": a.amount_a, "pay_rune": rune_b, "amount_b": a.amount_b,
            "maker_recv_addr": a.maker_addr, "taker_recv_addr": taker_addr,
            "funding_outpoint": f"{fund_txid}:{fund_vout}", "edicts": meta["edicts"]}
    if a.dry_run:
        print(json.dumps({"unsigned_tx_hex": unsigned_hex, "deal": deal,
                          "note": "dry-run: converttopsbt + walletprocesspsbt(SIGHASH_ALL) happen on-node"},
                         default=str, indent=2)); return
    psbt = cli("converttopsbt", unsigned_hex)
    proc = cli("walletprocesspsbt", psbt, "true", "ALL")   # taker signs ITS funding input
    print(json.dumps({"psbt": proc["psbt"], "taker_complete": proc.get("complete", False), "deal": deal,
                      "send_to_maker": "maker verifies output 0 receives the counter-rune, then "
                                       "countersigns (SIGHASH_ALL) + broadcasts"}, default=str, indent=2))


def cmd_addressed_rune_countersign(a):
    import btx_rune_swap as RS
    cli = CLI(a.bitcoin_cli, a.chain, a.datadir, a.wallet, a.dry_run)
    rune_a = f"{a.rune_a_block}:{a.rune_a_tx}"
    rune_b = f"{a.rune_b_block}:{a.rune_b_tx}"
    dec = cli("decodepsbt", a.psbt) if not a.dry_run else {"tx": {"vin": [], "vout": []}}
    tx = dec["tx"]
    maker_recv_spk_hex = None
    if a.expect_maker_addr and not a.dry_run:
        maker_recv_spk_hex = cli("validateaddress", a.expect_maker_addr)["scriptPubKey"]
    if not maker_recv_spk_hex and not a.dry_run:
        sys.exit("need --expect-maker-addr (your rune-B receiving address) to verify output 0 pays you")
    # input rune balances the verifier reasons over: offer backs EXACTLY amount_a; the funding's rune-B
    # balance is read from the maker's OWN ord oracle (never trust the taker's claim).
    input_runes = {rune_a: a.amount_a}
    vins = tx.get("vin", [])
    if not a.dry_run:
        if not a.ord_url or len(vins) < 2:
            sys.exit("need --ord-url and a 2-input swap to confirm the funding's rune-B balance")
        fop = f"{vins[1]['txid']}:{vins[1]['vout']}"
        input_runes[rune_b] = ord_rune_balance(a.ord_url)(fop, rune_b)
        ok, reason = RS.verify_addressed_rune_tx(tx, a.offer_txid, a.offer_vout, maker_recv_spk_hex,
                                                 rune_b, a.amount_b, input_runes)
        if not ok:
            sys.exit(f"refusing to countersign: {reason}")
    if a.dry_run:
        print(json.dumps({"would_verify": f"{a.offer_txid}:{a.offer_vout}", "sell_rune": rune_a,
                          "pay_rune": rune_b, "amount_b": a.amount_b}, indent=2)); return
    proc = cli("walletprocesspsbt", a.psbt, "true", "ALL")  # maker signs the offer input (whole tx)
    fin = cli("finalizepsbt", proc["psbt"], "true")
    out = {"verified": True, "complete": fin.get("complete", False)}
    if not fin.get("complete"):
        out["psbt"] = proc["psbt"]
        out["note"] = "not fully signed yet — return this PSBT to the taker"
    else:
        out["final_tx_hex"] = fin["hex"]
        if a.broadcast:
            out["txid"] = cli("sendrawtransaction", fin["hex"])
    print(json.dumps(out, default=str, indent=2))


def cmd_cancel(a):
    """Cancel a resting open order by spending its offer UTXO back to the maker — RBF-signaled and
    fee-bumped so it can REPLACE a competing fill in the mempool. There is no consensus 'cancel': the
    only way to retract a published 0x83 offer is to spend its offer UTXO before a fill confirms.
    BTX fills RBF-signal their taker funding input (RBF_SEQUENCE), so this cancel can replace an
    unconfirmed fill under BIP125 — but ONLY if it pays a higher fee, so set --fee-rate ABOVE the racing
    fill's feerate. Worst case the fill confirms first (you were out-raced / a non-RBF miner mined it),
    in which case the order is gone (filled), not cancellable. See BTX-frontrunning-threat-model.md §8.
    The rune on the offer follows ord's default allocation to the first non-OP_RETURN output, and every
    output here is the maker's own wallet, so the rune returns to the maker (no runestone needed)."""
    cli = CLI(a.bitcoin_cli, a.chain, a.datadir, a.wallet, a.dry_run)
    if a.dry_run:
        print(json.dumps({"action": "cancel", "offer": f"{a.offer_txid}:{a.offer_vout}",
                          "rbf_sequence": f"{RBF_SEQUENCE:#x}", "fee_rate_sat_vb": a.fee_rate,
                          "note": "spends the offer back to the maker, RBF-signaled; raise --fee-rate "
                                  "above the racing fill's feerate to win the BIP125 replacement"},
                         indent=2))
        return
    # 1) the offer UTXO must still be UNSPENT — if a fill already confirmed, this is null and it's too late
    info = cli("gettxout", a.offer_txid, a.offer_vout)
    if not info:
        sys.exit(f"offer {a.offer_txid}:{a.offer_vout} is not unspent — already filled/cancelled or never "
                 f"confirmed; nothing to cancel")
    # 2) release the wallet lock placed at maker-sign so coin selection / signing can use the offer
    try:
        cli("lockunspent", "true", json.dumps([{"txid": a.offer_txid, "vout": a.offer_vout}]))
    except RuntimeError:
        pass  # best-effort: the offer may not have been locked
    # 3) sweep destination (maker's own wallet)
    to_addr = a.to_addr or cli("getnewaddress", "", "bech32")
    # 4) offer as a mandatory RBF-signaled input; fundrawtransaction adds a fee input + change and
    #    replaceable=true signals BIP125 on every input. fee_rate is sat/vB.
    raw = cli("createrawtransaction",
              json.dumps([{"txid": a.offer_txid, "vout": a.offer_vout, "sequence": RBF_SEQUENCE}]),
              json.dumps([{to_addr: info["value"]}]))
    funded = cli("fundrawtransaction", raw,
                 json.dumps({"add_inputs": True, "replaceable": True, "fee_rate": a.fee_rate}))
    signed = cli("signrawtransactionwithwallet", funded["hex"])
    out = {"offer": f"{a.offer_txid}:{a.offer_vout}", "to": to_addr, "fee_rate_sat_vb": a.fee_rate,
           "complete": signed.get("complete"), "cancel_tx_hex": signed["hex"]}
    if a.broadcast and signed.get("complete"):
        out["txid"] = cli("sendrawtransaction", signed["hex"])
    elif a.broadcast:
        out["error"] = "wallet could not fully sign the cancel (is the offer key in this wallet?)"
    print(json.dumps(out, default=str, indent=2))


# ----------------------------- offline simulate -----------------------------
def simulate():
    """Prove the wallet-integration plumbing OFFLINE by standing in for Core's signer with
    python-bitcoinlib: build the partial tx, 'sign' it (P2WPKH BIP143, SINGLE|ANYONECANPAY) to
    produce a signed-tx hex exactly like signrawtransactionwithwallet would, then run the real
    extract/assemble/verify path; do the same transplant for the taker side."""
    import hashlib
    from bitcoin.core import Hash160
    from bitcoin.core.script import (SignatureHash, SIGHASH_ALL, SIGVERSION_WITNESS_V0,
                                     OP_DUP, OP_HASH160, OP_EQUALVERIFY, OP_CHECKSIG, OP_0)
    from bitcoin.wallet import CBitcoinSecret
    import bitcoin
    bitcoin.SelectParams("regtest")

    def k(seed):
        s = CBitcoinSecret.from_secret_bytes(hashlib.sha256(seed).digest())
        return s, CScript([OP_0, Hash160(s.pub)])
    def sc(pub):
        return CScript([OP_DUP, OP_HASH160, Hash160(pub), OP_EQUALVERIFY, OP_CHECKSIG])

    maker, _ = k(b"wallet-maker")
    _, payout_spk = k(b"wallet-maker-payout")
    offer_txid, offer_vout, offer_amt = "aa" * 32, 0, int(1.0 * COIN)
    price = int(0.5 * COIN)

    # --- stand in for `signrawtransactionwithwallet <partial> [] SINGLE|ANYONECANPAY` ---
    partial = build_partial_tx(offer_txid, offer_vout, price, payout_spk)
    sh = SignatureHash(sc(maker.pub), partial, 0, SAA, amount=offer_amt,
                       sigversion=SIGVERSION_WITNESS_V0)
    sig = maker.sign(sh) + bytes([SAA])
    partial.wit = CTxWitness([CTxInWitness(CScriptWitness([sig, maker.pub]))])
    signed_partial_hex = b2x(partial.serialize())     # == Core's signed['hex']

    checks = {}
    msig, mpub = extract_maker_witness_from_signed_tx(signed_partial_hex)
    checks["lifted_sig_sighash_is_0x83"] = (msig[-1] == SAA)
    checks["lifted_pubkey_matches_maker"] = (mpub == bytes(maker.pub))
    art = assemble_artifact(offer_txid, offer_vout, price, payout_spk, mpub, msig, group_id=3)
    blob = btx.serialize_artifact(art)
    parsed = btx.parse_artifact(blob)
    checks["assembled_artifact_verifies"] = btx.verify_maker_sig(parsed, offer_amt)
    tampered = dict(parsed); tampered["price"] = int(0.4 * COIN)
    checks["tampered_price_fails"] = (btx.verify_maker_sig(tampered, offer_amt) is False)

    # --- taker: stand in for the wallet signing only the funding input (SIGHASH_ALL) ---
    taker, taker_spk = k(b"wallet-taker")
    fund_txid, fund_vout, fund_amt = "bb" * 32, 1, int(0.6 * COIN)
    unsigned = build_taker_swap_unsigned(parsed, offer_amt, fund_txid, fund_vout, fund_amt, taker_spk)
    sh_t = SignatureHash(sc(taker.pub), unsigned, 1, SIGHASH_ALL, amount=fund_amt,
                         sigversion=SIGVERSION_WITNESS_V0)
    sig_t = taker.sign(sh_t) + bytes([SIGHASH_ALL])
    # wallet returns the tx with ONLY input1 signed, input0 left empty
    unsigned.wit = CTxWitness([CTxInWitness(CScriptWitness([])),
                               CTxInWitness(CScriptWitness([sig_t, taker.pub]))])
    wallet_signed_hex = b2x(unsigned.serialize())

    final_hex = transplant_maker_witness(wallet_signed_hex, parsed)
    final = CTransaction.deserialize(x(final_hex))
    checks["input0_witness_is_maker_sig"] = (
        bytes(final.wit.vtxinwit[0].scriptWitness.stack[0]) == parsed["maker_sig"])
    checks["input1_witness_preserved"] = (
        bytes(final.wit.vtxinwit[1].scriptWitness.stack[0]) == sig_t)
    checks["output0_is_committed_payout"] = (
        final.vout[0].nValue == price and bytes(final.vout[0].scriptPubKey) == parsed["payout_spk"])

    allpass = all(v is True for v in checks.values())
    print(json.dumps({"checks": checks, "ALL_PASS": allpass}, default=str, indent=2))
    return allpass


# ----------------------------- argparse -----------------------------
def build_parser():
    p = argparse.ArgumentParser(prog="btx_wallet", description="BTX Bitcoin Core wallet integration")
    sub = p.add_subparsers(dest="cmd", required=True)

    def rpc_args(sp):
        sp.add_argument("--bitcoin-cli", default="bitcoin-cli")
        sp.add_argument("--chain", default="regtest")
        sp.add_argument("--datadir")
        sp.add_argument("--wallet")
        sp.add_argument("--dry-run", action="store_true")

    sim = sub.add_parser("simulate", help="offline proof of the plumbing (no node)")
    sim.set_defaults(func=lambda a: sys.exit(0 if simulate() else 1))

    ms = sub.add_parser("maker-sign", help="wallet signs the offer -> BTX artifact")
    rpc_args(ms)
    ms.add_argument("--offer-txid"); ms.add_argument("--offer-vout", type=int, default=0)
    ms.add_argument("--offer-amount-sats", type=int)
    ms.add_argument("--price-btc", type=float); ms.add_argument("--price-sats", type=int)
    ms.add_argument("--payout-addr")
    ms.add_argument("--amount-units", type=int, default=1000)
    ms.add_argument("--rune-block", type=int, default=840000, help="counter-asset rune id (block)")
    ms.add_argument("--rune-tx", type=int, default=1, help="counter-asset rune id (tx index)")
    ms.add_argument("--ord-url", help="local ord server URL (e.g. http://127.0.0.1:8089) used as the "
                                      "rune oracle to verify the offer UTXO actually backs the order")
    ms.add_argument("--require-rune-backing", action="store_true",
                    help="refuse to publish unless the rune oracle (--ord-url) confirms the offer UTXO "
                         "holds EXACTLY --amount-units of the rune")
    ms.add_argument("--expiry", type=int, default=10**9)
    ms.add_argument("--group-id", type=int, default=0)
    ms.add_argument("--carrier", choices=["op_return", "envelope"], default="op_return")
    ms.add_argument("--no-lock-offer", action="store_true",
                    help="do NOT lockunspent the offer UTXO (default locks it so funding can't spend it)")
    ms.set_defaults(func=cmd_maker_sign)

    tf = sub.add_parser("taker-fill", help="wallet funds+signs a swap from an artifact")
    rpc_args(tf)
    tf.add_argument("--artifact-hex", required=True)
    tf.add_argument("--offer-amount-sats", type=int)
    tf.add_argument("--fund-amount-sats", type=int)
    tf.add_argument("--change-addr")
    tf.add_argument("--ord-url", help="ord server URL; when set, rune-bearing UTXOs are excluded from "
                                      "swap funding (a rune on the funding input would be lost to the maker)")
    tf.add_argument("--fee-sats", type=int, default=DEFAULT_FEE,
                    help="swap-tx fee in sats (btxd passes an estimatesmartfee-derived value)")
    tf.add_argument("--broadcast", action="store_true")
    tf.set_defaults(func=cmd_taker_fill)

    bf = sub.add_parser("batch-fill", help="wallet fills SEVERAL asks in one tx (roadmap #2)")
    rpc_args(bf)
    bf.add_argument("--artifact-hex", action="append", required=True,
                    help="repeat once per offer to sweep (e.g. --artifact-hex AA --artifact-hex BB)")
    bf.add_argument("--offer-amount-sats", type=int, help="dry-run only: stand-in offer amount")
    bf.add_argument("--fund-amount-sats", type=int, help="dry-run only: stand-in funding amount")
    bf.add_argument("--change-addr")
    bf.add_argument("--ord-url", help="ord server URL; keeps rune-bearing UTXOs out of swap funding")
    bf.add_argument("--fee-sats", type=int, default=DEFAULT_FEE,
                    help="per-offer fee in sats; total fee = this * number of offers")
    bf.add_argument("--broadcast", action="store_true")
    bf.set_defaults(func=cmd_batch_fill)

    cn = sub.add_parser("cancel", help="cancel a resting order: RBF-signaled, fee-bumped spend of the offer UTXO")
    rpc_args(cn)
    cn.add_argument("--offer-txid", required=True)
    cn.add_argument("--offer-vout", type=int, default=0)
    cn.add_argument("--to-addr", help="address to sweep the offer (rune + sats) back to "
                                      "(default: a fresh wallet address)")
    cn.add_argument("--fee-rate", type=float, default=20.0,
                    help="cancel fee rate in sat/vB; set ABOVE the racing fill's feerate to win the "
                         "BIP125 replacement (the fill RBF-signals its taker input, so a higher-fee "
                         "cancel replaces it)")
    cn.add_argument("--broadcast", action="store_true")
    cn.set_defaults(func=cmd_cancel)

    # ---- addressed (snipe-resistant) swaps: opt-in, two-message PSBT handshake ----
    ap = sub.add_parser("addressed-propose",
                        help="taker: build a fully-committed swap PSBT for the maker to countersign")
    rpc_args(ap)
    ap.add_argument("--offer-txid", required=True); ap.add_argument("--offer-vout", type=int, default=0)
    ap.add_argument("--offer-amount-sats", type=int)
    ap.add_argument("--price-btc", type=float); ap.add_argument("--price-sats", type=int)
    ap.add_argument("--maker-addr", required=True, help="address the maker receives the price at (output 0)")
    ap.add_argument("--amount-units", type=int, default=1000)
    ap.add_argument("--rune-block", type=int, default=840000); ap.add_argument("--rune-tx", type=int, default=1)
    ap.add_argument("--taker-addr", help="address to receive the rune + change (default: fresh)")
    ap.add_argument("--ord-url", help="ord server URL; verifies offer backing and keeps runes out of funding")
    ap.add_argument("--fee-sats", type=int, default=DEFAULT_FEE)
    ap.add_argument("--fund-amount-sats", type=int)
    ap.set_defaults(func=cmd_addressed_propose)

    ac = sub.add_parser("addressed-countersign",
                        help="maker: verify output 0 == agreed price, sign SIGHASH_ALL, broadcast")
    rpc_args(ac)
    ac.add_argument("--psbt", required=True, help="the PSBT from the taker's addressed-propose")
    ac.add_argument("--offer-txid", required=True, help="your offer txid (must be input 0)")
    ac.add_argument("--offer-vout", type=int, default=0)
    ac.add_argument("--expect-price-btc", type=float); ac.add_argument("--expect-price-sats", type=int)
    ac.add_argument("--expect-maker-addr", help="your payout address; verifies output 0 pays you")
    ac.add_argument("--broadcast", action="store_true")
    ac.set_defaults(func=cmd_addressed_countersign)

    # ---- rune<->rune addressed swaps (roadmap #4): maker sells rune A for the taker's rune B ----
    rp = sub.add_parser("addressed-rune-propose",
                        help="taker: build a rune<->rune swap PSBT (maker receives a counter-rune)")
    rpc_args(rp)
    rp.add_argument("--offer-txid", required=True); rp.add_argument("--offer-vout", type=int, default=0)
    rp.add_argument("--offer-amount-sats", type=int)
    rp.add_argument("--rune-a-block", type=int, required=True, help="OFFERED rune id block (maker sells)")
    rp.add_argument("--rune-a-tx", type=int, required=True)
    rp.add_argument("--amount-a", type=int, required=True, help="units of rune A the offer holds")
    rp.add_argument("--rune-b-block", type=int, required=True, help="COUNTER rune id block (taker pays)")
    rp.add_argument("--rune-b-tx", type=int, required=True)
    rp.add_argument("--amount-b", type=int, required=True, help="units of rune B the maker receives")
    rp.add_argument("--maker-addr", required=True, help="address the maker receives rune B at (output 0)")
    rp.add_argument("--taker-addr", help="address to receive rune A (+ change); default fresh")
    rp.add_argument("--change-addr")
    rp.add_argument("--ord-url", help="ord oracle: locates the taker's rune-B funding UTXO + verifies backing")
    rp.add_argument("--fee-sats", type=int, default=DEFAULT_FEE)
    rp.add_argument("--fund-amount-sats", type=int)
    rp.set_defaults(func=cmd_addressed_rune_propose)

    rc = sub.add_parser("addressed-rune-countersign",
                        help="maker: verify output 0 receives the counter-rune, sign SIGHASH_ALL, broadcast")
    rpc_args(rc)
    rc.add_argument("--psbt", required=True)
    rc.add_argument("--offer-txid", required=True, help="your offer txid (must be input 0)")
    rc.add_argument("--offer-vout", type=int, default=0)
    rc.add_argument("--rune-a-block", type=int, required=True); rc.add_argument("--rune-a-tx", type=int, required=True)
    rc.add_argument("--amount-a", type=int, required=True, help="units of rune A your offer holds")
    rc.add_argument("--rune-b-block", type=int, required=True); rc.add_argument("--rune-b-tx", type=int, required=True)
    rc.add_argument("--amount-b", type=int, required=True, help="units of rune B you must receive at output 0")
    rc.add_argument("--expect-maker-addr", help="your rune-B receiving address; verifies output 0 pays you")
    rc.add_argument("--ord-url", help="ord oracle: confirms the funding input actually holds >= amount-b of rune B")
    rc.add_argument("--broadcast", action="store_true")
    rc.set_defaults(func=cmd_addressed_rune_countersign)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
