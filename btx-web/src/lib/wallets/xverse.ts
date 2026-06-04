/**
 * Xverse browser-extension wallet adapter.
 *
 * Xverse injects `window.XverseProviders.BitcoinProvider` when the
 * extension is installed. Unlike UniSat's direct method API, Xverse
 * uses a single `.request(method, params)` dispatch:
 *
 *   request('getAccounts', {purposes: ['payment','ordinals']})  → addresses
 *   request('getInfo')                                          → wallet info
 *   request('signMessage', {address, message})                  → signature
 *   request('signPsbt', {psbt, signInputs, broadcast})          → signed PSBT
 *
 * Implements the BitcoinWallet interface from ../wallet.ts.
 *
 * Note: the official Xverse path is the `sats-connect` npm package,
 * which provides nicer TypeScript types. We use the direct provider
 * here so we don't add an npm dep — works correctly with Xverse
 * versions that ship the BitcoinProvider interface (Q4 2024 onward).
 */
import type { BitcoinWallet, ConnectedWallet, Utxo } from '../wallet';

interface XverseAddress {
  address: string;
  publicKey: string;
  purpose: 'payment' | 'ordinals' | 'stacks';
  addressType: string;
}

interface XverseGetAccountsResult {
  addresses?: XverseAddress[];
  // Older Xverse versions returned the array directly.
}

type XverseProvider = {
  request(method: string, params?: unknown): Promise<{
    status: 'success' | 'error';
    result?: unknown;
    error?: { message?: string; code?: number };
  }>;
};

function getProvider(): XverseProvider | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as {
    XverseProviders?: { BitcoinProvider?: XverseProvider };
  };
  return w.XverseProviders?.BitcoinProvider ?? null;
}

export function xverseInstalled(): boolean {
  return getProvider() !== null;
}

let _connected: ConnectedWallet | null = null;

async function call<T = unknown>(
  p: XverseProvider,
  method: string,
  params?: unknown,
): Promise<T> {
  const res = await p.request(method, params);
  if (res.status !== 'success') {
    const msg = res.error?.message ?? `Xverse ${method} failed`;
    throw new Error(msg);
  }
  return res.result as T;
}

function pickPaymentAddress(addrs: XverseAddress[]): XverseAddress | null {
  // Prefer 'payment' (BTC) over 'ordinals' (taproot ord/runes).
  return (
    addrs.find((a) => a.purpose === 'payment') ??
    addrs.find((a) => a.purpose === 'ordinals') ??
    addrs[0] ??
    null
  );
}

export const xverseWallet: BitcoinWallet = {
  async connect(): Promise<ConnectedWallet> {
    const p = getProvider();
    if (!p) {
      throw new Error(
        'Xverse extension not installed. Visit https://www.xverse.app/ to install.',
      );
    }
    const result = await call<XverseGetAccountsResult | XverseAddress[]>(
      p,
      'getAccounts',
      { purposes: ['payment', 'ordinals'], message: 'BTX wants to read your addresses' },
    );
    const addrs: XverseAddress[] = Array.isArray(result)
      ? result
      : result.addresses ?? [];
    const pick = pickPaymentAddress(addrs);
    if (!pick) throw new Error('Xverse: no address returned');
    // Xverse doesn't advertise the network on every account; default to
    // mainnet and let the user switch in-wallet if they need a testnet.
    _connected = {
      address: pick.address,
      pubkey: pick.publicKey,
      network: 'mainnet',
      providerName: 'Xverse',
    };
    return _connected;
  },

  async disconnect(): Promise<void> {
    _connected = null;
  },

  isConnected(): boolean {
    return _connected !== null;
  },

  /**
   * Same placeholder as UniSat — Xverse doesn't expose UTXOs over the
   * direct provider API. UTXO fetching belongs server-side.
   */
  async getUtxos(): Promise<Utxo[]> {
    return [];
  },

  async signMessage(message: string): Promise<string> {
    const p = getProvider();
    if (!p) throw new Error('Xverse not available');
    if (!_connected) throw new Error('Xverse: connect() first');
    const result = await call<{ signature: string } | string>(p, 'signMessage', {
      address: _connected.address,
      message,
    });
    return typeof result === 'string' ? result : result.signature;
  },

  async signPsbt(
    psbtBase64: string,
    opts: { signInputs: number[]; finalize: boolean },
  ): Promise<string> {
    const p = getProvider();
    if (!p) throw new Error('Xverse not available');
    if (!_connected) throw new Error('Xverse: connect() first');
    const result = await call<{ psbt: string } | string>(p, 'signPsbt', {
      psbt: psbtBase64,
      signInputs: { [_connected.address]: opts.signInputs },
      broadcast: false,
    });
    const signedPsbt = typeof result === 'string' ? result : result.psbt;
    return signedPsbt; // base64; caller decides whether to finalize / broadcast
  },
};
