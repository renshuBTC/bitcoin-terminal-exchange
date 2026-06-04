/**
 * Typed client for the brk_server BTX2 API.
 *
 * Routes shipped in brk-btx commit 8b08c83 (+ broadcast in 7eb3510):
 *   GET  /api/v1/btx2/orders        — orderbook
 *   GET  /api/v1/btx2/orders/{id}   — single-order lookup
 *   GET  /api/v1/btx2/conditional
 *   GET  /api/v1/btx2/filled
 *   GET  /api/v1/btx2/cancelled
 *   GET  /api/v1/btx2/expired
 *   GET  /api/v1/btx2/all
 *   GET  /api/v1/btx2/stats         — state-bucket counts
 *   GET  /api/v1/btx2/state_root    — cross-indexer agreement primitive
 *   GET  /api/v1/btx2/healthz       — liveness
 *   POST /api/v1/btx2/broadcast     — forward a signed tx to Bitcoin
 *
 * Also wraps the standard BRK series + address endpoints (brk-btx is
 * a brk fork — all BRK routes are present):
 *   GET  /api/series/price_close/day1/data
 *   GET  /api/series/price_close/day1/latest
 *   GET  /api/address/{addr}
 *
 * The response shapes here mirror `Btx2OrderView` / `Btx2StateCounts` /
 * `Btx2StateRoot` / `Btx2Health` in `crates/brk_query/src/impl/btx2.rs`.
 * When the brk-btx OpenAPI spec stabilizes, regenerate from
 * `openapi-typescript` instead of hand-maintaining these types.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3110';

export interface Btx2OrderView {
  id_hex: string;
  state: 'Open' | 'Conditional' | 'Filled' | 'Cancelled' | 'Expired';
  maker_pubkey_hex: string;
  offer_outpoint: string;
  expiry: number;
  announce_block_height: number;
  /**
   * Trading-economics fields. Added to the server-side schema in the
   * 'enrich OrderMetadata' brk-btx commit. Optional on the type so
   * the frontend keeps rendering against older indexers that haven't
   * shipped that commit yet — those servers will simply omit these
   * keys and the UI shows '—' instead of fake numbers.
   */
  rune_block?: number;
  rune_tx?: number;
  amount?: number;
  price?: number;
}

/**
 * True when the server-side OrderView is enriched with the trading
 * economics fields (so we can render real price/size instead of
 * synthetic placeholders). Used by OrderBook to hide the orange
 * "synthetic" chip the moment the backend ships the enrichment.
 */
export function orderViewIsEnriched(o: Btx2OrderView): boolean {
  return (
    typeof o.amount === 'number' &&
    typeof o.price === 'number' &&
    typeof o.rune_block === 'number'
  );
}

export interface Btx2StateCounts {
  open: number;
  conditional: number;
  filled: number;
  cancelled: number;
  expired: number;
  total: number;
}

export interface Btx2StateRoot {
  root_hex: string;
  height: number;
  block_hash: string;
}

export interface Btx2Health {
  ok: boolean;
  tip_height: number;
  tip_blockhash: string;
  n_open_orders: number;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: 'application/json' },
    next: { revalidate: 10 },
  });
  if (!res.ok) {
    throw new Error(`GET ${path} failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

/**
 * BRK daily-close price series point.
 *
 * Endpoint: `GET /api/series/price_close/day1/data?limit=N`
 * Response shape (from `crates/brk_server/src/api/series.rs:268-298`):
 *   a flat JSON array of values, oldest → newest. For the `price_close`
 *   series (declared in `crates/brk_computer/src/prices/mod.rs:93`)
 *   each item is a USD close-price as a JSON number.
 *
 * Index name `day1` is the canonical identifier; aliases such as
 * `day`/`date`/`dateindex` are also accepted (see
 * `crates/brk_types/src/day1.rs:205`).
 *
 * We attach a synthetic offset `i` so consumers don't need to track
 * the index of each point separately.
 */
export interface Btx2PricePoint {
  /** Days from the start of the returned window (0 = oldest). */
  i: number;
  /** Close price in USD. */
  close: number;
}

/**
 * Address-stats subset we use from BRK's `/api/address/{addr}`.
 *
 * Response shape declared in `crates/brk_types/src/addr_stats.rs`
 * (mempool.space-compatible):
 *
 *   { address, addr_type,
 *     chain_stats:   { funded_txo_sum, spent_txo_sum, tx_count, ... },
 *     mempool_stats: { funded_txo_sum, spent_txo_sum, tx_count, ... } }
 *
 * `Sats` serializes as a JSON number (u64) per brk_types. The
 * confirmed on-chain balance is
 * `chain_stats.funded_txo_sum - chain_stats.spent_txo_sum`, in sats.
 */
export interface Btx2AddressStats {
  address: string;
  addr_type?: string;
  chain_stats: {
    funded_txo_sum: number;
    spent_txo_sum: number;
    funded_txo_count?: number;
    spent_txo_count?: number;
    tx_count?: number;
  };
  mempool_stats?: {
    funded_txo_sum: number;
    spent_txo_sum: number;
  };
}

export const api = {
  /**
   * Most recent BRK price_close value (single number, USD).
   *
   * Endpoint: `GET /api/series/price_close/day1/latest`
   * Response: a bare JSON number (no envelope), per the latest
   *   handler at `crates/brk_server/src/api/series.rs:299-322`.
   *
   * Throws on non-2xx, non-numeric body, or NaN/Infinity so the
   * caller can fall back silently. Used by StatsHeader for the
   * "Mark" pill and by anything else that needs a single spot price.
   */
  priceCloseLatest: async (): Promise<number> => {
    const res = await fetch(
      `${API_BASE}/api/series/price_close/day1/latest`,
      { headers: { Accept: 'application/json' }, next: { revalidate: 30 } },
    );
    if (!res.ok) {
      throw new Error(
        `price_close_latest failed: ${res.status} ${res.statusText}`,
      );
    }
    const raw = (await res.json()) as unknown;
    if (typeof raw !== 'number' || !Number.isFinite(raw)) {
      throw new Error('price_close_latest: non-numeric body');
    }
    return raw;
  },

  /**
   * BRK daily-close USD series. Returns up to `limit` most-recent points.
   * Throws on non-2xx, empty body, or non-numeric items so callers can
   * fall back to a placeholder cleanly.
   */
  pricesClose: async (limit = 90): Promise<Btx2PricePoint[]> => {
    const res = await fetch(
      `${API_BASE}/api/series/price_close/day1/data?limit=${limit}`,
      { headers: { Accept: 'application/json' }, next: { revalidate: 60 } },
    );
    if (!res.ok) {
      throw new Error(`prices_close failed: ${res.status} ${res.statusText}`);
    }
    const raw = (await res.json()) as unknown;
    if (!Array.isArray(raw) || raw.length === 0) {
      throw new Error('prices_close: empty or non-array response');
    }
    const points: Btx2PricePoint[] = [];
    for (let i = 0; i < raw.length; i++) {
      const v = raw[i];
      if (typeof v !== 'number' || !Number.isFinite(v)) {
        throw new Error(`prices_close: non-numeric item at index ${i}`);
      }
      points.push({ i, close: v });
    }
    return points;
  },

  /**
   * Confirmed on-chain balance for any Bitcoin address, in sats.
   *
   * Endpoint: `GET /api/address/{addr}`
   * Computed as `chain_stats.funded_txo_sum - chain_stats.spent_txo_sum`
   * — same definition the mempool.space API uses. Returns null on any
   * failure (network, 404, bad shape) so callers can treat "no balance
   * yet" as a soft state instead of throwing.
   *
   * Caller is responsible for validating that `addr` is a sensible
   * Bitcoin address; we don't URL-encode here because addresses are
   * URL-safe ASCII by construction.
   */
  addressBalanceSats: async (addr: string): Promise<number | null> => {
    try {
      const res = await fetch(`${API_BASE}/api/address/${addr}`, {
        headers: { Accept: 'application/json' },
        next: { revalidate: 15 },
      });
      if (!res.ok) return null;
      const stats = (await res.json()) as Btx2AddressStats;
      const funded = Number(stats?.chain_stats?.funded_txo_sum);
      const spent = Number(stats?.chain_stats?.spent_txo_sum);
      if (!Number.isFinite(funded) || !Number.isFinite(spent)) return null;
      return Math.max(0, funded - spent);
    } catch {
      return null;
    }
  },

  orders: () => get<Btx2OrderView[]>('/api/v1/btx2/orders'),
  order: (id: string) => get<Btx2OrderView | null>(`/api/v1/btx2/orders/${id}`),
  conditional: () => get<Btx2OrderView[]>('/api/v1/btx2/conditional'),
  filled: () => get<Btx2OrderView[]>('/api/v1/btx2/filled'),
  cancelled: () => get<Btx2OrderView[]>('/api/v1/btx2/cancelled'),
  expired: () => get<Btx2OrderView[]>('/api/v1/btx2/expired'),
  all: () => get<Btx2OrderView[]>('/api/v1/btx2/all'),
  stats: () => get<Btx2StateCounts>('/api/v1/btx2/stats'),
  stateRoot: () => get<Btx2StateRoot>('/api/v1/btx2/state_root'),
  health: () => get<Btx2Health>('/api/v1/btx2/healthz'),

  /**
   * Broadcast a hex-encoded signed transaction. The server forwards it
   * verbatim to bitcoind; the signing happened in the user's wallet.
   * Returns the txid on success.
   */
  broadcast: async (rawTxHex: string): Promise<string> => {
    const res = await fetch(`${API_BASE}/api/v1/btx2/broadcast`, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      body: rawTxHex,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`broadcast failed: ${res.status} ${text}`);
    }
    return res.json() as Promise<string>;
  },
};
