#!/usr/bin/env python3
"""Offline regression test for btx_wallet._pick_p2wpkh_utxo (funding selection).

Locks in the two funding fixes found while proving the addressed swap on signet:
  - swap FUNDING must accept Taproot (P2TR) UTXOs, not just P2WPKH (Core's modern change default);
  - OFFER selection must stay P2WPKH-only (the maker-sig path is P2WPKH-specific).
Pure: _pick_p2wpkh_utxo takes a UTXO list + filters, no node. Run in WSL: python3 btx_funding_test.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import btx_wallet as W
from bitcoin.core import COIN

OK = True
def check(name, cond, detail=""):
    global OK; OK = OK and bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))

P2WPKH = "0014" + "11" * 20      # witness v0 keyhash
P2TR   = "5120" + "22" * 32      # witness v1 taproot
def u(txid, vout, sats, spk):
    return {"txid": txid, "vout": vout, "amount": sats / COIN, "scriptPubKey": spk}

OFFER = "ff" * 32 + ":0"

# --- the exact signet scenario: offer is P2WPKH (and excluded), the only funding >= want is Taproot ---
unspent = [
    u("ff" * 32, 0, 98000, P2WPKH),   # the offer (P2WPKH) — excluded from funding
    u("aa" * 32, 0, 10000, P2WPKH),   # P2WPKH but BELOW want (price+fee=11000)
    u("bb" * 32, 1, 12747, P2TR),     # Taproot change — the only rune-free funding >= want
    u("cc" * 32, 1, 12972, P2TR),     # another Taproot change
]
WANT = 11000

# 1) the bug: with allow_taproot=False, taproot funding is dropped -> nothing fundable
got = W._pick_p2wpkh_utxo(unspent, want_sats=WANT, exclude={OFFER}, allow_taproot=False)
check("regression: P2WPKH-only funding finds nothing (the old bug)", got is None)

# 2) the fix: with allow_taproot=True, the taproot UTXO is selected
got = W._pick_p2wpkh_utxo(unspent, want_sats=WANT, exclude={OFFER}, allow_taproot=True)
check("fix: taproot funding is selected", got is not None and got["scriptPubKey"] == P2TR, str(got))
check("fix: picks the cheapest qualifying (12747 before 12972)",
      got is not None and abs(got["amount"] * COIN - 12747) < 1, str(got and got["amount"]))

# 3) offer-selection stays P2WPKH-only (allow_taproot defaults False): a taproot-only wallet yields none
tponly = [u("dd" * 32, 0, 50000, P2TR)]
check("offer-pick ignores taproot (P2WPKH-only)", W._pick_p2wpkh_utxo(tponly, want_sats=1000) is None)
check("offer-pick takes P2WPKH", W._pick_p2wpkh_utxo([u("ee"*32,0,50000,P2WPKH)], want_sats=1000) is not None)

# 4) exclude removes the offer from BOTH pools
only_offer = [u("ff" * 32, 0, 98000, P2WPKH)]
check("exclude drops the offer", W._pick_p2wpkh_utxo(only_offer, want_sats=1000, exclude={OFFER}) is None)

# 5) want_sats floor respected
check("below-want is rejected", W._pick_p2wpkh_utxo([u("aa"*32,0,5000,P2WPKH)], want_sats=11000) is None)

# 6) reject hook (rune-safety) excludes a rune-bearing UTXO even if big enough
runed = {"bb" * 32 + ":1"}
got = W._pick_p2wpkh_utxo(unspent, want_sats=WANT, exclude={OFFER}, allow_taproot=True,
                          reject=lambda op: op in runed)
check("reject hook skips rune-bearing funding, takes the next", got is not None and got["txid"] == "cc" * 32, str(got))

# 7) cheapest-first ordering among P2WPKH
pool = [u("a1"*32,0,30000,P2WPKH), u("a2"*32,0,12000,P2WPKH), u("a3"*32,0,20000,P2WPKH)]
got = W._pick_p2wpkh_utxo(pool, want_sats=11000)
check("cheapest qualifying chosen", got is not None and abs(got["amount"]*COIN-12000) < 1, str(got and got["amount"]))

print("ALL_PASS" if OK else "FAILURES ABOVE")
sys.exit(0 if OK else 1)
