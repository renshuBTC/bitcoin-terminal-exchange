# BTX — seeding a real order (public signet, with mainnet caveats)

How to publish your first real on-chain order so the book/UI aren't empty, and — on public signet —
test the one thing custom-signet couldn't: **does the order actually propagate across foreign nodes
under default relay policy.**

> Read the cautions before touching mainnet. On mainnet a published order is real BTC: if a taker
> fills it, the trade happens for real and irreversibly. Don't publish a mainnet order just to
> populate a demo — use signet. Items marked **[verify]** depend on your version/network state.

## Why public signet (not custom signet)
The earlier custom-signet run (`BTX-signet-validation.md`) proved indexing + the full lifecycle, but
you were the only node and set your own policy, so it could NOT test propagation. Public signet has
many real nodes and a fixed signer, so it answers: will a `BTX1` carrier relay and get mined under
default policy? That's the remaining real-world unknown.

Trade-off: on public signet you can't self-mine (a signer produces blocks ~every 10 min), you need
faucet coins, and a from-scratch `brk_cli` sync indexes ~250k+ blocks (a few GB, not instant — but far
lighter than mainnet).

## Prerequisites
- `bitcoind`/`bitcoin-cli` — **v30+ recommended** (OP_RETURN ≤100KB relays by default). On v29.1 the
  OP_RETURN carrier needs `-datacarriersize=240` locally and may not relay to default-policy peers;
  the Taproot envelope carrier avoids this. **[verify]** your version.
- The `brk-btx` fork built (`cargo build -p brk_cli`).
- A few GB free for the signet datadir + brkdir.
- Signet coins from a faucet **[verify a faucet is live]** (e.g. signetfaucet.com / alt.signetfaucet.com).

## Steps (public signet)

```bash
SD=/tmp/sig-public; BIN=/tmp/bitcoin-29.1/bin   # or your v30 bin
CLI="$BIN/bitcoin-cli -signet -datadir=$SD"
mkdir -p $SD
# 1. start PUBLIC signet (no signetchallenge => default signet, magic 0a03cf40). Add datacarriersize
#    only if pre-v30 and you want the OP_RETURN carrier.
$BIN/bitcoind -signet -datadir=$SD -txindex=1 -datacarrier=1 -datacarriersize=240 -fallbackfee=0.0002 -server -daemon
# 2. wait for headers+blocks to sync (watch verificationprogress -> ~1.0; minutes, depends on peers)
watch -n5 "$CLI getblockchaininfo | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d[\"blocks\"], round(d[\"verificationprogress\"],4))'"
```

Once synced:

```bash
$CLI createwallet btx
ADDR=$($CLI getnewaddress "" bech32)
echo "fund this address from a signet faucet: $ADDR"
# ... paste ADDR into a signet faucet, wait for the funding tx to confirm (~10 min) ...
$CLI listunspent 1 9999999 "[\"$ADDR\"]"     # confirm a spendable P2WPKH UTXO arrived
```

Then maker-sign + publish (reuse the proven tooling; envelope is the safer carrier for propagation):

```bash
cd "<Bitcoin Terminal Exchange folder>"
# pick the funded UTXO as the offer:
OFFER_TXID=<from listunspent>; OFFER_VOUT=<n>
python3 btx_wallet.py maker-sign --bitcoin-cli "$BIN/bitcoin-cli" --chain signet \
  --datadir "$SD" --wallet btx --offer-txid "$OFFER_TXID" --offer-vout "$OFFER_VOUT" \
  --price-btc 0.001 --carrier envelope        # small price; envelope carrier
# -> artifact_hex. Publish:
#   OP_RETURN path (v30 default, or pre-v30 with datacarriersize=240): createrawtransaction data + fund + sign + send
#   Envelope path: `python3 btx_envelope_publish.py publish --artifact-hex <hex> ... --broadcast`
#   funds the commit + builds/signs/broadcasts the reveal (witness data, relays under default policy).
#   See BTX-envelope-publish-runbook.md. On-node acceptance proves the BIP341 script-path sighash.
```

Watch propagation (this is the real test):

```bash
$CLI sendrawtransaction <signed_carrier_hex>   # if it errors with datacarrier/scriptpubkey -> policy rejected it
$CLI getmempoolentry <announce_txid>           # in OUR mempool
# the real question is whether PEERS accept it: after a signet block (~10 min), check it confirmed:
$CLI getrawtransaction <announce_txid> true | python3 -c "import sys,json;print('confirmations',json.load(sys.stdin).get('confirmations'))"
```

Index + serve + view:

```bash
cd "<brk-btx>"
BRK_BLOCK_MAGIC=0a03cf40 cargo run -p brk_cli -- \
  --brkdir /tmp/brk-btx-public-signet \
  --blocksdir $SD/signet/blocks \
  --rpcconnect 127.0.0.1 --rpcport 38332 --rpccookiefile $SD/signet/.cookie --brkport 3110
# NOTE: first run indexes ~250k blocks — give it time. Then:
curl -s http://127.0.0.1:3110/api/v1/btx/orders | jq      # your order, reconstructed
# open index.html / btx_book.html, set API base to http://127.0.0.1:3110
```

## Outcome this proves
- The carrier **propagated and confirmed under default policy** (or which carrier did — likely the
  envelope on mixed-version nodes; OP_RETURN on a v30 network).
- `brk_cli` indexes the **public signet** chain and serves your real order.
- The book/UI show real data.

> **RESULT — PROVEN on public signet 2026-05-24.** A BTX order published via the **witness-envelope
> carrier** (commit `964e0678…`, reveal `60e969a3ad65a182faabf8e61f0902aeb607b50c53f7ca1be56e483faf9a63e3`)
> was accepted + relayed by a v29.1 node under **default policy** and **mined by a public-signet
> signer** (block 305837) — so the inscription-style reveal propagates across foreign nodes with no
> `-datacarriersize` relaxation. Corroborating finding: the faucet's own multi-`OP_RETURN` payout tx
> was rejected by the v29.1 mempool (pre-v30 allows only one `OP_RETURN`) and only appeared once mined
> — which is exactly why BTX uses the single-tx witness envelope rather than a multi-output carrier.
> (Practical note: maker-sign locks the offer UTXO, so you need a **second** UTXO to fund the commit —
> split the faucet UTXO first.)

## Mainnet caveats (read before considering it)
- **Real money, irreversible.** A mainnet order offers a real UTXO at a real price; a taker can fill it
  and the swap settles for real. Use a tiny amount and only if you intend a real offer — not for a demo.
- **Sync cost.** A from-scratch `brk-btx` mainnet sync is hundreds of GB and takes a long time; it's a
  separate index from your analytics node. Don't spin one up casually.
- **The swaps feed (`/api/v1/btx/swaps`)** only shows meaningful data on mainnet, where pre-signed PSBT
  trades actually occur; signet has little such activity. So the swaps view stays sparse on signet.

## Honest bottom line
Signet seeding makes the BTX book non-empty and answers the propagation question — genuinely useful.
But it doesn't change the demand side: an order book is only interesting if others publish and fill
orders, and that requires actual users, which no seeding step provides.
