import { formatDistanceToNow, parseISO } from "date-fns";

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return formatDistanceToNow(parseISO(iso), { addSuffix: true });
  } catch {
    return "—";
  }
}

export function sourceLabel(item: { source: string; handle: string | null }): string {
  if (item.source === "x" || item.source === "twitter") {
    return `@${(item.handle || "?").replace(/^@/, "")}`;
  }
  return item.handle || "?";
}

export function sourceIcon(source: string): string {
  return source === "telegram" ? "📨" : "🐦";
}

export function scoreBandColor(score: number, highThreshold = 9, notableThreshold = 7): string {
  if (score >= highThreshold) return "text-red-400";
  if (score >= notableThreshold) return "text-amber-400";
  return "text-slate-400";
}
