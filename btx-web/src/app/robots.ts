/**
 * App Router robots.txt generator. Lets search engines index the
 * trade page (there's no other page to gate) while excluding any
 * potential internal API paths the host might add later.
 */
import type { MetadataRoute } from 'next';

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: '*',
        allow: '/',
        disallow: ['/api/'],
      },
    ],
    // Leave host blank — set at deploy time via a sitemap.xml override
    // if needed. Without a canonical host we keep the file portable
    // across mainnet / signet / testnet deployments.
  };
}
