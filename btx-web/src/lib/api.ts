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

export const api = {
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
