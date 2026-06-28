import type { Event } from "@/lib/sop/types";
import { getTokenMeta } from "@/lib/sop/tokens";
import { sourceLabel } from "@/lib/sop/format";

export function RoutineSection({ byToken }: { byToken: Map<string, Event[]> }) {
  if (byToken.size === 0) return null;
  const ROUTINE_FLOOR = 2.0;
  const filtered = new Map<string, Event[]>();
  Array.from(byToken.entries()).forEach(([tid, items]) => {
    const kept = items.filter((it: Event) => (it.score_final || 0) >= ROUTINE_FLOOR);
    if (kept.length) filtered.set(tid, kept);
  });
  if (filtered.size === 0) return null;

  const total = Array.from(filtered.values()).reduce((s, arr) => s + arr.length, 0);
  const sortedTokens = Array.from(filtered.entries()).sort(
    (a, b) => Math.max(...b[1].map(it => it.score_final || 0)) -
              Math.max(...a[1].map(it => it.score_final || 0))
  );

  return (
    <section className="rounded-xl border border-[--hairline] bg-canvas overflow-hidden">
      <h2 className="flex items-baseline gap-3 px-5 py-3 border-b border-[--hairline] bg-surface-soft">
        <span className="w-1 h-4 rounded-sm bg-accent-teal self-center" />
        <span className="font-display text-[20px] leading-none text-ink">Routine</span>
        <span className="ml-auto text-[11px] uppercase tracking-[1.5px] text-muted font-normal tabular-nums">
          {total} events · {filtered.size} tokens
        </span>
      </h2>
      <div className="divide-y divide-[--hairline-soft]">
        {sortedTokens.map(([tid, items]) => (
          <RoutineTokenRow key={tid} tokenId={tid} items={items} />
        ))}
      </div>
    </section>
  );
}

function RoutineTokenRow({ tokenId, items }: { tokenId: string; items: Event[] }) {
  const meta = getTokenMeta(tokenId);
  const sorted = [...items].sort((a, b) => (b.score_final || 0) - (a.score_final || 0));
  const top = sorted[0];

  if (items.length === 1) {
    return (
      <div className="px-5 py-2.5 text-[14px] flex items-baseline gap-3 hover:bg-surface-soft/60 transition">
        <span className="font-display font-semibold text-[19px] text-ink w-20 shrink-0 leading-none">{meta.ticker}</span>
        <span className="text-accent-teal font-mono tabular-nums text-[12px] w-10 shrink-0">{top.score_final?.toFixed(1)}</span>
        <span className="text-body truncate flex-1 leading-snug">
          {top.url ? (
            <a href={top.url} target="_blank" rel="noreferrer" className="hover:text-primary transition">
              {top.summary || top.text.slice(0, 120)}
            </a>
          ) : (top.summary || top.text.slice(0, 120))}
          <span className="ml-2 text-muted-soft text-[11px]">{sourceLabel(top)}</span>
        </span>
      </div>
    );
  }

  const byFamily = new Map<string, Event[]>();
  for (const it of sorted) {
    const fam = (it.event_family || "").trim();
    byFamily.set(fam, [...(byFamily.get(fam) || []), it]);
  }
  const nonEmpty = Array.from(byFamily.keys()).filter(k => k);
  const useFamily = nonEmpty.length >= 2;

  return (
    <div className="px-5 py-3 text-[14px] hover:bg-surface-soft/60 transition">
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="font-display font-semibold text-[19px] text-ink leading-none">{meta.ticker}</span>
        <span className="text-[11px] text-muted tabular-nums">
          {items.length} events{useFamily && ` · ${byFamily.size} stories`}
        </span>
      </div>
      {useFamily ? (
        Array.from(byFamily.entries())
          .sort((a, b) => Math.max(...b[1].map(it => it.score_final || 0)) -
                          Math.max(...a[1].map(it => it.score_final || 0)))
          .map(([_fam, famItems]) => {
            const rep = famItems[0];
            return (
              <div key={rep.source_id} className="ml-4 mb-1 text-[13px] flex items-baseline gap-2 leading-snug">
                <span className="text-muted-soft shrink-0">▸</span>
                <span className="text-accent-teal font-mono tabular-nums w-9 shrink-0 text-[12px]">{rep.score_final?.toFixed(1)}</span>
                <span className="text-body truncate flex-1">
                  {rep.url ? (
                    <a href={rep.url} target="_blank" rel="noreferrer" className="hover:text-primary transition">
                      {rep.summary || rep.text.slice(0, 100)}
                    </a>
                  ) : (rep.summary || rep.text.slice(0, 100))}
                  {famItems.length > 1 && (
                    <span className="ml-1.5 text-muted-soft">(+{famItems.length - 1})</span>
                  )}
                </span>
              </div>
            );
          })
      ) : (
        sorted.map(it => (
          <div key={it.source_id} className="ml-4 mb-1 text-[13px] flex items-baseline gap-2 leading-snug">
            <span className="text-accent-teal font-mono tabular-nums w-9 shrink-0 text-[12px]">{it.score_final?.toFixed(1)}</span>
            <span className="text-body truncate flex-1">
              {it.url ? (
                <a href={it.url} target="_blank" rel="noreferrer" className="hover:text-primary transition">
                  {it.summary || it.text.slice(0, 100)}
                </a>
              ) : (it.summary || it.text.slice(0, 100))}
            </span>
          </div>
        ))
      )}
    </div>
  );
}
