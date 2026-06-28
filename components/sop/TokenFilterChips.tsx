"use client";
import { useState, useMemo } from "react";
import { getTokenMeta } from "@/lib/sop/tokens";

interface TokenFilterChipsProps {
  tokenIds: string[];
  onChange: (selected: Set<string>) => void;
}

export function TokenFilterChips({ tokenIds, onChange }: TokenFilterChipsProps) {
  const unique = useMemo(() => {
    const seen = new Set<string>();
    const ordered: string[] = [];
    for (const tid of tokenIds) {
      if (!seen.has(tid)) { seen.add(tid); ordered.push(tid); }
    }
    return ordered;
  }, [tokenIds]);

  const [selected, setSelected] = useState<Set<string>>(() => new Set(unique));

  const toggle = (tid: string) => {
    const next = new Set(selected);
    if (next.has(tid)) { next.delete(tid); } else { next.add(tid); }
    setSelected(next);
    onChange(next);
  };

  const selectAll = () => { const all = new Set(unique); setSelected(all); onChange(all); };
  const clearAll  = () => { setSelected(new Set()); onChange(new Set()); };

  if (unique.length === 0) return null;

  return (
    <div className="flex items-center gap-2 flex-wrap mb-6">
      <span className="text-[11px] uppercase tracking-[1.5px] text-[--muted] mr-1">Filter</span>
      <button onClick={selectAll} className="text-[11px] text-[--muted] hover:text-[--ink] px-1">All</button>
      <button onClick={clearAll}  className="text-[11px] text-[--muted] hover:text-[--ink] px-1 mr-1">None</button>
      {unique.map((tid) => {
        const meta = getTokenMeta(tid);
        const on = selected.has(tid);
        return (
          <button
            key={tid}
            onClick={() => toggle(tid)}
            className={
              "inline-flex items-center px-2.5 py-1 rounded-full text-[12px] font-medium border transition " +
              (on
                ? "bg-[--primary] text-white border-[--primary]"
                : "bg-transparent text-[--muted] border-[--hairline] hover:border-[--muted]")
            }
          >
            {meta.ticker}
          </button>
        );
      })}
    </div>
  );
}
