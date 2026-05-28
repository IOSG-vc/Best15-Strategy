"use client";

import type { CycleSignalData } from "@/lib/types";
import dynamic from "next/dynamic";
import Nav from "./Nav";

const ExposureHistoryChart = dynamic(() => import("./ExposureHistoryChart"), { ssr: false });
const Btc90ExposureChart = dynamic(() => import("./Btc90ExposureChart"), { ssr: false });

function dirColor(d: string) {
  if (d === "BULLISH") return "#00b894";
  if (d === "BEARISH") return "#e17055";
  return "#9ca3af";
}

function expColor(e: number) {
  if (e >= 0.65) return "#00b894";
  if (e <= 0.35) return "#e17055";
  return "#fdcb6e";
}

function deltaColor(d: number) {
  if (d > 0.005) return "#00b894";
  if (d < -0.005) return "#e17055";
  return "#9ca3af";
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

export default function CycleSignalDashboard({ data }: { data: CycleSignalData }) {
  const { state, history } = data;

  return (
    <div className="min-h-screen bg-[#0f1117] text-white">
      <header className="border-b border-[#2d3144] px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Cycle Signal</h1>
            <p className="text-gray-400 text-sm mt-0.5">
              V3 + K3 · one-step 10/90 +20% / -20% · universe 138
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
            {/* Cache / data warnings */}
            {state.cache_warnings.length > 0 && (
              <div className="bg-yellow-900/20 border border-yellow-700/40 rounded-lg px-4 py-3">
                <div className="text-yellow-400 text-xs font-semibold mb-1">
                  Data Source Warnings
                </div>
                {state.cache_warnings.map((w, i) => (
                  <div key={i} className="text-yellow-300/80 text-xs">
                    {w}
                  </div>
                ))}
              </div>
            )}

            {/* Status cards */}
            <section>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
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

                {/* V3 Exposure */}
                <div
                  className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144]"
                  style={{
                    borderLeftWidth: 3,
                    borderLeftColor: expColor(state.v3_exposure),
                  }}
                >
                  <div className="text-xs text-gray-400 mb-1">V3 Exposure</div>
                  <div
                    className="text-2xl font-bold font-mono"
                    style={{ color: expColor(state.v3_exposure) }}
                  >
                    {(state.v3_exposure * 100).toFixed(0)}%
                  </div>
                  <div className="text-xs text-gray-500 mt-1">
                    Base signal
                  </div>
                </div>

                {/* K3 Overlay Delta */}
                <div
                  className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144]"
                  style={{
                    borderLeftWidth: 3,
                    borderLeftColor: deltaColor(state.overlay_delta),
                  }}
                >
                  <div className="text-xs text-gray-400 mb-1">
                    K3 Overlay Δ
                  </div>
                  <div
                    className="text-2xl font-bold font-mono"
                    style={{ color: deltaColor(state.overlay_delta) }}
                  >
                    {state.overlay_delta >= 0 ? "+" : ""}
                    {(state.overlay_delta * 100).toFixed(0)}%
                  </div>
                  <div className="text-xs text-gray-500 mt-1 font-mono">
                    rank {state.k3_rank.toFixed(3)}
                  </div>
                </div>

                {/* K3 Score */}
                <div
                  className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144]"
                  style={{ borderLeftWidth: 3, borderLeftColor: "#6c5ce7" }}
                >
                  <div className="text-xs text-gray-400 mb-1">K3 Score</div>
                  <div className="text-2xl font-bold font-mono text-[#a78bfa]">
                    {state.k3_score.toFixed(3)}
                  </div>
                  <div className="text-xs text-gray-500 mt-1 font-mono">
                    E = {state.k3_E.toFixed(3)}
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
                    label="Strategy (V3 + K3)"
                    value={state.strategy_sharpe.toFixed(4)}
                    color="#a78bfa"
                  />
                  <MetricRow
                    label="V3 Original"
                    value={state.v3_sharpe.toFixed(4)}
                    color="#9ca3af"
                  />
                  <MetricRow
                    label="Delta vs V3"
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
                  subtitle="strategy vs V3 base"
                />
                <div className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144]">
                  <ExposureHistoryChart history={history} />
                </div>
              </section>
            )}
          </>
        )}
      </main>
    </div>
  );
}
