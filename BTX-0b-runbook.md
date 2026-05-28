# BTX Milestone 0b — Runbook (pure chain-reconstructed order, no relay)

Goal of 0b (the real Phase 0 exit gate): a **second node, given only the chain and no messaging
channel**, finds the maker's order and completes the atomic swap. This runbook is meant for a
stable full node (e.g. the Hetzner box), because the Cowork sandbox could not keep `bitcoind`
alive long enough to run it.

## What is already proven (offline, this session)
`btx_0b.py selftest` passed all checks against `python-bitcoinlib`:

- A party holding **only the BTX artifact bytes + the offer UTXO amount** can VERIFY the maker's
  `SIGHASH_SINGLE|ANYONECANPAY` signature (`maker_sig_verifies_from_chain_data: true`).
- Tampering the price inside the artifact makes the signature FAIL
  (`tampered_price_sig_fails: true`) — the order terms are signature-bound.
- The swap rebuilt purely from artifact data transplants the maker's witness into input 0 and
  reproduces the committed payout output (`swap_input0_witness_is_artifact_sig: true`,
  `swap_output0_is_committed_payout: true`).
- BTX v1 artifact size: **~200 bytes** (includes 33-byte maker pubkey + ~72-byte DER sig).

What is NOT yet proven and is the point of this runbook: the *on-node* path — publishing the
artifact in a real transaction, having a second `bitcoind` re-derive the order from blocks it
synced over P2P, and broadcasting the completed swap.

## Prerequisites on the node
- Bitcoin Core (v29.x ok) with `txindex=1`.
- `OP_RETURN` carrier: the artifact is ~200 bytes, so set `-datacarriersize=240` (or larger) in
  `bitcoin.conf`. **If your policy must keep the 80-byte limit, switch the carrier to a Taproot
  inscription-style envelope** — the reconstruction logic in `btx_0b.py` is unchanged because
  it parses the artifact bytes, not the carrier.
- `pip install python-bitcoinlib --break-system-packages`
- Copy `btx_0b.py` to the node.

## Procedure
1. **Two independent datadirs, connected only by P2P block sync** (this is what makes it a real
   no-relay test — no shared files, no order relay):
   - Node A (maker) and Node B (taker), e.g. `-datadir=/srv/nodeA` and `/srv/nodeB`, with
     `B addnode=A` for block propagation only.
2. **Fund** the maker offer UTXO (P2WPKH for the `btx-maker` key in `btx_0b.py`) and the
   taker payment UTXO. In production the offer UTXO also carries the rune (see `btx_runes.py`).
3. **Maker announces (Node A):**
   - `ART=$(python3 btx_0b.py artifact '{"offer":{"txid":"<OFFER_TXID>","vout":<V>,"amount_btc":1.0},"price_btc":0.5}')`
   - Build a tx with the `carrier_op_return_spk_hex` as a 0-value output, sign+broadcast it on A,
     mine 1 block. The offer UTXO stays UNSPENT.
4. **Taker reconstructs (Node B) — the exit-gate check:**
   - Let B sync the block over P2P. On B, run the indexer over new blocks: for each tx, look for
     a `6a...42545831` (`OP_RETURN ... "BTX1"`) output, `parse_artifact`, then fetch the offer
     UTXO amount via B's own `gettxout <offer_txid> <vout>` and call `verify_maker_sig`.
   - **PASS condition:** B surfaces the open order with correct terms and a verified maker sig,
     using only data it pulled from the chain.
5. **Taker completes (Node B):** `build_swap_from_artifact(...)` with B's payment UTXO, then
   `sendrawtransaction`, mine 1 block on B.
   - **PASS condition:** the swap confirms; offer UTXO spent; maker payout = committed price;
     rune (if present) lands on the taker output per the runestone edict (`btx_runes.py`).

## Exit gate (do not declare Phase 0 done until all hold)
- [ ] Step 4 succeeds on a node with **no messaging channel** to the maker (P2P block sync only).
- [ ] Signature-rebinding negative test: alter the maker payout in the completion tx -> rejected
      (`mandatory-script-verify-flag-failed`) — already shown in Milestone 0a.
- [ ] Double-take race: two takers spend the same offer UTXO -> exactly one confirms.
- [ ] Reorg: `invalidateblock` the fill -> indexer returns the order to OPEN.
- [ ] Validate rune movement with canonical `ord`, not just the simplified indexer.

## Files
- `btx_0b.py` — artifact serialize/parse, on-chain verify, swap build, `selftest`.
- `btx_runes.py` — runestone encode + minimal edict indexer (the asset leg).
- `swap_test.py` / `run_swap.sh` — Milestone 0a (validated on-node this session).
- `BTX-phase0-spec.md` — the spec these implement.
