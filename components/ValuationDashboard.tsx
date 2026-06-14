"use client";

import { useState, useRef, useEffect } from "react";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  BarChart, Bar, Cell, LabelList,
} from "recharts";
import type { ValuationsFile, TokenResult, ValuationScenario, McapPoint, MsPoint, ValuationData, Y3Volume, HistCharts, BacktestRow } from "@/lib/loadValuations";
import { LineChart, Line, ReferenceLine } from "recharts";
import Nav from "./Nav";

interface Props {
  data: ValuationsFile;
}

// ── Term definitions ─────────────────────────────────────────────────────────

const TERMS: Record<string, { title: string; body: string }> = {
  p25: {
    title: "P25 — 25th Percentile",
    body: "25% of Monte Carlo paths produce a fair value at or below this price. A conservative estimate — only a bad-luck quarter of simulated futures lands here.",
  },
  p50: {
    title: "P50 — Median",
    body: "The midpoint of simulated fair values. Half of all paths land above this, half below. The model's central estimate with no optimism bias.",
  },
  p75: {
    title: "P75 — 75th Percentile",
    body: "75% of paths land at or below this. Represents a good-but-not-exceptional outcome — the upper edge of the core range.",
  },
  p90: {
    title: "P90 — 90th Percentile",
    body: "Only 10% of simulated paths exceed this value. Reflects a strong bull outcome where growth significantly outperforms the historical base rate.",
  },
  ev: {
    title: "EV — Expected Value (Mean)",
    body: "The probability-weighted average across all 50–100k Monte Carlo paths. Pulled above P50 by the fat right tail of bull scenarios. Not a price target — the mathematical average of all possible futures.",
  },
  dr: {
    title: "Discount Rate",
    body: "The annualised rate used to bring Year-3 GP back to present value. Liquid-token CAPM: risk-free rate + equity risk premium × (token vol ÷ S&P 500 vol). Higher volatility = higher DR = lower present value.",
  },
  multiple: {
    title: "GP Multiple",
    body: "Year-3 trailing-12M gross profit is multiplied by this factor to get an enterprise value. Mid-cycle assumption for a high-growth DeFi protocol. 20x trough / 15x normal / 10x peak volume regime.",
  },
  paths: {
    title: "Monte Carlo Paths",
    body: "The number of simulated futures run. Each path draws random monthly growth shocks from the historical distribution of the protocol's volume/revenue. 50k–100k paths converge well for these distributions.",
  },
  prob_above_spot: {
    title: "Probability Above Spot",
    body: "Fraction of Monte Carlo paths where the model's 3-year discounted fair value exceeds the current spot price. Above 50% means the model's central case implies the token is undervalued.",
  },
  prob_3x: {
    title: "3× Probability",
    body: "Fraction of paths where the model fair value is at least 3× today's spot. A rough screen for asymmetric upside potential.",
  },
  upside: {
    title: "P50 Upside",
    body: "How far the median fair value (P50) is above or below the current spot price. Negative means the model's central estimate implies the token is fairly valued or stretched.",
  },
  gp_capture: {
    title: "GP-Capture Framework",
    body: "Rather than discounting all future cash flows to infinity, this model captures the gross profit the protocol is expected to generate in Year 3 and applies a multiple. Simpler, more robust to uncertainty, and standard in DeFi research.",
  },
  ms90: {
    title: "MS90 — 90-Day Market Share",
    body: "Hyperliquid's 90-day derivatives volume as a fraction of Binance Futures volume (scaled via Blockworks annual totals). Used as the base market share for the Monte Carlo paths.",
  },
  ms30: {
    title: "MS30 — 30-Day Market Share",
    body: "Hyperliquid's 30-day derivatives volume share vs Binance. Higher than MS90 indicates recent momentum; MS30/MS90 trend > 1× is used as the share-growth amplifier.",
  },
};

// ── Per-token methodology ────────────────────────────────────────────────────

const METHODOLOGY: Record<string, { sections: { heading: string; text: string }[] }> = {
  hype: {
    sections: [
      {
        heading: "Core revenue model",
        text: "Perp GP = Binance Futures monthly volume × HL market share × 0.034% take-rate. USDC yield = USDC TVL × net yield × 90% capture. TVL follows the simulated HL volume path via live-estimated elasticity. Both streams are simulated over 36 months.",
      },
      {
        heading: "Market share momentum",
        text: "MS30/MS90 is treated as the current 6M share-growth amplifier. Monthly velocity linearly decays to 1.0× over 12 months; the gained share is retained. Absolute cap: 35% of Binance.",
      },
      {
        heading: "Supply / emission scenarios",
        text: "Four scenarios by supply assumption: Bear uses worst-case non-circulating/team overhang release (full over 3Y); Base uses DB-observed ~1M HYPE/month; Bull uses the same with 10% overhang; Sensitivity assumes zero new emissions. Buybacks offset emissions at current GP/price.",
      },
      {
        heading: "Multiple regime",
        text: "20× trough (bottom 20% of Y3 volume paths) / 15× normal / 10× peak (top 20%). Multiple is applied to Y3 trailing-12M GP and discounted at 25% selected rate.",
      },
      {
        heading: "Data sources",
        text: "Binance volume: BTCUSDT Binance Futures ZIP data scaled by Blockworks annual totals. Market share: DefiLlama MCP derivatives volume (fallback: revenue ÷ 0.034% take-rate). USDC TVL: DefiLlama stablecoins API. Yield: FRED SOFR minus 50bp haircut.",
      },
    ],
  },
  uni: {
    sections: [
      {
        heading: "What is being valued",
        text: "Uniswap's protocol-level gross profit under two fee scenarios: current-state (~0.826bps LP protocol take + 0.30bps frontend) and full-activation (25% of LP fees routed to protocol + 0.30bps frontend). 3-year investment horizon — not a perpetual DCF.",
      },
      {
        heading: "Volume simulation",
        text: "Monthly volume history pulled from DeFiLlama (2021–present). Model bootstraps monthly log-returns and seeds each MC run at min(latest 30D volume, trailing 12M median). 36 months simulated.",
      },
      {
        heading: "Discount rate",
        text: "Liquid-token CAPM: risk-free rate + 3% ERP × (UNI daily vol ÷ S&P 500 daily vol), ~24–25% DR. Refreshed on each run.",
      },
      {
        heading: "Supply & multiple",
        text: "15× GP multiple applied to Year-3 GP, discounted at DR. FDV sensitivity shown as secondary scenario. Protocol fees burn UNI via TokenJar → Firepit.",
      },
      { heading: "Model locked", text: "Methodology locked 2026-05-09." },
    ],
  },
  ethfi: {
    sections: [
      {
        heading: "What is being valued",
        text: "ether.fi's gross profit from three revenue streams: (1) card business — GDV × 135bps take × operating margin, (2) liquid staking — staking TVL × staking APY × 5% take, (3) vaults — vault TVL × 1% flat fee.",
      },
      {
        heading: "Scenario weighting",
        text: "Bear (50% card margin, 20% weight), Base (60%, 40%), Bull (70%, 40%). 50k paths per scenario.",
      },
      {
        heading: "Discount rate",
        text: "Fixed at 27.5% — reflecting higher execution risk vs UNI given early-stage card business and ETH price dependency.",
      },
      {
        heading: "Supply & multiple",
        text: "15× GP multiple. 854.7M ETHFI projected supply at Y3. Treasury cash added back to equity value.",
      },
      {
        heading: "Key risks",
        text: "Card GDV growth is the dominant driver. Staking APY compression reduces staking GP over time.",
      },
    ],
  },
  jup: {
    sections: [
      {
        heading: "What is being valued",
        text: "Jupiter's entity-level gross profit from: (1) Perpetuals — 25% of gross perps fees, (2) Spot aggregator/Ultra + Jupiterz — combined ~3.55bps rake on GMV. Smaller products covered by +10% optionality premium.",
      },
      {
        heading: "Buyback mechanics",
        text: "50% of simulated entity GP used for JUP buybacks via Litterbox Trust, reducing Y3 effective supply denominator.",
      },
      {
        heading: "Supply schedule",
        text: "0 scheduled unlocks assumed. The ~3.4B JUP cold-storage/community reserve has no public distribution timeline.",
      },
      {
        heading: "Discount rate & multiple",
        text: "Fixed at 24.4%, 15× GP multiple. Three premium cases: Core, +10% Optionality, +10% Opt + Jupnet.",
      },
      {
        heading: "Model locked",
        text: "Methodology locked 2026-05-09, corrected 2026-05-15 for supply schedule.",
      },
    ],
  },
};

// ── InfoTooltip ──────────────────────────────────────────────────────────────

function InfoTooltip({ termKey }: { termKey: string }) {
  const def = TERMS[termKey];
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open]);

  if (!def) return null;

  return (
    <div ref={ref} className="relative inline-flex items-center" style={{ verticalAlign: "middle" }}>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        className="ml-1 w-3.5 h-3.5 rounded-full border text-gray-600 border-gray-600 flex items-center justify-center text-xs leading-none hover:border-gray-400 hover:text-gray-400 transition-colors shrink-0"
        style={{ fontSize: "9px", fontStyle: "italic", fontWeight: 700 }}
        aria-label={`Info: ${def.title}`}
      >
        i
      </button>
      {open && (
        <div
          className="absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 rounded-xl border border-[#3d4166] bg-[#1a1d29] shadow-xl p-3"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="text-xs font-semibold text-white mb-1">{def.title}</div>
          <div className="text-xs text-gray-400 leading-relaxed">{def.body}</div>
          <div className="absolute left-1/2 -translate-x-1/2 top-full w-2 h-2 border-r border-b border-[#3d4166] bg-[#1a1d29] rotate-45 -mt-1" />
        </div>
      )}
    </div>
  );
}

// ── ModelMethodology ─────────────────────────────────────────────────────────

function ModelMethodology({ tokenKey }: { tokenKey: string }) {
  const [open, setOpen] = useState(false);
  const m = METHODOLOGY[tokenKey];
  if (!m) return null;

  return (
    <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] overflow-hidden">
      <div
        role="button"
        tabIndex={0}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setOpen((v) => !v); }}
        className="w-full px-6 py-4 flex items-center justify-between text-left hover:bg-[#1e2130] transition-colors cursor-pointer"
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-gray-300">Model &amp; Assumptions</span>
          <InfoTooltip termKey="gp_capture" />
        </div>
        <svg
          className="transition-transform"
          style={{ transform: open ? "rotate(180deg)" : "rotate(0deg)" }}
          width="16" height="16" viewBox="0 0 24 24" fill="none"
          stroke="#6b7280" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </div>
      {open && (
        <div className="px-6 pb-6 space-y-4 border-t border-[#2d3144] pt-4">
          {m.sections.map((s) => (
            <div key={s.heading}>
              <div className="text-sm font-semibold text-gray-200 mb-1">{s.heading}</div>
              <div className="text-sm text-gray-400 leading-relaxed">{s.text}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Formatters ───────────────────────────────────────────────────────────────

function fmtPrice(n: number): string {
  if (n >= 1) return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return `$${n.toFixed(4)}`;
}

function fmtLarge(n: number): string {
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function pct(n: number, decimals = 1): string {
  return `${(n * 100).toFixed(decimals)}%`;
}

// ── MetricCard ───────────────────────────────────────────────────────────────

function MetricCard({
  label,
  value,
  sub,
  accent,
  termKey,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: "green" | "red" | "yellow" | "blue" | "default";
  termKey?: string;
}) {
  const color = {
    green: "#4ade80",
    red: "#f87171",
    yellow: "#fbbf24",
    blue: "#60a5fa",
    default: "#ffffff",
  }[accent ?? "default"];

  return (
    <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] px-4 py-3 flex flex-col gap-0.5">
      <div className="flex items-center gap-1 text-xs text-gray-500">
        {label}
        {termKey && <InfoTooltip termKey={termKey} />}
      </div>
      <div className="text-lg font-bold font-mono leading-tight" style={{ color }}>
        {value}
      </div>
      {sub && <div className="text-xs text-gray-600">{sub}</div>}
    </div>
  );
}

// ── McapChart ────────────────────────────────────────────────────────────────

function McapChart({ history, symbol, color }: { history: McapPoint[]; symbol: string; color: string }) {
  if (!history.length) return null;

  const min    = Math.min(...history.map((d) => d.mcap));
  const max    = Math.max(...history.map((d) => d.mcap));
  const latest = history[history.length - 1].mcap;
  const first  = history[0].mcap;
  const change = ((latest / first) - 1) * 100;
  const isUp   = change >= 0;

  function fmtMcap(n: number) {
    if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
    return `$${(n / 1e6).toFixed(0)}M`;
  }

  const step  = Math.max(1, Math.floor(history.length / 12));
  const ticks = history
    .filter((_, i) => i % step === 0 || i === history.length - 1)
    .map((d) => d.date);

  return (
    <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <span className="text-sm font-semibold text-gray-300">{symbol} Market Cap</span>
          <span className="ml-2 text-xs text-gray-500">90 days</span>
        </div>
        <div className="text-right">
          <div className="text-base font-bold font-mono text-white">{fmtMcap(latest)}</div>
          <div className="text-xs font-mono" style={{ color: isUp ? "#4ade80" : "#f87171" }}>
            {isUp ? "+" : ""}{change.toFixed(1)}%
          </div>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={160}>
        <AreaChart data={history} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id={`mcap-grad-${symbol}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.25} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" vertical={false} />
          <XAxis
            dataKey="date"
            ticks={ticks}
            tickFormatter={(d: string) => { const [, m, day] = d.split("-"); return `${parseInt(m)}/${parseInt(day)}`; }}
            tick={{ fill: "#6b7280", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            domain={[min * 0.95, max * 1.05]}
            tickFormatter={fmtMcap}
            tick={{ fill: "#6b7280", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={52}
          />
          <Tooltip
            contentStyle={{ background: "#1a1d29", border: "1px solid #2d3144", borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: "#9ca3af", marginBottom: 2 }}
            formatter={(v: number) => [fmtMcap(v), "MCap"]}
            itemStyle={{ color }}
          />
          <Area
            type="monotone"
            dataKey="mcap"
            stroke={color}
            strokeWidth={1.5}
            fill={`url(#mcap-grad-${symbol})`}
            dot={false}
            activeDot={{ r: 3, fill: color }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── DistributionChart ────────────────────────────────────────────────────────

const DIST_LABELS: { key: string; label: string; isMedian?: boolean }[] = [
  { key: "p95", label: "P95" },
  { key: "p90", label: "P90" },
  { key: "p80", label: "P80" },
  { key: "p75", label: "P75" },
  { key: "p70", label: "P70" },
  { key: "p60", label: "P60" },
  { key: "p50", label: "P50", isMedian: true },
  { key: "p40", label: "P40" },
  { key: "p30", label: "P30" },
  { key: "p25", label: "P25" },
  { key: "p20", label: "P20" },
  { key: "p10", label: "P10" },
  { key: "p5",  label: "P5" },
];

// Fallback: only core percentiles available
const DIST_LABELS_CORE: { key: string; label: string; isMedian?: boolean }[] = [
  { key: "p90", label: "P90" },
  { key: "p75", label: "P75" },
  { key: "p50", label: "P50", isMedian: true },
  { key: "p25", label: "P25" },
];

function DistributionChart({
  scenario,
  spot,
  ev,
}: {
  scenario: ValuationScenario;
  spot: number;
  ev: number;
}) {
  const dist = scenario.distribution;
  const hasFull = dist && Object.keys(dist).length > 4;
  const rowDefs = hasFull ? DIST_LABELS : DIST_LABELS_CORE;
  const source: Record<string, number> = dist ?? (scenario.pv as unknown as Record<string, number>);

  // Build ascending order (P5 → P95) for vertical bar chart
  const rows = [...rowDefs]
    .reverse()
    .map((d) => ({ ...d, value: source[d.key] as number | undefined }))
    .filter((r): r is typeof r & { value: number } => r.value !== undefined && r.value > 0);

  if (!rows.length) return null;

  const yMax = Math.max(...rows.map(r => r.value), ev) * 1.12;

  return (
    <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-6">
      <div className="flex items-center justify-between mb-1">
        <div>
          <div className="text-sm font-semibold text-gray-300">
            PV Distribution — {scenario.label}
          </div>
          <div className="text-xs text-gray-500 mt-0.5">Percentile ladder + probability-weighted EV</div>
        </div>
        <div className="flex items-center gap-4 text-xs text-gray-500">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-5 border-t border-orange-400" />
            Spot {fmtPrice(spot)}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-5 border-t border-dashed border-blue-400" />
            EV {fmtPrice(ev)}
          </span>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={rows} margin={{ top: 24, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: "#6b7280", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tickFormatter={(v: number) => `$${v >= 1000 ? (v / 1000).toFixed(0) + "k" : v.toFixed(0)}`}
            tick={{ fill: "#6b7280", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={40}
            domain={[0, yMax]}
          />
          <Tooltip
            contentStyle={{ background: "#1a1d29", border: "1px solid #2d3144", borderRadius: 8, fontSize: 11 }}
            formatter={(v: number) => [fmtPrice(v), "PV"]}
          />
          {/* Labels only in header legend; no inline chart labels to avoid clipping */}
          <ReferenceLine y={spot} stroke="#fb923c" strokeWidth={1.5} />
          <ReferenceLine y={ev}   stroke="#60a5fa" strokeWidth={1.5} strokeDasharray="4 3" />
          <Bar dataKey="value" radius={[3, 3, 0, 0]} maxBarSize={48}>
            <LabelList
              dataKey="value"
              position="top"
              content={(props) => {
                const { x, y, width, value, index } = props as { x?: unknown; y?: unknown; width?: unknown; value?: unknown; index?: number };
                const nx = Number(x), ny = Number(y), nw = Number(width), nv = Number(value);
                if (!isFinite(nx) || !isFinite(ny) || !isFinite(nw) || !isFinite(nv)) return null;
                const isP50 = rows[index ?? 0]?.isMedian;
                return (
                  <text
                    x={nx + nw / 2}
                    y={ny - 4}
                    textAnchor="middle"
                    fontSize={9}
                    fill={isP50 ? "#e2e8f0" : "#6b7280"}
                    fontWeight={isP50 ? 600 : 400}
                  >
                    {fmtPrice(nv)}
                  </text>
                );
              }}
            />
            {rows.map((row) => (
              <Cell
                key={row.key}
                fill={row.isMedian ? "#1e3a4a" : "#1e2a3a"}
                stroke={row.isMedian ? "#38bdf8" : "#2d3144"}
                strokeWidth={row.isMedian ? 1.5 : 0.5}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      <p className="text-xs text-gray-600 mt-2 leading-relaxed">
        Bars show selected-model PV/token percentiles. Bold bar is P50 {fmtPrice(scenario.pv.p50)}. Blue dashed line is probability-weighted EV {fmtPrice(ev)}, which captures all paths including the right tail.
      </p>
    </div>
  );
}

// ── ScenarioTable ────────────────────────────────────────────────────────────

function ScenarioTable({
  scenarios,
  spot,
}: {
  scenarios: ValuationScenario[];
  spot: number;
}) {
  return (
    <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] overflow-hidden">
      <div className="px-6 py-4 border-b border-[#2d3144]">
        <span className="text-sm font-semibold text-gray-300">Scenario Comparison</span>
        <span className="ml-2 text-xs text-gray-600">discounted PV / token @ 3Y</span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#2d3144]">
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 whitespace-nowrap">Scenario</th>
              {(["P25", "P50", "P75", "P90"] as const).map((p) => (
                <th key={p} className="text-right px-3 py-3 text-xs font-medium text-gray-500 whitespace-nowrap">
                  {p} <InfoTooltip termKey={p.toLowerCase()} />
                </th>
              ))}
              <th className="text-right px-3 py-3 text-xs font-medium text-gray-500 whitespace-nowrap">
                EV <InfoTooltip termKey="ev" />
              </th>
              <th className="text-right px-4 py-3 text-xs font-medium text-gray-500 whitespace-nowrap">
                P(spot) <InfoTooltip termKey="prob_above_spot" />
              </th>
              <th className="text-right px-4 py-3 text-xs font-medium text-gray-500 whitespace-nowrap">
                3× <InfoTooltip termKey="prob_3x" />
              </th>
            </tr>
          </thead>
          <tbody>
            {scenarios.map((s) => {
              const upside  = spot > 0 ? (s.pv.p50 / spot - 1) * 100 : 0;
              const probColor = s.prob_above_spot >= 0.5
                ? "#4ade80"
                : s.prob_above_spot >= 0.35
                ? "#fbbf24"
                : "#f87171";

              return (
                <tr
                  key={s.key}
                  className="border-b border-[#2d3144] last:border-0 transition-colors"
                  style={s.is_primary ? { background: "rgba(16, 185, 129, 0.04)" } : {}}
                >
                  {/* Label */}
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <span className={`text-sm font-medium ${s.is_primary ? "text-white" : "text-gray-400"}`}>
                        {s.label}
                      </span>
                      {s.is_primary && (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 font-medium">
                          primary
                        </span>
                      )}
                    </div>
                    <div className="text-xs mt-0.5" style={{ color: upside >= 0 ? "#4ade80" : "#f87171" }}>
                      P50 {upside >= 0 ? "+" : ""}{upside.toFixed(0)}% vs spot
                    </div>
                  </td>

                  {/* Percentiles */}
                  {(["p25", "p50", "p75", "p90"] as const).map((p) => (
                    <td key={p} className="px-3 py-4 text-right font-mono text-sm text-gray-300 whitespace-nowrap">
                      {fmtPrice(s.pv[p])}
                    </td>
                  ))}

                  {/* EV */}
                  <td className="px-3 py-4 text-right font-mono text-sm text-blue-300 whitespace-nowrap">
                    {fmtPrice(s.ev)}
                  </td>

                  {/* P(spot) */}
                  <td className="px-4 py-4 text-right whitespace-nowrap">
                    <span className="font-mono text-sm font-semibold" style={{ color: probColor }}>
                      {pct(s.prob_above_spot)}
                    </span>
                  </td>

                  {/* 3× prob */}
                  <td className="px-4 py-4 text-right whitespace-nowrap">
                    {s.prob_3x !== undefined
                      ? <span className="font-mono text-sm text-gray-400">{pct(s.prob_3x)}</span>
                      : <span className="text-gray-600">—</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Per-token GP metadata ────────────────────────────────────────────────────

type GpFmt = "pct" | "money" | "x" | "years" | "bps" | "raw";
type GpMeta = { label: string; fmt: GpFmt };

const TOKEN_GP_META: Record<string, Record<string, GpMeta>> = {
  uni: {
    annualized_current_state:   { label: "GP current state (ann.)",   fmt: "money" },
    annualized_full_activation: { label: "GP full activation (ann.)",  fmt: "money" },
    ann_volume:                 { label: "Annual volume",              fmt: "money" },
    lp_fee_bps_30d:             { label: "LP take 30D",               fmt: "bps"   },
    take_bps_current:           { label: "Protocol take — current",    fmt: "bps"   },
    take_bps_full:              { label: "Protocol take — full activ.", fmt: "bps"   },
    mcap_current_state_gp:      { label: "Mcap / GP (current)",        fmt: "x"     },
    mcap_full_activation_gp:    { label: "Mcap / GP (full activ.)",    fmt: "x"     },
  },
  ethfi: {
    card_annualized:   { label: "Card GP (ann.)",    fmt: "money" },
    staking_annualized:{ label: "Staking GP (ann.)", fmt: "money" },
    vault_annualized:  { label: "Vault GP (ann.)",   fmt: "money" },
    total_annualized:  { label: "Total GP (ann.)",   fmt: "money" },
    card_gdv_30d_ann:  { label: "Card GDV (ann.)",   fmt: "money" },
    staking_apy:       { label: "Staking APY",        fmt: "pct"   },
    stake_tvl:         { label: "Stake TVL",          fmt: "money" },
    vault_tvl:         { label: "Vault TVL",          fmt: "money" },
    card_take_bps_30d: { label: "Card take 30D",      fmt: "bps"   },
    card_mom:          { label: "Card MoM growth",    fmt: "pct"   },
  },
  jup: {
    perps_30d:          { label: "Perps 30D GP",      fmt: "money" },
    aggregator_30d:     { label: "Aggregator 30D GP", fmt: "money" },
    jupiterz_30d:       { label: "Jupiterz 30D GP",   fmt: "money" },
    total_30d:          { label: "Total 30D GP",      fmt: "money" },
    seed_monthly:       { label: "Seed monthly GP",   fmt: "money" },
    seed_annualized:    { label: "Seed GP (ann.)",    fmt: "money" },
    optional_tracked_30d:{ label: "Optional 30D",     fmt: "money" },
  },
};

function fmtGpVal(val: number, fmt: GpFmt): string {
  if (fmt === "pct")   return `${(val * 100).toFixed(1)}%`;
  if (fmt === "money") return fmtLarge(val);
  if (fmt === "x")     return `${val.toFixed(1)}×`;
  if (fmt === "years") return `${val.toFixed(1)}y`;
  if (fmt === "bps")   return `${val.toFixed(2)} bps`;
  return val.toFixed(4);
}

// ── TokenKeyMetrics ───────────────────────────────────────────────────────────

function TokenKeyMetrics({ currentGp, tokenKey }: { currentGp: Record<string, number>; tokenKey: string }) {
  const meta = TOKEN_GP_META[tokenKey] ?? {};
  const entries = Object.entries(currentGp)
    .filter(([k, v]) => meta[k] && typeof v === "number" && isFinite(v) && v !== 0)
    .map(([k, v]) => ({ key: k, label: meta[k].label, value: fmtGpVal(v, meta[k].fmt) }));

  if (!entries.length) return null;

  return (
    <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-6">
      <h3 className="text-xl font-bold text-white mb-4">Key metrics</h3>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
        {entries.map(({ key, label, value }) => (
          <div key={key} className="bg-[#252836] rounded-xl border border-[#2d3144] px-4 py-3 flex flex-col gap-0.5">
            <div className="text-xs text-gray-500">{label}</div>
            <div className="text-lg font-bold font-mono text-white leading-tight">{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── TokenModelAssumptions ─────────────────────────────────────────────────────

function TokenModelAssumptions({ tokenKey, model }: {
  tokenKey: string;
  model: { type: string; discount_rate: number; multiple: number; paths: number; note?: string };
}) {
  const m = METHODOLOGY[tokenKey];
  if (!m) return null;

  const drPct = (model.discount_rate * 100).toFixed(1);

  return (
    <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-6 space-y-4">
      <h3 className="text-xl font-bold text-white">Model assumptions</h3>

      {/* Top row: two code-block cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="bg-[#0d1117] rounded-xl border border-[#2d3144] px-5 py-4">
          <div className="text-xs text-gray-500 mb-2 uppercase tracking-wider font-semibold">Core revenue model</div>
          <pre className="text-xs text-gray-300 leading-relaxed whitespace-pre-wrap font-mono">{m.sections[0]?.text ?? ""}</pre>
        </div>
        <div className="bg-[#0d1117] rounded-xl border border-[#2d3144] px-5 py-4">
          <div className="text-xs text-gray-500 mb-2 uppercase tracking-wider font-semibold">Valuation logic</div>
          <pre className="text-xs text-gray-300 leading-relaxed whitespace-pre-wrap font-mono">{`Multiple: ${model.multiple}× GP
Discount rate: ${drPct}%
Paths: ${(model.paths / 1000).toFixed(0)}k Monte Carlo
Horizon: 3 years`}</pre>
        </div>
      </div>

      {/* Bottom rows: remaining methodology sections */}
      {m.sections.slice(1).length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {m.sections.slice(1).map((s) => (
            <div key={s.heading} className="bg-[#252836] rounded-xl border border-[#2d3144] px-4 py-3">
              <div className="text-xs text-gray-500 mb-1 font-semibold uppercase tracking-wider">{s.heading}</div>
              <div className="text-xs text-gray-400 leading-relaxed">{s.text}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── MarketShareSection (shared for HYPE + UNI) ───────────────────────────────

interface MsConfig {
  chartNote: string;
  tableNote: string;
  driversTitle: string;
  driversBody: React.ReactNode;
  tableRows: (gp: Record<string, number>) => [string, string][];
  yCapPct: number;   // y-axis max cap as decimal
}

const MS_CONFIG: Record<string, MsConfig> = {
  hype: {
    yCapPct: 0.35,
    chartNote: "Chart uses daily revenue-implied HL volume for rolling continuity; headline cards use DefiLlama MCP derivatives-volume aggregates.",
    tableNote: "DefiLlama MCP checked: revenue excludes Coinbase/USDC yield; stablecoin yield is modeled separately.",
    driversTitle: "Perps + stablecoin yield",
    driversBody: null,   // filled inline below
    tableRows: (gp) => ([
      ["MS30 vs Binance Futures",        pct(gp["ms30_vs_binance"] as number)],
      ["MS180 vs Binance Futures",       pct(gp["ms180_vs_binance"] as number)],
      ["MS30/MS180 trend",               `${(gp["ms30_ms180_trend"] as number).toFixed(2)}×`],
      ["DefiLlama 30D fee rev. ann.",    fmtLarge(gp["defillama_30d_ann"] as number)],
      ["DefiLlama 180D fee rev. ann.",   fmtLarge(gp["defillama_180d_ann"] as number)],
      ["Buyback yrs (fees + USDC)",      `${(gp["buyback_years_base"] as number).toFixed(1)}y`],
      ["Fee-only buyback years",         `${(gp["buyback_years_fee_only"] as number).toFixed(1)}y`],
    ] as [string, string][]).filter(([, v]) => v && v !== "$0" && v !== "0.0y"),
  },
  uni: {
    yCapPct: 0.50,
    chartNote: "Rolling 30D and 90D UNI DEX volume / total DEX volume (all protocols, DefiLlama). Shows Uniswap's share of on-chain trading.",
    tableNote: "Volume from DefiLlama; denominator is total DEX volume across all chains and protocols.",
    driversTitle: "DEX spot market share",
    driversBody: null,
    tableRows: (gp) => ([
      ["MS30 vs Total DEX",              pct(gp["ms30_vs_dex"] as number)],
      ["MS90 vs Total DEX",              pct(gp["ms90_vs_dex"] as number)],
      ["MS180 vs Total DEX",             pct(gp["ms180_vs_dex"] as number)],
      ["MS30/MS180 trend",               `${(gp["ms30_ms180_trend"] as number)?.toFixed(2)}×`],
      ["UNI 30D volume (ann.)",          fmtLarge(gp["ann_volume"] as number)],
      ["GP current state (ann.)",        fmtLarge(gp["annualized_current_state"] as number)],
      ["GP full activation (ann.)",      fmtLarge(gp["annualized_full_activation"] as number)],
    ] as [string, string][]).filter(([, v]) => v && v !== "$0" && v !== "NaN×"),
  },
  sky: {
    yCapPct: 0.08,
    chartNote: "Rolling 30D and 90D mean of (USDS + DAI) / total USD stablecoin supply (DefiLlama). Directly drives gross income — higher share → more revenue at current yield.",
    tableNote: "Total stablecoin denominator from DefiLlama /stablecoincharts/all (includes USDT, USDC, FDUSD, PYUSD, etc.).",
    driversTitle: "Decentralized stablecoin market",
    driversBody: null,
    tableRows: (gp) => ([
      ["MS30 vs All Stablecoins",        pct(gp["ms30_vs_stables"] as number)],
      ["MS90 vs All Stablecoins",        pct(gp["ms90_vs_stables"] as number)],
      ["MS180 vs All Stablecoins",       pct(gp["ms180_vs_stables"] as number)],
      ["MS30/MS180 trend",               `${(gp["ms30_ms180_trend"] as number)?.toFixed(2)}×`],
      ["Total stablecoin market",        fmtLarge(gp["total_stablecoin_supply"] as number)],
      ["USDS supply",                    fmtLarge(gp["usds_supply"] as number)],
      ["DAI supply",                     fmtLarge(gp["dai_supply"] as number)],
      ["Gross income (ann.)",            fmtLarge(gp["gross_income"] as number)],
    ] as [string, string][]).filter(([, v]) => v && v !== "$0" && v !== "NaN×"),
  },
  jup: {
    yCapPct: 1.00,
    chartNote: "Rolling 30D and 90D JUP Perps fees / total tracked Solana perps fees (JUP + Drift + Flash Trade). Fee revenue is a proxy for perps volume share.",
    tableNote: "Denominator covers DefiLlama-tracked Solana perps protocols with active fee data; excludes Zeta/Ranger (no fee data available).",
    driversTitle: "Solana perps fee share",
    driversBody: null,
    tableRows: (gp) => ([
      ["MS30 vs Solana Perps",            pct(gp["ms30_vs_sol_perps"] as number)],
      ["MS90 vs Solana Perps",            pct(gp["ms90_vs_sol_perps"] as number)],
      ["MS180 vs Solana Perps",           pct(gp["ms180_vs_sol_perps"] as number)],
      ["MS30/MS180 trend",                `${(gp["ms30_ms180_trend"] as number)?.toFixed(2)}×`],
      ["JUP Perps 30D fees",              fmtLarge(gp["jup_perps_30d_fees"] as number)],
      ["Solana Perps 30D fees (tracked)", fmtLarge(gp["sol_perps_30d_fees"] as number)],
      ["Perps 30D GP",                    fmtLarge(gp["perps_30d"] as number)],
    ] as [string, string][]).filter(([, v]) => v && v !== "$0" && v !== "NaN×"),
  },
  ethfi: {
    yCapPct: 0.90,
    chartNote: "Rolling 30D and 90D mean of ether.fi staking TVL / total LRT TVL (ether.fi + Kelp + Renzo + Puffer + Swell). Shows ether.fi dominance within the liquid restaking niche.",
    tableNote: "Denominator sums top LRT protocols from DefiLlama; excludes traditional liquid staking (Lido, Rocket Pool).",
    driversTitle: "LRT restaking market share",
    driversBody: null,
    tableRows: (gp) => ([
      ["MS30 vs Total LRT",              pct(gp["ms30_vs_lrt"] as number)],
      ["MS90 vs Total LRT",              pct(gp["ms90_vs_lrt"] as number)],
      ["MS180 vs Total LRT",             pct(gp["ms180_vs_lrt"] as number)],
      ["MS30/MS180 trend",               `${(gp["ms30_ms180_trend"] as number)?.toFixed(2)}×`],
      ["LRT market total TVL",           fmtLarge(gp["lrt_total_tvl"] as number)],
      ["MS vs all liquid staking",       pct(gp["ms30_vs_all_staking"] as number)],
      ["Staking TVL",                    fmtLarge(gp["stake_tvl"] as number)],
    ] as [string, string][]).filter(([, v]) => v && v !== "$0" && v !== "NaN×"),
  },
};

function MarketShareSection({ data, tokenKey }: { data: ValuationData; tokenKey: string }) {
  const history = data.ms_history;
  if (!history?.length) return null;
  const cfg = MS_CONFIG[tokenKey];
  if (!cfg) return null;

  const gp = data.current_gp;
  const step  = Math.max(1, Math.floor(history.length / 6));
  const ticks = history
    .filter((_, i) => i % step === 0 || i === history.length - 1)
    .map((d) => d.date);

  const ms30Vals = history.map((d) => d.ms30).filter(Boolean) as number[];
  const ms90Vals = history.map((d) => d.ms90).filter((v): v is number => v != null);
  const yMin = Math.max(0, Math.min(...ms30Vals) - 0.01);
  const yMax = Math.min(cfg.yCapPct, Math.max(...ms90Vals.concat(ms30Vals)) + 0.01);

  const tableRows = cfg.tableRows(gp);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
      {/* ── Left: chart ─────────────────────────────────────────────── */}
      <div className="lg:col-span-3 bg-[#1a1d29] rounded-xl border border-[#2d3144] p-6">
        <h3 className="text-xl font-bold text-white mb-5">Market share trend</h3>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={history} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" vertical={false} />
            <XAxis
              dataKey="date"
              ticks={ticks}
              tickFormatter={(d: string) => { const [, m, day] = d.split("-"); return `${parseInt(m)}/${parseInt(day)}`; }}
              tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false}
            />
            <YAxis
              domain={[yMin, yMax]}
              tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
              tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} width={36}
            />
            <Tooltip
              contentStyle={{ background: "#1a1d29", border: "1px solid #2d3144", borderRadius: 8, fontSize: 11 }}
              labelStyle={{ color: "#9ca3af", marginBottom: 2 }}
              formatter={(v: number, name: string) => [`${(v * 100).toFixed(2)}%`, name === "ms30" ? "MS30" : "MS90"]}
            />
            <Line type="monotone" dataKey="ms90" stroke="#6b7280" strokeWidth={1.5} dot={false} connectNulls />
            <Line type="monotone" dataKey="ms30" stroke="#e5e7eb" strokeWidth={1.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
        <p className="text-xs text-gray-600 mt-4 leading-relaxed">{cfg.chartNote}</p>
      </div>

      {/* ── Right: table + drivers card ─────────────────────────────── */}
      <div className="lg:col-span-2 flex flex-col gap-4">
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-5 flex-1">
          <div className="text-xs font-mono text-gray-500 mb-4 tracking-wide">Current snapshot</div>
          <table className="w-full">
            <tbody>
              {tableRows.map(([label, value]) => (
                <tr key={label} className="border-b border-[#252836] last:border-0">
                  <td className="py-2.5 text-sm text-gray-400 pr-3">{label}</td>
                  <td className="py-2.5 text-sm font-mono font-semibold text-gray-200 text-right whitespace-nowrap">{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-gray-600 mt-4 leading-relaxed">{cfg.tableNote}</p>
        </div>

        <div className="bg-[#0a0c14] rounded-xl border border-[#2d3144] p-5">
          <div className="text-xs font-mono text-gray-500 mb-1 tracking-wide">Core revenue drivers</div>
          <div className="text-lg font-bold text-white mb-3">{cfg.driversTitle}</div>
          {tokenKey === "hype" && (
            <p className="text-sm text-gray-400 leading-relaxed">
              DefiLlama rows are observed fee revenue. MC models future perps GP from Binance volume × HL share × 0.034% take-rate. Stablecoin yield modeled separately as USDC TVL × net yield × 90% capture; current run-rate{" "}
              <span className="text-gray-200 font-medium">{fmtLarge(gp["usdc_gp_annual"] as number)}</span>.
            </p>
          )}
          {tokenKey === "uni" && (
            <p className="text-sm text-gray-400 leading-relaxed">
              UNI revenue = LP fees × protocol take-rate. Current state: ~0.83bps LP protocol share + 0.30bps frontend. Full activation: 25% of LP fees + 0.30bps frontend. Market share trend shows UNI's share of total DEX volume across all on-chain protocols (DefiLlama).
            </p>
          )}
          {tokenKey === "ethfi" && (
            <p className="text-sm text-gray-400 leading-relaxed">
              ether.fi GP = Card GDV × 135bps take × margin + staking TVL × ETH APY × 5% + vault TVL × 1%. Market share trend shows ether.fi's rolling TVL share of the liquid restaking market (vs Kelp, Renzo, Puffer, Swell). Table also shows share of all liquid staking (LRT + LST including Lido).
            </p>
          )}
          {tokenKey === "jup" && (
            <p className="text-sm text-gray-400 leading-relaxed">
              JUP GP = 25% of Perps fees + aggregator rake + Jupiterz volume × 3.55bps. Market share uses Perps fee revenue as a volume proxy, comparing JUP vs Drift and Flash Trade (only Solana perps protocols with accessible fee history on DefiLlama). Zeta and Ranger excluded — no fee data available.
            </p>
          )}
          {tokenKey === "sky" && (
            <p className="text-sm text-gray-400 leading-relaxed">
              Sky GP = gross income − savings-rate cost − stUSDS expense. Gross income = (USDS + DAI supply) × yield. Market share trend tracks Sky&apos;s share of total USD stablecoin supply (USDT, USDC, FDUSD, PYUSD, etc.) — growing share means more gross income at the same yield.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Token color palette ──────────────────────────────────────────────────────

const TOKEN_COLORS: Record<string, string> = {
  uni:   "#ff007a",
  ethfi: "#06b6d4",
  jup:   "#9945ff",
  hype:  "#00e5a0",
  sky:   "#f59e0b",
};

// ── HypeHistoricalCharts ─────────────────────────────────────────────────────

const SIGNAL_COLOR: Record<string, string> = { GOOD: "#4ade80", NEUTRAL: "#9ca3af", BAD: "#f87171" };

function HypeHistoricalCharts({ hc }: { hc: HistCharts }) {
  const bt = hc.backtest;
  const chart = bt?.chart ?? [];
  const signals = bt?.signals ?? {};
  const buyback = hc.buyback_horizon ?? [];
  const eoy3 = hc.eoy3_ms ?? [];

  const fmtRet = (v: number | null) => v == null ? "n/a" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
  const fmtYr = (v: number) => `${v.toFixed(0)}y`;

  // x-axis label helper
  const dateLbl = (d: string) => { const [, m, day] = d.split("-"); return `${parseInt(m)}/${parseInt(day)}`; };

  // Backtest chart: use all points for dense dot coverage; add per-signal columns for colored lines
  const lastRealized = bt.last_realized_row ?? "";
  const btData = chart.map((row, i) => {
    const isUnscored = lastRealized && row.date > lastRealized;
    const prev = chart[i - 1];
    const next = chart[i + 1];
    const prevSig = prev ? (lastRealized && prev.date > lastRealized ? "unscored" : prev.signal) : row.signal;
    const nextSig = next ? (lastRealized && next.date > lastRealized ? "unscored" : next.signal) : row.signal;
    const curSig  = isUnscored ? "unscored" : row.signal;
    const v = row.spot;
    // Scored segments — include boundary points for seamless transitions
    const inGood    = (curSig === "GOOD"    || prevSig === "GOOD"    || nextSig === "GOOD")    && !isUnscored;
    const inNeutral = (curSig === "NEUTRAL" || prevSig === "NEUTRAL" || nextSig === "NEUTRAL") && !isUnscored;
    const inBad     = (curSig === "BAD"     || prevSig === "BAD"     || nextSig === "BAD")     && !isUnscored;
    // Unscored: same boundary logic but keep actual signal so color is preserved
    const isBoundaryToUnscored = !isUnscored && nextSig === "unscored";
    const unscoredSig = isUnscored ? row.signal : (isBoundaryToUnscored ? row.signal : null);
    return {
      ...row,
      spot_good:            inGood    ? v : null,
      spot_neutral:         inNeutral ? v : null,
      spot_bad:             inBad     ? v : null,
      spot_unscored_good:   (isUnscored || isBoundaryToUnscored) && unscoredSig === "GOOD"    ? v : null,
      spot_unscored_neutral:(isUnscored || isBoundaryToUnscored) && unscoredSig === "NEUTRAL" ? v : null,
      spot_unscored_bad:    (isUnscored || isBoundaryToUnscored) && unscoredSig === "BAD"     ? v : null,
    };
  });
  const btTicks = chart.filter((_, i) => i % Math.floor(chart.length / 6) === 0).map(r => r.date);

  // Buyback chart
  const bbStep = Math.max(1, Math.floor(buyback.length / 180));
  const bbSampled = buyback.filter((_, i) => i % bbStep === 0);
  const bbTicks = bbSampled.filter((_, i) => i % Math.floor(bbSampled.length / 5) === 0).map(r => r.date);
  const bbMin = Math.max(0, Math.min(...bbSampled.map(r => r.years)) - 2);
  const bbMax = Math.max(...bbSampled.map(r => r.years)) + 2;
  const bbLatest = buyback[buyback.length - 1];

  // EOY3 chart
  const e3Step = Math.max(1, Math.floor(eoy3.length / 180));
  const e3Sampled = eoy3.filter((_, i) => i % e3Step === 0);
  const e3Ticks = e3Sampled.filter((_, i) => i % Math.floor(e3Sampled.length / 5) === 0).map(r => r.date);
  const e3Latest = eoy3[eoy3.length - 1];

  return (
    <div className="space-y-5">

      {/* ── 1. Historical entry backtest ────────────────────────────── */}
      {chart.length > 0 && (
        <div className="space-y-3">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Left: description */}
            <div className="lg:col-span-1">
              <h3 className="text-xl font-bold text-white mb-3">Historical entry backtest</h3>
              <p className="text-sm text-gray-400 leading-relaxed">
                Historical model-shaped diagnostic, not a full MC replay: <span className="text-gray-200">GOOD</span> if model PV/spot &gt; 1.25, <span className="text-gray-200">BAD</span> if &lt; 0.75.{" "}
                Latest signal: <span className="font-bold" style={{ color: SIGNAL_COLOR[bt.latest_signal] }}>{bt.latest_signal}</span>
                {bt.last_realized_row && <>; last realized-return row: <span className="font-bold text-gray-200">{bt.last_realized_row}</span></>}.
              </p>
            </div>
            {/* Right: signal table */}
            <div className="lg:col-span-2 bg-[#1a1d29] rounded-xl border border-[#2d3144] overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#2d3144]">
                    {["SIGNAL", "OBS", "AVG +30D", "AVG +90D", "RECENT DATES"].map(h => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {["GOOD", "NEUTRAL", "BAD"].map(sig => {
                    const s = signals[sig];
                    if (!s) return null;
                    return (
                      <tr key={sig} className="border-b border-[#2d3144] last:border-0">
                        <td className="px-4 py-3 font-semibold text-xs tracking-wider" style={{ color: SIGNAL_COLOR[sig] }}>{sig}</td>
                        <td className="px-4 py-3 font-mono text-gray-200">{s.obs}</td>
                        <td className="px-4 py-3 font-mono text-gray-200">{fmtRet(s.avg_30d)}</td>
                        <td className="px-4 py-3 font-mono text-gray-200">{fmtRet(s.avg_90d)}</td>
                        <td className="px-4 py-3 text-xs text-gray-500">
                          {s.recent_dates.slice(-3).join(",\n").split(",").map((d, i) => <div key={i}>{d.trim()}</div>)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Backtest chart */}
          <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-5">
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm font-semibold text-gray-200">Backtest visual: spot vs model-shaped PV</div>
              <div className="text-xs text-gray-600">black=spot · blue=model-shaped PV normalized</div>
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={btData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" vertical={false} />
                <XAxis dataKey="date" ticks={btTicks} tickFormatter={dateLbl}
                  tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tickFormatter={(v: number) => `$${v.toFixed(0)}`} tick={{ fill: "#6b7280", fontSize: 10 }}
                  axisLine={false} tickLine={false} width={38} domain={["auto", "auto"]} scale="log" />
                <Tooltip contentStyle={{ background: "#1a1d29", border: "1px solid #2d3144", borderRadius: 8, fontSize: 11 }}
                  formatter={(v: number, name: string) => {
                    if (name === "pv") return [`$${(v as number).toFixed(2)}`, "Model PV"];
                    if (typeof v === "number") return [`$${v.toFixed(2)}`, "Spot"];
                    return [null, null];
                  }} />
                {/* Scored segments */}
                <Line type="monotone" dataKey="spot_good"            stroke="#4ade80" strokeWidth={2} dot={{ r: 3, fill: "#4ade80", strokeWidth: 0 }} connectNulls={false} legendType="none" />
                <Line type="monotone" dataKey="spot_neutral"         stroke="#6b7280" strokeWidth={2} dot={{ r: 3, fill: "#6b7280", strokeWidth: 0 }} connectNulls={false} legendType="none" />
                <Line type="monotone" dataKey="spot_bad"             stroke="#f87171" strokeWidth={2} dot={{ r: 3, fill: "#f87171", strokeWidth: 0 }} connectNulls={false} legendType="none" />
                {/* Unscored (faded) — same signal color so you can see the current regime */}
                <Line type="monotone" dataKey="spot_unscored_good"    stroke="#4ade80" strokeWidth={1.5} strokeOpacity={0.35} dot={{ r: 3, fill: "#4ade80", strokeWidth: 0, fillOpacity: 0.35 }} connectNulls={false} legendType="none" />
                <Line type="monotone" dataKey="spot_unscored_neutral" stroke="#6b7280" strokeWidth={1.5} strokeOpacity={0.35} dot={{ r: 3, fill: "#6b7280", strokeWidth: 0, fillOpacity: 0.35 }} connectNulls={false} legendType="none" />
                <Line type="monotone" dataKey="spot_unscored_bad"     stroke="#f87171" strokeWidth={1.5} strokeOpacity={0.35} dot={{ r: 3, fill: "#f87171", strokeWidth: 0, fillOpacity: 0.35 }} connectNulls={false} legendType="none" />
                {/* Blue PV line */}
                <Line type="monotone" dataKey="pv" stroke="#60a5fa" strokeWidth={1.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
            <p className="text-xs text-gray-600 mt-3 leading-relaxed">
              Colored line = HYPE spot (green=GOOD, grey=NEUTRAL, red=BAD). Faded tail = recent unscored dates without enough forward return history yet — same signal color so the current regime is visible. Blue line = model-shaped PV proxy normalized to current P50 PV. Preliminary diagnostic, not a full historical MC replay.
            </p>
          </div>
        </div>
      )}

      {/* ── 2. Historical buyback horizon ───────────────────────────── */}
      {buyback.length > 0 && (
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-5">
          <div className="flex items-center justify-between mb-2">
            <div className="text-sm font-semibold text-gray-200">Historical buyback horizon</div>
            {bbLatest && <div className="text-xs text-gray-500 font-mono">latest {fmtYr(bbLatest.years)}</div>}
          </div>
          <div className="text-xs text-gray-600 text-right mb-1">trailing-30D fee revenue annualized ÷ date price; target=circ+3Y gross issuance</div>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={bbSampled} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" vertical={false} />
              <XAxis dataKey="date" ticks={bbTicks} tickFormatter={dateLbl}
                tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={fmtYr} tick={{ fill: "#6b7280", fontSize: 10 }}
                axisLine={false} tickLine={false} width={32} domain={[bbMin, bbMax]} />
              <Tooltip contentStyle={{ background: "#1a1d29", border: "1px solid #2d3144", borderRadius: 8, fontSize: 11 }}
                formatter={(v: number) => [`${v.toFixed(1)}y`, "Buyback horizon"]} />
              <Line type="monotone" dataKey="years" stroke="#e5e7eb" strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
          <p className="text-xs text-gray-600 mt-3 leading-relaxed">
            Uses each date&apos;s HYPE price and trailing-30D annualized DefiLlama fee revenue only. Target = current circulating supply + modeled 3Y gross issuance. Current fee-only 30D horizon is {bbLatest ? fmtYr(bbLatest.years) : "—"}.
          </p>
        </div>
      )}

      {/* ── 3. Model implied EOY3 market share ──────────────────────── */}
      {eoy3.length > 0 && (
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-5">
          <div className="flex items-center justify-between mb-1">
            <div className="text-sm font-semibold text-gray-200">Model implied EOY3 Hyperliquid/Binance market share</div>
            {e3Latest && <div className="text-xs text-gray-500 font-mono">12M {pct(e3Latest.eoy3)}</div>}
          </div>
          <div className="text-xs text-gray-600 text-right mb-2">blue=current 12M decay · grey=MS90 · dashed=MS30</div>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={e3Sampled} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" vertical={false} />
              <XAxis dataKey="date" ticks={e3Ticks} tickFormatter={dateLbl}
                tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} width={36} />
              <Tooltip contentStyle={{ background: "#1a1d29", border: "1px solid #2d3144", borderRadius: 8, fontSize: 11 }}
                formatter={(v: number, name: string) => [`${(v * 100).toFixed(1)}%`,
                  name === "eoy3" ? "12M decay EOY3" : name === "ms90" ? "MS90" : "MS30"]} />
              <Line type="monotone" dataKey="eoy3" stroke="#60a5fa" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="ms90" stroke="#6b7280" strokeWidth={1.5} dot={false} />
              <Line type="monotone" dataKey="ms30" stroke="#9ca3af" strokeWidth={1} dot={false} strokeDasharray="4 2" />
            </LineChart>
          </ResponsiveContainer>
          <p className="text-xs text-gray-600 mt-3 leading-relaxed">
            Historical time series of the model-implied Year-3 terminal HL/Binance share using the same MS90 seed and MS30/MS180 velocity-decay rule. The current 12M-decay model point is {e3Latest ? pct(e3Latest.eoy3) : "—"}. Shows the terminal share embedded in the locked valuation model.
          </p>
        </div>
      )}

    </div>
  );
}

// ── HypeModelOutputs ─────────────────────────────────────────────────────────

function HypeModelOutputs({ scenario, spot }: { scenario: ValuationScenario; spot: number }) {
  const {
    y3_price_p50, y3_mcap_p50, y3_supply_p50, y3_gp_p50,
    ev_mcap, burn_3y_est, y3_volume,
  } = scenario;

  if (!y3_price_p50) return null;

  const vol = y3_volume as Y3Volume;

  return (
    <div className="space-y-3">
      <h3 className="text-xl font-bold text-white">Model outputs</h3>

      {/* ── Summary table ───────────────────────────────────────────── */}
      <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#2d3144]">
                {["CASE", "P50 PRICE", "P50 MCAP", "P50 PV", "EV PV/TOKEN", "PV MCAP EV", "P(SPOT)"].map((h) => (
                  <th key={h} className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="px-5 py-4 text-gray-200 font-medium whitespace-nowrap">Selected model</td>
                <td className="px-5 py-4 font-mono text-white whitespace-nowrap">{fmtPrice(y3_price_p50!)}</td>
                <td className="px-5 py-4 font-mono text-white whitespace-nowrap">{fmtLarge(y3_mcap_p50 ?? 0)}</td>
                <td className="px-5 py-4 font-mono text-white whitespace-nowrap">{fmtPrice(scenario.pv.p50)}</td>
                <td className="px-5 py-4 font-mono text-white whitespace-nowrap">{fmtPrice(scenario.ev)}</td>
                <td className="px-5 py-4 font-mono text-white whitespace-nowrap">{fmtLarge(ev_mcap ?? 0)}</td>
                <td className="px-5 py-4 font-mono whitespace-nowrap" style={{ color: scenario.prob_above_spot >= 0.5 ? "#4ade80" : "#f87171" }}>
                  {pct(scenario.prob_above_spot)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Bottom metric cards ──────────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] px-5 py-4">
          <div className="text-xs text-gray-500 font-mono mb-1">Y3 GP / supply</div>
          <div className="text-2xl font-bold text-white font-mono">
            {fmtLarge(y3_gp_p50 ?? 0)} / {((y3_supply_p50 ?? 0) / 1e6).toFixed(0)}M
          </div>
          <div className="text-xs text-gray-600 mt-1">Selected-model P50 end-Year-3.</div>
        </div>
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] px-5 py-4">
          <div className="text-xs text-gray-500 font-mono mb-1">P50 path daily volume</div>
          <div className="text-2xl font-bold text-white font-mono">
            {fmtLarge(vol?.avg ?? 0)}
          </div>
          <div className="text-xs text-gray-600 mt-1">
            Min {fmtLarge(vol?.min ?? 0)} / Avg {fmtLarge(vol?.avg ?? 0)} / Max {fmtLarge(vol?.max ?? 0)}.
          </div>
        </div>
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] px-5 py-4">
          <div className="text-xs text-gray-500 font-mono mb-1">EOY3 market share</div>
          <div className="text-2xl font-bold text-white font-mono">
            {pct(vol?.eoy_market_share ?? 0)}
          </div>
          <div className="text-xs text-gray-600 mt-1">After 12M velocity decay; gained share held.</div>
        </div>
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] px-5 py-4">
          <div className="text-xs text-gray-500 font-mono mb-1">Total burn EOY3</div>
          <div className="text-2xl font-bold text-white font-mono">
            {((burn_3y_est ?? 0) / 1e6).toFixed(0)}M
          </div>
          <div className="text-xs text-gray-600 mt-1">Modeled cumulative token buyback/burn.</div>
        </div>
      </div>
    </div>
  );
}

// ── HypeModelAssumptions ─────────────────────────────────────────────────────

function HypeModelAssumptions({ data }: { data: ValuationData }) {
  const gp = data.current_gp;
  const supplyVelocity = gp["supply_velocity_monthly"] as number | undefined;
  const gross3y        = gp["gross_3y"] as number | undefined;
  const burn3y         = gp["burn_3y_est"] as number | undefined;
  const dr             = data.model.discount_rate;

  if (!supplyVelocity) return null;

  const net3y = (gross3y ?? 0) - (burn3y ?? 0);
  const drPct = `${(dr * 100).toFixed(0)}%`;

  return (
    <div className="space-y-3">
      <h3 className="text-xl font-bold text-white">Model assumptions</h3>

      {/* ── Top row: formula cards ───────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-5">
          <div className="text-sm font-semibold text-gray-200 mb-3">Core revenue lines</div>
          <pre className="text-xs font-mono text-gray-400 leading-relaxed bg-[#252836] rounded-lg p-4 overflow-x-auto whitespace-pre-wrap">
{`perp_GP_t = BinanceVol_t × HLShare_t × 0.034%
USDC_GP_t = USDC_TVL_t × net_yield × 90% / 12
USDC TVL follows HL volume path ^ 0.22`}
          </pre>
        </div>
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-5">
          <div className="text-sm font-semibold text-gray-200 mb-3">Valuation logic</div>
          <pre className="text-xs font-mono text-gray-400 leading-relaxed bg-[#252836] rounded-lg p-4 overflow-x-auto whitespace-pre-wrap">
{`Y3 price = Y3 TTM GP × multiple / Y3 supply × 1.10
PV = Y3 price / (1+${drPct})^3
Multiple: 20× trough / 15× normal / 10× peak`}
          </pre>
        </div>
      </div>

      {/* ── Bottom row: metric cards ─────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] px-5 py-4">
          <div className="text-xs text-gray-500 mb-1">Supply velocity</div>
          <div className="text-2xl font-bold text-white font-mono">
            {(supplyVelocity / 1e6).toFixed(2)}M/mo
          </div>
          <div className="text-xs text-gray-600 mt-1">Selected-model gross release.</div>
        </div>
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] px-5 py-4">
          <div className="text-xs text-gray-500 mb-1">3Y gross / burn / net</div>
          <div className="text-2xl font-bold text-white font-mono">
            {((gross3y ?? 0) / 1e6).toFixed(0)}M / {((burn3y ?? 0) / 1e6).toFixed(0)}M / {net3y >= 0 ? "+" : ""}{(net3y / 1e6).toFixed(0)}M
          </div>
          <div className="text-xs text-gray-600 mt-1">Gross release / estimated burn / net supply change.</div>
        </div>
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] px-5 py-4">
          <div className="text-xs text-gray-500 mb-1">Revenue inclusion</div>
          <div className="text-2xl font-bold text-white font-mono">Fees ≠ Yield</div>
          <div className="text-xs text-gray-600 mt-1">DefiLlama fee revenue excludes USDC stablecoin yield; modeled separately.</div>
        </div>
      </div>
    </div>
  );
}

// ── TokenView ────────────────────────────────────────────────────────────────

function TokenView({ tokenKey, token }: { tokenKey: string; token: TokenResult }) {
  if (token.status === "error") {
    return (
      <div className="bg-[#1a1d29] rounded-xl p-8 border border-red-500/30">
        <div className="text-red-400 font-mono text-sm">{token.error}</div>
      </div>
    );
  }

  const d           = token.data!;
  const primary     = d.scenarios.find((s) => s.is_primary) ?? d.scenarios[0];
  const chartColor  = TOKEN_COLORS[tokenKey] ?? "#60a5fa";
  const spot        = d.market.spot;
  const p50Upside   = spot > 0 ? (primary.pv.p50 / spot - 1) * 100 : 0;
  const dr          = (d.model.discount_rate * 100).toFixed(1);
  const probColor   = primary.prob_above_spot >= 0.5
    ? "green"
    : primary.prob_above_spot >= 0.35
    ? "yellow"
    : "red";

  const gp = d.current_gp;
  const isHypeWithMs = tokenKey === "hype" && typeof gp["ms90_vs_binance"] === "number";
  const velocity = gp["growth_velocity_pp"] as number | undefined;

  return (
    <div className="space-y-5">

      {/* ── Metric cards ─────────────────────────────────────────────── */}
      {isHypeWithMs ? (
        /* HYPE-specific cards matching the dashboard design */
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {/* Card 1: Spot / mcap / circ */}
          <MetricCard
            label="Spot / mcap / circ"
            value={fmtPrice(spot)}
            sub={`Mcap ${fmtLarge(d.market.market_cap)} · circ ${(d.market.circulating_supply / 1e6).toFixed(0)}M HYPE`}
          />
          {/* Card 2: MS90 valuation seed */}
          <MetricCard
            label="MS90 valuation seed"
            value={pct(gp["ms90_vs_binance"] as number)}
            sub="Starting HL/Binance share used in the model"
            termKey="ms90"
          />
          {/* Card 3: MCP MS30 vs Binance */}
          <MetricCard
            label="MCP MS30 vs Binance"
            value={pct(gp["ms30_vs_binance"] as number)}
            sub="DefiLlama 30D derivatives volume / Binance Futures proxy"
            termKey="ms30"
          />
          {/* Card 4: MS30 / MS180 */}
          <MetricCard
            label="MS30 / MS180"
            value={`${(gp["ms30_ms180_trend"] as number).toFixed(2)}×`}
            sub="Market-share trend growth. Recent record/near-record share signal."
            accent={(gp["ms30_ms180_trend"] as number) >= 1.1 ? "green" : "default"}
          />
          {/* Card 5: Growth velocity */}
          {velocity !== undefined && (
            <MetricCard
              label="Growth velocity"
              value={`${velocity >= 0 ? "+" : ""}${velocity.toFixed(1)}pp`}
              sub="30D share change vs 90D valuation seed"
              accent={velocity >= 0 ? "green" : "red"}
            />
          )}
          {/* Card 6: Selected P50 PV / token */}
          <MetricCard
            label="Selected P50 PV / token"
            value={fmtPrice(primary.pv.p50)}
            sub={`Probability-weighted EV ${fmtPrice(primary.ev)}`}
            accent={p50Upside >= 0 ? "green" : "red"}
            termKey="p50"
          />
        </div>
      ) : (
        /* Per-token cards matching HYPE style */
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {/* Card 1: always spot/mcap */}
          <MetricCard
            label="Spot / mcap / circ"
            value={fmtPrice(spot)}
            sub={`Mcap ${fmtLarge(d.market.market_cap)} · circ ${(d.market.circulating_supply / 1e6).toFixed(0)}M ${d.token}`}
          />
          {/* Card 2–4: token-specific GP metrics */}
          {tokenKey === "uni" && <>
            <MetricCard label="GP current state (ann.)" value={fmtLarge(gp["annualized_current_state"] as number)} sub="Protocol fees at current take rate" />
            <MetricCard label="GP full activation (ann.)" value={fmtLarge(gp["annualized_full_activation"] as number)} sub="25% of LP fees → protocol" />
            {gp["ms30_vs_dex"] != null
              ? <MetricCard label="MS30 vs Total DEX" value={pct(gp["ms30_vs_dex"] as number)} sub={`MS30/MS180 trend ${(gp["ms30_ms180_trend"] as number)?.toFixed(2)}×`} accent={(gp["ms30_ms180_trend"] as number) >= 1.05 ? "green" : "default"} />
              : <MetricCard label="Annual volume" value={fmtLarge(gp["ann_volume"] as number)} sub={`Mcap/GP ${(gp["mcap_current_state_gp"] as number)?.toFixed(0)}× (current state)`} />
            }
          </>}
          {tokenKey === "ethfi" && <>
            <MetricCard label="Total GP (ann.)" value={fmtLarge(gp["total_annualized"] as number)} sub="Card + staking + vault" />
            <MetricCard label="Card GDV (ann.)" value={fmtLarge(gp["card_gdv_30d_ann"] as number)} sub={`Take: ${((gp["card_take_bps_30d"] as number) ?? 0).toFixed(2)} bps`} />
            {gp["ms30_vs_lrt"] != null
              ? <MetricCard label="MS30 vs Total LRT" value={pct(gp["ms30_vs_lrt"] as number)} sub={`MS30/MS180 trend ${(gp["ms30_ms180_trend"] as number)?.toFixed(2)}×`} accent={(gp["ms30_ms180_trend"] as number) >= 1.0 ? "default" : "red"} />
              : <MetricCard label="Staking APY / TVL" value={pct(gp["staking_apy"] as number)} sub={`TVL ${fmtLarge(gp["stake_tvl"] as number)}`} />
            }
          </>}
          {tokenKey === "jup" && <>
            <MetricCard label="Total 30D GP" value={fmtLarge(gp["total_30d"] as number)} sub="Perps + aggregator + Jupiterz" />
            <MetricCard label="Seed GP (ann.)" value={fmtLarge(gp["seed_annualized"] as number)} sub={`Seed monthly ${fmtLarge(gp["seed_monthly"] as number)}`} />
            {gp["ms30_vs_sol_perps"] != null
              ? <MetricCard label="MS30 vs Solana Perps" value={pct(gp["ms30_vs_sol_perps"] as number)} sub={`MS30/MS180 trend ${(gp["ms30_ms180_trend"] as number)?.toFixed(2)}×`} accent={(gp["ms30_ms180_trend"] as number) >= 1.0 ? "green" : "default"} />
              : <MetricCard label="Perps 30D" value={fmtLarge(gp["perps_30d"] as number)} sub={`Aggregator ${fmtLarge(gp["aggregator_30d"] as number)}`} />
            }
          </>}
          {tokenKey === "sky" && <>
            <MetricCard label="Gross income (ann.)" value={fmtLarge(gp["gross_income"] as number)} sub={`Yield ${((gp["gross_income_yield_pct"] as number) ?? 0).toFixed(2)}% on USDS+DAI supply`} />
            <MetricCard label="Current GP (ann.)" value={fmtLarge(gp["current_gp"] as number)} sub={`After savings rate & stUSDS cost`} />
            {gp["ms30_vs_stables"] != null
              ? <MetricCard label="MS30 vs All Stablecoins" value={pct(gp["ms30_vs_stables"] as number)} sub={`MS30/MS180 trend ${(gp["ms30_ms180_trend"] as number)?.toFixed(2)}×`} accent={(gp["ms30_ms180_trend"] as number) >= 1.0 ? "green" : "default"} />
              : <MetricCard label="USDS + DAI supply" value={fmtLarge((gp["usds_supply"] as number) + (gp["dai_supply"] as number))} sub="Sky stablecoin total" />
            }
          </>}
          {/* Fallback for unknown tokens */}
          {!["uni", "ethfi", "jup", "sky"].includes(tokenKey) && <>
            <MetricCard label="Market Cap" value={fmtLarge(d.market.market_cap)} sub={`FDV ${fmtLarge(d.market.fdv)}`} />
            <MetricCard label="Circ. Supply" value={`${(d.market.circulating_supply / 1e6).toFixed(0)}M`} sub={`of ${(d.market.max_supply / 1e6).toFixed(0)}M max`} />
            <MetricCard label="EV (mean)" value={fmtPrice(primary.ev)} accent="blue" termKey="ev" />
          </>}
          {/* Card 5–6: always P50 + P(spot) */}
          <MetricCard
            label="P50 Fair Value"
            value={fmtPrice(primary.pv.p50)}
            sub={`P25 ${fmtPrice(primary.pv.p25)} · P75 ${fmtPrice(primary.pv.p75)}`}
            accent={p50Upside >= 0 ? "green" : "red"}
            termKey="p50"
          />
          <MetricCard
            label="P(above spot)"
            value={pct(primary.prob_above_spot)}
            sub={`P50 ${p50Upside >= 0 ? "+" : ""}${p50Upside.toFixed(0)}% vs spot · EV ${fmtPrice(primary.ev)}`}
            accent={probColor as "green" | "red" | "yellow"}
            termKey="prob_above_spot"
          />
        </div>
      )}

      {/* ── Model info strip ─────────────────────────────────────────── */}
      <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] px-6 py-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-gray-500">
        <span className="text-gray-400 font-medium">{d.model.type}</span>
        <span className="flex items-center gap-1">DR <InfoTooltip termKey="dr" /><span className="text-gray-300 ml-1">{dr}%</span></span>
        <span className="flex items-center gap-1">{d.model.multiple}× multiple <InfoTooltip termKey="multiple" /></span>
        <span className="flex items-center gap-1">{(d.model.paths / 1000).toFixed(0)}k paths <InfoTooltip termKey="paths" /></span>
        {d.data_freshness && <span>data as of <span className="text-gray-300">{d.data_freshness}</span></span>}
      </div>

      {/* ── Market share trend ───────────────────────────────────────── */}
      {(tokenKey === "hype" || tokenKey === "uni" || tokenKey === "ethfi" || tokenKey === "jup" || tokenKey === "sky") && <MarketShareSection data={d} tokenKey={tokenKey} />}

      {/* ── Model assumptions ────────────────────────────────────────── */}
      {tokenKey === "hype" && <HypeModelAssumptions data={d} />}

      {/* ── Model outputs ────────────────────────────────────────────── */}
      {tokenKey === "hype" && primary.y3_price_p50 && (
        <HypeModelOutputs scenario={primary} spot={spot} />
      )}

      {/* ── Non-HYPE: key metrics (HYPE only) ────────────────────────── */}

      {/* ── Non-HYPE: model assumptions ───────────────────────────────── */}
      {tokenKey !== "hype" && <TokenModelAssumptions tokenKey={tokenKey} model={d.model} />}

      {/* ── Scenario comparison table ─────────────────────────────────── */}
      <ScenarioTable scenarios={d.scenarios} spot={spot} />

      {/* ── PV price distribution ─────────────────────────────────────── */}
      <DistributionChart scenario={primary} spot={spot} ev={primary.ev} />


      {/* ── HYPE: Historical charts (backtest, buyback, EOY3 MS) ─────── */}
      {tokenKey === "hype" && d.hist_charts && <HypeHistoricalCharts hc={d.hist_charts} />}

      {/* ── HYPE: DefiLlama MCP weekly answer ────────────────────────── */}
      {tokenKey === "hype" && d.mcp_bullets && d.mcp_bullets.length > 0 && (
        <HypeMcpWeekly bullets={d.mcp_bullets} asOf={d.data_freshness} />
      )}

      {d.as_of_utc && (
        <div className="text-xs text-gray-600 text-right">
          Valuation computed {new Date(d.as_of_utc).toLocaleString()}
        </div>
      )}
    </div>
  );
}

// ── HypeMcpWeekly ─────────────────────────────────────────────────────────────

function HypeMcpWeekly({ bullets, asOf }: { bullets: string[]; asOf?: string }) {
  return (
    <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-6">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h3 className="text-lg font-bold text-white">DefiLlama MCP weekly answer</h3>
          <p className="text-sm text-gray-400 mt-0.5">
            Top 5 trailing-30D updates fetched now, not just scheduled.
          </p>
        </div>
        {asOf && <div className="text-xs text-gray-600 shrink-0">as of {asOf}</div>}
      </div>
      <ul className="space-y-2.5">
        {bullets.map((b, i) => (
          <li key={i} className="flex items-start gap-3">
            <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0" />
            <span className="text-sm text-gray-300 leading-relaxed font-medium">{b}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Token picker ─────────────────────────────────────────────────────────────

const TOKEN_RING: Record<string, string> = {
  uni:   "#ff007a",
  ethfi: "#06b6d4",
  jup:   "#9945ff",
  hype:  "#00e5a0",
  sky:   "#f59e0b",
};

// ── Main dashboard ───────────────────────────────────────────────────────────

export default function ValuationDashboard({ data }: Props) {
  const tokens      = Object.entries(data.tokens);
  const [selected, setSelected] = useState<string>(tokens[0]?.[0] ?? "");
  const activeToken = data.tokens[selected];

  return (
    <div className="min-h-screen bg-[#0f1117] text-white">
      <header className="border-b border-[#2d3144] px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Crypto Valuations</h1>
            <p className="text-sm text-gray-500 mt-0.5">updated {data.lastUpdated || "—"}</p>
          </div>
          <Nav />
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 sm:px-6 py-8">
        {tokens.length === 0 ? (
          <div className="text-center py-24 text-gray-400">No valuation data yet.</div>
        ) : (
          <>
            {/* Token picker */}
            <div className="flex gap-3 mb-8 flex-wrap">
              {tokens.map(([key, token]) => {
                const active   = key === selected;
                const spot     = token.data?.market.spot;
                const primary  = token.data?.scenarios.find((s) => s.is_primary) ?? token.data?.scenarios[0];
                const p50      = primary?.pv.p50;
                const ring     = TOKEN_RING[key] ?? "#60a5fa";

                return (
                  <button
                    key={key}
                    onClick={() => setSelected(key)}
                    className="flex items-center gap-4 px-5 py-3 rounded-xl border transition-all text-left"
                    style={{
                      background:   active ? `${ring}12` : "#1a1d29",
                      borderColor:  active ? ring : "#2d3144",
                    }}
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span
                          className="text-base font-bold"
                          style={{ color: active ? ring : "#e5e7eb" }}
                        >
                          {token.symbol}
                        </span>
                        <span className="text-xs text-gray-500">{token.chain}</span>
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">{token.name}</div>
                    </div>
                    <div className="text-right ml-2">
                      {spot !== undefined && (
                        <div
                          className="text-base font-mono font-semibold"
                          style={{ color: active ? ring : "#9ca3af" }}
                        >
                          {fmtPrice(spot)}
                        </div>
                      )}
                      {p50 !== undefined && (
                        <div className="text-xs text-gray-600">
                          P50 {fmtPrice(p50)}
                        </div>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Active token */}
            {activeToken && (
              <div>
                <div className="flex items-baseline gap-3 mb-6 flex-wrap">
                  <h2 className="text-3xl font-bold text-white">{activeToken.symbol}</h2>
                  <span className="text-lg text-gray-400">{activeToken.name}</span>
                  {activeToken.data && (
                    <span
                      className="text-3xl font-bold font-mono ml-auto"
                      style={{ color: TOKEN_RING[selected] ?? "#60a5fa" }}
                    >
                      {fmtPrice(activeToken.data.market.spot)}
                    </span>
                  )}
                </div>
                <TokenView tokenKey={selected} token={activeToken} />
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
