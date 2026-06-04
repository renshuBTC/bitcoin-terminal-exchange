'use client';
/**
 * Wallet context — provides connect/disconnect + connected state to
 * the rest of the app. Today only the UniSat adapter is wired in;
 * Xverse / Leather / OKX adapters slot into the same context.
 *
 * Critical commitment: this provider NEVER holds private keys. It
 * only holds the connected address + pubkey + provider name. Signing
 * always round-trips through the user's wallet extension.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from 'react';
import type { ConnectedWallet } from '@/lib/wallet';
import {
  unisatBalanceSats,
  unisatInstalled,
  unisatRestore,
  unisatWallet,
} from '@/lib/wallets/unisat';
import { leatherInstalled, leatherWallet } from '@/lib/wallets/leather';
import { xverseInstalled, xverseWallet } from '@/lib/wallets/xverse';

interface WalletState {
  connected: ConnectedWallet | null;
  balanceSats: number | null;
  connecting: boolean;
  error: string | null;
  connect: (adapter?: 'unisat' | 'xverse' | 'leather') => Promise<void>;
  disconnect: () => Promise<void>;
}

const Ctx = createContext<WalletState | null>(null);

export function WalletProvider({ children }: { children: React.ReactNode }) {
  const [connected, setConnected] = useState<ConnectedWallet | null>(null);
  const [balanceSats, setBalanceSats] = useState<number | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Best-effort: restore on mount if UniSat already authorized this site.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const r = await unisatRestore();
      if (!cancelled && r) {
        setConnected(r);
        setBalanceSats(await unisatBalanceSats());
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const connect = useCallback(async (adapter: 'unisat' | 'xverse' | 'leather' = 'unisat') => {
    setConnecting(true);
    setError(null);
    try {
      if (adapter === 'xverse') {
        if (!xverseInstalled()) {
          throw new Error(
            'Xverse extension not installed. Install from https://www.xverse.app/ then refresh.',
          );
        }
        const w = await xverseWallet.connect();
        setConnected(w);
        setBalanceSats(null); // Xverse balance fetched server-side later
        return;
      }
      if (adapter === 'leather') {
        if (!leatherInstalled()) {
          throw new Error(
            'Leather extension not installed. Install from https://leather.io/ then refresh.',
          );
        }
        const w = await leatherWallet.connect();
        setConnected(w);
        setBalanceSats(null); // Leather balance fetched server-side later
        return;
      }
      // default: unisat
      if (!unisatInstalled()) {
        throw new Error(
          'UniSat extension not installed. Install from https://unisat.io/ then refresh.',
        );
      }
      const w = await unisatWallet.connect();
      setConnected(w);
      setBalanceSats(await unisatBalanceSats());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'connect failed');
      setConnected(null);
      setBalanceSats(null);
    } finally {
      setConnecting(false);
    }
  }, []);

  const disconnect = useCallback(async () => {
    await unisatWallet.disconnect();
    setConnected(null);
    setBalanceSats(null);
  }, []);

  return (
    <Ctx.Provider
      value={{ connected, balanceSats, connecting, error, connect, disconnect }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useWallet(): WalletState {
  const c = useContext(Ctx);
  if (!c) {
    // Safe fallback when used outside the provider — useful for SSR
    // and for testing components in isolation. Connect throws if called.
    return {
      connected: null,
      balanceSats: null,
      connecting: false,
      error: null,
      async connect(_adapter?: 'unisat' | 'xverse' | 'leather') {
        throw new Error('useWallet called outside WalletProvider');
      },
      async disconnect() {},
    };
  }
  return c;
}
