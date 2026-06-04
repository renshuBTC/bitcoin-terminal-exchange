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
import { api, type Btx2FillDraft } from '@/lib/api';
import {
  appendAttestation,
  emitAttestationsChanged,
} from '@/lib/attestations';
import { EXPECTED_NETWORK } from '@/lib/network';
import { SelectedOrderDetail } from './SelectedOrderDetail';
import { useSelectedOrder } from './SelectedOrderProvider';
import { useWallet } from './WalletProvider';

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
  /** When set, the result strip shows a copy button that puts this on the clipboard. */
  copyable?: string;
}

/**
 * Lightweight validation for the Fill artifact input. We accept either
 *   (a) a hex string of at least 8 bytes (16 hex chars), OR
 *   (b) the sample-row placeholder we generate from OrderBook clicks
 *       (parens-wrapped, contains 'sample row').
 * Returns an error string when invalid, null when OK.
 */
function validateFillArtifact(s: string): string | null {
  const v = s.trim();
  if (v.length === 0) return 'paste an order artifact / id first';
  if (/sample row/i.test(v)) return null; // OrderBook sample placeholder
  // Real artifacts / order ids are hex.
  if (!/^[0-9a-fA-F]+$/.test(v)) {
    return 'not hex — expected an order id or BTX2 artifact in hex';
  }
  if (v.length < 16) {
    return `too short (${v.length} chars) — at least 16 hex chars`;
  }
  if (v.length % 2 !== 0) {
    return 'odd hex length — bytes must be 2 hex chars each';
  }
  return null;
}

export function TradePanel() {
  const { connected, connect, signMessage } = useWallet();
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

  // Auto-fetch the structural fill draft when the artifact input
  // looks like a 72-char hex order id. Lets the user preview what
  // their fill will commit to (offer outpoint, payout SPK, total
  // sats, sighash flag) before signing or building a PSBT.
  const [fillDraft, setFillDraft] = useState<Btx2FillDraft | null>(null);
  const [fillDraftErr, setFillDraftErr] = useState<string | null>(null);
  useEffect(() => {
    const v = fillArtifact.trim();
    setFillDraftErr(null);
    if (!/^[0-9a-fA-F]{72}$/.test(v)) {
      setFillDraft(null);
      return;
    }
    let cancelled = false;
    api
      .fillDraft(v)
      .then((d) => {
        if (cancelled) return;
        if (d === null) {
          setFillDraft(null);
          setFillDraftErr('order not in store or already terminal');
        } else {
          setFillDraft(d);
        }
      })
      .catch((e) => {
        if (cancelled) return;
        setFillDraft(null);
        setFillDraftErr(e instanceof Error ? e.message : 'fetch failed');
      });
    return () => {
      cancelled = true;
    };
  }, [fillArtifact]);

  const fill = async () => {
    setFillResult(null);
    if (connected && connected.network !== EXPECTED_NETWORK) {
      setFillResult({
        ok: false,
        text: `wallet network '${connected.network}' does not match deployment '${EXPECTED_NETWORK}'. Switch your wallet's network and retry.`,
      });
      return;
    }
    if (!connected) {
      try { await connect(); } catch (e) {
        setFillResult({ ok: false, text: e instanceof Error ? e.message : 'connect failed' });
        return;
      }
    }
    const vErr = validateFillArtifact(fillArtifact);
    if (vErr) {
      setFillResult({ ok: false, text: vErr });
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
      const signature = await signMessage(message, 'bip322');
      appendAttestation({
        kind: 'fill',
        provider: connected?.providerName ?? 'wallet',
        address: connected?.address ?? '',
        network: connected?.network ?? 'mainnet',
        signature,
        summary: `fill ← ${fillArtifact.trim().slice(0, 20)}…`,
      });
      emitAttestationsChanged();
      setFillResult({
        ok: true,
        text: `BIP-322 fill-commitment OK\nsignature: ${signature.slice(0, 24)}…${signature.slice(-12)}`,
        copyable: signature,
      });
    } catch (e) {
      setFillResult({ ok: false, text: e instanceof Error ? e.message : 'sign failed' });
    } finally {
      setFilling(false);
    }
  };

  const publish = async () => {
    setResult(null);
    if (connected && connected.network !== EXPECTED_NETWORK) {
      setResult({
        ok: false,
        text: `wallet network '${connected.network}' does not match deployment '${EXPECTED_NETWORK}'. Switch your wallet's network and retry.`,
      });
      return;
    }
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
      const signature = await signMessage(message, 'bip322');
      appendAttestation({
        kind: 'publish',
        provider: connected?.providerName ?? 'wallet',
        address: connected?.address ?? '',
        network: connected?.network ?? 'mainnet',
        signature,
        summary: `${side} ${form.amount} ${form.rune} @ ${form.priceBtc} BTC`,
      });
      emitAttestationsChanged();
      setResult({
        ok: true,
        text: `BIP-322 attestation OK\nsignature: ${signature.slice(0, 24)}…${signature.slice(-12)}`,
        copyable: signature,
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

      {connected && connected.network !== EXPECTED_NETWORK && (
        <NetworkMismatchBanner
          walletNetwork={connected.network}
          expected={EXPECTED_NETWORK}
        />
      )}

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
          {result && <ResultStrip state={result} />}
        </>
      )}

      {tab === 'fill' && (
        <>
          <SelectedOrderDetail />
          {fillDraft && <FillDraftPanel draft={fillDraft} />}
          {fillDraftErr && (
            <div className="text-[10px] text-red mt-1 mb-1 font-mono">
              · fill-draft: {fillDraftErr}
            </div>
          )}
          <Label>Order artifact / id (click a book row to load)</Label>
          <Input
            placeholder="BTX2 artifact hex or 36-byte order id"
            value={fillArtifact}
            onChange={(e) => setFillArtifact(e.target.value)}
          />
          {fillArtifact.trim().length > 0 &&
            (() => {
              const err = validateFillArtifact(fillArtifact);
              return err ? (
                <div className="text-[10px] text-red mt-1 font-mono">
                  · {err}
                </div>
              ) : (
                <div className="text-[10px] text-green mt-1 font-mono">
                  · OK · {fillArtifact.trim().length} chars
                </div>
              );
            })()}
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
          {fillResult && <ResultStrip state={fillResult} />}
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

/**
 * Structural fill-tx draft — what GET /api/v1/btx2/orders/{id}/fill_draft
 * gives the taker's wallet to assemble a signable PSBT. Rendered above
 * the artifact input when the input is a recognizable 72-char hex id.
 *
 * This is INFORMATIONAL — clicking Fill still runs the BIP-322
 * attestation flow (the protocol-level commitment). PSBT construction
 * lives in the wallet / a future broadcast step.
 */
function FillDraftPanel({ draft }: { draft: Btx2FillDraft }) {
  const sighashName =
    draft.sighash_flag_for_offer_input === 0x83
      ? 'SIGHASH_SINGLE|ACP'
      : `0x${draft.sighash_flag_for_offer_input.toString(16)}`;
  return (
    <div className="mt-2 mb-2 border border-border-soft rounded-sm bg-panel p-2 font-mono text-[11px]">
      <div className="flex justify-between items-baseline mb-1">
        <span className="text-[10px] uppercase tracking-wider text-muted">
          Fill draft · structural
        </span>
        <span className="text-[10px] text-dim normal-case tracking-normal">
          state: {draft.state}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
        <DraftRow label="Pay">
          <span className="text-fg-bright">
            {draft.total_sats.toLocaleString()} sats
          </span>
          <span className="text-dim">
            {' '}
            ({draft.amount.toLocaleString()} × {draft.price.toLocaleString()})
          </span>
        </DraftRow>
        <DraftRow label="Rune">
          <span className="text-fg-bright">
            {draft.rune_block}:{draft.rune_tx}
          </span>
        </DraftRow>
        <DraftRow label="Offer in">
          <span className="text-fg text-[10px] break-all">
            {draft.offer_input}
          </span>
        </DraftRow>
        <DraftRow label="Expiry">
          <span>{draft.expiry.toLocaleString()}</span>
        </DraftRow>
        <DraftRow label="Payout SPK">
          <span className="text-fg text-[10px] break-all">
            {draft.maker_payout_spk_hex.slice(0, 18)}…
          </span>
        </DraftRow>
        <DraftRow label="Sighash">
          <span className="text-orange">{sighashName}</span>
        </DraftRow>
      </div>
    </div>
  );
}

function DraftRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex justify-between items-baseline gap-2">
      <span className="text-[10px] uppercase tracking-wider text-muted shrink-0">
        {label}
      </span>
      <span className="text-right">{children}</span>
    </div>
  );
}

/**
 * Loud red banner shown above the Publish/Fill controls when the
 * connected wallet reports a network other than the one this btx-web
 * deployment is targeting. Publish + Fill are gated on the same
 * predicate — even if a user dismisses the banner mentally, the
 * sign call exits early with the same message.
 */
function NetworkMismatchBanner({
  walletNetwork,
  expected,
}: {
  walletNetwork: string;
  expected: string;
}) {
  return (
    <div className="text-[11px] mb-3 p-2 px-2.5 rounded-sm border border-red bg-[#1a0e0e] text-red font-mono leading-snug">
      <div className="font-bold uppercase tracking-wider text-[10px] mb-1">
        Network mismatch · sign disabled
      </div>
      <div className="break-all">
        Wallet reports <span className="text-fg-bright">{walletNetwork}</span>{' '}
        but this site is rendering{' '}
        <span className="text-fg-bright">{expected}</span> orders. Switch your
        wallet&rsquo;s network to {expected} (or load the {walletNetwork}{' '}
        deployment) before signing.
      </div>
    </div>
  );
}

/**
 * Coloured result strip with an inline copy button. The button uses
 * navigator.clipboard.writeText when available and falls back to
 * a hidden <textarea> + document.execCommand('copy') for older
 * browsers / non-HTTPS contexts where the Clipboard API is blocked.
 */
function ResultStrip({ state }: { state: ResultState }) {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    if (!state.copyable) return;
    try {
      await navigator.clipboard.writeText(state.copyable);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // Fallback for non-secure contexts.
      const ta = document.createElement('textarea');
      ta.value = state.copyable;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand('copy');
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
      } finally {
        document.body.removeChild(ta);
      }
    }
  };
  return (
    <div
      className={`text-[11px] mt-2.5 whitespace-pre-wrap break-all p-2 px-2.5 rounded-sm border font-mono ${
        state.ok
          ? 'text-green border-[#2c5e57] bg-[#0c1816]'
          : 'text-red border-[#5e2e34] bg-[#1a0e0e]'
      }`}
    >
      <div className="flex justify-between items-start gap-2">
        <div className="flex-1">{state.text}</div>
        {state.copyable && (
          <button
            onClick={onCopy}
            className="shrink-0 text-[10px] uppercase tracking-wider border border-current rounded-sm px-1.5 py-0.5 hover:bg-hover cursor-pointer"
          >
            {copied ? 'copied' : 'copy sig'}
          </button>
        )}
      </div>
    </div>
  );
}
