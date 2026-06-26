import { readFileSync } from "fs";
import { join } from "path";

export interface CrashClusterVariant {
  key: string;
  label: string;
  color: string;
  isBaseline: boolean;
  params?: string;
}

export interface CrashClusterWindow {
  key: string;
  label: string;
  start: string;
  end: string;
}

export interface CrashClusterMetric {
  window: string;
  strategy: string;
  days: number;
  total_return: number;
  cagr: number;
  ann_vol: number;
  cagr_sharpe: number;
  arith_sharpe: number;
  sortino_cagr: number;
  max_drawdown: number;
  calmar: number;
  avg_exposure: number;
  latest_exposure: number;
  avg_turnover: number;
  fee_drag: number;
  d_cagr_sharpe: number;
  d_cagr: number;
  d_arith_sharpe: number;
  d_ann_vol: number;
  d_max_drawdown: number;
  d_total_return: number;
}

export interface CrashClusterData {
  generatedAt: string;
  description: string;
  variants: CrashClusterVariant[];
  windows: CrashClusterWindow[];
  metrics: CrashClusterMetric[];
}

export function loadCrashClusterData(): CrashClusterData {
  const raw = readFileSync(join(process.cwd(), "data", "crash_cluster_metrics.json"), "utf-8");
  return JSON.parse(raw) as CrashClusterData;
}
