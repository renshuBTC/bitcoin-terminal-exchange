/**
 * The single trade page. Server-side fetches orderbook, stats, state
 * root, and health from the BTX API, then renders the three-column
 * trade layout from btx_trade.html on desktop and a tab-switched
 * single-column layout on mobile (via MainGrid client component).
 */
import { api, type Btx2OrderView, type Btx2Health, type Btx2StateRoot } from '@/lib/api';
import { TopNav } from '@/components/TopNav';
import { StatsHeader } from '@/components/StatsHeader';
import { Chart } from '@/components/Chart';
import { OrderBook } from '@/components/OrderBook';
import { TradePanel } from '@/components/TradePanel';
import { BottomTable } from '@/components/BottomTable';
import { StatusBar } from '@/components/StatusBar';
import { MainGrid } from '@/components/MainGrid';

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
      <MainGrid
        chart={<Chart />}
        book={<OrderBook orders={orders} stateRootShort={rootShort} />}
        trade={<TradePanel />}
      />
      <div className="overflow-x-auto">
        <div className="min-w-[760px]">
          <BottomTable orders={orders} />
        </div>
      </div>
      <StatusBar health={health} stateRoot={stateRoot} />
    </>
  );
}
