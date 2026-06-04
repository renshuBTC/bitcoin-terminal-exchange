import type { Metadata, Viewport } from 'next';
import './globals.css';

const TITLE = 'BTX — trade';
const DESCRIPTION =
  'A Bitcoin DEX. Orders live on Bitcoin. Your keys never leave your wallet. No custody, no native token, no off-chain order book.';

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  applicationName: 'BTX',
  authors: [{ name: 'BTX' }],
  keywords: [
    'bitcoin',
    'dex',
    'on-chain exchange',
    'runes',
    'btc',
    'self-custody',
    'BIP-322',
    'atomic swap',
  ],
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: 'website',
    siteName: 'BTX',
    locale: 'en_US',
  },
  twitter: {
    card: 'summary',
    title: TITLE,
    description: DESCRIPTION,
  },
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  themeColor: '#000000',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen flex flex-col">{children}</body>
    </html>
  );
}
