# Scouting report — `sipa/minisketch` (Pieter Wuille's set reconciliation)

*Fifth scouting target this 2026-06-03 cycle. Pivots from script-policy
(rust-miniscript) to a fundamentally different layer: bandwidth-efficient
set reconciliation. Co-authors of the implementation: Pieter Wuille
("sipa"), Greg Maxwell, Gleb Naumenko.*

Date: 2026-06-03.

## Why this developer / repo

Pieter Wuille is the most influential Bitcoin Core developer of the
last decade — author or co-author of BIP-32/141/143/340/341/342, the
Schnorr/Taproot soft fork, libsecp256k1, etc.

`sipa/minisketch` (`bitcoin-core/minisketch` upstream) is an
implementation of **PinSketch set reconciliation**: a BCH-based
"set checksum" that lets two parties with similar sets reconcile their
differences using **O(differences)** communication, not O(set size).

The library has one known Bitcoin production application:
**Erlay** (BIP-330) — a transaction relay protocol that uses minisketch
to reduce P2P bandwidth by ~80%. It is also the design BIP-152 compact
block relay's hypothetical "v2" would build on.

For BTX, the relevant question is: can BTX use minisketch to make
indexer-to-indexer order book synchronisation more efficient?

## Repository at a glance

Cloned to `Bitcoin CoreX/minisketch-reference/` at master HEAD
(2026-06-03). MIT-licensed C++ library with a C API.

Workspace structure (per cloned tree):

```
include/
  minisketch.h        — the public C API
src/
  minisketch.cpp      — main entry point + impl registry
  sketch.h            — abstract sketch template
  sketch_impl.h       — sketch implementations
  fields/             — finite-field implementations per bit size
  fielddefines.h      — which bit sizes are supported
  bench.cpp           — performance benchmark
  test.cpp            — correctness tests
  int_utils.h         — bit manipulation helpers
  lintrans.h          — linear-transform helpers
  false_positives.h   — false-positive math for capacity tuning
  util.h
doc/
  math.md             — algorithm walk-through
  protocoltips.md     — how to design reconciliation protocols
  moduli.md           — list of irreducible polynomials used
  example.c           — minimal C example
```

## The API surface (from `include/minisketch.h`)

The complete public API is 9 functions plus 3 introspection helpers:

```c
minisketch* minisketch_create(uint32_t bits, uint32_t impl, size_t capacity);
void        minisketch_destroy(minisketch*);
minisketch* minisketch_clone(const minisketch*);
size_t      minisketch_serialized_size(const minisketch*);
void        minisketch_serialize(const minisketch*, unsigned char* out);
void        minisketch_deserialize(minisketch*, const unsigned char* in);
void        minisketch_add_uint64(minisketch*, uint64_t element);
size_t      minisketch_merge(minisketch*, const minisketch* other);
ssize_t     minisketch_decode(const minisketch*, size_t max, uint64_t* out);
/* + minisketch_compute_capacity, minisketch_compute_max_elements,
     minisketch_bits, minisketch_capacity, minisketch_implementation */
```

Key properties (verified from the README + the inline docstrings):

1. **Sketch size:** `bits × capacity / 8` bytes. A sketch of 64-bit
   elements with capacity 20 fits in **160 bytes**, regardless of
   set size.
2. **Merge = XOR:** `merge(A, B)` produces a sketch of the *symmetric
   difference* of A and B. Equivalent to bitwise XOR of the
   serialisations when both sides used the same `(bits, capacity)`.
3. **Decode = recovery:** `decode()` returns the elements of the
   symmetric difference if the difference size ≤ capacity. Returns -1
   if larger.
4. **PinSketch never produces false positives when |Δ| ≤ capacity.**
   Above capacity, false-positive probability is bounded by
   `2^{-fpbits}` where `fpbits` is a tunable parameter.
5. **Element = 0 is forbidden.** Adding the same element twice removes
   it (XOR semantics, set not multiset).

## The reconciliation protocol (from README)

For Alice and Bob with sets A and B:

```
1. Alice computes sketch_A = create(bits, impl, capacity), adds all A
2. Alice → Bob:  serialize(sketch_A)             // bits×capacity/8 bytes
3. Bob computes sketch_B same way
4. Bob computes diff = merge(sketch_B, sketch_A)  // symmetric difference sketch
5. Bob decodes: elements in (A ∪ B) − (A ∩ B)
6. Bob → Alice: the elements in B − A (Bob can detect these via lookup)
7. Alice → Bob: the elements in A − B
```

Bandwidth: `bits×capacity/8 + |A−B|·sizeof(element) + |B−A|·sizeof(element)`.

For BTX-sized order books (1000s of orders), if the typical pair-wise
difference is a few orders (≪ capacity), the per-sync cost drops from
the full set size to ~160 bytes + a few KB of order data.

## BTX integration concretely

### The candidate use case

Two BTX indexers (or a BTX indexer + a light-client wallet) sync their
view of the active order book. They might disagree on:

- A handful of orders at the chain tip (block reorgs)
- Newly-announced orders the lagging indexer hasn't processed
- Cancelled orders the lagging side hasn't seen the cancellation tx for

These differences are usually small (single digits) even for a healthy
order book.

### Element encoding

BTX2 order IDs are 36 bytes:

```
announce_txid (32) || envelope_record_index (u16) || intra_record_order_index (u16)
```

For minisketch, the natural reduction is `64 bits of the BTX2 order
sighash` (the same tagged hash already computed by
`btx_taproot.tagged_hash("BTX2/order/sighash", body_bytes)`):

```python
element = int.from_bytes(order_sighash[:8], "big")
```

64-bit collision probability for an order book of size N is
~N² / 2^64. For N=1,000,000 orders, that's ~6 × 10⁻⁸ — negligible.

### Sketch sizing for BTX

| Order book size | Expected drift | Sketch capacity | fpbits=32 | Sketch size |
|-----------------|----------------|-----------------|-----------|-------------|
| 100             | ≤ 5            | 20              | 32        | 160 B       |
| 1,000           | ≤ 20           | 50              | 32        | 400 B       |
| 10,000          | ≤ 100          | 200             | 32        | 1.6 KB      |
| 100,000         | ≤ 500          | 1000            | 32        | 8 KB        |

These are upper bounds; if the actual drift is smaller the decode still
succeeds (capacity > differences is fine, capacity < differences fails).

### Protocol fit with BTX2

Maps cleanly to a new BTX HTTP endpoint:

- `GET /api/v1/btx2/sketch?capacity=N&fpbits=32` →
  returns a serialized minisketch over all currently-open order
  sighashes (truncated to 64 bits)
- Client computes its own sketch, XORs with received, decodes
- Client requests the specific missing orders via existing endpoints
  (`/api/v1/btx2/orders/<oid>` or similar)

This is BTX2-side product work, not a primitive port.

## Realistic effort estimate

Three paths:

### Path A — bindings to libminisketch (1-2 days)

Use `ctypes` to wrap the C API. Requires libminisketch installed on the
BTX host (apt package available in some distros as `libminisketch-dev`
but not in this watcher's WSL; build from source requires
`autoconf libtool` or `cmake`).

Pros: zero re-derivation of math. Performance is excellent.
Cons: external C dependency, adds packaging complexity to BTX bundle.

### Path B — pure-Python port (~1-2 weeks)

Re-implement the math in Python: finite-field arithmetic in GF(2^b),
Berlekamp–Massey algorithm for decoding, Berlekamp trace root-finding.

Pros: no external dependency.
Cons: significant cryptographic engineering work; performance worse
than C by ~100×; carries a real risk of subtle bugs.

### Path C — spec + bookmark for trigger (this session)

Write this doc. Defer the implementation until BTX has a real
multi-indexer deployment that motivates the bandwidth-saving.

**Path C is what this session ships** (per the build constraints — see
next section).

## Why the demo didn't ship this session

The watcher environment is missing `autoconf` / `libtool` / `cmake`,
and `sudo apt-get install` requires a password BTX doesn't pass in
non-interactively. The pure-Python port (Path B) would be substantial
work and isn't a discriminator anyway — the right next step is
bindings, not a re-derivation.

To unblock Path A, a human can install build tools on the WSL side:

```bash
sudo apt install autoconf libtool g++ make
cd "Bitcoin CoreX/minisketch-reference"
./autogen.sh && ./configure --enable-shared && make
```

After that, a Python wrapper using `ctypes.CDLL("./.libs/libminisketch.so.0")`
is straightforward (~50 LOC). The cross-test would compare BTX-side
sketch construction against the canonical C output on shared inputs.

## Module-by-module value to BTX

| Module | Direct extractable for BTX2 today? |
|--------|------------------------------------|
| Public C API | No — direct linkage requires a build step that needs root |
| Reconciliation protocol design | **Yes** — applicable to BTX indexer-to-indexer sync (this doc) |
| Element encoding pattern | **Yes** — truncate BTX2 order sighash to 64 bits |
| Sketch sizing math | **Yes** — table above gives BTX-realistic numbers |
| Pure-Python re-derivation | Defer — significant crypto-engineering effort |
| Berlekamp–Massey / trace algorithms | Defer — same |
| CLMUL hardware specialisations | Defer — same |

## Comparison with the previous scouting docs

| Repo | What landed |
|---|---|
| `BlockstreamResearch/secp256k1-zkp` | half-agg + MuSig2 + adaptor + S2C + DLC integrated |
| `LLFourn/secp256kfun` | FROST trusted-dealer integrated; cross-curve DLEQ specced |
| `bitcoin/bips` | BIP-340/341/327/374 canonical-validated; BIP-374 DLEQ ported |
| `rust-bitcoin/rust-miniscript` | `btx_descriptor.py` (tr(K) + BIP-380 checksum + BIP-371 fields) |
| **`sipa/minisketch`** | **Design doc + integration plan; library binding blocked on build deps** |

The third "no-code-lands" scouting in the cycle — but here the reason
is operational (build environment), not architectural (rust-miniscript
was deferred because BTX2 is key-path-only). Path A becomes viable the
moment build deps are installed.

## Verdict

`libminisketch` is high-quality, MIT-licensed C with a tight C API
and one production use case (Erlay) that validates it. The math is
well-suited to BTX indexer order book sync.

**For BTX's current scope (single-indexer mainnet, no peer-to-peer
indexer mesh), nothing ships today.** The repo is bookmarked as a
**ready-to-bind primitive** for when BTX runs multiple indexers that
need to stay aligned with minimal bandwidth.

Trigger conditions for actually shipping the integration:
- BTX deploys ≥ 2 active indexers (e.g., one on signet + one on
  mainnet, or geographically distributed)
- BTX adds a public indexer-mesh feature (light-client sync)
- A maker desk requests a low-bandwidth way to mirror the order book

## File index

```
Bitcoin CoreX/minisketch-reference/                   (cloned 2026-06-03, master HEAD)
  ├── include/minisketch.h                            full 9-function C API
  ├── src/{minisketch.cpp, sketch.h, sketch_impl.h}   core implementation
  ├── src/fields/                                     finite-field impls per bit size
  ├── doc/{math.md, protocoltips.md, moduli.md}       design + integration docs
  └── doc/example.c                                   minimal C example

bitcoin-terminal-exchange/
  ├── BTX-minisketch-scouting-2026-06-03.md          (THIS DOC)
  └── (no code changes this session)
```

## Source

Repo: <https://github.com/sipa/minisketch> (upstream:
<https://github.com/bitcoin-core/minisketch>)
Authors: Pieter Wuille (sipa), Greg Maxwell, Gleb Naumenko
Examined: master HEAD at clone time 2026-06-03.
Production reference: Erlay (BIP-330) tx-relay reconciliation.
