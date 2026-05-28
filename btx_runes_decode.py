#!/usr/bin/env python3
"""
btx_runes_decode.py — a full(er) Runes runestone DECODER (Phase A of the live-activity feed).

`btx_runes.py` has the byte-accurate *encoder* (validated vs canonical `ord`) and a *minimal*
edict-only decoder. This module decodes ARBITRARY mainnet runestones from a transaction's
`OP_RETURN OP_PUSHNUM_13 <data...>` output: the full tag/value integer stream, Body edicts (with
rune-id delta decoding), the etching (rune name+id, divisibility, symbol, spacers, premine, terms),
mint, and pointer — plus best-effort cenotaph flagging. Dependency-free (pure Python), so it is a
faithful reference for the Rust port (Phase A2) and is cross-checkable against `ord` in WSL.

Wire format (Runes spec): a runestone output is `OP_RETURN(0x6a) OP_PUSHNUM_13(0x5d)` followed only by
data pushes whose payloads concatenate. The payload is a stream of LEB128 u128s read as (tag, value)
pairs, except tag 0 (Body) after which the remaining integers are edicts in groups of four
(block_delta, tx_delta, amount, output), rune ids delta-encoded.

Usage:
  python3 btx_runes_decode.py decode <scriptPubKey_hex>   # decode one runestone output script
  python3 btx_runes_decode.py selftest                    # offline round-trip + synthetic vectors
"""
import sys, json

# ----------------------------- Runes tags / flags -----------------------------
TAG_BODY = 0
TAG_FLAGS = 2
TAG_RUNE = 4
TAG_PREMINE = 6
TAG_CAP = 8
TAG_AMOUNT = 10
TAG_HEIGHTSTART = 12
TAG_HEIGHTEND = 14
TAG_OFFSETSTART = 16
TAG_OFFSETEND = 18
TAG_MINT = 20
TAG_POINTER = 22
TAG_DIVISIBILITY = 1
TAG_SPACERS = 3
TAG_SYMBOL = 5
TAG_NOP = 127
# tags this decoder recognizes (any *other even* tag => cenotaph per spec)
_KNOWN_TAGS = {TAG_FLAGS, TAG_RUNE, TAG_PREMINE, TAG_CAP, TAG_AMOUNT, TAG_HEIGHTSTART, TAG_HEIGHTEND,
               TAG_OFFSETSTART, TAG_OFFSETEND, TAG_MINT, TAG_POINTER, TAG_DIVISIBILITY, TAG_SPACERS,
               TAG_SYMBOL, TAG_NOP}

FLAG_ETCHING = 1 << 0
FLAG_TERMS = 1 << 1
FLAG_TURBO = 1 << 2
_KNOWN_FLAGS = FLAG_ETCHING | FLAG_TERMS | FLAG_TURBO
U128_MAX = (1 << 128) - 1


# ----------------------------- LEB128 -----------------------------
def leb128_encode(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def leb128_decode_all(buf: bytes):
    """Decode all LEB128 u128s in buf. Returns (values, ok): ok=False if a varint is truncated or
    overflows u128 (=> the runestone is a cenotaph)."""
    vals, n, shift, in_progress = [], 0, 0, False
    for byte in buf:
        in_progress = True
        n |= (byte & 0x7f) << shift
        if byte & 0x80:
            shift += 7
            if shift > 127:           # would overflow u128
                return vals, False
        else:
            if n > U128_MAX:
                return vals, False
            vals.append(n)
            n, shift, in_progress = 0, 0, False
    return vals, (not in_progress)    # trailing unterminated varint => not ok


# ----------------------------- payload extraction -----------------------------
def extract_payload(spk: bytes):
    """From a scriptPubKey, return (payload_bytes, is_runestone, cenotaph, reason). A runestone is
    OP_RETURN(0x6a) OP_PUSHNUM_13(0x5d) followed ONLY by data pushes (their data concatenated)."""
    if len(spk) < 2 or spk[0] != 0x6a or spk[1] != 0x5d:
        return None, False, False, "not a runestone"
    i, payload = 2, bytearray()
    while i < len(spk):
        op = spk[i]; i += 1
        if op == 0x00:                       # OP_0 -> empty push
            n = 0
        elif 0x01 <= op <= 0x4b:
            n = op
        elif op == 0x4c:                     # OP_PUSHDATA1
            if i >= len(spk):
                return bytes(payload), True, True, "truncated PUSHDATA1"
            n = spk[i]; i += 1
        elif op == 0x4d:                     # OP_PUSHDATA2
            if i + 2 > len(spk):
                return bytes(payload), True, True, "truncated PUSHDATA2"
            n = int.from_bytes(spk[i:i + 2], "little"); i += 2
        elif op == 0x4e:                     # OP_PUSHDATA4
            if i + 4 > len(spk):
                return bytes(payload), True, True, "truncated PUSHDATA4"
            n = int.from_bytes(spk[i:i + 4], "little"); i += 4
        else:
            # any non-push opcode after OP_13 makes the runestone a cenotaph
            return bytes(payload), True, True, f"non-push opcode 0x{op:02x} in runestone"
        if i + n > len(spk):
            return bytes(payload), True, True, "push exceeds script length"
        payload += spk[i:i + n]; i += n
    return bytes(payload), True, False, ""


# ----------------------------- rune name (base-26) -----------------------------
def rune_name(n: int) -> str:
    """Decode a rune number to its modified-base-26 name (A..Z, AA..)."""
    s = ""
    n += 1
    while n > 0:
        n -= 1
        s = chr(ord('A') + n % 26) + s
        n //= 26
    return s


def apply_spacers(name: str, spacers: int) -> str:
    out = []
    for idx, ch in enumerate(name):
        out.append(ch)
        if idx < len(name) - 1 and (spacers >> idx) & 1:
            out.append('•')   # '•'
    return ''.join(out)


# ----------------------------- decode -----------------------------
def decode_payload(payload: bytes):
    """Decode a runestone payload (post-extraction integer stream) into a structured dict."""
    cenotaph, reasons = False, []
    ints, ok = leb128_decode_all(payload)
    if not ok:
        cenotaph = True
        reasons.append("malformed LEB128 varint")

    fields = {}     # tag -> list[int] (in order)
    edicts = []
    i = 0
    while i < len(ints):
        tag = ints[i]
        if tag == TAG_BODY:
            body = ints[i + 1:]
            if len(body) % 4 != 0:
                cenotaph = True
                reasons.append("edict block not a multiple of 4")
            blk, txi = 0, 0
            _U64, _U32 = (1 << 64) - 1, (1 << 32) - 1
            for j in range(0, len(body) - (len(body) % 4), 4):
                h, t, amount, output = body[j:j + 4]
                # Mirror ord `RuneId::next` (rune_id.rs): the block DELTA must fit u64 and the running
                # block must not overflow u64; the tx must fit u32 (always) and, within a block, the
                # running tx must not overflow u32. Any of these makes the runestone a CENOTAPH
                # (Flaw::EdictRuneId) — ord then burns all input runes. Our decoder must flag it, else a
                # crafted overflow edict would slip past verify_addressed_rune_tx and grief the maker.
                if h > _U64 or blk + h > _U64 or t > _U32 or (h == 0 and txi + t > _U32):
                    cenotaph = True
                    reasons.append("edict rune id overflow (u64 block / u32 tx)")
                    break
                if h == 0:
                    txi += t
                else:
                    blk += h
                    txi = t
                edicts.append({"id": f"{blk}:{txi}", "block": blk, "tx": txi,
                               "amount": amount, "output": output})
            break
        if i + 1 >= len(ints):
            cenotaph = True
            reasons.append(f"tag {tag} with no value")
            break
        fields.setdefault(tag, []).append(ints[i + 1])
        i += 2

    def take(tag, count=1):
        vals = fields.get(tag)
        if not vals or len(vals) < count:
            return None
        out = vals[:count]
        del vals[:count]
        if not vals:
            fields.pop(tag, None)
        return out[0] if count == 1 else out

    flags = take(TAG_FLAGS) or 0
    residual_flags = flags          # ord clears the flag bits it consumes, then cenotaphs on any residual
    etching = None
    if flags & FLAG_ETCHING:
        residual_flags &= ~FLAG_ETCHING
        rune_num = take(TAG_RUNE)
        div = take(TAG_DIVISIBILITY)
        spacers = take(TAG_SPACERS) or 0
        symbol = take(TAG_SYMBOL)
        premine = take(TAG_PREMINE)
        name = rune_name(rune_num) if rune_num is not None else None
        etching = {
            "rune_number": rune_num,
            "name": name,
            "display_name": apply_spacers(name, spacers) if name else None,
            "divisibility": div or 0,
            "symbol": chr(symbol) if symbol is not None and symbol <= 0x10FFFF else None,
            "spacers": spacers,
            "premine": premine or 0,
            "terms": None,
        }
        if flags & FLAG_TERMS:
            residual_flags &= ~FLAG_TERMS
            etching["terms"] = {
                "amount": take(TAG_AMOUNT),
                "cap": take(TAG_CAP),
                "height_start": take(TAG_HEIGHTSTART),
                "height_end": take(TAG_HEIGHTEND),
                "offset_start": take(TAG_OFFSETSTART),
                "offset_end": take(TAG_OFFSETEND),
            }
        if flags & FLAG_TURBO:
            residual_flags &= ~FLAG_TURBO   # turbo, like terms, is only consumed within an etching
        # SupplyOverflow (ord runestone.rs decipher: `if etching.supply().is_none()` =>
        # Flaw::SupplyOverflow): the etched supply is premine + cap*amount, and if that overflows u128
        # the etching is a CENOTAPH (ord's Etching::supply uses checked add/mul). Only etchings can hit
        # this (swap runestones are edict-only), so it never affects the swap path — but the decoder
        # classifies arbitrary mainnet runestones for the activity feed, so it must match ord/ME here.
        _terms = etching["terms"] or {}
        _supply = (etching["premine"] or 0) + (_terms.get("cap") or 0) * (_terms.get("amount") or 0)
        if _supply > U128_MAX:
            cenotaph = True
            reasons.append("supply overflow (premine + cap*amount > u128)")
    # UnrecognizedFlag (ord runestone.rs `if flags != 0`): any flag bit NOT consumed above is a CENOTAPH
    # — including FLAG_TERMS / FLAG_TURBO set WITHOUT FLAG_ETCHING, or any unknown bit. This MUST run
    # whether or not etching was present; the old check lived inside the etching branch, so a swap
    # runestone with a stray flag bit slipped past as non-cenotaph and false-accepted in verify.
    if residual_flags != 0:
        cenotaph = True
        reasons.append("unrecognized flag bits")

    mint_vals = take(TAG_MINT, 2)
    mint = f"{mint_vals[0]}:{mint_vals[1]}" if mint_vals else None
    pointer = take(TAG_POINTER)
    take(TAG_NOP)  # Nop (odd tag) is ignored if present

    # any leftover EVEN tag is unrecognized => cenotaph (odd leftovers are ignorable)
    for tag in list(fields.keys()):
        if tag % 2 == 0:
            cenotaph = True
            reasons.append(f"unrecognized even tag {tag}")

    return {
        "edicts": edicts,
        "etching": etching,
        "mint": mint,
        "pointer": pointer,
        "flags": flags,
        "cenotaph": cenotaph,
        "cenotaph_reasons": reasons,
    }


def decode_runestone(spk_hex: str):
    """Top-level: decode a runestone from an output scriptPubKey hex. Returns a dict with
    is_runestone=False if the script isn't a runestone output."""
    spk = bytes.fromhex(spk_hex)
    payload, is_rs, ceno, reason = extract_payload(spk)
    if not is_rs:
        return {"is_runestone": False}
    if ceno:
        return {"is_runestone": True, "cenotaph": True, "cenotaph_reasons": [reason],
                "edicts": [], "etching": None, "mint": None, "pointer": None, "flags": 0}
    out = decode_payload(payload)
    out["is_runestone"] = True
    return out


# ----------------------------- selftest -----------------------------
def _encode_runestone_spk(ints):
    """Build an OP_RETURN OP_PUSHNUM_13 <payload> scriptPubKey from a list of integers (test helper)."""
    payload = b''.join(leb128_encode(n) for n in ints)
    # single push (payloads here are < 76 bytes); use direct push opcode
    return bytes([0x6a, 0x5d, len(payload)]) + payload


def selftest():
    checks = {}

    # 1) round-trip the edict path against the ord-validated encoder in btx_runes.py.
    # NOTE: only SAME-block edict sets are used here. btx_runes.runestone_spk encodes the tx delta
    # as `tx - prev_tx` even across blocks, whereas the canonical Runes spec uses the ABSOLUTE tx when
    # block_delta != 0. BTX only ever emits a single edict, so that encoder path is unused/harmless;
    # the cross-block CANONICAL case is covered by the spec vector in check (1b) below.
    try:
        import btx_runes as enc
        for label, edicts in {
            "single": [(840000, 1, 1000, 1)],
            "multi_same_block": [(840000, 1, 500, 1), (840000, 5, 250, 2)],
            "amount_zero_all": [(840000, 1, 0, 1)],
        }.items():
            spk = bytes(enc.runestone_spk(edicts)).hex()
            d = decode_runestone(spk)
            got = [(e["block"], e["tx"], e["amount"], e["output"]) for e in d["edicts"]]
            checks[f"roundtrip_{label}"] = (got == edicts and not d["cenotaph"])
    except Exception as e:  # noqa
        checks["roundtrip_import"] = False
        checks["roundtrip_error"] = str(e)

    # 1b) canonical cross-block edicts (hand-encoded per spec): ids 840000:1 then 840001:3.
    #     block_delta!=0 => tx is absolute, so the stream is [Body, 840000,1,..., 1,3,...].
    d = decode_runestone(_encode_runestone_spk([TAG_BODY, 840000, 1, 1000, 0, 1, 3, 7, 1]).hex())
    got = [(e["block"], e["tx"], e["amount"], e["output"]) for e in d["edicts"]]
    checks["spec_cross_block"] = (got == [(840000, 1, 1000, 0), (840001, 3, 7, 1)] and not d["cenotaph"])

    # 2) synthetic etching + terms + edict (hand-built per spec), decode and assert fields
    # flags = ETCHING|TERMS; Rune=some number; Divisibility=2; Symbol='$'(0x24); Spacers=0b1 (one spacer)
    rune_num = 28        # -> name "BC" (28+1=29; 29-1=28 ->'C'? checked in assertions below)
    ints = [
        TAG_FLAGS, FLAG_ETCHING | FLAG_TERMS,
        TAG_RUNE, rune_num,
        TAG_DIVISIBILITY, 2,
        TAG_SYMBOL, 0x24,            # '$'
        TAG_SPACERS, 0b1,
        TAG_PREMINE, 100,
        TAG_AMOUNT, 10, TAG_CAP, 5,
        TAG_POINTER, 1,
        TAG_BODY, 840000, 7, 42, 1,  # one edict: id 840000:7, amount 42, output 1
    ]
    d = decode_runestone(_encode_runestone_spk(ints).hex())
    et = d.get("etching") or {}
    checks["synthetic_is_runestone"] = (d["is_runestone"] is True)
    checks["synthetic_not_cenotaph"] = (d["cenotaph"] is False)
    checks["synthetic_name"] = (et.get("name") == rune_name(rune_num))
    checks["synthetic_divisibility"] = (et.get("divisibility") == 2)
    checks["synthetic_symbol"] = (et.get("symbol") == '$')
    checks["synthetic_premine"] = (et.get("premine") == 100)
    checks["synthetic_terms_cap"] = ((et.get("terms") or {}).get("cap") == 5)
    checks["synthetic_pointer"] = (d.get("pointer") == 1)
    checks["synthetic_edict"] = (d["edicts"] == [{"id": "840000:7", "block": 840000, "tx": 7,
                                                  "amount": 42, "output": 1}])

    # 3) cenotaph detection: an unrecognized EVEN tag
    d2 = decode_runestone(_encode_runestone_spk([TAG_FLAGS, FLAG_ETCHING, TAG_RUNE, 0, 124, 9]).hex())
    checks["cenotaph_even_tag"] = (d2["cenotaph"] is True)

    # 4) non-push opcode after OP_13 => cenotaph
    d3 = decode_runestone("6a5d51")   # OP_RETURN OP_13 OP_1(non-push)
    checks["cenotaph_nonpush"] = (d3.get("cenotaph") is True)

    # 4b) supply overflow: etching+terms with premine + cap*amount > u128 => cenotaph
    #     (ord Flaw::SupplyOverflow via Etching::supply checked add/mul). A non-overflowing twin is NOT.
    d_ov = decode_runestone(_encode_runestone_spk(
        [TAG_FLAGS, FLAG_ETCHING | FLAG_TERMS, TAG_RUNE, 0,
         TAG_PREMINE, U128_MAX, TAG_AMOUNT, U128_MAX, TAG_CAP, U128_MAX]).hex())
    checks["cenotaph_supply_overflow"] = (d_ov["cenotaph"] is True)
    d_ok = decode_runestone(_encode_runestone_spk(
        [TAG_FLAGS, FLAG_ETCHING | FLAG_TERMS, TAG_RUNE, 0,
         TAG_PREMINE, 100, TAG_AMOUNT, 10, TAG_CAP, 5]).hex())
    checks["supply_in_range_not_cenotaph"] = (d_ok["cenotaph"] is False)

    # 5) base-26 name sanity (known mapping: 0->'A', 25->'Z', 26->'AA')
    checks["name_0_A"] = (rune_name(0) == "A")
    checks["name_25_Z"] = (rune_name(25) == "Z")
    checks["name_26_AA"] = (rune_name(26) == "AA")

    allpass = all(v is True for v in checks.values())
    print(json.dumps({"checks": checks, "ALL_PASS": allpass}, indent=2))
    return allpass


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "decode":
        print(json.dumps(decode_runestone(sys.argv[2]), indent=2))
    elif len(sys.argv) >= 2 and sys.argv[1] == "selftest":
        sys.exit(0 if selftest() else 1)
    else:
        print(__doc__)
        sys.exit(2)
