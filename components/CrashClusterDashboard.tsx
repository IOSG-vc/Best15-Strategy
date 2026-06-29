"use client";

import dynamic from "next/dynamic";
import Nav from "./Nav";
import type { CrashClusterData, CrashClusterMetric } from "@/lib/loadCrashClusterData";

const CrashClusterBarChart    = dynamic(() => import("./CrashClusterBarChart"),    { ssr: false });
const CrashClusterLineChart   = dynamic(() => import("./CrashClusterLineChart"),   { ssr: false });
const CrashClusterExposureChart = dynamic(() => import("./CrashClusterExposureChart"), { ssr: false });
const CrashClusterBtcChart    = dynamic(() => import("./CrashClusterBtcChart"),    { ssr: false });

function pct(v: number, digits = 1) {
  return `${(v * 100).toFixed(digits)}%`;
}

function fmt(v: number, digits = 2) {
  return v.toFixed(digits);
}

function deltaColor(v: number) {
  if (v > 0.01) return "#34d399";
  if (v < -0.01) return "#f87171";
  return "#9ca3af";
}

function MetricRow({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-[#2d3144]/50 last:border-0">
      <span className="text-xs text-gray-400">{label}</span>
      <span className="text-xs font-mono font-semibold" style={color ? { color } : undefined}>
        {value}
      </span>
    </div>
  );
}

function VariantCard({
  variant,
  base,
  row,
}: {
  variant: { label: string; color: string; params?: string };
  base: CrashClusterMetric;
  row: CrashClusterMetric;
}) {
  return (
    <div
      className="bg-[#1a1d29] rounded-xl p-5 border border-[#2d3144]"
      style={{ borderTopWidth: 3, borderTopColor: variant.color }}
    >
      <div className="mb-3">
        <div className="text-sm font-semibold" style={{ color: variant.color }}>
          {variant.label}
        </div>
        {variant.params && (
          <div className="text-xs text-gray-500 mt-0.5">{variant.params}</div>
        )}
      </div>
      <MetricRow label="CAGR Sharpe" value={fmt(row.cagr_sharpe)} color={variant.color} />
      <MetricRow
        label="Δ Sharpe vs Baseline"
        value={`${row.d_cagr_sharpe >= 0 ? "+" : ""}${fmt(row.d_cagr_sharpe)}`}
        color={deltaColor(row.d_cagr_sharpe)}
      />
      <MetricRow label="CAGR" value={pct(row.cagr)} />
      <MetricRow
        label="Δ CAGR vs Baseline"
        value={`${row.d_cagr >= 0 ? "+" : ""}${pct(row.d_cagr)}`}
        color={deltaColor(row.d_cagr)}
      />
      <MetricRow label="Max Drawdown" value={pct(row.max_drawdown)} color="#f87171" />
      <MetricRow
        label="Δ Max DD vs Baseline"
        value={`${row.d_max_drawdown >= 0 ? "+" : ""}${pct(row.d_max_drawdown)}`}
        color={deltaColor(row.d_max_drawdown)}
      />
      <MetricRow label="Ann. Vol" value={pct(row.ann_vol)} />
      <MetricRow label="Avg Exposure" value={pct(row.avg_exposure)} />
      <MetricRow label="Latest Exposure" value={pct(row.latest_exposure)} />
    </div>
  );
}

function MetricsTable({
  data,
  windows,
  variants,
}: {
  data: CrashClusterData;
  windows: { key: string; label: string }[];
  variants: { key: string; label: string; color: string }[];
}) {
  const cols: { key: string; label: string; format: (v: number) => string; delta?: boolean }[] = [
    { key: "cagr_sharpe", label: "Sharpe", format: (v) => v.toFixed(3) },
    { key: "d_cagr_sharpe", label: "ΔSharpe", format: (v) => (v >= 0 ? "+" : "") + v.toFixed(3), delta: true },
    { key: "cagr", label: "CAGR", format: (v) => pct(v) },
    { key: "max_drawdown", label: "MaxDD", format: (v) => pct(v) },
    { key: "d_max_drawdown", label: "ΔMaxDD", format: (v) => (v >= 0 ? "+" : "") + pct(v), delta: true },
    { key: "avg_exposure", label: "AvgExp", format: (v) => pct(v) },
  ];

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-[#2d3144]">
            <th className="text-left text-gray-500 py-2 pr-4 font-medium">Window</th>
            <th className="text-left text-gray-500 py-2 pr-4 font-medium">Strategy</th>
            {cols.map((c) => (
              <th key={c.key} className="text-right text-gray-500 py-2 px-2 font-medium whitespace-nowrap">
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {windows.map((win) =>
            variants.map((v, vi) => {
              const row = data.metrics.find(
                (m) => m.window === win.key && m.strategy === v.key
              );
              if (!row) return null;
              return (
                <tr
                  key={`${win.key}-${v.key}`}
                  className="border-b border-[#2d3144]/30 hover:bg-[#2d3144]/20"
                >
                  <td className="py-2 pr-4 text-gray-500 whitespace-nowrap">
                    {vi === 0 ? win.label : ""}
                  </td>
                  <td className="py-2 pr-4 whitespace-nowrap font-medium" style={{ color: v.color }}>
                    {v.label}
                  </td>
                  {cols.map((c) => {
                    const val = row[c.key as keyof CrashClusterMetric] as number;
                    const color = c.delta ? deltaColor(val) : undefined;
                    return (
                      <td
                        key={c.key}
                        className="py-2 px-2 text-right font-mono"
                        style={color ? { color } : { color: "#d1d5db" }}
                      >
                        {c.format(val)}
                      </td>
                    );
                  })}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}

export default function CrashClusterDashboard({ data }: { data: CrashClusterData }) {
  const fullWindow = data.windows.find((w) => w.key === "full_2020_26")!;
  const baselineRow = data.metrics.find(
    (m) => m.window === "full_2020_26" && m.strategy === "baseline_v4_cbrtM_locked"
  )!;
  const variantRows = data.variants
    .filter((v) => !v.isBaseline)
    .map((v) => ({
      variant: v,
      row: data.metrics.find(
        (m) => m.window === "full_2020_26" && m.strategy === v.key
      )!,
    }));

  const allVariantsForTable = data.variants.map((v) => ({
    key: v.key,
    label: v.label,
    color: v.color,
  }));

  return (
    <div className="min-h-screen bg-[#0f1117] text-white">
      <header className="border-b border-[#2d3144] px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between flex-wrap gap-3">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold tracking-tight">Crash Cluster Overlay</h1>
              <span className="px-2 py-0.5 rounded text-xs font-bold uppercase tracking-wider bg-amber-500/15 text-amber-400 border border-amber-500/30">
                Experimental
              </span>
            </div>
            <p className="text-gray-400 text-sm mt-0.5">
              SH crash-gate post-hoc overlay on V4 cbrtM baseline · Candidate only · Not production-ready
            </p>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right text-sm text-gray-400">
              Data through&nbsp;
              <span className="text-white font-medium">{fullWindow.end}</span>
            </div>
            <Nav />
          </div>
        </div>
      </header>

      {/* Prominent warning banner */}
      <div className="bg-amber-500/10 border-b border-amber-500/20 px-6 py-3">
        <div className="max-w-7xl mx-auto flex items-start gap-3">
          <span className="text-amber-400 text-base mt-0.5">⚠</span>
          <div className="text-sm text-amber-300/80">
            <span className="font-semibold text-amber-400">Not production-ready.</span>{" "}
            This is a post-hoc diagnostic overlay applied to the V4 cbrtM baseline. The crash-gate signal has not been
            validated out-of-sample, is not yet integrated into the live production pipeline, and is presented here
            as a research candidate only. Results reflect locked-convention backtesting (prior-day exposure earns
            today&apos;s BTC return).
          </div>
        </div>
      </div>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8 space-y-10">

        {/* Methodology */}
        <section>
          <h2 className="text-lg font-semibold mb-4">Methodology</h2>
          <div className="bg-[#1a1d29] rounded-xl p-5 border border-[#2d3144] text-sm text-gray-300 space-y-2">
            <p>
              The SH crash-gate computes a rolling volatility z-score of daily BTC returns. When a severe negative
              shock exceeds the z-threshold, an intensity counter is incremented and decays exponentially with a
              configured half-life. The intensity is passed through a sigmoid gate function, which multiplicatively
              reduces the V4 baseline exposure toward a configurable floor during elevated crash risk.
            </p>
            <p>
              <span className="text-gray-400 font-medium">Convention:</span> crash events on day{" "}
              <code className="text-xs bg-[#2d3144] px-1 rounded">t</code> affect intensity/exposure from{" "}
              <code className="text-xs bg-[#2d3144] px-1 rounded">t+1</code> onward (fully lagged). Turnover cost of
              0.1% per unit traded is applied after final exposure is set.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-3 pt-3 border-t border-[#2d3144]">
              {data.variants.filter((v) => !v.isBaseline).map((v) => (
                <div key={v.key} className="bg-[#0f1117] rounded-lg p-3">
                  <div className="text-xs font-semibold mb-1" style={{ color: v.color }}>
                    {v.label}
                  </div>
                  <div className="text-xs text-gray-500">{v.params}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Full-period summary cards */}
        <section>
          <h2 className="text-lg font-semibold mb-1">Full Period Summary</h2>
          <p className="text-sm text-gray-500 mb-4">{fullWindow.label} vs V4 Baseline</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
            {variantRows.map(({ variant, row }) => (
              <VariantCard key={variant.key} variant={variant} base={baselineRow} row={row} />
            ))}
          </div>
        </section>

        {/* Baseline reference card */}
        <section>
          <h2 className="text-lg font-semibold mb-4">Baseline Reference (V4 cbrtM)</h2>
          <div className="bg-[#1a1d29] rounded-xl p-5 border border-[#2d3144] grid grid-cols-2 sm:grid-cols-4 gap-6">
            {[
              { label: "CAGR Sharpe", value: fmt(baselineRow.cagr_sharpe) },
              { label: "CAGR", value: pct(baselineRow.cagr) },
              { label: "Max Drawdown", value: pct(baselineRow.max_drawdown) },
              { label: "Avg Exposure", value: pct(baselineRow.avg_exposure) },
            ].map(({ label, value }) => (
              <div key={label}>
                <div className="text-xs text-gray-500 mb-1">{label}</div>
                <div className="text-lg font-mono font-bold text-gray-200">{value}</div>
              </div>
            ))}
          </div>
        </section>

        {/* Sharpe by window bar chart */}
        <section>
          <h2 className="text-lg font-semibold mb-1">CAGR Sharpe by Time Window</h2>
          <p className="text-sm text-gray-500 mb-4">All variants vs baseline across sub-periods</p>
          <div className="bg-[#1a1d29] rounded-xl p-5 border border-[#2d3144]">
            <CrashClusterBarChart data={data} />
          </div>
        </section>

        {/* Equity curve chart */}
        <section>
          <h2 className="text-lg font-semibold mb-1">Cumulative Equity Curves</h2>
          <p className="text-sm text-gray-500 mb-4">All strategies indexed to 1.0 on 2020-01-01 · Red ticks mark individual crash events</p>
          <div className="bg-[#1a1d29] rounded-xl p-5 border border-[#2d3144]">
            <CrashClusterLineChart />
          </div>
        </section>

        {/* BTC price + crash cluster chart */}
        <section>
          <h2 className="text-lg font-semibold mb-1">BTC Price with Crash Clustering</h2>
          <p className="text-sm text-gray-500 mb-4">BTC close price overlaid with individual crash event ticks and shaded cluster bands (events ≤30 days apart grouped into one cluster)</p>
          <div className="bg-[#1a1d29] rounded-xl p-5 border border-[#2d3144]">
            <CrashClusterBtcChart />
          </div>
        </section>

        {/* Exposure / gate chart */}
        <section>
          <h2 className="text-lg font-semibold mb-1">Exposure &amp; Gate Over Time</h2>
          <p className="text-sm text-gray-500 mb-4">How the crash gate compresses exposure after events · Toggle between effective exposure and raw gate multiplier</p>
          <div className="bg-[#1a1d29] rounded-xl p-5 border border-[#2d3144]">
            <CrashClusterExposureChart />
          </div>
        </section>

        {/* Full metrics table */}
        <section>
          <h2 className="text-lg font-semibold mb-4">Metrics by Window — All Variants</h2>
          <div className="bg-[#1a1d29] rounded-xl p-5 border border-[#2d3144]">
            <MetricsTable
              data={data}
              windows={data.windows}
              variants={allVariantsForTable}
            />
          </div>
        </section>

        {/* Footer notice */}
        <div className="text-center text-xs text-gray-600 pb-4">
          Crash Cluster Overlay · Research candidate · Source: crash_cluster_overlay_latest_locked_convention.py ·
          Data through {fullWindow.end}
        </div>
      </main>
    </div>
  );
}
