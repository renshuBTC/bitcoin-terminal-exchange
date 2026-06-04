'use client';
/**
 * Small preview card shown above the Fill artifact textarea. Reads
 * SelectedOrderProvider state and renders side/rune/amount/price/
 * maker so the taker sees what they're committing to before they sign.
 *
 * Pure presentational — renders nothing when nothing is selected, or
 * when the selection lacks a `detail` payload (e.g. manual entry).
 */
import { useSelectedOrder } from './SelectedOrderProvider';

export function SelectedOrderDetail() {
  const { selected } = useSelectedOrder();
  if (!selected || !selected.detail) return null;
  const d = selected.detail;
  const sideColor = d.side === 'buy' ? 'text-green' : 'text-red';

  return (
    <div className="mt-2 mb-2 border border-border-soft rounded-sm bg-panel p-2 font-mono text-[11px]">
      <div className="flex justify-between items-baseline mb-1">
        <span className="text-[10px] uppercase tracking-wider text-muted">
          Filling
        </span>
        <span className="text-[10px] text-dim normal-case tracking-normal">
          {selected.label}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
        <DetailRow label="Side">
          <span className={`uppercase ${sideColor}`}>{d.side ?? '—'}</span>
        </DetailRow>
        <DetailRow label="Rune">
          <span className="text-fg-bright">{d.rune ?? '—'}</span>
        </DetailRow>
        <DetailRow label="Amount">
          <span>{d.amount !== undefined ? d.amount.toLocaleString() : '—'}</span>
        </DetailRow>
        <DetailRow label="Price">
          <span>
            {d.priceSats !== undefined
              ? `${d.priceSats.toLocaleString()} sats`
              : '—'}
          </span>
        </DetailRow>
        <DetailRow label="Maker">
          <span className="text-dim">{d.makerShort ?? '—'}</span>
        </DetailRow>
        <DetailRow label="Total">
          <span>
            {d.amount !== undefined && d.priceSats !== undefined
              ? `${(d.amount * d.priceSats).toLocaleString()} sats`
              : '—'}
          </span>
        </DetailRow>
      </div>
    </div>
  );
}

function DetailRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex justify-between items-baseline">
      <span className="text-[10px] uppercase tracking-wider text-muted">
        {label}
      </span>
      {children}
    </div>
  );
}
