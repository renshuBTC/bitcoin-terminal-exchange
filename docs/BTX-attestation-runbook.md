# BTX maker-attestation runbook (BIP-322)

*Audience: a market maker who wants to prove control of a `bc1p`
Taproot address to a BTX operator (or to themselves, to verify a
counterparty), without any custodial component.*

Last updated: 2026-06-04.

## What this is for

BTX issues a random challenge. You sign the challenge under your
`bc1p` address using BIP-322. BTX verifies the signature. If it
verifies, BTX (or the verifier) knows you control the private key for
that address. Your private key never leaves your wallet.

Use cases:

- **Maker onboarding without a registry.** Prove you control your
  maker address; BTX can list you without holding any of your data.
- **Time-bounded liquidity commitments.** Sign with the full format
  (`ful` prefix) and set `nLockTime` so the attestation is only
  cryptographically valid until block N. After N, anyone who tries
  to claim the attestation as still valid is provably lying.
- **Sig-on-quote pricing.** Sign a quote message ("I will sell 100k
  USDh at 100,000 sats/USDh for the next 100 blocks"). The signed
  quote is portable proof of the commitment.

## The flow at a glance

```
   maker                      BTX (verifier)             output
  ┌──────┐                    ┌──────────┐
  │      │  1. /api/attest    │          │
  │      │ ───/challenge────► │          │
  │      │ ◄── nonce_hex ──── │          │
  │      │                    │          │
  │      │  2. sign nonce     │          │
  │      │     locally with   │          │
  │      │     your wallet    │          │
  │      │                    │          │
  │      │  3. /api/attest    │          │  {valid: true,
  │      │ ──/verify ────────►│          │   format: simple|full}
  │      │ ◄─── {valid}  ─────│          │
  └──────┘                    └──────────┘
```

Step 2 is the only step where your key material is touched, and
it happens entirely inside your own wallet. BTX never sees the key.

## Step 1 — get a challenge

### From the GUI

Open the BTX terminal, click **Attest** in the nav, click **generate
challenge**. The 64-hex nonce appears. Click **copy**.

### From the command line

```bash
curl -sS http://127.0.0.1:3333/api/attest/challenge | jq .
# → {"challenge_hex": "920f1c00...4c18"}
```

The nonce is 32 random bytes printed as 64 hex characters. The server
is stateless about the nonce: it's the verifier's responsibility to
remember which nonces they've issued to which maker.

## Step 2 — sign the challenge under your `bc1p` address

You can sign with any BIP-322-capable wallet. Five options below in
rough order of convenience.

### Sparrow Wallet

1. Open Sparrow. Select your bc1p account.
2. **Tools → Sign / Verify Message**.
3. Paste the challenge hex into the Message box.
4. Pick **bc1p…** as the signing address.
5. Click **Sign Message**. Sparrow uses BIP-322 simple format by
   default. The output starts with `smp...`.
6. Copy the signature.

### Coldcard (Mk4, latest firmware)

1. Go to **Address Explorer → Single Sig → Taproot**.
2. Use **Sign Text** to sign the challenge. BIP-322 simple format,
   `smp...` prefix.

### Ledger (Bitcoin app ≥ 2.2)

```bash
hwi --device-type ledger signmessage \
    --addr-type tr "<challenge_hex>" m/86h/0h/0h/0/0
```

The wallet emits a base64 signature; if it starts with `smp`/`ful` it's
BIP-322; if it doesn't, your Bitcoin app version doesn't yet support
BIP-322 P2TR — upgrade or switch wallets.

### Bitcoin Core (≥ 25)

```bash
bitcoin-cli signmessage "<bc1p-address>" "<challenge_hex>"
```

Note: Bitcoin Core's `signmessage` adopted BIP-322 in v25.0 (June 2024).
For older Core versions, you'll need an external tool.

### Python primitive (for scripted maker pipelines)

```python
import btx_bip322 as B

seckey, _ = B.decode_wif("<your_WIF>")
sig = B.sign_simple_p2tr("<challenge_hex>", seckey)
print(sig)   # smp...
```

For time-bounded attestations:

```python
sig = B.sign_full_p2tr(
    "<message>", seckey,
    version=2,
    locktime=900_000,   # block height attestation expires at
    sequence=0xfffffffd,
)
print(sig)   # ful...
```

## Step 3 — verify

### From the GUI

Open **Attest**, paste address / message / signature, click **verify**.
A green badge means it's valid; format pill says `simple` or `full`.

### From curl

```bash
curl -sS -X POST http://127.0.0.1:3333/api/attest/verify \
     -H "Content-Type: application/json" \
     -d '{
       "address":   "bc1p…",
       "message":   "<the challenge hex you signed>",
       "signature": "smp…"
     }'
# → {"valid": true, "format": "simple"}
```

Response shapes:

| HTTP | Body | Meaning |
|------|------|---------|
| 200 | `{"valid": true,  "format": "simple"|"full"}` | Verified |
| 200 | `{"valid": false, "format": "simple"|"full"}` | Well-formed but doesn't bind to (address × message) |
| 400 | `{"error": "<reason>"}` | Malformed input (non-Taproot address, bad JSON, unknown variant prefix, oversized) |
| 403 | `{"error": "forbidden origin", …}` | Cross-origin POST — wire your client to same-origin or whitelist via Host/Origin |

### From Python

```python
import btx_bip322 as B

ok = B.verify_simple_p2tr(message, address, sig)    # smp...
ok = B.verify_full_p2tr  (message, address, sig)    # ful...
```

### From Rust (brk-btx, indexer-side)

```rust
use brk_indexer::btx_bip322::{verify_simple_p2tr, verify_full_p2tr};

let valid: bool = verify_simple_p2tr(message, address, sig)?;
```

## What can go wrong

| Symptom | Cause | Fix |
|---------|-------|-----|
| `error: only Taproot (bc1p/tb1p) addresses are supported` (400) | You sent a `bc1q` (P2WPKH) or legacy address | BTX attestation is Taproot-only. Use a `bc1p` address. |
| `error: unknown signature variant` (400) | Signature doesn't start with `smp` or `ful` | Your wallet emitted legacy `signmessage` format, not BIP-322. Upgrade the wallet or use a different tool. |
| `valid: false` | The signature is well-formed but doesn't bind (address × message) | (a) wrong address selected when signing, (b) message was modified between sign and verify (whitespace, charset, hex case), (c) the signature was issued for a different challenge. |
| `error: invalid JSON body` (400) | The POST body wasn't valid JSON | Check curl quoting; consider piping through `jq -n` |
| `error: forbidden origin` (403) | Your client sent a cross-origin Origin header | btxd's CSRF guard rejects anything from outside loopback. Wire the client to same-origin or hit it from inside the bundle. |

### Charset gotcha

The message bytes are signed as-is, no length prefix, no null
terminator. If your wallet shows the message back to you with extra
whitespace, normalises Unicode, or strips trailing newlines, you'll
get `valid:false` on verify because the bytes the verifier sees are
not the bytes the signer signed. Use bytes-identical messages on both
sides.

### Time-locked attestation gotcha

The `nLockTime` in a `ful`-format attestation does NOT make the
attestation auto-expire from the verifier's perspective in BTX — the
verifier only checks the BIP-340 signature math, which is timeless.
What `nLockTime` gives you is **a cryptographic commitment** that the
signed `to_sign` tx is one that can't be confirmed before block N.
If your attestation policy is "valid until block N", the **verifier**
must enforce N — typically by checking
`current_block_height < tx.locktime` before accepting.

## Threat model

What BIP-322 attestation **does** prove:

- The signer controls the private key for the `bc1p` address at
  the moment of signing.
- The signature binds the (address, message) pair. Replaying the
  signature for a different message will fail to verify.

What it does **not** prove:

- That the signer controls the address NOW (the signing may have been
  yesterday and the key may have been compromised since).
- Anything about the funds at the address. The address may be empty.
  (Use the proof-of-funds variant — `pof` prefix — when BTX adds
  support for it.)
- Anything about non-Taproot key paths. BIP-322 P2TR specifically
  signs with the **output key** (after BIP-341 tweak with empty
  merkle root). If your address uses a script-path tweak, this verifier
  won't accept your signature.

For these reasons, treat attestations as **session tokens** — short
expiration windows, re-attest periodically — not as standing identity
claims.

## Cross-references

- BIP-322 spec: <https://github.com/bitcoin/bips/blob/master/bip-0322.mediawiki>
- Test vectors used in BTX's cross-validation:
  `Bitcoin CoreX/bitcoin-bips-reference/bip-0322/{basic,generated}-test-vectors.json`
- Python primitive: `btx_bip322.py`
- Rust primitive: `brk-btx/crates/brk_indexer/src/btx_bip322.rs`
- HTTP endpoints: `btxd.py` `h_attest_challenge` / `h_attest_verify`
- GUI page: `btx_attest.html`
- Scouting doc + design rationale: `BTX-BIP322-scouting-2026-06-03.md`
- Adversarial test battery: `btx_bip322_adversarial.py`
