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

export interface Y3Volume {
  min: number;
  avg: number;
  max: number;
  eoy_market_share: number;
}

export interface ValuationScenario {
  key: string;
  label: string;
  is_primary?: boolean;
  pv: ScenarioPV;
  ev: number;
  prob_above_spot: number;
  prob_3x?: number;
  /** Full percentile ladder P5–P95, present when the agent produces CHART_QS output */
  distribution?: Record<string, number>;
  /** HYPE model outputs */
  y3_price_p50?: number;
  y3_mcap_p50?: number;
  y3_supply_p50?: number;
  y3_gp_p50?: number;
  ev_mcap?: number;
  burn_3y_est?: number;
  y3_volume?: Y3Volume;
  y3_daily_mean_volume_p50?: number;
  prob_spot_up_30_2y?: number;
  prob_spot_down_30_2y?: number;
  y3_perp_gp_p50?: number;
  y3_stable_yield_gp_p50?: number;
}

export interface BacktestSignal {
  obs: number;
  avg_30d: number | null;
  avg_90d: number | null;
  recent_dates: string[];
}

export interface BacktestRow {
  date: string;
  spot: number;
  pv: number;
  signal: "GOOD" | "NEUTRAL" | "BAD";
}

export interface SecondaryChart {
  label: string;
  subtitle: string;
  note: string;
  unit: "x" | "y" | "pct";
  data: { date: string; value: number }[];
}

export interface HistCharts {
  backtest: {
    chart: BacktestRow[];
    signals: Record<string, BacktestSignal>;
    latest_signal: string;
    last_realized_row: string | null;
  };
  buyback_horizon?: { date: string; years: number }[];
  secondary_chart?: SecondaryChart;
  eoy3_ms: { date: string; eoy3: number; ms90: number; ms30: number }[];
  binance_spot_eoy3_ms?: { date: string; eoy3: number; ms90: number; ms30: number }[];
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
  ms_history?: MsPoint[];
  hist_charts?: HistCharts;
  mcp_bullets?: string[];
}

export interface McapPoint {
  date: string;
  mcap: number;
}

export interface MsPoint {
  date: string;
  ms30: number;
  ms90: number | null;
}

export interface TokenResult {
  name: string;
  symbol: string;
  chain: string;
  status: "ok" | "error";
  data?: ValuationData;
  error?: string;
  mcap_history?: McapPoint[];
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
