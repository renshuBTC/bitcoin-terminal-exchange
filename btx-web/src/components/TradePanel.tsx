'use client';
/**
 * Trade panel — Open/Addressed mode toggle, Publish/Fill/OTC tabs,
 * Sell/Buy stablecoin toggle, full publish form, pstats footer.
 * Matches btx_trade.html's trade panel card.
 *
 * The Publish button now does a real wallet round-trip: gathers the
 * form snapshot, asks the connected wallet to BIP-322-sign it, shows
 * the resulting signature in a result strip. This is the maker
 * attestation step. The full PSBT-construct-and-broadcast flow is a
 * later commit; today's deliverable is the wallet signing roundtrip.
 */
import { useEffect, useState } from 'react';
import { useWallet } from './WalletProvider';
import { useSelectedOrder } from './SelectedOrderProvider';
import { unisatWallet } from '@/lib/wallets/unisat';

type Mode = 'open' | 'addressed';
type Tab = 'publish' | 'fill' | 'otc';
type Side = 'sell' | 'buy';

interface FormState {
  utxo: string;
  priceBtc: string;
  rune: string;
  amount: string;
  carrier: 'OP_RETURN' | 'Taproot envelope';
}

interface ResultState {
  ok: boolean;
  text: string;
}

export function TradePanel() {
  const { connected, connect } = useWallet();
  const [mode, setMode] = useState<Mode>('open');
  const [tab, setTab] = useState<Tab>('publish');
  const [side, setSide] = useState<Side>('sell');
  const [form, setForm] = useState<FormState>({
    utxo: '',
    priceBtc: '0.001',
    rune: 'USDh',
    amount: '1000',
    carrier: 'OP_RETURN',
  });
  const [result, setResult] = useState<ResultState | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [fillArtifact, setFillArtifact] = useState('');
  const [filling, setFilling] = useState(false);
  const [fillResult, setFillResult] = useState<ResultState | null>(null);

  // Subscribe to OrderBook / BottomTable row clicks.
  const { selected, nonce } = useSelectedOrder();
  useEffect(() => {
    if (selected) {
      setTab('fill');
      setFillArtifact(selected.artifactHex);
      setFillResult(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce]);

  const fill = async () => {
    setFillResult(null);
    if (!connected) {
      try { await connect(); } catch (e) {
        setFillResult({ ok: false, text: e instanceof Error ? e.message : 'connect failed' });
        return;
      }
    }
    if (!fillArtifact.trim()) {
      setFillResult({ ok: false, text: 'paste an order artifact / id first' });
      return;
    }
    setFilling(true);
    try {
      const snapshot = {
        kind: 'btx2.order.fill',
        version: 1,
        order: fillArtifact.trim(),
        taker: connected?.address ?? '(unknown)',
        network: connected?.network ?? 'mainnet',
        ts: new Date().toISOString(),
      };
      const message = JSON.stringify(snapshot, null, 2);
      const signature = await unisatWallet.signMessage(message, 'bip322');
      setFillResult({
        ok: true,
        text: `BIP-322 fill-commitment OK\nsignature: ${signature.slice(0, 24)}…${signature.slice(-12)}`,
      });
    } catch (e) {
      setFillResult({ ok: false, text: e instanceof Error ? e.message : 'sign failed' });
    } finally {
      setFilling(false);
    }
  };

  const publish = async () => {
    setResult(null);
    if (!connected) {
      try {
        await connect();
      } catch (e) {
        setResult({
          ok: false,
          text: e instanceof Error ? e.message : 'connect failed',
        });
        return;
      }
    }
    setPublishing(true);
    try {
      // The BIP-322 message the wallet signs is a structured order
      // snapshot — exactly the fields a maker is committing to. This
      // is the maker-attestation step; the on-chain PSBT publish lands
      // in a later commit.
      const snapshot = {
        kind: 'btx2.order.publish',
        version: 1,
        side,
        rune: form.rune,
        amount: form.amount,
        price_btc: form.priceBtc,
        carrier: form.carrier,
        offer_utxo: form.utxo || '(unspecified)',
        network: connected?.network ?? 'mainnet',
        ts: new Date().toISOString(),
      };
      const message = JSON.stringify(snapshot, null, 2);
      const signature = await unisatWallet.signMessage(message, 'bip322');
      setResult({
        ok: true,
        text: `BIP-322 attestation OK\nsignature: ${signature.slice(0, 24)}…${signature.slice(-12)}`,
      });
    } catch (e) {
      setResult({
        ok: false,
        text: e instanceof Error ? e.message : 'sign failed',
      });
    } finally {
      setPublishing(false);
    }
  };

  return (
    <div className="bg-bg p-3.5 flex flex-col">
      <div className="inline-flex gap-px bg-panel p-0.5 border border-line-strong rounded-sm h-[30px] mb-3 self-start">
        <ModeBtn on={mode === 'open'} onClick={() => setMode('open')}>
          Open · 0x83
        </ModeBtn>
        <ModeBtn on={mode === 'addressed'} onClick={() => setMode('addressed')}>
          Addressed · PSBT
        </ModeBtn>
      </div>
      <div className="flex gap-0 mb-3 border-b border-border">
        <TabBtn on={tab === 'publish'} onClick={() => setTab('publish')}>Publish</TabBtn>
        <TabBtn on={tab === 'fill'} onClick={() => setTab('fill')}>Fill</TabBtn>
        <TabBtn on={tab === 'otc'} onClick={() => setTab('otc')}>OTC</TabBtn>
      </div>

      {tab === 'publish' && (
        <>
          <div className="inline-flex gap-px bg-panel p-0.5 border border-line-strong rounded-sm h-8 mb-3 w-full">
            <SideBtn on={side === 'sell'} side="sell" onClick={() => setSide('sell')}>
              Sell stablecoin
            </SideBtn>
            <SideBtn on={side === 'buy'} side="buy" onClick={() => setSide('buy')}>
              Buy stablecoin
            </SideBtn>
          </div>
          <Label>Offer UTXO (P2WPKH coin)</Label>
          <Input
            placeholder="txid:vout — or connect wallet to auto-pick"
            value={form.utxo}
            onChange={(e) => setForm({ ...form, utxo: e.target.value })}
          />
          <Label>Price (BTC taker pays)</Label>
          <Input
            value={form.priceBtc}
            onChange={(e) => setForm({ ...form, priceBtc: e.target.value })}
          />
          <Label>Stablecoin</Label>
          <Select
            value={form.rune}
            onChange={(e) => setForm({ ...form, rune: e.target.value })}
          >
            <option value="USDh">USDh · BTC-backed</option>
            <option value="Ducat">Ducat · BTC-backed</option>
          </Select>
          <Label>Stablecoin amount (base units)</Label>
          <Input
            value={form.amount}
            onChange={(e) => setForm({ ...form, amount: e.target.value })}
          />
          <Label>Carrier</Label>
          <Select
            value={form.carrier}
            onChange={(e) =>
              setForm({
                ...form,
                carrier: e.target.value as 'OP_RETURN' | 'Taproot envelope',
              })
            }
          >
            <option>OP_RETURN</option>
            <option>Taproot envelope</option>
          </Select>
          <button
            onClick={publish}
            disabled={publishing}
            className="w-full mt-3 py-2.5 bg-orange text-black border border-orange rounded-sm font-mono text-xs font-bold uppercase tracking-wider cursor-pointer hover:bg-orange-bright hover:border-orange-bright disabled:opacity-60 disabled:cursor-default"
          >
            {publishing
              ? 'signing in wallet…'
              : connected
              ? 'Maker-sign & publish'
              : 'Connect wallet to publish'}
          </button>
          <div className="text-[11px] text-muted leading-relaxed mt-2.5">
            self-custody · signs via your Bitcoin wallet · settles on-chain
          </div>
          {result && (
            <div
              className={`text-[11px] mt-2.5 whitespace-pre-wrap break-all p-2 px-2.5 rounded-sm border font-mono ${
                result.ok
                  ? 'text-green border-[#2c5e57] bg-[#0c1816]'
                  : 'text-red border-[#5e2e34] bg-[#1a0e0e]'
              }`}
            >
              {result.text}
            </div>
          )}
        </>
      )}

      {tab === 'fill' && (
        <>
          <Label>Order artifact / id (click a book row to load)</Label>
          <Input
            placeholder="BTX2 artifact hex or 36-byte order id"
            value={fillArtifact}
            onChange={(e) => setFillArtifact(e.target.value)}
          />
          <button
            onClick={fill}
            disabled={filling}
            className="w-full mt-3 py-2.5 bg-orange text-black border border-orange rounded-sm font-mono text-xs font-bold uppercase tracking-wider cursor-pointer hover:bg-orange-bright hover:border-orange-bright disabled:opacity-60 disabled:cursor-default"
          >
            {filling ? 'signing in wallet…' : connected ? 'Fill — sign commitment' : 'Connect wallet to fill'}
          </button>
          <div className="text-[11px] text-muted leading-relaxed mt-2.5">
            taker funds + signs; the maker&rsquo;s pre-sig is dropped in; rune routes to your output.
          </div>
          {fillResult && (
            <div className={`text-[11px] mt-2.5 whitespace-pre-wrap break-all p-2 px-2.5 rounded-sm border font-mono ${fillResult.ok ? 'text-green border-[#2c5e57] bg-[#0c1816]' : 'text-red border-[#5e2e34] bg-[#1a0e0e]'}`}>
              {fillResult.text}
            </div>
          )}
        </>
      )}

      {tab === 'otc' && (
        <>
          <div className="text-[11px] text-muted leading-relaxed mb-2">
            Snipe-resistant addressed swap (BIP-174 PSBT, 2 parties). Taker proposes → maker verifies output 0 &amp; countersigns SIGHASH_ALL. No relay.
          </div>
          <Label>Offer UTXO (txid:vout)</Label>
          <Input placeholder="txid:vout" />
          <Label>Price (sats)</Label>
          <Input defaultValue="10000" />
          <Label>Stablecoin · amount</Label>
          <Input defaultValue="1000" />
          <button className="w-full mt-3 py-2.5 bg-transparent text-orange border border-orange rounded-sm font-mono text-xs font-bold uppercase tracking-wider cursor-pointer">
            Taker: build PSBT
          </button>
          <Label>PSBT</Label>
          <Input placeholder="paste / generated" />
          <button className="w-full mt-3 py-2.5 bg-orange text-black border border-orange rounded-sm font-mono text-xs font-bold uppercase tracking-wider cursor-pointer hover:bg-orange-bright hover:border-orange-bright">
            Maker: verify, sign &amp; broadcast
          </button>
        </>
      )}

      <div className="mt-auto pt-3 border-t border-border-soft grid grid-cols-2 gap-y-2 gap-x-3.5 text-[11px]">
        <PStat label="Carrier" value={form.carrier} />
        <PStat label="Custody" value="self · no escrow" />
        <PStat label="Settlement" value="on-chain · 1 tx" />
        <PStat label="Fee path" value="no protocol fee" />
        <PStat label="Net fee" value="12" suffix="sat/vB" />
        <PStat label="Mempool" value="14,213" suffix="tx" />
      </div>
    </div>
  );
}

function ModeBtn({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={
        on
          ? 'h-6 inline-flex items-center justify-center px-3 text-[11px] tracking-wider leading-none bg-orange text-black border border-orange rounded-sm cursor-pointer font-mono uppercase font-bold'
          : 'h-6 inline-flex items-center justify-center px-3 text-[11px] tracking-wider leading-none bg-panel text-fg border border-transparent rounded-sm cursor-pointer font-mono uppercase hover:bg-hover hover:text-fg-bright'
      }
    >{children}</button>
  );
}

function TabBtn({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={
        on
          ? 'flex-1 py-1.5 px-1 font-mono text-xs font-medium border-0 border-b-2 border-orange bg-transparent text-orange cursor-pointer uppercase tracking-wider'
          : 'flex-1 py-1.5 px-1 font-mono text-xs font-medium border-0 border-b-2 border-transparent bg-transparent text-muted cursor-pointer uppercase tracking-wider hover:text-fg-bright'
      }
    >{children}</button>
  );
}

function SideBtn({ on, side, onClick, children }: { on: boolean; side: 'sell' | 'buy'; onClick: () => void; children: React.ReactNode }) {
  const onColor = side === 'sell' ? 'bg-green text-black border-green' : 'bg-red text-black border-red';
  return (
    <button
      onClick={onClick}
      className={
        on
          ? `flex-1 h-[26px] inline-flex items-center justify-center px-2.5 font-mono text-xs font-bold border rounded-sm cursor-pointer uppercase tracking-wider ${onColor}`
          : 'flex-1 h-[26px] inline-flex items-center justify-center px-2.5 font-mono text-xs font-semibold bg-panel border border-transparent rounded-sm text-fg cursor-pointer uppercase tracking-wider hover:bg-hover hover:text-fg-bright'
      }
    >{children}</button>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <label className="block text-[10px] text-muted mt-2.5 mb-1 uppercase tracking-wider">{children}</label>;
}

function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className="w-full bg-bg text-fg border border-border rounded-sm px-2 py-1.5 font-mono text-xs focus:outline-none focus:border-orange" />;
}

function Select({ children, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className="w-full bg-bg text-fg border border-border rounded-sm px-2 py-1.5 font-mono text-xs focus:outline-none focus:border-orange">{children}</select>;
}

function PStat({ label, value, suffix }: { label: string; value: string; suffix?: string }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-muted uppercase tracking-wider text-[10px]">{label}</span>
      <span className="text-fg font-mono text-right">{value} {suffix && <span className="text-dim">{suffix}</span>}</span>
    </div>
  );
}
