import type { Event } from "@/lib/sop/types";
import { getTokenMeta } from "@/lib/sop/tokens";

interface MentionRef {
  secondaryToken: string;
  primaryToken: string;
  event: Event;
}

export function MentionedSection({ mentions }: { mentions: MentionRef[] }) {
  if (mentions.length === 0) return null;

  const bySec = new Map<string, MentionRef[]>();
  for (const m of mentions) {
    bySec.set(m.secondaryToken, [...(bySec.get(m.secondaryToken) || []), m]);
  }

  return (
    <section className="rounded-xl border border-[--hairline] bg-canvas overflow-hidden">
      <h2 className="flex items-baseline gap-3 px-5 py-3 border-b border-[--hairline] bg-surface-soft">
        <span className="w-1 h-4 rounded-sm bg-muted/40 self-center" />
        <span className="font-display text-[20px] leading-none text-ink">Mentioned</span>
        <span className="ml-auto text-[11px] uppercase tracking-[1.5px] text-muted font-normal">
          {bySec.size} surfaced via others
        </span>
      </h2>
      <div className="divide-y divide-[--hairline-soft]">
        {Array.from(bySec.entries()).sort().map(([sec, refs]) => {
          const secMeta = getTokenMeta(sec);
          const top = refs.sort((a, b) => (b.event.score_final || 0) - (a.event.score_final || 0))[0];
          const primaryMeta = getTokenMeta(top.primaryToken);
          return (
            <div key={sec} className="px-5 py-2.5 text-[13px] flex items-baseline gap-3 hover:bg-surface-soft/60 transition">
              <span className="font-display font-semibold text-[19px] text-ink w-20 shrink-0 leading-none">{secMeta.ticker}</span>
              <span className="text-muted-soft shrink-0">←</span>
              <span className="text-body truncate flex-1">
                in{" "}
                {top.event.url ? (
                  <a href={top.event.url} target="_blank" rel="noreferrer" className="font-mono text-ink hover:text-primary transition">
                    {primaryMeta.ticker}
                  </a>
                ) : (
                  <span className="font-mono text-ink">{primaryMeta.ticker}</span>
                )}
                {" — "}
                {top.event.summary || top.event.text.slice(0, 100)}
                {refs.length > 1 && (
                  <span className="text-muted-soft ml-1.5">
                    (also {refs.slice(1).map(r => getTokenMeta(r.primaryToken).ticker).join(", ")})
                  </span>
                )}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
