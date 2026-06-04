'use client';
/**
 * Top navigation bar. Hooks into WalletProvider so the Connect button
 * actually opens the wallet, and so we display the short address +
 * provider name after connecting.
 */
import { useWallet } from './WalletProvider';

interface TopNavProps {
  oracleStatus?: 'ok' | 'warn' | 'bad';
  syncStatus?: 'ok' | 'warn' | 'bad';
  oracleText?: string;
  syncText?: string;
}

export function TopNav({
  oracleStatus = 'warn',
  syncStatus = 'warn',
  oracleText = 'oracle · preview',
  syncText = 'sync 100%',
}: TopNavProps) {
  const { connected, connecting, error, connect, disconnect } = useWallet();

  const pillClass = (s: 'ok' | 'warn' | 'bad') => {
    const base =
      'inline-flex items-center bg-hover text-fg border h-7 px-2.5 rounded-sm text-[11px] uppercase tracking-wider leading-[26px]';
    if (s === 'ok') return `${base} border-[#2c5e57] text-green`;
    if (s === 'warn') return `${base} border-[#7a4b13] text-orange`;
    return `${base} border-[#5e2e34] text-red`;
  };

  const connectLabel = (() => {
    if (connecting) return 'connecting…';
    if (connected) {
      const a = connected.address;
      return `${a.slice(0, 6)}…${a.slice(-4)}`;
    }
    return 'Connect';
  })();

  const handleClick = async () => {
    if (connected) {
      await disconnect();
    } else {
      await connect();
    }
  };

  return (
    <div className="flex items-center gap-2 px-3 py-2 bg-bg border-b border-border flex-wrap">
      <span className="flex items-center gap-2 text-fg-bright uppercase tracking-wider px-2.5 py-0 text-[15px] font-display font-bold">
        <span className="inline-block w-[18px] h-[18px] rounded-sm bg-gradient-to-br from-orange to-orange-bright" />
        BT<span className="text-orange font-bold">X</span>
      </span>
      <div className="flex gap-[2px] ml-1.5">
        <a
          href="#"
          className="text-fg px-2.5 py-1.5 text-xs rounded-sm uppercase tracking-wider bg-hover text-fg-bright no-underline hover:no-underline"
        >
          Trade
        </a>
        <a
          href="https://github.com/renshuBTC"
          target="_blank"
          rel="noreferrer"
          className="text-fg px-2.5 py-1.5 text-xs rounded-sm uppercase tracking-wider hover:bg-hover hover:text-fg-bright no-underline hover:no-underline"
        >
          Docs
        </a>
      </div>
      <div className="ml-auto flex items-center gap-1.5">
        {error && (
          <span
            className={pillClass('bad')}
            title={error}
          >
            wallet error
          </span>
        )}
        <span className={pillClass(oracleStatus)}>{oracleText}</span>
        <span className={pillClass(syncStatus)}>{syncText}</span>
        <button
          onClick={handleClick}
          disabled={connecting}
          title={
            connected
              ? `${connected.providerName} · ${connected.network} · click to disconnect`
              : 'Connect a Bitcoin wallet (UniSat supported)'
          }
          className={
            connected
              ? 'bg-hover text-fg-bright border border-line-strong rounded-sm h-7 px-3 font-mono text-xs font-bold uppercase tracking-wider leading-[26px] cursor-pointer hover:border-orange'
              : 'bg-orange text-black border border-orange rounded-sm h-7 px-4 font-mono text-xs font-bold uppercase tracking-wider leading-[26px] cursor-pointer hover:bg-orange-bright hover:border-orange-bright disabled:opacity-60 disabled:cursor-default'
          }
        >
          {connectLabel}
        </button>
      </div>
    </div>
  );
}
