'use client';
/**
 * Next.js App Router error boundary. If any client component below
 * the root layout throws at render time, Next renders this instead
 * of the white screen of death. The user gets a useful retry button
 * and the error message; we get a console signal for debugging.
 *
 * Next requires this file to be a Client Component (it uses the
 * Error API). The 'reset()' callback re-attempts the failed render.
 */
import { useEffect } from 'react';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Log on the client so the developer sees the stack in DevTools.
    // We deliberately don't send this anywhere — no error tracker yet.
    // eslint-disable-next-line no-console
    console.error('btx-web: render-time error', error);
  }, [error]);

  return (
    <div className="flex-1 flex items-center justify-center bg-bg p-6 text-fg font-mono">
      <div className="max-w-[480px] w-full">
        <div className="text-[10px] uppercase tracking-wider text-orange mb-1">
          Render error
        </div>
        <h2 className="text-fg-bright text-base mb-3">Something broke.</h2>
        <p className="text-xs text-muted mb-3 leading-relaxed">
          The trade page hit a runtime error and stopped rendering. Your
          wallet was not touched. Most issues are transient — try the
          retry button. If it persists, check DevTools and open an issue
          on the repo.
        </p>
        <div className="border border-border-soft rounded-sm bg-panel p-2 mb-3 text-[11px] break-all">
          <span className="text-red">{error.name}:</span>{' '}
          <span className="text-fg">{error.message}</span>
          {error.digest && (
            <div className="text-[10px] text-dim mt-1">
              digest: {error.digest}
            </div>
          )}
        </div>
        <div className="flex gap-2">
          <button
            onClick={reset}
            type="button"
            className="bg-orange text-black border border-orange rounded-sm h-7 px-3 font-mono text-xs font-bold uppercase tracking-wider cursor-pointer hover:bg-orange-bright hover:border-orange-bright"
          >
            Retry
          </button>
          <a
            href="https://github.com/renshuBTC/bitcoin-terminal-exchange/issues"
            target="_blank"
            rel="noreferrer"
            className="bg-hover text-fg-bright border border-line-strong rounded-sm h-7 px-3 leading-[26px] font-mono text-xs font-bold uppercase tracking-wider cursor-pointer hover:border-orange no-underline"
          >
            Report
          </a>
        </div>
      </div>
    </div>
  );
}
