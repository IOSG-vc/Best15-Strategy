"use client";
import { useState, useMemo } from "react";
import type { Digest, Event } from "@/lib/sop/types";
import { StatsCards } from "@/components/sop/StatsCards";
import { TokenSection } from "@/components/sop/TokenSection";
import { RoutineSection } from "@/components/sop/RoutineSection";
import { MentionedSection } from "@/components/sop/MentionedSection";
import { QuietTokensBar } from "@/components/sop/QuietTokensBar";
import { TokenFilterChips } from "@/components/sop/TokenFilterChips";

interface DigestContentProps {
  digest: Digest;
  events: Event[];
  universe: string[];
}

export function DigestContent({ digest, events, universe }: DigestContentProps) {
  const [selectedTokens, setSelectedTokens] = useState<Set<string>>(() => {
    const tids = new Set<string>();
    for (const e of events) {
      if (e.token_id && e.token_id !== "__shared__" && e.token_id !== "__unknown__") {
        tids.add(e.token_id);
      }
    }
    return tids;
  });

  const filteredEvents = useMemo(() => {
    if (selectedTokens.size === 0) return [];
    return events.filter((e) => {
      if (!e.token_id) return false;
      if (e.token_id === "__shared__" || e.token_id === "__unknown__") return false;
      return selectedTokens.has(e.token_id);
    });
  }, [events, selectedTokens]);

  const tokenIds = useMemo(() => {
    const tids = new Set<string>();
    for (const e of events) {
      if (e.token_id && e.token_id !== "__shared__" && e.token_id !== "__unknown__") {
        tids.add(e.token_id);
      }
    }
    return Array.from(tids).sort();
  }, [events]);

  const highByToken    = bucketByToken(filteredEvents.filter(e => e.bucket === "high"));
  const notableByToken = bucketByToken(filteredEvents.filter(e => e.bucket === "notable"));
  const routineByToken = bucketByToken(filteredEvents.filter(e => e.bucket === "routine"));

  const highTokens = new Set(Array.from(highByToken.keys()));
  Array.from(highTokens).forEach(tid => notableByToken.delete(tid));
  Array.from(highTokens).concat(Array.from(notableByToken.keys())).forEach(tid => routineByToken.delete(tid));

  const primaryTokens = new Set(filteredEvents.filter(e => e.token_id).map(e => e.token_id!));
  const mentions: { secondaryToken: string; primaryToken: string; event: Event }[] = [];
  for (const ev of filteredEvents) {
    if (!ev.secondary_token_ids || !ev.token_id) continue;
    for (const sec of ev.secondary_token_ids) {
      if (sec === ev.token_id) continue;
      if (!primaryTokens.has(sec)) {
        mentions.push({ secondaryToken: sec, primaryToken: ev.token_id, event: ev });
      }
    }
  }
  const mentionedTokens = new Set(mentions.map(m => m.secondaryToken));
  const activeTokens    = new Set(Array.from(primaryTokens).concat(Array.from(mentionedTokens)));
  const quietTokens     = universe.filter(t => !activeTokens.has(t));

  return (
    <>
      <div className="border-t border-[--hairline] pt-8">
        <div className="flex items-baseline justify-between gap-4 flex-wrap">
          <div>
            <div className="text-[11px] uppercase tracking-[1.5px] text-[--body] font-semibold mb-1">
              Raw Source Material
            </div>
            <h2 className="font-display font-semibold text-[28px] leading-none text-[--ink]">
              Daily digest
            </h2>
          </div>
          <span className="text-[13px] text-[--muted-soft] tabular-nums">
            {filteredEvents.length} items
          </span>
        </div>
      </div>

      <TokenFilterChips tokenIds={tokenIds} onChange={setSelectedTokens} />
      <StatsCards digest={digest} totalUniverse={universe.length} />

      <TokenSection
        title="High Impact"
        toneClass="text-primary"
        accentBg="bg-primary"
        byToken={highByToken}
      />
      <TokenSection
        title="Notable"
        toneClass="text-accent-amber"
        accentBg="bg-accent-amber"
        byToken={notableByToken}
      />
      <RoutineSection byToken={routineByToken} />
      <MentionedSection mentions={mentions} />
      <QuietTokensBar tokenIds={quietTokens} />
    </>
  );
}

function bucketByToken(events: Event[]): Map<string, Event[]> {
  const m = new Map<string, Event[]>();
  for (const e of events) {
    const tid = e.token_id;
    if (!tid || tid === "__shared__" || tid === "__unknown__") continue;
    m.set(tid, [...(m.get(tid) || []), e]);
  }
  return m;
}
