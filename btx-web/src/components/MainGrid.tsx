'use client';
/**
 * Three-column main grid with mobile fallback.
 *
 * Desktop (>= 900px): a CSS grid renders Chart / OrderBook / TradePanel
 * side-by-side, mirroring btx_trade.html's three-column layout.
 *
 * Mobile (< 900px): the three panes stack into a single column and the
 * user switches between them via a sticky tab strip — Chart / Book /
 * Trade. Active pane only renders to keep the bundle light.
 */
import { useEffect, useState } from 'react';

type Pane = 'chart' | 'book' | 'trade';

interface MainGridProps {
  chart: React.ReactNode;
  book: React.ReactNode;
  trade: React.ReactNode;
}

export function MainGrid({ chart, book, trade }: MainGridProps) {
  const [active, setActive] = useState<Pane>('chart');
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 900px)');
    const onChange = () => setIsMobile(mq.matches);
    onChange();
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  if (!isMobile) {
    return (
      <main
        className="grid gap-px bg-border min-h-[calc(100vh-130px-240px)]"
        style={{
          gridTemplateColumns:
            'minmax(420px, 1.7fr) minmax(280px, 0.85fr) minmax(320px, 0.85fr)',
        }}
      >
        {chart}
        {book}
        {trade}
      </main>
    );
  }

  // Mobile: tab strip + single visible pane
  return (
    <>
      <div className="flex gap-0 px-3 items-center border-b border-border bg-bg sticky top-[46px] z-[4]">
        <MTab on={active === 'chart'} onClick={() => setActive('chart')}>
          Chart
        </MTab>
        <MTab on={active === 'book'} onClick={() => setActive('book')}>
          Book
        </MTab>
        <MTab on={active === 'trade'} onClick={() => setActive('trade')}>
          Trade
        </MTab>
      </div>
      <main className="block bg-bg min-h-[60vh]">
        {active === 'chart' && chart}
        {active === 'book' && book}
        {active === 'trade' && trade}
      </main>
    </>
  );
}

function MTab({
  on,
  onClick,
  children,
}: {
  on: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      className={
        on
          ? 'text-orange cursor-pointer py-2.5 mr-6 font-mono font-medium text-xs uppercase tracking-wider border-b-2 border-orange -mb-px bg-transparent border-x-0 border-t-0'
          : 'text-muted cursor-pointer py-2.5 mr-6 font-mono font-medium text-xs uppercase tracking-wider border-b-2 border-transparent -mb-px hover:text-fg-bright bg-transparent border-x-0 border-t-0'
      }
    >
      {children}
    </button>
  );
}
