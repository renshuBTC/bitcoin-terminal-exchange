/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Smaller production bundle — source maps still available locally
  // via `next dev` / `next build --debug`.
  productionBrowserSourceMaps: false,
  env: {
    NEXT_PUBLIC_API_URL:
      process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3110',
    // BTC network this deployment targets. Reads through to
    // lib/network.ts → wallet network chip + sign mismatch banner.
    // Valid: 'mainnet' | 'signet' | 'testnet'.
    NEXT_PUBLIC_BTC_NETWORK: process.env.NEXT_PUBLIC_BTC_NETWORK || 'mainnet',
  },
};

module.exports = nextConfig;
