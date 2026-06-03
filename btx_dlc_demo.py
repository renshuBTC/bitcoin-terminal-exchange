#!/usr/bin/env python3
"""
btx_dlc_demo.py — End-to-end DLC-style conditional-order demo.

The flow:
  1. Oracle commits to a future event by publishing a nonce point R_o = r_o·G
     (the "attestation point") in advance, alongside the parameters of the
     event ("BTC price > 60k by 2026-07-01").
  2. Maker publishes a BTX2 CONDITIONAL_ORDER record signed with a Schnorr
     adaptor signature whose encryption point T = R_o + Hash("BTC>60k")·G
     — derivable by anyone who knows the oracle's pubkey + event params.
  3. Taker funds the order normally, accepting the conditional pre-signature.
  4. When the event resolves, the oracle publishes its attestation:
        s_o = r_o + Hash("BTC>60k") · d_o   (Schnorr-like)
     This s_o is literally the secret t that unlocks the adaptor sig:
        decrypt(pre_sig, s_o) → completed BIP340 sig → swap settles
  5. If the event doesn't resolve before the BTX2 order's `expiry` height,
     the taker reclaims via the standard timelocked refund path baked into
     the CONDITIONAL_ORDER record.

This module ships the demo only — no on-chain interaction. It proves the
oracle→adaptor→decrypt→settle composition is sound using BTX's existing
primitives:
  - btx_taproot      : BIP340/BIP341 schnorr, tagged hashes, lift_x
  - btx_adaptor      : pre_sign / pre_verify / decrypt / recover
  - (optional) btx_musig2_adaptor for institutional-maker pools

Reference (scouting-doc followup item):
  BTX-secp256k1-zkp-scouting-2026-06-02.md line 271:
    "Build a regtest DLC-style demo: oracle attests outcome → adaptor decrypt
     → swap settles    ~1 month"

In pure-Python form the demo collapses to a small script (no regtest node
required) because all the load-bearing math is on-curve — adding bitcoind
would only test bitcoin's mempool acceptance, which BTX2 already tests
elsewhere.
"""

from __future__ import annotations
from btx_taproot import (
    N, P, G,
    point_mul, point_add, _has_even_y,
    tagged_hash, schnorr_verify, xonly_pubkey,
)
from btx_adaptor import pre_sign, pre_verify, decrypt, recover


# ----------------------------- helpers -----------------------------


def _ser_compressed(pt):
    if pt is None:
        raise ValueError("infinity")
    x, y = pt
    prefix = 0x02 if (y % 2 == 0) else 0x03
    return bytes([prefix]) + x.to_bytes(32, "big")


def _x32(n):
    return n.to_bytes(32, "big")


# ----------------------------- oracle -----------------------------


class Oracle:
    """
    A minimal Discreet-Log-Contract-style oracle.

    Publishes a long-lived pubkey  Po = d_o · G  and a per-event nonce point
    Ro = r_o · G  at event-announcement time. Later, when the event resolves
    to outcome `o`, publishes the attestation scalar:
        s_o = r_o + Hash("BTX2/dlc/outcome", event_id || outcome_bytes) · d_o   (mod N)

    Anyone who knows Po, Ro, event_id, outcome_bytes can compute the
    attestation point  T = Ro + Hash(...)·Po   in advance. The maker uses
    T as the adaptor encryption key. When s_o is published, the adaptor sig
    decrypts.
    """

    EVENT_TAG = "BTX2/dlc/outcome"

    def __init__(self, secret_key: bytes, nonce_secret: bytes):
        if len(secret_key) != 32 or len(nonce_secret) != 32:
            raise ValueError("oracle scalars must be 32 bytes")
        self._d = int.from_bytes(secret_key, "big")
        self._r = int.from_bytes(nonce_secret, "big")
        if not (1 <= self._d < N) or not (1 <= self._r < N):
            raise ValueError("oracle scalars out of range")

        # Publish: Po (x-only with even y), Ro (compressed for parity)
        Po_pt_raw = point_mul(G, self._d)
        if _has_even_y(Po_pt_raw):
            self._d_eff = self._d
            self._Po_pt = Po_pt_raw
        else:
            self._d_eff = N - self._d
            self._Po_pt = (Po_pt_raw[0], (-Po_pt_raw[1]) % P)
        # Po as x-only (even-y normalised, matches what the maker uses)
        self.Po_xonly = _x32(self._Po_pt[0])

        # Ro (compressed; we preserve parity so the encryption-point T derivation
        # by the maker can lift_x_with_parity properly)
        Ro_pt_raw = point_mul(G, self._r)
        if _has_even_y(Ro_pt_raw):
            self._r_eff = self._r
            self._Ro_pt = Ro_pt_raw
        else:
            self._r_eff = N - self._r
            self._Ro_pt = (Ro_pt_raw[0], (-Ro_pt_raw[1]) % P)
        self.Ro_compressed = _ser_compressed(self._Ro_pt)

    @staticmethod
    def _challenge(event_id: bytes, outcome: bytes) -> int:
        return int.from_bytes(
            tagged_hash(Oracle.EVENT_TAG, event_id + outcome),
            "big",
        ) % N

    def attestation_point(self, event_id: bytes, outcome: bytes):
        """
        Compute the attestation point T = Ro + e·Po  (compressed).
        Both maker and taker can derive this independently — no oracle
        secret involved.
        """
        e = self._challenge(event_id, outcome)
        ePo = point_mul(self._Po_pt, e)
        T = point_add(self._Ro_pt, ePo)
        if T is None:
            raise RuntimeError("attestation point landed at infinity")
        return _ser_compressed(T)

    def attest(self, event_id: bytes, outcome: bytes) -> bytes:
        """
        Publish the attestation scalar s_o = r_eff + e · d_eff (mod N).
        This is the secret `t` that unlocks the maker's adaptor sig.
        """
        e = self._challenge(event_id, outcome)
        s_o = (self._r_eff + e * self._d_eff) % N
        if s_o == 0:
            raise RuntimeError("attestation scalar is 0 (vanishingly improbable)")
        return _x32(s_o)


def maker_derive_T(Po_xonly: bytes, Ro_compressed: bytes, event_id: bytes,
                    outcome: bytes) -> bytes:
    """
    Public function — both maker and taker can derive the attestation point
    T = Ro + e·Po given Po, Ro, the event description, and an OUTCOME they
    expect/bet-on. Returns compressed(T).
    """
    from btx_adaptor import _parse_compressed
    # Po as x-only — lift to even-y
    from btx_taproot import lift_x
    Po_pt = lift_x(int.from_bytes(Po_xonly, "big"))
    if Po_pt is None:
        raise ValueError("Po not on curve")
    Ro_pt = _parse_compressed(Ro_compressed)
    e = int.from_bytes(tagged_hash(Oracle.EVENT_TAG, event_id + outcome), "big") % N
    ePo = point_mul(Po_pt, e)
    T = point_add(Ro_pt, ePo)
    if T is None:
        raise RuntimeError("attestation point at infinity")
    return _ser_compressed(T)


# ----------------------------- demo flow -----------------------------


def run_demo(verbose: bool = True) -> bool:
    """
    Step-by-step DLC-style flow. Returns True iff every check passes.

    Stages:
      A. Setup oracle and publish (Po, Ro, event_id).
      B. Maker builds adaptor pre-sig under attestation point T_yes
         (the outcome they want to bet on).
      C. Taker verifies pre-sig matches T_yes (computed independently).
      D. Oracle attests outcome "yes". Maker (or anyone with the pre-sig)
         decrypts → completed BIP340 sig.
      E. Cross-check: recover(pre_sig, completed) returns the attestation
         scalar (which is "t" in adaptor parlance).
      F. Negative test: an attestation for outcome "no" produces a different
         scalar that does NOT decrypt the pre-sig correctly.
    """
    ok = True

    # A. Oracle setup
    oracle = Oracle(
        secret_key=bytes.fromhex(
            "0b432b2677937381aef05bb02a66ecd012773062cf3fa2549e44f58ed2401710"
        ),
        nonce_secret=bytes.fromhex(
            "c90fdaa22168c234c4c6628b80dc1cd129024e088a67cc74020bbea63b14e5c9"
        ),
    )
    Po = oracle.Po_xonly
    Ro = oracle.Ro_compressed
    event_id = b"BTX2-DLC-DEMO-2026-06-03-BTC-PRICE-Q3"
    outcome_yes = b"BTC>60K"
    outcome_no = b"BTC<=60K"

    if verbose:
        print(f"[A] oracle setup")
        print(f"    Po = {Po.hex()}")
        print(f"    Ro = {Ro.hex()}")
        print(f"    event_id = {event_id.decode()}")

    # B. Maker builds adaptor pre-sig
    maker_sk = bytes.fromhex(
        "b7e151628aed2a6abf7158809cf4f3c762e7160f38b4da56a784d9045190cfef"
    )
    maker_xonly = xonly_pubkey(maker_sk)[0]
    sighash = bytes.fromhex(
        "243f6a8885a308d313198a2e03707344a4093822299f31d0082efa98ec4e6c89"
    )
    T_yes = maker_derive_T(Po, Ro, event_id, outcome_yes)
    pre_sig = pre_sign(maker_sk, sighash, T_yes)

    if verbose:
        print(f"[B] maker pre-sig produced under T_yes")
        print(f"    T_yes   = {T_yes.hex()}")
        print(f"    pre_sig = {pre_sig.hex()}")

    # C. Taker (or any verifier) checks the pre-sig is bound to T_yes
    if not pre_verify(pre_sig, maker_xonly, sighash, T_yes):
        if verbose: print("[C] FAIL: pre_verify rejected legit pre-sig")
        return False
    if verbose: print("[C] taker pre_verify under T_yes: OK")

    # D. Oracle attests "yes" — publishes s_o
    s_o = oracle.attest(event_id, outcome_yes)
    completed = decrypt(pre_sig, s_o)
    if completed is None or len(completed) != 65:
        if verbose: print("[D] FAIL: decrypt did not yield 65 bytes")
        return False
    # The completed sig should verify as a normal BIP340 Schnorr sig.
    # btx_adaptor.decrypt returns 65 bytes = compressed(R̂) || s. The BIP340
    # x-only sig is x(R̂) || s_bip340 where s_bip340 = s if R̂ has even y,
    # else (N - s). Apply that normalisation now.
    R_hat_compressed = completed[:33]
    s_bytes = completed[33:]
    R_hat_x = R_hat_compressed[1:]
    if R_hat_compressed[0] == 0x03:
        # R̂ has odd y → flip s for BIP340 even-y convention
        s_int = int.from_bytes(s_bytes, "big")
        s_norm = (N - s_int) % N
        sig_bip340 = R_hat_x + s_norm.to_bytes(32, "big")
    else:
        sig_bip340 = R_hat_x + s_bytes

    if not schnorr_verify(sighash, maker_xonly, sig_bip340):
        if verbose: print("[D] FAIL: completed sig fails BIP340 verify")
        return False
    if verbose:
        print(f"[D] oracle attestation s_o = {s_o.hex()}")
        print(f"    completed → BIP340 sig = {sig_bip340.hex()}")
        print("    schnorr_verify under maker_xonly: OK  (swap can settle)")

    # E. Round-trip: recover the attestation scalar from pre/completed
    rec_t = recover(pre_sig, completed)
    if rec_t != s_o:
        if verbose: print(f"[E] FAIL: recover got {rec_t.hex() if rec_t else None}, want {s_o.hex()}")
        return False
    if verbose: print("[E] recover(pre, completed) == s_o: OK")

    # F. Negative: attestation for the WRONG outcome must NOT decrypt the
    #    pre-sig. Specifically, "no"-attestation gives a different scalar;
    #    if we naively decrypt with it, the recovered "t" won't be s_o,
    #    and the resulting BIP340 sig will not verify (with very high prob).
    s_o_no = oracle.attest(event_id, outcome_no)
    if s_o_no == s_o:
        if verbose: print("[F] FAIL: yes and no attestation scalars collided")
        return False
    completed_no = decrypt(pre_sig, s_o_no)
    R_hat_compressed_no = completed_no[:33]
    s_bytes_no = completed_no[33:]
    if R_hat_compressed_no[0] == 0x03:
        s_int_no = int.from_bytes(s_bytes_no, "big")
        s_norm_no = (N - s_int_no) % N
        sig_bip340_no = R_hat_compressed_no[1:] + s_norm_no.to_bytes(32, "big")
    else:
        sig_bip340_no = R_hat_compressed_no[1:] + s_bytes_no
    if schnorr_verify(sighash, maker_xonly, sig_bip340_no):
        if verbose: print("[F] FAIL: wrong-outcome attestation produced a valid BIP340 sig (cryptographic break)")
        return False
    if verbose: print("[F] wrong-outcome attestation fails BIP340 verify: OK")

    if verbose:
        print("\n[btx_dlc_demo] ALL STAGES PASS — oracle→adaptor→decrypt→settle is sound.")
    return True


if __name__ == "__main__":
    import sys
    sys.exit(0 if run_demo() else 1)
