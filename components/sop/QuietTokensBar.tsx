import { getTokenMeta } from "@/lib/sop/tokens";

export function QuietTokensBar({ tokenIds }: { tokenIds: string[] }) {
  if (tokenIds.length === 0) return null;
  const tickers = tokenIds.map(id => getTokenMeta(id).ticker).sort();

  return (
    <section className="rounded-xl border border-[--hairline] bg-canvas overflow-hidden">
      <h2 className="flex items-baseline gap-3 px-5 py-3 border-b border-[--hairline] bg-surface-soft">
        <span className="w-1 h-4 rounded-sm bg-muted-soft/40 self-center" />
        <span className="font-display text-[20px] leading-none text-muted">Quiet</span>
        <span className="ml-auto text-[11px] uppercase tracking-[1.5px] text-muted-soft font-normal">
          {tickers.length} tokens · no signal in 24h
        </span>
      </h2>
      <div className="px-5 py-3 flex flex-wrap gap-1.5">
        {tickers.map(t => (
          <span key={t} className="text-[12px] px-2.5 py-1 rounded-full bg-surface-card text-muted font-mono">
            {t}
          </span>
        ))}
      </div>
    </section>
  );
}
