/**
 * Bitcoin wallet adapter interface.
 *
 * Normalizes UniSat, Xverse, Leather, and OKX Wallet's browser-extension
 * APIs into a single TypeScript interface. Per the build plan §5:
 * **the wallet holds all keys; the website only asks the wallet to sign,
 * never receives or stores keys.**
 *
 * MVP scope: connect + getUtxos + signPsbt. Adapters are added in
 * later commits; this file ships the interface + a no-op default.
 */

export interface ConnectedWallet {
  /** User's primary address (Taproot preferred when available). */
  address: string;
  /** Hex-encoded 33-byte plain pubkey for the address. */
  pubkey: string;
  /** mainnet | signet | testnet — must match the backend. */
  network: 'mainnet' | 'signet' | 'testnet';
  /** Provider name for the trust-UI footer ("UniSat" / "Xverse" / ...) */
  providerName: string;
}

export interface Utxo {
  txid: string;
  vout: number;
  /** Value in sats. */
  value: number;
  /** Hex-encoded scriptPubkey. */
  scriptPubKey: string;
  confirmations: number;
}

export interface BitcoinWallet {
  /** Connect to the wallet (triggers wallet UI). */
  connect(): Promise<ConnectedWallet>;

  /** Disconnect (best-effort — most extensions don't have an API for this). */
  disconnect(): Promise<void>;

  /** Whether a wallet is currently connected. */
  isConnected(): boolean;

  /**
   * Fetch the user's spendable UTXOs. Implementations may query the
   * extension or fall back to a public Esplora endpoint depending on
   * what the extension exposes.
   */
  getUtxos(opts?: { minConfirmations?: number }): Promise<Utxo[]>;

  /**
   * Ask the wallet to sign a PSBT. `signInputs` lists the input indices
   * the user must sign (those funded by the user's keys, not the
   * maker's pre-signed input). `finalize` controls whether the wallet
   * returns a signed-but-not-finalized PSBT or a fully finalized
   * raw transaction.
   *
   * Returns the resulting hex string (PSBT or raw tx depending on
   * `finalize`).
   */
  signPsbt(
    psbtBase64: string,
    opts: { signInputs: number[]; finalize: boolean },
  ): Promise<string>;
}

/** Default no-op adapter — replaced by a real one on connect(). */
export const noWallet: BitcoinWallet = {
  async connect() {
    throw new Error(
      'No wallet adapter available. Install UniSat, Xverse, Leather, or OKX Wallet.',
    );
  },
  async disconnect() {},
  isConnected() {
    return false;
  },
  async getUtxos() {
    return [];
  },
  async signPsbt() {
    throw new Error('No wallet adapter available.');
  },
};

/**
 * Detect available wallet providers. Returns a list of provider names
 * the user can choose from. Adapters themselves are loaded lazily.
 *
 * NOTE: stub implementation; real detection lands per-adapter as the
 * adapters themselves are written.
 */
export function detectWallets(): string[] {
  if (typeof window === 'undefined') return [];
  const names: string[] = [];
  // @ts-expect-error window.unisat is injected by the UniSat extension
  if (window.unisat) names.push('UniSat');
  // @ts-expect-error Xverse provider
  if (window.XverseProviders?.BitcoinProvider) names.push('Xverse');
  // @ts-expect-error Leather provider
  if (window.LeatherProvider) names.push('Leather');
  // @ts-expect-error OKX wallet provider
  if (window.okxwallet?.bitcoin) names.push('OKX Wallet');
  return names;
}
