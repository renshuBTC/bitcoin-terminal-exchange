import type { Metadata } from 'next';
import './globals.css';
import { TrustFooter } from '@/components/TrustFooter';

export const metadata: Metadata = {
  title: 'BTX — fully on-chain Bitcoin exchange',
  description:
    'A Bitcoin DEX. Orders live on Bitcoin. Your keys never leave your wallet. No custody, no native token, no off-chain order book.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen flex flex-col">
        <header className="border-b border-border-strong bg-panel-2">
          <div className="mx-auto max-w-7xl px-4 py-3 flex items-center justify-between">
            <a href="/" className="font-mono text-lg font-bold text-fg-1 no-underline hover:no-underline">
              <span className="text-btc-orange">BTX</span>{' '}
              <span className="text-fg-2 text-xs ml-2">fully on-chain Bitcoin exchange</span>
            </a>
            <nav className="text-sm flex gap-4">
              <a href="/">Trade</a>
              <a href="/transparency">Transparency</a>
              <a
                href="https://github.com/renshuBTC/bitcoin-terminal-exchange"
                target="_blank"
                rel="noreferrer"
              >
                Source
              </a>
            </nav>
          </div>
        </header>
        <main className="flex-1">{children}</main>
        <TrustFooter />
      </body>
    </html>
  );
}
