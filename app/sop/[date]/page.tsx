import { notFound } from "next/navigation";
import Link from "next/link";
import { sopSupabase } from "@/lib/sop/supabase";
import { allTokenIds } from "@/lib/sop/tokens";
import type { Digest, Event, Suggestion } from "@/lib/sop/types";
import { DatePicker } from "@/components/sop/DatePicker";
import { SuggestionsSection } from "@/components/sop/SuggestionsSection";
import { TabBar } from "@/components/sop/TabBar";
import { DigestContent } from "@/components/sop/DigestContent";

export const dynamic = "force-dynamic";

interface PageProps {
  params: { date: string };
  searchParams: { tab?: string };
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function prettyDate(iso: string): string {
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString("en-US", {
    weekday: "long", month: "long", day: "numeric", timeZone: "UTC",
  });
}

export default async function SopDigestPage({ params, searchParams }: PageProps) {
  const { date } = params;
  const { tab } = searchParams;
  const activeTab = tab === "digest" ? "digest" : "suggestions";
  if (!DATE_RE.test(date)) notFound();

  const [digestRes, eventsRes, suggestionsRes] = await Promise.all([
    sopSupabase().from("digests").select("*").eq("date", date).maybeSingle(),
    sopSupabase().from("events").select("*").eq("digest_date", date).order("score_final", { ascending: false }),
    sopSupabase().from("suggestions").select("*").eq("date", date).order("created_at", { ascending: true }),
  ]);

  if (digestRes.error || !digestRes.data) {
    return (
      <div className="max-w-7xl mx-auto px-6 py-12 w-full">
        <SopHeader activeDate={date} />
        <DatePicker currentDate={date} />
        <p className="mt-12 text-[15px] text-muted">No digest found for {date}. Try another date.</p>
      </div>
    );
  }

  const digest = digestRes.data as Digest;
  const events = (eventsRes.data || []) as Event[];
  const suggestions = (suggestionsRes.data || []) as Suggestion[];
  const universe = allTokenIds();

  return (
    <>
      <SopHeader activeDate={date} />
      <main className="max-w-7xl mx-auto px-6 py-10 w-full space-y-10">
        <section className="flex items-end justify-between gap-6 flex-wrap pb-6 border-b border-[--hairline]">
          <div>
            <div className="text-[11px] uppercase tracking-[1.5px] text-muted mb-2">Daily Digest</div>
            <h1 className="font-display text-[56px] leading-none tracking-tight text-ink">
              {prettyDate(date)}
            </h1>
            <div className="mt-3 text-[13px] text-muted-soft tabular-nums">
              Generated {new Date(digest.generated_at).toLocaleString()}
            </div>
          </div>
          <DatePicker currentDate={date} />
        </section>

        <div className="mt-10">
          <TabBar activeTab={activeTab} date={date} />
        </div>

        {activeTab === "suggestions" ? (
          <SuggestionsSection suggestions={suggestions} />
        ) : (
          <DigestContent digest={digest} events={events} universe={universe} />
        )}

        <footer className="text-[11px] text-muted-soft text-center pt-4 pb-8 border-t border-[--hairline-soft] mt-8">
          SOP Token Monitor · 25-token universe · 15:30 + 16:30 HKT · GitHub Actions · IOSG internal
        </footer>
      </main>
    </>
  );
}

function SopHeader({ activeDate }: { activeDate?: string }) {
  return (
    <header className="border-b border-[--hairline] bg-canvas/95 backdrop-blur sticky top-0 z-30">
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        <Link href="/sop" className="flex items-baseline gap-2 group">
          <svg width="14" height="14" viewBox="0 0 16 16" className="text-ink shrink-0 self-center">
            <g fill="currentColor">
              <rect x="7.2" y="0"   width="1.6" height="6" />
              <rect x="7.2" y="10"  width="1.6" height="6" />
              <rect x="0"   y="7.2" width="6"   height="1.6" />
              <rect x="10"  y="7.2" width="6"   height="1.6" />
              <rect x="2.5" y="2.5" width="1.4" height="4" transform="rotate(-45 3.2 4.5)" />
              <rect x="11.1" y="2.5" width="1.4" height="4" transform="rotate(45 11.8 4.5)" />
              <rect x="2.5" y="9.5" width="1.4" height="4" transform="rotate(45 3.2 11.5)" />
              <rect x="11.1" y="9.5" width="1.4" height="4" transform="rotate(-45 11.8 11.5)" />
            </g>
          </svg>
          <span className="font-display text-[20px] tracking-tight text-ink group-hover:text-primary transition">
            SOP Monitor
          </span>
          {activeDate && (
            <span className="text-[12px] font-mono text-muted ml-2 hidden sm:inline">· {activeDate}</span>
          )}
        </Link>
        <nav className="flex items-center gap-4 text-[13px]">
          <Link href="/sop" className="text-muted hover:text-ink transition">Today</Link>
          <span className="text-[--hairline]">·</span>
          <Link href="/private-fund" className="text-muted-soft hover:text-ink transition">← Dashboard</Link>
        </nav>
      </div>
    </header>
  );
}
