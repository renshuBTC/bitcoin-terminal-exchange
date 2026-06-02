# BTX on Bitcoin mainnet — a 568-sat proof

*Case study, 2026-06-02. Bitcoin Terminal Exchange (BTX) is a server-less,
on-chain order-book DEX. After roughly two months of regtest + signet proofs,
the carrier shipped on mainnet for 568 sats in fees. This is the empirical
record and what it proves.*

## TL;DR

A test-rune order announce was broadcast via BTX's Taproot witness-envelope
carrier on Bitcoin mainnet on 2026-06-02 ~04:40 UTC. Both the commit and
reveal landed in the **same block** — 952071, at 04:46:32 UTC — about six
minutes after broadcast. The reveal's witness[1] tapscript contains the
207-byte BTX1 artifact starting at byte offset 38; the bytes
`42545831...` are the BTX magic, version 2, runestone-flag mode.

Three independent third-party node operators — mempool.space,
blockstream.info, and bitaps.com — confirmed the same reveal in the same
block. The artifact is now on Bitcoin's canonical chain history and will
remain there as long as the chain itself does.

Total mainnet cost: 568 sats fees + 5,460 commit dust (5,057 of which
came back as the reveal output to my wallet). Net spend ≈ 971 sats —
roughly $0.60.

## What "BTX on mainnet" actually means

BTX is not a token, not an exchange, not a server. The protocol is two
pieces:

1. **An on-chain artifact format** — a 207-byte BTX1 record carrying a
   maker's `SIGHASH_SINGLE|ANYONECANPAY` pre-signature, the offer UTXO
   reference, the price, and (optionally) a rune identifier.
2. **An indexer** — a fork of BRK (Bitcoin Research Kit) that reads
   artifacts from on-chain witness/OP_RETURN data, reconstructs the order
   book deterministically, and serves it over an HTTP API. Because the
   book is a pure function of chain data, any independent indexer over the
   same chain produces the byte-identical book.

The 2026-06-02 broadcast proves the first piece reaches and survives the
Bitcoin mainnet relay graph under Core v30 default policy. The second
piece has already been proven byte-identical across two indexer
implementations (Python reference + Rust production) on regtest and
signet; the third-party verification of the on-chain bytes (BTX1 magic
at byte 38, artifact head matching `425458310201007f969800010001...`)
removes the remaining "but it's only been tested off-mainnet" caveat.

## The transaction record

```
commit_txid: 199ac25126f363ecb0380a84419ad15399a57bb5ed8d7bd258212cb0a2ed633e
reveal_txid: 8acf6c70b2c1d75153374ab52f57b6da69ae7606a5931ba295d8cb5dd477f84c
block:       952071
block_hash:  000000000000000000017f61a793597418f69b967626d48b1e3bca3d85c1e29f
block_time:  2026-06-02 04:46:32 UTC

commit P2TR:   bc1p5t8nslkrekrje6h8k0qqfjxk0h8pxx94k6zffq3mmmm8u28xayaq4km6u0
reveal output: 5057 sats → bc1qsvfwvewxgm3s4e3cxatwdht09vzfce6tdpl34s

commit fee:   165 sats   (vsize ~164 vB → ~1.0 sat/vB)
reveal fee:   403 sats   (vsize ~169 vB → ~2.4 sat/vB)
CPFP combined: 568 / 333 vsize = 1.7 sat/vB

witness structure (reveal tx):
  [0] 64B BIP340 Schnorr signature
  [1] 246B envelope tapscript: <32B internal pubkey> OP_CHECKSIG OP_FALSE OP_IF <207B BTX1 artifact> OP_ENDIF
  [2] 33B control block (leaf_version|parity + 32B internal key)

BTX1 magic offset:  byte 38 of witness[1]
artifact head:      425458310201007f969800010001...
                    (BTX1, version 2, runestone-flag mode)
```

Verify on any third-party explorer:

- mempool.space: <https://mempool.space/tx/8acf6c70b2c1d75153374ab52f57b6da69ae7606a5931ba295d8cb5dd477f84c>
- blockstream.info: <https://blockstream.info/tx/8acf6c70b2c1d75153374ab52f57b6da69ae7606a5931ba295d8cb5dd477f84c>
- bitaps.com: <https://bitaps.com/8acf6c70b2c1d75153374ab52f57b6da69ae7606a5931ba295d8cb5dd477f84c>

## What I expected to be hard, and what actually was

The interesting part of any mainnet-first is the gap between the bench
test and reality. Going in I expected the hard part to be the cryptography
(BIP340 Schnorr, BIP341 sighashes) or fee-market behavior. Those went
fine. What actually bit me, in order:

1. **Bitcoin Core v30 schema drift.** The pre-flight script read
   `getwalletinfo.balance` to verify the wallet was funded; v30 quietly
   removed that field, leaving it only in `getbalances.mine.trusted`.
   The wallet had 16,063 sats but the script reported zero. Caught in
   thirty seconds, fixed with a five-line patch. Lesson: any tooling
   that touches `getwalletinfo` after v30 should be re-audited.

2. **bitcoin-cli v30 datadir validation.** In external-RPC mode the
   publisher passes a placeholder `--datadir /tmp/btx-fake-datadir` for
   argument compatibility. v29.1 silently ignored this when
   `-rpcconnect` was set; v30 validates the directory exists and aborts
   when it doesn't. Two-line fix (a `mkdir -p`). Worth noting because
   it's the kind of behavioral change that won't show up in a release-
   notes diff.

3. **Single-UTXO wallet trap.** My funding wallet had exactly one P2WPKH
   UTXO. The maker-sign step locks the offer UTXO so it isn't accidentally
   spent. The publisher's commit-funding `sendtoaddress` then had nothing
   to spend. The fix is operational, not a code change — wallets that
   intend to publish BTX orders should keep ≥2 UTXOs. The pre-flight
   script now warns about this explicitly.

4. **CPFP saved a marginal commit fee.** The wallet's automatic fee
   selection put the commit at ~1.0 sat/vB — right at relay floor. The
   reveal at 2.4 sat/vB was comfortable, and because the reveal spends
   the commit's output, they're CPFP-bundled at 1.7 sat/vB. Both
   confirmed in the same block. Note for any future broadcast: the
   reveal's fee is the load-bearing one because of CPFP.

None of these were cryptographic. All four are the kind of integration
hazard that only shows up against a real production deployment of the
latest Core release. The signet propagation result (May 2026) didn't
catch any of them, because signet operators tend to follow Core defaults
less aggressively and the public faucets fund wallets with many UTXOs by
default.

## What this doesn't prove

A few honest disclaimers, because mainnet-broadcast claims often elide
them:

- **It doesn't prove demand.** The order broadcast was at an absurd
  price (1 BTC for 1 unit of a non-existent rune). No taker can fill it.
  B4 was a propagation-and-survival test, not a market test.
- **It doesn't prove order recovery from witness alone end-to-end at
  scale.** The artifact-extraction path is byte-pinned to the on-chain
  reveal via a regression test that runs against the actual witness
  data; full chain-wide indexer integration on mainnet would take
  several days of sync to demonstrate empirically. The unit-level proof
  is enough that any synced indexer over Bitcoin mainnet *will* surface
  the order — by construction.
- **It doesn't prove behavior under restrictive miner policy.** Three
  default-policy aggregators saw the tx within minutes. Knots-configured
  or operator-restricted miners may behave differently. A 1-week signet
  soak against a mixed-policy peer set would tighten this.

The point of B4 was the carrier-propagation milestone, and that's done.

## How to verify this for yourself

This is the whole point of an on-chain proof: no need to trust me.

```bash
# Any Bitcoin Core node:
bitcoin-cli getrawtransaction 8acf6c70b2c1d75153374ab52f57b6da69ae7606a5931ba295d8cb5dd477f84c true \
  | jq -r '.vin[0].txinwitness[1]' \
  | grep -o '42545831' \
  | head -1

# Expected output: 42545831  (BTX1 in ASCII hex)
```

Or, for the impatient, three third-party explorers each independently
serve the witness data for that txid. All three agreed the bytes are
what they should be.

## What's next (briefly)

Now that the technical readiness gate is closed, what BTX needs is
**either** a counter-asset decision (the locked goal is a USD-backed
stablecoin issued as a rune, the closest concession to a no-token
design) **and / or** market-maker capital, **or** to sit as a reference
implementation for the design space — an existence proof that the
"no-server, no-relay, no-token, no-escrow" architecture is shippable on
the live Bitcoin network at retail cost.

Either path is honest. The technical case is now empirical, not
prospective.

---

*BTX repos: [`bitcoin-terminal-exchange`](https://github.com/renshuBTC/bitcoin-terminal-exchange) (Python + Tauri shell + docs), [`brk-btx`](https://github.com/renshuBTC/brk-btx) (Rust BRK fork with the BTX indexer). Built on Rust + Python; 33 cross-language tests; 14 Python offline tests; one regression test now pinned to the on-chain reveal so the chain itself is the goldfish memory.*
