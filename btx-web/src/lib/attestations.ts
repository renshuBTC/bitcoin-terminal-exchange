/**
 * Local-only attestation log.
 *
 * Persists the user's successful BIP-322 publish + fill signatures to
 * localStorage so they survive page refresh. This is purely a UX log:
 * the BTX protocol does NOT depend on the client remembering anything
 * (the on-chain envelope is authoritative). When the broadcast flow
 * lands, each row will gain a "re-broadcast" affordance.
 *
 * Schema is versioned (v1). On migration, bump V and add a converter.
 */

/** localStorage key. */
const STORAGE_KEY = 'btx-web/attestations/v1';

/** Hard cap — older rows drop off when we cross this. */
const MAX_ROWS = 50;

export type AttestationKind = 'publish' | 'fill';

export interface Attestation {
  /** Stable client-side id (random). Lets React lists key off it. */
  id: string;
  /** ISO timestamp of when the signature was produced. */
  ts: string;
  kind: AttestationKind;
  /** Wallet name that signed (e.g. 'UniSat', 'Xverse'). */
  provider: string;
  /** Bitcoin address that signed. */
  address: string;
  /** Bitcoin network the signing wallet reported. */
  network: string;
  /** BIP-322 signature (base64). */
  signature: string;
  /**
   * For 'publish': a short summary of what the maker committed to
   * (side, rune, amount, price).
   * For 'fill': the order id/artifact the taker accepted.
   */
  summary: string;
}

function safeRead(): Attestation[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    // Light shape filter — discards any malformed legacy rows silently.
    return parsed.filter(
      (r): r is Attestation =>
        typeof r === 'object' &&
        r !== null &&
        typeof (r as Attestation).id === 'string' &&
        typeof (r as Attestation).ts === 'string' &&
        typeof (r as Attestation).signature === 'string',
    );
  } catch {
    return [];
  }
}

function safeWrite(rows: Attestation[]): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(rows));
  } catch {
    // localStorage quota / disabled — silently no-op.
  }
}

/**
 * Append a row. Most-recent-first. Trims to MAX_ROWS.
 * Returns the new full list so callers don't need a second read.
 */
export function appendAttestation(
  row: Omit<Attestation, 'id' | 'ts'> & { ts?: string },
): Attestation[] {
  const id =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  const ts = row.ts ?? new Date().toISOString();
  const full: Attestation = {
    id,
    ts,
    kind: row.kind,
    provider: row.provider,
    address: row.address,
    network: row.network,
    signature: row.signature,
    summary: row.summary,
  };
  const next = [full, ...safeRead()].slice(0, MAX_ROWS);
  safeWrite(next);
  return next;
}

export function readAttestations(): Attestation[] {
  return safeRead();
}

export function clearAttestations(): void {
  safeWrite([]);
}

/**
 * Subscribe to changes. Uses a custom event so multiple components on
 * the page (e.g. BottomTable tab + a possible header counter) refresh
 * in unison after a save. Returns the unsubscribe.
 */
const EVENT_NAME = 'btx-web/attestations/changed';

export function emitAttestationsChanged(): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(EVENT_NAME));
}

export function onAttestationsChanged(handler: () => void): () => void {
  if (typeof window === 'undefined') return () => {};
  window.addEventListener(EVENT_NAME, handler);
  return () => window.removeEventListener(EVENT_NAME, handler);
}
