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
import {
  clearAttestations,
  onAttestationsChanged,
  readAttestations,
  type Attestation,
} from '@/lib/attestations';
import { useSelectedOrder } from './SelectedOrderProvider';
import { useWallet } from './WalletProvider';

type BTab = 'orders' | 'pending' | 'trades' | 'balances' | 'activity';

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
        <BTabBtn on={tab === 'activity'} onClick={() => setTab('activity')}>
          My Activity
        </BTabBtn>
        <span className="ml-auto text-dim text-[11px] cursor-default">
          Filter ▾
        </span>
      </div>
      {tab === 'activity' ? (
        <ActivityPanel />
      ) : tab === 'balances' ? (
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
              rowsForTab.map((o) => {
                const runeId =
                  typeof o.rune_block === 'number' &&
                  typeof o.rune_tx === 'number'
                    ? `${o.rune_block}:${o.rune_tx}`
                    : '—';
                const amountText =
                  typeof o.amount === 'number'
                    ? o.amount.toLocaleString()
                    : '—';
                const priceText =
                  typeof o.price === 'number'
                    ? o.price.toLocaleString()
                    : '—';
                const totalText =
                  typeof o.amount === 'number' && typeof o.price === 'number'
                    ? ((o.amount * o.price) / 1e8).toLocaleString(undefined, {
                        minimumFractionDigits: 0,
                        maximumFractionDigits: 8,
                      })
                    : '—';
                return (
                  <tr
                    key={o.id_hex}
                    onClick={() =>
                      select({
                        label: `${o.id_hex.slice(0, 16)}…`,
                        artifactHex: o.id_hex,
                        source: 'bottom-table',
                        detail: {
                          rune: runeId === '—' ? undefined : runeId,
                          amount: o.amount,
                          priceSats: o.price,
                          makerShort: `${o.maker_pubkey_hex.slice(0, 8)}…`,
                        },
                      })
                    }
                    className="border-t border-border-soft hover:bg-hover cursor-pointer"
                  >
                    <td className="px-4 py-2 font-mono text-fg">{o.state}</td>
                    <td className="px-4 py-2 font-mono text-fg">{runeId}</td>
                    <td className="px-4 py-2 font-mono text-fg text-right">
                      {amountText}
                    </td>
                    <td className="px-4 py-2 font-mono text-fg text-right">
                      {priceText}
                    </td>
                    <td className="px-4 py-2 font-mono text-fg text-right">
                      {totalText}
                    </td>
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
                );
              })
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

/**
 * "My Activity" — paint the local attestation log. Pure-client; reads
 * localStorage on mount and after every `appendAttestation` (via the
 * onAttestationsChanged event). Empty-state explains where rows
 * come from so a fresh user understands.
 */
function ActivityPanel() {
  const [rows, setRows] = useState<Attestation[]>([]);
  useEffect(() => {
    setRows(readAttestations());
    return onAttestationsChanged(() => setRows(readAttestations()));
  }, []);
  const clear = () => {
    if (typeof window === 'undefined') return;
    const ok = window.confirm(
      'Clear all locally-saved attestations? This does not affect anything on-chain.',
    );
    if (!ok) return;
    clearAttestations();
    setRows([]);
  };
  if (rows.length === 0) {
    return (
      <div className="text-dim text-center py-6 font-mono text-xs px-4">
        No saved attestations yet.
        <br />
        Publish or fill an order — each successful BIP-322 signature
        is saved locally so you can re-broadcast later.
      </div>
    );
  }
  return (
    <div>
      <table className="w-full border-collapse text-xs bg-bg">
        <thead>
          <tr>
            <Th>When</Th>
            <Th>Kind</Th>
            <Th>Wallet</Th>
            <Th>Summary</Th>
            <Th>Signature</Th>
            <Th>Body</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <ActivityRow key={r.id} row={r} />
          ))}
        </tbody>
      </table>
      <div className="flex justify-end px-4 py-2 border-t border-border-soft">
        <button
          onClick={clear}
          className="text-[10px] text-dim uppercase tracking-wider hover:text-red font-mono"
        >
          Clear local log
        </button>
      </div>
    </div>
  );
}

/**
 * Activity log row. For 'fill' attestations we know which order id
 * the taker committed to (it's the artifactHex from the click). For
 * 'publish' we don't yet know the on-chain order id — the broadcast
 * step assigns it. So the body fetch is only meaningful when the
 * summary looks like a fill targeting a 72-char hex id (parsed from
 * the 'fill ← <id>' summary we synthesize in TradePanel.fill()).
 *
 * The body fetch uses the new GET /api/v1/btx2/orders/{id}/body
 * endpoint added in the brk-btx commit B.
 */
function ActivityRow({ row }: { row: Attestation }) {
  const [bodyState, setBodyState] = useState<
    | { kind: 'idle' }
    | { kind: 'loading' }
    | { kind: 'data'; hex: string }
    | { kind: 'error'; message: string }
    | { kind: 'unsupported' }
  >({ kind: 'idle' });

  const idFromFill = (() => {
    if (row.kind !== 'fill') return null;
    // Summary format: "fill ← <first-20-chars-of-id>…" — strip
    // arrow + ellipsis. We only fetch when the full 72-char hex
    // form is recoverable; otherwise mark unsupported.
    const m = row.summary.match(/fill ← ([0-9a-fA-F]+)/);
    if (!m) return null;
    return m[1].length >= 72 ? m[1].slice(0, 72) : null;
  })();

  const fetchBody = async () => {
    if (!idFromFill) {
      setBodyState({ kind: 'unsupported' });
      return;
    }
    setBodyState({ kind: 'loading' });
    try {
      const hex = await api.orderBody(idFromFill);
      if (hex === null) {
        setBodyState({ kind: 'error', message: 'order not in store' });
        return;
      }
      setBodyState({ kind: 'data', hex });
    } catch (e) {
      setBodyState({
        kind: 'error',
        message: e instanceof Error ? e.message : 'fetch failed',
      });
    }
  };

  return (
    <tr className="border-t border-border-soft align-top">
      <td className="px-4 py-2 font-mono text-fg whitespace-nowrap">
        {formatRelative(row.ts)}
      </td>
      <td className="px-4 py-2 font-mono">
        <span className={row.kind === 'publish' ? 'text-orange' : 'text-green'}>
          {row.kind}
        </span>
      </td>
      <td className="px-4 py-2 font-mono text-fg">
        {row.provider}
        <span className="text-dim"> · {row.network}</span>
      </td>
      <td className="px-4 py-2 font-mono text-fg break-all">{row.summary}</td>
      <td className="px-4 py-2 font-mono text-dim break-all">
        {row.signature.slice(0, 12)}…{row.signature.slice(-8)}
      </td>
      <td className="px-4 py-2 font-mono">
        {bodyState.kind === 'idle' && (
          <button
            onClick={fetchBody}
            disabled={row.kind === 'publish'}
            title={
              row.kind === 'publish'
                ? "Publish doesn't yet have an on-chain order id"
                : 'Fetch the canonical signed body bytes'
            }
            className="text-[10px] text-dim uppercase tracking-wider border border-border-soft rounded-sm px-1.5 py-0.5 hover:text-fg-bright hover:border-line-strong disabled:opacity-40 disabled:cursor-default cursor-pointer"
          >
            fetch
          </button>
        )}
        {bodyState.kind === 'loading' && (
          <span className="text-[10px] text-dim">loading…</span>
        )}
        {bodyState.kind === 'unsupported' && (
          <span className="text-[10px] text-dim">n/a</span>
        )}
        {bodyState.kind === 'error' && (
          <span className="text-[10px] text-red">· {bodyState.message}</span>
        )}
        {bodyState.kind === 'data' && (
          <span className="text-[10px] text-green break-all">
            {bodyState.hex.slice(0, 16)}…
            <span className="text-dim"> ({bodyState.hex.length / 2}B)</span>
          </span>
        )}
      </td>
    </tr>
  );
}

function formatRelative(iso: string): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return iso;
  const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return new Date(t).toLocaleString();
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
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      className={
        on
          ? 'text-orange cursor-pointer py-3 mr-6 font-mono font-medium uppercase tracking-wider border-b-2 border-orange -mb-px bg-transparent border-x-0 border-t-0'
          : 'text-muted cursor-pointer py-3 mr-6 font-mono font-medium uppercase tracking-wider border-b-2 border-transparent -mb-px hover:text-fg-bright bg-transparent border-x-0 border-t-0'
      }
    >
      {children}
    </button>
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
