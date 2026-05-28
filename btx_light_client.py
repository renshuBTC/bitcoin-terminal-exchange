#!/usr/bin/env python3
"""btx_light_client.py — a standalone BTX light client that FOLLOWS the order book by folding the
cumulative event stream, with NO full node and NO full-book download.

What it consumes
----------------
The brk-btx indexer (directly, or via the btxd localhost proxy) serves two read endpoints this
client uses:
  - GET /api/v1/btx/event-stream  ->  [{height, block_hash, cumulative}, ...]   (ascending)
      `block_hash`  = the per-event-bearing-block digest  sha256(0x02 || sorted event lines)
      `cumulative`  = the rolling commitment THROUGH that block
  - GET /api/v1/btx/event-hash    ->  {cumulative, n_event_blocks, n_events}
      `cumulative`  = the final commitment over the whole announce/fill/cancel stream
  (via btxd the same data is at /api/dex/event-stream and /api/dex/event-hash.)

What it actually VERIFIES (the point of a light client — don't trust the served `cumulative`)
--------------------------------------------------------------------------------------------
1. RE-FOLD: it recomputes the cumulative chain itself from the per-block digests using the exact
   reference fold and asserts every entry's served `cumulative` matches, and that the final value
   equals the standalone /event-hash endpoint. A server that serves an inconsistent cumulative (e.g.
   to hide a fold over events it didn't actually commit) is caught here.
       cum_0   = 0x00 * 32                                              (genesis / empty)
       cum_i   = sha256( 0x03 || cum_{i-1} || height_i (be4) || block_hash_i )
   This matches btx_orderbook.event_stream / cumulative_event_hash byte-for-byte (and the Rust
   event_stream_from_views golden), so any honest indexer over the same chain folds to the same value.
2. MONOTONICITY: event-bearing block heights must be strictly ascending.
3. CHECKPOINT / REORG / OMISSION: it persists the last (height, cumulative) it accepted. On the next
   poll it re-finds that height in the fresh stream and asserts the cumulative THROUGH it is unchanged.
   If the indexer rewrote history (reorg that dropped or reordered an order event, or silently omitted
   one), the cumulative at the checkpoint height changes — or the height vanishes — and this client
   refuses to advance and reports the divergence. This is the "any light client can challenge" property
   the open-book root gives per-order, applied to the event STREAM over time.

It does NOT reconstruct events from chain itself (that is the indexer's job, and any *other* indexer
can be polled as an independent oracle of the same per-block digests). What it removes is blind trust
in the served cumulative and blind trust that history wasn't rewritten between polls.

Stdlib only (hashlib, json, urllib, argparse) — same dependency-free discipline as btxd. Offline
self-test:  python3 btx_light_client.py --selftest      (no network; folds the frozen goldens)
Follow live: python3 btx_light_client.py --url http://127.0.0.1:3333 --proxy   (btxd)
             python3 btx_light_client.py --url http://127.0.0.1:3110           (brk direct)
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.request

# --- fold constants: must equal btx_orderbook._CUM_TAG / _CUM_GENESIS (and the Rust 0x03 fold) ----
_CUM_TAG = b"\x03"
_CUM_GENESIS = b"\x00" * 32


def fold_block(cum_prev_hex, height, block_hash_hex):
    """One fold step: cum = sha256(0x03 || cum_prev(32) || height(be4) || block_hash(32)). Returns hex."""
    cum_prev = bytes.fromhex(cum_prev_hex)
    bh = bytes.fromhex(block_hash_hex)
    if len(cum_prev) != 32 or len(bh) != 32:
        raise ValueError("cumulative and block_hash must each be 32 bytes (64 hex chars)")
    return hashlib.sha256(_CUM_TAG + cum_prev + int(height).to_bytes(4, "big") + bh).hexdigest()


class StreamError(Exception):
    """A verifiable inconsistency in the served stream (fold mismatch, non-monotonic, etc.)."""


def verify_stream(stream, expect_final=None, start_cum=None, start_height=None):
    """Independently re-fold `stream` (a list of {height, block_hash, cumulative}); raise StreamError on
    any inconsistency. Returns the recomputed final cumulative (hex; genesis if the stream is empty).

    If `start_cum`/`start_height` are given (a trusted checkpoint), folding RESUMES from that cumulative
    over only the blocks strictly after `start_height` — the whole point of a resumable checkpoint.
    If `expect_final` is given (e.g. the /event-hash cumulative), the recomputed final must equal it.
    """
    cum = start_cum if start_cum is not None else _CUM_GENESIS.hex()
    prev_h = start_height  # last height already folded into `cum` (None => fold everything)
    for i, blk in enumerate(stream):
        h = int(blk["height"])
        bh = blk["block_hash"]
        served_cum = blk["cumulative"]
        if prev_h is not None and h <= prev_h:
            raise StreamError(f"non-monotonic / replayed height at index {i}: {h} <= {prev_h}")
        cum = fold_block(cum, h, bh)
        if cum != served_cum:
            raise StreamError(
                f"cumulative mismatch at height {h} (index {i}): "
                f"recomputed {cum[:12]}… != served {served_cum[:12]}… "
                f"— the indexer's cumulative does not fold from its own per-block digest")
        prev_h = h
    if expect_final is not None and cum != expect_final:
        raise StreamError(
            f"final cumulative {cum[:12]}… != /event-hash {str(expect_final)[:12]}… "
            f"— the stream does not fold to the published commitment")
    return cum


def cumulative_at(stream, height):
    """The served cumulative THROUGH a given event-bearing height, or None if that height isn't present."""
    for blk in stream:
        if int(blk["height"]) == int(height):
            return blk["cumulative"]
    return None


def check_against_checkpoint(stream, checkpoint):
    """Reorg/omission guard. `checkpoint` = {"height": H, "cumulative": C} from a previous accepted poll.
    Returns (ok, message). ok=False means the indexer rewrote history at or before H (the client must
    NOT advance and should treat the served book as untrustworthy / try another indexer)."""
    if not checkpoint:
        return True, "no prior checkpoint — first sync"
    h0, c0 = int(checkpoint["height"]), checkpoint["cumulative"]
    seen = cumulative_at(stream, h0)
    if seen is None:
        # The checkpoint's event-bearing block is gone from the stream. Either a deep reorg dropped that
        # order event, or the indexer omitted it. Only acceptable if the whole stream now ends BELOW h0
        # (a genuine reorg the client can re-evaluate); otherwise it's an omission of committed history.
        max_h = max((int(b["height"]) for b in stream), default=-1)
        if max_h < h0:
            return True, f"checkpoint height {h0} not yet re-confirmed (stream tip {max_h}) — reorg in flight"
        return False, (f"OMISSION/REORG: checkpoint event block {h0} is absent from a stream that "
                       f"extends to {max_h} — committed history was rewritten")
    if seen != c0:
        return False, (f"HISTORY REWRITE: cumulative through height {h0} changed "
                       f"{c0[:12]}… -> {seen[:12]}… — a reorg reordered/replaced a committed order event")
    return True, f"checkpoint height {h0} re-confirmed (cumulative through it unchanged)"


# ----------------------------- network (live follow) -----------------------------------------------
def _get_json(base, path, timeout=10):
    url = base.rstrip("/") + path
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec: localhost indexer/proxy
        return json.loads(r.read().decode())


def _endpoints(proxy):
    """btxd proxies the btx reads under /api/dex/*; the brk indexer serves them at /api/v1/btx/*."""
    return (("/api/dex/event-stream", "/api/dex/event-hash") if proxy
            else ("/api/v1/btx/event-stream", "/api/v1/btx/event-hash"))


def _load_checkpoint(path):
    if path and os.path.isfile(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None
    return None


def _save_checkpoint(path, height, cumulative, n_blocks):
    if not path:
        return
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"height": height, "cumulative": cumulative, "n_blocks": n_blocks}, f, indent=2)
    os.replace(tmp, path)  # atomic; never leave a half-written checkpoint


def follow(base, proxy, checkpoint_path):
    """One poll: fetch the stream + the /event-hash, re-fold and verify, check the prior checkpoint,
    and (only if everything holds) advance the checkpoint. Returns a process exit code."""
    stream_path, hash_path = _endpoints(proxy)
    try:
        stream = _get_json(base, stream_path)
        eh = _get_json(base, hash_path)
    except Exception as e:  # noqa: BLE001 — surface any transport/parse problem plainly
        print(f"[error] could not reach {base} ({stream_path}): {str(e)[:120]}")
        return 2

    if not isinstance(stream, list):
        print(f"[error] {stream_path} did not return a list: {type(stream).__name__}")
        return 2
    expect_final = (eh or {}).get("cumulative")

    prior = _load_checkpoint(checkpoint_path)
    # 1) re-fold the whole stream from genesis and confirm it matches the published /event-hash
    try:
        final = verify_stream(stream, expect_final=expect_final)
    except StreamError as e:
        print(f"[REJECT] served stream is internally inconsistent: {e}")
        return 1

    # 2) reorg/omission guard against what we accepted last time
    ok, msg = check_against_checkpoint(stream, prior)
    if not ok:
        print(f"[REJECT] {msg}")
        print("         refusing to advance the checkpoint — re-poll a second indexer to adjudicate.")
        return 1

    tip = stream[-1] if stream else None
    if tip:
        _save_checkpoint(checkpoint_path, int(tip["height"]), tip["cumulative"], len(stream))
        print(f"[ok] followed {len(stream)} event block(s); tip height {tip['height']}, "
              f"cumulative {final[:12]}…  ({msg})")
    else:
        print(f"[ok] empty stream (no order events yet); cumulative {final[:12]}…  ({msg})")
    if expect_final is not None:
        print(f"     verified == /event-hash cumulative ({str(expect_final)[:12]}…), "
              f"n_events={eh.get('n_events')}, n_event_blocks={eh.get('n_event_blocks')}")
    if checkpoint_path:
        print(f"     checkpoint saved to {checkpoint_path}")
    return 0


# ----------------------------- offline self-test ---------------------------------------------------
# Frozen goldens copied from btx_eventhash_test.py — the exact values the Python reference and the
# Rust indexer agree on. If this client's independent fold reproduces GOLDEN_CUM from the per-block
# digests, its verification logic matches the consensus implementations byte-for-byte.
_GOLDEN_BLOCKS = [
    (100, "1d86d47bdd69aadc0af2a602c7623cd0a83f54664b4160cd8a5db68986e8f451"),
    (101, "5e99fece8e4e0af5d6afb486acafb18afd8e458560b7863f68201b3c2d775ee6"),
    (103, "47df3d30306fdb34375c5cfe5ce4024129beedcb376ee653eda0eab485d480d5"),
    (105, "280f90991f5ffaceeeb7a0a41985471fd3be505fd284c6fa15b839bdf0fe1322"),
]
_GOLDEN_CUM = "0716e1c48e823dfc8f03cf8d5b8bb30f5a91fbf0622943c1553537203a02141e"


def _golden_stream():
    """Rebuild the served-shape stream from the frozen per-block digests by folding them ourselves."""
    cum = _CUM_GENESIS.hex()
    out = []
    for h, bh in _GOLDEN_BLOCKS:
        cum = fold_block(cum, h, bh)
        out.append({"height": h, "block_hash": bh, "cumulative": cum})
    return out


def selftest():
    ok = True
    stream = _golden_stream()

    # (a) independent fold reproduces the consensus golden cumulative
    final = verify_stream(stream, expect_final=_GOLDEN_CUM)
    if final != _GOLDEN_CUM:
        print(f"  [FAIL] fold {final} != golden {_GOLDEN_CUM}"); ok = False

    # (b) empty stream folds to the genesis sentinel
    if verify_stream([]) != _CUM_GENESIS.hex():
        print("  [FAIL] empty stream did not fold to 00*32"); ok = False

    # (c) resume from a mid-stream checkpoint reaches the same final value
    cp_idx = 1  # checkpoint at height 101
    cp = stream[cp_idx]
    resumed = verify_stream(stream[cp_idx + 1:], expect_final=_GOLDEN_CUM,
                            start_cum=cp["cumulative"], start_height=cp["height"])
    if resumed != _GOLDEN_CUM:
        print(f"  [FAIL] resume-from-checkpoint {resumed} != golden {_GOLDEN_CUM}"); ok = False

    # (d) a tampered served cumulative is caught by the re-fold
    tampered = [dict(b) for b in stream]
    tampered[2]["cumulative"] = "ff" * 32
    try:
        verify_stream(tampered); print("  [FAIL] tampered cumulative was NOT detected"); ok = False
    except StreamError:
        pass

    # (e) a tampered per-block digest breaks the published-final check
    tampered2 = [dict(b) for b in stream]
    tampered2[0]["block_hash"] = "ab" * 32
    try:
        verify_stream(tampered2, expect_final=_GOLDEN_CUM)
        print("  [FAIL] tampered block_hash was NOT detected"); ok = False
    except StreamError:
        pass

    # (f) non-monotonic heights are rejected
    try:
        verify_stream([stream[1], stream[0]]); print("  [FAIL] non-monotonic stream accepted"); ok = False
    except StreamError:
        pass

    # (g) checkpoint guard: history-rewrite at the checkpoint height is flagged
    good_cp = {"height": 103, "cumulative": stream[2]["cumulative"]}
    rewritten = [dict(b) for b in stream]
    rewritten[2]["cumulative"] = "cc" * 32  # cumulative through 103 changed -> reorg/rewrite
    okc, _ = check_against_checkpoint(rewritten, good_cp)
    if okc:
        print("  [FAIL] history rewrite at checkpoint height NOT flagged"); ok = False

    # (h) checkpoint guard: omission of the checkpoint block (while stream extends past it) is flagged
    omitted = [b for b in stream if int(b["height"]) != 103]
    okc2, _ = check_against_checkpoint(omitted, good_cp)
    if okc2:
        print("  [FAIL] omission of checkpoint block NOT flagged"); ok = False

    # (i) checkpoint guard: a benign re-confirm (cumulative unchanged) is accepted
    okc3, _ = check_against_checkpoint(stream, good_cp)
    if not okc3:
        print("  [FAIL] benign checkpoint re-confirm rejected"); ok = False

    print(f"light-client follower: independent fold + checkpoint guard match the golden ({_GOLDEN_CUM[:12]}…)"
          if ok else "LIGHT-CLIENT FOLLOWER TEST FAILED")
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser(description="BTX light client — follow the order book by folding the "
                                             "cumulative event stream (no full node, no full-book download).")
    ap.add_argument("--selftest", action="store_true", help="run the offline golden fold test (no network)")
    ap.add_argument("--url", default="http://127.0.0.1:3333",
                    help="base URL of btxd (default) or the brk indexer")
    ap.add_argument("--proxy", action="store_true",
                    help="hit btxd's /api/dex/* paths (default assumes btxd); omit for brk /api/v1/btx/*")
    ap.add_argument("--checkpoint", default=None,
                    help="path to persist the (height,cumulative) checkpoint between polls")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return
    sys.exit(follow(a.url, a.proxy, a.checkpoint))


if __name__ == "__main__":
    main()
