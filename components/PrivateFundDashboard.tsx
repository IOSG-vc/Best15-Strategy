"use client";

import { useState, useCallback, useEffect, useMemo } from "react";
import dynamic from "next/dynamic";
import type { StrategyData, AssetData } from "@/lib/types";
import type { PositionsData } from "@/lib/loadPositions";
import type { ChartPoint, AssetPerfEntry, MetricsSummary } from "@/lib/privateFundTypes";
import { MCAP_WEIGHTS, VOLUME_WEIGHTS, LIQUIDITY_WEIGHTS } from "@/lib/benchmarkWeights";
import Nav from "./Nav";
import type { SeriesConfig } from "./PrivateFundIndexChart";

const PrivateFundIndexChart = dynamic(() => import("./PrivateFundIndexChart"), { ssr: false });
const PrivateFundAssetPerf = dynamic(() => import("./PrivateFundAssetPerf"), { ssr: false });

interface Props {
  privateData: StrategyData | undefined;
  btcData: AssetData | undefined;
  allAssets: Record<string, AssetData>;
  etfData: StrategyData | undefined;
  qualityData: StrategyData | undefined;
  riskData: StrategyData | undefined;
  positions: PositionsData | null;
  lastUpdated: string;
  latestRebalanceDate: string;
}

type PriceMap = Record<string, number>;

const CHART_SERIES: SeriesConfig[] = [
  { key: "index",     label: "Private Fund Index",    color: "#8b5cf6" },
  { key: "combined",  label: "Index + Signal (50/50)", color: "#06b6d4" },
  { key: "btc",       label: "Bitcoin",               color: "#f97316" },
  { key: "etf",       label: "ETF Weights",           color: "#f59e0b" },
  { key: "quality",   label: "Quality Factor",        color: "#10b981" },
  { key: "risk",      label: "Risk Factor",           color: "#ef4444" },
  { key: "mcap",      label: "MCAP Weighted",         color: "#3b82f6" },
  { key: "volume",    label: "Liquidity Weighted",    color: "#84cc16" },
  { key: "liquidity", label: "1/N Equal",             color: "#ec4899" },
];

function fmtPrice(p: number): string {
  if (p >= 1000) return p.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (p >= 1) return p.toFixed(3);
  return p.toFixed(6);
}

function fmtUsd(n: number, decimals = 0): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

// Compute weighted portfolio cumReturn series from allAssets
function computeWeightedSeries(
  weights: Record<string, number>,
  allAssets: Record<string, AssetData>,
): Map<string, number> {
  const result = new Map<string, number>();
  const assetDateMap = new Map<string, Map<string, number>>();
  for (const id of Object.keys(weights)) {
    const data = allAssets[id];
    if (!data) continue;
    const m = new Map<string, number>();
    for (const dp of data.dailyData) m.set(dp.date, dp.cumReturn);
    assetDateMap.set(id, m);
  }
  const dates = new Set<string>();
  Array.from(assetDateMap.values()).forEach((m) => m.forEach((_, d) => dates.add(d)));
  Array.from(dates).forEach((date) => {
    let val = 0;
    for (const [id, w] of Object.entries(weights)) {
      const cr = assetDateMap.get(id)?.get(date);
      if (cr !== undefined) val += w * cr;
    }
    result.set(date, val);
  });
  return result;
}

export default function PrivateFundDashboard({
  privateData,
  btcData,
  allAssets,
  etfData,
  qualityData,
  riskData,
  positions,
  lastUpdated,
  latestRebalanceDate,
}: Props) {
  const [livePrices, setLivePrices] = useState<PriceMap | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastFetched, setLastFetched] = useState<string | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);

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

  // Per-asset computation — live prices when available, cumReturn fallback
  const portfolioAssets = useMemo((): AssetPerfEntry[] => {
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
        const cumReturn = assetData.dailyData[assetData.dailyData.length - 1].cumReturn;
        currentPrice = executionPrice * cumReturn;
        totalReturn = (cumReturn - 1) * 100;
        pnlDollar = allocation * (cumReturn - 1);
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
  }, [privateData, allAssets, positionMap, livePrices]);

  const totalDeployed = positions?.totalDeployed ?? 0;
  const totalPnlDollar = portfolioAssets.reduce((s, a) => s + a.pnlDollar, 0);
  const totalPnlPct = totalDeployed > 0 ? (totalPnlDollar / totalDeployed) * 100 : 0;
  const portfolioLiveReturn = totalPnlPct / 100;
  const isLive = livePrices !== null;

  const btcPos = positionMap.get("bitcoin");
  const btcLive = livePrices?.["bitcoin"];
  const btcReturn = btcPos && btcLive
    ? btcLive / btcPos.executionPrice - 1
    : (btcData?.dailyData.at(-1)?.cumReturn ?? 1) - 1;

  // Pre-compute weighted benchmark series
  const mcapSeries = useMemo(() => computeWeightedSeries(MCAP_WEIGHTS, allAssets), [allAssets]);
  const volumeSeries = useMemo(() => computeWeightedSeries(VOLUME_WEIGHTS, allAssets), [allAssets]);
  const liquiditySeries = useMemo(() => computeWeightedSeries(LIQUIDITY_WEIGHTS, allAssets), [allAssets]);

  const mcapTotalReturn = useMemo(() => {
    const maxDate = Array.from(mcapSeries.keys()).sort().at(-1);
    const last = maxDate ? (mcapSeries.get(maxDate) ?? 1) : 1;
    return (last - 1) * 100;
  }, [mcapSeries]);

  const volumeTotalReturn = useMemo(() => {
    const maxDate = Array.from(volumeSeries.keys()).sort().at(-1);
    const last = maxDate ? (volumeSeries.get(maxDate) ?? 1) : 1;
    return (last - 1) * 100;
  }, [volumeSeries]);

  const liquidityTotalReturn = useMemo(() => {
    const maxDate = Array.from(liquiditySeries.keys()).sort().at(-1);
    const last = maxDate ? (liquiditySeries.get(maxDate) ?? 1) : 1;
    return (last - 1) * 100;
  }, [liquiditySeries]);

  // Primary metric cards
  const primaryMetrics: MetricsSummary[] = [
    {
      label: "Private Fund Index",
      color: "#8b5cf6",
      totalReturn: parseFloat((portfolioLiveReturn * 100).toFixed(2)),
      sharpe: null,
      maxDrawdown: privateData?.metrics?.maxDrawdown ?? 0,
      annReturn: 0,
      volatility: privateData?.metrics?.annVolatility ?? 0,
    },
    {
      label: "Index + Signal (50/50)",
      color: "#06b6d4",
      totalReturn: parseFloat((portfolioLiveReturn * 50).toFixed(2)),
      sharpe: null,
      maxDrawdown: 0,
      annReturn: 0,
      volatility: 0,
    },
    {
      label: "Bitcoin",
      color: "#f97316",
      totalReturn: parseFloat((btcReturn * 100).toFixed(2)),
      sharpe: null,
      maxDrawdown: 0,
      annReturn: 0,
      volatility: 0,
    },
  ];

  // Benchmark metric cards
  const benchmarkMetrics: MetricsSummary[] = [
    {
      label: "ETF Weights",
      color: "#f59e0b",
      totalReturn: parseFloat((((etfData?.dailyData.at(-1)?.cumReturn ?? 1) - 1) * 100).toFixed(2)),
      sharpe: null,
      maxDrawdown: etfData?.metrics?.maxDrawdown ?? 0,
      annReturn: 0,
      volatility: 0,
    },
    {
      label: "Quality Factor",
      color: "#10b981",
      totalReturn: parseFloat((((qualityData?.dailyData.at(-1)?.cumReturn ?? 1) - 1) * 100).toFixed(2)),
      sharpe: null,
      maxDrawdown: qualityData?.metrics?.maxDrawdown ?? 0,
      annReturn: 0,
      volatility: 0,
    },
    {
      label: "Risk Factor",
      color: "#ef4444",
      totalReturn: parseFloat((((riskData?.dailyData.at(-1)?.cumReturn ?? 1) - 1) * 100).toFixed(2)),
      sharpe: null,
      maxDrawdown: riskData?.metrics?.maxDrawdown ?? 0,
      annReturn: 0,
      volatility: 0,
    },
    {
      label: "MCAP Weighted",
      color: "#3b82f6",
      totalReturn: parseFloat(mcapTotalReturn.toFixed(2)),
      sharpe: null,
      maxDrawdown: 0,
      annReturn: 0,
      volatility: 0,
    },
    {
      label: "Liquidity Weighted",
      color: "#84cc16",
      totalReturn: parseFloat(volumeTotalReturn.toFixed(2)),
      sharpe: null,
      maxDrawdown: 0,
      annReturn: 0,
      volatility: 0,
    },
    {
      label: "1/N Equal",
      color: "#ec4899",
      totalReturn: parseFloat(liquidityTotalReturn.toFixed(2)),
      sharpe: null,
      maxDrawdown: 0,
      annReturn: 0,
      volatility: 0,
    },
  ];

  // Chart series: all strategies base-1000 from May 1
  const chartSeries = useMemo((): ChartPoint[] => {
    const dateMap = new Map<string, ChartPoint>();
    dateMap.set("2026-05-01", {
      date: "2026-05-01",
      index: 1000, combined: 1000,
      etf: 1000, quality: 1000, risk: 1000,
    });

    let combinedValue = 1000;
    if (privateData) {
      for (const d of privateData.dailyData) {
        if (!dateMap.has(d.date)) dateMap.set(d.date, { date: d.date });
        const pt = dateMap.get(d.date)!;
        pt.index = d.cumReturn * 1000;
        combinedValue *= 1 + 0.5 * d.return;
        pt.combined = parseFloat(combinedValue.toFixed(4));
      }
    }
    if (btcData) {
      for (const d of btcData.dailyData) {
        if (!dateMap.has(d.date)) dateMap.set(d.date, { date: d.date });
        dateMap.get(d.date)!.btc = parseFloat((d.cumReturn * 1000).toFixed(4));
      }
    }
    if (etfData) {
      for (const d of etfData.dailyData) {
        if (!dateMap.has(d.date)) dateMap.set(d.date, { date: d.date });
        dateMap.get(d.date)!.etf = parseFloat((d.cumReturn * 1000).toFixed(4));
      }
    }
    if (qualityData) {
      for (const d of qualityData.dailyData) {
        if (!dateMap.has(d.date)) dateMap.set(d.date, { date: d.date });
        dateMap.get(d.date)!.quality = parseFloat((d.cumReturn * 1000).toFixed(4));
      }
    }
    if (riskData) {
      for (const d of riskData.dailyData) {
        if (!dateMap.has(d.date)) dateMap.set(d.date, { date: d.date });
        dateMap.get(d.date)!.risk = parseFloat((d.cumReturn * 1000).toFixed(4));
      }
    }
    // Computed benchmark series from allAssets cumReturn
    mcapSeries.forEach((cr, date) => {
      if (!dateMap.has(date)) dateMap.set(date, { date });
      dateMap.get(date)!.mcap = parseFloat((cr * 1000).toFixed(4));
    });
    volumeSeries.forEach((cr, date) => {
      if (!dateMap.has(date)) dateMap.set(date, { date });
      dateMap.get(date)!.volume = parseFloat((cr * 1000).toFixed(4));
    });
    liquiditySeries.forEach((cr, date) => {
      if (!dateMap.has(date)) dateMap.set(date, { date });
      dateMap.get(date)!.liquidity = parseFloat((cr * 1000).toFixed(4));
    });
    // Live point for Private Fund and BTC
    if (isLive) {
      const today = new Date().toISOString().split("T")[0];
      if (!dateMap.has(today)) dateMap.set(today, { date: today });
      const pt = dateMap.get(today)!;
      pt.index = parseFloat((1000 * (1 + portfolioLiveReturn)).toFixed(4));
      pt.combined = parseFloat((1000 * (1 + 0.5 * portfolioLiveReturn)).toFixed(4));
      if (btcPos && btcLive) pt.btc = parseFloat((1000 * (btcLive / btcPos.executionPrice)).toFixed(4));
    }

    return Array.from(dateMap.values()).sort((a, b) => (a.date as string).localeCompare(b.date as string));
  }, [privateData, btcData, etfData, qualityData, riskData, mcapSeries, volumeSeries, liquiditySeries, isLive, portfolioLiveReturn, btcPos, btcLive]);

  const topMovers = useMemo(
    () => [...portfolioAssets].sort((a, b) => b.totalReturn - a.totalReturn),
    [portfolioAssets],
  );

  const hasData = !!privateData;

  return (
    <div className="min-h-screen bg-[#0f1117] text-white">
      <header className="border-b border-[#2d3144] px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Private Fund Strategy</h1>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-right text-sm">
              {lastFetched && (
                <div className="flex items-center gap-1.5 justify-end text-gray-400 text-xs">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                  Live · {lastFetched}
                </div>
              )}
              {fetchError && <div className="text-red-400 text-xs">{fetchError}</div>}
              {lastUpdated && (
                <div className="text-gray-600 text-xs">Data updated {lastUpdated}</div>
              )}
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
            {/* Portfolio summary banner */}
            {positions && (
              <section>
                <div className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144] flex flex-wrap gap-6 items-end">
                  <div>
                    <div className="text-xs text-gray-500 mb-1">Deployed Capital</div>
                    <div className="text-xl font-bold text-white font-mono">
                      ${fmtUsd(totalDeployed)}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 mb-1">Current Value</div>
                    <div className="text-xl font-bold text-white font-mono">
                      ${fmtUsd(totalDeployed + totalPnlDollar)}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 mb-1">Total P&amp;L</div>
                    <div className="text-xl font-bold font-mono" style={{ color: totalPnlDollar >= 0 ? "#4ade80" : "#f87171" }}>
                      {totalPnlDollar >= 0 ? "+" : "−"}${fmtUsd(Math.abs(totalPnlDollar))}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 mb-1">Return {isLive ? "(live)" : "(eod)"}</div>
                    <div className="text-xl font-bold font-mono" style={{ color: totalPnlPct >= 0 ? "#4ade80" : "#f87171" }}>
                      {totalPnlPct >= 0 ? "+" : ""}{totalPnlPct.toFixed(2)}%
                    </div>
                  </div>
                  <div className="ml-auto text-xs text-gray-600 self-end">
                    execution: {positions.executionDate}
                  </div>
                </div>
              </section>
            )}

            {/* Primary performance cards */}
            <section>
              <SectionHeader
                title="Performance"
                subtitle={`since ${positions?.executionDate ?? latestRebalanceDate} · ${isLive ? "live prices" : "end-of-day"}`}
              />
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                {primaryMetrics.map((m) => (
                  <MetricCard key={m.label} m={m} />
                ))}
              </div>
              {/* Benchmark cards */}
              <div className="mb-2">
                <span className="text-xs text-gray-500 uppercase tracking-wider">Benchmark Strategies</span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
                {benchmarkMetrics.map((m) => (
                  <MetricCardSmall key={m.label} m={m} />
                ))}
              </div>
            </section>

            {/* Chart */}
            <section>
              <SectionHeader
                title="Index Performance (Base 1000)"
                subtitle="All strategies vs benchmarks · toggle to compare"
              />
              <div className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144]">
                <PrivateFundIndexChart chartSeries={chartSeries} series={CHART_SERIES} />
              </div>
            </section>

            {/* Individual asset performance */}
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

            {/* Top movers */}
            {topMovers.length > 0 && (
              <section>
                <SectionHeader
                  title="Top Movers Within Signal"
                  subtitle={`ranked by return from execution price${isLive ? " · live" : " · eod"}`}
                />
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {[
                    { label: "Top Gainers", color: "#4ade80", data: topMovers.slice(0, 8) },
                    { label: "Laggards", color: "#f87171", data: [...topMovers].reverse().slice(0, 8) },
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

            {/* Positions table */}
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
          <div className="text-gray-500 font-mono">— <span className="text-gray-700">(30d min)</span></div>
        </div>
        <div>
          <div className="text-gray-500">Max DD</div>
          <div className="text-red-400 font-mono">
            {m.maxDrawdown > 0 ? `-${m.maxDrawdown.toFixed(2)}%` : "0%"}
          </div>
        </div>
      </div>
    </div>
  );
}

function MetricCardSmall({ m }: { m: MetricsSummary }) {
  return (
    <div
      className="bg-[#1a1d29] rounded-xl p-3 border border-[#2d3144]"
      style={{ borderLeftWidth: 3, borderLeftColor: m.color }}
    >
      <div className="text-xs mb-1 truncate" style={{ color: m.color }}>{m.label}</div>
      <div className="text-xl font-bold" style={{ color: m.totalReturn >= 0 ? "#4ade80" : "#f87171" }}>
        {m.totalReturn >= 0 ? "+" : ""}{m.totalReturn.toFixed(2)}%
      </div>
      <div className="text-xs text-gray-600 mt-0.5">Total Return</div>
      {m.maxDrawdown > 0 && (
        <div className="mt-2 text-xs">
          <span className="text-gray-600">Max DD </span>
          <span className="text-red-400 font-mono">-{m.maxDrawdown.toFixed(2)}%</span>
        </div>
      )}
    </div>
  );
}
