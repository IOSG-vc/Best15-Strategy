"use client";

import type { ValuationsFile, TokenResult, ValuationScenario } from "@/lib/loadValuations";
import Nav from "./Nav";

interface Props {
  data: ValuationsFile;
}

function fmt(n: number, decimals = 2): string {
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  if (n >= 1000) return `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  if (n >= 1) return `$${n.toFixed(decimals)}`;
  return `$${n.toFixed(4)}`;
}

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

function ProbBadge({ prob }: { prob: number }) {
  const color = prob >= 0.5 ? "#4ade80" : prob >= 0.35 ? "#fbbf24" : "#f87171";
  const bg    = prob >= 0.5 ? "#4ade8018" : prob >= 0.35 ? "#fbbf2418" : "#f8717118";
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold"
      style={{ color, background: bg, border: `1px solid ${color}40` }}>
      {pct(prob)} above spot
    </span>
  );
}

function PercentileBar({ pv, spot }: { pv: { p25: number; p50: number; p75: number; p90: number }; spot: number }) {
  const max = Math.max(pv.p90 * 1.1, spot * 1.5);
  const toW = (v: number) => `${Math.min((v / max) * 100, 100).toFixed(1)}%`;
  const spotW = Math.min((spot / max) * 100, 100);

  return (
    <div className="relative h-6 bg-[#252836] rounded-full overflow-hidden mt-1">
      {/* P25–P75 range bar */}
      <div
        className="absolute top-0 h-full rounded-full opacity-40"
        style={{
          left: toW(pv.p25),
          width: `${Math.min(((pv.p75 - pv.p25) / max) * 100, 100 - (pv.p25 / max) * 100).toFixed(1)}%`,
          background: "linear-gradient(90deg, #6ee7b7, #10b981)",
        }}
      />
      {/* P50 marker */}
      <div className="absolute top-1 h-4 w-0.5 bg-emerald-400 rounded"
        style={{ left: toW(pv.p50) }} />
      {/* Spot price marker */}
      <div className="absolute top-0 h-full w-0.5 bg-orange-400 opacity-80"
        style={{ left: `${spotW}%` }} />
    </div>
  );
}

function ScenarioRow({ s, spot, isPrimary }: { s: ValuationScenario; spot: number; isPrimary: boolean }) {
  const upside = spot > 0 ? (s.pv.p50 / spot - 1) * 100 : 0;
  return (
    <div className={`p-3 rounded-lg border ${isPrimary ? "border-emerald-500/40 bg-emerald-500/5" : "border-[#2d3144] bg-[#252836]"}`}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs font-medium text-gray-200">{s.label}</span>
        <div className="flex items-center gap-2">
          {isPrimary && (
            <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
              primary
            </span>
          )}
          <ProbBadge prob={s.prob_above_spot} />
        </div>
      </div>

      <PercentileBar pv={s.pv} spot={spot} />

      <div className="grid grid-cols-5 gap-1 mt-2 text-center">
        {(["p25", "p50", "p75", "p90"] as const).map((p) => (
          <div key={p}>
            <div className="text-gray-500 text-xs">{p.toUpperCase()}</div>
            <div className="text-xs font-mono font-medium text-gray-200">{fmt(s.pv[p])}</div>
          </div>
        ))}
        <div>
          <div className="text-gray-500 text-xs">EV</div>
          <div className="text-xs font-mono font-medium text-blue-300">{fmt(s.ev)}</div>
        </div>
      </div>

      <div className="mt-1.5 text-xs text-gray-500 text-right">
        P50 upside: <span className={upside >= 0 ? "text-emerald-400" : "text-red-400"}>
          {upside >= 0 ? "+" : ""}{upside.toFixed(0)}%
        </span>
        {s.prob_3x !== undefined && (
          <span className="ml-3">3× prob: <span className="text-gray-400">{pct(s.prob_3x)}</span></span>
        )}
      </div>
    </div>
  );
}

function TokenCard({ tokenKey, token }: { tokenKey: string; token: TokenResult }) {
  if (token.status === "error") {
    return (
      <div className="bg-[#1a1d29] rounded-xl p-5 border border-red-500/30">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-lg font-bold text-white">{token.symbol}</span>
          <span className="text-xs text-gray-500">{token.chain}</span>
        </div>
        <div className="text-red-400 text-xs font-mono">{token.error}</div>
      </div>
    );
  }

  const d = token.data!;
  const primary = d.scenarios.find((s) => s.is_primary) ?? d.scenarios[0];
  const others  = d.scenarios.filter((s) => s !== primary);
  const dr      = (d.model.discount_rate * 100).toFixed(1);

  return (
    <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 border-b border-[#2d3144] flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-xl font-bold text-white">{d.token}</h3>
            <span className="text-xs text-gray-500 bg-[#252836] px-2 py-0.5 rounded">{token.chain}</span>
          </div>
          <div className="text-sm text-gray-400 mt-0.5">{d.name}</div>
        </div>
        <div className="text-right">
          <div className="text-xl font-bold font-mono text-white">{fmt(d.market.spot)}</div>
          <div className="text-xs text-gray-500 mt-0.5">
            MCap {fmt(d.market.market_cap)} · FDV {fmt(d.market.fdv)}
          </div>
        </div>
      </div>

      {/* Model info strip */}
      <div className="px-5 py-2 bg-[#252836] border-b border-[#2d3144] flex flex-wrap gap-4 text-xs text-gray-500">
        <span>{d.model.type}</span>
        <span>DR {dr}%</span>
        <span>{d.model.multiple}× multiple</span>
        <span>{(d.model.paths / 1000).toFixed(0)}k paths</span>
        {d.data_freshness && <span>data: {d.data_freshness}</span>}
      </div>

      {/* Scenarios */}
      <div className="p-5 space-y-3">
        <ScenarioRow s={primary} spot={d.market.spot} isPrimary={true} />
        {others.map((s) => (
          <ScenarioRow key={s.key} s={s} spot={d.market.spot} isPrimary={false} />
        ))}
      </div>

      {/* Current GP */}
      <div className="px-5 pb-5">
        <div className="text-xs text-gray-500 mb-2 font-medium uppercase tracking-wide">Current GP (annualized)</div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1">
          {Object.entries(d.current_gp)
            .filter(([, v]) => typeof v === "number" && Math.abs(v) > 0)
            .slice(0, 6)
            .map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs py-0.5 border-b border-[#2d3144]">
                <span className="text-gray-500 truncate mr-2">{k.replace(/_/g, " ")}</span>
                <span className="font-mono text-gray-300 shrink-0">
                  {typeof v === "number" && Math.abs(v) > 100 ? fmt(v) : typeof v === "number" ? v.toFixed(4) : String(v)}
                </span>
              </div>
            ))}
        </div>
      </div>

      {/* Timestamp */}
      <div className="px-5 pb-3 text-xs text-gray-600">
        as of {d.as_of_utc ? new Date(d.as_of_utc).toLocaleString() : "—"}
      </div>
    </div>
  );
}

export default function ValuationDashboard({ data }: Props) {
  const tokens = Object.entries(data.tokens);

  return (
    <div className="min-h-screen bg-[#0f1117] text-white">
      <header className="border-b border-[#2d3144] px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Crypto Valuations</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              3-Year GP-Capture Monte Carlo · updated {data.lastUpdated || "—"}
            </p>
          </div>
          <Nav />
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        {tokens.length === 0 ? (
          <div className="text-center py-24 text-gray-400">
            No valuation data yet — trigger the workflow to generate results.
          </div>
        ) : (
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
            {tokens.map(([key, token]) => (
              <TokenCard key={key} tokenKey={key} token={token} />
            ))}
          </div>
        )}

        <div className="mt-8 text-xs text-gray-600 text-center">
          Models: UNI 3Y GP-Capture MC · ETHFI Bottom-up GP MC · JUP Perps+Spot MC ·
          Data: CoinGecko, DeFiLlama, Yahoo Finance
        </div>
      </main>
    </div>
  );
}
