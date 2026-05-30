#!/usr/bin/env python3
"""
btxd.py — BTX local orchestrator (Phase 3a of the bundle + unified GUI).

A small, dependency-free (stdlib-only) service bound to 127.0.0.1 that the GUI talks to as a single
origin. It does the things the static HTML can't:
  - node status   (bitcoin-cli getblockchaininfo / getnetworkinfo / getconnectioncount)
  - wallet        (getbalances, listunspent, getnewaddress)
  - mining        (getmininginfo, getblocktemplate; regtest-only generate)
  - DEX reads     (proxied from the brk-btx indexer's /api/v1/btx/*)
  - DEX ACTIONS   (POST /api/order/create, /api/order/fill) — executes the PROVEN tooling
                  (btx_wallet.py maker-sign / taker-fill, btx_envelope_publish.py) so the GUI can
                  publish and fill orders, not just display them.
  - serves the static UI from this folder.

BTX never holds keys: every signing/broadcast goes through Bitcoin Core's own wallet via the same
CLI paths already validated on regtest/signet. btxd only orchestrates subprocess calls; it adds no
new consensus or crypto logic.

Run (point it at the same node your CLI tooling uses):
  python3 btxd.py --bitcoin-cli ~/bitcoin-29.1/bin/bitcoin-cli --chain signet \
      --datadir ~/sig-public --wallet btx --brk-url http://127.0.0.1:3140 --port 3333
then open http://127.0.0.1:3333/
"""
import argparse
import json
import math
import os
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
# Where the static UI lives. In a PyInstaller bundle the launcher sets BTX_UI_DIR to the bundle dir.
UI_DIR = os.environ.get("BTX_UI_DIR", HERE)
CFG = {}  # filled by main()

# btxd is a ThreadingHTTPServer, so wallet-mutating POSTs run on concurrent threads and all drive the
# SAME Bitcoin Core wallet. Each does listunspent -> pick funding -> sign -> broadcast without locking
# the chosen funding coin, so two concurrent requests can select the same UTXO and one broadcast then
# fails with a missing-input double-spend error (no fund loss — consensus forbids the double-spend — but
# a wasted, failed request). Serialize every mutating POST behind this single lock: for a single-user
# local orchestrator, concurrent signing buys nothing and this removes the whole funding-collision race.
# Read-only GETs (book/wallet/status) are NOT serialized. One non-nested lock => no deadlock risk.
_WALLET_LOCK = threading.Lock()

# Cap on POST body size. Orders/artifacts/PSBTs are a few KB at most; a crafted Content-Length must not
# let `rfile.read(ln)` allocate unboundedly (a local process can POST to loopback). 1 MiB is generous.
MAX_BODY = 1 << 20

_CHAIN_FLAG = {"regtest": "-regtest", "signet": "-signet", "testnet": "-testnet",
               "test": "-testnet", "testnet4": "-testnet4", "main": "-chain=main", "mainnet": "-chain=main"}


# ----------------------------- bitcoin-cli / tooling helpers -----------------------------
def _bcli_base(wallet=False):
    base = [CFG["bitcoin_cli"], _CHAIN_FLAG.get(CFG["chain"], f"-chain={CFG['chain']}")]
    if CFG.get("datadir"):
        base.append(f"-datadir={CFG['datadir']}")
    if wallet and CFG.get("wallet"):
        base.append(f"-rpcwallet={CFG['wallet']}")
    return base


def bcli(*args, wallet=False):
    """Run bitcoin-cli; return parsed JSON or the raw string. Raises RuntimeError on failure."""
    cmd = _bcli_base(wallet) + [str(a) for a in args]
    # Normalize "binary not found" to RuntimeError so every existing `except RuntimeError` (startup
    # wallet auto-load, offer re-lock, the _guard-wrapped handlers) degrades gracefully instead of a
    # FileNotFoundError escaping and hard-crashing the daemon when bitcoin-cli isn't on PATH / mispathed.
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (FileNotFoundError, PermissionError) as e:
        raise RuntimeError(f"bitcoin-cli not runnable ({cmd[0]}): {e}") from e
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"bitcoin-cli failed: {' '.join(args[:1])}")
    s = r.stdout.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return s


def run_tool(script, *args):
    """Run one of the BTX tools; return (rc, stdout, stderr). In dev, runs `python3 <script>.py`.
    In a PyInstaller bundle (sys.frozen), each tool is a sibling standalone executable, so we call
    that exe directly (no interpreter, no .py) — same CLI args, same behavior."""
    sargs = [str(a) for a in args]
    if getattr(sys, "frozen", False):
        name = script[:-3] if script.endswith(".py") else script
        bundle = os.path.dirname(sys.executable)
        cmd = [os.path.join(bundle, name), *sargs]
        cwd = bundle
    else:
        cmd = [sys.executable, os.path.join(HERE, script), *sargs]
        cwd = HERE
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=300)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _first_json(s):
    """Extract the first JSON object from a tool's stdout (some print prose after)."""
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        i, j = s.find("{"), s.rfind("}")
        if i >= 0 and j > i:
            return json.loads(s[i:j + 1])
        raise


def brk_get(path):
    """Proxy a GET to the brk-btx indexer (the read-only order book / trades feed)."""
    url = CFG["brk_url"].rstrip("/") + path
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode())


def ord_get(path):
    """GET JSON from the local ord rune oracle (Accept: application/json)."""
    req = urllib.request.Request(CFG["ord_url"].rstrip("/") + path, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def estimate_fee_sats(vbytes, fallback, conf_target=6):
    """Fee (sats) for a tx of ~vbytes, derived from the node's fee estimator: estimatesmartfee
    returns a feerate in BTC/kvB, which we convert to sat/vB and multiply by the estimated size.
    Falls back to a fixed value when the estimator has no answer — which is the normal case on
    regtest/signet and during early mainnet sync — so behavior there is unchanged. Floors at
    1 sat/vB so a returned-but-tiny estimate still produces a relayable tx."""
    try:
        est = bcli("estimatesmartfee", conf_target)
        rate = est.get("feerate") if isinstance(est, dict) else None
        if rate and float(rate) > 0:
            sat_per_vb = max(1.0, float(rate) * 1e5)  # BTC/kvB -> sat/vB
            return int(math.ceil(sat_per_vb * vbytes))
    except (RuntimeError, ValueError, TypeError) as e:
        # Don't fall back silently on an estimator *failure* (vs. the normal no-answer case on
        # regtest/early sync, where rate is None and we fall through quietly): surface it so a stuck
        # fee isn't a mystery.
        sys.stderr.write(f"btxd: fee estimator failed ({type(e).__name__}: {str(e)[:80]}); "
                         f"using fallback {fallback} sats\n")
    return fallback


def ord_synced(margin=2):
    """Mainnet hardening: rune ops trust ord's balances, so a lagging/half-indexed ord could approve an
    UNBACKED rune order (its backing check passes against stale data). Returns (ok, detail) comparing
    ord's indexed height to the node tip. ord serves its height at /blockheight as a bare integer —
    valid JSON, so ord_get parses it. Within `margin` blocks counts as synced (ord trails the tip by a
    block or two normally)."""
    if not CFG.get("ord_url"):
        return False, "no ord oracle configured"
    try:
        node_h = int(bcli("getblockcount"))
    except Exception as e:  # noqa
        return False, f"node height unavailable: {e}"
    try:
        ord_h = int(ord_get("/blockheight"))
    except Exception as e:  # noqa
        return False, f"ord height unavailable: {e}"
    if node_h - ord_h > margin:
        return False, f"ord is {node_h - ord_h} blocks behind the node (ord {ord_h} < node {node_h})"
    return True, f"ord synced (ord {ord_h}, node {node_h})"


def relock_open_offers():
    """Mainnet hardening: Bitcoin Core's locked-coin set is IN-MEMORY and cleared on wallet/node restart,
    so after a restart coin selection could spend an open order's offer UTXO out from under it. On
    startup, re-lock every open order's offer this wallet owns. Best-effort: offers the wallet doesn't
    own just error on lockunspent and are skipped."""
    try:
        orders = brk_get("/api/v1/btx/orders") or []
    except Exception as e:  # noqa
        print(f"  (offer re-lock skipped: brk unreachable: {str(e)[:60]})")
        return
    locked = 0
    skipped = 0
    for o in orders:
        txid, vout = o.get("offer_txid"), o.get("offer_vout")
        if not txid:
            continue
        try:
            bcli("lockunspent", "false", json.dumps([{"txid": txid, "vout": int(vout)}]), wallet=True)
            locked += 1
        except RuntimeError:
            skipped += 1  # not our UTXO / already spent / not lockable here — expected for others' offers
    # Always report both counts so a failed re-lock of an offer we DO own isn't invisible (observability:
    # a non-zero `skipped` for your own orders means those offer UTXOs are not protected from coin select).
    if locked or skipped:
        print(f"  re-locked {locked} open-order offer UTXO(s); {skipped} not lockable "
              f"(not ours / already spent) (restart-safe)")


# ----------------------------- endpoint handlers (return python objects) -----------------------------
def h_config():
    return {"chain": CFG["chain"], "wallet": CFG.get("wallet"), "brk_url": CFG["brk_url"],
            "datadir": CFG.get("datadir"), "ord_url": CFG.get("ord_url"),
            "rune_oracle": bool(CFG.get("ord_url"))}


def h_node_status():
    info = bcli("getblockchaininfo")
    net = {}
    try:
        net = bcli("getnetworkinfo")
    except RuntimeError:
        pass
    try:
        peers = bcli("getconnectioncount")
    except RuntimeError:
        peers = None
    return {
        "chain": info.get("chain"),
        "blocks": info.get("blocks"),
        "headers": info.get("headers"),
        "verificationprogress": round(info.get("verificationprogress", 0), 5),
        "initialblockdownload": info.get("initialblockdownload"),
        "peers": peers,
        "version": net.get("version"),
        "subversion": net.get("subversion"),
    }


def h_wallet():
    bals = bcli("getbalances", wallet=True)
    mine = bals.get("mine", {}) if isinstance(bals, dict) else {}
    utxos = []
    try:
        for u in (bcli("listunspent", 1, wallet=True) or []):
            spk = u.get("scriptPubKey", "")
            utxos.append({
                "txid": u["txid"], "vout": u["vout"], "amount": u["amount"],
                "address": u.get("address"), "scriptPubKey": spk,
                "p2wpkh": spk.startswith("0014"),
            })
    except RuntimeError:
        pass
    return {"trusted": mine.get("trusted"), "untrusted_pending": mine.get("untrusted_pending"),
            "immature": mine.get("immature"), "utxos": utxos}


def h_newaddress():
    return {"address": bcli("getnewaddress", "", "bech32", wallet=True)}


def h_mining_info():
    info = bcli("getmininginfo")
    return {"blocks": info.get("blocks"), "difficulty": info.get("difficulty"),
            "networkhashps": info.get("networkhashps"), "pooledtx": info.get("pooledtx"),
            "chain": info.get("chain")}


def h_mining_generate(body):
    """Regtest-only convenience: mine N blocks to a wallet address (real mining UI = template/submit)."""
    if CFG["chain"] != "regtest":
        return {"error": "generate is regtest-only; on signet/main use a real miner (template/submit)"}, 400
    n = int(body.get("n", 1))
    addr = body.get("address") or bcli("getnewaddress", "", "bech32", wallet=True)
    hashes = bcli("generatetoaddress", n, addr)
    return {"mined": len(hashes) if isinstance(hashes, list) else n, "address": addr}, 200


def h_mining_template():
    rules = ["segwit", "signet"] if CFG["chain"] == "signet" else ["segwit"]
    tmpl = bcli("getblocktemplate", json.dumps({"rules": rules}))
    return {"height": tmpl.get("height"), "n_txs": len(tmpl.get("transactions", [])),
            "coinbasevalue": tmpl.get("coinbasevalue"), "bits": tmpl.get("bits"),
            "previousblockhash": tmpl.get("previousblockhash")}


def h_dex_book():
    """Deterministic, verifiable order book (roadmap #1): the chain-reconstructed BTX orders served by
    brk, canonicalized into a price-time book with a content hash any two indexers can compare
    (btx_orderbook). Read-only; nothing offchain — just a canonical view over the on-chain orders."""
    import btx_orderbook as ob
    orders = brk_get("/api/v1/btx/orders") or []
    py_hash = ob.book_hash(orders)
    # divisibility map (rune_id -> decimals) from the ord oracle, so the book can show prices
    # normalized per WHOLE rune (comparable across runes). Best-effort: skipped without ord, and any
    # per-rune lookup failure just omits that rune's norm_price. Does NOT affect the consensus hash.
    divmap = {}
    if CFG.get("ord_url"):
        for rid in {str(o.get("rune_id") or "0:0") for o in orders}:
            if rid and rid != "0:0":
                try:
                    rj = ord_get(f"/rune/{rid}")
                    entry = rj.get("entry", rj) if isinstance(rj, dict) else {}
                    divmap[rid] = int(entry.get("divisibility", 0) or 0)
                except Exception:
                    # ord unreachable/erroring: STOP (don't pay an ord_get timeout per rune on this hot
                    # read endpoint — one down ord would otherwise stall /api/dex/book for N*timeout).
                    break
    out = {"hash": py_hash, "n_orders": len(orders), "book": ob.build_book(orders, divmap=divmap)}
    # Cross-indexer CONSENSUS check: compare our locally-computed hash against the brk-btx indexer's
    # NATIVE book hash (computed in Rust over its persisted order store, served at /api/v1/btx/book-hash).
    # If both independent implementations agree, surface it — that agreement is what makes a
    # nothing-offchain book trustworthy. The endpoint is absent on older brk builds, so this is best-effort.
    try:
        bh = brk_get("/api/v1/btx/book-hash")
        if isinstance(bh, dict) and bh.get("hash"):
            out["indexer_hash"] = bh["hash"]
            out["consensus"] = (bh["hash"] == py_hash)
    except Exception:
        pass
    return out


def h_order_create(body):
    """maker-sign (locks the offer) then publish via the chosen carrier. Returns the artifact + the
    announce txid. Mirrors btx_live_verify.sh's publish logic."""
    offer_txid = body["offer_txid"]
    offer_vout = int(body["offer_vout"])
    # Carrier default is chain-aware. The BTX artifact is ~190 bytes; a bare OP_RETURN that large
    # exceeds Bitcoin Core's historical `datacarriersize` (83 bytes) standardness limit, so on MAINNET
    # an OP_RETURN announce is unlikely to relay/confirm across nodes that haven't raised the limit.
    # The Taproot witness-envelope carrier puts the artifact in witness data, which is NOT subject to
    # datacarriersize, so it propagates under default policy — the safe mainnet default. regtest/signet
    # keep OP_RETURN (simpler, single tx) since the bundle's own node raises datacarriersize there.
    default_carrier = "envelope" if CFG.get("chain") in ("main", "mainnet") else "op_return"
    carrier = body.get("carrier", default_carrier)
    args = ["maker-sign", "--bitcoin-cli", CFG["bitcoin_cli"], "--chain", CFG["chain"],
            "--wallet", CFG.get("wallet", "btx"), "--offer-txid", offer_txid,
            "--offer-vout", offer_vout, "--carrier", carrier]
    if CFG.get("datadir"):
        args += ["--datadir", CFG["datadir"]]
    if body.get("price_btc") is not None:
        args += ["--price-btc", body["price_btc"]]
    elif body.get("price_sats") is not None:
        args += ["--price-sats", int(body["price_sats"])]
    for k in ("amount_units", "expiry", "group_id", "rune_block", "rune_tx"):
        if body.get(k) is not None:
            args += [f"--{k.replace('_', '-')}", int(body[k])]
    # If an ord oracle is configured, REQUIRE the offer UTXO to actually back the rune order
    # (refuses to publish an order the offer doesn't hold exactly). Without it, maker-sign only warns.
    if CFG.get("ord_url"):
        # for a rune order, the backing check is only trustworthy if ord is synced — else a stale ord
        # could approve an unbacked order. Gate it (BTC-only orders, no rune id, are unaffected).
        if body.get("rune_block") or body.get("rune_tx"):
            ok, detail = ord_synced()
            if not ok:
                return {"error": "ord not synced — refusing to publish a rune order", "detail": detail}, 503
        args += ["--ord-url", CFG["ord_url"], "--require-rune-backing"]
    rc, out, err = run_tool("btx_wallet.py", *args)
    if rc != 0:
        return {"error": "maker-sign failed", "detail": err or out}, 500
    sign = _first_json(out)
    artifact = sign["artifact_hex"]
    if not sign.get("maker_sig_self_verifies", True):
        return {"error": "maker signature did not self-verify", "sign": sign}, 500

    if carrier == "envelope":
        # reveal tx is small (the ~207B artifact rides in the witness, 4x-discounted); ~250 vB is a
        # safe size estimate. fallback 2000 = btx_envelope_publish.py's fixed default.
        reveal_fee = estimate_fee_sats(250, 2000)
        pa = ["publish", "--artifact-hex", artifact, "--bitcoin-cli", CFG["bitcoin_cli"],
              "--chain", CFG["chain"], "--wallet", CFG.get("wallet", "btx"),
              "--fee-sats", reveal_fee, "--broadcast"]
        if CFG.get("datadir"):
            pa += ["--datadir", CFG["datadir"]]
            # crash-safety: persist the ephemeral reveal key + commit info (0o600) so a failure between
            # the commit broadcast and the reveal doesn't strand the commit funds — recover with
            # `btx_envelope_publish.py publish-reveal --state-file <path>`.
            pa += ["--state-file", os.path.join(CFG["datadir"], "btx_envelope_recovery.json")]
        rc, out, err = run_tool("btx_envelope_publish.py", *pa)
        if rc != 0:
            return {"error": "envelope publish failed", "detail": err or out, "artifact_hex": artifact}, 500
        pub = _first_json(out)
        announce = pub.get("reveal_txid")
    else:  # op_return carrier: build + fund + sign + broadcast the OP_RETURN tx via Core
        try:
            raw = bcli("createrawtransaction", "[]", json.dumps([{"data": artifact}]))
            funded = bcli("fundrawtransaction", raw, wallet=True)["hex"]
            signed = bcli("signrawtransactionwithwallet", funded, wallet=True)["hex"]
            announce = bcli("sendrawtransaction", signed)
        except RuntimeError as e:
            return {"error": "OP_RETURN publish failed", "detail": str(e), "artifact_hex": artifact}, 500

    return {"ok": True, "carrier": carrier, "artifact_hex": artifact,
            "offer_outpoint": f"{offer_txid}:{offer_vout}", "announce_txid": announce,
            "payout_addr": sign.get("payout_addr")}, 200


def h_order_fill(body):
    """Complete + broadcast a swap from an artifact via Core's wallet (taker-fill)."""
    artifact = body["artifact_hex"]
    # swap tx ~ offer input + funding input + payout/asset/change outputs; ~300 vB is a safe estimate.
    # fallback 10000 = btx_wallet.py's fixed DEFAULT_FEE.
    swap_fee = estimate_fee_sats(300, 10000)
    args = ["taker-fill", "--bitcoin-cli", CFG["bitcoin_cli"], "--chain", CFG["chain"],
            "--wallet", CFG.get("wallet", "btx"), "--artifact-hex", artifact,
            "--fee-sats", swap_fee, "--broadcast"]
    if CFG.get("datadir"):
        args += ["--datadir", CFG["datadir"]]
    if CFG.get("ord_url"):     # exclude rune-bearing UTXOs from swap funding
        args += ["--ord-url", CFG["ord_url"]]
    rc, out, err = run_tool("btx_wallet.py", *args)
    if rc != 0:
        return {"error": "taker-fill failed", "detail": err or out}, 500
    fill = _first_json(out)
    return {"ok": True, "swap_txid": fill.get("txid"), "offer_outpoint": fill.get("offer_outpoint"),
            "committed_payout_sats": fill.get("committed_payout_sats")}, 200


def h_batch_fill(body):
    """Roadmap #2: fill SEVERAL asks in ONE swap tx (batch-fill). Each maker's SINGLE|ANYONECANPAY
    pre-sig commits only to its own (offer_k -> payout_k) leg, so we pack N offers + one funding input
    into a single transaction — one fee, atomic settlement. Body: {"artifact_hex": [hexA, hexB, ...]}."""
    arts = body.get("artifact_hex") or []
    if isinstance(arts, str):
        arts = [arts]
    if not arts:
        return {"error": "batch-fill needs a non-empty artifact_hex list"}, 400
    # per-offer fee rate; btx_wallet multiplies by the offer count. ~250 vB per added offer leg.
    per_offer_fee = estimate_fee_sats(250, 10000)
    args = ["batch-fill", "--bitcoin-cli", CFG["bitcoin_cli"], "--chain", CFG["chain"],
            "--wallet", CFG.get("wallet", "btx"), "--fee-sats", per_offer_fee, "--broadcast"]
    for h in arts:
        args += ["--artifact-hex", h]
    if CFG.get("datadir"):
        args += ["--datadir", CFG["datadir"]]
    if CFG.get("ord_url"):     # exclude rune-bearing UTXOs from swap funding
        args += ["--ord-url", CFG["ord_url"]]
    rc, out, err = run_tool("btx_wallet.py", *args)
    if rc != 0:
        return {"error": "batch-fill failed", "detail": err or out}, 500
    fill = _first_json(out)
    return {"ok": True, "swap_txid": fill.get("txid"), "n_offers": fill.get("n_offers"),
            "offer_outpoints": fill.get("offer_outpoints"),
            "committed_payout_sats_total": fill.get("committed_payout_sats_total"),
            "fee_sats": fill.get("fee_sats")}, 200


def h_rune_etch(body):
    """Mint a counter-asset rune with BTX's own primitives (btx_etch) so the maker can publish a
    BACKED rune order from the GUI. The reveal's output 0 (the premine) becomes the offer UTXO. ord
    indexes it and assigns the rune id (block:tx), which we resolve so the GUI can publish straight
    away. REGTEST-ONLY: btx_etch mines its own commit-maturity + reveal blocks."""
    if CFG.get("chain") != "regtest":
        return {"error": "GUI etch is regtest-only (it mines blocks); on signet/mainnet etch out-of-band"}, 400
    if not CFG.get("ord_url"):
        return {"error": "no ord oracle configured (start the bundle with ord, or pass --ord-url)"}, 400
    # Runes names are globally unique: etching a name that already exists is a cenotaph (no premine
    # minted), so the GUI button must mint a FRESH name each click. Default to a unique A-Z name;
    # callers may still override via body["rune"]. The base "BTXUSDTEST" + 5 random letters keeps
    # the name long enough to clear the current minimum-rune gate on regtest.
    import os as _os
    if body.get("rune"):
        rune = body["rune"].upper()
        # rule #4 (name-already-etched) needs the ord oracle, so it lives here rather than in
        # btx_etch. If ord already knows this rune, etching it again would only cenotaph — refuse.
        try:
            existing = ord_get(f"/rune/{rune}")
            if existing and existing.get("id"):
                return {"error": f"rune '{rune}' is already etched (id {existing['id']}) — pick another name"}, 400
        except Exception:
            pass  # 404 / not found = name is free = good
    else:
        suffix = "".join(chr(65 + (b % 26)) for b in _os.urandom(5))
        rune = "BTXUSDTEST" + suffix
    premine = int(body.get("premine", 1000))
    args = ["etch", "--rune", rune, "--premine", premine,
            "--divisibility", int(body.get("divisibility", 0)), "--symbol", body.get("symbol", "$"),
            "--bitcoin-cli", CFG["bitcoin_cli"], "--chain", CFG["chain"],
            "--wallet", CFG.get("wallet", "btx"), "--broadcast"]
    if CFG.get("datadir"):
        args += ["--datadir", CFG["datadir"]]
    if CFG.get("ord_url"):     # lock rune-bearing UTXOs so the commit funds from rune-free coins
        args += ["--ord-url", CFG["ord_url"]]
    rc, out, err = run_tool("btx_etch.py", *args)
    if rc != 0:
        return {"error": "etch failed", "detail": err or out}, 500
    etch = _first_json(out)
    reveal_txid = etch.get("reveal_txid")
    # resolve the rune id (block:tx) from ord once it has indexed the etch
    rune_block = rune_tx = None
    import time
    for _ in range(25):
        try:
            rid = ord_get(f"/rune/{rune}").get("id")
            if rid and ":" in rid:
                rune_block, rune_tx = (int(x) for x in rid.split(":"))
                break
        except Exception:
            pass
        time.sleep(1)
    return {"ok": True, "rune": rune, "rune_block": rune_block, "rune_tx": rune_tx,
            "offer_txid": reveal_txid, "offer_vout": 0, "premine": premine,
            "reveal_txid": reveal_txid,
            "indexed": rune_block is not None}, 200


def h_addressed_propose(body):
    """Taker side of the opt-in snipe-resistant swap: build the full swap and sign ONLY the funding
    input, emitting a BIP-174 PSBT for the maker to countersign. Exchanged out-of-band (no relay)."""
    swap_fee = estimate_fee_sats(300, 10000)
    args = ["addressed-propose", "--bitcoin-cli", CFG["bitcoin_cli"], "--chain", CFG["chain"],
            "--wallet", CFG.get("wallet", "btx"), "--offer-txid", body["offer_txid"],
            "--offer-vout", int(body["offer_vout"]), "--maker-addr", body["maker_addr"],
            "--fee-sats", swap_fee]
    if CFG.get("datadir"):
        args += ["--datadir", CFG["datadir"]]
    if body.get("price_btc") is not None:
        args += ["--price-btc", body["price_btc"]]
    elif body.get("price_sats") is not None:
        args += ["--price-sats", int(body["price_sats"])]
    for k in ("amount_units", "rune_block", "rune_tx"):
        if body.get(k) is not None:
            args += [f"--{k.replace('_', '-')}", int(body[k])]
    if body.get("taker_addr"):
        args += ["--taker-addr", body["taker_addr"]]
    if CFG.get("ord_url"):     # verify offer backing + keep rune-bearing UTXOs out of funding
        if body.get("rune_block") or body.get("rune_tx"):
            ok, detail = ord_synced()
            if not ok:
                return {"error": "ord not synced — refusing rune-backed swap", "detail": detail}, 503
        args += ["--ord-url", CFG["ord_url"]]
    rc, out, err = run_tool("btx_wallet.py", *args)
    if rc != 0:
        return {"error": "addressed-propose failed", "detail": err or out}, 500
    return _first_json(out), 200


def h_addressed_countersign(body):
    """Maker side: verify output 0 == the agreed price/address, sign the offer input SIGHASH_ALL
    (committing to the WHOLE tx → snipe-resistant), finalize and broadcast."""
    args = ["addressed-countersign", "--bitcoin-cli", CFG["bitcoin_cli"], "--chain", CFG["chain"],
            "--wallet", CFG.get("wallet", "btx"), "--psbt", body["psbt"],
            "--offer-txid", body["offer_txid"], "--offer-vout", int(body["offer_vout"]), "--broadcast"]
    if CFG.get("datadir"):
        args += ["--datadir", CFG["datadir"]]
    if body.get("expect_price_btc") is not None:
        args += ["--expect-price-btc", body["expect_price_btc"]]
    elif body.get("expect_price_sats") is not None:
        args += ["--expect-price-sats", int(body["expect_price_sats"])]
    if body.get("expect_maker_addr"):
        args += ["--expect-maker-addr", body["expect_maker_addr"]]
    rc, out, err = run_tool("btx_wallet.py", *args)
    if rc != 0:
        return {"error": "addressed-countersign failed", "detail": err or out}, 500
    return _first_json(out), 200


def _rune_args(body, keys):
    """Helper: append --rune-a-block/.../--amount-b style flags from body for the rune<->rune commands."""
    args = []
    for k in keys:
        if body.get(k) is not None:
            args += [f"--{k.replace('_', '-')}", int(body[k])]
    return args


def h_rune_propose(body):
    """Taker side of a rune<->rune addressed swap (roadmap #4): build the swap (offer rune A in,
    counter rune B funding in), locate the rune-B UTXO via ord, sign the funding input, emit a PSBT
    for the maker to countersign. Needs the ord oracle to find the counter-rune."""
    if not CFG.get("ord_url"):
        return {"error": "rune<->rune needs the ord oracle (start the bundle with ord)"}, 400
    ok, detail = ord_synced()
    if not ok:
        return {"error": "ord not synced — refusing rune op", "detail": detail}, 503
    args = ["addressed-rune-propose", "--bitcoin-cli", CFG["bitcoin_cli"], "--chain", CFG["chain"],
            "--wallet", CFG.get("wallet", "btx"), "--offer-txid", body["offer_txid"],
            "--offer-vout", int(body["offer_vout"]), "--maker-addr", body["maker_addr"],
            "--ord-url", CFG["ord_url"], "--fee-sats", estimate_fee_sats(400, 10000)]
    if CFG.get("datadir"):
        args += ["--datadir", CFG["datadir"]]
    args += _rune_args(body, ("rune_a_block", "rune_a_tx", "amount_a",
                              "rune_b_block", "rune_b_tx", "amount_b"))
    if body.get("taker_addr"):
        args += ["--taker-addr", body["taker_addr"]]
    rc, out, err = run_tool("btx_wallet.py", *args)
    if rc != 0:
        return {"error": "rune-propose failed", "detail": err or out}, 500
    return _first_json(out), 200


def h_rune_countersign(body):
    """Maker side of a rune<->rune addressed swap: verify (via ord) that output 0 actually receives the
    agreed counter-rune amount, sign the offer input SIGHASH_ALL over the whole tx, finalize, broadcast."""
    if not CFG.get("ord_url"):
        return {"error": "rune<->rune countersign needs the ord oracle"}, 400
    ok, detail = ord_synced()
    if not ok:
        return {"error": "ord not synced — refusing rune op", "detail": detail}, 503
    args = ["addressed-rune-countersign", "--bitcoin-cli", CFG["bitcoin_cli"], "--chain", CFG["chain"],
            "--wallet", CFG.get("wallet", "btx"), "--psbt", body["psbt"],
            "--offer-txid", body["offer_txid"], "--offer-vout", int(body["offer_vout"]),
            "--ord-url", CFG["ord_url"], "--broadcast"]
    if CFG.get("datadir"):
        args += ["--datadir", CFG["datadir"]]
    args += _rune_args(body, ("rune_a_block", "rune_a_tx", "amount_a",
                              "rune_b_block", "rune_b_tx", "amount_b"))
    if body.get("expect_maker_addr"):
        args += ["--expect-maker-addr", body["expect_maker_addr"]]
    rc, out, err = run_tool("btx_wallet.py", *args)
    if rc != 0:
        return {"error": "rune-countersign failed", "detail": err or out}, 500
    return _first_json(out), 200


# ----------------------------- HTTP plumbing -----------------------------
_DEX_READS = {"orders", "groups", "history", "swaps", "trades", "mempool", "book-root", "event-hash", "event-stream"}
# Upstream BRK (Bitcoin Research Kit) routes proxied under /api/brk/<name>. These are on-chain-derived
# data — BTC mark price, recommended fees, mempool depth, difficulty epoch — surfaced in the trade
# terminal so a maker/taker has the context BRK already computes locally from their bitcoin node.
# Slash-containing names (e.g. "fees/recommended") are normalized below before lookup.
_BRK_READS = {"prices", "fees/recommended", "fees/mempool-blocks", "fees/precise", "difficulty-adjustment", "blocks"}
_CONTENT = {".html": "text/html", ".js": "application/javascript", ".css": "text/css",
            ".json": "application/json", ".svg": "image/svg+xml"}


def _allowed_hosts():
    """Host: header values a *loopback* client legitimately sends. btxd binds 127.0.0.1, so the
    only way to reach it is from the local machine — EXCEPT for DNS rebinding: a page on evil.com can
    re-resolve evil.com to 127.0.0.1 and `fetch('http://evil.com:<port>/api/order/fill', ...)`. The TCP
    connection lands on btxd, but the browser still sends `Host: evil.com:<port>` (Host is a
    forbidden header the page can't forge to a loopback name). Allowlisting loopback Host values is the
    standard rebinding guard (bitcoind/geth do the same)."""
    port = CFG.get("port", 3333)
    names = ["127.0.0.1", "localhost", "::1", "[::1]"]
    allowed = set()
    for n in names:
        allowed.add(f"{n}:{port}".lower())
        allowed.add(n.lower())  # lenient: some clients omit an explicit port
    return allowed


def _allowed_origins():
    """Origins a *same-origin* loopback GUI sends on a POST. The Host allowlist stops DNS rebinding, but
    NOT a direct cross-origin POST: a page on evil.com can `fetch('http://127.0.0.1:<port>/api/...',
    {method:'POST'})` — the TCP target is loopback so `Host: 127.0.0.1` PASSES the host guard, and a
    'simple' Content-Type (text/plain) skips the CORS preflight, so a wallet-mutating action executes even
    though the browser blocks reading the response (classic localhost CSRF). Browsers DO attach an
    UNFORGEABLE `Origin` header on cross-origin POSTs, so we allowlist the loopback origins here and reject
    any other present Origin (see Handler._origin_ok)."""
    port = CFG.get("port", 3333)
    return {f"http://{n}:{port}".lower() for n in ("127.0.0.1", "localhost", "[::1]")}


class Handler(BaseHTTPRequestHandler):
    server_version = "btxd/0.1"

    def log_message(self, *a):  # quieter logs
        sys.stderr.write("btxd: " + (a[0] % a[1:]) + "\n")

    def _host_ok(self):
        """Reject any request whose Host: isn't a loopback name (DNS-rebinding / cross-site driving
        of wallet-signing actions). Browsers set Host from the URL and cannot spoof it to a loopback
        name, so this blocks rebinding while leaving the legit 127.0.0.1/localhost GUI working."""
        host = (self.headers.get("Host") or "").strip().lower()
        if host in _allowed_hosts():
            return True
        self._send({"error": "forbidden host",
                    "detail": "btxd only serves loopback Host headers (DNS-rebinding guard)"}, 403)
        return False

    def _origin_ok(self):
        """CSRF guard for mutating POSTs. A cross-origin page that does `fetch(.../api/..., {method:POST})`
        still reaches btxd (Host=127.0.0.1 passes _host_ok; a text/plain body skips the CORS preflight),
        so without this an attacker page the user merely visits could drive wallet-signing actions. The
        browser attaches an Origin header on cross-origin POSTs that JS CANNOT forge, so reject any POST
        whose Origin is present and NOT loopback. Absent Origin = a non-browser local client (curl/CLI),
        which is not a CSRF vector, so it's allowed."""
        origin = (self.headers.get("Origin") or "").strip().lower()
        if origin and origin not in _allowed_origins():
            self._send({"error": "forbidden origin",
                        "detail": "btxd refuses cross-origin POSTs (CSRF guard); Origin must be loopback"}, 403)
            return False
        return True

    def _send(self, obj, code=200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path):
        root = os.path.normpath(UI_DIR)
        full = os.path.normpath(os.path.join(root, path.lstrip("/")))
        # contain to UI_DIR: must be the dir itself or strictly under it (prefix-only would admit a
        # sibling like /x/btx-secrets when UI_DIR=/x/btx)
        if not (full == root or full.startswith(root + os.sep)) or not os.path.isfile(full):
            self._send({"error": "not found"}, 404)
            return
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", _CONTENT.get(os.path.splitext(full)[1], "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _guard(self, fn):
        try:
            return fn()
        except KeyError as e:
            self._send({"error": f"missing field {e}"}, 400)
        except Exception as e:  # noqa
            self._send({"error": type(e).__name__, "detail": str(e)}, 500)
        return None

    def do_GET(self):
        if not self._host_ok():
            return
        p = self.path.split("?", 1)[0]
        if p in ("/", "/index.html"):
            return self._send_file("btx_app.html" if os.path.isfile(os.path.join(UI_DIR, "btx_app.html")) else "index.html")
        if p == "/api/config":
            return self._guard(lambda: self._send(h_config()))
        if p == "/api/node/status":
            return self._guard(lambda: self._send(h_node_status()))
        if p == "/api/wallet":
            return self._guard(lambda: self._send(h_wallet()))
        if p == "/api/mining/info":
            return self._guard(lambda: self._send(h_mining_info()))
        if p == "/api/mining/template":
            return self._guard(lambda: self._send(h_mining_template()))
        if p.startswith("/api/brk/"):
            name = p[len("/api/brk/"):]
            # 1) flat allowlist for the BRK upstream /api/v1/<name> routes
            if name in _BRK_READS:
                return self._guard(lambda: self._send(brk_get(f"/api/v1/{name}") or {}))
            # 2) path-style allowlist for BRK time-series chart data:
            #    /api/brk/series/<series>/<index>/data  ->  /api/series/<series>/<index>/data
            # Restricted to series/<*>/<*>/(data|latest|len) — read-only chart introspection only.
            # Each path component is validated as alphanumeric+underscore so the proxy can never be
            # tricked into hitting an unrelated brk_cli route.
            if name.startswith("series/"):
                parts = name.split("/")
                # series/<name>/<index>/<tail>  where tail in {data, latest, len}
                if (len(parts) == 4
                        and all(c.isalnum() or c == "_" for c in parts[1] + parts[2])
                        and parts[3] in {"data", "latest", "len"}):
                    qs = self.path.split("?", 1)
                    suffix = "?" + qs[1] if len(qs) == 2 else ""
                    return self._guard(lambda: self._send(brk_get(f"/api/{name}{suffix}") or {}))
            return self._send({"error": "unknown brk read"}, 404)
        if p == "/api/dex/book":
            return self._guard(lambda: self._send(h_dex_book()))
        if p.startswith("/api/dex/"):
            name = p[len("/api/dex/"):]
            if name in _DEX_READS:
                return self._guard(lambda: self._send(brk_get(f"/api/v1/btx/{name}")))
            # order-proof/{txid}/{vout}: Merkle membership proof for ONE order (path params). Validate
            # the shape before proxying (txid = 64 hex, vout = digits); brk re-validates too.
            parts = name.split("/")
            if (len(parts) == 3 and parts[0] == "order-proof" and len(parts[1]) == 64
                    and all(c in "0123456789abcdefABCDEF" for c in parts[1]) and parts[2].isdigit()):
                return self._guard(lambda: self._send(brk_get(f"/api/v1/btx/{name}")))
            return self._send({"error": "unknown dex read"}, 404)
        # ---- Supervisor read-through (M3 bundle work) -----------------------
        # The Tauri shell's daemon supervisor publishes its snapshot to a known
        # file inside WSL every ~2s; btxd just reads it. Same for per-daemon
        # log tailing. This sidesteps Tauri 2's permission system for remote
        # URLs (which blocks direct IPC calls from btxd-served pages) — the
        # debug pane in btx_daemons.html uses fetch() against these routes.
        if p == "/api/supervisor/status":
            def _read_status():
                try:
                    with open("/tmp/btx-supervisor.json", "r") as f:
                        import json as _json
                        return _json.load(f)
                except (OSError, ValueError):
                    return {"error": "supervisor status not yet written"}
            return self._guard(lambda: self._send(_read_status()))
        if p == "/api/supervisor/logs":
            # /api/supervisor/logs?name=<daemon>&n=<lines>
            qs = self.path.split("?", 1)
            name = ""
            n = 100
            if len(qs) == 2:
                from urllib.parse import parse_qs as _pq
                params = _pq(qs[1])
                name = (params.get("name", [""])[0] or "").strip()
                try:
                    n = max(1, min(2000, int(params.get("n", ["100"])[0])))
                except ValueError:
                    n = 100
            # Daemon-name allowlist: prevents path traversal via name=...
            if name not in {"bitcoind", "brk_cli", "ord", "btxd"}:
                return self._send({"error": "unknown daemon"}, 400)
            def _tail():
                path = f"/tmp/btx-{name}.log"
                try:
                    with open(path, "r") as f:
                        lines = f.readlines()
                    return {"lines": [l.rstrip("\n") for l in lines[-n:]]}
                except OSError:
                    return {"lines": []}
            return self._guard(lambda: self._send(_tail()))
        if p.endswith((".html", ".js", ".css", ".svg")):
            return self._send_file(p)
        self._send({"error": "not found", "path": p}, 404)

    def do_POST(self):
        if not self._host_ok():
            return
        if not self._origin_ok():   # CSRF guard: reject cross-origin wallet-mutating POSTs
            return
        p = self.path.split("?", 1)[0]
        ln = int(self.headers.get("Content-Length", 0) or 0)
        if ln < 0 or ln > MAX_BODY:   # reject oversized/negative BEFORE allocating (unbounded-read DoS)
            return self._send({"error": "request body too large", "max_bytes": MAX_BODY}, 413)
        try:
            body = json.loads(self.rfile.read(ln) or b"{}")
        except json.JSONDecodeError:
            return self._send({"error": "invalid JSON body"}, 400)
        routes = {
            "/api/wallet/newaddress": lambda: (h_newaddress(), 200),
            "/api/mining/generate": lambda: h_mining_generate(body),
            "/api/order/create": lambda: h_order_create(body),
            "/api/order/fill": lambda: h_order_fill(body),
            "/api/swap/batch-fill": lambda: h_batch_fill(body),
            "/api/rune/etch": lambda: h_rune_etch(body),
            "/api/swap/propose": lambda: h_addressed_propose(body),
            "/api/swap/countersign": lambda: h_addressed_countersign(body),
            "/api/swap/rune-propose": lambda: h_rune_propose(body),
            "/api/swap/rune-countersign": lambda: h_rune_countersign(body),
        }
        if p not in routes:
            return self._send({"error": "not found", "path": p}, 404)

        def run():
            res = routes[p]()
            obj, code = res if isinstance(res, tuple) else (res, 200)
            self._send(obj, code)
        # Serialize all wallet-mutating POSTs (see _WALLET_LOCK): closes the funding-UTXO TOCTOU between
        # concurrent requests. The request body is already read above (per-connection, no shared state),
        # so only the wallet-touching dispatch is inside the lock.
        with _WALLET_LOCK:
            self._guard(run)


def main():
    ap = argparse.ArgumentParser(prog="btxd", description="BTX local orchestrator")
    ap.add_argument("--bitcoin-cli", default="bitcoin-cli")
    ap.add_argument("--chain", default="signet")
    ap.add_argument("--datadir")
    ap.add_argument("--wallet", default="btx")
    ap.add_argument("--brk-url", default="http://127.0.0.1:3110")
    ap.add_argument("--ord-url", help="local ord server URL (rune oracle); when set, rune orders "
                                      "must be backed by the offer UTXO (maker-sign --require-rune-backing)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=3333)
    ap.add_argument("--max-hot-balance-btc", type=float,
                    help="refuse to start if the wallet's spendable balance exceeds this (BTC) — a "
                         "misconfiguration rail so btxd isn't pointed at a primary store of value "
                         "(it signs with no per-action consent). Off by default; see "
                         "BTX-mainnet-hardening.md 'blast radius'.")
    a = ap.parse_args()
    CFG.update(bitcoin_cli=a.bitcoin_cli, chain=a.chain, datadir=a.datadir, wallet=a.wallet,
               brk_url=a.brk_url, ord_url=a.ord_url, port=a.port, bind_host=a.host)
    # Best-effort: make sure the wallet is loaded so the GUI's wallet panel works out of the box
    # (a "non-dev installs once" product shouldn't require a manual loadwallet). Harmless if the node
    # is down, the wallet is already loaded, or it doesn't exist yet — just logged.
    if a.wallet:
        try:
            bcli("loadwallet", a.wallet)
            print(f"  loaded wallet '{a.wallet}'")
        except RuntimeError as e:
            print(f"  (wallet '{a.wallet}' not auto-loaded: {str(e).splitlines()[0][:90]})")
    # Blast-radius guardrail (BTX-mainnet-hardening.md "blast radius"): btxd drives the wallet to
    # sign/spend with NO per-action consent, so a compromised btxd — or any local process that can POST
    # to it — can spend the entire loaded wallet (threat-model item e). This operationalizes the
    # "use a dedicated thin wallet" guidance: refuse to start against a wallet whose spendable balance
    # exceeds --max-hot-balance-btc. It is a MISCONFIGURATION rail (so you can't accidentally point btxd
    # at a primary store of value), NOT an anti-compromise control — a compromised btxd bypasses it.
    # Cryptographic bounding needs a 2-of-2 policy cosigner or a covenant (see the doc). Off by default.
    if a.max_hot_balance_btc is not None and a.wallet:
        try:
            bals = bcli("getbalances", wallet=True)
            spendable = float((bals or {}).get("mine", {}).get("trusted", 0) or 0)
            if spendable > a.max_hot_balance_btc:
                sys.exit(
                    f"btxd: wallet '{a.wallet}' spendable balance {spendable:.8f} BTC exceeds the "
                    f"--max-hot-balance-btc cap ({a.max_hot_balance_btc}). Refusing to start.\n"
                    f"  BTX signs with no per-action consent, so run it against a DEDICATED thin wallet "
                    f"holding only your trading float (see BTX-mainnet-hardening.md). Raise --max-hot-"
                    f"balance-btc if this balance is intended.")
        except RuntimeError as e:
            print(f"  (balance guardrail skipped: {str(e).splitlines()[0][:80]})")
    # restart-safe: re-lock the offer UTXOs of any still-open orders so coin selection can't spend them
    # (Core's locked-coin set is in-memory and cleared on restart). See BTX-mainnet-hardening.md #2.
    relock_open_offers()
    try:
        srv = ThreadingHTTPServer((a.host, a.port), Handler)
    except OSError as e:
        # the only foreseeable hard-startup failure left: the port is already taken (btxd already
        # running, or another service on it). Give a clean message instead of a bind traceback.
        sys.exit(f"btxd: cannot bind {a.host}:{a.port} — {e}\n"
                 f"  (already running? try a different --port, or './run stop')")
    print(f"btxd on http://{a.host}:{a.port}  (chain={a.chain} wallet={a.wallet} brk={a.brk_url})")
    print("  open the GUI in a browser at the URL above; Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbtxd stopping")
        srv.shutdown()


if __name__ == "__main__":
    main()
