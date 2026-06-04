/**
 * Trading page — the orderbook.
 *
 * MVP scope: read-only view of the live orderbook from
 * /api/v1/btx2/orders + /api/v1/btx2/stats. Wallet connection and order
 * entry are stubbed; they land per build-plan §8 weeks 7–10.
 */
import { api, type Btx2OrderView } from '@/lib/api';
import { OrderBook } from '@/components/OrderBook';

async function fetchPageData() {
  try {
    const [orders, stats] = await Promise.all([api.orders(), api.stats()]);
    return { orders, stats, error: null as string | null };
  } catch (e) {
    return {
      orders: [] as Btx2OrderView[],
      stats: {
        open: 0,
        conditional: 0,
        filled: 0,
        cancelled: 0,
        expired: 0,
        total: 0,
      },
      error:
        e instanceof Error
          ? e.message
          : 'API unreachable — start the brk_server and set NEXT_PUBLIC_API_URL',
    };
  }
}

export default async function HomePage() {
  const { orders, stats, error } = await fetchPageData();

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 space-y-6">
      <section className="rounded-lg bg-panel-2 border border-border-strong p-4">
        <h1 className="text-2xl font-semibold mb-1">BTX orderbook</h1>
        <p className="text-fg-2 text-sm">
          Open orders reconstructed from Bitcoin. No relay, no server-side
          book — the data here lives on-chain.
        </p>
        <div className="mt-3 grid grid-cols-2 sm:grid-cols-5 gap-2 text-sm font-mono">
          <Stat label="open" value={stats.open} />
          <Stat label="conditional" value={stats.conditional} />
          <Stat label="filled" value={stats.filled} />
          <Stat label="cancelled" value={stats.cancelled} />
          <Stat label="expired" value={stats.expired} />
        </div>
      </section>

      {error ? (
        <div className="rounded-lg bg-panel-2 border border-red-down/40 p-4 text-sm text-red-down">
          <div className="font-semibold mb-1">API unreachable</div>
          <div className="text-fg-2">{error}</div>
          <div className="mt-2 text-fg-2">
            To run the API locally: see{' '}
            <code className="font-mono text-fg-1">brk-btx</code> README +{' '}
            <code className="font-mono text-fg-1">cargo run -p brk_cli</code>.
          </div>
        </div>
      ) : (
        <OrderBook orders={orders} />
      )}

      <section className="rounded-lg bg-panel-2 border border-border-strong p-4 text-sm text-fg-2 space-y-2">
        <h2 className="text-fg-1 font-semibold">Honest about the MVP</h2>
        <p>
          This is a scaffold. The orderbook fetch and stats are real; the
          buy / sell flows aren&apos;t wired yet. Per the build plan in{' '}
          <code className="font-mono text-fg-1">
            BTX-frontend-architecture-2026-06-04.md
          </code>
          : wallet integration is week 7–8, BUY flow week 9–10, SELL flow
          week 11.
        </p>
        <p>
          The data shown above is whatever the connected{' '}
          <code className="font-mono text-fg-1">brk_server</code> reports.
          Today the underlying <code className="font-mono text-fg-1">Btx2Store</code>{' '}
          is an in-memory stub returning empty data, so this page shows
          zero rows until the persistence wiring lands (week 1–2 task).
        </p>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-panel rounded p-2 border border-border-strong">
      <div className="text-fg-2 text-xs uppercase tracking-wide">{label}</div>
      <div className="text-fg-1 text-lg">{value.toLocaleString()}</div>
    </div>
  );
}
