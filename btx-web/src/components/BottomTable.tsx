'use client';
/**
 * Bottom table with Open Orders / Pending / Trade History / Balances
 * tabs. Matches btx_trade.html's .bottom block (lines 480–491).
 */
import { useState } from 'react';
import type { Btx2OrderView } from '@/lib/api';
import { useSelectedOrder } from './SelectedOrderProvider';

type BTab = 'orders' | 'pending' | 'trades' | 'balances';

interface BottomTableProps {
  orders: Btx2OrderView[];
}

export function BottomTable({ orders }: BottomTableProps) {
  const [tab, setTab] = useState<BTab>('orders');
  const { select } = useSelectedOrder();

  return (
    <div className="border-t border-border bg-bg min-h-[220px]">
      <div className="flex gap-0 px-4 items-center border-b border-border text-xs">
        <BTab on={tab === 'orders'} onClick={() => setTab('orders')}>
          Open Orders
        </BTab>
        <BTab on={tab === 'pending'} onClick={() => setTab('pending')}>
          Pending
        </BTab>
        <BTab on={tab === 'trades'} onClick={() => setTab('trades')}>
          Trade History
        </BTab>
        <BTab on={tab === 'balances'} onClick={() => setTab('balances')}>
          Balances
        </BTab>
        <span className="ml-auto text-dim text-[11px] cursor-default">
          Filter ▾
        </span>
      </div>
      <table className="w-full border-collapse text-xs bg-bg">
        <thead>
          <tr>
            <Th>Side</Th>
            <Th>Stablecoin</Th>
            <Th right>Amount</Th>
            <Th right>Price (sats)</Th>
            <Th right>Total (BTC)</Th>
            <Th>Offer (txid:vout)</Th>
            <Th right>Announced</Th>
            <Th right>Expiry</Th>
          </tr>
        </thead>
        <tbody>
          {orders.length === 0 ? (
            <tr>
              <td
                colSpan={8}
                className="text-dim text-center py-6 font-mono"
              >
                {tab === 'orders'
                  ? 'No open orders · waiting on chain data'
                  : tab === 'pending'
                  ? 'No pending transactions'
                  : tab === 'trades'
                  ? 'No completed trades yet'
                  : 'Connect a wallet to see balances'}
              </td>
            </tr>
          ) : (
            orders.map((o) => (
              <tr
                key={o.id_hex}
                onClick={() => select({ label: `${o.id_hex.slice(0,16)}…`, artifactHex: o.id_hex, source: 'bottom-table' })}
                className="border-t border-border-soft hover:bg-hover cursor-pointer"
              >
                <td className="px-4 py-2 font-mono text-fg">{o.state}</td>
                <td className="px-4 py-2 font-mono text-fg">—</td>
                <td className="px-4 py-2 font-mono text-fg text-right">—</td>
                <td className="px-4 py-2 font-mono text-fg text-right">—</td>
                <td className="px-4 py-2 font-mono text-fg text-right">—</td>
                <td className="px-4 py-2 font-mono text-fg">
                  {o.offer_outpoint}
                </td>
                <td className="px-4 py-2 font-mono text-fg text-right">
                  {o.announce_block_height.toLocaleString()}
                </td>
                <td className="px-4 py-2 font-mono text-fg text-right">
                  {o.expiry.toLocaleString()}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function BTab({
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
          ? 'text-orange cursor-pointer py-3 mr-6 font-mono font-medium uppercase tracking-wider border-b-2 border-orange -mb-px'
          : 'text-muted cursor-pointer py-3 mr-6 font-mono font-medium uppercase tracking-wider border-b-2 border-transparent -mb-px hover:text-fg-bright'
      }
    >
      {children}
    </span>
  );
}

function Th({
  children,
  right,
}: {
  children: React.ReactNode;
  right?: boolean;
}) {
  return (
    <th
      className={`text-muted font-medium px-4 py-2 text-[10px] uppercase tracking-wider border-b border-border-soft font-mono ${
        right ? 'text-right' : 'text-left'
      }`}
    >
      {children}
    </th>
  );
}
