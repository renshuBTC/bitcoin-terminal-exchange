/**
 * Orderbook table. Read-only in the MVP — clicking an order will
 * trigger the BUY flow once wallet integration lands.
 */
import type { Btx2OrderView } from '@/lib/api';

export function OrderBook({ orders }: { orders: Btx2OrderView[] }) {
  if (orders.length === 0) {
    return (
      <section className="rounded-lg bg-panel-2 border border-border-strong p-8 text-center text-fg-2">
        <div className="text-fg-1 text-lg font-semibold mb-2">
          No open orders
        </div>
        <div className="text-sm">
          The orderbook is empty right now. This is expected if the indexer
          hasn&apos;t encountered any BTX2 envelopes yet on the connected
          network (or if you&apos;re running against a freshly-started
          stub).
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-lg bg-panel-2 border border-border-strong overflow-hidden">
      <div className="px-4 py-3 border-b border-border-strong">
        <h2 className="font-semibold">Open orders ({orders.length})</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm font-mono">
          <thead className="bg-panel">
            <tr className="text-fg-2 text-xs uppercase tracking-wide">
              <th className="text-left px-4 py-2">order id</th>
              <th className="text-left px-4 py-2">maker pubkey</th>
              <th className="text-left px-4 py-2">offer outpoint</th>
              <th className="text-right px-4 py-2">expiry</th>
              <th className="text-right px-4 py-2">announced</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr
                key={o.id_hex}
                className="border-t border-border-strong hover:bg-panel/60 cursor-pointer"
              >
                <td className="px-4 py-2" title={o.id_hex}>
                  {o.id_hex.slice(0, 16)}…
                </td>
                <td className="px-4 py-2" title={o.maker_pubkey_hex}>
                  {o.maker_pubkey_hex.slice(0, 12)}…
                </td>
                <td className="px-4 py-2">{o.offer_outpoint}</td>
                <td className="px-4 py-2 text-right">
                  {o.expiry.toLocaleString()}
                </td>
                <td className="px-4 py-2 text-right">
                  {o.announce_block_height.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
