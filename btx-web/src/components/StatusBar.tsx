/**
 * Bottom status bar — live indicator + Source link.
 * Matches btx_trade.html's .statusbar (lines 492–502) with the
 * consolidation decision applied: just live status + Source.
 */
import type { Btx2Health, Btx2StateRoot } from '@/lib/api';

interface StatusBarProps {
  health: Btx2Health | null;
  stateRoot: Btx2StateRoot | null;
}

export function StatusBar({ health, stateRoot }: StatusBarProps) {
  const ok = health?.ok ?? false;
  const rootShort = stateRoot
    ? `${stateRoot.root_hex.slice(0, 12)}…`
    : '—';
  return (
    <div className="flex items-center gap-[18px] px-3 py-1.5 bg-bg border-t border-border text-xs text-muted flex-wrap">
      <span
        className={`flex items-center gap-1.5 ${
          ok ? 'text-green' : 'text-red'
        }`}
      >
        <span
          className={`w-[7px] h-[7px] rounded-full inline-block ${
            ok ? 'bg-green' : 'bg-red'
          }`}
        />
        {ok ? 'live · indexer connected' : 'preview · not connected'}
      </span>
      <span>
        block:{' '}
        <span className="text-fg font-mono">
          {health?.tip_height ? health.tip_height.toLocaleString() : '—'}
        </span>
      </span>
      <span>
        state root: <span className="text-fg font-mono">{rootShort}</span>
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
