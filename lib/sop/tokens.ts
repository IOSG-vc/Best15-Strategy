import accounts from "@/data/sop-accounts.json";
import type { TokenMeta } from "./types";

interface AccountsData {
  tokens: Record<string, { coingecko_id?: string; ticker: string; category: string }>;
}

const tokensData = (accounts as AccountsData).tokens;

export function getTokenMeta(tokenId: string | null | undefined): TokenMeta {
  if (!tokenId) return { ticker: "UNKNOWN", category: "" };
  const t = tokensData[tokenId.toLowerCase()];
  if (!t) return { ticker: tokenId.toUpperCase(), category: "" };
  return { ticker: t.ticker, category: t.category, coingecko_id: t.coingecko_id };
}

export function allTokenIds(): string[] {
  return Object.keys(tokensData);
}
