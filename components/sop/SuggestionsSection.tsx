"use client";
import { useMemo, useState, useTransition } from "react";
import type { Suggestion, SubDim, SuggestionSourceItem, Confidence } from "@/lib/sop/types";
import { getTokenMeta } from "@/lib/sop/tokens";
import { Check, ChevronDown, ChevronRight, ExternalLink, Ban, Undo2 } from "lucide-react";

interface Props { suggestions: Suggestion[] }

const SUBDIM_LABELS: Record<SubDim, string> = {
  alignment: "Alignment", cogs: "COGS", distribution: "Distribution",
  blockworks_transparency: "Blockworks Penalty", liquidity: "Liquidity",
  tam_pure: "TAM (pure)", catalyst: "Catalyst",
  market_leadership: "Market Leadership", moat: "Moat", leadership: "Leadership",
};

const CONFIDENCE_STYLE: Record<string, string> = {
  HIGH:   "bg-primary text-on-primary",
  MEDIUM: "bg-accent-amber text-ink",
  LOW:    "bg-surface-card text-muted",
};

const CONFIDENCE_RANK: Record<Confidence, number> = { HIGH: 3, MEDIUM: 2, LOW: 1 };

function groupedSort(items: Suggestion[]): Suggestion[] {
  if (items.length === 0) return items;
  const byToken = new Map<string, Suggestion[]>();
  for (const s of items) {
    const arr = byToken.get(s.token_id) || [];
    arr.push(s);
    byToken.set(s.token_id, arr);
  }
  const tokenPriority = (rows: Suggestion[]): [number, number] => {
    let maxC = 0, maxD = 0;
    for (const r of rows) {
      const c = r.confidence ? CONFIDENCE_RANK[r.confidence] : 0;
      const d = Math.abs(r.delta ?? 0);
      if (c > maxC) maxC = c;
      if (d > maxD) maxD = d;
    }
    return [maxC, maxD];
  };
  const ordered = Array.from(byToken.entries()).sort(([, a], [, b]) => {
    const [ca, da] = tokenPriority(a);
    const [cb, db] = tokenPriority(b);
    if (cb !== ca) return cb - ca;
    return db - da;
  });
  const flat: Suggestion[] = [];
  for (const [, rows] of ordered) {
    rows.sort((a, b) => {
      const ca = a.confidence ? CONFIDENCE_RANK[a.confidence] : 0;
      const cb = b.confidence ? CONFIDENCE_RANK[b.confidence] : 0;
      if (cb !== ca) return cb - ca;
      return Math.abs(b.delta ?? 0) - Math.abs(a.delta ?? 0);
    });
    flat.push(...rows);
  }
  return flat;
}

export function SuggestionsSection({ suggestions }: Props) {
  const [selectedTokens, setSelectedTokens] = useState<Set<string>>(new Set());

  const allTokens = useMemo(() => {
    const counts = new Map<string, number>();
    for (const s of suggestions) counts.set(s.token_id, (counts.get(s.token_id) || 0) + 1);
    return Array.from(counts.entries())
      .sort(([, a], [, b]) => b - a)
      .map(([id, n]) => ({ id, count: n, ticker: getTokenMeta(id).ticker }));
  }, [suggestions]);

  const filtered = useMemo(() => {
    if (selectedTokens.size === 0) return suggestions;
    return suggestions.filter(s => selectedTokens.has(s.token_id));
  }, [suggestions, selectedTokens]);

  const changes  = useMemo(() => groupedSort(filtered.filter(s => (s.delta ?? 0) !== 0)), [filtered]);
  const noChange = useMemo(() => groupedSort(filtered.filter(s => (s.delta ?? 0) === 0)), [filtered]);

  const stats = useMemo(() => {
    const all = suggestions;
    return {
      tokens:   new Set(all.map(s => s.token_id)).size,
      total:    all.length,
      changes:  all.filter(s => (s.delta ?? 0) !== 0).length,
      high:     all.filter(s => s.confidence === "HIGH" && (s.delta ?? 0) !== 0).length,
      applied:  all.filter(s => s.status === "applied").length,
      rejected: all.filter(s => s.status === "dismissed").length,
    };
  }, [suggestions]);

  if (!suggestions.length) return null;

  function toggleToken(id: string) {
    setSelectedTokens(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }
  function clearFilter() { setSelectedTokens(new Set()); }

  return (
    <section className="mt-2">
      <div className="flex items-end justify-between border-b border-[--hairline] pb-4 mb-5">
        <div>
          <div className="text-[11px] uppercase tracking-[1.5px] text-body font-semibold mb-1">IOSG Factor Suggestions</div>
          <h2 className="font-display font-semibold text-[36px] leading-none text-ink">Score adjustments</h2>
        </div>
      </div>

      <div className="grid grid-cols-3 md:grid-cols-6 gap-3 mb-5">
        <StatCell label="Tokens"   value={stats.tokens}   accent="ink" />
        <StatCell label="Total"    value={stats.total}    accent="ink" />
        <StatCell label="Changes"  value={stats.changes}  accent="primary" />
        <StatCell label="HIGH"     value={stats.high}     accent="primary" emphasized />
        <StatCell label="Applied"  value={stats.applied}  accent="success" />
        <StatCell label="Rejected" value={stats.rejected} accent="muted" />
      </div>

      <div className="mb-6">
        <div className="flex items-baseline gap-3 mb-2">
          <div className="text-[11px] uppercase tracking-[1.5px] text-body font-semibold">Filter by token</div>
          {selectedTokens.size > 0 && (
            <button onClick={clearFilter} className="text-[11px] text-primary hover:text-primary-active font-medium">
              clear ({selectedTokens.size} active)
            </button>
          )}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {allTokens.map(t => {
            const on = selectedTokens.has(t.id);
            return (
              <button
                key={t.id}
                onClick={() => toggleToken(t.id)}
                className={`text-[12px] font-mono font-semibold px-3 py-1 rounded-full transition ${
                  on ? "bg-ink text-on-dark" : "bg-surface-card text-ink hover:bg-surface-strong"
                }`}
              >
                {t.ticker}
                <span className={`ml-1.5 text-[10px] font-normal ${on ? "text-on-dark-soft" : "text-muted"}`}>
                  {t.count}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {changes.length > 0 && (
        <SuggestionsList
          title="Changes"
          subtitle={`${changes.length} suggestion${changes.length > 1 ? "s" : ""}`}
          rows={changes}
          defaultExpanded={true}
        />
      )}
      {noChange.length > 0 && (
        <SuggestionsList
          title="No change"
          subtitle={`${noChange.length} suggestion${noChange.length > 1 ? "s" : ""}`}
          rows={noChange}
          defaultExpanded={false}
        />
      )}
    </section>
  );
}

function StatCell({ label, value, accent, emphasized }: {
  label: string; value: number;
  accent: "ink" | "primary" | "success" | "muted";
  emphasized?: boolean;
}) {
  const tone =
    accent === "primary" ? "text-primary" :
    accent === "success" ? "text-success"  :
    accent === "muted"   ? "text-muted"    :
                           "text-ink";
  return (
    <div className={`rounded-xl border ${emphasized ? "border-primary/40 bg-primary/5" : "border-[--hairline] bg-canvas"} px-4 py-3`}>
      <div className="text-[10px] uppercase tracking-[1.5px] text-muted font-medium">{label}</div>
      <div className={`mt-1 font-display font-semibold text-[28px] leading-none tabular-nums ${tone}`}>{value}</div>
    </div>
  );
}

function SuggestionsList({
  title, subtitle, rows, defaultExpanded,
}: { title: string; subtitle: string; rows: Suggestion[]; defaultExpanded: boolean }) {
  const [open, setOpen] = useState(defaultExpanded);
  const boundaries = new Set<number>();
  for (let i = 1; i < rows.length; i++) {
    if (rows[i].token_id !== rows[i - 1].token_id) boundaries.add(i);
  }

  return (
    <div className="mb-10">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-baseline gap-3 mb-3 group"
      >
        {open ? <ChevronDown size={14} className="text-body self-center" /> : <ChevronRight size={14} className="text-body self-center" />}
        <h3 className="font-display font-semibold text-[22px] text-ink group-hover:text-primary transition">{title}</h3>
        <span className="text-[12px] text-body">· {subtitle}</span>
      </button>

      {open && rows.length > 0 && (
        <div className="rounded-xl border border-[--hairline] bg-canvas overflow-hidden">
          {rows.map((s, i) => (
            <SuggestionRow
              key={`${s.token_id}-${s.sub_dim}`}
              suggestion={s}
              groupBoundary={boundaries.has(i)}
            />
          ))}
        </div>
      )}
      {open && rows.length === 0 && (
        <div className="rounded-xl border border-[--hairline] bg-surface-soft p-6 text-[13px] text-muted text-center italic">
          No suggestions matching current filter.
        </div>
      )}
    </div>
  );
}

function SuggestionRow({ suggestion: initial, groupBoundary }: { suggestion: Suggestion; groupBoundary: boolean }) {
  const [suggestion, setSuggestion] = useState(initial);
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const meta = getTokenMeta(suggestion.token_id);
  const label = SUBDIM_LABELS[suggestion.sub_dim] || suggestion.sub_dim;
  const cur = suggestion.current_score;
  const sug = suggestion.suggested_score;
  const delta = suggestion.delta ?? 0;
  const arrow = delta > 0 ? "↑" : delta < 0 ? "↓" : "→";
  const deltaTone = delta > 0 ? "text-success" : delta < 0 ? "text-error" : "text-muted";
  const isCategory = (suggestion.sub_dim as string) === "category";
  const confidence = suggestion.confidence || "LOW";
  const isApplied   = suggestion.status === "applied";
  const isDismissed = suggestion.status === "dismissed";
  const inactive = isApplied || isDismissed;
  const sources = suggestion.sources;
  const sourceCount =
    (sources?.sop?.length || 0) +
    (sources?.governance?.length || 0) +
    (sources?.opennews?.length || 0);

  const signalText = suggestion.signal || suggestion.summary;

  function postApi(path: string, status: "applied" | "dismissed" | "open") {
    setError(null);
    startTransition(async () => {
      try {
        const res = await fetch(path, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            date: suggestion.date, token_id: suggestion.token_id,
            sub_dim: suggestion.sub_dim, new_subdim_value: sug, reason: suggestion.summary,
          }),
        });
        const json = await res.json();
        if (!json.ok) { setError(json.error || `${status} failed`); return; }
        setSuggestion({ ...suggestion, status, applied_at: status === "open" ? null : new Date().toISOString() });
      } catch (e) { setError((e as Error).message); }
    });
  }

  function stopAndRun(fn: () => void) {
    return (e: React.MouseEvent) => { e.stopPropagation(); fn(); };
  }

  function toggleRow() {
    if (sourceCount === 0) return;
    setExpanded(v => !v);
  }

  return (
    <div
      onClick={toggleRow}
      className={[
        "px-5 py-4 transition overflow-hidden",
        sourceCount > 0 ? "cursor-pointer" : "",
        inactive ? "opacity-50 bg-surface-soft" : "hover:bg-surface-soft/60",
        groupBoundary ? "border-t border-[--hairline]" : "",
      ].join(" ")}
    >
      <div className="flex items-start gap-4">
        <div className="shrink-0 mt-1 text-body">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} className={sourceCount === 0 ? "opacity-25" : ""} />}
        </div>
        <div className="shrink-0 w-24">
          <div className="font-display font-semibold text-[22px] leading-none text-ink truncate">{meta.ticker}</div>
          {meta.category && (
            <div className="text-[10px] uppercase tracking-[1px] text-muted mt-1.5 font-medium">{meta.category}</div>
          )}
        </div>
        <div className="shrink-0 w-44">
          <div className="text-[13px] text-ink font-medium">{isCategory ? "分类建议" : label}</div>
          {isCategory ? (
            <div className="mt-1 text-[10px] uppercase tracking-[1px] text-muted font-medium">A / B / C</div>
          ) : (
            <div className="mt-1 flex items-baseline gap-1.5 font-mono tabular-nums text-[14px]">
              <span className="text-body">{cur ?? "—"}</span>
              <span className={`${deltaTone} font-semibold`}>{arrow}</span>
              <span className="text-ink font-semibold">{sug ?? "—"}</span>
              {delta !== 0 && (
                <span className={`${deltaTone} text-[11px] font-medium`}>({delta > 0 ? "+" : ""}{delta})</span>
              )}
            </div>
          )}
        </div>
        <span className={`shrink-0 self-center text-[10px] uppercase tracking-[1.5px] px-2.5 py-1 rounded-full font-semibold ${CONFIDENCE_STYLE[confidence]}`}>
          {confidence}
        </span>
        <div className="flex-1 min-w-0 text-[14px] leading-snug text-ink break-words">
          {isCategory && (
            <div className="mb-1 font-mono text-[13px]">
              <span className="text-body">{suggestion.current_value_text || "—"}</span>
              <span className="text-muted mx-1.5">→</span>
              <span className="text-ink font-semibold">{suggestion.suggested_value_text || "—"}</span>
            </div>
          )}
          <div className={expanded ? "" : "line-clamp-2"}>
            {signalText}
            {sourceCount > 0 && (
              <span className="ml-2 text-[11px] text-primary tabular-nums font-semibold">[{sourceCount}]</span>
            )}
          </div>
        </div>
        <div className="shrink-0 flex items-center gap-2 self-center">
          {isApplied && (
            <span className="inline-flex items-center gap-1.5 text-[12px] text-success italic">
              <Check size={13} /> applied
            </span>
          )}
          {isDismissed && (
            <span className="inline-flex items-center gap-1.5 text-[12px] text-muted italic">
              <Ban size={13} /> rejected
            </span>
          )}
          {!inactive && !isCategory && (
            <>
              <button
                onClick={stopAndRun(() => postApi("/api/sop/apply-suggestion", "applied"))}
                disabled={pending}
                className="text-[13px] font-medium px-4 h-9 rounded-md text-on-primary bg-primary hover:bg-primary-active disabled:opacity-50 transition"
              >
                {pending ? "..." : "Apply"}
              </button>
              <button
                onClick={stopAndRun(() => postApi("/api/sop/dismiss-suggestion", "dismissed"))}
                disabled={pending}
                className="text-[13px] font-medium px-4 h-9 rounded-md text-ink bg-canvas border border-[--hairline] hover:bg-surface-card disabled:opacity-50 transition"
              >
                Reject
              </button>
            </>
          )}
          {!inactive && isCategory && (
            <>
              <span className="text-[11px] text-muted italic mr-1">手动 su-update</span>
              <button
                onClick={stopAndRun(() => postApi("/api/sop/dismiss-suggestion", "dismissed"))}
                disabled={pending}
                className="text-[13px] font-medium px-4 h-9 rounded-md text-ink bg-canvas border border-[--hairline] hover:bg-surface-card disabled:opacity-50 transition"
              >
                {pending ? "..." : "Dismiss"}
              </button>
            </>
          )}
          {inactive && !isCategory && (
            <button
              onClick={stopAndRun(() => postApi("/api/sop/revert-suggestion", "open"))}
              disabled={pending}
              className="inline-flex items-center gap-1.5 text-[12px] font-medium px-3 h-8 rounded-md text-body bg-canvas border border-[--hairline] hover:border-primary hover:text-primary disabled:opacity-50 transition"
            >
              <Undo2 size={11} />
              {pending ? "..." : "Revert"}
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="mt-2 ml-12 text-[12px] text-error font-medium">⚠ {error}</div>
      )}

      {suggestion.disagreements && !inactive && (
        typeof suggestion.disagreements === "string" ? (
          <div className="mt-3 ml-12 rounded-md border-l-2 border-warning bg-warning/15 px-3 py-2">
            <div className="text-[10px] uppercase tracking-[1.5px] font-bold text-warning mb-1">⚠ Sources disagree</div>
            <div className="text-[12px] text-ink">{suggestion.disagreements}</div>
          </div>
        ) : Object.keys(suggestion.disagreements).length > 0 ? (
          <div className="mt-3 ml-12 rounded-md border-l-2 border-warning bg-warning/15 px-3 py-2">
            <div className="text-[10px] uppercase tracking-[1.5px] font-bold text-warning mb-1">⚠ Sources disagree</div>
            <div className="text-[12px] text-ink space-y-0.5">
              {Object.entries(suggestion.disagreements).map(([k, v]) => (
                <div key={k}>
                  <span className="font-mono font-semibold">{k}</span>: <span className="text-body-strong">{v}</span>
                </div>
              ))}
            </div>
          </div>
        ) : null
      )}

      {expanded && sources && (
        <div className="mt-3 ml-12">
          <SourcesBlock sources={sources} />
        </div>
      )}
    </div>
  );
}

function normalizeSource(raw: unknown): { text: string; url: string | null; date: string | null; score: number | null } | null {
  if (typeof raw === "string") return { text: raw, url: null, date: null, score: null };
  if (!raw || typeof raw !== "object") return null;
  const s = raw as Record<string, unknown>;
  const text =
    (typeof s.one_liner === "string" && s.one_liner) ||
    (typeof s.summary   === "string" && s.summary)   ||
    (typeof s.text      === "string" && s.text)       ||
    (typeof s.title     === "string" && s.title)      ||
    (typeof s.note      === "string" && s.note)       || "";
  let url = typeof s.url === "string" && s.url ? s.url : null;
  if (url && !/^https?:\/\//i.test(url)) { try { new URL("https://" + url); url = "https://" + url; } catch { url = null; } }
  const date = typeof s.ts   === "string" && s.ts   ? s.ts   :
               typeof s.date === "string" && s.date ? s.date : null;
  const score = typeof s.score       === "number" ? s.score :
                typeof s.score_final === "number" ? s.score_final : null;
  if (!text && !url) return null;
  return { text: text || (url ?? ""), url, date, score };
}

function sourceName(url: string | null): string {
  if (!url) return "";
  try {
    const u = new URL(url);
    const host = u.hostname.replace(/^www\./, "");
    if (host === "x.com" || host === "twitter.com") {
      const seg = u.pathname.split("/").filter(Boolean);
      if (seg[0] && seg[0] !== "i" && seg[0] !== "search") return `@${seg[0]}`;
      return host;
    }
    const parts = host.split(".");
    if (parts.length > 2) return parts.slice(-2).join(".");
    return host;
  } catch { return ""; }
}

function SourcesBlock({ sources }: { sources: NonNullable<Suggestion["sources"]> }) {
  return (
    <div className="rounded-lg bg-surface-dark p-5 space-y-4">
      <SourceGroup label="SOP"        tint="text-accent-teal"  items={sources.sop} />
      <SourceGroup label="Governance" tint="text-accent-amber" items={sources.governance} />
      <SourceGroup label="News"       tint="text-on-dark"      items={sources.opennews} />
    </div>
  );
}

function SourceGroup({ label, tint, items }: { label: string; tint: string; items: SuggestionSourceItem[] | undefined }) {
  if (!items || items.length === 0) return null;
  const normalized = items.map(normalizeSource).filter((x): x is NonNullable<typeof x> => x !== null);
  if (normalized.length === 0) return null;
  return (
    <div>
      <div className={`text-[10px] uppercase tracking-[1.5px] font-semibold mb-2 ${tint}`}>{label} · {normalized.length}</div>
      <div className="space-y-1.5">
        {normalized.map((s, i) => {
          const srcName = sourceName(s.url);
          return (
            <div key={i} className="text-[13px] leading-snug flex items-baseline gap-3 text-on-dark">
              {s.score !== null && (
                <span className="shrink-0 font-mono tabular-nums text-[11px] text-on-dark-soft w-10 text-right">
                  {s.score.toFixed(1)}
                </span>
              )}
              {s.url ? (
                <a href={s.url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}
                   className="flex-1 min-w-0 text-on-dark hover:text-primary group inline-flex items-baseline gap-1.5 transition">
                  <span>{s.text}</span>
                  <ExternalLink size={10} className="opacity-0 group-hover:opacity-100 transition shrink-0 text-primary" />
                </a>
              ) : (
                <span className="flex-1 min-w-0">{s.text}</span>
              )}
              {srcName && <span className="shrink-0 text-[11px] text-on-dark-soft font-mono">{srcName}</span>}
              {s.date && (
                <span className="shrink-0 text-[10px] text-on-dark-soft tabular-nums">
                  {(() => {
                    const d = new Date(s.date);
                    return isNaN(d.getTime()) ? s.date :
                      d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
                  })()}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
