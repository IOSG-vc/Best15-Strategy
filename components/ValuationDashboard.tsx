"use client";

import { useState, useRef, useEffect } from "react";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";
import type { ValuationsFile, TokenResult, ValuationScenario, McapPoint } from "@/lib/loadValuations";
import Nav from "./Nav";

interface Props {
  data: ValuationsFile;
}

// ── Term definitions ────────────────────────────────────────────────────────

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
    body: "The probability-weighted average across all 50–100k Monte Carlo paths. Pulled above P50 by the fat right tail of bull scenarios. Not a price target — more like a mathematical average of all possible futures.",
  },
  dr: {
    title: "Discount Rate",
    body: "The annualised rate used to bring Year-3 GP back to present value. Calculated using a liquid-token CAPM framework: risk-free rate + equity risk premium × (token volatility ÷ S&P 500 volatility). Higher volatility = higher DR = lower present value.",
  },
  multiple: {
    title: "15× GP Multiple",
    body: "Year-3 trailing-12-month gross profit is multiplied by 15× to get an enterprise value. This is consistent across all models here and is a mid-cycle assumption for a high-growth DeFi protocol. Not a perpetual DCF — it's a 3-year investment horizon valuation.",
  },
  paths: {
    title: "Monte Carlo Paths",
    body: "The number of simulated futures run. Each path draws random monthly growth shocks from the historical distribution of the protocol's volume/revenue. More paths = smoother percentile estimates. 50k–100k paths converge well for these distributions.",
  },
  prob_above_spot: {
    title: "Probability Above Spot",
    body: "Fraction of Monte Carlo paths where the model's 3-year discounted fair value exceeds the current spot price. A value above 50% means the model's central case implies the token is undervalued today.",
  },
  prob_3x: {
    title: "3× Probability",
    body: "Fraction of paths where the model fair value is at least 3× today's spot. A rough screen for asymmetric upside potential.",
  },
  upside: {
    title: "P50 Upside",
    body: "How far the median fair value (P50) is above or below the current spot price. Negative means the model's central estimate implies the token is fairly valued or stretched at current prices.",
  },
  gp_capture: {
    title: "GP-Capture Framework",
    body: "Rather than discounting all future cash flows to infinity (DCF), this model captures the gross profit the protocol is expected to generate in Year 3 and applies a 15× multiple. It asks: what will this protocol earn in 3 years, and what multiple does that deserve? Simpler, more robust to uncertainty, and standard in DeFi research.",
  },
};

// ── Per-token model methodology ─────────────────────────────────────────────

const METHODOLOGY: Record<string, { sections: { heading: string; text: string }[] }> = {
  uni: {
    sections: [
      {
        heading: "What is being valued",
        text: "Uniswap's protocol-level gross profit under two fee scenarios: current-state (fee switch partially active, ~0.826bps LP protocol take + 0.30bps frontend) and full-activation (25% of LP fees routed to protocol + 0.30bps frontend). This is a 3-year investment horizon — not a perpetual DCF.",
      },
      {
        heading: "Volume simulation",
        text: "Monthly volume history is pulled from DeFiLlama (2021–present). The model bootstraps monthly log-returns from this history and seeds each MC run at min(latest 30D volume, trailing 12M median). 36 months are simulated and Year-3 trailing-12M volume is valued.",
      },
      {
        heading: "Discount rate",
        text: "Liquid-token CAPM: risk-free rate (10Y Treasury) + 3% ERP × (UNI daily volatility ÷ S&P 500 daily volatility), producing ~24–25% DR. Refreshed on each run using live market data.",
      },
      {
        heading: "Supply & multiple",
        text: "15× GP multiple applied to Year-3 GP, discounted at the DR. Primary basis is circulating supply. An FDV sensitivity (using max supply) is shown as a secondary scenario. Protocol fees burn UNI via TokenJar → Firepit; no cash accumulation line is added.",
      },
      {
        heading: "Model locked",
        text: "Methodology locked 2026-05-09. Scenarios and assumptions will not change between runs unless the locked model is revised.",
      },
    ],
  },
  ethfi: {
    sections: [
      {
        heading: "What is being valued",
        text: "ether.fi's gross profit from three revenue streams: (1) card business — GDV × 135bps take × operating margin, (2) liquid staking — staking TVL × staking APY × 5% protocol take, (3) vaults — vault TVL × 1% flat fee. This is a bottom-up GP build, not a revenue multiple.",
      },
      {
        heading: "Scenario weighting",
        text: "Three scenarios are simulated: Bear (50% card margin), Base (60%), Bull (70%). Weighted distribution: 20% bear, 40% base, 40% bull. Monte Carlo is run per scenario for ETH price paths (affects staking TVL value). 50k paths total.",
      },
      {
        heading: "Discount rate",
        text: "Fixed at 27.5% — reflecting higher execution risk vs UNI given earlier-stage card business and ETH price dependency. Not refreshed dynamically (unlike UNI).",
      },
      {
        heading: "Supply & multiple",
        text: "15× GP multiple applied to Year-3 GP. Supply uses 854.7M ETHFI projected supply at Year 3. Treasury cash is added back to the equity value (additive to the GP-capture valuation).",
      },
      {
        heading: "Key risks",
        text: "Card GDV growth is the dominant driver — if the card business underperforms, fair value converges to the bear scenario. Staking APY compression (more ETH staked globally) reduces staking GP over time.",
      },
    ],
  },
  jup: {
    sections: [
      {
        heading: "What is being valued",
        text: "Jupiter's entity-level gross profit from two core products: (1) Perpetuals — 25% of gross perps fees (75% goes to JLP LPs), (2) Spot aggregator/Ultra + Jupiterz — combined at ~3.55bps rake on GMV. Smaller products (DCA, Lend, jupSOL, Studio, Ape) are not simulated but are covered by the +10% optionality premium.",
      },
      {
        heading: "Buyback mechanics",
        text: "50% of simulated entity GP is assumed to be used for JUP buybacks via Litterbox Trust. Buybacks reduce the Year-3 effective supply denominator, which increases the per-token fair value. The other 50% goes to treasury/DAO operations.",
      },
      {
        heading: "Supply schedule",
        text: "0 scheduled unlocks per month are assumed. The ~3.4B JUP cold-storage/community reserve has no public distribution timeline. If a new schedule is announced, this assumption should be revised.",
      },
      {
        heading: "Discount rate & multiple",
        text: "Fixed at 24.4%, 15× GP multiple. Three premium cases: Core (no premium), +10% Optionality (smaller unmonetised products), +10% Opt + Jupnet (cross-chain expansion premium).",
      },
      {
        heading: "Model locked",
        text: "Methodology locked 2026-05-09, corrected 2026-05-15 for supply schedule and optional product tracking.",
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
          {/* Arrow */}
          <div className="absolute left-1/2 -translate-x-1/2 top-full w-2 h-2 border-r border-b border-[#3d4166] bg-[#1a1d29] rotate-45 -mt-1" />
        </div>
      )}
    </div>
  );
}

// ── ModelMethodology (collapsible) ──────────────────────────────────────────

function ModelMethodology({ tokenKey }: { tokenKey: string }) {
  const [open, setOpen] = useState(false);
  const m = METHODOLOGY[tokenKey];
  if (!m) return null;

  return (
    <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full px-6 py-4 flex items-center justify-between text-left hover:bg-[#1e2130] transition-colors"
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
      </button>

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

// ── McapChart ───────────────────────────────────────────────────────────────

function McapChart({ history, symbol, color }: { history: McapPoint[]; symbol: string; color: string }) {
  if (!history.length) return null;

  const min = Math.min(...history.map((d) => d.mcap));
  const max = Math.max(...history.map((d) => d.mcap));
  const latest = history[history.length - 1].mcap;
  const first  = history[0].mcap;
  const change = ((latest / first) - 1) * 100;
  const isUp   = change >= 0;

  function fmtMcap(n: number) {
    if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
    return `$${(n / 1e6).toFixed(0)}M`;
  }

  // Show only ~12 evenly-spaced x-axis ticks
  const step = Math.max(1, Math.floor(history.length / 12));
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
            tickFormatter={(d: string) => {
              const [, m, day] = d.split("-");
              return `${parseInt(m)}/${parseInt(day)}`;
            }}
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
            itemStyle={{ color: color }}
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

// ── Helpers ─────────────────────────────────────────────────────────────────

function fmtPrice(n: number): string {
  if (n >= 1) return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
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

function ProbBadge({ prob }: { prob: number }) {
  const color = prob >= 0.5 ? "#4ade80" : prob >= 0.35 ? "#fbbf24" : "#f87171";
  const bg    = prob >= 0.5 ? "#4ade8018" : prob >= 0.35 ? "#fbbf2418" : "#f8717118";
  return (
    <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-sm font-semibold"
      style={{ color, background: bg, border: `1px solid ${color}40` }}>
      {pct(prob)} above spot
      <InfoTooltip termKey="prob_above_spot" />
    </span>
  );
}

function PercentileBar({ pv, spot }: {
  pv: { p25: number; p50: number; p75: number; p90: number };
  spot: number;
}) {
  const max = Math.max(pv.p90 * 1.15, spot * 1.5);
  const toW = (v: number) => `${Math.min((v / max) * 100, 100).toFixed(2)}%`;
  const spotPct = Math.min((spot / max) * 100, 100);
  const rangeLeft = (pv.p25 / max) * 100;
  const rangeWidth = Math.min(((pv.p75 - pv.p25) / max) * 100, 100 - rangeLeft);

  return (
    <div className="relative h-8 bg-[#252836] rounded-xl overflow-hidden">
      <div
        className="absolute top-0 h-full rounded-xl opacity-50"
        style={{
          left: `${rangeLeft.toFixed(2)}%`,
          width: `${rangeWidth.toFixed(2)}%`,
          background: "linear-gradient(90deg, #6ee7b7, #10b981)",
        }}
      />
      <div className="absolute top-1.5 h-5 w-0.5 bg-emerald-300 rounded"
        style={{ left: toW(pv.p50) }} />
      <div className="absolute top-0 h-full w-0.5 bg-orange-400 opacity-90"
        style={{ left: `${spotPct.toFixed(2)}%` }} />
    </div>
  );
}

function ScenarioCard({ s, spot, isPrimary }: { s: ValuationScenario; spot: number; isPrimary: boolean }) {
  const upside = spot > 0 ? (s.pv.p50 / spot - 1) * 100 : 0;
  return (
    <div className={`rounded-xl border p-5 ${
      isPrimary
        ? "border-emerald-500/40 bg-emerald-500/5"
        : "border-[#2d3144] bg-[#1e2130]"
    }`}>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="text-base font-semibold text-white">{s.label}</span>
          {isPrimary && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
              primary
            </span>
          )}
        </div>
        <ProbBadge prob={s.prob_above_spot} />
      </div>

      <PercentileBar pv={s.pv} spot={spot} />

      {/* Legend */}
      <div className="flex items-center gap-4 mt-1.5 text-xs text-gray-500">
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-1 rounded bg-emerald-400 opacity-60" /> P25–P75 range
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-0.5 h-3 rounded bg-emerald-300" /> P50 median
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-0.5 h-3 rounded bg-orange-400" /> spot
        </span>
      </div>

      {/* Percentile grid */}
      <div className="grid grid-cols-5 gap-3 mt-4">
        {(["p25", "p50", "p75", "p90"] as const).map((p) => (
          <div key={p} className="bg-[#252836] rounded-lg px-3 py-2.5 text-center">
            <div className="text-xs text-gray-500 mb-1 flex items-center justify-center gap-0.5">
              {p.toUpperCase()} <InfoTooltip termKey={p} />
            </div>
            <div className="text-sm font-mono font-semibold text-gray-100">
              {fmtPrice(s.pv[p])}
            </div>
          </div>
        ))}
        <div className="bg-[#1a2640] rounded-lg px-3 py-2.5 text-center border border-blue-500/20">
          <div className="text-xs text-blue-400 mb-1 flex items-center justify-center gap-0.5">
            EV <InfoTooltip termKey="ev" />
          </div>
          <div className="text-sm font-mono font-semibold text-blue-300">
            {fmtPrice(s.ev)}
          </div>
        </div>
      </div>

      {/* Footer stats */}
      <div className="mt-3 flex flex-wrap gap-4 text-sm">
        <span className="text-gray-500 flex items-center gap-1">
          P50 upside <InfoTooltip termKey="upside" />:{" "}
          <span className={upside >= 0 ? "text-emerald-400 font-semibold" : "text-red-400 font-semibold"}>
            {upside >= 0 ? "+" : ""}{upside.toFixed(0)}%
          </span>
        </span>
        {s.prob_3x !== undefined && (
          <span className="text-gray-500 flex items-center gap-1">
            3× probability <InfoTooltip termKey="prob_3x" />:{" "}
            <span className="text-gray-300 font-medium">{pct(s.prob_3x)}</span>
          </span>
        )}
      </div>
    </div>
  );
}

const TOKEN_COLORS: Record<string, string> = {
  uni:   "#ff007a",
  ethfi: "#06b6d4",
  jup:   "#9945ff",
  hype:  "#00e5a0",
  sky:   "#f59e0b",
};

function TokenView({ tokenKey, token }: { tokenKey: string; token: TokenResult }) {
  if (token.status === "error") {
    return (
      <div className="bg-[#1a1d29] rounded-xl p-8 border border-red-500/30">
        <div className="text-red-400 font-mono text-sm">{token.error}</div>
      </div>
    );
  }

  const d = token.data!;
  const primary = d.scenarios.find((s) => s.is_primary) ?? d.scenarios[0];
  const others  = d.scenarios.filter((s) => s !== primary);
  const dr      = (d.model.discount_rate * 100).toFixed(1);
  const chartColor = TOKEN_COLORS[tokenKey] ?? "#60a5fa";

  return (
    <div className="space-y-5">
      {/* Market summary */}
      <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-6">
        <div className="flex items-start justify-between flex-wrap gap-4">
          <div>
            <div className="flex items-center gap-1.5 text-sm text-gray-500 mb-1">
              {d.model.type}
              <InfoTooltip termKey="gp_capture" />
            </div>
            <div className="flex flex-wrap gap-5 text-sm text-gray-400">
              <span className="flex items-center gap-1">
                DR <InfoTooltip termKey="dr" />
                <span className="text-white font-medium ml-1">{dr}%</span>
              </span>
              <span className="flex items-center gap-1">
                <span>{d.model.multiple}× multiple</span>
                <InfoTooltip termKey="multiple" />
              </span>
              <span className="flex items-center gap-1">
                <span>{(d.model.paths / 1000).toFixed(0)}k paths</span>
                <InfoTooltip termKey="paths" />
              </span>
              {d.data_freshness && (
                <span>data as of <span className="text-white">{d.data_freshness}</span></span>
              )}
            </div>
          </div>
          <div className="flex gap-6">
            <div className="text-right">
              <div className="text-xs text-gray-500">Market Cap</div>
              <div className="text-lg font-bold text-white">{fmtLarge(d.market.market_cap)}</div>
            </div>
            <div className="text-right">
              <div className="text-xs text-gray-500">FDV</div>
              <div className="text-lg font-bold text-white">{fmtLarge(d.market.fdv)}</div>
            </div>
            <div className="text-right">
              <div className="text-xs text-gray-500">Circ. Supply</div>
              <div className="text-lg font-bold text-white">
                {(d.market.circulating_supply / 1e6).toFixed(0)}M
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Market cap chart */}
      {token.mcap_history && token.mcap_history.length > 0 && (
        <McapChart history={token.mcap_history} symbol={d.token} color={chartColor} />
      )}

      {/* Primary scenario */}
      <ScenarioCard s={primary} spot={d.market.spot} isPrimary={true} />

      {/* Other scenarios */}
      {others.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wider">Other scenarios</h3>
          {others.map((s) => (
            <ScenarioCard key={s.key} s={s} spot={d.market.spot} isPrimary={false} />
          ))}
        </div>
      )}

      {/* Current GP */}
      <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-6">
        <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">
          Current GP metrics (annualized)
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {Object.entries(d.current_gp)
            .filter(([, v]) => typeof v === "number" && Math.abs(v as number) > 0)
            .map(([k, v]) => {
              const num = v as number;
              const isLarge = Math.abs(num) >= 1000;
              return (
                <div key={k} className="bg-[#252836] rounded-lg px-4 py-3">
                  <div className="text-xs text-gray-500 mb-1">{k.replace(/_/g, " ")}</div>
                  <div className="text-sm font-mono font-semibold text-gray-100">
                    {isLarge ? fmtLarge(num) : num.toFixed(4)}
                  </div>
                </div>
              );
            })}
        </div>
      </div>

      {/* Model methodology (collapsible) */}
      <ModelMethodology tokenKey={tokenKey} />

      {d.as_of_utc && (
        <div className="text-xs text-gray-600 text-right">
          Valuation computed {new Date(d.as_of_utc).toLocaleString()}
        </div>
      )}
    </div>
  );
}

// ── Main dashboard ───────────────────────────────────────────────────────────

export default function ValuationDashboard({ data }: Props) {
  const tokens = Object.entries(data.tokens);
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
                const active = key === selected;
                const spot   = token.data?.market.spot;
                return (
                  <button
                    key={key}
                    onClick={() => setSelected(key)}
                    className="flex items-center gap-4 px-5 py-3 rounded-xl border transition-all text-left"
                    style={{
                      background: active ? "#1a2640" : "#1a1d29",
                      borderColor: active ? "#3b82f6" : "#2d3144",
                    }}
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-base font-bold" style={{ color: active ? "#60a5fa" : "#e5e7eb" }}>
                          {token.symbol}
                        </span>
                        <span className="text-xs text-gray-500">{token.chain}</span>
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">{token.name}</div>
                    </div>
                    {spot !== undefined && (
                      <div className="text-right ml-2">
                        <div className="text-base font-mono font-semibold" style={{ color: active ? "#60a5fa" : "#9ca3af" }}>
                          {fmtPrice(spot)}
                        </div>
                        <div className="text-xs text-gray-600">spot</div>
                      </div>
                    )}
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
                    <span className="text-3xl font-bold font-mono text-blue-300 ml-auto">
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
