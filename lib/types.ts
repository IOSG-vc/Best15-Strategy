export interface DailyDataPoint {
  date: string;
  return: number;
  cumReturn: number;
}

export interface MonthlyReturn {
  year: number;
  month: number;
  return: number;
}

export interface Metrics {
  totalReturn: number;
  annReturn: number;
  annVolatility: number;
  sharpe: number | null;
  sortino: number | null;
  maxDrawdown: number;
  calmar: number | null;
  winRate: number;
  bestDay: number;
  worstDay: number;
  numDays: number;
}

export interface WeightEntry {
  coin: string;
  weight: number;
}

export interface StrategyData {
  displayName: string;
  color: string;
  dailyData: DailyDataPoint[];
  metrics: Metrics | null;
  latestWeights: WeightEntry[];
  monthlyReturns: MonthlyReturn[];
}

export interface AssetDailyPoint {
  date: string;
  cumReturn: number;
}

export interface AssetData {
  displayName: string;
  type: "crypto" | "stock";
  color: string;
  dailyData: AssetDailyPoint[];
}

export interface PerformanceData {
  lastUpdated: string;
  latestRebalanceDate: string;
  rebalanceDates: string[];
  strategies: Record<string, StrategyData>;
  assets: Record<string, AssetData>;
}

export interface CycleSignalState {
  date: string;
  btc_price: number;
  exposure: number;
  v3_exposure: number;
  overlay_delta: number;
  direction: "BULLISH" | "BEARISH" | "NEUTRAL";
  k3_rank: number;
  k3_E: number;
  k3_score: number;
  strategy_sharpe: number;
  v3_sharpe: number;
  sharpe_delta: number;
  annual_return: number;
  max_drawdown: number;
  avg_exposure: number;
  cache_warnings: string[];
}

export interface CycleHistoryPoint {
  date: string;
  exposure: number | null;
  v3_exposure?: number | null;
  btc_price?: number | null;
  k3_rank?: number | null;
}

export interface CycleSignalData {
  state: CycleSignalState | null;
  history: CycleHistoryPoint[];
}
