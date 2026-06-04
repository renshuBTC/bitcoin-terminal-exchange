'use client';
/**
 * Order book card with depth bars.
 *
 * On row click, publishes the selected order to SelectedOrderProvider
 * so the TradePanel auto-switches to Fill and pre-fills the artifact
 * input. Sample asks/bids render when the indexer hasn't yet observed
 * any BTX2 envelopes — same approach as preview.html.
 */
import type { Btx2OrderView } from '@/lib/api';
import { useSelectedOrder } from './SelectedOrderProvider';

interface OrderBookProps {
  orders: Btx2OrderView[];
  stateRootShort?: string;
}

interface BookRow {
  price: number;
  size: number;
  total: number;
  pct: number;
  source: 'sample' | 'live';
  sourceId?: string;
}

const SAMPLE_ASKS: BookRow[] = [
  { price: 9560, size: 240, total: 2294400, pct: 42, source: 'sample' },
  { price: 9540, size: 160, total: 1526400, pct: 28, source: 'sample' },
  { price: 9520, size: 315, total: 2999800, pct: 55, source: 'sample' },
  { price: 9505, size: 100, total: 950500, pct: 18, source: 'sample' },
  { price: 9490, size: 198, total: 1879020, pct: 34, source: 'sample' },
];

const SAMPLE_BIDS: BookRow[] = [
  { price: 9480, size: 130, total: 1232400, pct: 22, source: 'sample' },
  { price: 9460, size: 275, total: 2601500, pct: 48, source: 'sample' },
  { price: 9440, size: 105, total: 991200, pct: 18, source: 'sample' },
  { price: 9420, size: 170, total: 1601400, pct: 30, source: 'sample' },
  { price: 9400, size: 68, total: 639200, pct: 12, source: 'sample' },
];

export function OrderBook({ orders, stateRootShort = '—' }: OrderBookProps) {
  const empty = orders.length === 0;
  // Real depth-ladder derivation lives in a follow-up commit (needs
  // price/amount fields on OrderView). For now: when we have real
  // orders, render them as sample-shape rows keyed by id; when we
  // don't, fall back to demo asks/bids.
  const asks: BookRow[] = empty
    ? SAMPLE_ASKS
    : orders.slice(0, 5).map((o, i) => ({
        price: 9500 + i * 10,
        size: 100,
        total: 950000 + i * 1000,
        pct: 30,
        source: 'live',
        sourceId: o.id_hex,
      }));
  const bids: BookRow[] = empty
    ? SAMPLE_BIDS
    : orders.slice(5, 10).map((o, i) => ({
        price: 9490 - i * 10,
        size: 100,
        total: 949000 - i * 1000,
        pct: 25,
        source: 'live',
        sourceId: o.id_hex,
      }));

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
        {asks.map((r, i) => (
          <Row key={`a-${r.price}-${i}`} row={r} side="ask" />
        ))}
      </div>
      <div className="flex justify-between items-center text-[11px] text-muted border-t border-b border-border py-1.5 px-0.5 my-1.5 font-mono">
        <span className="text-dim uppercase tracking-wider text-[10px]">Spread</span>
        <span>10 sats · 0.10%</span>
      </div>
      <div className="flex flex-col">
        {bids.map((r, i) => (
          <Row key={`b-${r.price}-${i}`} row={r} side="bid" />
        ))}
      </div>
      <div className="text-[11px] text-muted leading-relaxed mt-2.5">
        BTX orders are one-sided pre-signed offers — sell-side unless buy-rune offers exist. Click a row to fill.
      </div>
    </div>
  );
}

function Row({ row, side }: { row: BookRow; side: 'ask' | 'bid' }) {
  const { select } = useSelectedOrder();
  const barColor = side === 'ask' ? '#f0616d' : '#26a69a';
  const priceClass = side === 'ask' ? 'text-red' : 'text-green';

  const onClick = () => {
    // `side` here is the order-book side: an 'ask' is a maker selling
    // stablecoin, so the taker is buying. A 'bid' is the reverse.
    const takerSide = side === 'ask' ? 'buy' : 'sell';
    if (row.source === 'sample') {
      select({
        label: `sample @ ${row.price}`,
        artifactHex: `(sample row · price=${row.price} size=${row.size})`,
        source: 'orderbook',
        detail: {
          side: takerSide,
          rune: 'USDh',
          amount: row.size,
          priceSats: row.price,
          makerShort: 'sample',
        },
      });
    } else if (row.sourceId) {
      select({
        label: `${row.sourceId.slice(0, 16)}…`,
        artifactHex: row.sourceId,
        source: 'orderbook',
        detail: {
          side: takerSide,
          rune: 'USDh',
          amount: row.size,
          priceSats: row.price,
          makerShort: `${row.sourceId.slice(0, 8)}…`,
        },
      });
    }
  };

  return (
    <div
      onClick={onClick}
      className="relative grid items-center gap-1.5 py-[3px] px-0.5 font-mono text-xs cursor-pointer hover:bg-hover"
      style={{ gridTemplateColumns: '18px 1fr 1fr 1fr' }}
    >
      <span
        className="absolute right-0 top-0 bottom-0 rounded-[1px] opacity-40"
        style={{ background: barColor, width: `${row.pct}%` }}
      />
      {side === 'ask' ? (
        <input
          type="checkbox"
          onClick={(e) => e.stopPropagation()}
          className="m-0 accent-orange scale-[.85] relative z-10"
        />
      ) : (
        <span />
      )}
      <span className={`${priceClass} relative z-10`}>{row.price.toLocaleString()}</span>
      <span className="text-right relative z-10">{row.size.toLocaleString()}</span>
      <span className="text-right relative z-10">{row.total.toLocaleString()}</span>
    </div>
  );
}
