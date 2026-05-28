#!/usr/bin/env python3
"""Offline test of the addressed-swap maker-side verification (no node).

Run in WSL:  python3 _addressed_test.py
Covers verify_addressed_tx: the check a maker runs before countersigning a taker's PSBT. The full
PSBT signing round-trip needs a live regtest node (see the runbook); this proves the deal-matching
logic that gates the SIGHASH_ALL countersignature."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import btx_wallet as W
from bitcoin.core import COIN

OK = True
def check(name, cond, detail=""):
    global OK; OK = OK and bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))

OFFER = "aa" * 32
PAYOUT = "0014" + "22" * 20
PRICE = 10000  # sats

def decoded(price_sats=PRICE, in_txid=OFFER, in_vout=0, spk=PAYOUT, extra_outs=0):
    vout = [{"value": price_sats / COIN, "scriptPubKey": {"hex": spk}}]
    for i in range(extra_outs):
        vout.append({"value": 0.001, "scriptPubKey": {"hex": "0014" + "%02x" % i * 20}})
    return {"vin": [{"txid": in_txid, "vout": in_vout}], "vout": vout}

# the happy path: input 0 is the agreed offer, output 0 pays the agreed price to the maker
ok, why = W.verify_addressed_tx(decoded(extra_outs=2), OFFER, 0, PRICE, PAYOUT)
check("accepts the agreed deal", ok, why)

# wrong price -> reject (this is the maker's core protection)
ok, _ = W.verify_addressed_tx(decoded(price_sats=5000), OFFER, 0, PRICE, PAYOUT)
check("rejects underpaying output 0", not ok)

# output 0 pays a DIFFERENT address -> reject (a taker can't redirect the maker's proceeds)
ok, _ = W.verify_addressed_tx(decoded(spk="0014" + "33" * 20), OFFER, 0, PRICE, PAYOUT)
check("rejects wrong payout script", not ok)

# input 0 is not the maker's offer -> reject (can't trick the maker into signing a different UTXO)
ok, _ = W.verify_addressed_tx(decoded(in_txid="bb" * 32), OFFER, 0, PRICE, PAYOUT)
check("rejects wrong offer input", not ok)

# vout=0 vs agreed vout=1 -> reject
ok, _ = W.verify_addressed_tx(decoded(in_vout=0), OFFER, 1, PRICE, PAYOUT)
check("rejects wrong offer vout", not ok)

# payout-spk check is optional (maker may verify by price+offer alone)
ok, why = W.verify_addressed_tx(decoded(), OFFER, 0, PRICE, None)
check("payout check skipped when no spk given", ok, why)

# empty / malformed -> reject, no crash
ok, _ = W.verify_addressed_tx({}, OFFER, 0, PRICE, PAYOUT)
check("rejects empty tx without crashing", not ok)

print("ALL_PASS" if OK else "FAILURES ABOVE")
sys.exit(0 if OK else 1)
