/**
 * Leather browser-extension wallet adapter.
 *
 * Leather injects `window.LeatherProvider` when installed. The API
 * mirrors Xverse's request-dispatch shape but returns a JSON-RPC-ish
 * envelope:
 *
 *   request('getAddresses')                           → { result: { addresses: [...] } }
 *   request('signMessage', { message, paymentType })  → { result: { signature, address } }
 *   request('signPsbt',    { hex, signAtIndex, broadcast }) → { result: { hex } }
 *
 * The address list returns one entry per supported chain
 * (BTC + STX). We pick the first BTC entry. Address `type` values
 * we accept: 'p2wpkh', 'p2tr', 'p2sh-p2wpkh' — pubkey is on the same
 * object.
 *
 * Implements the BitcoinWallet interface from ../wallet.ts.
 */
import type { BitcoinWallet, ConnectedWallet, Utxo } from '../wallet';

interface LeatherAddress {
  symbol: 'BTC' | 'STX' | string;
  type?: string;
  address: string;
  publicKey?: string;
  derivationPath?: string;
}

type LeatherEnvelope<T> = {
  jsonrpc?: string;
  id?: string;
  result?: T;
  error?: { message?: string; code?: number };
};

type LeatherProvider = {
  request<T = unknown>(method: string, params?: unknown): Promise<LeatherEnvelope<T>>;
};

function getProvider(): LeatherProvider | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as { LeatherProvider?: LeatherProvider };
  return w.LeatherProvider ?? null;
}

export function leatherInstalled(): boolean {
  return getProvider() !== null;
}

let _connected: ConnectedWallet | null = null;

async function call<T>(
  p: LeatherProvider,
  method: string,
  params?: unknown,
): Promise<T> {
  const env = await p.request<T>(method, params);
  if (env.error) {
    throw new Error(env.error.message ?? `Leather ${method} failed`);
  }
  if (env.result === undefined) {
    throw new Error(`Leather ${method}: empty result`);
  }
  return env.result;
}

function pickBtcAddress(addrs: LeatherAddress[]): LeatherAddress | null {
  // Prefer SegWit (p2wpkh) over Taproot (p2tr) over legacy.
  const btc = addrs.filter((a) => a.symbol === 'BTC');
  return (
    btc.find((a) => a.type === 'p2wpkh') ??
    btc.find((a) => a.type === 'p2tr') ??
    btc[0] ??
    null
  );
}

export const leatherWallet: BitcoinWallet = {
  async connect(): Promise<ConnectedWallet> {
    const p = getProvider();
    if (!p) {
      throw new Error(
        'Leather extension not installed. Visit https://leather.io/ to install.',
      );
    }
    const result = await call<{ addresses: LeatherAddress[] } | LeatherAddress[]>(
      p,
      'getAddresses',
    );
    const addrs: LeatherAddress[] = Array.isArray(result)
      ? result
      : result.addresses ?? [];
    const pick = pickBtcAddress(addrs);
    if (!pick) throw new Error('Leather: no BTC address returned');
    _connected = {
      address: pick.address,
      pubkey: pick.publicKey ?? '',
      network: 'mainnet',
      providerName: 'Leather',
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
   * Leather doesn't expose UTXOs through the page provider; the
   * indexer or a public Esplora-style endpoint owns that view.
   */
  async getUtxos(): Promise<Utxo[]> {
    return [];
  },

  async signMessage(message: string): Promise<string> {
    const p = getProvider();
    if (!p) throw new Error('Leather not available');
    if (!_connected) throw new Error('Leather: connect() first');
    const result = await call<{ signature: string; address?: string }>(
      p,
      'signMessage',
      { message, paymentType: 'p2wpkh' },
    );
    return result.signature;
  },

  async signPsbt(
    psbtBase64: string,
    opts: { signInputs: number[]; finalize: boolean },
  ): Promise<string> {
    const p = getProvider();
    if (!p) throw new Error('Leather not available');
    if (!_connected) throw new Error('Leather: connect() first');
    // Leather's signPsbt takes a hex string, not base64. Caller passes
    // base64 to satisfy the interface; convert here.
    const hex = base64ToHex(psbtBase64);
    const result = await call<{ hex: string }>(p, 'signPsbt', {
      hex,
      signAtIndex: opts.signInputs,
      broadcast: false,
    });
    return hexToBase64(result.hex); // hand back base64 to match the interface
  },
};

function base64ToHex(b64: string): string {
  // Browser-safe: atob → byte string → hex.
  const bin = atob(b64);
  let out = '';
  for (let i = 0; i < bin.length; i++) {
    out += bin.charCodeAt(i).toString(16).padStart(2, '0');
  }
  return out;
}

function hexToBase64(hex: string): string {
  let bin = '';
  for (let i = 0; i < hex.length; i += 2) {
    bin += String.fromCharCode(parseInt(hex.slice(i, i + 2), 16));
  }
  return btoa(bin);
}
