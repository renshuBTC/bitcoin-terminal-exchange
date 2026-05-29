# BTX — Ecosystem Scan & Improvement Research (2026-05-27)

*Triage of the 27 supplied repos/people by relevance to BTX, deep-dive on the relevant ones, and
concrete improvement recommendations. Note: the sandbox cannot `git clone` (anonymous GitHub over its
network is blocked), so deep code dives were done on the reference checkouts already present locally
(`ord-reference`, `runestone-lib-reference`, `saturnbtc-reference`, `tbdex-reference`, …); for the
high-value repos not yet local, WSL clone commands are at the bottom.*

BTX recap (the lens for "relevant"): a nothing-offchain, Bitcoin-L1, self-custody DEX —
`SIGHASH_SINGLE|ANYONECANPAY` pre-signed offers as on-chain artifacts, a BRK-fork indexer that
reconstructs the order book from chain and serves an order-set-independent **consensus hash**, ord as a
read-only rune oracle, a localhost orchestrator + terminal.

---

## Relevance triage

### HIGH — directly maps onto BTX's architecture

| Repo / person | What it is | Why it matters to BTX | Local? |
|---|---|---|---|
| **bestinslot-xyz/OPI** & **OPI-LC** | Open Protocol Indexer + **light client** for BRC-20/meta-protocols | OPI computes a per-block **cumulative event hash** and OPI-LC verifies protocol state against the OPI-network hash **without a full node**. This is the mature version of BTX's consensus hash — and BTX can't do light verification yet. **The #1 improvement target.** | no |
| **RiemaLabs/modular-indexer-light** & **committee** | "Stateless & verifiable execution layer for meta-protocols" (Nubit) | Committee publishes **Verkle-tree state checkpoints**; light indexer verifies via **challenge/fraud-proof** (not 51% vote), checkpoints distributed over a DA layer. Succinct **membership proofs** + fraud detection — strictly more than BTX's flat hash. | no |
| **ordinals/ord** (raphjaph, casey) | Ordinals + Runes reference impl | BTX ported runestone decode + cenotaph rules from `ord`'s `rune.rs`. A decoder divergence breaks the consensus hash, so `ord` master is the correctness oracle. | **yes** (`ord-reference`) |
| **runestone-lib** (Magic Eden) | TypeScript Runes implementation | A **second independent** runestone impl — cross-check BTX's decoder + import its test vectors so BTX isn't validated against only one reference. | **yes** (`runestone-lib-reference`) |
| **bitcoinresearchkit/brk** | The indexer BTX is forked from | Upstream of `brk_indexer`/`brk_query`/`brk_server`. Track it for store/serving changes and the (clean) `cargo audit` baseline. | yes (the `brk` repo) |
| **casey (Light Pools)** | Casey Rodarmor's Bitcoin DEX design | BTX's explicit benchmark (per project notes): a pool/AMM design with **mempool-sniping immunity** — the one axis where BTX (open-order front-running is *accepted*) is weaker. Worth studying the anti-snipe mechanism. | check casey's repos |

### MEDIUM — addresses a known open BTX item

| Repo / person | What it is | BTX angle |
|---|---|---|
| **rust-bitcoin** + **apoelstra** | BTX's core Rust dependency | Already used (bitcoin 0.32.9 / secp256k1 0.29.1, audit-clean). Track for sighash/PSBT API. |
| **rust-bitcoin/rust-miniscript** (apoelstra, darosior) | Miniscript | Express BTX offer/spend conditions as **descriptors**; a miniscript spending policy on a dedicated btxd wallet would **bound the hot-wallet blast radius** (the accepted (e) item from the key-material/ops audits). |
| **darosior** (Antoine Poinsot, Liana) | Miniscript wallet + TRUC/v3 + consensus cleanup | (1) Liana-style **timelocked-recovery / policy wallet** → blast-radius mitigation. (2) **TRUC (v3) + package relay** → the **cancel-pinning** gap (item (g) in the attack/defense matrix). |
| **JeremyRubin** (CTV / Sapio) | OP_CHECKTEMPLATEVERIFY covenants | A CTV-committed offer could enforce the **exact** fill template (anti-snipe / no substitution) and cap what btxd can sign. Forward-looking (not activated). |
| **jamesob** (OP_VAULT) | Vault covenant | A vault over the btxd hot wallet → **delayed/clawback-able** spends = the strongest (e) blast-radius fix. Forward-looking (needs covenant activation). |
| **real-or-random** (Tim Ruffing) | secp256k1 maintainer, **MuSig2 / FROST** | **MuSig2** 2-of-2 or threshold maker offers → multi-party / escrowed liquidity without leaving L1. Forward-looking liquidity feature. |
| **sipa** + **bitcoin-core/secp256k1** | Pieter Wuille; the C crypto lib | Correctness reference for the **hand-rolled** `btx_taproot.py` Schnorr/BIP341 (already vector-tested); the lib backs BTX's production verify via rust-bitcoin. |
| **bitcoin/bitcoin** | Bitcoin Core | BTX's runtime dependency (RPC, policy, datacarriersize). Reference specific parts (sighash, mempool policy), don't clone wholesale. |

### LOW / forward-looking — interesting, not near-term

| Repo / person | Why lower priority |
|---|---|
| **RobinLinus/ZeroSync** | STARK proof of Bitcoin chain state → a BTX client could verify the chain (book-reconstruction inputs) **without a full node**. Strategically aligned with "light + trustless," but heavy and early. |
| **BitVM/BitVM** (RobinLinus) | Optimistic computation via fraud proofs — powerful but L2-flavored; BTX is L1-pure. A "prove the book off-chain, verify on-chain" future, not now. |
| **TheBlueMatt / lightningdevkit** | Lightning is *off-chain* — against BTX's thesis. Useful only as an engineering reference (async tx handling, anchor/RBF fee-bumping, interactive funding handshake ≈ BTX's addressed-swap). |
| **saturnbtc** | Saturn's runes DEX runs on **Arch Network** (an execution layer), i.e. the **opposite** architectural bet to BTX's pure L1. Best as a *contrast* comparable, not a code source. |
| **tbdex** | RFQ messaging DEX (Offering→RFQ→Quote→Order→Status) — **off-chain** liquidity protocol. The RFQ handshake is a useful **model for BTX's interactive addressed-swap** flow, not the on-chain core. |
| **kibo-money/kibo** | BRK-ecosystem Bitcoin data/charts frontend — UI/analytics reference, not DEX core. |

---

## Deep-dive findings (the relevant clusters)

### 1. Verifiable indexing / light clients — the biggest gap and opportunity

BTX's trust story today: the `brk-btx` indexer serves `/api/v1/btx/book-hash` — an order-set-independent `sha256` over the open book. Two indexers over the same chain produce the identical digest, so they can *prove agreement*. But to **verify** that hash a client must download the **whole** book and recompute it, or run its own full node + indexer. A passive viewer who just reads `/orders` trusts the server.

OPI-LC and RiemaLabs solve exactly this, and more maturely:
- **OPI-LC**: indexes meta-protocol state **without a Bitcoin full node**, computes a per-block **block hash + cumulative event hash**, and checks it against a verified hash from the OPI network — a runnable light client on a tiny machine.
- **RiemaLabs modular-indexer**: the *committee* publishes **Verkle-tree state checkpoints** (succinct commitments) to a DA layer; the *light* indexer verifies via a **challenge / fraud-proof** mechanism — a single malicious indexer is removed on proof, **not** by majority vote.

**BTX implications (ranked):**
1. **Commit the book in a Merkle (or Verkle) tree, not a flat hash.** Then a taker can verify *a specific order is in the book* with a **log-sized membership proof** — no full download, no full node. This turns the "passive viewer must trust the indexer" caveat (from the threat model + attack/defense matrix item (d)) into "any viewer can verify a served order." This is the single highest-leverage upgrade to BTX's core claim.
2. **Add a cumulative event hash** (announce/fill/cancel stream), à la OPI, alongside the open-book commitment — lets a light client follow the book incrementally and detect omission.
3. **A challenge/fraud-proof path** (RiemaLabs model): publish checkpoints; let anyone submit a proof that a served order is invalid (sig doesn't verify) or that a known on-chain order was omitted. BTX already has the raw material — every order is a self-verifying artifact (`verify_maker_sig` against the offer UTXO) — so a fraud proof for "this served order is bogus" or "you omitted this valid order" is constructible.

### 2. Runes correctness — cheap, high-value hardening

BTX's decoder/cenotaph logic was ported from **one** reference (`ord`'s `rune.rs`). `runestone-lib` (Magic Eden, TypeScript) is an **independent** implementation of the same spec. A decoder divergence is a consensus-hash break, so:
- **Import `runestone-lib`'s test vectors** into BTX's `btx_fuzz.py` / golden suite, and cross-run BTX's decoder against both `ord` master and `runestone-lib` on the same inputs. A third independent oracle materially lowers the "we matched only one impl" risk. (Both references are already local.)

### 3. The accepted security items have known ecosystem answers

The security audit accepted two architectural items; the supplied list points right at their fixes:
- **(e) hot-wallet blast radius** (compromised btxd can drive Core to drain the wallet): a **miniscript** spending-policy wallet (apoelstra/darosior) or, forward-looking, an **OP_VAULT / CTV** covenant (jamesob/JeremyRubin) bounds or delays what btxd can spend. Near-term: run btxd against a **dedicated thin descriptor wallet** with a miniscript policy.
- **(g) cancel pinning** (mempool-pinning a maker's cancel): **TRUC/v3 + package relay** (darosior, TheBlueMatt) is the ecosystem's anti-pinning answer.

### 4. The competitive landscape (contrast comparables)

- **Saturn (Arch)** and **tbDEX** both take execution-layer / off-chain-messaging bets — BTX's differentiation is *pure L1, nothing off-chain, indexer-reconstructed*. The light-client work (cluster 1) is what makes that differentiation **defensible** rather than just "more purist."
- **Light Pools (casey)** is the one to study seriously: its mempool-sniping immunity is the axis where BTX's open-order mode is weakest (front-running is *accepted*; addressed mode is the opt-out). Understanding its anti-snipe construction could inform a BTX open-order improvement.

---

## Top recommendations for BTX (ranked)

1. **Merkle-commit the order book + serve membership proofs** (model: OPI-LC cumulative hash + RiemaLabs Verkle/challenge). Upgrades the flat `book-hash` so a taker verifies a served order without a full node — directly closes the "viewer trusts the indexer" gap and is BTX's clearest competitive differentiator.
2. **Cross-validate the Runes decoder against `runestone-lib` + `ord` master** and import both sets of test vectors. Cheap, removes a single-reference risk on the consensus-critical path.
3. **Run btxd against a dedicated miniscript-policy thin wallet** (rust-miniscript / Liana patterns) to bound the hot-wallet blast radius — the near-term, no-soft-fork answer to audit item (e).
4. **Track upstream `brk`** for store/serving changes; keep the `cargo audit`-clean baseline.
5. **Forward-looking watchlist**: CTV/OP_VAULT for covenant-enforced offers + vaulted wallet (anti-snipe + blast-radius), MuSig2/FROST for multi-party offers, ZeroSync for full light-client chain verification. None are near-term, all align with the "light + trustless + L1" thesis.

---

## WSL clone commands for the high-value not-local repos

The sandbox can't clone; run these on your WSL to pull the ones worth a deeper local dive (shallow clones keep them small):

```bash
cd "/mnt/c/Users/Ren Shu/Documents/Claude/Projects/Bitcoin Terminal Exchange"
mkdir -p research && cd research
git clone --depth 1 https://github.com/bestinslot-xyz/OPI-LC.git              # light-client model (priority)
git clone --depth 1 https://github.com/bestinslot-xyz/OPI.git                 # cumulative event hash
git clone --depth 1 https://github.com/RiemaLabs/modular-indexer-light.git    # Verkle + challenge-proof
git clone --depth 1 https://github.com/RiemaLabs/modular-indexer-committee.git
git clone --depth 1 https://github.com/casey/ord.git light-pools-check        # check casey's repos for light-pools
git clone --depth 1 https://github.com/rust-bitcoin/rust-miniscript.git       # descriptor/policy wallet
```

Once cloned, point me at `research/` and I'll do the line-level dive — especially OPI-LC's hash/verify path and RiemaLabs' checkpoint/proof format — to design the BTX Merkle-commitment + membership-proof upgrade (recommendation #1).

---

## Forward-looking watchlist — detail (last refreshed 2026-05-29)

Recommendations #1–#3 above are now shipped: the Merkle-committed book + membership proofs and the
cumulative event hash (#1; see `BTX-book-commitment-design.md`), the Runes decoder cross-validation
vs Magic Eden `runestone-lib` (#2; `btx_runes_xcheck.py`), and the dedicated thin-wallet blast-radius
rail (#3; btxd `--max-hot-balance-btc`, `BTX-mainnet-hardening.md`). What remains is #5 — things
that align with BTX's "light + trustless + Bitcoin-L1" thesis but are **not adoptable yet**, each with
the concrete trigger that would move it from watch to build.

### 1. CTV (BIP-119) + OP_CHECKCONTRACTVERIFY (BIP-443) — covenant-enforced offers & vaulted hot wallet
*What:* `OP_CHECKTEMPLATEVERIFY` commits a UTXO to be spendable only into a specific predetermined
transaction template (version, locktime, in/out count, outputs, input position). `OP_VAULT` (BIP-345) was
**withdrawn in May 2025** (bitcoin/bips PR #1848) and **superseded by BIP-443 OP_CHECKCONTRACTVERIFY
(CCV)**, which gives a more general "spend transaction commits to a script/data" primitive that subsumes
vault semantics. CCV is the doc to track for the vaulted-float use case from `BTX-mainnet-hardening.md`,
not OP_VAULT.

*Status (verified 2026-05-29):* CTV has concrete activation parameters on the table — signaling start
**2026-03-30**, timeout 2027-03-30, minimum activation height ~May 2027, 90% miner threshold over a
2016-block period. **As of late May 2026, signaling is 0/203 blocks (0.00%) in the current difficulty
period 468** ([bip119monitor.com](https://bip119monitor.com/)). The activation client is third-party
([delvingbitcoin.org/t/bip-119-ctv-activation-client/2242](https://delvingbitcoin.org/t/bip-119-ctv-activation-client/2242))
— **not merged into Bitcoin Core master**. The Oct-2026 Bitcoin Core v30 release is dominated by an
OP_RETURN datacarrier policy change (4MB / multi-OP_RETURN allowed), **not CTV**
([theblock.co](https://www.theblock.co/post/357594/bitcoin-core-devs-merge-controversial-op_return-policy-change-into-planned-october-release)).
A pro-activation open letter from 40+ devs is on the table
([atlas21.com](https://atlas21.com/bitcoin-developers-call-for-implementation-of-ctv-and-csfs-letter-to-the-community/))
but the on-chain reality is no signaling yet. **Still: covenant proposal closest to activation, but not
locked in.**

*Why BTX cares (two distinct wins):*
  (a) **Blast radius (audit item e).** This is the layer-3 "trustless" bound named in
  `BTX-mainnet-hardening.md`: the trading float sits in a covenant-enforced wallet — under BIP-443 CCV
  it's a contract that constrains where the float can go (withdrawal delay + clawback path), so a theft
  attempt becomes a visible, revertible on-chain unvaulting instead of an instant drain. No trusted
  cosigner needed (unlike the layer-2 2-of-2). It upgrades the thin-wallet/cosigner design *in place*.
  (b) **Anti-snipe offers.** A CTV-templated offer could commit the maker's payout structure into the
  spend template itself, narrowing the taker's degrees of freedom that the mempool-sniping attack exploits
  — though `BTX-frontrunning-threat-model.md` §7 establishes that *open + snipe-proof* is logically
  impossible under any per-transaction Bitcoin predicate, so this would harden but not solve the problem.
  The addressed-swap mode (already shipped) remains the actual snipe-proof escape for open orders.
*Trigger:* CTV locks in (signaling succeeds) → prototype the vaulted-float wallet under BIP-443 CCV
first (pure ops win, no protocol change to BTX), then evaluate a CTV-committed offer variant. Until
signaling moves above 0%, this remains theoretical.

### 2. MuSig2 (BIP-327) / FROST — multi-party makers & the policy cosigner
*What:* MuSig2 (standardized as **BIP-327**) aggregates an **n-of-n** set of signers into one key + one
ordinary Schnorr signature. FROST (Flexible Round-Optimized Schnorr Threshold) is the **t-of-n** analogue:
any t of n cooperators produce a single standard Schnorr signature, revealing nothing about the group
on-chain, and tolerating offline members.

*Status (verified 2026-05-29):* MuSig2 is finalized (BIP-327), no recent errata or revisions. Adjacent
tooling moved: **Bitcoin Core PR #34219** completed MuSig2 PSBT pubnonce / partial-sig validation, merged
2026-03-04 for the Core 31.0 milestone
([bitcoinindex.net](https://bitcoinindex.net/blog/bitcoin-core-s-musig2-psbt-validation-making-multisig-more-r/)).
**BIP-390 v0.2.0** released 2026-03-04 enables `musig()` inside `sp()` (silent payments)
([bips.dev/390](https://bips.dev/390/)).

FROST has **firmer footing than the previous note implied**: **IETF RFC 9591** was published **June
2024** and is the canonical FROST spec, with `FROST(secp256k1, SHA-256)` as a named ciphersuite
([datatracker.ietf.org/doc/rfc9591](https://datatracker.ietf.org/doc/rfc9591/)) — not just a CFRG draft.
Implementations active in 2026: `BlockstreamResearch/bip-frost-dkg`,
`siv2r/bip-frost-signing` (v0.3.5, 2026-01-25) as a draft Bitcoin BIP on the mailing list, and Zcash
Foundation's `frost-secp256k1-tr` (BIP-340/341 ciphersuite). **No canonical Bitcoin BIP yet** — the
`bip-frost-signing` draft is the closest candidate.

*Why BTX cares:*
  (a) **The layer-2 policy cosigner** (`BTX-mainnet-hardening.md` blast radius) is a 2-of-2; FROST/MuSig2
  make that a single-key-on-chain construction — the offer UTXO and fills look like ordinary Taproot
  key-path spends, so the cosigner adds no on-chain footprint and the maker keeps Taproot's privacy/fee
  profile. The velocity/whitelist limit still lives in the cosigner's signing
policy (no signature scheme
  encodes amount caps), exactly as documented.
  (b) **Multi-party makers.** A FROST t-of-n group could collectively maintain an offer (e.g. a small
  market-making desk) without any on-chain multisig script — still a single pre-signed
  `SIGHASH_SINGLE|ACP` artifact, just produced by a threshold group.
*Trigger:* a concrete need for either a privacy-preserving cosigner or a multi-party maker. FROST tooling
maturity is now mostly there (RFC 9591 + multiple secp256k1 libs); the remaining gate is a single canonical
Bitcoin BIP — `bip-frost-signing` clearing the BIP process or one of the lib authors shipping a stable
mainnet-targeted release. Until then the 2-of-2 miniscript cosigner is the documented near-term path.

### 3. ZeroSync (and adjacent succinct-Bitcoin work) — trustless light-client chain verification
*What:* succinct (zk/STARK) proofs that the Bitcoin chain up to some state is valid, so a verifier
confirms chain state without downloading/validating every block.

*Status (verified 2026-05-29):* ZeroSync is **still alive but its focus has shifted**. The project is
largely subsumed into the **BitVM Alliance** (founded September 2024; ZeroSync co-founder Robin Linus is
a principal). The most recent ZeroSync-specific milestone surfaced is **zkCoins PoC (March 2025)**. Robin
Linus's group received the **Bitcoin Research Prize 2025**. No 2026 cadence on chain-state proofs has
surfaced; the energy has moved to BitVM bridges / zkCoins / BitVM2
([bitvm.org](https://bitvm.org/), [coindesk on BitVM2](https://www.coindesk.com/tech/2024/08/15/bitcoins-programmability-draws-closer-to-reality-as-robin-linus-delivers-bitvm2)).
**Not paused, not superseded — refocused.** A chain-state proof for mainnet light clients (the BTX use
case) is not on a published 2026 roadmap.

*Why BTX cares:* BTX's verifiability story currently bottoms out at "run an honest indexer over a full
node." The Merkle book root + cumulative event hash let a light client verify *a served order / the event
stream* against a committed root — but the client still trusts that the root corresponds to the real
chain. A ZeroSync-style chain proof would close that last gap: a phone could verify the chain, then verify
the book root against it, end-to-end trustless — the full realization of the "light + trustless + L1"
thesis. This is the most speculative item and the furthest out.
*Trigger:* a usable proof artifact + verifier for mainnet chain state (from ZeroSync, BitVM, or a
successor). Until then this is research, not roadmap.

### Adjacent items surfaced 2026-05-29 (worth tracking even though not on the original watchlist)

- **Bitcoin Core v30 (target October 2026) — OP_RETURN policy relaxation.** Default `-datacarrier`
  policy moves from "single 80-byte OP_RETURN" to "multi-OP_RETURN allowed, up to 4MB combined" per the
  merged PR. **What it means for BTX:** Prompt 10's pass criteria ("OP_RETURN 70B allowed, 100B rejected
  under strict default policy") asserts behavior of Core **v29.1**, and that's still empirically true on
  v29.1 nodes today. Once v30 is widely deployed, the 80-byte OP_RETURN boundary disappears as a
  policy boundary in the network — BTX's envelope carrier remains the default and is unaffected, the
  OP_RETURN carrier could legally carry the full 207-byte artifact in a single output, and the
  Prompt-10-style strict-policy assertion becomes "envelope passes under strict default" (still true) plus
  a note that the OP_RETURN policy boundary moved.
- **MuSig2 PSBT validation in Core 31.0.** Direct relevance to BTX is low (we don't build maker sigs
  through Core's PSBT flow), but if a future cosigner uses Core's wallet to manage MuSig2 partials, this
  is the lib path.

**Net:** none of these are near-term, and BTX needs no code now. The ordering when they mature is
CTV+CCV vault (ops-only, highest leverage on the open blast-radius residual) → FROST cosigner (privacy
upgrade to the already-designed 2-of-2; tooling is closer than this doc previously implied) → ZeroSync /
BitVM chain proofs (the trustless-light-client end state). All three deepen the same thesis rather than
adding off-chain dependencies, which keeps them consistent with BTX's nothing-offchain rule.
