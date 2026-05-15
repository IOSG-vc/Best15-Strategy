"use client";

import { useState, useCallback, useEffect, useMemo } from "react";
import dynamic from "next/dynamic";
import type { StrategyData, AssetData } from "@/lib/types";
import type { PositionsData } from "@/lib/loadPositions";
import type { ChartPoint, AssetPerfEntry, MetricsSummary } from "@/lib/privateFundTypes";
import {
  MCAP_1N_WEIGHTS, LIQ_1N_WEIGHTS,
  ETF_MCAP_BASE, ETF_MCAP_MINVAR, ETF_MCAP_PLUS_LIQ, ETF_MCAP_PLUS_TECH,
  ETF_LIQ_BASE, ETF_LIQ_MINVAR, ETF_LIQ_PLUS_LIQ, ETF_LIQ_PLUS_TECH,
  PF_BASE, PF_PLUS_SIZE, PF_PLUS_LIQ, PF_PLUS_TECH, PF_PLUS_QUALITY,
} from "@/lib/benchmarkWeights";
import Nav from "./Nav";
import type { SeriesConfig } from "./PrivateFundIndexChart";

const PrivateFundIndexChart = dynamic(() => import("./PrivateFundIndexChart"), { ssr: false });
const PrivateFundAssetPerf = dynamic(() => import("./PrivateFundAssetPerf"), { ssr: false });

type UniverseMode = "mcap" | "liquidity";

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

// Permanent series (always shown regardless of mode)
const ALWAYS_SERIES: SeriesConfig[] = [
  { key: "index",    label: "Private Fund Index",    color: "#8b5cf6" },
  { key: "combined", label: "Index + Signal (50/50)", color: "#06b6d4" },
  { key: "btc",      label: "Bitcoin",               color: "#f97316" },
];

// PF family — same data in both modes, same colors
const PF_SERIES: SeriesConfig[] = [
  { key: "pf_b",  label: "PF Base",        color: "#6ee7b7" },
  { key: "pf_sz", label: "PF +Size",       color: "#34d399" },
  { key: "pf_lq", label: "PF +Liquidity",  color: "#10b981" },
  { key: "pf_tc", label: "PF +Tech",       color: "#059669" },
  { key: "pf_ql", label: "PF +Quality",    color: "#047857" },
];

// ETF MCAP universe benchmarks
const ETF_MCAP_SERIES: SeriesConfig[] = [
  { key: "em_b",  label: "ETF Base",       color: "#fde68a" },
  { key: "em_mv", label: "ETF MinVar",     color: "#fcd34d" },
  { key: "em_lq", label: "ETF +Liq",       color: "#fbbf24" },
  { key: "em_tc", label: "ETF +Tech",      color: "#f59e0b" },
  { key: "onn_m", label: "1/N (MCAP)",     color: "#f472b6" },
];

// ETF Liquidity universe benchmarks
const ETF_LIQ_SERIES: SeriesConfig[] = [
  { key: "el_b",  label: "ETF Base",       color: "#bae6fd" },
  { key: "el_mv", label: "ETF MinVar",     color: "#7dd3fc" },
  { key: "el_lq", label: "ETF +Liq",       color: "#38bdf8" },
  { key: "el_tc", label: "ETF +Tech",      color: "#0ea5e9" },
  { key: "onn_l", label: "1/N (Liq)",      color: "#c084fc" },
];

function fmtPrice(p: number): string {
  if (p >= 1000) return p.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (p >= 1) return p.toFixed(3);
  return p.toFixed(6);
}

function fmtUsd(n: number, decimals = 0): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

// Normalizes by available-weight sum so missing assets don't bias the result
function computeWeightedSeries(
  weights: Record<string, number>,
  allAssets: Record<string, AssetData>,
): Map<string, number> {
  const result = new Map<string, number>();
  const assetDateMap = new Map<string, Map<string, number>>();

  const availableWeightSum = Object.entries(weights).reduce(
    (sum, [id, w]) => sum + (allAssets[id] ? w : 0),
    0,
  );
  if (availableWeightSum === 0) return result;

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
      if (cr !== undefined) val += (w / availableWeightSum) * cr;
    }
    result.set(date, val);
  });
  return result;
}

function lastReturn(series: Map<string, number>): number {
  const maxDate = Array.from(series.keys()).sort().at(-1);
  const last = maxDate ? (series.get(maxDate) ?? 1) : 1;
  return (last - 1) * 100;
}

type CompRow =
  | { type: "section"; label: string; color: string }
  | { type: "data"; label: string; color: string; mcap: number; liq: number };

// ── Asset Breakdown helpers ────────────────────────────────────────────────────

type StrategyGroup = "pf" | "etf_mcap" | "etf_liq" | "onn";

interface StrategyStage {
  key: string;
  label: string;
  color: string;
  weights: Record<string, number>;
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
      { key: "pf_b",  label: "Base",     color: "#6ee7b7", weights: PF_BASE },
      { key: "pf_sz", label: "+Size",    color: "#34d399", weights: PF_PLUS_SIZE },
      { key: "pf_lq", label: "+Liq",     color: "#10b981", weights: PF_PLUS_LIQ },
      { key: "pf_tc", label: "+Tech",    color: "#059669", weights: PF_PLUS_TECH },
      { key: "pf_ql", label: "+Quality", color: "#047857", weights: PF_PLUS_QUALITY },
    ],
  },
  {
    key: "etf_mcap", label: "ETF (MCAP)", color: "#fbbf24",
    stages: [
      { key: "em_b",  label: "Base",   color: "#fde68a", weights: ETF_MCAP_BASE },
      { key: "em_mv", label: "MinVar", color: "#fcd34d", weights: ETF_MCAP_MINVAR },
      { key: "em_lq", label: "+Liq",   color: "#fbbf24", weights: ETF_MCAP_PLUS_LIQ },
      { key: "em_tc", label: "+Tech",  color: "#f59e0b", weights: ETF_MCAP_PLUS_TECH },
    ],
  },
  {
    key: "etf_liq", label: "ETF (Liq)", color: "#38bdf8",
    stages: [
      { key: "el_b",  label: "Base",   color: "#bae6fd", weights: ETF_LIQ_BASE },
      { key: "el_mv", label: "MinVar", color: "#7dd3fc", weights: ETF_LIQ_MINVAR },
      { key: "el_lq", label: "+Liq",   color: "#38bdf8", weights: ETF_LIQ_PLUS_LIQ },
      { key: "el_tc", label: "+Tech",  color: "#0ea5e9", weights: ETF_LIQ_PLUS_TECH },
    ],
  },
  {
    key: "onn", label: "1/N Equal", color: "#f472b6",
    stages: [
      { key: "onn_m", label: "MCAP", color: "#f472b6", weights: MCAP_1N_WEIGHTS },
      { key: "onn_l", label: "Liq",  color: "#c084fc", weights: LIQ_1N_WEIGHTS },
    ],
  },
];

interface AssetBreakdownRow {
  id: string;
  name: string;
  weightPct: number;           // raw weight from CSV × 100 (matches source file)
  returnPct: number | null;    // null when asset not in performance data
  contribution: number | null; // raw weight × return (null when return unavailable)
  available: boolean;
}

// Uses raw (non-normalized) weights so numbers match the source CSV directly.
// Missing assets (e.g. sky, aave, sui) appear as grayed-out rows.
function computeAssetBreakdown(
  weights: Record<string, number>,
  allAssets: Record<string, AssetData>,
): AssetBreakdownRow[] {
  return Object.entries(weights)
    .filter(([, w]) => w > 0)
    .map(([id, w]) => {
      const asset = allAssets[id];
      const lastData = asset?.dailyData.at(-1);
      const returnPct = lastData ? parseFloat(((lastData.cumReturn - 1) * 100).toFixed(2)) : null;
      const weightPct = parseFloat((w * 100).toFixed(2));
      return {
        id,
        name: asset?.displayName ?? id,
        weightPct,
        returnPct,
        contribution: returnPct !== null ? parseFloat((w * returnPct).toFixed(3)) : null,
        available: !!asset,
      };
    })
    .sort((a, b) => b.weightPct - a.weightPct);
}

export default function PrivateFundDashboard({
  privateData,
  btcData,
  allAssets,
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

  // ── 1/N series ─────────────────────────────────────────────────────────────
  const mcapOnnSeries = useMemo(() => computeWeightedSeries(MCAP_1N_WEIGHTS, allAssets), [allAssets]);
  const liqOnnSeries  = useMemo(() => computeWeightedSeries(LIQ_1N_WEIGHTS,  allAssets), [allAssets]);

  // ── ETF MCAP family ─────────────────────────────────────────────────────────
  const etfMBaseSeries    = useMemo(() => computeWeightedSeries(ETF_MCAP_BASE,      allAssets), [allAssets]);
  const etfMMinvarSeries  = useMemo(() => computeWeightedSeries(ETF_MCAP_MINVAR,    allAssets), [allAssets]);
  const etfMPlusLiqSeries = useMemo(() => computeWeightedSeries(ETF_MCAP_PLUS_LIQ,  allAssets), [allAssets]);
  const etfMPlusTechSeries= useMemo(() => computeWeightedSeries(ETF_MCAP_PLUS_TECH, allAssets), [allAssets]);

  // ── ETF Liquidity family ────────────────────────────────────────────────────
  const etfLBaseSeries    = useMemo(() => computeWeightedSeries(ETF_LIQ_BASE,      allAssets), [allAssets]);
  const etfLMinvarSeries  = useMemo(() => computeWeightedSeries(ETF_LIQ_MINVAR,    allAssets), [allAssets]);
  const etfLPlusLiqSeries = useMemo(() => computeWeightedSeries(ETF_LIQ_PLUS_LIQ,  allAssets), [allAssets]);
  const etfLPlusTechSeries= useMemo(() => computeWeightedSeries(ETF_LIQ_PLUS_TECH, allAssets), [allAssets]);

  // ── PF family (universe-agnostic) ───────────────────────────────────────────
  const pfBaseSeries      = useMemo(() => computeWeightedSeries(PF_BASE,         allAssets), [allAssets]);
  const pfPlusSizeSeries  = useMemo(() => computeWeightedSeries(PF_PLUS_SIZE,    allAssets), [allAssets]);
  const pfPlusLiqSeries   = useMemo(() => computeWeightedSeries(PF_PLUS_LIQ,     allAssets), [allAssets]);
  const pfPlusTechSeries  = useMemo(() => computeWeightedSeries(PF_PLUS_TECH,    allAssets), [allAssets]);
  const pfPlusQualSeries  = useMemo(() => computeWeightedSeries(PF_PLUS_QUALITY, allAssets), [allAssets]);

  // ── Comparison table rows ───────────────────────────────────────────────────
  const comparisonRows = useMemo((): CompRow[] => {
    const btcPct = parseFloat((btcReturn * 100).toFixed(2));
    const r = (s: Map<string, number>) => parseFloat(lastReturn(s).toFixed(2));
    return [
      { type: "section", label: "Simple Benchmarks",         color: "#6b7280" },
      { type: "data",    label: "Bitcoin",                    color: "#f97316", mcap: btcPct,                    liq: btcPct },
      { type: "data",    label: "1/N Equal",                  color: "#f472b6", mcap: r(mcapOnnSeries),          liq: r(liqOnnSeries) },
      { type: "section", label: "ETF Family (Construction)",  color: "#fbbf24" },
      { type: "data",    label: "Base",                       color: "#fde68a", mcap: r(etfMBaseSeries),         liq: r(etfLBaseSeries) },
      { type: "data",    label: "MinVar",                     color: "#fcd34d", mcap: r(etfMMinvarSeries),       liq: r(etfLMinvarSeries) },
      { type: "data",    label: "+Liquidity",                 color: "#fbbf24", mcap: r(etfMPlusLiqSeries),      liq: r(etfLPlusLiqSeries) },
      { type: "data",    label: "+Tech",                      color: "#f59e0b", mcap: r(etfMPlusTechSeries),     liq: r(etfLPlusTechSeries) },
      { type: "section", label: "PF Family (Construction)",   color: "#10b981" },
      { type: "data",    label: "Base",                       color: "#6ee7b7", mcap: r(pfBaseSeries),           liq: r(pfBaseSeries) },
      { type: "data",    label: "+Size",                      color: "#34d399", mcap: r(pfPlusSizeSeries),       liq: r(pfPlusSizeSeries) },
      { type: "data",    label: "+Liquidity",                 color: "#10b981", mcap: r(pfPlusLiqSeries),        liq: r(pfPlusLiqSeries) },
      { type: "data",    label: "+Tech",                      color: "#059669", mcap: r(pfPlusTechSeries),       liq: r(pfPlusTechSeries) },
      { type: "data",    label: "+Quality",                   color: "#047857", mcap: r(pfPlusQualSeries),       liq: r(pfPlusQualSeries) },
    ];
  }, [
    btcReturn, mcapOnnSeries, liqOnnSeries,
    etfMBaseSeries, etfMMinvarSeries, etfMPlusLiqSeries, etfMPlusTechSeries,
    etfLBaseSeries, etfLMinvarSeries, etfLPlusLiqSeries, etfLPlusTechSeries,
    pfBaseSeries, pfPlusSizeSeries, pfPlusLiqSeries, pfPlusTechSeries, pfPlusQualSeries,
  ]);

  // ── Asset breakdown for selected strategy ──────────────────────────────────
  const activeStratWeights = useMemo(() => {
    const group = STRAT_GROUPS.find((g) => g.key === stratGroup);
    const stage = group?.stages.find((s) => s.key === stratStage) ?? group?.stages.at(-1);
    return { weights: stage?.weights ?? {}, stage };
  }, [stratGroup, stratStage]);

  const assetBreakdown = useMemo(
    () => computeAssetBreakdown(activeStratWeights.weights, allAssets),
    [activeStratWeights.weights, allAssets],
  );

  const breakdownTotalWeight = useMemo(
    () => parseFloat(assetBreakdown.filter((r) => r.available).reduce((s, r) => s + r.weightPct, 0).toFixed(2)),
    [assetBreakdown],
  );

  const breakdownTotalReturn = useMemo(
    () => parseFloat(assetBreakdown.reduce((s, r) => s + (r.contribution ?? 0), 0).toFixed(3)),
    [assetBreakdown],
  );

  // ── Chart data (all series pre-computed) ───────────────────────────────────
  const chartSeries = useMemo((): ChartPoint[] => {
    const dateMap = new Map<string, ChartPoint>();
    dateMap.set("2026-05-01", { date: "2026-05-01", index: 1000, combined: 1000 });

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

    // 1/N
    mcapOnnSeries.forEach((cr, date) => {
      if (!dateMap.has(date)) dateMap.set(date, { date });
      dateMap.get(date)!.onn_m = parseFloat((cr * 1000).toFixed(4));
    });
    liqOnnSeries.forEach((cr, date) => {
      if (!dateMap.has(date)) dateMap.set(date, { date });
      dateMap.get(date)!.onn_l = parseFloat((cr * 1000).toFixed(4));
    });

    // ETF MCAP family
    etfMBaseSeries.forEach((cr, date) => {
      if (!dateMap.has(date)) dateMap.set(date, { date });
      dateMap.get(date)!.em_b = parseFloat((cr * 1000).toFixed(4));
    });
    etfMMinvarSeries.forEach((cr, date) => {
      if (!dateMap.has(date)) dateMap.set(date, { date });
      dateMap.get(date)!.em_mv = parseFloat((cr * 1000).toFixed(4));
    });
    etfMPlusLiqSeries.forEach((cr, date) => {
      if (!dateMap.has(date)) dateMap.set(date, { date });
      dateMap.get(date)!.em_lq = parseFloat((cr * 1000).toFixed(4));
    });
    etfMPlusTechSeries.forEach((cr, date) => {
      if (!dateMap.has(date)) dateMap.set(date, { date });
      dateMap.get(date)!.em_tc = parseFloat((cr * 1000).toFixed(4));
    });

    // ETF Liquidity family
    etfLBaseSeries.forEach((cr, date) => {
      if (!dateMap.has(date)) dateMap.set(date, { date });
      dateMap.get(date)!.el_b = parseFloat((cr * 1000).toFixed(4));
    });
    etfLMinvarSeries.forEach((cr, date) => {
      if (!dateMap.has(date)) dateMap.set(date, { date });
      dateMap.get(date)!.el_mv = parseFloat((cr * 1000).toFixed(4));
    });
    etfLPlusLiqSeries.forEach((cr, date) => {
      if (!dateMap.has(date)) dateMap.set(date, { date });
      dateMap.get(date)!.el_lq = parseFloat((cr * 1000).toFixed(4));
    });
    etfLPlusTechSeries.forEach((cr, date) => {
      if (!dateMap.has(date)) dateMap.set(date, { date });
      dateMap.get(date)!.el_tc = parseFloat((cr * 1000).toFixed(4));
    });

    // PF family
    pfBaseSeries.forEach((cr, date) => {
      if (!dateMap.has(date)) dateMap.set(date, { date });
      dateMap.get(date)!.pf_b = parseFloat((cr * 1000).toFixed(4));
    });
    pfPlusSizeSeries.forEach((cr, date) => {
      if (!dateMap.has(date)) dateMap.set(date, { date });
      dateMap.get(date)!.pf_sz = parseFloat((cr * 1000).toFixed(4));
    });
    pfPlusLiqSeries.forEach((cr, date) => {
      if (!dateMap.has(date)) dateMap.set(date, { date });
      dateMap.get(date)!.pf_lq = parseFloat((cr * 1000).toFixed(4));
    });
    pfPlusTechSeries.forEach((cr, date) => {
      if (!dateMap.has(date)) dateMap.set(date, { date });
      dateMap.get(date)!.pf_tc = parseFloat((cr * 1000).toFixed(4));
    });
    pfPlusQualSeries.forEach((cr, date) => {
      if (!dateMap.has(date)) dateMap.set(date, { date });
      dateMap.get(date)!.pf_ql = parseFloat((cr * 1000).toFixed(4));
    });

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
  }, [
    privateData, btcData,
    mcapOnnSeries, liqOnnSeries,
    etfMBaseSeries, etfMMinvarSeries, etfMPlusLiqSeries, etfMPlusTechSeries,
    etfLBaseSeries, etfLMinvarSeries, etfLPlusLiqSeries, etfLPlusTechSeries,
    pfBaseSeries, pfPlusSizeSeries, pfPlusLiqSeries, pfPlusTechSeries, pfPlusQualSeries,
    isLive, portfolioLiveReturn, btcPos, btcLive,
  ]);

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
            {/* Portfolio summary banner */}
            {positions && (
              <section>
                <div className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144] flex flex-wrap gap-6 items-end">
                  <div>
                    <div className="text-xs text-gray-500 mb-1">Deployed Capital</div>
                    <div className="text-xl font-bold text-white font-mono">${fmtUsd(totalDeployed)}</div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 mb-1">Current Value</div>
                    <div className="text-xl font-bold text-white font-mono">${fmtUsd(totalDeployed + totalPnlDollar)}</div>
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
                  <div className="ml-auto text-xs text-gray-600 self-end">execution: {positions.executionDate}</div>
                </div>
              </section>
            )}

            {/* Primary performance cards */}
            <section>
              <SectionHeader
                title="Performance"
                subtitle={`since ${positions?.executionDate ?? latestRebalanceDate} · ${isLive ? "live prices" : "end-of-day"}`}
              />
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {[
                  {
                    label: "Private Fund Index", color: "#8b5cf6",
                    totalReturn: parseFloat((portfolioLiveReturn * 100).toFixed(2)),
                    maxDrawdown: privateData?.metrics?.maxDrawdown ?? 0,
                  },
                  {
                    label: "Index + Signal (50/50)", color: "#06b6d4",
                    totalReturn: parseFloat((portfolioLiveReturn * 50).toFixed(2)),
                    maxDrawdown: 0,
                  },
                  {
                    label: "Bitcoin", color: "#f97316",
                    totalReturn: parseFloat((btcReturn * 100).toFixed(2)),
                    maxDrawdown: 0,
                  },
                ].map((m) => (
                  <MetricCard key={m.label} m={{ ...m, sharpe: null, annReturn: 0, volatility: 0 }} />
                ))}
              </div>
            </section>

            {/* Construction-stage comparison table */}
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
                              <span
                                className="text-xs font-semibold tracking-wider uppercase"
                                style={{ color: row.color }}
                              >
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
                  MCAP Universe: BTC/ETH/BNB/SOL/XRP/ADA/LINK/XLM/UNI/LTC/ZEC/BCH + COIN/HOOD/MSTR ·
                  Liq Universe: replaces XLM with HYPE; ETF missing aave/sui (renormalized)
                </div>
              </div>
            </section>

            {/* Chart with universe toggle */}
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

            {/* Asset breakdown by strategy */}
            <section>
              <SectionHeader
                title="Asset Breakdown by Strategy"
                subtitle="individual weights and returns for each construction stage"
              />
              {/* Group + stage selector */}
              <div className="flex flex-col gap-2 mb-3">
                {/* Group row */}
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
                {/* Stage row */}
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
              {/* Breakdown table */}
              <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[#2d3144]">
                      <th className="text-left px-4 py-3 text-gray-400 font-medium text-xs">#</th>
                      <th className="text-left px-4 py-3 text-gray-400 font-medium text-xs">Asset</th>
                      <th className="text-right px-4 py-3 text-gray-400 font-medium text-xs">Weight</th>
                      <th className="text-right px-4 py-3 text-gray-400 font-medium text-xs">Return (since May 1)</th>
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
                            {!row.available && (
                              <span className="ml-1.5 text-xs text-gray-600 font-normal">(no data)</span>
                            )}
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono text-xs"
                            style={{ color: row.available ? (activeStratWeights.stage?.color ?? "#9ca3af") : "#4b5563" }}>
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
                      <td className="px-4 py-2.5 text-right font-mono text-xs" style={{ color: activeStratWeights.stage?.color ?? "#9ca3af" }}>
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
                  Weights match source CSV directly · grayed rows = asset not in performance data · Contribution = raw weight × return (eod)
                </div>
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
