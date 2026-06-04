'use client';
/**
 * Wallet context — provides connect/disconnect/signMessage + connected
 * state to the rest of the app. Dispatches to whichever adapter is
 * actually connected (UniSat / Xverse / Leather / OKX).
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
  useRef,
  useState,
} from 'react';
import { api } from '@/lib/api';
import type { BitcoinWallet, ConnectedWallet } from '@/lib/wallet';
import {
  unisatBalanceSats,
  unisatInstalled,
  unisatRestore,
  unisatWallet,
} from '@/lib/wallets/unisat';
import { leatherInstalled, leatherWallet } from '@/lib/wallets/leather';
import { okxInstalled, okxWallet } from '@/lib/wallets/okx';
import { xverseInstalled, xverseWallet } from '@/lib/wallets/xverse';

type AdapterId = 'unisat' | 'xverse' | 'leather' | 'okx';

const ADAPTERS: Record<AdapterId, BitcoinWallet> = {
  unisat: unisatWallet,
  xverse: xverseWallet,
  leather: leatherWallet,
  okx: okxWallet,
};

interface WalletState {
  connected: ConnectedWallet | null;
  balanceSats: number | null;
  connecting: boolean;
  error: string | null;
  connect: (adapter?: AdapterId) => Promise<void>;
  disconnect: () => Promise<void>;
  /**
   * Sign a UTF-8 message using whichever adapter is currently
   * connected. Throws when no adapter is connected.
   *
   * Per the BTX maker-attestation flow this defaults to BIP-322;
   * callers can pass 'ecdsa' for the legacy path if needed.
   */
  signMessage: (message: string, type?: 'bip322' | 'ecdsa') => Promise<string>;
  /**
   * Sign a base64-encoded PSBT using whichever adapter is currently
   * connected. Throws when no adapter is connected. `opts.signInputs`
   * is the array of input indexes the connected wallet should sign;
   * `opts.finalize` asks the wallet to also finalize after signing
   * (most wallets return base64 either way).
   *
   * Reserved for the future broadcast flow — no UI calls this yet.
   * Implemented now so that whenever a PSBT signing surface lands,
   * it inherits the dispatch correctly (avoids the signMessage
   * unisat-hardcode bug we just fixed).
   */
  signPsbt: (
    psbtBase64: string,
    opts: { signInputs: number[]; finalize: boolean },
  ) => Promise<string>;
}

const Ctx = createContext<WalletState | null>(null);

export function WalletProvider({ children }: { children: React.ReactNode }) {
  const [connected, setConnected] = useState<ConnectedWallet | null>(null);
  const [balanceSats, setBalanceSats] = useState<number | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Tracks which adapter is currently authoritative. A ref (not state)
  // so the signMessage callback identity doesn't change when the user
  // reconnects to a different wallet — TradePanel keeps a stable
  // reference.
  const activeAdapterRef = useRef<AdapterId | null>(null);

  // Best-effort: restore on mount if UniSat already authorized this site.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const r = await unisatRestore();
      if (!cancelled && r) {
        setConnected(r);
        activeAdapterRef.current = 'unisat';
        setBalanceSats(await unisatBalanceSats());
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const connect = useCallback(async (adapter: AdapterId = 'unisat') => {
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
        activeAdapterRef.current = 'xverse';
        setBalanceSats(await api.addressBalanceSats(w.address));
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
        activeAdapterRef.current = 'leather';
        setBalanceSats(await api.addressBalanceSats(w.address));
        return;
      }
      if (adapter === 'okx') {
        if (!okxInstalled()) {
          throw new Error(
            'OKX Wallet extension not installed. Install from https://www.okx.com/web3 then refresh.',
          );
        }
        const w = await okxWallet.connect();
        setConnected(w);
        activeAdapterRef.current = 'okx';
        setBalanceSats(await api.addressBalanceSats(w.address));
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
      activeAdapterRef.current = 'unisat';
      setBalanceSats(await unisatBalanceSats());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'connect failed');
      setConnected(null);
      activeAdapterRef.current = null;
      setBalanceSats(null);
    } finally {
      setConnecting(false);
    }
  }, []);

  const disconnect = useCallback(async () => {
    const id = activeAdapterRef.current;
    if (id) {
      try {
        await ADAPTERS[id].disconnect();
      } catch {
        // Disconnect from the wallet extension can throw on some
        // versions (or with a stale provider). We still want to clear
        // local UI state regardless.
      }
    }
    activeAdapterRef.current = null;
    setConnected(null);
    setBalanceSats(null);
  }, []);

  const signMessage = useCallback(
    async (message: string, type: 'bip322' | 'ecdsa' = 'bip322'): Promise<string> => {
      const id = activeAdapterRef.current;
      if (!id) {
        throw new Error('No wallet connected. Click Connect first.');
      }
      // The BitcoinWallet interface declares `type?` so this is safe;
      // every adapter currently defaults to BIP-322 internally too.
      return ADAPTERS[id].signMessage(message, type);
    },
    [],
  );

  const signPsbt = useCallback(
    async (
      psbtBase64: string,
      opts: { signInputs: number[]; finalize: boolean },
    ): Promise<string> => {
      const id = activeAdapterRef.current;
      if (!id) {
        throw new Error('No wallet connected. Click Connect first.');
      }
      return ADAPTERS[id].signPsbt(psbtBase64, opts);
    },
    [],
  );

  return (
    <Ctx.Provider
      value={{
        connected,
        balanceSats,
        connecting,
        error,
        connect,
        disconnect,
        signMessage,
        signPsbt,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useWallet(): WalletState {
  const c = useContext(Ctx);
  if (!c) {
    // Safe fallback when used outside the provider — useful for SSR
    // and for testing components in isolation. Connect / signMessage
    // throw if called.
    return {
      connected: null,
      balanceSats: null,
      connecting: false,
      error: null,
      async connect(_adapter?: AdapterId) {
        throw new Error('useWallet called outside WalletProvider');
      },
      async disconnect() {},
      async signMessage() {
        throw new Error('useWallet called outside WalletProvider');
      },
      async signPsbt() {
        throw new Error('useWallet called outside WalletProvider');
      },
    };
  }
  return c;
}
