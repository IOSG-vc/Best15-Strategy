import type { Event } from "@/lib/sop/types";
import { getTokenMeta } from "@/lib/sop/tokens";
import { sourceIcon, sourceLabel, timeAgo } from "@/lib/sop/format";
import { ExternalLink } from "lucide-react";

interface Props {
  title: string;
  toneClass: string;
  accentBg: string;
  byToken: Map<string, Event[]>;
}

export function TokenSection({ title, toneClass, accentBg, byToken }: Props) {
  if (byToken.size === 0) return null;
  const sortedTokens = Array.from(byToken.entries()).sort(
    (a, b) => Math.max(...b[1].map(it => it.score_final || 0)) -
              Math.max(...a[1].map(it => it.score_final || 0))
  );
  return (
    <section className="rounded-xl border border-[--hairline] bg-canvas overflow-hidden">
      <h2 className="flex items-baseline gap-3 px-5 py-3 border-b border-[--hairline] bg-surface-soft">
        <span className={`w-1 h-4 rounded-sm ${accentBg} self-center`} />
        <span className={`font-display text-[20px] leading-none ${toneClass}`}>{title}</span>
        <span className="ml-auto text-[11px] uppercase tracking-[1.5px] text-muted font-normal">
          {byToken.size} token{byToken.size > 1 ? "s" : ""}
        </span>
      </h2>
      <div className="divide-y divide-[--hairline-soft]">
        {sortedTokens.map(([tokenId, items]) => (
          <TokenBlock key={tokenId} tokenId={tokenId} items={items} toneClass={toneClass} />
        ))}
      </div>
    </section>
  );
}

function TokenBlock({ tokenId, items, toneClass }: { tokenId: string; items: Event[]; toneClass: string }) {
  const meta = getTokenMeta(tokenId);
  const byFamily = new Map<string, Event[]>();
  for (const it of items) {
    const fam = (it.event_family || "").trim();
    byFamily.set(fam, [...(byFamily.get(fam) || []), it]);
  }
  const nonEmptyFams = Array.from(byFamily.keys()).filter(k => k);
  const useFamily = nonEmptyFams.length >= 2;
  const stories = useFamily ? byFamily.size : 1;

  const sortedFams = Array.from(byFamily.entries())
    .sort((a, b) => Math.max(...b[1].map(it => it.score_final || 0)) -
                    Math.max(...a[1].map(it => it.score_final || 0)));

  return (
    <div className="px-5 py-4 hover:bg-surface-soft/60 transition">
      <div className="flex items-baseline justify-between mb-2">
        <div className="flex items-baseline gap-3">
          <span className="font-display font-semibold text-[22px] leading-none text-ink">{meta.ticker}</span>
          {meta.category && (
            <span className="text-[10px] uppercase tracking-[1.5px] text-body font-medium">{meta.category}</span>
          )}
        </div>
        <div className="text-[11px] text-body tabular-nums">
          {items.length} event{items.length > 1 ? "s" : ""}
          {useFamily && <span className="text-muted"> · {stories} stories</span>}
        </div>
      </div>
      <div className="space-y-1.5">
        {useFamily
          ? sortedFams.map(([_fam, famItems]) => (
              <EventLine
                key={famItems[0].source_id}
                item={famItems.sort((a, b) => (b.score_final || 0) - (a.score_final || 0))[0]}
                extraCount={famItems.length - 1}
                toneClass={toneClass}
              />
            ))
          : items
              .sort((a, b) => (b.score_final || 0) - (a.score_final || 0))
              .slice(0, 3)
              .map(it => (
                <EventLine key={it.source_id} item={it} extraCount={0} toneClass={toneClass} />
              ))}
      </div>
    </div>
  );
}

function EventLine({ item, extraCount, toneClass }: { item: Event; extraCount: number; toneClass: string }) {
  const score = item.score_final?.toFixed(1) || "—";
  return (
    <div className="text-[14px] leading-snug">
      <div className="flex items-start gap-2.5">
        <span className={`shrink-0 mt-0.5 font-mono tabular-nums text-[12px] font-semibold w-10 ${toneClass}`}>{score}</span>
        <span className="shrink-0 text-xs mt-0.5 opacity-50">{sourceIcon(item.source)}</span>
        <div className="flex-1 min-w-0">
          {item.url ? (
            <a href={item.url} target="_blank" rel="noreferrer"
               className="text-body-strong hover:text-primary group inline-flex items-baseline gap-1.5 transition">
              <span>{item.summary || item.text.slice(0, 140)}</span>
              <ExternalLink size={11} className="text-muted-soft opacity-0 group-hover:opacity-100 transition" />
            </a>
          ) : (
            <span className="text-body-strong">{item.summary || item.text.slice(0, 140)}</span>
          )}
          {extraCount > 0 && (
            <span className="ml-1.5 text-[12px] text-muted-soft">(+{extraCount} more)</span>
          )}
          <div className="text-[11px] text-muted-soft tabular-nums mt-1">
            {sourceLabel(item)}
            <span className="text-[--hairline] mx-1.5">·</span>
            {timeAgo(item.timestamp)}
            {item.affects && item.affects !== "none" && (
              <>
                <span className="text-[--hairline] mx-1.5">·</span>
                <span className="text-muted">{item.affects}</span>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
