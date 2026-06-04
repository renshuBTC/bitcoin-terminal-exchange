'use client';
/**
 * Trade panel — Open/Addressed mode toggle, Publish/Fill/OTC tabs,
 * Sell/Buy stablecoin toggle, full publish form, pstats footer.
 * Matches btx_trade.html's trade panel card (lines 408–470).
 */
import { useState } from 'react';

type Mode = 'open' | 'addressed';
type Tab = 'publish' | 'fill' | 'otc';
type Side = 'sell' | 'buy';

export function TradePanel() {
  const [mode, setMode] = useState<Mode>('open');
  const [tab, setTab] = useState<Tab>('publish');
  const [side, setSide] = useState<Side>('sell');

  return (
    <div className="bg-bg p-3.5 flex flex-col">
      <div className="inline-flex gap-px bg-panel p-0.5 border border-line-strong rounded-sm h-[30px] mb-3 self-start">
        <ModeBtn on={mode === 'open'} onClick={() => setMode('open')}>
          Open · 0x83
        </ModeBtn>
        <ModeBtn
          on={mode === 'addressed'}
          onClick={() => setMode('addressed')}
        >
          Addressed · PSBT
        </ModeBtn>
      </div>

      <div className="flex gap-0 mb-3 border-b border-border">
        <Tab on={tab === 'publish'} onClick={() => setTab('publish')}>
          Publish
        </Tab>
        <Tab on={tab === 'fill'} onClick={() => setTab('fill')}>
          Fill
        </Tab>
        <Tab on={tab === 'otc'} onClick={() => setTab('otc')}>
          OTC
        </Tab>
      </div>

      {tab === 'publish' && (
        <>
          <div className="inline-flex gap-px bg-panel p-0.5 border border-line-strong rounded-sm h-8 mb-3 w-full">
            <SideBtn
              on={side === 'sell'}
              side="sell"
              onClick={() => setSide('sell')}
            >
              Sell stablecoin
            </SideBtn>
            <SideBtn
              on={side === 'buy'}
              side="buy"
              onClick={() => setSide('buy')}
            >
              Buy stablecoin
            </SideBtn>
          </div>
          <Label>Offer UTXO (P2WPKH coin)</Label>
          <Select>
            <option>— refresh wallet —</option>
          </Select>
          <Label>Price (BTC taker pays)</Label>
          <Input defaultValue="0.001" />
          <Label>Stablecoin</Label>
          <Select>
            <option>USDh · BTC-backed</option>
            <option>Ducat · BTC-backed</option>
          </Select>
          <Label>Stablecoin amount (base units)</Label>
          <Input defaultValue="1000" />
          <Label>Carrier</Label>
          <Select>
            <option>OP_RETURN</option>
            <option>Taproot envelope</option>
          </Select>
          <button className="w-full mt-3 py-2.5 bg-orange text-black border border-orange rounded-sm font-mono text-xs font-bold uppercase tracking-wider cursor-pointer hover:bg-orange-bright hover:border-orange-bright">
            Maker-sign &amp; publish
          </button>
          <div className="text-[11px] text-muted leading-relaxed mt-2.5">
            self-custody · signs via your Bitcoin Core wallet · settles
            on-chain
          </div>
        </>
      )}

      {tab === 'fill' && (
        <>
          <Label>Order artifact (click a book row to load)</Label>
          <Input placeholder="BTX2 artifact hex" />
          <button className="w-full mt-3 py-2.5 bg-orange text-black border border-orange rounded-sm font-mono text-xs font-bold uppercase tracking-wider cursor-pointer hover:bg-orange-bright hover:border-orange-bright">
            Fill — build &amp; broadcast swap
          </button>
          <div className="text-[11px] text-muted leading-relaxed mt-2.5">
            taker funds + signs; the maker&rsquo;s pre-sig is dropped in;
            rune routes to your output.
          </div>
        </>
      )}

      {tab === 'otc' && (
        <>
          <div className="text-[11px] text-muted leading-relaxed mb-2">
            Snipe-resistant addressed swap (BIP-174 PSBT, 2 parties).
            Taker proposes → maker verifies output 0 &amp; countersigns
            SIGHASH_ALL. No relay.
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
        <PStat label="Carrier" value="OP_RETURN" />
        <PStat label="Custody" value="self · no escrow" />
        <PStat label="Settlement" value="on-chain · 1 tx" />
        <PStat label="Fee path" value="no protocol fee" />
        <PStat label="Net fee" value="12" suffix="sat/vB" />
        <PStat label="Mempool" value="14,213" suffix="tx" />
      </div>
    </div>
  );
}

function ModeBtn({
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
      onClick={onClick}
      className={
        on
          ? 'h-6 inline-flex items-center justify-center px-3 text-[11px] tracking-wider leading-none bg-orange text-black border border-orange rounded-sm cursor-pointer font-mono uppercase font-bold'
          : 'h-6 inline-flex items-center justify-center px-3 text-[11px] tracking-wider leading-none bg-panel text-fg border border-transparent rounded-sm cursor-pointer font-mono uppercase hover:bg-hover hover:text-fg-bright'
      }
    >
      {children}
    </button>
  );
}

function Tab({
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
      onClick={onClick}
      className={
        on
          ? 'flex-1 py-1.5 px-1 font-mono text-xs font-medium border-0 border-b-2 border-orange bg-transparent text-orange cursor-pointer uppercase tracking-wider'
          : 'flex-1 py-1.5 px-1 font-mono text-xs font-medium border-0 border-b-2 border-transparent bg-transparent text-muted cursor-pointer uppercase tracking-wider hover:text-fg-bright'
      }
    >
      {children}
    </button>
  );
}

function SideBtn({
  on,
  side,
  onClick,
  children,
}: {
  on: boolean;
  side: 'sell' | 'buy';
  onClick: () => void;
  children: React.ReactNode;
}) {
  const onColor =
    side === 'sell'
      ? 'bg-green text-black border-green'
      : 'bg-red text-black border-red';
  return (
    <button
      onClick={onClick}
      className={
        on
          ? `flex-1 h-[26px] inline-flex items-center justify-center px-2.5 font-mono text-xs font-bold border rounded-sm cursor-pointer uppercase tracking-wider ${onColor}`
          : 'flex-1 h-[26px] inline-flex items-center justify-center px-2.5 font-mono text-xs font-semibold bg-panel border border-transparent rounded-sm text-fg cursor-pointer uppercase tracking-wider hover:bg-hover hover:text-fg-bright'
      }
    >
      {children}
    </button>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <label className="block text-[10px] text-muted mt-2.5 mb-1 uppercase tracking-wider">
      {children}
    </label>
  );
}

function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className="w-full bg-bg text-fg border border-border rounded-sm px-2 py-1.5 font-mono text-xs focus:outline-none focus:border-orange"
    />
  );
}

function Select({ children }: { children: React.ReactNode }) {
  return (
    <select className="w-full bg-bg text-fg border border-border rounded-sm px-2 py-1.5 font-mono text-xs focus:outline-none focus:border-orange">
      {children}
    </select>
  );
}

function PStat({
  label,
  value,
  suffix,
}: {
  label: string;
  value: string;
  suffix?: string;
}) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-muted uppercase tracking-wider text-[10px]">
        {label}
      </span>
      <span className="text-fg font-mono text-right">
        {value} {suffix && <span className="text-dim">{suffix}</span>}
      </span>
    </div>
  );
}
