import { readFileSync } from "fs";
import { join } from "path";

export interface ValuationMarket {
  spot: number;
  market_cap: number;
  fdv: number;
  circulating_supply: number;
  max_supply: number;
}

export interface ValuationModel {
  type: string;
  discount_rate: number;
  multiple: number;
  paths: number;
  note?: string;
}

export interface ScenarioPV {
  p25: number;
  p50: number;
  p75: number;
  p90: number;
}

export interface ValuationScenario {
  key: string;
  label: string;
  is_primary?: boolean;
  pv: ScenarioPV;
  ev: number;
  prob_above_spot: number;
  prob_3x?: number;
}

export interface ValuationData {
  token: string;
  name: string;
  as_of_utc: string;
  market: ValuationMarket;
  model: ValuationModel;
  current_gp: Record<string, number>;
  scenarios: ValuationScenario[];
  caveats?: string[];
  data_freshness?: string;
}

export interface TokenResult {
  name: string;
  symbol: string;
  chain: string;
  status: "ok" | "error";
  data?: ValuationData;
  error?: string;
}

export interface ValuationsFile {
  lastUpdated: string;
  tokens: Record<string, TokenResult>;
}

export function loadValuations(): ValuationsFile {
  try {
    const raw = readFileSync(join(process.cwd(), "data", "valuations.json"), "utf-8");
    return JSON.parse(raw) as ValuationsFile;
  } catch {
    return { lastUpdated: "", tokens: {} };
  }
}
