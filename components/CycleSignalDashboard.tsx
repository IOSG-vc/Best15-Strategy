"use client";

import type { CycleSignalData } from "@/lib/types";
import type { CrashClusterData } from "@/lib/loadCrashClusterData";
import dynamic from "next/dynamic";
import Link from "next/link";
import Nav from "./Nav";

const ExposureHistoryChart = dynamic(() => import("./ExposureHistoryChart"), { ssr: false });
const Btc90ExposureChart = dynamic(() => import("./Btc90ExposureChart"), { ssr: false });

function dirColor(d: string) {
  if (d === "UP") return "#00b894";
  if (d === "DOWN") return "#e17055";
  return "#9ca3af";
}

function expColor(e: number) {
  if (e >= 0.65) return "#00b894";
  if (e <= 0.35) return "#e17055";
  return "#fdcb6e";
}


function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="flex items-baseline gap-2 mb-4">
      <h2 className="text-lg font-semibold">{title}</h2>
      {subtitle && <span className="text-sm text-gray-500">{subtitle}</span>}
    </div>
  );
}

function MetricRow({
  label,
  value,
  color,
  mono = true,
}: {
  label: string;
  value: string;
  color?: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-[#2d3144]/50 last:border-0">
      <span className="text-sm text-gray-400">{label}</span>
      <span
        className={`text-sm font-semibold ${mono ? "font-mono" : ""}`}
        style={color ? { color } : undefined}
      >
        {value}
      </span>
    </div>
  );
}

export default function CycleSignalDashboard({
  data,
  crashClusterData,
}: {
  data: CycleSignalData;
  crashClusterData?: CrashClusterData;
}) {
  const { state, history } = data;

  return (
    <div className="min-h-screen bg-[#0f1117] text-white">
      <header className="border-b border-[#2d3144] px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Cycle Signal</h1>
            <p className="text-gray-400 text-sm mt-0.5">
              V4 · K10/sqrtN · one-step 10/high-dynamic +20% / -20% · universe 138
            </p>
          </div>
          <div className="flex items-center gap-4">
            {state && (
              <div className="text-right text-sm text-gray-400">
                Last run&nbsp;
                <span className="text-white font-medium">{state.date}</span>
              </div>
            )}
            <Nav />
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8 space-y-10">
        {!state ? (
          <div className="text-center py-24">
            <p className="text-gray-400 text-lg">No CycleSignal data yet.</p>
            <p className="text-gray-600 text-sm mt-2">
              Run{" "}
              <code className="text-gray-400">
                Production_v3_k3_one_step_10_90_add20_138.py
              </code>{" "}
              and save output to{" "}
              <code className="text-gray-400">data/cycle_state.json</code>.
            </p>
          </div>
        ) : (
          <>
            {/* Status cards */}
            <section>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {/* BTC Price */}
                <div
                  className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144]"
                  style={{ borderLeftWidth: 3, borderLeftColor: "#f7931a" }}
                >
                  <div className="text-xs text-gray-400 mb-1">BTC Price</div>
                  <div className="text-2xl font-bold font-mono text-[#f7931a]">
                    ${state.btc_price.toLocaleString()}
                  </div>
                </div>

                {/* Strategy Exposure */}
                <div
                  className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144]"
                  style={{
                    borderLeftWidth: 3,
                    borderLeftColor: expColor(state.exposure),
                  }}
                >
                  <div className="text-xs text-gray-400 mb-1">
                    Strategy Exposure
                  </div>
                  <div
                    className="text-2xl font-bold font-mono"
                    style={{ color: expColor(state.exposure) }}
                  >
                    {(state.exposure * 100).toFixed(0)}%
                  </div>
                  <div
                    className="text-xs mt-1 font-medium"
                    style={{ color: dirColor(state.direction) }}
                  >
                    {state.direction}
                  </div>
                </div>

                {/* Base Exposure */}
                <div
                  className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144]"
                  style={{
                    borderLeftWidth: 3,
                    borderLeftColor: expColor(state.base_exposure),
                  }}
                >
                  <div className="text-xs text-gray-400 mb-1">Base Exposure</div>
                  <div
                    className="text-2xl font-bold font-mono"
                    style={{ color: expColor(state.base_exposure) }}
                  >
                    {(state.base_exposure * 100).toFixed(0)}%
                  </div>
                  <div className="text-xs text-gray-500 mt-1">
                    K10/sqrtN
                  </div>
                </div>

              </div>
            </section>

            {/* 90-day BTC + Exposure chart */}
            {history.length > 0 && (
              <section>
                <SectionHeader
                  title="Last 90 Days"
                  subtitle="strategy exposure · BTC price"
                />
                <div className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144]">
                  <Btc90ExposureChart history={history} />
                </div>
              </section>
            )}

            {/* Backtest Metrics */}
            <section>
              <SectionHeader
                title="Backtest Metrics"
                subtitle="since 2020-01-01"
              />
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Strategy vs V3 */}
                <div className="bg-[#1a1d29] rounded-xl p-5 border border-[#2d3144]">
                  <div className="text-xs text-gray-500 font-semibold uppercase tracking-wide mb-3">
                    Sharpe Ratio
                  </div>
                  <MetricRow
                    label="Strategy (V4)"
                    value={state.strategy_sharpe.toFixed(4)}
                    color="#a78bfa"
                  />
                  <MetricRow
                    label="Base K10/sqrtN"
                    value={state.base_sharpe.toFixed(4)}
                    color="#9ca3af"
                  />
                  <MetricRow
                    label="Delta vs Base"
                    value={`${state.sharpe_delta >= 0 ? "+" : ""}${state.sharpe_delta.toFixed(4)}`}
                    color={state.sharpe_delta >= 0 ? "#00b894" : "#e17055"}
                  />
                </div>

                {/* Performance */}
                <div className="bg-[#1a1d29] rounded-xl p-5 border border-[#2d3144]">
                  <div className="text-xs text-gray-500 font-semibold uppercase tracking-wide mb-3">
                    Performance
                  </div>
                  <MetricRow
                    label="Annual Return"
                    value={`${(state.annual_return * 100).toFixed(2)}%`}
                    color="#00b894"
                  />
                  <MetricRow
                    label="Max Drawdown"
                    value={`${(state.max_drawdown * 100).toFixed(2)}%`}
                    color="#e17055"
                  />
                  <MetricRow
                    label="Avg Exposure"
                    value={`${(state.avg_exposure * 100).toFixed(1)}%`}
                  />
                </div>
              </div>
            </section>

            {/* Historical exposure */}
            {history.length > 0 && (
              <section>
                <SectionHeader
                  title="Historical Exposure"
                  subtitle="strategy vs K10/sqrtN base"
                />
                <div className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144]">
                  <ExposureHistoryChart history={history} />
                </div>
              </section>
            )}

            {/* Crash Cluster Overlay — Experimental Candidate */}
            {crashClusterData && (
              <section>
                <div className="flex items-center gap-3 mb-4">
                  <h2 className="text-lg font-semibold">Crash Cluster Overlay</h2>
                  <span className="px-2 py-0.5 rounded text-xs font-bold uppercase tracking-wider bg-amber-500/15 text-amber-400 border border-amber-500/30">
                    Experimental · Not Production-Ready
                  </span>
                </div>

                {/* Warning */}
                <div className="bg-amber-500/8 border border-amber-500/20 rounded-xl p-4 mb-4 text-xs text-amber-300/80">
                  <span className="font-semibold text-amber-400">Research candidate only.</span>{" "}
                  The SH crash-gate overlay is a post-hoc diagnostic applied to the V4 cbrtM baseline.
                  It has not been validated out-of-sample and is not integrated into the live production pipeline.
                  Data runs to{" "}
                  {crashClusterData.windows.find((w) => w.key === "full_2020_26")?.end ?? "—"}.
                </div>

                {/* Summary grid — full period */}
                {(() => {
                  const fullMetrics = crashClusterData.metrics.filter(
                    (m) => m.window === "full_2020_26"
                  );
                  return (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
                      {crashClusterData.variants.map((v) => {
                        const row = fullMetrics.find((m) => m.strategy === v.key);
                        if (!row) return null;
                        return (
                          <div
                            key={v.key}
                            className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144]"
                            style={{ borderLeftWidth: 3, borderLeftColor: v.color }}
                          >
                            <div
                              className="text-xs font-semibold mb-2"
                              style={{ color: v.color }}
                            >
                              {v.label}
                              {v.isBaseline && (
                                <span className="ml-1 text-gray-500 font-normal">(baseline)</span>
                              )}
                            </div>
                            <div className="text-xl font-bold font-mono text-white mb-0.5">
                              {row.cagr_sharpe.toFixed(3)}
                            </div>
                            <div className="text-xs text-gray-500">CAGR Sharpe</div>
                            <div className="mt-2 flex gap-3 text-xs">
                              <span className="text-gray-400">
                                DD{" "}
                                <span className="text-red-400 font-mono">
                                  {(row.max_drawdown * 100).toFixed(0)}%
                                </span>
                              </span>
                              <span className="text-gray-400">
                                Exp{" "}
                                <span className="font-mono text-gray-300">
                                  {(row.avg_exposure * 100).toFixed(0)}%
                                </span>
                              </span>
                            </div>
                            {!v.isBaseline && (
                              <div className="mt-1.5 text-xs font-mono"
                                style={{ color: row.d_cagr_sharpe >= 0 ? "#34d399" : "#f87171" }}>
                                {row.d_cagr_sharpe >= 0 ? "+" : ""}
                                {row.d_cagr_sharpe.toFixed(3)} Sharpe vs base
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  );
                })()}

                <div className="text-center">
                  <Link
                    href="/crash-cluster"
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors"
                    style={{
                      background: "#a78bfa22",
                      color: "#a78bfa",
                      border: "1px solid #a78bfa44",
                    }}
                  >
                    View Full Crash Cluster Analysis
                    <span>→</span>
                  </Link>
                </div>
              </section>
            )}
          </>
        )}
      </main>
    </div>
  );
}
