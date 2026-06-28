import type { Digest } from "@/lib/sop/types";

export function StatsCards({ digest, totalUniverse }: { digest: Digest; totalUniverse: number }) {
  const cards: Array<{ label: string; value: number; tone: "neutral" | "high" | "notable" | "routine" }> = [
    { label: "Universe", value: totalUniverse,        tone: "neutral" },
    { label: "Active",   value: digest.active_tokens, tone: "neutral" },
    { label: "Events",   value: digest.item_count,    tone: "neutral" },
    { label: "High",     value: digest.high_count,    tone: "high" },
    { label: "Notable",  value: digest.notable_count, tone: "notable" },
    { label: "Routine",  value: digest.routine_count, tone: "routine" },
  ];

  return (
    <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
      {cards.map((c) => (
        <div
          key={c.label}
          className="rounded-xl border border-[--hairline] bg-surface-card/60 px-5 py-4"
        >
          <div className="text-[11px] uppercase tracking-[1.5px] text-muted font-medium">
            {c.label}
          </div>
          <div
            className={`mt-1 font-display text-[32px] leading-none tabular-nums ${
              c.tone === "high"     ? "text-primary"      :
              c.tone === "notable"  ? "text-accent-amber" :
              c.tone === "routine"  ? "text-accent-teal"  :
                                      "text-ink"
            }`}
          >
            {c.value}
          </div>
        </div>
      ))}
    </div>
  );
}
