#!/usr/bin/env python3
"""
btx_taproot.py — BIP340/341 Taproot commit/reveal for the BTX witness-envelope carrier.

`btx_carrier.py` proved the envelope ENCODING (the tapscript that holds the artifact). To actually
PUBLISH an order via that carrier you must:
  1. commit: pay to a P2TR output whose output key = tweak(internal_key, tapleaf(envelope)),
  2. reveal: spend that output, putting [<>, envelope_tapscript, control_block] in the witness.

This module implements the pure crypto for both, with NO external dependency (python-bitcoinlib
0.12.2 predates Taproot and there's no libsecp here), and self-verifies against the official BIP341
wallet test vectors. It removes BTX's dependence on a relaxed -datacarriersize: witness data is not
subject to the datacarrier limit.

Verified offline against BIP341 vectors (`btx_taproot.py` selftest): tapleaf hash, single-leaf
merkle root, the TapTweak output-key tweak, the resulting x-only output key, the P2TR scriptPubKey,
the bech32m address, and the script-path control block — all match the published vectors.

The commit/reveal *broadcast* is now built in `btx_envelope_publish.py` (it funds the commit and
signs the reveal using `schnorr_sign` + `tap_sighash` from this module). The selftest here also checks `schnorr_sign`/`schnorr_verify` against the official BIP340 vectors,
`tap_sighash` against the official BIP341 keyPathSpending vectors, AND — since BIP341 publishes no
script-path sighash vector — the script-path (ext_flag=1) sighash against values independently produced
by the `embit` library (which reproduces the official key-path vectors). On-node acceptance is also
PROVEN twice, on two distinct networks (the low vs high block heights are the tell): a custom signet
(envelope reveal txid 56234a0d…, block 121, 2026-05-24) AND public signet, where the reveal
(txid 60e969a3…, block 305837) propagated cross-node under default relay policy and was mined by an
independent signer — see BTX.md. In both, the order was served from witness data, so the script-path
sighash is consensus-correct. See BTX-envelope-publish-runbook.md.
"""
import hashlib, struct

# ----------------------------- secp256k1 (minimal) -----------------------------
P  = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N  = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
G  = (GX, GY)


def _inv(a, m=P):
    return pow(a, m - 2, m)


def point_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if p1 == p2:
        lam = (3 * x1 * x1) * _inv(2 * y1) % P
    else:
        lam = (y2 - y1) * _inv(x2 - x1) % P
    x3 = (lam * lam - x1 - x2) % P
    y3 = (lam * (x1 - x3) - y1) % P
    return (x3, y3)


def point_mul(p, k):
    r = None
    while k:
        if k & 1:
            r = point_add(r, p)
        p = point_add(p, p)
        k >>= 1
    return r


def lift_x(x):
    """BIP340 lift_x: return the point with even y for x-coordinate `x`, or raise if not on curve."""
    if not (0 < x < P):
        raise ValueError("x out of range")
    c = (pow(x, 3, P) + 7) % P
    y = pow(c, (P + 1) // 4, P)
    if (y * y) % P != c:
        raise ValueError("x is not on the curve")
    if y & 1:
        y = P - y
    return (x, y)


# ----------------------------- tagged hashes -----------------------------
def tagged_hash(tag, msg):
    t = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(t + t + msg).digest()


def _compact_size(n):
    if n < 0xfd:
        return bytes([n])
    if n <= 0xffff:
        return b'\xfd' + n.to_bytes(2, 'little')
    if n <= 0xffffffff:
        return b'\xfe' + n.to_bytes(4, 'little')
    return b'\xff' + n.to_bytes(8, 'little')


def tapleaf_hash(script, leaf_version=0xc0):
    s = bytes(script)
    return tagged_hash("TapLeaf", bytes([leaf_version]) + _compact_size(len(s)) + s)


def tapbranch_hash(a, b):
    return tagged_hash("TapBranch", (a + b) if a <= b else (b + a))


# ----------------------------- BIP341 tweak -----------------------------
def taproot_tweak_pubkey(internal_xonly, merkle_root=b""):
    """Return (parity, tweaked_xonly_32). internal_xonly: 32-byte x-only key. merkle_root: 32 bytes
    (or b"" for key-path-only)."""
    internal_xonly = bytes(internal_xonly)
    t = int.from_bytes(tagged_hash("TapTweak", internal_xonly + bytes(merkle_root)), 'big')
    if t >= N:
        raise ValueError("tweak >= group order")
    P_pt = lift_x(int.from_bytes(internal_xonly, 'big'))
    Q = point_add(P_pt, point_mul(G, t))
    if Q is None:
        raise ValueError("infinite tweaked point")
    return (Q[1] & 1, Q[0].to_bytes(32, 'big'))


def p2tr_scriptpubkey(tweaked_xonly):
    """OP_1 <32-byte x-only output key>  ->  51 20 <key>."""
    return b'\x51\x20' + bytes(tweaked_xonly)


def control_block(internal_xonly, parity, merkle_path=b"", leaf_version=0xc0):
    """Script-path control block: (leaf_version | parity) || internal_xonly || merkle_path.
    For a single-leaf tree (the BTX envelope) merkle_path is empty."""
    return bytes([leaf_version | parity]) + bytes(internal_xonly) + bytes(merkle_path)


# ----------------------------- bech32m (BIP350) -----------------------------
_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_polymod(values):
    gen = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1ffffff) << 5) ^ v
        for i in range(5):
            chk ^= gen[i] if ((b >> i) & 1) else 0
    return chk


def _hrp_expand(hrp):
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convertbits(data, frm, to, pad=True):
    acc = 0; bits = 0; ret = []
    maxv = (1 << to) - 1
    for b in data:
        acc = (acc << frm) | b
        bits += frm
        while bits >= to:
            bits -= to
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (to - bits)) & maxv)
    return ret


def segwit_address(witver, witprog, hrp="bc"):
    """BIP350 bech32m for witness v1+ (Taproot uses witver=1)."""
    data = [witver] + _convertbits(list(witprog), 8, 5)
    const = 0x2bc830a3   # bech32m constant
    values = _hrp_expand(hrp) + data
    polymod = _bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ const
    checksum = [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_CHARSET[d] for d in (data + checksum))


# ----------------------------- BTX envelope commit/reveal -----------------------------
def commit_for_envelope(internal_xonly, envelope_tapscript_bytes, hrp="bc"):
    """Single-leaf commit for the BTX envelope. Returns dict with the P2TR scriptPubKey/address to
    fund (the commit), and the control block needed to reveal."""
    leaf = tapleaf_hash(envelope_tapscript_bytes, 0xc0)
    parity, out_xonly = taproot_tweak_pubkey(internal_xonly, leaf)
    spk = p2tr_scriptpubkey(out_xonly)
    return {
        "tapleaf_hex": leaf.hex(),
        "output_key_xonly_hex": out_xonly.hex(),
        "commit_scriptPubKey_hex": spk.hex(),
        "commit_address": segwit_address(1, out_xonly, hrp),
        "control_block_hex": control_block(internal_xonly, parity).hex(),
        "parity": parity,
    }


# ----------------------------- BIP340 Schnorr (sign + verify) -----------------------------
# Needed to PUBLISH the envelope: the reveal tapscript is `<xonly> OP_CHECKSIG OP_FALSE OP_IF .. `,
# so the reveal witness must carry a BIP340 Schnorr signature over the BIP341 script-path sighash.
def _has_even_y(point):
    return point[1] % 2 == 0


def _b32(n):
    return int(n).to_bytes(32, 'big')


def xonly_pubkey(seckey: bytes):
    """Return (xonly_pubkey_32, point) for a 32-byte secret. xonly = x of the (implicitly even-y) key."""
    d0 = int.from_bytes(seckey, 'big')
    if not (1 <= d0 < N):
        raise ValueError("secret key out of range")
    point = point_mul(G, d0)
    return _b32(point[0]), point


def schnorr_sign(msg: bytes, seckey: bytes, aux_rand: bytes = b'\x00' * 32) -> bytes:
    """BIP340 Schnorr signature over a 32-byte message with a 32-byte secret key."""
    if len(msg) != 32:
        raise ValueError("msg must be 32 bytes")
    d0 = int.from_bytes(seckey, 'big')
    if not (1 <= d0 < N):
        raise ValueError("secret key out of range")
    point = point_mul(G, d0)
    d = d0 if _has_even_y(point) else N - d0
    px = _b32(point[0])
    t = (d ^ int.from_bytes(tagged_hash("BIP0340/aux", aux_rand), 'big')).to_bytes(32, 'big')
    k0 = int.from_bytes(tagged_hash("BIP0340/nonce", t + px + msg), 'big') % N
    if k0 == 0:
        raise ValueError("k0 == 0 (vanishingly unlikely; retry with different aux_rand)")
    R = point_mul(G, k0)
    k = k0 if _has_even_y(R) else N - k0
    rx = _b32(R[0])
    e = int.from_bytes(tagged_hash("BIP0340/challenge", rx + px + msg), 'big') % N
    sig = rx + _b32((k + e * d) % N)
    if not schnorr_verify(msg, px, sig):  # never emit a sig we can't verify
        raise ValueError("internal error: produced signature fails self-verification")
    return sig


def schnorr_verify(msg: bytes, pubkey_xonly: bytes, sig: bytes) -> bool:
    """BIP340 verify. P (the global) is the field prime; the public point is `point` here."""
    if len(msg) != 32 or len(pubkey_xonly) != 32 or len(sig) != 64:
        return False
    try:
        point = lift_x(int.from_bytes(pubkey_xonly, 'big'))
    except ValueError:
        return False
    r = int.from_bytes(sig[:32], 'big')
    s = int.from_bytes(sig[32:], 'big')
    if r >= P or s >= N:
        return False
    e = int.from_bytes(tagged_hash("BIP0340/challenge", sig[:32] + pubkey_xonly + msg), 'big') % N
    R = point_add(point_mul(G, s), point_mul(point, (N - e) % N))
    if R is None or not _has_even_y(R):
        return False
    return R[0] == r


# ----------------------------- BIP341/342 TapSighash -----------------------------
SIGHASH_DEFAULT = 0x00
SIGHASH_ALL = 0x01
SIGHASH_NONE = 0x02
SIGHASH_SINGLE = 0x03
SIGHASH_ANYONECANPAY = 0x80


def _ser_script(spk: bytes) -> bytes:
    return _compact_size(len(spk)) + bytes(spk)


def tap_sighash(*, version, locktime, vin, spent_amounts, spent_spks, vout, input_index,
                hash_type=SIGHASH_DEFAULT, ext_flag=0, tapleaf_hash=None, annex=None,
                codesep_pos=0xffffffff):
    """BIP341 SigMsg + the BIP342 (ext_flag=1) script-path extension, returned as the 32-byte
    TapSighash. Inputs are primitives (no python-bitcoinlib dependency):
      vin           : list of (txid_bytes32_internal_order, vout_u32, sequence_u32)
      spent_amounts : list[int] sats, one per input
      spent_spks    : list[bytes] scriptPubKey, one per input
      vout          : list of (value_sats:int, spk:bytes)
    For a script-path spend pass ext_flag=1 and a 32-byte tapleaf_hash (BIP341 'TapLeaf')."""
    # BIP341 §4.3: a verifier MUST reject any sighash type outside the defined set. Enforce it here so a
    # caller cannot construct a SigMsg for an undefined type (e.g. 0x04) that no validator would accept.
    if hash_type not in (0x00, 0x01, 0x02, 0x03, 0x81, 0x82, 0x83):
        raise ValueError(f"invalid sighash type 0x{hash_type:02x} (BIP341 §4.3)")
    sha = lambda b: hashlib.sha256(b).digest()
    out_type = hash_type & 0x03
    anyone = (hash_type & SIGHASH_ANYONECANPAY) != 0
    m = bytearray()
    m += bytes([hash_type & 0xff])
    m += struct.pack('<i', version)
    m += struct.pack('<I', locktime)
    if not anyone:
        m += sha(b''.join(txid + struct.pack('<I', n) for (txid, n, _s) in vin))   # sha_prevouts
        m += sha(b''.join(struct.pack('<q', a) for a in spent_amounts))            # sha_amounts
        m += sha(b''.join(_ser_script(s) for s in spent_spks))                     # sha_scriptpubkeys
        m += sha(b''.join(struct.pack('<I', s) for (_t, _n, s) in vin))            # sha_sequences
    if out_type not in (SIGHASH_NONE, SIGHASH_SINGLE):
        m += sha(b''.join(struct.pack('<q', v) + _ser_script(s) for (v, s) in vout))  # sha_outputs
    annex_present = annex is not None
    m += bytes([(ext_flag * 2) + (1 if annex_present else 0)])                      # spend_type
    if anyone:
        (txid, n, seq) = vin[input_index]
        m += txid + struct.pack('<I', n)
        m += struct.pack('<q', spent_amounts[input_index])
        m += _ser_script(spent_spks[input_index])
        m += struct.pack('<I', seq)
    else:
        m += struct.pack('<I', input_index)
    if annex_present:
        m += sha(_compact_size(len(annex)) + bytes(annex))
    if out_type == SIGHASH_SINGLE:
        if input_index >= len(vout):     # SINGLE with no matching output -> clean error, not IndexError
            raise ValueError("SIGHASH_SINGLE: no output at input_index")
        (v, s) = vout[input_index]
        m += sha(struct.pack('<q', v) + _ser_script(s))
    if ext_flag == 1:
        if tapleaf_hash is None or len(tapleaf_hash) != 32:
            raise ValueError("script-path sighash needs a 32-byte tapleaf_hash")
        m += bytes(tapleaf_hash) + b'\x00' + struct.pack('<I', codesep_pos)         # leaf || keyver || codesep
    return tagged_hash("TapSighash", b'\x00' + bytes(m))   # 0x00 = sighash epoch


# ----------------------------- official BIP340 / BIP341 vectors -----------------------------
# BIP340 Schnorr test vectors (subset, 32-byte messages only): (seckey, pubkey, aux, msg, sig, result).
# Empty seckey => verify-only. From bitcoin/bips bip-0340/test-vectors.csv.
_BIP340 = [
    # signing vectors (seckey present): sign(msg, sk, aux) must equal sig, and verify must pass
    ("0000000000000000000000000000000000000000000000000000000000000003",
     "F9308A019258C31049344F85F89D5229B531C845836F99B08601F113BCE036F9",
     "0000000000000000000000000000000000000000000000000000000000000000",
     "0000000000000000000000000000000000000000000000000000000000000000",
     "E907831F80848D1069A5371B402410364BDF1C5F8307B0084C55F1CE2DCA821525F66A4A85EA8B71E482A74F382D2CE5EBEEE8FDB2172F477DF4900D310536C0", True),
    ("B7E151628AED2A6ABF7158809CF4F3C762E7160F38B4DA56A784D9045190CFEF",
     "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659",
     "0000000000000000000000000000000000000000000000000000000000000001",
     "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89",
     "6896BD60EEAE296DB48A229FF71DFE071BDE413E6D43F917DC8DCF8C78DE33418906D11AC976ABCCB20B091292BFF4EA897EFCB639EA871CFA95F6DE339E4B0A", True),
    ("C90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B14E5C9",
     "DD308AFEC5777E13121FA72B9CC1B7CC0139715309B086C960E18FD969774EB8",
     "C87AA53824B4D7AE2EB035A2B5BBBCCC080E76CDC6D1692C4B0B62D798E6D906",
     "7E2D58D8B3BCDF1ABADEC7829054F90DDA9805AAB56C77333024B9D0A508B75C",
     "5831AAEED7B44BB74E5EAB94BA9D4294C49BCF2A60728D8B4C200F50DD313C1BAB745879A5AD954A72C45A91C3A51D3C7ADEA98D82F8481E0E1E03674A6F3FB7", True),
    ("0B432B2677937381AEF05BB02A66ECD012773062CF3FA2549E44F58ED2401710",
     "25D1DFF95105F5253C4022F628A996AD3A0D95FBF21D468A1B33F8C160D8F517",
     "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
     "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
     "7EB0509757E246F19449885651611CB965ECC1A187DD51B64FDA1EDC9637D5EC97582B9CB13DB3933705B32BA982AF5AF25FD78881EBB32771FC5922EFC66EA3", True),
    # verify-only vectors (seckey empty) — the FULL official set, vectors 4..14. 5..14 are the rejecting
    # vectors and exercise every negative class: pubkey-not-on-curve (5), has_even_y(R) false (6),
    # negated msg/s (7,8), R = point at infinity (9,10), r not an X coordinate (11), r = field size (12),
    # s = curve order (13), pubkey exceeds field size (14). Vectors 15-18 (variable-length messages, BIP340
    # 2022 update) are OUT OF SCOPE: this is a 32-byte-message signer (it only ever signs tap sighashes)
    # and rejects non-32-byte input via an explicit guard, so those are intentionally not included.
    ("", "D69C3509BB99E412E68B0FE8544E72837DFA30746D8BE2AA65975F29D22DC7B9", "",
     "4DF3C3F68FCC83B27E9D42C90431A72499F17875C81A599B566C9889B9696703",
     "00000000000000000000003B78CE563F89A0ED9414F5AA28AD0D96D6795F9C6376AFB1548AF603B3EB45C9F8207DEE1060CB71C04E80F593060B07D28308D7F4", True),   # v4
    ("", "EEFDEA4CDB677750A420FEE807EACF21EB9898AE79B9768766E4FAA04A2D4A34", "",
     "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89",
     "6CFF5C3BA86C69EA4B7376F31A9BCB4F74C1976089B2D9963DA2E5543E17776969E89B4C5564D00349106B8497785DD7D1D713A8AE82B32FA79D5F7FC407D39B", False),  # v5 pubkey not on curve
    ("", "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659", "",
     "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89",
     "FFF97BD5755EEEA420453A14355235D382F6472F8568A18B2F057A14602975563CC27944640AC607CD107AE10923D9EF7A73C643E166BE5EBEAFA34B1AC553E2", False),  # v6 has_even_y(R) false
    ("", "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659", "",
     "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89",
     "1FA62E331EDBC21C394792D2AB1100A7B432B013DF3F6FF4F99FCB33E0E1515F28890B3EDB6E7189B630448B515CE4F8622A954CFE545735AAEA5134FCCDB2BD", False),  # v7 negated message
    ("", "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659", "",
     "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89",
     "6CFF5C3BA86C69EA4B7376F31A9BCB4F74C1976089B2D9963DA2E5543E177769961764B3AA9B2FFCB6EF947B6887A226E8D7C93E00C5ED0C1834FF0D0C2E6DA6", False),  # v8 negated s value
    ("", "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659", "",
     "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89",
     "0000000000000000000000000000000000000000000000000000000000000000123DDA8328AF9C23A94C1FEECFD123BA4FB73476F0D594DCB65C6425BD186051", False),  # v9 R = infinity (x=0)
    ("", "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659", "",
     "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89",
     "00000000000000000000000000000000000000000000000000000000000000017615FBAF5AE28864013C099742DEADB4DBA87F11AC6754F93780D5A1837CF197", False),  # v10 R = infinity (x=1)
    ("", "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659", "",
     "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89",
     "4A298DACAE57395A15D0795DDBFD1DCB564DA82B0F269BC70A74F8220429BA1D69E89B4C5564D00349106B8497785DD7D1D713A8AE82B32FA79D5F7FC407D39B", False),  # v11 r not an X coord
    ("", "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659", "",
     "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89",
     "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F69E89B4C5564D00349106B8497785DD7D1D713A8AE82B32FA79D5F7FC407D39B", False),  # v12 r = field size
    ("", "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659", "",
     "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89",
     "6CFF5C3BA86C69EA4B7376F31A9BCB4F74C1976089B2D9963DA2E5543E177769FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141", False),  # v13 s = curve order
    ("", "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC30", "",
     "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89",
     "6CFF5C3BA86C69EA4B7376F31A9BCB4F74C1976089B2D9963DA2E5543E17776969E89B4C5564D00349106B8497785DD7D1D713A8AE82B32FA79D5F7FC407D39B", False),  # v14 pubkey exceeds field size
]

# BIP341 keyPathSpending vector (bitcoin/bips bip-0341/wallet-test-vectors.json): one 9-input tx and
# the expected per-input TapSighash for a spread of sighash types. ext_flag=0 (key path), which
# exercises the whole common SigMsg (ALL/NONE/SINGLE/DEFAULT + ANYONECANPAY + the single-output hash).
_BIP341_RAWTX = (
    "02000000097de20cbff686da83a54981d2b9bab3586f4ca7e48f57f5b55963115f3b334e9c010000000000000000"
    "d7b7cab57b1393ace2d064f4d4a2cb8af6def61273e127517d44759b6dafdd990000000000ffffffff"
    "f8e1f583384333689228c5d28eac13366be082dc57441760d957275419a418420000000000ffffffff"
    "f0689180aa63b30cb162a73c6d2a38b7eeda2a83ece74310fda0843ad604853b0100000000feffffff"
    "aa5202bdf6d8ccd2ee0f0202afbbb7461d9264a25e5bfd3c5a52ee1239e0ba6c0000000000feffffff"
    "956149bdc66faa968eb2be2d2faa29718acbfe3941215893a2a3446d32acd0500000000000000000"
    "00e664b9773b88c09c32cb70a2a3e4da0ced63b7ba3b22f848531bbb1d5d5f4c940100000000000000"
    "00e9aa6b8e6c9de67619e6a3924ae25696bb7b694bb677a632a74ef7eadfd4eabf0000000000ffffffff"
    "a778eb6a263dc090464cd125c466b5a99667720b1c110468831d058aa1b82af10100000000ffffffff"
    "0200ca9a3b000000001976a91406afd46bcdfd22ef94ac122aa11f241244a37ecc88ac"
    "807840cb0000000020ac9a87f5594be208f8532db38cff670c450ed2fea8fcdefcc9a663f78bab962b0065cd1d"
)
_BIP341_UTXOS = [  # (scriptPubKey_hex, amount_sats) in input order
    ("512053a1f6e454df1aa2776a2814a721372d6258050de330b3c6d10ee8f4e0dda343", 420000000),
    ("5120147c9c57132f6e7ecddba9800bb0c4449251c92a1e60371ee77557b6620f3ea3", 462000000),
    ("76a914751e76e8199196d454941c45d1b3a323f1433bd688ac", 294000000),
    ("5120e4d810fd50586274face62b8a807eb9719cef49c04177cc6b76a9a4251d5450e", 504000000),
    ("512091b64d5324723a985170e4dc5a0f84c041804f2cd12660fa5dec09fc21783605", 630000000),
    ("00147dd65592d0ab2fe0d0257d571abf032cd9db93dc", 378000000),
    ("512075169f4001aa68f15bbed28b218df1d0a62cbbcf1188c6665110c293c907b831", 672000000),
    ("5120712447206d7a5238acc7ff53fbe94a3b64539ad291c7cdbc490b7577e4b17df5", 546000000),
    ("512077e30a5522dd9f894c3f8b8bd4c4b2cf82ca7da8a3ea6a239655c39c050ab220", 588000000),
]
_BIP341_SIGHASHES = [  # (txinIndex, hashType, expected_sigHash_hex)
    (0, 3,   "2514a6272f85cfa0f45eb907fcb0d121b808ed37c6ea160a5a9046ed5526d555"),
    (1, 131, "325a644af47e8a5a2591cda0ab0723978537318f10e6a63d4eed783b96a71a4d"),
    (3, 1,   "bf013ea93474aa67815b1b6cc441d23b64fa310911d991e713cd34c7f5d46669"),
    (4, 0,   "4f900a0bae3f1446fd48490c2958b5a023228f01661cda3496a11da502a7f7ef"),
    (6, 2,   "15f25c298eb5cdc7eb1d638dd2d45c97c4c59dcaec6679cfc16ad84f30876b85"),
    (7, 130, "cd292de50313804dabe4685e83f923d2969577191a3e1d2882220dca88cbeb10"),
    (8, 129, "cccb739eca6c13a8a89e6e5cd317ffe55669bbda23f2fd37b0f18755e008edd2"),
]


def _read_varint(b, o):
    n = b[o[0]]; o[0] += 1
    if n < 0xfd:
        return n
    width = {0xfd: 2, 0xfe: 4, 0xff: 8}[n]
    v = int.from_bytes(b[o[0]:o[0] + width], 'little'); o[0] += width
    return v


def parse_unsigned_tx(raw_hex):
    """Minimal legacy (no-witness) tx parser -> (version, locktime, vin, vout) where vin entries are
    (txid_bytes_internal_order, vout_u32, sequence_u32) and vout entries are (value_sats, spk_bytes)."""
    b = bytes.fromhex(raw_hex); o = [0]
    # A count varint can never exceed the buffer length (each input >= 41 bytes, each output >= 9), so
    # reject a varint bomb up front — without this, `range(2**64)` against a short buffer would spin
    # ~forever. Defense-in-depth: this parser is currently only fed the fixed BIP341 test vector.
    def _count(b, o):
        n = _read_varint(b, o)
        if n > len(b):
            raise ValueError("tx in/out count exceeds buffer (varint bomb)")
        return n
    version = int.from_bytes(b[0:4], 'little', signed=True); o[0] = 4
    vin = []
    for _ in range(_count(b, o)):
        txid = b[o[0]:o[0] + 32]; o[0] += 32
        vout = int.from_bytes(b[o[0]:o[0] + 4], 'little'); o[0] += 4
        slen = _read_varint(b, o); o[0] += slen
        seq = int.from_bytes(b[o[0]:o[0] + 4], 'little'); o[0] += 4
        vin.append((txid, vout, seq))
    vout = []
    for _ in range(_count(b, o)):
        val = int.from_bytes(b[o[0]:o[0] + 8], 'little'); o[0] += 8
        slen = _read_varint(b, o)
        spk = b[o[0]:o[0] + slen]; o[0] += slen
        vout.append((val, spk))
    locktime = int.from_bytes(b[o[0]:o[0] + 4], 'little'); o[0] += 4
    return version, locktime, vin, vout


def _crypto_vector_checks(checks):
    """Add BIP340 (Schnorr sign+verify) and BIP341 (TapSighash) official-vector checks to `checks`."""
    for i, (sk, pk, aux, msg, sig, result) in enumerate(_BIP340):
        m = bytes.fromhex(msg)
        if sk:  # signing vector: reproduce the exact signature, then self-verify
            produced = schnorr_sign(m, bytes.fromhex(sk), bytes.fromhex(aux))
            checks[f"bip340_v{i}_sign_matches"] = (produced.hex().upper() == sig.upper())
        checks[f"bip340_v{i}_verify"] = (schnorr_verify(m, bytes.fromhex(pk), bytes.fromhex(sig)) is result)
    version, locktime, vin, vout = parse_unsigned_tx(_BIP341_RAWTX)
    spent_amounts = [a for (_s, a) in _BIP341_UTXOS]
    spent_spks = [bytes.fromhex(s) for (s, _a) in _BIP341_UTXOS]
    for (idx, ht, expected) in _BIP341_SIGHASHES:
        got = tap_sighash(version=version, locktime=locktime, vin=vin, spent_amounts=spent_amounts,
                          spent_spks=spent_spks, vout=vout, input_index=idx, hash_type=ht, ext_flag=0)
        checks[f"bip341_sighash_in{idx}_ht{ht}"] = (got.hex() == expected)
    # defensive: SIGHASH_SINGLE with no matching output errors cleanly (ValueError, not IndexError)
    try:
        tap_sighash(version=2, locktime=0, vin=[(b'\x00' * 32, 0, 0xffffffff)], spent_amounts=[1000],
                    spent_spks=[b'\x51\x20' + b'\x00' * 32], vout=[], input_index=0, hash_type=SIGHASH_SINGLE)
        checks["bip341_single_no_output_guard"] = False
    except ValueError:
        checks["bip341_single_no_output_guard"] = True
    # SCRIPT-PATH (ext_flag=1) TapSighash golden vectors. BIP341's published wallet vectors are KEY-PATH
    # only, so the script-path branch BTX actually uses for the envelope reveal had no offline vector.
    # These goldens were produced by an INDEPENDENT implementation (the `embit` library), which exactly
    # reproduces the official key-path vectors for DEFAULT/ALL/NONE — the modes used here; DEFAULT (0x00)
    # is BTX's production reveal mode. Self-contained 2-in / 2-out tx, input 0 is the script-path spend.
    sp_ins = [(bytes.fromhex("11" * 32), 0, 0xfffffffd), (bytes.fromhex("22" * 32), 2, 0xffffffff)]
    sp_spks = [bytes.fromhex("5120" + "33" * 32), bytes.fromhex("0014" + "44" * 20)]
    sp_amts = [150000, 250000]
    sp_outs = [(120000, bytes.fromhex("5120" + "55" * 32)), (260000, bytes.fromhex("0014" + "66" * 20))]
    sp_leaf = tapleaf_hash(bytes.fromhex("20" + "ab" * 32 + "ac"), 0xc0)   # <32B pubkey> OP_CHECKSIG
    _SCRIPTPATH_GOLDEN = {
        0x00: "a15e8933049a780ebfb42e807bd816154b9628854ad077f65b976ecad1c5265b",  # SIGHASH_DEFAULT (prod)
        0x01: "d11626d45f20ae21ea1e3480e0d8589bdf5def4f8c5d54657021ff4c115e2083",  # SIGHASH_ALL
        0x02: "a8e5e30f4c5041aded05d6220b23da1411c6fece953630240d466fa3bb9099e2",  # SIGHASH_NONE
    }
    for ht, expected in _SCRIPTPATH_GOLDEN.items():
        got = tap_sighash(version=2, locktime=777, vin=sp_ins, spent_amounts=sp_amts, spent_spks=sp_spks,
                          vout=sp_outs, input_index=0, hash_type=ht, ext_flag=1, tapleaf_hash=sp_leaf)
        checks[f"bip341_scriptpath_sighash_ht{ht}"] = (got.hex() == expected)


# ----------------------------- selftest vs BIP341 vectors -----------------------------
def _build_merkle(tree):
    """Recursively compute the merkle root from a BIP341 scriptTree node (dict leaf or [a,b] branch)."""
    if tree is None:
        return b""
    if isinstance(tree, dict):
        return tapleaf_hash(bytes.fromhex(tree["script"]), tree["leafVersion"])
    a = _build_merkle(tree[0]); b = _build_merkle(tree[1])
    return tapbranch_hash(a, b)


def selftest(vectors_path=None):
    import json, os
    if vectors_path is None:
        vectors_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "bip341_vectors_subset.json")
    vecs = json.load(open(vectors_path))
    checks = {}
    for i, v in enumerate(vecs):
        internal = bytes.fromhex(v["internalPubkey"])
        mr = _build_merkle(v.get("tree"))
        if v["merkleRoot"] is None:
            checks[f"v{i}_merkleRoot_empty"] = (mr == b"")
        else:
            checks[f"v{i}_merkleRoot"] = (mr.hex() == v["merkleRoot"])
        parity, out = taproot_tweak_pubkey(internal, mr)
        # verify the tweak scalar too
        t = tagged_hash("TapTweak", internal + mr).hex()
        checks[f"v{i}_tweak"] = (t == v["tweak"])
        checks[f"v{i}_tweakedPubkey"] = (out.hex() == v["tweakedPubkey"])
        checks[f"v{i}_scriptPubKey"] = (p2tr_scriptpubkey(out).hex() == v["scriptPubKey"])
        checks[f"v{i}_bech32m_address"] = (segwit_address(1, out) == v["bip350Address"])
        if v.get("controlBlock"):
            cb = control_block(internal, parity).hex()
            checks[f"v{i}_controlBlock"] = (cb == v["controlBlock"])
    # extra: EC engine internal consistency (no external answer needed)
    checks["G_on_curve"] = ((GY * GY - GX ** 3 - 7) % P == 0)
    checks["nG_is_infinity"] = (point_mul(G, N) is None)
    checks["mul5_eq_add5"] = (point_mul(G, 5) == point_add(point_add(point_add(point_add(G, G), G), G), G))
    # BIP340 Schnorr (sign/verify) + BIP341 TapSighash against official vectors
    _crypto_vector_checks(checks)
    allpass = all(checks.values())
    print(json.dumps({"checks": checks, "ALL_PASS": allpass}, indent=2))
    return allpass


if __name__ == "__main__":
    selftest()
