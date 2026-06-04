import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'BTX — trade',
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
      <body className="min-h-screen flex flex-col">{children}</body>
    </html>
  );
}
