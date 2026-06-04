/**
 * OKX Wallet browser-extension adapter (Bitcoin namespace).
 *
 * OKX injects `window.okxwallet.bitcoin` when the OKX extension is
 * installed. The API is direct-method (not a dispatch wrapper),
 * matching UniSat's style more than Xverse's:
 *
 *   bitcoin.connect()                     → { address, publicKey, compressedPublicKey }
 *   bitcoin.getAccounts()                 → string[]
 *   bitcoin.signMessage(msg, type?)       → string  (type: 'ecdsa' | 'bip322-simple')
 *   bitcoin.signPsbt(psbtHex, options)    → string  (signed PSBT hex)
 *   bitcoin.getNetwork()                  → 'livenet' | 'testnet'
 *
 * Implements the BitcoinWallet interface from ../wallet.ts.
 */
import type { BitcoinWallet, ConnectedWallet, Utxo } from '../wallet';

type OkxConnectResult = {
  address: string;
  publicKey: string;
  compressedPublicKey?: string;
};

type OkxBitcoinProvider = {
  connect(): Promise<OkxConnectResult>;
  disconnect?(): Promise<void>;
  getAccounts(): Promise<string[]>;
  getNetwork(): Promise<'livenet' | 'testnet' | string>;
  signMessage(
    msg: string,
    type?: 'ecdsa' | 'bip322-simple',
  ): Promise<string>;
  signPsbt(psbtHex: string, options?: unknown): Promise<string>;
};

function getProvider(): OkxBitcoinProvider | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as {
    okxwallet?: { bitcoin?: OkxBitcoinProvider };
  };
  return w.okxwallet?.bitcoin ?? null;
}

export function okxInstalled(): boolean {
  return getProvider() !== null;
}

let _connected: ConnectedWallet | null = null;

export const okxWallet: BitcoinWallet = {
  async connect(): Promise<ConnectedWallet> {
    const p = getProvider();
    if (!p) {
      throw new Error(
        'OKX Wallet extension not installed. Visit https://www.okx.com/web3 to install.',
      );
    }
    const result = await p.connect();
    let network: 'mainnet' | 'testnet' | 'signet' | 'regtest' = 'mainnet';
    try {
      const n = await p.getNetwork();
      if (n === 'testnet') network = 'testnet';
      // OKX doesn't expose signet/regtest distinctly; livenet/testnet only.
    } catch {
      // fall through; default to mainnet
    }
    _connected = {
      address: result.address,
      pubkey: result.compressedPublicKey ?? result.publicKey,
      network,
      providerName: 'OKX',
    };
    return _connected;
  },

  async disconnect(): Promise<void> {
    const p = getProvider();
    if (p?.disconnect) {
      try {
        await p.disconnect();
      } catch {
        // some OKX versions don't implement disconnect; ignore
      }
    }
    _connected = null;
  },

  isConnected(): boolean {
    return _connected !== null;
  },

  /**
   * Same placeholder as the other adapters — UTXO discovery belongs
   * server-side in BTX's design (indexer ↔ wallet via /api).
   */
  async getUtxos(): Promise<Utxo[]> {
    return [];
  },

  async signMessage(message: string): Promise<string> {
    const p = getProvider();
    if (!p) throw new Error('OKX not available');
    if (!_connected) throw new Error('OKX: connect() first');
    // BIP-322-simple is what the publish / fill attestations need
    // (matches the UniSat path), so default to that.
    return p.signMessage(message, 'bip322-simple');
  },

  async signPsbt(
    psbtBase64: string,
    opts: { signInputs: number[]; finalize: boolean },
  ): Promise<string> {
    const p = getProvider();
    if (!p) throw new Error('OKX not available');
    if (!_connected) throw new Error('OKX: connect() first');
    const hex = base64ToHex(psbtBase64);
    const signedHex = await p.signPsbt(hex, {
      autoFinalized: opts.finalize,
      toSignInputs: opts.signInputs.map((idx) => ({
        index: idx,
        address: _connected!.address,
      })),
    });
    return hexToBase64(signedHex);
  },
};

function base64ToHex(b64: string): string {
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
