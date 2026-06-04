'use client';
/**
 * Chart card — TradingView-style sparkline. Static SVG for now; the
 * real implementation will use lightweight-charts or recharts pulling
 * from the BRK price_close series.
 * Matches btx_trade.html's chart card (lines 366–380).
 */
import { useState } from 'react';

interface ChartProps {
  initialTab?: 'btc' | 'rune';
}

export function Chart({ initialTab = 'btc' }: ChartProps) {
  const [tab, setTab] = useState<'btc' | 'rune'>(initialTab);

  return (
    <div className="bg-bg p-3.5 flex flex-col">
      <div className="m-0 mb-2.5 font-mono text-[11px] font-semibold text-muted uppercase tracking-wider flex justify-between items-baseline">
        <span className="inline-flex gap-px bg-panel p-0.5 border border-line-strong rounded-sm h-6 box-border">
          <ChartTab on={tab === 'btc'} onClick={() => setTab('btc')}>
            BTC MARK
          </ChartTab>
          <ChartTab on={tab === 'rune'} onClick={() => setTab('rune')}>
            RUNE FILLS
          </ChartTab>
        </span>
        <span className="text-[10px] text-dim font-normal normal-case tracking-normal">
          BRK · price_close · 90d
        </span>
      </div>
      <div className="flex-1 min-h-[280px] relative">
        <svg viewBox="0 0 600 300" preserveAspectRatio="none" className="w-full h-full block">
          <defs>
            <linearGradient id="ag" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="#ff8c00" stopOpacity=".3" />
              <stop offset="100%" stopColor="#ff8c00" stopOpacity="0" />
            </linearGradient>
          </defs>
          <g stroke="#1f1f1f" strokeWidth="1">
            <line x1="0" y1="60" x2="600" y2="60" />
            <line x1="0" y1="120" x2="600" y2="120" />
            <line x1="0" y1="180" x2="600" y2="180" />
            <line x1="0" y1="240" x2="600" y2="240" />
          </g>
          <path
            d="M 0,220 L 30,210 L 60,225 L 90,200 L 120,195 L 150,175 L 180,180 L 210,160 L 240,155 L 270,140 L 300,130 L 330,150 L 360,135 L 390,118 L 420,122 L 450,100 L 480,95 L 510,110 L 540,90 L 570,80 L 600,75 L 600,300 L 0,300 Z"
            fill="url(#ag)"
          />
          <path
            d="M 0,220 L 30,210 L 60,225 L 90,200 L 120,195 L 150,175 L 180,180 L 210,160 L 240,155 L 270,140 L 300,130 L 330,150 L 360,135 L 390,118 L 420,122 L 450,100 L 480,95 L 510,110 L 540,90 L 570,80 L 600,75"
            stroke="#ff8c00"
            strokeWidth="1.5"
            fill="none"
          />
          <g fill="#666" fontFamily="Source Code Pro" fontSize="10">
            <text x="595" y="55" textAnchor="end">$110k</text>
            <text x="595" y="115" textAnchor="end">$105k</text>
            <text x="595" y="175" textAnchor="end">$100k</text>
            <text x="595" y="235" textAnchor="end">$95k</text>
          </g>
        </svg>
      </div>
      <div className="text-[11px] text-dim mt-1.5">
        rune↔BTC price reconstructed from confirmed swaps. Sparse by
        nature — Bitcoin blocks, not ticks.
      </div>
    </div>
  );
}

function ChartTab({
  on,
  onClick,
  children,
}: {
  on: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <span
      onClick={onClick}
      className={
        on
          ? 'h-[18px] inline-flex items-center justify-center px-2.5 text-[10px] tracking-wider leading-none bg-orange text-black border border-orange rounded-sm cursor-pointer font-mono uppercase font-bold'
          : 'h-[18px] inline-flex items-center justify-center px-2.5 text-[10px] tracking-wider leading-none bg-panel text-fg border border-transparent rounded-sm cursor-pointer font-mono uppercase hover:bg-hover hover:text-fg-bright'
      }
    >
      {children}
    </span>
  );
}
