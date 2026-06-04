'use client';
/**
 * Wallet picker popover. Replaces the Connect button's hardcoded UniSat
 * call with a small dropdown listing detected wallets.
 *
 * Today UniSat is the only fully-wired adapter. Xverse / Leather /
 * OKX detect-only (we surface them so the user sees the roadmap),
 * with a "coming soon" affordance.
 *
 * Click-outside dismisses the popover; Escape dismisses too.
 */
import { useEffect, useRef, useState } from 'react';

import { EXPECTED_NETWORK } from '@/lib/network';
import { useWallet } from './WalletProvider';

interface WalletOption {
  id: 'unisat' | 'xverse' | 'leather' | 'okx';
  label: string;
  installed: boolean;
  installUrl: string;
  status: 'ready' | 'coming-soon';
}

function detect(): WalletOption[] {
  if (typeof window === 'undefined') {
    return [
      { id: 'unisat', label: 'UniSat', installed: false, installUrl: 'https://unisat.io/', status: 'ready' },
      { id: 'xverse', label: 'Xverse', installed: false, installUrl: 'https://www.xverse.app/', status: 'ready' },
      { id: 'leather', label: 'Leather', installed: false, installUrl: 'https://leather.io/', status: 'ready' },
      { id: 'okx', label: 'OKX Wallet', installed: false, installUrl: 'https://www.okx.com/web3', status: 'ready' },
    ];
  }
  const w = window as unknown as {
    unisat?: unknown;
    XverseProviders?: { BitcoinProvider?: unknown };
    LeatherProvider?: unknown;
    okxwallet?: { bitcoin?: unknown };
  };
  return [
    { id: 'unisat',  label: 'UniSat',     installed: !!w.unisat,                           installUrl: 'https://unisat.io/',         status: 'ready' },
    { id: 'xverse',  label: 'Xverse',     installed: !!w.XverseProviders?.BitcoinProvider, installUrl: 'https://www.xverse.app/',    status: 'ready' },
    { id: 'leather', label: 'Leather',    installed: !!w.LeatherProvider,                  installUrl: 'https://leather.io/',        status: 'ready' },
    { id: 'okx',     label: 'OKX Wallet', installed: !!w.okxwallet?.bitcoin,               installUrl: 'https://www.okx.com/web3',   status: 'ready' },
  ];
}

export function WalletPickerButton() {
  const { connected, connecting, error, connect, disconnect } = useWallet();
  const [open, setOpen] = useState(false);
  const popRef = useRef<HTMLDivElement>(null);
  const [opts, setOpts] = useState<WalletOption[]>(detect);

  useEffect(() => {
    setOpts(detect());
  }, [open]);

  // Click outside / Escape to dismiss.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (popRef.current && !popRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const connectLabel = (() => {
    if (connecting) return 'connecting…';
    if (connected) {
      const a = connected.address;
      return `${a.slice(0, 6)}…${a.slice(-4)}`;
    }
    return 'Connect';
  })();

  const onMainClick = async () => {
    if (connected) {
      await disconnect();
      return;
    }
    setOpen((o) => !o);
  };

  const onPick = async (opt: WalletOption) => {
    setOpen(false);
    if (!opt.installed) {
      window.open(opt.installUrl, '_blank', 'noopener');
      return;
    }
    if (
      opt.id === 'unisat' ||
      opt.id === 'xverse' ||
      opt.id === 'leather' ||
      opt.id === 'okx'
    ) {
      await connect(opt.id);
      return;
    }
  };

  // Network chip color: green when wallet matches the expected
  // network for this deployment; red when it doesn't. Hidden when
  // disconnected.
  const networkMismatch =
    !!connected && connected.network !== EXPECTED_NETWORK;
  const networkChipClass = !connected
    ? ''
    : networkMismatch
      ? 'ml-1.5 inline-block text-[9px] uppercase tracking-wider border border-red text-red rounded-sm px-1 leading-[14px]'
      : 'ml-1.5 inline-block text-[9px] uppercase tracking-wider border border-green text-green rounded-sm px-1 leading-[14px]';

  return (
    <div ref={popRef} className="relative inline-block">
      <button
        onClick={onMainClick}
        disabled={connecting}
        aria-label={
          connected
            ? `${connected.providerName} connected on ${connected.network} — click to disconnect`
            : 'Connect a Bitcoin wallet'
        }
        aria-expanded={open}
        aria-haspopup={connected ? undefined : 'menu'}
        title={
          connected
            ? `${connected.providerName} · ${connected.network} · click to disconnect`
            : 'Connect a Bitcoin wallet'
        }
        className={
          connected
            ? 'bg-hover text-fg-bright border border-line-strong rounded-sm h-7 px-3 font-mono text-xs font-bold uppercase tracking-wider leading-[26px] cursor-pointer hover:border-orange'
            : 'bg-orange text-black border border-orange rounded-sm h-7 px-4 font-mono text-xs font-bold uppercase tracking-wider leading-[26px] cursor-pointer hover:bg-orange-bright hover:border-orange-bright disabled:opacity-60 disabled:cursor-default'
        }
      >
        <span>{connectLabel}</span>
        {connected && (
          <span className={networkChipClass}>{connected.network}</span>
        )}
      </button>

      {open && !connected && (
        <div
          className="absolute right-0 mt-1.5 w-[240px] bg-menu border border-line-strong rounded-sm shadow-lg z-50 text-xs"
          role="menu"
        >
          <div className="px-3 py-2 border-b border-border-soft text-muted uppercase tracking-wider text-[10px]">
            Connect wallet
          </div>
          {opts.map((opt) => (
            <button
              key={opt.id}
              onClick={() => onPick(opt)}
              className="flex items-center justify-between w-full text-left px-3 py-2 font-mono hover:bg-hover cursor-pointer border-b border-border-soft last:border-0"
            >
              <span className="flex items-center gap-2">
                <span
                  className={`w-2 h-2 rounded-full ${
                    opt.installed
                      ? opt.status === 'ready'
                        ? 'bg-green'
                        : 'bg-orange'
                      : 'bg-dim'
                  }`}
                />
                <span className="text-fg-bright">{opt.label}</span>
              </span>
              <span
                className={`text-[10px] uppercase tracking-wider ${
                  opt.installed
                    ? opt.status === 'ready'
                      ? 'text-green'
                      : 'text-orange'
                    : 'text-dim'
                }`}
              >
                {opt.installed
                  ? opt.status === 'ready'
                    ? 'ready'
                    : 'coming soon'
                  : 'install ↗'}
              </span>
            </button>
          ))}
          {error && (
            <div className="px-3 py-2 text-red border-t border-border-soft">
              {error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
