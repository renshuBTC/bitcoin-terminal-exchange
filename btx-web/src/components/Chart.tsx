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
    if (i === 0) {
      d = `M ${x.toFixed(1)},${