'use client';
/**
 * Shared "selected order" context. Lets the OrderBook (clicked row),
 * the BottomTable (clicked existing order), and the TradePanel (Fill
 * tab input) coordinate without prop-drilling.
 *
 * When something gets selected, the TradePanel auto-switches to the
 * Fill tab and pre-fills its artifact-hex input with the order's id.
 */
import { createContext, useCallback, useContext, useState } from 'react';

export interface SelectedOrder {
  /** Display label shown in the Fill input (typically the order id). */
  label: string;
  /** Real artifact hex when known; falls back to the order id. */
  artifactHex: string;
  /** Source — useful for analytics + result strip wording. */
  source: 'orderbook' | 'bottom-table' | 'manual';
  /**
   * Optional structured detail. When present, the TradePanel renders a
   * small preview card above the artifact textarea so the taker sees
   * what they are about to commit to before they sign. Missing fields
   * render as "—".
   */
  detail?: {
    side?: 'buy' | 'sell';
    rune?: string;
    /** Amount in rune base units (display as-is). */
    amount?: number;
    /** Price in sats per rune unit. */
    priceSats?: number;
    /** Short maker label (e.g. truncated pubkey). */
    makerShort?: string;
  };
}

interface Ctx {
  selected: SelectedOrder | null;
  /** Counter that increments on each selection — lets consumers react
   *  even when the same row is clicked twice. */
  nonce: number;
  select(s: SelectedOrder): void;
  clear(): void;
}

const C = createContext<Ctx | null>(null);

export function SelectedOrderProvider({ children }: { children: React.ReactNode }) {
  const [selected, setSelected] = useState<SelectedOrder | null>(null);
  const [nonce, setNonce] = useState(0);

  const select = useCallback((s: SelectedOrder) => {
    setSelected(s);
    setNonce((n) => n + 1);
  }, []);

  const clear = useCallback(() => {
    setSelected(null);
  }, []);

  return (
    <C.Provider value={{ selected, nonce, select, clear }}>
      {children}
    </C.Provider>
  );
}

export function useSelectedOrder(): Ctx {
  const c = useContext(C);
  if (!c) {
    return {
      selected: null,
      nonce: 0,
      select() {},
      clear() {},
    };
  }
  return c;
}
