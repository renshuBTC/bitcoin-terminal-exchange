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
  // Production HTTP security headers. Per OWASP guidance for a
  // single-page web wallet host. No JS-only origins are loaded
  // (no Cloudflare turnstile, no Google Analytics, no Sentry —
  // see lib/api.ts for the only fetch hosts the page talks to).
  async headers() {
    return [
      {
        // Catch-all: applies to every route.
        source: '/:path*',
        headers: [
          // Block clickjacking attempts that put the trade page inside
          // an attacker iframe. SAMEORIGIN is permissive enough for our
          // installer's WebView, which serves from the same origin.
          { key: 'X-Frame-Options', value: 'SAMEORIGIN' },
          // Don't leak the full referer URL on cross-origin navigation
          // (wallet picker install links go to unisat.io / xverse.app /
          // leather.io / okx.com).
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          // Disable MIME-type sniffing — we serve typed JSON via the
          // brk-btx API, never inline scripts from untyped responses.
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          // Lock down browser features we don't need so a future bug
          // can't accidentally expose them.
          {
            key: 'Permissions-Policy',
            value: 'camera=(), microphone=(), geolocation=(), interest-cohort=()',
          },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
