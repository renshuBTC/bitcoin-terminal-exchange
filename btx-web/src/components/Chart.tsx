'use client';
/**
 * Chart card — TradingView-style sparkline backed by the BRK
 * `price_close` daily series. Falls back to the previous hardcoded
 * SVG when the brk-btx server is unreachable so the page still
 * renders cleanly offline.
 *
 * Matches the visual of btx_trade.html's chart card (lines 366–380).
 */
import { useEffect, useState } from 'react';

import { api, type Btx2PricePoint } from '@/lib/api';

interface ChartProps {
  initialTab?: 'btc' | 'rune';
  /** How many trailing days of BTC close to pull. */
  days?: number;
}

type Status = 'loading' | 'live' | 'fallback';

export function Chart({ initialTab = 'btc', days = 90 }: ChartProps) {
  const [tab, setTab] = useState<'btc' | 'rune'>(initialTab);
  const [points, setPoints] = useState<Btx2PricePoint[] | null>(null);
  const [status, setStatus] = useState<Status>('loading');

  useEffect(() => {
    let cancelled = false;
    // RUNE FILLS is not on BRK — that's reconstructed from confirmed
    // swaps server-side later. Only the BTC tab fetches live data today.
    if (tab !== 'btc') {
      setPoints(null);
      setStatus('fallback');
      return;
    }
    setStatus('loading');
    api
      .pricesClose(days)
      .then((p) => {
        if (cancelled) return;
        setPoints(p);
        setStatus('live');
      })
      .catch(() => {
        if (cancelled) return;
        setPoints(null);
        setStatus('fallback');
      });
    return () => {
      cancelled = true;
    };
  }, [tab, days]);

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
          {status === 'live'
            ? `BRK · price_close · ${points?.length ?? days}d`
            : status === 'loading'
              ? 'BRK · loading…'
              : 'BRK · offline · sample'}
        </span>
      </div>
      <div className="flex-1 min-h-[280px] relative">
        {status === 'live' && points && points.length >= 2 ? (
          <LiveSparkline points={points} />
        ) : (
          <FallbackSparkline />
        )}
      </div>
      <div className="text-[11px] text-dim mt-1.5">
        rune↔BTC price reconstructed from confirmed swaps. Sparse by
        nature — Bitcoin blocks, not ticks.
      </div>
    </div>
  );
}

/**
 * Real series → SVG. Scales the close-price min/max into the same
 * 0–300 viewBox the placeholder uses so the visual is interchangeable.
 */
function LiveSparkline({ points }: { points: Btx2PricePoint[] }) {
  const W = 600;
  const H = 300;
  const PAD_TOP = 30;
  const PAD_BOTTOM = 40;
  const closes = points.map((p) => p.close);
  let min = closes[0];
  let max = closes[0];
  for (const c of closes) {
    if (c < min) min = c;
    if (c > max) max = c;
  }
  if (max - min < 1) {
    // Degenerate flat series — bump the range so we don't divide by zero.
    max = min + 1;
  }
  const span = max - min;
  const xStep = points.length > 1 ? W / (points.length - 1) : 0;
  const yFor = (c: number) =>
    PAD_TOP + ((max - c) / span) * (H - PAD_TOP - PAD_BOTTOM);

  let d = '';
  let area = '';
  points.forEach((p, i) => {
    const x = i * xStep;
    const y = yFor(p.close);
    const xs = x.toFixed(1);
    const ys = y.toFixed(1);
    if (i === 0) {
      d = `M ${xs},${ys}`;
      area = `M ${xs},${ys}`;
    } else {
      d += ` L ${xs},${ys}`;
      area += ` L ${xs},${ys}`;
    }
  });
  area += ` L ${W},${H} L 0,${H} Z`;

  // Four evenly-spaced axis labels.
  const labels = [0.25, 0.5, 0.75, 1.0].map((t) => {
    const v = max - t * span;
    return { v, y: PAD_TOP + t * (H - PAD_TOP - PAD_BOTTOM) };
  });

  const fmt = (v: number) => {
    if (v >= 1000) return `$${(v / 1000).toFixed(0)}k`;
    return `$${v.toFixed(0)}`;
  };

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className="w-full h-full block"
    >
      <defs>
        <linearGradient id="ag-live" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#ff8c00" stopOpacity=".3" />
          <stop offset="100%" stopColor="#ff8c00" stopOpacity="0" />
        </linearGradient>
      </defs>
      <g stroke="#1f1f1f" strokeWidth="1">
        {labels.map((l, i) => (
          <line key={i} x1="0" y1={l.y} x2={W} y2={l.y} />
        ))}
      </g>
      <path d={area} fill="url(#ag-live)" />
      <path d={d} stroke="#ff8c00" strokeWidth="1.5" fill="none" />
      <g fill="#666" fontFamily="Source Code Pro" fontSize="10">
        {labels.map((l, i) => (
          <text key={i} x={W - 5} y={l.y - 5} textAnchor="end">
            {fmt(l.v)}
          </text>
        ))}
      </g>
    </svg>
  );
}

/** Previous hardcoded sparkline — kept verbatim as the offline fallback. */
function FallbackSparkline() {
  return (
    <svg
      viewBox="0 0 600 300"
      preserveAspectRatio="none"
      className="w-full h-full block"
    >
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
        <text x="595" y="55" textAnchor="end">
          $110k
        </text>
        <text x="595" y="115" textAnchor="end">
          $105k
        </text>
        <text x="595" y="175" textAnchor="end">
          $100k
        </text>
        <text x="595" y="235" textAnchor="end">
          $95k
        </text>
      </g>
    </svg>
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
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      className={
        on
          ? 'h-[18px] inline-flex items-center justify-center px-2.5 text-[10px] tracking-wider leading-none bg-orange text-black border border-orange rounded-sm cursor-pointer font-mono uppercase font-bold'
          : 'h-[18px] inline-flex items-center justify-center px-2.5 text-[10px] tracking-wider leading-none bg-panel text-fg border border-transparent rounded-sm cursor-pointer font-mono uppercase hover:bg-hover hover:text-fg-bright'
      }
    >
      {children}
    </button>
  );
}
