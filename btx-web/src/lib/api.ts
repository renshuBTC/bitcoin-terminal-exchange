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
      { headers: { Accept: 'application/json' }, next: { revalidate: 60 } 