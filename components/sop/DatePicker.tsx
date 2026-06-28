"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, Calendar } from "lucide-react";

interface DateOption {
  date: string;
  item_count: number;
  high_count: number;
  notable_count: number;
}

export function DatePicker({ currentDate }: { currentDate: string }) {
  const router = useRouter();
  const [dates, setDates] = useState<DateOption[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    fetch("/api/sop/dates")
      .then((r) => r.json())
      .then((d) => setDates(d.dates || []))
      .catch(() => setDates([]));
  }, []);

  const onPick = (d: string) => {
    setOpen(false);
    router.push(`/sop/${d}`);
  };

  return (
    <div className="relative inline-block">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 h-10 px-3 rounded-md border border-[--hairline] bg-canvas hover:bg-surface-card text-[13px] font-mono text-ink transition"
      >
        <Calendar size={13} className="text-muted" />
        <span>{currentDate}</span>
        <ChevronDown size={13} className="text-muted" />
      </button>
      {open && (
        <div className="absolute z-20 mt-1 w-80 max-h-80 overflow-auto rounded-lg border border-[--hairline] bg-canvas shadow-lg">
          {dates.length === 0 && (
            <div className="px-4 py-3 text-[12px] text-muted">No digests yet</div>
          )}
          {dates.map((d) => {
            const active = d.date === currentDate;
            return (
              <button
                key={d.date}
                onClick={() => onPick(d.date)}
                className={`w-full text-left px-4 py-2 text-[13px] flex items-center justify-between border-b border-[--hairline-soft] last:border-0 transition ${
                  active ? "bg-surface-card text-ink" : "hover:bg-surface-soft text-body"
                }`}
              >
                <span className="font-mono">{d.date}</span>
                <span className="text-[11px] text-muted-soft tabular-nums">
                  {d.item_count}
                  {d.high_count > 0 && (
                    <span className="ml-2 text-primary font-semibold">{d.high_count} high</span>
                  )}
                  {d.notable_count > 0 && (
                    <span className="ml-1.5 text-accent-amber font-semibold">{d.notable_count}</span>
                  )}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
