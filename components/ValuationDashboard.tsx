"use client";

import { useState } from "react";
import type { ValuationsFile, TokenResult, ValuationScenario } from "@/lib/loadValuations";
import Nav from "./Nav";

interface Props {
  data: ValuationsFile;
}

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
    <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-semibold"
      style={{ color, background: bg, border: `1px solid ${color}40` }}>
      {pct(prob)} above spot
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
          <span className="inline-block w-0.5 h-3 rounded bg-emerald-300" /> P50
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-0.5 h-3 rounded bg-orange-400" /> spot
        </span>
      </div>

      {/* Percentile grid */}
      <div className="grid grid-cols-5 gap-3 mt-4">
        {(["p25", "p50", "p75", "p90"] as const).map((p) => (
          <div key={p} className="bg-[#252836] rounded-lg px-3 py-2.5 text-center">
            <div className="text-xs text-gray-500 mb-1">{p.toUpperCase()}</div>
            <div className="text-sm font-mono font-semibold text-gray-100">
              {fmtPrice(s.pv[p])}
            </div>
          </div>
        ))}
        <div className="bg-[#1a2640] rounded-lg px-3 py-2.5 text-center border border-blue-500/20">
          <div className="text-xs text-blue-400 mb-1">EV</div>
          <div className="text-sm font-mono font-semibold text-blue-300">
            {fmtPrice(s.ev)}
          </div>
        </div>
      </div>

      {/* Footer stats */}
      <div className="mt-3 flex flex-wrap gap-4 text-sm">
        <span className="text-gray-500">
          P50 upside:{" "}
          <span className={upside >= 0 ? "text-emerald-400 font-semibold" : "text-red-400 font-semibold"}>
            {upside >= 0 ? "+" : ""}{upside.toFixed(0)}%
          </span>
        </span>
        {s.prob_3x !== undefined && (
          <span className="text-gray-500">
            3× probability: <span className="text-gray-300 font-medium">{pct(s.prob_3x)}</span>
          </span>
        )}
      </div>
    </div>
  );
}

function TokenView({ token }: { token: TokenResult }) {
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

  return (
    <div className="space-y-6">
      {/* Market summary */}
      <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-6">
        <div className="flex items-start justify-between flex-wrap gap-4">
          <div>
            <div className="text-sm text-gray-500 mb-1">{d.model.type}</div>
            <div className="flex flex-wrap gap-6 text-sm text-gray-400">
              <span>DR <span className="text-white font-medium">{dr}%</span></span>
              <span>{d.model.multiple}× GP multiple</span>
              <span>{(d.model.paths / 1000).toFixed(0)}k paths</span>
              {d.data_freshness && <span>data as of <span className="text-white">{d.data_freshness}</span></span>}
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
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
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

      {d.as_of_utc && (
        <div className="text-xs text-gray-600 text-right">
          Valuation computed {new Date(d.as_of_utc).toLocaleString()}
        </div>
      )}
    </div>
  );
}

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
                    className="flex items-center gap-3 px-5 py-3 rounded-xl border transition-all text-left"
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
                      <div className="text-right ml-4">
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

            {/* Active token detail */}
            {activeToken && (
              <div>
                <div className="flex items-baseline gap-3 mb-6">
                  <h2 className="text-3xl font-bold text-white">{activeToken.symbol}</h2>
                  <span className="text-lg text-gray-400">{activeToken.name}</span>
                  {activeToken.data && (
                    <span className="text-3xl font-bold font-mono text-blue-300 ml-auto">
                      {fmtPrice(activeToken.data.market.spot)}
                    </span>
                  )}
                </div>
                <TokenView token={activeToken} />
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
