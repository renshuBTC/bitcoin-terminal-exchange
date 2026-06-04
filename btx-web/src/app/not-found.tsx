/**
 * Next.js App Router 404 page. Rendered when a user navigates to a
 * path that doesn't match any route. BTX is a single-page app so this
 * is rare — anyone hitting it either typed a wrong URL or followed
 * a stale link. The "Go to trade page" CTA gets them home.
 */
import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="flex-1 flex items-center justify-center bg-bg p-6 text-fg font-mono">
      <div className="max-w-[420px] w-full">
        <div className="text-[10px] uppercase tracking-wider text-muted mb-1">
          404 · page not found
        </div>
        <h2 className="text-fg-bright text-base mb-3">
          BTX has one page, and this isn&rsquo;t it.
        </h2>
        <p className="text-xs text-muted mb-4 leading-relaxed">
          BTX is a single-page app: the trade view is all there is. The
          link you followed probably points at an older draft.
        </p>
        <Link
          href="/"
          className="inline-block bg-orange text-black border border-orange rounded-sm h-7 px-3 leading-[26px] font-mono text-xs font-bold uppercase tracking-wider cursor-pointer hover:bg-orange-bright hover:border-orange-bright no-underline"
        >
          Go to trade page
        </Link>
      </div>
    </div>
  );
}
