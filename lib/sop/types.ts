export interface Digest {
  date: string;
  generated_at: string;
  item_count: number;
  active_tokens: number;
  high_count: number;
  notable_count: number;
  routine_count: number;
}

export interface Event {
  source_id: string;
  digest_date: string;
  source: "x" | "telegram";
  handle: string | null;
  tier: "T1" | "T1.5" | "T2" | null;
  token_id: string | null;
  url: string | null;
  text: string;
  summary: string | null;
  score_final: number | null;
  score_impact: number | null;
  score_novelty: number | null;
  score_source_quality: number | null;
  score_evidence: number | null;
  score_scoring_relevance: number | null;
  affects: string | null;
  event_family: string | null;
  cluster_id: number | null;
  is_primary: boolean;
  secondary_token_ids: string[] | null;
  bucket: "high" | "notable" | "routine" | "mentioned";
  timestamp: string;
}

export interface TokenMeta {
  ticker: string;
  category: string;
  coingecko_id?: string;
}

export type SubDim =
  | "alignment"
  | "cogs"
  | "distribution"
  | "blockworks_transparency"
  | "tam_pure"
  | "catalyst"
  | "market_leadership"
  | "moat"
  | "leadership"
  | "liquidity";

export type Confidence = "HIGH" | "MEDIUM" | "LOW";
export type SuggestionStatus = "open" | "applied" | "dismissed";

export interface SuggestionSourceItem {
  source: "sop" | "governance" | "opennews";
  url?: string | null;
  title?: string | null;
  score?: number | null;
  ts?: string | null;
  one_liner: string;
}

export interface Suggestion {
  date: string;
  token_id: string;
  sub_dim: SubDim;
  current_score: number | null;
  suggested_score: number | null;
  delta: number | null;
  confidence: Confidence | null;
  summary: string;
  signal?: string | null;
  sources: {
    sop?: SuggestionSourceItem[];
    governance?: SuggestionSourceItem[];
    opennews?: SuggestionSourceItem[];
  } | null;
  disagreements: Record<string, string> | null;
  current_value_text?: string | null;
  suggested_value_text?: string | null;
  status: SuggestionStatus;
  applied_at: string | null;
  created_at: string;
}
