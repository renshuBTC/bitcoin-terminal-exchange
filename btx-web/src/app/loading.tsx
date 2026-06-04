/**
 * Next.js App Router loading skeleton. Rendered while the server
 * component fetches orders / health / state_root and composes the
 * page on first request.
 *
 * Kept deliberately minimal so it doesn't flash a competing layout
 * before the real page arrives — just a dim "Loading…" line with the
 * BTX glyph so the user knows something's happening.
 */
export default function Loading() {
  return (
    <div className="flex-1 flex items-center justify-center bg-bg p-6 font-mono">
      <div className="flex items-center gap-3 text-muted text-xs uppercase tracking-wider">
        <span className="inline-block w-[18px] h-[18px] rounded-sm bg-gradient-to-br from-orange to-orange-bright animate-pulse" />
        Loading BTX&hellip;
      </div>
    </div>
  );
}
