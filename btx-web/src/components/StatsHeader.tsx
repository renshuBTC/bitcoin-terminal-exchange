'use client';
/**
 * Stats header. The "Wallet" metric now reflects the connected wallet's
 * confirmed balance when one is connected.
 */
import type { Btx2Health } from '@/lib/api';
import { useWallet } from './WalletProvider';

interface StatsHeaderProps {
  pair?: string;
  markPriceUsd?: string;
  lastSats?: string;
  health?: Btx2Health | null;
  volume24h?: string;
  streamHash?: string;
}

function fmtBtc(sats: number): string {
  return (sats / 1e8).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 8,
  });
}

export function StatsHeader({
  pair = 'USDH / BTC',
  markPriceUsd = '—',
  lastSats = '—',
  health,
  volume24h = '—',
  streamHash = '—',
}: StatsHeaderProps) {
  const { connected, balanceSats } = useWallet();
  const tipHeight = health?.tip_height ?? 0;
  const streamShort = streamHash === '—' ? '—' : `${streamHash.slice(0, 8)}…`;
  const walletText = balanceSats !== null ? fmtBtc(balanceSats) : '0.00000';

  return (
    <div className="flex items-center gap-6 px-4 py-2.5 bg-bg border-b border-border overflow-x-auto">
      <div className="flex items-center gap-2.5 pr-5 border-r border-border">
        <span className="font-display font-bold text-[18px] text-fg-bright tracking-wide">
          {pair}
        </span>
        <span className="bg-orange text-black rounded-sm px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider">
          spot · L1
        </span>
      </div>
      <Metric label="Mark">
        <span className="text-dim text-[10px]">$</span>{markPriceUsd}
      </Metric>
      <Metric label="Last">
        {lastSats} <span className="text-dim text-[10px]">sats</span>
      </Metric>
      <Metric label="Indexer" small>
        {health?.ok ? 'node' : 'preview'}
      </Metric>
      <Metric label="Height" small>
        {tipHeight ? tipHeight.toLocaleString() : '—'}
      </Metric>
      <Metric label="24h Vol" small>
        {volume24h} <span className="text-dim text-[10px]">BTC</span>
      </Metric>
      <Metric label="Wallet" small>
        <span className={connected ? 'text-green' : ''}>
          {walletText} <span className="text-dim text-[10px]">BTC</span>
        </span>
      </Metric>
      <Metric label="Stream Hash" small>{streamShort}</Metric>
    </div>
  );
}

function Metric({
  label,
  small,
  children,
}: {
  label: string;
  small?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-0.5 min-w-max">
      <span className="text-[10px] text-muted uppercase tracking-wider">{label}</span>
      <span className={`${small ? 'text-xs' : 'text-[13px]'} text-fg font-mono`}>
        {children}
      </span>
    </div>
  );
}
