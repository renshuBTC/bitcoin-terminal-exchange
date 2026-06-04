/**
 * Bitcoin wallet adapter interface.
 *
 * Normalizes UniSat / Xverse / Leather / OKX browser-extension APIs.
 * Per build-plan §5: the wallet holds all keys; the website only asks
 * the wallet to sign, never receives or stores keys.
 */

export interface ConnectedWallet {
  address: string;
  pubkey: string;
  network: 'mainnet' | 'signet' | 'testnet';
  providerName: string;
}

export interface Utxo {
  txid: string;
  vout: number;
  value: number;
  scriptPubKey: string;
  confirmations: number;
}

export interface BitcoinWallet {
  connect(): Promise<ConnectedWallet>;
  disconnect(): Promise<void>;
  isConnected(): boolean;
  getUtxos(opts?: { minConfirmations?: number }): Promise<Utxo[]>;
  signPsbt(
    psbtBase64: string,
    opts: { signInputs: number[]; finalize: boolean },
  ): Promise<string>;
  /**
   * Sign a UTF-8 message using BIP-322 (the modern Bitcoin message
   * signing standard). Used for BTX maker attestation when a maker
   * wants to prove control of a pubkey without an on-chain spend.
   */
  signMessage(
    message: string,
    type?: 'bip322' | 'ecdsa',
  ): Promise<string>;
}

export const noWallet: BitcoinWallet = {
  async connect() {
    throw new Error(
      'No wallet adapter available. Install UniSat, Xverse, Leather, or OKX Wallet.',
    );
  },
  async disconnect() {},
  isConnected() { return false; },
  async getUtxos() { return []; },
  async signPsbt() {
    throw new Error('No wallet adapter available.');
  },
  async signMessage() {
    throw new Error('No wallet adapter available.');
  },
};

export function detectWallets(): string[] {
  if (typeof window === 'undefined') return [];
  const names: string[] = [];
  // @ts-expect-error injected by UniSat
  if (window.unisat) names.push('UniSat');
  // @ts-expect-error Xverse provider
  if (window.XverseProviders?.BitcoinProvider) names.push('Xverse');
  // @ts-expect-error Leather provider
  if (window.LeatherProvider) names.push('Leather');
  // @ts-expect-error OKX wallet
  if (window.okxwallet?.bitcoin) names.push('OKX Wallet');
  return names;
}
