/**
 * UniSat browser-extension wallet adapter.
 *
 * UniSat injects `window.unisat` when the extension is installed.
 * Documented API surface used here:
 *   requestAccounts()                  -> string[]    (addresses)
 *   getAccounts()                      -> string[]    (already-connected addrs)
 *   getPublicKey()                     -> string      (33-byte hex)
 *   getNetwork()                       -> 'livenet' | 'testnet' | 'signet'
 *   switchNetwork(net)                 -> void
 *   signPsbt(psbtHex, opts)            -> string      (signed PSBT hex)
 *   on('accountsChanged', handler)     -> subscribe
 *   getBalance()                       -> {confirmed, unconfirmed, total}
 *
 * Implements the BitcoinWallet interface from ../wallet.ts. The PSBT
 * signing here returns hex; callers should convert to base64 (or use
 * UniSat's own `pushPsbt` for the broadcast step if they prefer the
 * wallet to broadcast, though for BTX we always broadcast through
 * /api/v1/btx2/broadcast so the chain layer is Bitcoin, not UniSat).
 */
import type { BitcoinWallet, ConnectedWallet, Utxo } from '../wallet';

// Minimal type for the injected window.unisat. Avoids pulling a full
// type package in; we only use what we actually call.
type UniSatProvider = {
  requestAccounts(): Promise<string[]>;
  getAccounts(): Promise<string[]>;
  getPublicKey(): Promise<string>;
  getNetwork(): Promise<'livenet' | 'testnet' | 'signet'>;
  switchNetwork(network: 'livenet' | 'testnet' | 'signet'): Promise<void>;
  getBalance(): Promise<{ confirmed: number; unconfirmed: number; total: number }>;
  signMessage(
    message: string,
    type?: 'ecdsa' | 'bip322-simple',
  ): Promise<string>;
  signPsbt(
    psbtHex: string,
    options?: {
      autoFinalized?: boolean;
      toSignInputs?: Array<{
        index: number;
        address?: string;
        publicKey?: string;
        sighashTypes?: number[];
        disableTweakSigner?: boolean;
      }>;
    },
  ): Promise<string>;
  on(event: 'accountsChanged', handler: (accounts: string[]) => void): void;
  removeListener(
    event: 'accountsChanged',
    handler: (accounts: string[]) => void,
  ): void;
};

function getProvider(): UniSatProvider | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as { unisat?: UniSatProvider };
  return w.unisat ?? null;
}

export function unisatInstalled(): boolean {
  return getProvider() !== null;
}

function mapNetwork(
  n: 'livenet' | 'testnet' | 'signet',
): 'mainnet' | 'testnet' | 'signet' {
  return n === 'livenet' ? 'mainnet' : n;
}

let _connected: ConnectedWallet | null = null;

export const unisatWallet: BitcoinWallet = {
  async connect(): Promise<ConnectedWallet> {
    const p = getProvider();
    if (!p) {
      throw new Error(
        'UniSat extension not installed. Visit https://unisat.io/ to install.',
      );
    }
    const accounts = await p.requestAccounts();
    if (!accounts.length) throw new Error('UniSat: no account returned');
    const [address] = accounts;
    const pubkey = await p.getPublicKey();
    const network = mapNetwork(await p.getNetwork());
    _connected = {
      address,
      pubkey,
      network,
      providerName: 'UniSat',
    };
    return _connected;
  },

  async disconnect(): Promise<void> {
    // UniSat has no programmatic disconnect; we drop our cached state.
    _connected = null;
  },

  isConnected(): boolean {
    return _connected !== null;
  },

  /**
   * UniSat doesn't expose a UTXO list directly via the extension API.
   * For BTX's purposes we'll fetch UTXOs server-side from an Esplora
   * mirror or the user's own Bitcoin node — this method is a placeholder
   * for that flow. Today it returns an empty list rather than throwing,
   * so the UI can render "no spendable coins" instead of an error spike.
   */
  async getUtxos(): Promise<Utxo[]> {
    return [];
  },

  async signMessage(message: string, type: 'bip322' | 'ecdsa' = 'bip322'): Promise<string> {
    const p = getProvider();
    if (!p) throw new Error('UniSat not available');
    // UniSat's signature type literal is 'bip322-simple' for BIP-322.
    const t = type === 'bip322' ? 'bip322-simple' : 'ecdsa';
    return p.signMessage(message, t);
  },

  async signPsbt(
    psbtBase64: string,
    opts: { signInputs: number[]; finalize: boolean },
  ): Promise<string> {
    const p = getProvider();
    if (!p) throw new Error('UniSat not available');
    const psbtHex = base64ToHex(psbtBase64);
    const signed = await p.signPsbt(psbtHex, {
      autoFinalized: opts.finalize,
      toSignInputs: opts.signInputs.map((index) => ({ index })),
    });
    return signed; // hex; caller converts to base64 if needed
  },
};

function base64ToHex(b64: string): string {
  if (typeof window === 'undefined') return b64;
  const bin = window.atob(b64);
  let h = '';
  for (let i = 0; i < bin.length; i++) {
    h += bin.charCodeAt(i).toString(16).padStart(2, '0');
  }
  return h;
}

/**
 * Best-effort: returns the currently-connected wallet without prompting.
 * Useful on page mount to restore the pubkey if UniSat is already
 * authorized for this site.
 */
export async function unisatRestore(): Promise<ConnectedWallet | null> {
  const p = getProvider();
  if (!p) return null;
  try {
    const accounts = await p.getAccounts();
    if (!accounts.length) return null;
    const pubkey = await p.getPublicKey();
    const network = mapNetwork(await p.getNetwork());
    _connected = {
      address: accounts[0],
      pubkey,
      network,
      providerName: 'UniSat',
    };
    return _connected;
  } catch {
    return null;
  }
}

/** Confirmed BTC balance in satoshis. Returns null if not connected. */
export async function unisatBalanceSats(): Promise<number | null> {
  const p = getProvider();
  if (!p || !_connected) return null;
  try {
    const b = await p.getBalance();
    return b.confirmed;
  } catch {
    return null;
  }
}
