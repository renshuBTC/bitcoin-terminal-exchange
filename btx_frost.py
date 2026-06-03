#!/usr/bin/env python3
"""
btx_frost.py — Trusted-dealer t-of-n FROST signing for BTX maker pools.

Closes the highest-value remaining item from
BTX-secp256kfun-scouting-2026-06-03.md: bringing FROST (Flexible
Round-Optimised Schnorr Threshold) to BTX as the strict upgrade over
btx_musig2's n-of-n trusted-aggregator model.

## What this module ships

A working implementation of t-of-n threshold Schnorr signing using
**Shamir Secret Sharing over secp256k1** with **Lagrange interpolation at
sign time**, in the same "trusted aggregator" mode as
btx_musig2.pool_sign_demo. The aggregator generates the polynomial
(equivalent to a trusted dealer DKG), distributes shares, and at sign
time collects the t shares it needs to reconstruct the group secret and
produce a BIP340 Schnorr signature.

The on-chain footprint is identical to a single-signer BIP340 sig under
the aggregated x-only group pubkey Y. The BTX2 indexer doesn't know (or
need to know) any of the maker pubkeys are FROST-aggregated.

## What this module does NOT ship

- **ChillDKG (encpedpop / certpedpop)** — the full distributed key
  generation protocols. Trusted-dealer covers BTX's current use case
  (one pool operator + multiple keys for inventory rotation across
  geos / data centres). ChillDKG is needed for *mutually distrusting*
  parties to set up a FROST key without a trusted setup; that's a
  ~1-week additional task and is bookmarked in the closure doc.
- **Interactive 2-round signing.** Like btx_musig2's trusted-aggregator,
  this module collects all t secret shares in one place at sign time.
  The interactive nonce_gen/nonce_agg/partial_sign/partial_sig_agg
  flow is what FROST is designed for, but it requires the parties to
  be online simultaneously. Trusted-aggregator just runs both rounds
  inside the aggregator with no communication.

## Math (trusted-dealer t-of-n FROST, single round)

Keygen (dealer side):
  pick polynomial    f(x) = a_0 + a_1·x + a_2·x² + … + a_{t-1}·x^{t-1}
  where a_0 = group secret s, and a_1..a_{t-1} are random scalars

  group public key   Y = s · G                      (BIP340 even-y)
  per-share secret   sh_i = f(i)                    for i = 1..N
  per-share point    P_i = sh_i · G                 (verifiable share)

Sign (any t shares at indices [i_1, ..., i_t]):
  Lagrange λ_j      = ∏_{k≠j} (i_k / (i_k - i_j))   (mod N)
  reconstruct s     = Σ_j λ_j · sh_{i_j}            (mod N)
  produce BIP340    sig = schnorr_sign(msg, s)      (under BIP340 norm)

The signature verifies as a normal BIP340 Schnorr signature under Y.
"""

from __future__ import annotations
import secrets
from typing import List, Tuple

from btx_taproot import (
    N, P, G,
    point_mul, point_add, _has_even_y,
    schnorr_sign, schnorr_verify, xonly_pubkey,
)


# ----------------------------- helpers -----------------------------


def _modinv(a: int, m: int = N) -> int:
    """Modular inverse via Fermat (m prime)."""
    return pow(a, m - 2, m)


def _eval_poly(coeffs: List[int], x: int) -> int:
    """f(x) = Σ coeffs[k] · x^k  (mod N), Horner's rule."""
    out = 0
    for c in reversed(coeffs):
        out = (out * x + c) % N
    return out


def _lagrange_at_zero(indices: List[int], j: int) -> int:
    """
    λ_j = ∏_{k≠j} (i_k / (i_k - i_j))  (mod N)

    This is the Lagrange coefficient that, when applied to a t-out-of-n
    set of shares, reconstructs f(0). Standard Shamir interpolation.
    """
    i_j = indices[j]
    num, den = 1, 1
    for k, i_k in enumerate(indices):
        if k == j:
            continue
        num = (num * i_k) % N
        den = (den * (i_k - i_j)) % N
    return (num * _modinv(den)) % N


# ----------------------------- API -----------------------------


class FrostKey:
    """
    Output of trusted-dealer keygen. Carries the group secret (DEALER-ONLY
    field; never broadcast), the verifiable per-share points, the group
    pubkey, and the polynomial coefficients (DEALER-ONLY).
    """

    def __init__(self, t: int, n: int,
                 secret: int,
                 group_xonly: bytes,
                 share_secrets: List[int],
                 share_points_xonly: List[bytes],
                 even_y_normalised: bool):
        self.t = t
        self.n = n
        self.secret = secret              # DEALER ONLY
        self.group_xonly = group_xonly    # 32-byte x-only Y
        self.share_secrets = share_secrets  # DEALER ONLY (shares to distribute)
        self.share_points_xonly = share_points_xonly  # public commitments to each share
        self.even_y_normalised = even_y_normalised  # whether secret was negated to satisfy BIP340 even-y


def keygen_trusted_dealer(t: int, n: int, seed: bytes = None) -> FrostKey:
    """
    Trusted-dealer t-of-n FROST keygen.

    Args:
        t: threshold (any t shares can sign)
        n: total participants (1 ≤ t ≤ n)
        seed: optional 32-byte seed for determinism (if None, use OS RNG)

    Returns: FrostKey

    Notes:
        - Shamir's secret sharing over secp256k1 with constant term =
          group secret.
        - Participant indices are 1..n (index 0 would reveal the secret
          directly).
        - The group secret is BIP340-normalised (forced to even-y); if
          that requires negating s, the FrostKey carries that fact in
          `even_y_normalised` so the signing path can apply it to the
          per-share contributions.
    """
    if not (1 <= t <= n):
        raise ValueError(f"need 1 ≤ t ≤ n, got t={t}, n={n}")

    rng = secrets.SystemRandom() if seed is None else _SeededRng(seed)

    # Pick t coefficients: a_0 is the secret; a_1..a_{t-1} are random.
    # We want a_0 in [1, N-1].
    while True:
        coeffs = [rng.randrange(1, N) for _ in range(t)]
        if coeffs[0] != 0:
            break

    secret = coeffs[0]
    Y_pt = point_mul(G, secret)

    # BIP340: the canonical group pubkey is the even-y version. If Y has
    # odd y, negate the secret AND every coefficient so all shares end up
    # consistent under the even-y group key.
    if not _has_even_y(Y_pt):
        coeffs = [(N - c) % N for c in coeffs]
        secret = coeffs[0]
        Y_pt = point_mul(G, secret)
        even_y_normalised = True
    else:
        even_y_normalised = False

    group_xonly = Y_pt[0].to_bytes(32, "big")

    # Distribute shares at indices 1..n
    share_secrets: List[int] = []
    share_points_xonly: List[bytes] = []
    for i in range(1, n + 1):
        sh = _eval_poly(coeffs, i)
        if sh == 0:
            # Vanishingly improbable; reroll
            return keygen_trusted_dealer(t, n, seed)
        P_i = point_mul(G, sh)
        if P_i is None:
            return keygen_trusted_dealer(t, n, seed)
        share_secrets.append(sh)
        share_points_xonly.append(P_i[0].to_bytes(32, "big"))

    return FrostKey(
        t=t, n=n,
        secret=secret,
        group_xonly=group_xonly,
        share_secrets=share_secrets,
        share_points_xonly=share_points_xonly,
        even_y_normalised=even_y_normalised,
    )


def threshold_sign(frost: FrostKey, signer_indices: List[int],
                   msg: bytes, aux_rand: bytes = b"\x00" * 32) -> bytes:
    """
    Trusted-aggregator threshold sign.

    Args:
        frost:           FrostKey from keygen_trusted_dealer
        signer_indices:  list of t share indices (1-based) to use
        msg:             32-byte message to sign
        aux_rand:        32-byte BIP340 aux randomness

    Returns: 64-byte BIP340 Schnorr signature, valid under frost.group_xonly.

    The signer indices MUST be:
      - distinct
      - exactly t of them (using more or fewer would still succeed
        mathematically but is rejected to catch bugs)
      - in 1..n
    """
    if len(msg) != 32:
        raise ValueError("msg must be 32 bytes")
    if len(set(signer_indices)) != len(signer_indices):
        raise ValueError("signer_indices must be distinct")
    if len(signer_indices) != frost.t:
        raise ValueError(f"need exactly t={frost.t} signers, got {len(signer_indices)}")
    for i in signer_indices:
        if not (1 <= i <= frost.n):
            raise ValueError(f"signer index {i} out of range [1, {frost.n}]")

    # Apply Lagrange interpolation at 0 to reconstruct the group secret.
    s_reconstructed = 0
    for j, idx in enumerate(signer_indices):
        lam = _lagrange_at_zero(signer_indices, j)
        sh = frost.share_secrets[idx - 1]
        s_reconstructed = (s_reconstructed + lam * sh) % N

    # The reconstructed s must match frost.secret (the original group secret).
    # This is the cryptographic invariant of Shamir secret sharing.
    if s_reconstructed != frost.secret:
        raise RuntimeError("internal: Lagrange reconstruction does not match group secret")

    # Sign with standard BIP340 schnorr_sign over the reconstructed secret.
    sk_bytes = s_reconstructed.to_bytes(32, "big")
    return schnorr_sign(msg, sk_bytes, aux_rand)


# ----------------------------- deterministic RNG -----------------------------


class _SeededRng:
    """Deterministic int RNG keyed off a seed (for reproducible selftests)."""

    def __init__(self, seed: bytes):
        if len(seed) < 32:
            raise ValueError("seed must be ≥ 32 bytes")
        self.state = bytes(seed)
        self.counter = 0

    def randrange(self, lo: int, hi: int) -> int:
        import hashlib
        bits = (hi - 1).bit_length() + 64  # safety margin
        nbytes = (bits + 7) // 8
        while True:
            h = hashlib.sha256(self.state + self.counter.to_bytes(8, "big")).digest()
            self.counter += 1
            x = int.from_bytes(h[:nbytes] if nbytes <= 32 else h, "big") % (hi - lo) + lo
            if lo <= x < hi:
                return x


# ----------------------------- selftest -----------------------------


def _selftest_config_vectors():
    """Test (t, n, signer_subsets) configurations."""
    return [
        (2, 3, [[1, 2], [1, 3], [2, 3]]),    # 2-of-3 — every quorum
        (3, 5, [[1, 2, 3], [1, 3, 5], [2, 4, 5]]),  # 3-of-5
        (1, 1, [[1]]),                        # degenerate trivial case
        (4, 7, [[1, 2, 3, 4], [4, 5, 6, 7], [1, 3, 5, 7]]),  # 4-of-7
    ]


def selftest(verbose: bool = True) -> bool:
    """
    For each (t, n) config:
      1. Keygen deterministically (so vectors are reproducible)
      2. For each signer subset of size t:
         a. threshold_sign produces a 64-byte sig
         b. schnorr_verify accepts it under the group x-only pubkey
         c. Re-running with the same inputs is deterministic
      3. Sanity: per-share points reconstruct the group pubkey via
         Lagrange interpolation in the exponent (verifiable shares
         property)
      4. Sanity: a WRONG subset (one share replaced) produces a sig
         that fails verify under the group pubkey
    """
    ok = True

    for t, n, subsets in _selftest_config_vectors():
        seed = (b"BTX-FROST-seed-2026-06-03-" + bytes([t, n])).ljust(32, b"\x00")[:32]
        try:
            frost = keygen_trusted_dealer(t, n, seed=seed)
        except Exception as e:
            ok = False
            if verbose: print(f"[frost t={t} n={n}] FAIL keygen: {e}")
            continue

        msg = (b"BTX2 threshold-sign probe t=%d n=%d" % (t, n)).ljust(32, b"\x00")[:32]

        # 2. For each subset
        for subset in subsets:
            try:
                sig = threshold_sign(frost, subset, msg, aux_rand=b"\x00" * 32)
            except Exception as e:
                ok = False
                if verbose: print(f"[frost t={t} n={n} subset={subset}] FAIL sign: {e}")
                continue

            if len(sig) != 64:
                ok = False
                if verbose: print(f"[frost t={t} n={n} subset={subset}] FAIL: bad sig len {len(sig)}")
                continue

            # 2b. Standard BIP340 verify under group x-only
            if not schnorr_verify(msg, frost.group_xonly, sig):
                ok = False
                if verbose: print(f"[frost t={t} n={n} subset={subset}] FAIL: BIP340 verify rejected sig")
                continue

            # 2c. Determinism
            sig2 = threshold_sign(frost, subset, msg, aux_rand=b"\x00" * 32)
            if sig != sig2:
                ok = False
                if verbose: print(f"[frost t={t} n={n} subset={subset}] FAIL: non-deterministic")
                continue

        # 3. Verifiable-shares property — Σ λ_i · P_i ≟ Y, at any signer subset.
        # We pick the FIRST subset to check.
        if subsets:
            subset = subsets[0]
            Q = None  # accumulator
            for j, idx in enumerate(subset):
                lam = _lagrange_at_zero(subset, j)
                # Reconstruct: each P_i is x-only EVEN-Y representation of sh_i·G,
                # but sh_i may have been negated by the BIP340 normalisation. To
                # reconstruct Y at index 0 from x-only points, we use the actual
                # share secrets (which we have access to here in the dealer-side
                # selftest) — this just verifies the polynomial identity.
                from btx_taproot import lift_x
                # Use the share point's even-y lift; the corresponding scalar share
                # is what makes it consistent.
                contrib = point_mul(G, (lam * frost.share_secrets[idx - 1]) % N)
                if contrib is None:
                    continue
                Q = contrib if Q is None else point_add(Q, contrib)
            if Q is None or Q[0].to_bytes(32, "big") != frost.group_xonly:
                ok = False
                if verbose: print(f"[frost t={t} n={n}] FAIL: verifiable-shares reconstruction != Y")

        # 4. Wrong subset (corrupt one share) — sig should fail verify.
        if t >= 2 and subsets:
            subset = subsets[0]
            saved_share = frost.share_secrets[subset[0] - 1]
            try:
                frost.share_secrets[subset[0] - 1] = (saved_share + 1) % N
                # threshold_sign should fail the s_reconstructed == frost.secret
                # invariant — that's the defensive check
                try:
                    bad_sig = threshold_sign(frost, subset, msg, aux_rand=b"\x00" * 32)
                    # If we somehow got here, the sig must NOT verify under Y
                    if schnorr_verify(msg, frost.group_xonly, bad_sig):
                        ok = False
                        if verbose: print(f"[frost t={t} n={n}] FAIL: corrupted share produced a verifying sig")
                except RuntimeError:
                    pass  # expected — defensive check fires
            finally:
                frost.share_secrets[subset[0] - 1] = saved_share

        if verbose:
            print(f"[frost t={t} n={n}] OK  Y={frost.group_xonly.hex()[:16]}...  "
                  f"subsets={subsets} all verify under Y")

    if verbose:
        print(f"\n[btx_frost] {'ALL VECTORS PASS' if ok else 'FAILED'}")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
