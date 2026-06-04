/**
 * Persistent footer per build-plan §6 — the trust UI is non-negotiable.
 * Shows the connected indexer endpoint, the current block height, the
 * BTX2 state root, and a link to the transparency page.
 *
 * Reads `/api/v1/btx2/healthz` + `/api/v1/btx2/state_root` directly (no
 * caching, because freshness here is the point). Falls back silently
 * to "—" placeholders if the API is unreachable; the UI never lies
 * about state it doesn't have.
 */
import { api } from '@/lib/api';

async function fetchFooterState() {
  try {
    const [health, root] = await Promise.all([api.health(), api.stateRoot()]);
    return { health, root };
  } catch {
    return null;
  }
}

export async function TrustFooter() {
  const apiBase =
    process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3110';
  const data = await fetchFooterState();
  const ok = data?.health.ok ?? false;
  const tipHeight = data?.health.tip_height ?? 0;
  const rootHex = data?.root.root_hex ?? '—';
  const apiHost = (() => {
    try {
      return new URL(apiBase).host;
    } catch {
      return apiBase;
    }
  })();

  return (
    <footer className="border-t border-border-strong bg-panel-2 text-xs text-fg-2">
      <div className="mx-auto max-w-7xl px-4 py-2 flex flex-wrap gap-x-4 gap-y-1 items-center">
        <span
          className={`inline-flex items-center gap-1 ${ok ? 'text-green-up' : 'text-red-down'}`}
          title={ok ? 'API reachable' : 'API unreachable — data may be stale'}
        >
          <span className="w-2 h-2 rounded-full bg-current" /> api: {apiHost}
        </span>
        <span>block: {tipHeight.toLocaleString()}</span>
        <span className="font-mono" title={rootHex}>
          state root: {rootHex.slice(0, 12)}…
        </span>
        <span className="ml-auto flex gap-3">
          <a href="/transparency">verify ↗</a>
          <a
            href="https://github.com/renshuBTC/brk-btx"
            target="_blank"
            rel="noreferrer"
          >
            run your own ↗
          </a>
        </span>
      </div>
    </footer>
  );
}
