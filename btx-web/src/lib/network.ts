/**
 * Expected Bitcoin network for this btx-web deployment.
 *
 * Read from NEXT_PUBLIC_BTC_NETWORK at build time so a dev deployment
 * can target signet/testnet without rebuilding the trade logic. The
 * default is `mainnet` — match what the brk-btx server is indexing.
 *
 * Used by the wallet network chip + the cross-network sign warning
 * in TradePanel. The protocol does NOT actually enforce this; we
 * just refuse to let the user sign a publish/fill when their wallet
 * is reporting a different network than the one we're rendering
 * orders from.
 */

const RAW = process.env.NEXT_PUBLIC_BTC_NETWORK?.toLowerCase();

export type BtcNetwork = 'mainnet' | 'signet' | 'testnet';

function parse(): BtcNetwork {
  if (RAW === 'signet') return 'signet';
  if (RAW === 'testnet') return 'testnet';
  return 'mainnet';
}

export const EXPECTED_NETWORK: BtcNetwork = parse();

/**
 * Visual classification for a network. Mainnet is the safe default
 * (green); anything else is highlighted orange so the user knows
 * they're on a non-production chain.
 */
export function networkTone(n: BtcNetwork): 'safe' | 'warn' {
  return n === 'mainnet' ? 'safe' : 'warn';
}
