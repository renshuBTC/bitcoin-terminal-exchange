'use client';
/**
 * Bottom status bar — live indicator + tip height + open-order count
 * + state root + last-refresh age + Source link.
 *
 * Server-side fetched values are passed in as initial props. The bar
 * then re-polls /healthz every 30s on the client, so the indicator
 * goes red the moment brk-btx becomes unreachable, and goes green
 * again when it comes back. State root is left at its SSR value
 * since it only changes when block height changes — the height pill
 * already telegraphs that.
 *
 * Matches btx_trade.html's .statusbar (lines 492–502) with the
 * consolidation decision applied: just live status + tip + Source.
 */
import { useEffect, useState } from 'react';

import { api, type Btx2Health, type Btx2StateRoot } from '@/lib/api';

interface StatusBarProps {
  health: Btx2Health | null;
  stateRoot: Btx2StateRoot | null;
}

/** Auto-poll interval, ms. Matches the chart's 60s revalidate ÷2. */
const POLL_MS = 30_000;

export function StatusBar({ health: initialHealth, stateRoot }: StatusBarProps) {
  const [health, setHealth] = useState<Btx2Health | null>(initialHealth);
  const [lastFetchMs, setLastFetchMs] = useState<number>(Date.now());
  const [now, setNow] = useState<number>(Date.now());

  // Poll healthz on a fixed interval. Silent on failure — the indicator
  // pill will turn red because health.ok stays false (or we keep the
  // last known value but mark it stale).
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const h = await api.health();
        if (cancelled) return;
        setHealth(h);
      } catch {
        if (cancelled) return;
        // Don't blow away the last known value — caller's eye sees
        // "last update Ns ago" climbing, and the indicator stays
        // green-but-stale until the next successful poll.
      } finally {
        if (!cancelled) setLastFetchMs(Date.now());
      }
    };
    const t = setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  // Drive the "Ns ago" display.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const ok = health?.ok ?? false;
  const rootShort = stateRoot
    ? `${stateRoot.root_hex.slice(0, 12)}…`
    : '—';
  const ageSec = Math.max(0, Math.floor((now - lastFetchMs) / 1000));
  const ageText =
    ageSec < 5 ? 'just now' : ageSec < 60 ? `${ageSec}s ago` : `${Math.floor(ageSec / 60)}m ago`;
  // After 2× the poll interval with no success, show stale dot color.
  const stale = ageSec > (POLL_MS * 2) / 1000;
  const dot = ok && !stale ? 'bg-green' : stale ? 'bg-orange' : 'bg-red';
  const label =
    ok && !stale
      ? 'live · indexer connected'
      : ok && stale
        ? 'live · poll stalled'
        : 'preview · not connected';
  const labelColor = ok && !stale ? 'text-green' : stale ? 'text-orange' : 'text-red';

  return (
    <div className="flex items-center gap-[18px] px-3 py-1.5 bg-bg border-t border-border text-xs text-muted flex-wrap">
      <span className={`flex items-center gap-1.5 ${labelColor}`}>
        <span className={`w-[7px] h-[7px] rounded-full inline-block ${dot}`} />
        {label}
      </span>
      <span>
        block:{' '}
        <span className="text-fg font-mono">
          {health?.tip_height ? health.tip_height.toLocaleString() : '—'}
        </span>
      </span>
      <span>
        open:{' '}
        <span className="text-fg font-mono">
          {health?.n_open_orders !== undefined
            ? health.n_open_orders.toLocaleString()
            : '—'}
        </span>
      </span>
      <span>
        state root: <span className="text-fg font-mono">{rootShort}</span>
      </span>
      <span>
        update: <span className="text-fg font-mono">{ageText}</span>
      </span>
      <span className="ml-auto flex gap-3.5">
        <a
          href="https://github.com/renshuBTC/bitcoin-terminal-exchange"
          target="_blank"
          rel="noreferrer"
          className="text-muted text-[11px] uppercase tracking-wider hover:text-fg-bright"
        >
          Source
        </a>
      </span>
    </div>
  );
}
