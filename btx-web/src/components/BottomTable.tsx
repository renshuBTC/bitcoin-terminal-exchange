'use client';
/**
 * Bottom table with Open Orders / Pending / Trade History / Balances
 * tabs. Matches btx_trade.html's .bottom block (lines 480–491).
 *
 * Open Orders are passed in from the page-level fetch (SSR-friendly).
 * Pending / Trade History fetch lazily when the user switches tabs —
 * each tab caches its first successful response so subsequent
 * switches are instant. Balances tab wires to the connected wallet.
 */
import { useEffect, useState } from 'react';

import { api, type Btx2OrderView } from '@/lib/api';
import { useSelectedOrder } from './SelectedOrderProvider';
import { useWallet } from './WalletProvider';

type BTab = 'orders' | 'pending' | 'trades' | 'balances';

interface BottomTableProps {
  orders: Btx2OrderView[];
}

type FetchState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'data'; rows: Btx2OrderView[] }
  | { kind: 'error'; message: string };

export function BottomTable({ orders }: BottomTableProps) {
  const [tab, setTab] = useState<BTab>('orders');
  const { select } = useSelectedOrder();
  const { connected, balanceSats } = useWallet();

  const [pending, setPending] = useState<FetchState>({ kind: 'idle' });
  const [trades, setTrades] = useState<FetchState>({ kind: 'idle' });

  useEffect(() => {
    let cancelled = false;
    const fetchFor = async (
      which: 'pending' | 'trades',
      setter: (s: FetchState) => void,
      call: () => Promise<Btx2OrderView[]>,
    ) => {
      setter({ kind: 'loading' });
      try {
        const rows = await call();
        if (cancelled) return;
        setter({ kind: 'data', rows });
      } catch (e) {
        if (cancelled) return;
        setter({
          kind: 'error',
          message: e instanceof Error ? e.message : `${which} fetch failed`,
        });
      }
    };
    if (tab === 'pending' && pending.kind === 'idle') {
      void fetchFor('pending', setPending, () => api.conditional());
    } else if (tab === 'trades' && trades.kind === 'idle') {
      void fetchFor('trades', setTrades, () => api.filled());
    }
    return () => {
      cancelled = true;
    };
  }, [tab, pending.kind, trades.kind]);

  const rowsForTab = activeRows(tab, orders, pending, trades);
  const emptyMsg = emptyMessageForTab(tab, pending, trades);

  return (
    <div className="border-t border-border bg-bg min-h-[220px]">
      <div className="flex gap-0 px-4 items-center border-b border-border text-xs">
        <BTabBtn on={tab === 'orders'} onClick={() => setTab('orders')}>
          Open Orders
        </BTabBtn>
        <BTabBtn on={tab === 'pending'} onClick={() => setTab('pending')}>
          Pending
        </BTabBtn>
        <BTabBtn on={tab === 'trades'} onClick={() => setTab('trades')}>
          Trade History
        </BTabBtn>
        <BTabBtn on={tab === 'balances'} onClick={() => setTab('balances')}>
          Balances
        </BTabBtn>
        <span className="ml-auto text-dim text-[11px] cursor-default">
          Filter ▾
        </span>
      </div>
      {tab === 'balances' ? (
        <BalancesPanel
          connected={!!connected}
          address={connected?.address ?? null}
          providerName={connected?.providerName ?? null}
          balanceSats={balanceSats}
        />
      ) : (
        <table className="w-full border-collapse text-xs bg-bg">
          <thead>
            <tr>
              <Th>State</Th>
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
            {rowsForTab.length === 0 ? (
              <tr>
                <td
                  colSpan={8}
                  className="text-dim text-center py-6 font-mono"
                >
                  {emptyMsg}
                </td>
              </tr>
            ) : (
              rowsForTab.map((o) => (
                <tr
                  key={o.id_hex}
                  onClick={() =>
                    select({
                      label: `${o.id_hex.slice(0, 16)}…`,
                      artifactHex: o.id_hex,
                      source: 'bottom-table',
                      detail: {
                        // Amount / price / side aren't on Btx2OrderView
                        // yet (the view exposes only id + state + maker
                        // pubkey + outpoint + heights — see lib/api.ts).
                        // When those fields land they slot in here.
                        makerShort: `${o.maker_pubkey_hex.slice(0, 8)}…`,
                      },
                    })
                  }
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
      )}
    </div>
  );
}

/**
 * Selects the row source for the current tab. Falls back to an empty
 * array when the fetch is in flight or errored so the empty-row state
 * always shows a meaningful message.
 */
function activeRows(
  tab: BTab,
  orders: Btx2OrderView[],
  pending: FetchState,
  trades: FetchState,
): Btx2OrderView[] {
  if (tab === 'orders') return orders;
  if (tab === 'pending') return pending.kind === 'data' ? pending.rows : [];
  if (tab === 'trades') return trades.kind === 'data' ? trades.rows : [];
  return [];
}

function emptyMessageForTab(
  tab: BTab,
  pending: FetchState,
  trades: FetchState,
): string {
  if (tab === 'orders') return 'No open orders · waiting on chain data';
  if (tab === 'pending') {
    if (pending.kind === 'loading') return 'Loading conditional orders…';
    if (pending.kind === 'error') return `· ${pending.message}`;
    return 'No pending transactions';
  }
  if (tab === 'trades') {
    if (trades.kind === 'loading') return 'Loading trade history…';
    if (trades.kind === 'error') return `· ${trades.message}`;
    return 'No completed trades yet';
  }
  return '';
}

function BalancesPanel({
  connected,
  address,
  providerName,
  balanceSats,
}: {
  connected: boolean;
  address: string | null;
  providerName: string | null;
  balanceSats: number | null;
}) {
  if (!connected) {
    return (
      <div className="text-dim text-center py-6 font-mono text-xs">
        Connect a wallet to see balances
      </div>
    );
  }
  const btc =
    balanceSats !== null
      ? (balanceSats / 1e8).toLocaleString(undefined, {
          minimumFractionDigits: 0,
          maximumFractionDigits: 8,
        })
      : '—';
  return (
    <table className="w-full border-collapse text-xs bg-bg">
      <thead>
        <tr>
          <Th>Wallet</Th>
          <Th>Address</Th>
          <Th right>Confirmed (BTC)</Th>
          <Th right>Confirmed (sats)</Th>
        </tr>
      </thead>
      <tbody>
        <tr className="border-t border-border-soft">
          <td className="px-4 py-2 font-mono text-fg">
            {providerName ?? 'wallet'}
          </td>
          <td className="px-4 py-2 font-mono text-fg break-all">{address}</td>
          <td className="px-4 py-2 font-mono text-fg text-right">{btc}</td>
          <td className="px-4 py-2 font-mono text-fg text-right">
            {balanceSats !== null ? balanceSats.toLocaleString() : '—'}
          </td>
        </tr>
      </tbody>
    </table>
  );
}

function BTabBtn({
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
