#!/usr/bin/env python3
"""Offline test of btx_etch's signet/regtest control flow (no node, no crypto).

Run in WSL:  python3 _etch_signet_test.py
Exercises the commit/reveal split: state round-trip, conf-gating on signet (refuse reveal < 6 confs),
regtest matures-by-mining, and that a mature commit broadcasts the reveal. build_etch_reveal is stubbed
so we test the orchestration, not the (separately-tested) BIP341 crypto."""
import sys, os, json, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import btx_etch as E
import btx_envelope_publish as P   # cmd_etch_reveal does `from btx_envelope_publish import CLI`

def patch_cli(cli):
    """Make the function-local `from btx_envelope_publish import CLI` resolve to our fake."""
    P.CLI = lambda *x, **k: cli

OK = True
def check(name, cond, detail=""):
    global OK; OK = OK and bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))

class FakeCLI:
    """Stand-in for btx_envelope_publish.CLI: records calls, returns canned values. `confs` controls
    what getrawtransaction reports so we can drive the maturity gate."""
    def __init__(self, confs=0):
        self.confs = confs
        self.calls = []
    def __call__(self, method, *args):
        self.calls.append((method, args))
        if method == "getrawtransaction":
            return {"confirmations": self.confs,
                    "vout": [{"n": 0, "value": 0.00098, "scriptPubKey": {"hex": "5120" + "11"*32}}]}
        if method == "getnewaddress":
            return "tb1qfakefreshaddr"
        if method == "getaddressinfo":
            return {"scriptPubKey": "0014" + "22"*20}   # a valid-looking P2WPKH spk
        if method == "sendrawtransaction":
            return "reveal_txid_deadbeef"
        if method == "sendtoaddress":
            return "commit_txid_cafe"
        if method == "generatetoaddress":
            return ["blockhash"]
        return None
    def count(self, method):
        return sum(1 for m, _ in self.calls if m == method)

# stub the crypto-heavy reveal builder; we only assert orchestration here
E.build_etch_reveal = lambda **kw: {"reveal_hex": "0200000000", "out0_value_sats": 98000}

ST = {"rune": "BTXUSDTESTAAAAA", "rune_number": E.rune_number("BTXUSDTESTAAAAA"),
      "chain": "signet", "commit_txid": "commit_txid_cafe", "commit_vout": 0,
      "commit_value_sats": 100000, "commit_address": "tb1pfake", "premine": 1000,
      "divisibility": 0, "symbol": "$", "spacers": 0, "fee_sats": 2000,
      "premine_addr": None, "seckey_hex": "11"*32}

def ns(**kw):
    base = dict(state_file=None, seckey=None, rune=None, commit_txid=None, commit_vout=None,
                commit_value_sats=None, premine=1000, divisibility=0, symbol="$", spacers=0,
                fee_sats=2000, premine_addr=None, mine_to=None, bitcoin_cli="bitcoin-cli",
                chain="signet", datadir=None, wallet=None, dry_run=False)
    base.update(kw)
    return types.SimpleNamespace(**base)

# 1) signet reveal under 6 confs must REFUSE (SystemExit), and must NOT broadcast
def run_reveal(cli, a, stfile):
    with open(stfile, "w") as f: json.dump(ST, f)
    a.state_file = stfile
    out = {}
    try:
        patch_cli(cli)
        E.cmd_etch_reveal(a)
        out["exit"] = None
    except SystemExit as e:
        out["exit"] = e.code
    return out

stfile = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_etch_state_test.json")

cli_imm = FakeCLI(confs=2)
r = run_reveal(cli_imm, ns(chain="signet"), stfile)
check("signet: reveal refused at 2/6 confs (SystemExit)", r["exit"] not in (None, 0))
check("signet: no reveal broadcast when immature", cli_imm.count("sendrawtransaction") == 0)

# 2) signet reveal at >=6 confs broadcasts exactly once, mines zero blocks
cli_mature = FakeCLI(confs=6)
r = run_reveal(cli_mature, ns(chain="signet"), stfile)
check("signet: mature commit reveals (no SystemExit)", r["exit"] in (None,))
check("signet: reveal broadcast once", cli_mature.count("sendrawtransaction") == 1)
check("signet: no generatetoaddress on signet", cli_mature.count("generatetoaddress") == 0)

# 3) regtest reveal under 6 confs matures by MINING, then broadcasts + mines the reveal
st_rt = dict(ST); st_rt["chain"] = "regtest"
with open(stfile, "w") as f: json.dump(st_rt, f)
cli_rt = FakeCLI(confs=1)
a_rt = ns(chain="regtest", state_file=stfile)
try:
    patch_cli(cli_rt)
    E.cmd_etch_reveal(a_rt); rt_exit = None
except SystemExit as e:
    rt_exit = e.code
check("regtest: reveal succeeds by mining maturity (no SystemExit)", rt_exit in (None,))
check("regtest: mined to mature + confirm reveal (>=2 generatetoaddress)", cli_rt.count("generatetoaddress") >= 2)
check("regtest: reveal broadcast once", cli_rt.count("sendrawtransaction") == 1)

# 4) _etch_state carries everything etch-reveal needs
a = ns(rune="BTXUSDTESTBBBBB", chain="signet")
seck = bytes.fromhex("33"*32)
commit = {"commit_txid": "c", "commit_vout": 1, "commit_value_sats": 99000, "commit_address": "tb1pc"}
state = E._etch_state(a, E.rune_number(a.rune), seck, commit)
for k in ("rune", "rune_number", "commit_txid", "commit_vout", "commit_value_sats", "seckey_hex",
          "premine", "divisibility", "symbol", "spacers", "fee_sats"):
    check(f"_etch_state has {k}", k in state)
check("_etch_state seckey_hex matches", state["seckey_hex"] == "33"*32)

# 5) flag-driven reveal without state-file requires the commit fields
cli_x = FakeCLI(confs=6)
a_missing = ns(chain="signet", state_file=None, seckey="11"*32, rune="BTXUSDTESTCCCCC")
try:
    patch_cli(cli_x)
    E.cmd_etch_reveal(a_missing); m_exit = None
except SystemExit as e:
    m_exit = e.code
check("flag-driven reveal without commit fields errors", m_exit not in (None, 0))

try: os.remove(stfile)
except OSError: pass

print("ALL_PASS" if OK else "FAILURES ABOVE")
sys.exit(0 if OK else 1)
