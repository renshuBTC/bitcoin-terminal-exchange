/**
 * Order book card with depth bars.
 * Matches btx_trade.html's orderbook card.
 *
 * Sample asks/bids render when the indexer hasn't yet observed any
 * BTX2 envelopes — same approach as preview.html.
 */
import type { Btx2OrderView } from '@/lib/api';

interface OrderBookProps {
  orders: Btx2OrderView[];
  stateRootShort?: string;
}

interface BookRow {
  price: number;
  size: number;
  total: number;
  pct: number;
}

const SAMPLE_ASKS: BookRow[] = [
  { price: 9560, size: 240, total: 2294400, pct: 42 },
  { price: 9540, size: 160, total: 1526400, pct: 28 },
  { price: 9520, size: 315, total: 2999800, pct: 55 },
  { price: 9505, size: 100, total: 950500, pct: 18 },
  { price: 9490, size: 198, total: 1879020, pct: 34 },
];

const SAMPLE_BIDS: BookRow[] = [
  { price: 9480, size: 130, total: 1232400, pct: 22 },
  { price: 9460, size: 275, total: 2601500, pct: 48 },
  { price: 9440, size: 105, total: 991200, pct: 18 },
  { price: 9420, size: 170, total: 1601400, pct: 30 },
  { price: 9400, size: 68, total: 639200, pct: 12 },
];

export function OrderBook({ orders, stateRootShort = '—' }: OrderBookProps) {
  const empty = orders.length === 0;
  const asks = empty ? SAMPLE_ASKS : [];
  const bids = empty ? SAMPLE_BIDS : [];

  return (
    <div className="bg-bg p-3.5 flex flex-col">
      <div className="m-0 mb-2.5 font-mono text-[11px] font-semibold text-muted uppercase tracking-wider flex justify-between items-baseline">
        Order Book
        <span className="text-[10px] text-dim font-normal normal-case tracking-normal">
          book {stateRootShort}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 text-[10px] text-muted uppercase tracking-wider px-0.5 pb-1.5 border-b border-border-soft">
        <span>Price (sats)</span>
        <span className="text-right">Size</span>
        <span className="text-right">Total</span>
      </div>
      <div className="flex flex-col">
        {asks.map((r) => (
          <Row key={`a-${r.price}`} row={r} side="ask" />
        ))}
      </div>
      <div className="flex justify-between items-center text-[11px] text-muted border-t border-b border-border py-1.5 px-0.5 my-1.5 font-mono">
        <span className="text-dim uppercase tracking-wider text-[10px]">Spread</span>
        <span>10 sats · 0.10%</span>
      </div>
      <div className="flex flex-col">
        {bids.map((r) => (
          <Row key={`b-${r.price}`} row={r} side="bid" />
        ))}
      </div>
      <div className="text-[11px] text-muted leading-relaxed mt-2.5">
        BTX orders are one-sided pre-signed offers — sell-side unless buy-rune offers exist. Click a row to fill, or tick several asks for a batch tx.
      </div>
    </div>
  );
}

function Row({ row, side }: { row: BookRow; side: 'ask' | 'bid' }) {
  const barColor = side === 'ask' ? '#f0616d' : '#26a69a';
  const priceClass = side === 'ask' ? 'text-red' : 'text-green';
  return (
    <div
      className="relative grid items-center gap-1.5 py-[3px] px-0.5 font-mono text-xs cursor-pointer hover:bg-hover"
      style={{ gridTemplateColumns: '18px 1fr 1fr 1fr' }}
    >
      <span
        className="absolute right-0 top-0 bottom-0 rounded-[1px] opacity-40"
        style={{ background: barColor, width: `${row.pct}%` }}
      />
      {side === 'ask' ? (
        <input type="checkbox" className="m-0 accent-orange scale-[.85] relative z-10" />
      ) : (
        <span />
      )}
      <span className={`${priceClass} relative z-10`}>{row.price.toLocaleString()}</span>
      <span className="text-right relative z-10">{row.size.toLocaleString()}</span>
      <span className="text-right relative z-10">{row.total.toLocaleString()}</span>
    </div>
  );
}
