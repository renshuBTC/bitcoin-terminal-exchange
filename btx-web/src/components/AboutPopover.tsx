'use client';
/**
 * Small "?" button + popover that explains BTX in two paragraphs.
 * Drops into the TopNav next to the Trade / Docs links so first-time
 * visitors can orient themselves without leaving the page.
 *
 * Pure presentational. No data fetching; closes on click-outside +
 * Escape (same pattern as WalletPicker).
 */
import { useEffect, useRef, useState } from 'react';

export function AboutPopover() {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div ref={wrapRef} className="relative inline-block">
      <button
        onClick={() => setOpen((o) => !o)}
        title="What is BTX?"
        aria-label="About BTX"
        aria-expanded={open}
        aria-haspopup="dialog"
        className="text-fg px-2 py-1.5 text-xs rounded-sm uppercase tracking-wider hover:bg-hover hover:text-fg-bright cursor-pointer font-mono"
      >
        ?
      </button>
      {open && (
        <div
          className="absolute left-0 mt-1.5 w-[320px] bg-menu border border-line-strong rounded-sm shadow-lg z-50 p-3 text-xs leading-relaxed"
          role="dialog"
        >
          <div className="text-[10px] uppercase tracking-wider text-muted mb-1.5">
            What is BTX?
          </div>
          <p className="text-fg mb-2">
            A Bitcoin exchange that lives entirely on Bitcoin. Makers
            publish pre-signed orders into Bitcoin transactions; takers
            atomic-swap-spend the offer UTXO. The chain is the order
            book.
          </p>
          <p className="text-fg mb-2">
            This website is a convenience layer over a fully on-chain
            protocol &mdash; the same trade page also ships inside the
            installer. Your wallet holds your keys. The site signs
            nothing; your wallet does.
          </p>
          <div className="border-t border-border-soft pt-2 mt-2 flex gap-3 text-[10px] uppercase tracking-wider">
            <a
              href="https://github.com/renshuBTC/bitcoin-terminal-exchange"
              target="_blank"
              rel="noreferrer"
              className="text-orange hover:text-orange-bright"
            >
              Source
            </a>
            <a
              href="https://github.com/renshuBTC"
              target="_blank"
              rel="noreferrer"
              className="text-muted hover:text-fg-bright"
            >
              Docs
            </a>
            <span className="ml-auto text-dim">Esc to close</span>
          </div>
        </div>
      )}
    </div>
  );
}
