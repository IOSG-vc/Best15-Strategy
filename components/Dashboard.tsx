import type { PerformanceData } from "@/lib/types";
import dynamic from "next/dynamic";
import MetricsTable from "./MetricsTable";
import WeightsDisplay from "./WeightsDisplay";
import MonthlyHeatmap from "./MonthlyHeatmap";
import Nav from "./Nav";

const CumulativeChart = dynamic(() => import("./CumulativeChart"), { ssr: false });
const DrawdownChart = dynamic(() => import("./DrawdownChart"), { ssr: false });
const AssetPerformanceChart = dynamic(() => import("./AssetPerformanceChart"), { ssr: false });

export default function Dashboard({ data }: { data: PerformanceData }) {
  const hasData = Object.keys(data.strategies).length > 0;

  return (
    <div className="min-h-screen bg-[#0f1117] text-white">
      <header className="border-b border-[#2d3144] px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Best15 IOSG Ventures</h1>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right text-sm">
              {data.lastUpdated && (
                <div className="text-gray-400">
                  Updated&nbsp;
                  <span className="text-white font-medium">{data.lastUpdated}</span>
                </div>
              )}
              {data.latestRebalanceDate && (
                <div className="text-gray-400">
                  Last rebalance&nbsp;
                  <span className="text-white font-medium">{data.latestRebalanceDate}</span>
                </div>
              )}
            </div>
            <Nav />
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8 space-y-10">
        {!hasData ? (
          <div className="text-center py-24">
            <p className="text-gray-400 text-lg">No performance data yet.</p>
            <p className="text-gray-600 text-sm mt-2">
              Run the GitHub Action (or <code className="text-gray-400">python scripts/update_performance.py</code>) to generate data.
            </p>
          </div>
        ) : (
          <>
            {/* Metric summary cards */}
            <section>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                {Object.entries(data.strategies).map(([key, strat]) => {
                  const m = strat.metrics;
                  return (
                    <div
                      key={key}
                      className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144]"
                      style={{ borderLeftWidth: 3, borderLeftColor: strat.color }}
                    >
                      <div className="text-xs text-gray-400 mb-1">{strat.displayName}</div>
                      {m ? (
                        <>
                          <div
                            className="text-2xl font-bold"
                            style={{ color: m.totalReturn >= 0 ? "#4ade80" : "#f87171" }}
                          >
                            {m.totalReturn >= 0 ? "+" : ""}{m.totalReturn.toFixed(1)}%
                          </div>
                          <div className="text-xs text-gray-500 mt-0.5">Total Return</div>
                          <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
                            <div>
                              <div className="text-gray-500">Sharpe</div>
                              <div className="text-white font-medium font-mono">
                                {m.sharpe?.toFixed(2) ?? "—"}
                              </div>
                            </div>
                            <div>
                              <div className="text-gray-500">Max DD</div>
                              <div className="text-red-400 font-medium font-mono">
                                {m.maxDrawdown.toFixed(1)}%
                              </div>
                            </div>
                            <div>
                              <div className="text-gray-500">Ann. Ret</div>
                              <div
                                className="font-medium font-mono"
                                style={{ color: m.annReturn >= 0 ? "#4ade80" : "#f87171" }}
                              >
                                {m.annReturn >= 0 ? "+" : ""}{m.annReturn.toFixed(1)}%
                              </div>
                            </div>
                            <div>
                              <div className="text-gray-500">Vol</div>
                              <div className="text-gray-300 font-medium font-mono">
                                {m.annVolatility.toFixed(1)}%
                              </div>
                            </div>
                          </div>
                        </>
                      ) : (
                        <div className="text-gray-600 text-xs mt-2">Insufficient data</div>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>

            {/* Cumulative returns */}
            <section>
              <SectionHeader title="Cumulative Returns" />
              <div className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144]">
                <CumulativeChart
                  strategies={data.strategies}
                  rebalanceDates={data.rebalanceDates}
                />
              </div>
            </section>

            {/* Individual asset performance */}
            {Object.keys(data.assets ?? {}).length > 0 && (
              <section>
                <SectionHeader title="Individual Asset Performance" subtitle="% return since first rebalance" />
                <div className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144]">
                  <AssetPerformanceChart
                    assets={data.assets}
                    rebalanceDates={data.rebalanceDates}
                  />
                </div>
              </section>
            )}

            {/* Drawdowns */}
            <section>
              <SectionHeader title="Drawdowns" />
              <div className="bg-[#1a1d29] rounded-xl p-4 border border-[#2d3144]">
                <DrawdownChart strategies={data.strategies} />
              </div>
            </section>

            {/* Metrics table */}
            <section>
              <SectionHeader title="Performance Metrics" />
              <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] overflow-x-auto">
                <MetricsTable strategies={data.strategies} />
              </div>
            </section>

            {/* Monthly heatmap */}
            <section>
              <SectionHeader title="Monthly Returns" />
              <MonthlyHeatmap strategies={data.strategies} />
            </section>

            {/* Weights */}
            <section>
              <SectionHeader
                title="Latest Weights"
                subtitle={data.latestRebalanceDate}
              />
              <WeightsDisplay strategies={data.strategies} />
            </section>
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
