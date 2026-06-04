/**
 * The single trade page. Server-side fetches orderbook, stats, state
 * root, and health from the BTX API, then renders the three-column
 * trade layout shown in btx_trade.html.
 *
 * Per BTX-single-page-decision-2026-06-04.md, the trade page is the
 * only page for both the website and the installer.
 */
import { api, type Btx2OrderView, type Btx2Health, type Btx2StateRoot } from '@/lib/api';
import { TopNav } from '@/components/TopNav';
import { StatsHeader } from '@/components/StatsHeader';
import { Chart } from '@/components/Chart';
import { OrderBook } from '@/components/OrderBook';
import { TradePanel } from '@/components/TradePanel';
import { BottomTable } from '@/components/BottomTable';
import { StatusBar } from '@/components/StatusBar';

async function fetchPageData(): Promise<{
  orders: Btx2OrderView[];
  health: Btx2Health | null;
  stateRoot: Btx2StateRoot | null;
}> {
  const safe = async <T,>(p: Promise<T>): Promise<T | null> => {
    try { return await p; } catch { return null; }
  };
  const [orders, health, stateRoot] = await Promise.all([
    safe(api.orders()),
    safe(api.health()),
    safe(api.stateRoot()),
  ]);
  return { orders: orders ?? [], health, stateRoot };
}

export default async function HomePage() {
  const { orders, health, stateRoot } = await fetchPageData();
  const rootShort = stateRoot ? `${stateRoot.root_hex.slice(0, 6)}…` : '—';

  return (
    <>
      <TopNav />
      <StatsHeader health={health} streamHash={stateRoot?.root_hex} />
      <main
        className="grid gap-px bg-border min-h-[calc(100vh-130px-240px)]"
        style={{ gridTemplateColumns: 'minmax(420px, 1.7fr) minmax(280px, 0.85fr) minmax(320px, 0.85fr)' }}
      >
        <Chart />
        <OrderBook orders={orders} stateRootShort={rootShort} />
        <TradePanel />
      </main>
      <BottomTable orders={orders} />
      <StatusBar health={health} stateRoot={stateRoot} />
    </>
  );
}
