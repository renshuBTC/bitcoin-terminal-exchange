/**
 * Transparency page per build-plan §6.
 *
 * Spells out, in plain language, what the user is and isn't trusting
 * when they use this website. The content here is the load-bearing
 * differentiator vs a centralized exchange — if the user can't follow
 * the trust argument, the architectural advantage doesn't matter.
 */
import { api } from '@/lib/api';

async function fetchStateRoot() {
  try {
    return await api.stateRoot();
  } catch {
    return null;
  }
}

export default async function TransparencyPage() {
  const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3110';
  const root = await fetchStateRoot();

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 space-y-8 text-fg-1">
      <header>
        <h1 className="text-3xl font-semibold mb-2">Transparency</h1>
        <p className="text-fg-2">
          What you&apos;re trusting when you use this site, in plain English.
        </p>
      </header>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">What you are trusting</h2>
        <ul className="list-disc list-inside space-y-2 text-fg-2 marker:text-btc-orange">
          <li>
            The operator of <code className="text-fg-1">{new URL(apiBase).host}</code>{' '}
            (this indexer + API) to report honest orderbook data.
          </li>
          <li>
            The same operator to forward your signed transaction to Bitcoin&apos;s
            mempool unmodified.
          </li>
        </ul>
        <p className="text-sm text-fg-2 mt-2">
          That&apos;s it. The operator never sees your private keys, never
          holds your funds, and cannot move your money.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">What you are NOT trusting</h2>
        <ul className="list-disc list-inside space-y-2 text-fg-2 marker:text-btc-orange">
          <li>
            <span className="text-fg-1">Your keys stay in your wallet.</span>{' '}
            The website asks your wallet to sign; it never sees the key.
          </li>
          <li>
            <span className="text-fg-1">Trades land on Bitcoin.</span> Your
            signed transaction goes into Bitcoin&apos;s mempool, not into
            any BTX-controlled ledger.
          </li>
          <li>
            <span className="text-fg-1">The chain is the source of truth.</span>{' '}
            Anyone can independently verify any order by running their own
            indexer.
          </li>
          <li>
            <span className="text-fg-1">No custody, ever.</span> The BTX
            operator cannot freeze, seize, or move your funds — they
            don&apos;t have access.
          </li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Cross-verification</h2>
        <p className="text-fg-2">
          BTX&apos;s indexer produces a deterministic state-root hash at
          each Bitcoin block. Two honest indexers running against the same
          Bitcoin chain must produce the same hash. If they disagree, at
          least one is lying.
        </p>
        <div className="rounded bg-panel-2 border border-border-strong p-3 font-mono text-sm">
          <div className="text-fg-2 text-xs uppercase">current state root</div>
          <div className="break-all">
            {root ? root.root_hex : 'API unreachable'}
          </div>
          {root && (
            <div className="text-fg-2 text-xs mt-1">
              at block {root.height.toLocaleString()}
            </div>
          )}
        </div>
        <p className="text-sm text-fg-2">
          When community-operated indexers come online, this page will
          show the state root from each and flag any disagreement
          immediately.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Run your own</h2>
        <p className="text-fg-2">
          The strongest verification is your own indexer. The brk-btx Rust
          code is open source. A laptop and a Bitcoin Core node are enough.
          Once it&apos;s synced, point this website at it by setting{' '}
          <code className="font-mono text-fg-1">?api=http://localhost:3110</code>{' '}
          in the URL.
        </p>
        <ul className="list-disc list-inside text-fg-2 marker:text-btc-orange">
          <li>
            <a
              href="https://github.com/renshuBTC/brk-btx"
              target="_blank"
              rel="noreferrer"
            >
              brk-btx source on GitHub
            </a>
          </li>
          <li>
            <a
              href="https://github.com/renshuBTC/bitcoin-terminal-exchange"
              target="_blank"
              rel="noreferrer"
            >
              bitcoin-terminal-exchange source on GitHub
            </a>{' '}
            (Python tools + specs)
          </li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Compared to a regular exchange</h2>
        <div className="overflow-x-auto rounded border border-border-strong">
          <table className="w-full text-sm">
            <thead className="bg-panel-2 text-fg-2 text-xs uppercase">
              <tr>
                <th className="text-left px-3 py-2">Capability</th>
                <th className="text-left px-3 py-2">Regular exchange</th>
                <th className="text-left px-3 py-2">BTX</th>
              </tr>
            </thead>
            <tbody className="text-fg-1">
              <Row label="Holds your keys" cex="yes" btx="no" />
              <Row label="Can freeze your account" cex="yes" btx="no" />
              <Row label="Can move your funds" cex="yes" btx="no" />
              <Row label="Sees your trading history" cex="yes" btx="yes, this site does" />
              <Row label="Required to participate" cex="account / KYC" btx="a Bitcoin wallet" />
              <Row label="Operates without us" cex="no" btx="yes — anyone can run another frontend" />
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function Row({ label, cex, btx }: { label: string; cex: string; btx: string }) {
  return (
    <tr className="border-t border-border-strong">
      <td className="px-3 py-2">{label}</td>
      <td className="px-3 py-2 text-red-down">{cex}</td>
      <td className="px-3 py-2 text-green-up">{btx}</td>
    </tr>
  );
}
