"""Offline proof of the exact Fill/Cancel classifier (no node needed).

Rule: a CONFIRMED tx spending the order's offer UTXO is a FILL iff its output 0 equals exactly
(price_sats, payout_spk). This is not a heuristic: the maker's SINGLE|ANYONECANPAY signature
consensus-enforces output 0, so a confirmed swap MUST carry the committed payout. A spend that
lacks it can only be the maker spending their own UTXO with a different signature -> CANCEL.
"""
import json
from bitcoin.core import COIN, CMutableTransaction, CMutableTxIn, CMutableTxOut, COutPoint, lx, b2x
import btx_0b as c

def classify_spend(spend_tx_outputs, art):
    """spend_tx_outputs: list of (value_sats, scriptPubKey_bytes) for the spending tx.
       art: parsed BTX artifact. Returns 'FILL' or 'CANCEL'."""
    if not spend_tx_outputs:
        return 'CANCEL'
    v0, spk0 = spend_tx_outputs[0]
    return 'FILL' if (v0 == art['price'] and bytes(spk0) == bytes(art['payout_spk'])) else 'CANCEL'

# build an artifact + the canonical fill tx from it (reuses validated 0b builder)
offer_txid, offer_vout = 'aa'*32, 0
offer_amt, price, pay_amt = int(1.0*COIN), int(0.5*COIN), int(0.6*COIN)
art = c.parse_artifact(c.serialize_artifact(c.make_artifact(offer_txid, offer_vout, offer_amt, price)))

fill_tx = c.build_swap_from_artifact(art, offer_amt, ('bb'*32, 1), pay_amt, b'btx-taker')
fill_outputs = [(o.nValue, bytes(o.scriptPubKey)) for o in fill_tx.vout]

# a CANCEL tx: maker spends the offer UTXO back to themselves, no committed-payout output
_, maker_offer_spk = c.key(b'btx-maker')
cancel_tx = CMutableTransaction(
    [CMutableTxIn(COutPoint(lx(offer_txid), offer_vout))],
    [CMutableTxOut(offer_amt - 1000, maker_offer_spk)])  # back to self
cancel_outputs = [(o.nValue, bytes(o.scriptPubKey)) for o in cancel_tx.vout]

# adversarial: a spend whose output0 pays the payout SPK but a WRONG (too-low) amount.
# Such a tx could never confirm with the maker's pre-sig (sig commits the exact price), so if it
# appears it isn't using the maker's authorization -> must classify as CANCEL, not a fill.
wrong_amt_outputs = [(int(0.4*COIN), bytes(art['payout_spk']))]

r_fill   = classify_spend(fill_outputs, art)
r_cancel = classify_spend(cancel_outputs, art)
r_wrong  = classify_spend(wrong_amt_outputs, art)
print(json.dumps({
  "fill_tx_classified":   r_fill,   # expect FILL
  "cancel_tx_classified": r_cancel, # expect CANCEL
  "wrong_amount_classified": r_wrong, # expect CANCEL (not a valid fill)
  "ALL_PASS": r_fill=='FILL' and r_cancel=='CANCEL' and r_wrong=='CANCEL'
}, indent=2))
