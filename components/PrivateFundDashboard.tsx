"use client";

import { useState, useCallback, useEffect, useMemo } from "react";
import dynamic from "next/dynamic";
import type { StrategyData, AssetData } from "@/lib/types";
import type { PositionsData } from "@/lib/loadPositions";
import type { ChartPoint, AssetPerfEntry, MetricsSummary } from "@/lib/privateFundTypes";
import Nav from "./Nav";
import type { SeriesConfig } from "./PrivateFundIndexChart";

const PrivateFundIndexChart = dynamic(() => import("./PrivateFundIndexChart"), { ssr: false });
const PrivateFundAssetPerf = dynamic(() => import("./PrivateFundAssetPerf"), { ssr: false });

type UniverseMode = "mcap" | "liquidity";

interface Props {
  privateData: StrategyData | undefined;
  btcData: AssetData | undefined;
  allAssets: Record<string, AssetData>;
  allStrategies: Record<string, StrategyData>;
  positions: PositionsData | null;
  lastUpdated: string;
  latestRebalanceDate: string;
}

type PriceMap = Record<string, number>;

const ALWAYS_SERIES: SeriesConfig[] = [
  { key: "index",    label: "Private Fund Index",    color: "#8b5cf6" },
  { key: "combined", label: "Index + Signal (50/50)", color: "#06b6d4" },
  { key: "btc",      label: "Bitcoin",               color: "#f97316" },
];

const PF_SERIES: SeriesConfig[] = [
  { key: "pf_b",  label: "PF Base",       color: "#6ee7b7" },
  { key: "pf_sz", label: "PF +Size",      color: "#34d399" },
  { key: "pf_lq", label: "PF +Liquidity", color: "#10b981" },
  { key: "pf_tc", label: "PF +Tech",      color: "#059669" },
  { key: "pf_ql", label: "PF +Quality",   color: "#047857" },
];

const ETF_MCAP_SERIES: SeriesConfig[] = [
  { key: "em_b",  label: "ETF Base",   color: "#fde68a" },
  { key: "em_mv", label: "ETF MinVar", color: "#fcd34d" },
  { key: "em_lq", label: "ETF +Liq",  color: "#fbbf24" },
  { key: "em_tc", label: "ETF +Tech", color: "#f59e0b" },
  { key: "onn_m", label: "1/N (MCAP)", color: "#f472b6" },
];

const ETF_LIQ_SERIES: SeriesConfig[] = [
  { key: "el_b",  label: "ETF Base",   color: "#bae6fd" },
  { key: "el_mv", label: "ETF MinVar", color: "#7dd3fc" },
  { key: "el_lq", label: "ETF +Liq",  color: "#38bdf8" },
  { key: "el_tc", label: "ETF +Tech", color: "#0ea5e9" },
  { key: "onn_l", label: "1/N (Liq)", color: "#c084fc" },
];

function computeTWR(
  inceptionFundSize: number,
  history: import("@/lib/loadPositions").RebalanceEntry[],
  currentFundValue: number,
): number | null {
  let periodStart = inceptionFundSize;
  let chainedFactor = 1;
  for (const entry of history) {
    if (entry.fundValueBeforeCashFlow === null) return null;
    chainedFactor *= entry.fundValueBeforeCashFlow / periodStart;
    periodStart = entry.fundValueBeforeCashFlow + entry.cashFlow;
  }
  chainedFactor *= currentFundValue / periodStart;
  return chainedFactor - 1;
}

function fmtPrice(p: number): string {
  if (p >= 1000) return p.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (p >= 1) return p.toFixed(3);
  return p.toFixed(6);
}

function fmtUsd(n: number, decimals = 0): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function lastCumReturn(strat: StrategyData | undefined): number {
  if (!strat?.dailyData.length) return 0;
  return (strat.dailyData[strat.dailyData.length - 1].cumReturn - 1) * 100;
}

type CompRow =
  | { type: "section"; label: string; color: string }
  | { type: "data"; label: string; color: string; mcap: number; liq: number };

type StrategyGroup = "pf" | "etf_mcap" | "etf_liq" | "onn";

interface StrategyStage {
  key: string;
  label: string;
  color: string;
}

interface StrategyGroupDef {
  key: StrategyGroup;
  label: string;
  color: string;
  stages: StrategyStage[];
}

const STRAT_GROUPS: StrategyGroupDef[] = [
  {
    key: "pf", label: "PF Family", color: "#10b981",
    stages: [
      { key: "pf_b",  label: "Base",     color: "#6ee7b7" },
      { key: "pf_sz", label: "+Size",    color: "#34d399" },
      { key: "pf_lq", label: "+Liq",    color: "#10b981" },
      { key: "pf_tc", label: "+Tech",   color: "#059669" },
      { key: "pf_ql", label: "+Quality", color: "#047857" },
    ],
  },
  {
    key: "etf_mcap", label: "ETF (MCAP)", color: "#fbbf24",
    stages: [
      { key: "em_b",  label: "Base",   color: "#fde68a" },
      { key: "em_mv", label: "MinVar", color: "#fcd34d" },
      { key: "em_lq", label: "+Liq",  color: "#fbbf24" },
      { key: "em_tc", label: "+Tech", color: "#f59e0b" },
    ],
  },
  {
    key: "etf_liq", label: "ETF (Liq)", color: "#38bdf8",
    stages: [
      { key: "el_b",  label: "Base",   color: "#bae6fd" },
      { key: "el_mv", label: "MinVar", color: "#7dd3fc" },
      { key: "el_lq", label: "+Liq",  color: "#38bdf8" },
      { key: "el_tc", label: "+Tech", color: "#0ea5e9" },
    ],
  },
  {
    key: "onn", label: "1/N Equal", color: "#f472b6",
    stages: [
      { key: "onn_m", label: "MCAP", color: "#f472b6" },
      { key: "onn_l", label: "Liq",  color: "#c084fc" },
    ],
  },
];

interface AssetBreakdownRow {
  id: string;
  name: string;
  weightPct: number;
  returnPct: number | null;
  contribution: number | null;
  available: boolean;
}

export default function PrivateFundDashboard({
  privateData,
  btcData,
  allAssets,
  allStrategies,
  positions,
  lastUpdated,
  latestRebalanceDate,
}: Props) {
  const [livePrices, setLivePrices] = useState<PriceMap | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastFetched, setLastFetched] = useState<string | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [universeMode, setUniverseMode] = useState<UniverseMode>("mcap");
  const [stratGroup, setStratGroup] = useState<StrategyGroup>("pf");
  const [stratStage, setStratStage] = useState<string>("pf_ql");

  const refresh = useCallback(async () => {
    setLoading(true);
    setFetchError(null);
    try {
      const res = await fetch("/api/prices");
      if (!res.ok) throw new Error("API error");
      const data = (await res.json()) as { prices: PriceMap; timestamp: string };
      setLivePrices(data.prices);
      setLastFetched(
        new Date(data.timestamp).toLocaleTimeString([], {
          hour: "2-digit", minute: "2-digit", second: "2-digit",
        }),
      );
    } catch {
      setFetchError("Could not fetch live prices");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const positionMap = useMemo(
    () => new Map((positions?.positions ?? []).map((p) => [p.id, p])),
    [positions],
  );

  const portfolioAssets = useMemo((): AssetPerfEntry[] => {
    const executionDate = positions?.executionDate;
    return (privateData?.latestWeights ?? []).flatMap((w) => {
      const pos = positionMap.get(w.coin);
      const assetData = allAssets[w.coin];
      const executionPrice = pos?.executionPrice ?? 0;
      const amount = pos?.amount ?? 0;
      const allocation = pos?.allocation ?? 0;
      if (!executionPrice && !allocation) return [];

      let currentPrice: number;
      let totalReturn: number;
      let pnlDollar: number;

      const livePrice = livePrices?.[w.coin];
      if (livePrice && executionPrice > 0) {
        currentPrice = livePrice;
        totalReturn = (livePrice / executionPrice - 1) * 100;
        pnlDollar = amount * (livePrice - executionPrice);
      } else if (assetData?.dailyData.length) {
        // Baseline at execution date so return reflects since-execution, not since May 1
        const execPoint = executionDate
          ? assetData.dailyData.find((d) => d.date === executionDate)
          : undefined;
        const baseCumReturn = execPoint?.cumReturn ?? 1;
        const latestCumReturn = assetData.dailyData[assetData.dailyData.length - 1].cumReturn;
        const returnSinceExec = latestCumReturn / baseCumReturn - 1;
        currentPrice = executionPrice * (1 + returnSinceExec);
        totalReturn = returnSinceExec * 100;
        pnlDollar = allocation * returnSinceExec;
      } else {
        currentPrice = executionPrice;
        totalReturn = 0;
        pnlDollar = 0;
      }

      return [{
        id: w.coin,
        name: assetData?.displayName ?? w.coin.toUpperCase(),
        weight: w.weight,
        totalReturn: parseFloat(totalReturn.toFixed(2)),
        executionPrice,
        currentPrice: parseFloat(currentPrice.toFixed(currentPrice < 1 ? 6 : 2)),
        amount,
        allocation,
        pnlDollar: parseFloat(pnlDollar.toFixed(2)),
      }];
    });
  }, [privateData, allAssets, positionMap, livePrices, positions]);

  const totalDeployed = positions?.totalDeployed ?? 0;
  const totalPnlDollar = portfolioAssets.reduce((s, a) => s + a.pnlDollar, 0);
  const totalPnlPct = totalDeployed > 0 ? (totalPnlDollar / totalDeployed) * 100 : 0;
  const portfolioLiveReturn = totalPnlPct / 100;
  const isLive = livePrices !== null;

  const inceptionFundSize = positions?.inceptionFundSize ?? totalDeployed;
  const rebalanceHistory = positions?.rebalanceHistory ?? [];

  // Net invested capital: what the investor has put in minus withdrawals — used for P&L
  const totalCashFlows = rebalanceHistory.reduce((s, e) => s + e.cashFlow, 0);
  const netInvestedCapital = inceptionFundSize + totalCashFlows;

  // Cash portion: what's uninvested after the last rebalance.
  // Derived from (fund value after that rebalance's cash flow) - deployed.
  // Without rebalance history we fall back to inception split.
  const lastRebalance = rebalanceHistory.length > 0 ? rebalanceHistory[rebalanceHistory.length - 1] : null;
  const fundValueAfterLastCF = lastRebalance?.fundValueBeforeCashFlow != null
    ? lastRebalance.fundValueBeforeCashFlow + lastRebalance.cashFlow
    : inceptionFundSize;
  const cashPortion = fundValueAfterLastCF - totalDeployed;

  const wholeFundCurrentValue = totalDeployed + totalPnlDollar + cashPortion;
  const wholeFundPnl = wholeFundCurrentValue - netInvestedCapital;

  // TWR chains returns across rebalance periods, eliminating cash-flow distortion.
  // Falls back to simple return if any period is missing fundValueBeforeCashFlow.
  const twrRaw = computeTWR(inceptionFundSize, rebalanceHistory, wholeFundCurrentValue);
  const wholeFundReturnPct = twrRaw !== null
    ? twrRaw * 100
    : netInvestedCapital > 0 ? (wholeFundPnl / netInvestedCapital) * 100 : 0;
  const isTWR = twrRaw !== null;

  // Deployed-only return (current positions vs their execution cost)
  const inceptionReturnPct = totalDeployed > 0 ? (totalPnlDollar / totalDeployed) * 100 : 0;

  const btcPos = positionMap.get("bitcoin");
  const btcLive = livePrices?.["bitcoin"];
  const btcReturn = btcPos && btcLive
    ? btcLive / btcPos.executionPrice - 1
    : (btcData?.dailyData.at(-1)?.cumReturn ?? 1) - 1;

  // ── From-inception returns (May 1 start) for metric cards ─────────────
  const inceptionStartDate = positions?.inceptionDate ?? latestRebalanceDate;

  const privateFundInceptionReturn = useMemo(() => {
    if (!privateData?.dailyData.length) return 0;
    return (privateData.dailyData[privateData.dailyData.length - 1].cumReturn - 1) * 100;
  }, [privateData]);

  const btcInceptionReturn = useMemo(() => {
    if (!btcData?.dailyData.length) return 0;
    return (btcData.dailyData[btcData.dailyData.length - 1].cumReturn - 1) * 100;
  }, [btcData]);

  const combinedInceptionReturn = useMemo(() => {
    if (!privateData?.dailyData.length) return 0;
    let val = 1;
    for (const d of privateData.dailyData) val *= 1 + 0.5 * d.return;
    return (val - 1) * 100;
  }, [privateData]);

  // ── Client-side Sharpe + Max DD for Combined and Bitcoin ─────────────────
  const combinedMetrics = useMemo(() => {
    const data = privateData?.dailyData ?? [];
    if (data.length < 3) return { sharpe: null as number | null, maxDrawdown: 0 };
    const rets = data.map(d => 0.5 * d.return);
    let cum = 1, peak = 1, maxDD = 0;
    for (const r of rets) {
      cum *= (1 + r);
      if (cum > peak) peak = cum;
      const dd = cum / peak - 1;
      if (dd < maxDD) maxDD = dd;
    }
    const n = rets.length;
    const mean = rets.reduce((s, r) => s + r, 0) / n;
    const std = Math.sqrt(rets.reduce((s, r) => s + (r - mean) ** 2, 0) / (n - 1));
    const annRet = (Math.pow(cum, 365 / n) - 1);
    const annVol = std * Math.sqrt(365);
    const sharpe = annVol > 0 ? annRet / annVol : null;
    return {
      sharpe: sharpe !== null && isFinite(sharpe) ? parseFloat(sharpe.toFixed(4)) : null,
      maxDrawdown: parseFloat((maxDD * 100).toFixed(2)),
    };
  }, [privateData]);

  const btcMetrics = useMemo(() => {
    const data = btcData?.dailyData ?? [];
    if (data.length < 3) return { sharpe: null as number | null, maxDrawdown: 0 };
    const rets: number[] = [];
    for (let i = 1; i < data.length; i++)
      rets.push(data[i].cumReturn / data[i - 1].cumReturn - 1);
    let cum = 1, peak = 1, maxDD = 0;
    for (const r of rets) {
      cum *= (1 + r);
      if (cum > peak) peak = cum;
      const dd = cum / peak - 1;
      if (dd < maxDD) maxDD = dd;
    }
    const n = rets.length;
    const mean = rets.reduce((s, r) => s + r, 0) / n;
    const std = Math.sqrt(rets.reduce((s, r) => s + (r - mean) ** 2, 0) / (n - 1));
    const annRet = Math.pow(cum, 365 / n) - 1;
    const annVol = std * Math.sqrt(365);
    const sharpe = annVol > 0 ? annRet / annVol : null;
    return {
      sharpe: sharpe !== null && isFinite(sharpe) ? parseFloat(sharpe.toFixed(4)) : null,
      maxDrawdown: parseFloat((maxDD * 100).toFixed(2)),
    };
  }, [btcData]);

  // ── Comparison table ────────────────────────────────────────────────────
  const comparisonRows = useMemo((): CompRow[] => {
    const btcPct = parseFloat(btcInceptionReturn.toFixed(2));
    const r = (key: string) => parseFloat(lastCumReturn(allStrategies[key]).toFixed(2));
    return [
      { type: "section", label: "Simple Benchmarks",        color: "#6b7280" },
      { type: "data",    label: "Bitcoin",                   color: "#f97316", mcap: btcPct,      liq: btcPct },
      { type: "data",    label: "1/N Equal",                 color: "#f472b6", mcap: r("onn_m"),  liq: r("onn_l") },
      { type: "section", label: "ETF Family (Construction)", color: "#fbbf24" },
      { type: "data",    label: "Base",                      color: "#fde68a", mcap: r("em_b"),   liq: r("el_b") },
      { type: "data",    label: "MinVar",                    color: "#fcd34d", mcap: r("em_mv"),  liq: r("el_mv") },
      { type: "data",    label: "+Liquidity",                color: "#fbbf24", mcap: r("em_lq"),  liq: r("el_lq") },
      { type: "data",    label: "+Tech",                     color: "#f59e0b", mcap: r("em_tc"),  liq: r("el_tc") },
      { type: "section", label: "PF Family (Construction)",  color: "#10b981" },
      { type: "data",    label: "Base",                      color: "#6ee7b7", mcap: r("pf_b"),   liq: r("pf_b_l") },
      { type: "data",    label: "+Size",                     color: "#34d399", mcap: r("pf_sz"),  liq: r("pf_sz_l") },
      { type: "data",    label: "+Liquidity",                color: "#10b981", mcap: r("pf_lq"),  liq: r("pf_lq_l") },
      { type: "data",    label: "+Tech",                     color: "#059669", mcap: r("pf_tc"),  liq: r("pf_tc_l") },
      { type: "data",    label: "+Quality",                  color: "#047857", mcap: r("pf_ql"),  liq: r("pf_ql_l") },
    ];
  }, [btcReturn, allStrategies]);

  // ── Asset breakdown for selected strategy ──────────────────────────────
  const activeStageWeights = useMemo(() => {
    const group = STRAT_GROUPS.find((g) => g.key === stratGroup);
    const stage = group?.stages.find((s) => s.key === stratStage) ?? group?.stages.at(-1);
    const strat = stage ? allStrategies[stage.key] : undefined;
    return { strat, stage };
  }, [stratGroup, stratStage, allStrategies]);

  const assetBreakdown = useMemo((): AssetBreakdownRow[] => {
    const { strat } = activeStageWeights;
    if (!strat?.latestWeights) return [];
    const executionDate = positions?.executionDate;
    return strat.latestWeights
      .filter((w) => w.weight > 0)
      .map((w) => {
        const asset = allAssets[w.coin];
        const lastData = asset?.dailyData.at(-1);
        let returnPct: number | null = null;
        if (lastData) {
          const execPoint = executionDate
            ? asset?.dailyData.find((d) => d.date === executionDate)
            : undefined;
          const baseCumReturn = execPoint?.cumReturn ?? 1;
          returnPct = parseFloat(((lastData.cumReturn / baseCumReturn - 1) * 100).toFixed(2));
        }
        return {
          id: w.coin,
          name: asset?.displayName ?? w.coin,
          weightPct: w.weight,
          returnPct,
          contribution: returnPct !== null ? parseFloat(((w.weight / 100) * returnPct).toFixed(3)) : null,
          available: !!asset,
        };
      });
  }, [activeStageWeights, allAssets, positions]);

  const breakdownTotalWeight = useMemo(
    () => parseFloat(assetBreakdown.filter((r) => r.available).reduce((s, r) => s + r.weightPct, 0).toFixed(2)),
    [assetBreakdown],
  );
  const breakdownTotalReturn = useMemo(
    () => parseFloat(assetBreakdown.reduce((s, r) => s + (r.contribution ?? 0), 0).toFixed(3)),
    [assetBreakdown],
  );

  // ── Chart series (all from performance.json) ───────────────────────────
  const chartSeries = useMemo((): ChartPoint[] => {
    const dateMap = new Map<string, ChartPoint>();

    // Helper: add any strategy series by key
    const addSeries = (chartKey: string, stratKey: string) => {
      const data = allStrategies[stratKey]?.dailyData ?? [];
      for (const d of data) {
        if (!dateMap.has(d.date)) dateMap.set(d.date, { date: d.date });
        dateMap.get(d.date)![chartKey] = parseFloat((d.cumReturn * 1000).toFixed(4));
      }
    };

    // Private Fund Index + combined (50/50 signal)
    if (privateData) {
      let combinedValue = 1000;
      for (const d of privateData.dailyData) {
        if (!dateMap.has(d.date)) dateMap.set(d.date, { date: d.date });
        const pt = dateMap.get(d.date)!;
        pt.index = d.cumReturn * 1000;
        combinedValue *= 1 + 0.5 * d.return;
        pt.combined = parseFloat(combinedValue.toFixed(4));
      }
    }

    // Bitcoin
    if (btcData) {
      for (const d of btcData.dailyData) {
        if (!dateMap.has(d.date)) dateMap.set(d.date, { date: d.date });
        dateMap.get(d.date)!.btc = parseFloat((d.cumReturn * 1000).toFixed(4));
      }
    }

    // PF family
    addSeries("pf_b",  "pf_b");
    addSeries("pf_sz", "pf_sz");
    addSeries("pf_lq", "pf_lq");
    addSeries("pf_tc", "pf_tc");
    addSeries("pf_ql", "pf_ql");

    // ETF MCAP family
    addSeries("em_b",  "em_b");
    addSeries("em_mv", "em_mv");
    addSeries("em_lq", "em_lq");
    addSeries("em_tc", "em_tc");

    // ETF Liq family
    addSeries("el_b",  "el_b");
    addSeries("el_mv", "el_mv");
    addSeries("el_lq", "el_lq");
    addSeries("el_tc", "el_tc");

    // 1/N benchmarks
    addSeries("onn_m", "onn_m");
    addSeries("onn_l", "onn_l");

    // Live point for Private Fund + BTC
    if (isLive) {
      const today = new Date().toISOString().split("T")[0];
      if (!dateMap.has(today)) dateMap.set(today, { date: today });
      const pt = dateMap.get(today)!;
      pt.index    = parseFloat((1000 * (1 + portfolioLiveReturn)).toFixed(4));
      pt.combined = parseFloat((1000 * (1 + 0.5 * portfolioLiveReturn)).toFixed(4));
      if (btcPos && btcLive) pt.btc = parseFloat((1000 * (btcLive / btcPos.executionPrice)).toFixed(4));
    }

    return Array.from(dateMap.values()).sort((a, b) => (a.date as string).localeCompare(b.date as string));
  }, [privateData, btcData, allStrategies, isLive, portfolioLiveReturn, btcPos, btcLive]);

  const activeSeries = useMemo(
    () => [
      ...ALWAYS_SERIES,
      ...PF_SERIES,
      ...(universeMode === "mcap" ? ETF_MCAP_SERIES : ETF_LIQ_SERIES),
    ],
    [universeMode],
  );

  const topMovers = useMemo(
    () => [...portfolioAssets].sort((a, b) => b.totalReturn - a.totalReturn),
    [portfolioAssets],
  );

  const hasData = !!privateData;

  return (
    <div className="min-h-screen bg-[#0f1117] text-white">
      <header className="border-b border-[#2d3144] px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between flex-wrap gap-3">
          <h1 className="text-2xl font-bold tracking-tight">Private Fund Strategy</h1>
          <div className="flex items-center gap-3">
            <div className="text-right text-sm">
              {lastFetched && (
                <div className="flex items-center gap-1.5 justify-end text-gray-400 text-xs">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                  Live · {lastFetched}
                </div>
              )}
              {fetchError && <div className="text-red-400 text-xs">{fetchError}</div>}
              {lastUpdated && <div className="text-gray-600 text-xs">Data updated {lastUpdated}</div>}
            </div>
            <button
              onClick={refresh}
              disabled={loading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
              style={{
                background: loading ? "#2d3144" : "#8b5cf622",
                border: "1px solid #8b5cf644",
                color: loading ? "#6b7280" : "#a78bfa",
                cursor: loading ? "not-allowed" : "pointer",
              }}
            >
              <svg
                className={loading ? "animate-spin" : ""}
                width="12" height="12" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
              >
                <path d="M21 12a9 9 0 1 1-6.219-8.56" />
              </svg>
              {loading ? "Fetching…" : "Refresh"}
            </button>
            <Nav />
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8 space-y-10">
        {!hasData ? (
          <div className="text-center py-24 text-gray-400">No performance data yet.</div>
        ) : (
          <>
            {positions && (
              <section>
                <div className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144] flex flex-wrap gap-6 items-end">
                  <div>
                    <div className="text-xs text-gray-500 mb-1">Inception Capital</div>
                    <div className="text-xl font-bold text-white font-mono">${fmtUsd(inceptionFundSize)}</div>
                    {totalCashFlows !== 0 && (
                      <div className="text-xs mt-0.5" style={{ color: totalCashFlows < 0 ? "#f87171" : "#4ade80" }}>
                        {totalCashFlows < 0 ? "−" : "+"}${fmtUsd(Math.abs(totalCashFlows))} withdrawals
                      </div>
                    )}
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 mb-1">Deployed (50% signal)</div>
                    <div className="text-xl font-bold text-white font-mono">${fmtUsd(totalDeployed)}</div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 mb-1">Current Value {isLive ? "· live" : "· eod"}</div>
                    <div className="text-xl font-bold text-white font-mono">${fmtUsd(wholeFundCurrentValue)}</div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 mb-1">Total P&amp;L</div>
                    <div className="text-xl font-bold font-mono" style={{ color: wholeFundPnl >= 0 ? "#4ade80" : "#f87171" }}>
                      {wholeFundPnl >= 0 ? "+" : "−"}${fmtUsd(Math.abs(wholeFundPnl))}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 mb-1">
                      {isTWR ? "TWR since" : "Return since"} {positions.inceptionDate}
                    </div>
                    <div className="text-xl font-bold font-mono" style={{ color: wholeFundReturnPct >= 0 ? "#4ade80" : "#f87171" }}>
                      {wholeFundReturnPct >= 0 ? "+" : ""}{wholeFundReturnPct.toFixed(2)}%
                    </div>
                    {!isTWR && (
                      <div className="text-xs text-yellow-500 mt-0.5">fill fundValueBeforeCashFlow</div>
                    )}
                  </div>
                  <div className="ml-auto text-xs text-gray-600 self-end">last rebalance: {positions.executionDate}</div>
                </div>
              </section>
            )}

            <section>
              <SectionHeader
                title="Performance"
                subtitle={`since ${inceptionStartDate} · end-of-day`}
              />
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {[
                  {
                    label: "Private Fund", color: "#8b5cf6",
                    totalReturn: parseFloat(wholeFundReturnPct.toFixed(2)),
                    sharpe: combinedMetrics.sharpe,
                    maxDrawdown: combinedMetrics.maxDrawdown,
                  },
                  {
                    label: "Deployed Return", color: "#06b6d4",
                    totalReturn: parseFloat(inceptionReturnPct.toFixed(2)),
                    sharpe: privateData?.metrics?.sharpe ?? null,
                    maxDrawdown: privateData?.metrics?.maxDrawdown ?? 0,
                  },
                  {
                    label: "Bitcoin B&H", color: "#f97316",
                    totalReturn: parseFloat(btcInceptionReturn.toFixed(2)),
                    sharpe: btcMetrics.sharpe,
                    maxDrawdown: btcMetrics.maxDrawdown,
                  },
                ].map((m) => (
                  <MetricCard key={m.label} m={{ ...m, annReturn: 0, volatility: 0 }} />
                ))}
              </div>
            </section>

            <section>
              <SectionHeader
                title="Construction Stage Comparison"
                subtitle="MCAP Universe vs Liquidity Universe · PF and ETF families"
              />
              <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[#2d3144]">
                      <th className="text-left px-4 py-3 text-gray-400 font-medium text-xs">Strategy / Stage</th>
                      <th className="text-right px-4 py-3 text-xs font-medium" style={{ color: "#60a5fa" }}>MCAP Universe</th>
                      <th className="text-right px-4 py-3 text-xs font-medium" style={{ color: "#38bdf8" }}>Liq Universe</th>
                      <th className="text-right px-4 py-3 text-gray-400 font-medium text-xs">Δ</th>
                      <th className="text-center px-4 py-3 text-gray-400 font-medium text-xs">Better</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparisonRows.map((row, i) => {
                      if (row.type === "section") {
                        return (
                          <tr key={`sec-${i}`} className="border-b border-[#2d3144]">
                            <td colSpan={5} className="px-4 py-2">
                              <span className="text-xs font-semibold tracking-wider uppercase" style={{ color: row.color }}>
                                {row.label}
                              </span>
                            </td>
                          </tr>
                        );
                      }
                      const diff = parseFloat((row.liq - row.mcap).toFixed(2));
                      const liqWins = diff > 0;
                      const mcapWins = diff < 0;
                      const isSame = diff === 0;
                      return (
                        <tr key={row.label + i} className="border-b border-[#2d3144] hover:bg-[#ffffff04]">
                          <td className="px-4 py-2.5 pl-6 flex items-center gap-2.5">
                            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: row.color }} />
                            <span className="text-gray-200">{row.label}</span>
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono font-medium"
                            style={{ color: row.mcap >= 0 ? "#4ade80" : "#f87171" }}>
                            {row.mcap >= 0 ? "+" : ""}{row.mcap.toFixed(2)}%
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono font-medium"
                            style={{ color: row.liq >= 0 ? "#4ade80" : "#f87171" }}>
                            {row.liq >= 0 ? "+" : ""}{row.liq.toFixed(2)}%
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono text-xs"
                            style={{ color: isSame ? "#4b5563" : diff > 0 ? "#86efac" : "#fca5a5" }}>
                            {isSame ? "—" : `${diff > 0 ? "+" : ""}${diff.toFixed(2)}%`}
                          </td>
                          <td className="px-4 py-2.5 text-center">
                            {liqWins && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium"
                                style={{ background: "#38bdf820", color: "#38bdf8", border: "1px solid #38bdf840" }}>
                                Liq ↑
                              </span>
                            )}
                            {mcapWins && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium"
                                style={{ background: "#3b82f620", color: "#60a5fa", border: "1px solid #3b82f640" }}>
                                MCAP ↑
                              </span>
                            )}
                            {isSame && <span className="text-gray-600 text-xs">Same</span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <div className="px-4 py-2 border-t border-[#2d3144] text-xs text-gray-600">
                  Returns since first rebalance date · computed server-side per-period using weights active at each rebalance
                </div>
              </div>
            </section>

            <section>
              <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
                <div>
                  <h2 className="text-lg font-semibold">Index Performance (Base 1000)</h2>
                  <p className="text-sm text-gray-500 mt-0.5">
                    {universeMode === "mcap"
                      ? "MCAP Universe · ETF family in amber · PF family in emerald"
                      : "Liquidity Universe · ETF family in sky · PF family in emerald"}
                  </p>
                </div>
                <div className="flex items-center rounded-lg overflow-hidden border border-[#2d3144] text-xs font-medium">
                  {(["mcap", "liquidity"] as UniverseMode[]).map((mode) => {
                    const active = universeMode === mode;
                    return (
                      <button
                        key={mode}
                        onClick={() => setUniverseMode(mode)}
                        className="px-4 py-2 transition-all"
                        style={{
                          background: active ? "#8b5cf6" : "#1a1d29",
                          color: active ? "#fff" : "#6b7280",
                        }}
                      >
                        {mode === "mcap" ? "MCAP Universe" : "Liq Universe"}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144]">
                <PrivateFundIndexChart chartSeries={chartSeries} series={activeSeries} />
              </div>
            </section>

            <section>
              <SectionHeader
                title="Asset Breakdown by Strategy"
                subtitle="individual weights and returns for each construction stage"
              />
              <div className="flex flex-col gap-2 mb-3">
                <div className="flex gap-2 flex-wrap">
                  {STRAT_GROUPS.map((g) => {
                    const active = stratGroup === g.key;
                    return (
                      <button
                        key={g.key}
                        onClick={() => {
                          setStratGroup(g.key);
                          setStratStage(g.stages.at(-1)!.key);
                        }}
                        className="px-3 py-1 rounded-lg text-xs font-semibold transition-all"
                        style={{
                          background: active ? `${g.color}30` : "#1a1d29",
                          border: `1px solid ${active ? g.color : "#2d3144"}`,
                          color: active ? g.color : "#6b7280",
                        }}
                      >
                        {g.label}
                      </button>
                    );
                  })}
                </div>
                <div className="flex gap-1.5 flex-wrap">
                  {STRAT_GROUPS.find((g) => g.key === stratGroup)?.stages.map((s) => {
                    const active = stratStage === s.key;
                    return (
                      <button
                        key={s.key}
                        onClick={() => setStratStage(s.key)}
                        className="px-3 py-1 rounded-md text-xs font-medium transition-all"
                        style={{
                          background: active ? `${s.color}25` : "transparent",
                          border: `1px solid ${active ? s.color : "#2d3144"}`,
                          color: active ? s.color : "#9ca3af",
                        }}
                      >
                        {s.label}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[#2d3144]">
                      <th className="text-left px-4 py-3 text-gray-400 font-medium text-xs">#</th>
                      <th className="text-left px-4 py-3 text-gray-400 font-medium text-xs">Asset</th>
                      <th className="text-right px-4 py-3 text-gray-400 font-medium text-xs">Weight</th>
                      <th className="text-right px-4 py-3 text-gray-400 font-medium text-xs">Return (since {positions?.executionDate ?? "last rebalance"})</th>
                      <th className="text-right px-4 py-3 text-gray-400 font-medium text-xs">Contribution</th>
                    </tr>
                  </thead>
                  <tbody>
                    {assetBreakdown.map((row, i) => {
                      const availIdx = assetBreakdown.slice(0, i).filter((r) => r.available).length;
                      return (
                        <tr
                          key={row.id}
                          className="border-b border-[#2d3144] hover:bg-[#ffffff04]"
                          style={{ opacity: row.available ? 1 : 0.38 }}
                        >
                          <td className="px-4 py-2.5 text-gray-600 text-xs">
                            {row.available ? availIdx + 1 : "—"}
                          </td>
                          <td className="px-4 py-2.5 font-medium text-xs" style={{ color: row.available ? "#e5e7eb" : "#6b7280" }}>
                            {row.name}
                            {!row.available && <span className="ml-1.5 text-xs text-gray-600 font-normal">(no data)</span>}
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono text-xs"
                            style={{ color: row.available ? (activeStageWeights.stage?.color ?? "#9ca3af") : "#4b5563" }}>
                            {row.weightPct.toFixed(2)}%
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono font-medium text-xs"
                            style={{ color: row.returnPct === null ? "#4b5563" : row.returnPct >= 0 ? "#4ade80" : "#f87171" }}>
                            {row.returnPct === null ? "—" : `${row.returnPct >= 0 ? "+" : ""}${row.returnPct.toFixed(2)}%`}
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono text-xs"
                            style={{ color: row.contribution === null ? "#4b5563" : row.contribution >= 0 ? "#86efac" : "#fca5a5" }}>
                            {row.contribution === null ? "—" : `${row.contribution >= 0 ? "+" : ""}${row.contribution.toFixed(3)}%`}
                          </td>
                        </tr>
                      );
                    })}
                    <tr className="border-t-2 border-[#3d4166] bg-[#ffffff04]">
                      <td className="px-4 py-2.5" />
                      <td className="px-4 py-2.5 text-gray-300 font-semibold text-xs">Available total</td>
                      <td className="px-4 py-2.5 text-right font-mono text-xs" style={{ color: activeStageWeights.stage?.color ?? "#9ca3af" }}>
                        {breakdownTotalWeight.toFixed(2)}%
                      </td>
                      <td className="px-4 py-2.5" />
                      <td className="px-4 py-2.5 text-right font-mono font-bold text-xs"
                        style={{ color: breakdownTotalReturn >= 0 ? "#4ade80" : "#f87171" }}>
                        {breakdownTotalReturn >= 0 ? "+" : ""}{breakdownTotalReturn.toFixed(3)}%
                      </td>
                    </tr>
                  </tbody>
                </table>
                <div className="px-4 py-2 border-t border-[#2d3144] text-xs text-gray-600">
                  Weights from latest rebalance · grayed rows = asset not in performance data · Contribution = (weight/100) × return
                </div>
              </div>
            </section>

            {portfolioAssets.length > 0 && (
              <section>
                <SectionHeader
                  title="Individual Asset Performance"
                  subtitle={`% return from execution price${isLive ? " · live" : " · eod"}`}
                />
                <div className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144]">
                  <PrivateFundAssetPerf assets={portfolioAssets} />
                </div>
              </section>
            )}

            {topMovers.length > 0 && (
              <section>
                <SectionHeader
                  title="Top Movers Within Signal"
                  subtitle={`ranked by return from execution price${isLive ? " · live" : " · eod"}`}
                />
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {[
                    { label: "Top Gainers", color: "#4ade80", data: topMovers.slice(0, 8) },
                    { label: "Laggards",    color: "#f87171", data: [...topMovers].reverse().slice(0, 8) },
                  ].map(({ label, color, data }) => (
                    <div key={label} className="bg-[#1a1d29] rounded-xl border border-[#2d3144] overflow-hidden">
                      <div className="px-4 py-3 border-b border-[#2d3144] flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full" style={{ background: color }} />
                        <span className="text-sm font-medium" style={{ color }}>{label}</span>
                      </div>
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-[#2d3144]">
                            <th className="text-left px-4 py-2 text-gray-500 font-medium text-xs">#</th>
                            <th className="text-left px-4 py-2 text-gray-500 font-medium text-xs">Asset</th>
                            <th className="text-right px-4 py-2 text-gray-500 font-medium text-xs">Weight</th>
                            <th className="text-right px-4 py-2 text-gray-500 font-medium text-xs">P&amp;L $</th>
                            <th className="text-right px-4 py-2 text-gray-500 font-medium text-xs">Return</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.map((a, i) => (
                            <tr key={a.id} className="border-b border-[#2d3144] hover:bg-[#ffffff04]">
                              <td className="px-4 py-2 text-gray-600 text-xs">{i + 1}</td>
                              <td className="px-4 py-2 text-gray-200">{a.name}</td>
                              <td className="px-4 py-2 text-right text-gray-400 font-mono text-xs">{a.weight.toFixed(1)}%</td>
                              <td className="px-4 py-2 text-right font-mono font-medium text-xs" style={{ color: a.pnlDollar >= 0 ? "#4ade80" : "#f87171" }}>
                                {a.pnlDollar >= 0 ? "+" : "−"}${fmtUsd(Math.abs(a.pnlDollar))}
                              </td>
                              <td className="px-4 py-2 text-right font-mono font-medium text-xs" style={{ color: a.totalReturn >= 0 ? "#4ade80" : "#f87171" }}>
                                {a.totalReturn >= 0 ? "+" : ""}{a.totalReturn.toFixed(2)}%
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {portfolioAssets.length > 0 && positions && (
              <section>
                <SectionHeader title="Positions" subtitle={`execution ${positions.executionDate}`} />
                <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-[#2d3144]">
                        <th className="text-left px-4 py-3 text-gray-400 font-medium text-xs">#</th>
                        <th className="text-left px-4 py-3 text-gray-400 font-medium text-xs">Asset</th>
                        <th className="text-right px-4 py-3 text-gray-400 font-medium text-xs">Weight</th>
                        <th className="text-right px-4 py-3 text-gray-400 font-medium text-xs">Exec Price</th>
                        <th className="text-right px-4 py-3 text-gray-400 font-medium text-xs">Live Price</th>
                        <th className="text-right px-4 py-3 text-gray-400 font-medium text-xs">Amount</th>
                        <th className="text-right px-4 py-3 text-gray-400 font-medium text-xs">Allocated $</th>
                        <th className="text-right px-4 py-3 text-gray-400 font-medium text-xs">P&amp;L $</th>
                        <th className="text-right px-4 py-3 text-gray-400 font-medium text-xs">Return %</th>
                      </tr>
                    </thead>
                    <tbody>
                      {portfolioAssets.map((a, i) => (
                        <tr key={a.id} className="border-b border-[#2d3144] hover:bg-[#ffffff04]">
                          <td className="px-4 py-2.5 text-gray-600 text-xs">{i + 1}</td>
                          <td className="px-4 py-2.5 text-gray-200 font-medium">
                            {a.name}
                            {isLive && livePrices?.[a.id] && (
                              <span className="ml-1.5 w-1 h-1 rounded-full bg-green-400 inline-block align-middle" />
                            )}
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono text-purple-300 text-xs">{a.weight.toFixed(2)}%</td>
                          <td className="px-4 py-2.5 text-right font-mono text-gray-500 text-xs">${fmtPrice(a.executionPrice)}</td>
                          <td className="px-4 py-2.5 text-right font-mono text-xs" style={{ color: isLive && livePrices?.[a.id] ? "#f1f5f9" : "#4b5563" }}>
                            {isLive && livePrices?.[a.id] ? `$${fmtPrice(a.currentPrice)}` : "—"}
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono text-gray-500 text-xs">
                            {a.amount.toLocaleString("en-US", { maximumFractionDigits: 4 })}
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono text-gray-400 text-xs">${fmtUsd(a.allocation)}</td>
                          <td className="px-4 py-2.5 text-right font-mono font-medium text-xs" style={{ color: a.pnlDollar >= 0 ? "#4ade80" : "#f87171" }}>
                            {a.pnlDollar >= 0 ? "+" : "−"}${fmtUsd(Math.abs(a.pnlDollar))}
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono font-medium text-xs" style={{ color: a.totalReturn >= 0 ? "#4ade80" : "#f87171" }}>
                            {a.totalReturn >= 0 ? "+" : ""}{a.totalReturn.toFixed(2)}%
                          </td>
                        </tr>
                      ))}
                      <tr className="border-t-2 border-[#3d4166] bg-[#ffffff04]">
                        <td className="px-4 py-2.5" />
                        <td className="px-4 py-2.5 text-gray-300 font-semibold text-xs">Total</td>
                        <td className="px-4 py-2.5 text-right font-mono text-purple-300 text-xs font-medium">
                          {portfolioAssets.reduce((s, a) => s + a.weight, 0).toFixed(1)}%
                        </td>
                        <td colSpan={3} />
                        <td className="px-4 py-2.5 text-right font-mono text-gray-200 text-xs font-medium">${fmtUsd(totalDeployed)}</td>
                        <td className="px-4 py-2.5 text-right font-mono font-bold text-xs" style={{ color: totalPnlDollar >= 0 ? "#4ade80" : "#f87171" }}>
                          {totalPnlDollar >= 0 ? "+" : "−"}${fmtUsd(Math.abs(totalPnlDollar))}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono font-bold text-xs" style={{ color: totalPnlPct >= 0 ? "#4ade80" : "#f87171" }}>
                          {totalPnlPct >= 0 ? "+" : ""}{totalPnlPct.toFixed(2)}%
                        </td>
                      </tr>
                    </tbody>
                  </table>
                  <div className="px-4 py-2 text-xs text-gray-600">
                    Crypto via CoinGecko · Stocks via Yahoo Finance · execution: {positions.executionDate}
                  </div>
                </div>
              </section>
            )}

            {positions && (
              <section>
                <SectionHeader title="Capital Events" subtitle="deposits and withdrawals since inception" />
                <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-[#2d3144]">
                        <th className="text-left px-4 py-3 text-gray-400 font-medium text-xs">#</th>
                        <th className="text-left px-4 py-3 text-gray-400 font-medium text-xs">Date</th>
                        <th className="text-left px-4 py-3 text-gray-400 font-medium text-xs">Type</th>
                        <th className="text-right px-4 py-3 text-gray-400 font-medium text-xs">Amount</th>
                        <th className="text-right px-4 py-3 text-gray-400 font-medium text-xs">Fund Value Before</th>
                        <th className="text-right px-4 py-3 text-gray-400 font-medium text-xs">Fund Value After</th>
                        <th className="text-right px-4 py-3 text-gray-400 font-medium text-xs">Running Capital</th>
                      </tr>
                    </thead>
                    <tbody>
                      {/* Inception deposit */}
                      <tr className="border-b border-[#2d3144] hover:bg-[#ffffff04]">
                        <td className="px-4 py-2.5 text-gray-600 text-xs">1</td>
                        <td className="px-4 py-2.5 font-mono text-xs text-gray-300">{positions.inceptionDate}</td>
                        <td className="px-4 py-2.5 text-xs">
                          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
                            style={{ background: "#4ade8020", color: "#4ade80", border: "1px solid #4ade8040" }}>
                            ↓ Deposit
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono font-medium text-xs text-green-400">
                          +${fmtUsd(inceptionFundSize)}
                        </td>
                        <td className="px-4 py-2.5 text-right text-gray-600 text-xs">—</td>
                        <td className="px-4 py-2.5 text-right font-mono text-xs text-gray-300">${fmtUsd(inceptionFundSize)}</td>
                        <td className="px-4 py-2.5 text-right font-mono text-xs text-gray-300">${fmtUsd(inceptionFundSize)}</td>
                      </tr>

                      {/* Rebalance cash flow events */}
                      {rebalanceHistory.filter((e) => e.cashFlow !== 0).map((e, i) => {
                        const isWithdrawal = e.cashFlow < 0;
                        const valueAfter = e.fundValueBeforeCashFlow != null ? e.fundValueBeforeCashFlow + e.cashFlow : null;
                        // running capital = inceptionFundSize + sum of cashFlows up to and including this entry
                        const runningCapital = inceptionFundSize + rebalanceHistory
                          .slice(0, rebalanceHistory.indexOf(e) + 1)
                          .reduce((s, x) => s + x.cashFlow, 0);
                        return (
                          <tr key={e.date + i} className="border-b border-[#2d3144] hover:bg-[#ffffff04]">
                            <td className="px-4 py-2.5 text-gray-600 text-xs">{i + 2}</td>
                            <td className="px-4 py-2.5 font-mono text-xs text-gray-300">{e.date}</td>
                            <td className="px-4 py-2.5 text-xs">
                              {isWithdrawal ? (
                                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
                                  style={{ background: "#f8717120", color: "#f87171", border: "1px solid #f8717140" }}>
                                  ↑ Withdrawal
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
                                  style={{ background: "#4ade8020", color: "#4ade80", border: "1px solid #4ade8040" }}>
                                  ↓ Deposit
                                </span>
                              )}
                            </td>
                            <td className="px-4 py-2.5 text-right font-mono font-medium text-xs"
                              style={{ color: isWithdrawal ? "#f87171" : "#4ade80" }}>
                              {isWithdrawal ? "−" : "+"}${fmtUsd(Math.abs(e.cashFlow))}
                            </td>
                            <td className="px-4 py-2.5 text-right font-mono text-xs text-gray-300">
                              {e.fundValueBeforeCashFlow != null ? `$${fmtUsd(e.fundValueBeforeCashFlow)}` : (
                                <span className="text-yellow-600">not recorded</span>
                              )}
                            </td>
                            <td className="px-4 py-2.5 text-right font-mono text-xs text-gray-300">
                              {valueAfter != null ? `$${fmtUsd(valueAfter)}` : "—"}
                            </td>
                            <td className="px-4 py-2.5 text-right font-mono text-xs text-gray-400">
                              ${fmtUsd(runningCapital)}
                            </td>
                          </tr>
                        );
                      })}

                      {/* Totals row */}
                      <tr className="border-t-2 border-[#3d4166] bg-[#ffffff04]">
                        <td className="px-4 py-2.5" />
                        <td className="px-4 py-2.5 text-gray-300 font-semibold text-xs" colSpan={2}>Net invested capital</td>
                        <td className="px-4 py-2.5 text-right font-mono font-bold text-xs"
                          style={{ color: totalCashFlows <= 0 ? "#f87171" : "#4ade80" }}>
                          {totalCashFlows !== 0 && (
                            <span className="text-gray-500 font-normal mr-2 text-xs">
                              {totalCashFlows < 0 ? "−" : "+"}${fmtUsd(Math.abs(totalCashFlows))} net flows
                            </span>
                          )}
                        </td>
                        <td colSpan={2} />
                        <td className="px-4 py-2.5 text-right font-mono font-bold text-xs text-white">
                          ${fmtUsd(netInvestedCapital)}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </section>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="flex items-baseline gap-2 mb-4">
      <h2 className="text-lg font-semibold">{title}</h2>
      {subtitle && <span className="text-sm text-gray-500">{subtitle}</span>}
    </div>
  );
}

function MetricCard({ m }: { m: MetricsSummary }) {
  return (
    <div
      className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144]"
      style={{ borderLeftWidth: 3, borderLeftColor: m.color }}
    >
      <div className="text-xs mb-1" style={{ color: m.color }}>{m.label}</div>
      <div className="text-2xl font-bold" style={{ color: m.totalReturn >= 0 ? "#4ade80" : "#f87171" }}>
        {m.totalReturn >= 0 ? "+" : ""}{m.totalReturn.toFixed(2)}%
      </div>
      <div className="text-xs text-gray-500 mt-0.5">Total Return</div>
      <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
        <div>
          <div className="text-gray-500">Sharpe</div>
          <div className="font-mono" style={{ color: m.sharpe === null ? "#6b7280" : m.sharpe >= 0 ? "#4ade80" : "#f87171" }}>
            {m.sharpe === null ? "—" : m.sharpe.toFixed(2)}
          </div>
        </div>
        <div>
          <div className="text-gray-500">Max DD</div>
          <div className="font-mono" style={{ color: m.maxDrawdown < 0 ? "#f87171" : "#6b7280" }}>
            {m.maxDrawdown < 0 ? `${m.maxDrawdown.toFixed(2)}%` : "—"}
          </div>
        </div>
      </div>
    </div>
  );
}
