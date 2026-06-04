/**
 * App Router sitemap generator. BTX is a single-page app, so the
 * sitemap is trivial — just the trade page. Listed at high priority
 * so search engines treat it as the canonical entry point.
 */
import type { MetadataRoute } from 'next';

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      // Relative URL — Next will resolve against the request host at
      // serve time, so the same code works for mainnet / signet /
      // testnet deployments without a hard-coded canonical domain.
      url: '/',
      lastModified: new Date(),
      changeFrequency: 'daily',
      priority: 1.0,
    },
  ];
}
