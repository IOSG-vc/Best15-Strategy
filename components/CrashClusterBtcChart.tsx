"use client";

import { useState, useEffect } from "react";
import {
  ComposedChart, Line, Bar, XAxis, YAxis, Tooltip,
  CartesianGrid, ResponsiveContainer, ReferenceArea,
} from "recharts";

interface DailyRow {
  date: string;
  btc_close: number;
  crash_event: number;
}

interface DailyData {
  crashEvents: string[];
  daily: DailyRow[];
}

const YEAR_TICKS = ["2020-01-01","2021-01-01","2022-01-01","2023-01-01","2024-01-01","2025-01-01","2026-01-01"];

// Cluster consecutive crash events into groups separated by >30 days
function buildClusters(events: string[]): { start: string; end: string; count: number }[] {
  if (!events.length) return [];
  const sorted = [...events].sort();
  const clusters: { start: string; end: string; count: number }[] = [];
  let clusterStart = sorted[0];
  let clusterEnd   = sorted[0];
  let count = 1;

  for (let i = 1; i < sorted.length; i++) {
    const prev = new Date(sorted[i - 1]).getTime();
    const curr = new Date(sorted[i]).getTime();
    const diffDays = (curr - prev) / 86_400_000;
    if (diffDays <= 30) {
      clusterEnd = sorted[i];
      count++;
    } else {
      clusters.push({ start: clusterStart, end: clusterEnd, count });
      clusterStart = sorted[i];
      clusterEnd   = sorted[i];
      count = 1;
    }
  }
  clusters.push({ start: clusterStart, end: clusterEnd, count });
  return clusters;
}

function CustomTooltip({ active, label, payload }: {
  active?: boolean; label?: string; payload?: { dataKey: string; value: number }[];
}) {
  if (!active || !payload?.length || !label) return null;
  const btcEntry = payload.find(p => p.dataKey === "btc_close");
  const crashEntry = payload.find(p => p.dataKey === "crash_bar");
  return (
    <div className="bg-[#1a1d29] border border-[#2d3144] rounded-lg p-3 text-xs shadow-xl">
      <div className="text-gray-400 mb-2">{label}</div>
      {btcEntry && (
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full shrink-0 bg-amber-400" />
          <span className="text-gray-300 w-16">BTC</span>
          <span className="font-mono ml-auto text-amber-400">
            ${btcEntry.value.toLocaleString("en-US", { maximumFractionDigits: 0 })}
          </span>
        </div>
      )}
      {crashEntry && crashEntry.value > 0 && (
        <div className="flex items-center gap-2 mt-1">
          <span className="w-2 h-2 rounded-sm shrink-0 bg-red-500/60" />
          <span className="text-red-400">Crash event (z≤−1.5σ)</span>
        </div>
      )}
    </div>
  );
}

export default function CrashClusterBtcChart() {
  const [data, setData]         = useState<DailyData | null>(null);
  const [showClusters, setShowClusters] = useState(true);
  const [showEvents, setShowEvents]     = useState(true);

  useEffect(() => {
    fetch("/data/crash_cluster_daily.json")
      .then(r => r.json())
      .then(setData)
      .catch(console.error);
  }, []);

  if (!data) {
    return (
      <div className="h-80 flex items-center justify-center text-gray-500 text-sm">
        Loading chart data…
      </div>
    );
  }

  const clusters = buildClusters(data.crashEvents);
  const btcMax   = Math.max(...data.daily.map(r => r.btc_close));

  // Crash bar height = 10% of btc axis range for visibility
  const crashBarHeight = btcMax * 0.10;

  const chartData = data.daily.map(row => ({
    date:      row.date,
    btc_close: row.btc_close,
    crash_bar: row.crash_event === 1 ? crashBarHeight : undefined,
  }));

  return (
    <div>
      {/* Legend + toggles */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
          style={{ background: "#f59e0b18", color: "#f59e0b", border: "1px solid #f59e0b" }}>
          <span className="w-2 h-2 rounded-full shrink-0 bg-amber-400" />
          BTC price
        </div>
        <button
          onClick={() => setShowEvents(v => !v)}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-all"
          style={{
            background: showEvents ? "#ef444418" : "transparent",
            color: showEvents ? "#f87171" : "#4b5563",
            border: `1px solid ${showEvents ? "#ef4444" : "#2d3144"}`,
          }}
        >
          <span className="w-3 h-1.5 rounded-sm shrink-0" style={{ background: showEvents ? "#ef4444" : "#374151" }} />
          Crash events
        </button>
        <button
          onClick={() => setShowClusters(v => !v)}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-all"
          style={{
            background: showClusters ? "#ef444408" : "transparent",
            color: showClusters ? "#fca5a5" : "#4b5563",
            border: `1px solid ${showClusters ? "#ef444440" : "#2d3144"}`,
          }}
        >
          <span className="w-3 h-3 rounded-sm shrink-0" style={{ background: showClusters ? "#ef444430" : "#374151" }} />
          Cluster bands
        </button>
        <span className="text-xs text-gray-500 ml-auto">
          {data.crashEvents.length} crash events · {clusters.length} clusters
        </span>
      </div>

      <div className="relative">
        {/* Cluster bands rendered as SVG overlays via absolute positioned divs */}
        {/* We use ReferenceLine area workaround: render as a ComposedChart with reference areas */}
        <ResponsiveContainer width="100%" height={380}>
          <ComposedChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" vertical={false} />
            <XAxis
              dataKey="date"
              type="category"
              ticks={YEAR_TICKS}
              tickFormatter={v => v.slice(0, 4)}
              tick={{ fill: "#6b7280", fontSize: 11 }}
              axisLine={{ stroke: "#2d3144" }}
              tickLine={false}
            />
            {/* BTC price axis */}
            <YAxis
              yAxisId="btc"
              orientation="left"
              domain={[0, btcMax * 1.12]}
              tick={{ fill: "#6b7280", fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={52}
              tickFormatter={v => v >= 1000 ? `$${(v/1000).toFixed(0)}k` : `$${v}`}
            />
            {/* Hidden axis for crash bars */}
            <YAxis yAxisId="crash" domain={[0, btcMax * 1.12]} hide />

            <Tooltip
              content={<CustomTooltip />}
              cursor={{ stroke: "#4b5563", strokeWidth: 1 }}
            />

            {/* Crash event rug bars */}
            {showEvents && (
              <Bar
                yAxisId="crash"
                dataKey="crash_bar"
                fill="#ef4444"
                fillOpacity={0.45}
                barSize={2}
                isAnimationActive={false}
                legendType="none"
              />
            )}

            {/* Cluster bands as filled reference areas */}
            {showClusters && clusters.map((cl, i) => (
              <ReferenceArea
                key={`cl-${i}`}
                yAxisId="btc"
                x1={cl.start}
                x2={cl.end === cl.start ? cl.start : cl.end}
                fill="#ef4444"
                fillOpacity={0.12}
                stroke="#ef4444"
                strokeOpacity={0.25}
                strokeWidth={1}
                label={cl.count >= 6 ? {
                  value: `${cl.count}d`,
                  position: "insideTop",
                  fill: "#ef444470",
                  fontSize: 9,
                } : undefined}
              />
            ))}

            {/* BTC price line */}
            <Line
              yAxisId="btc"
              dataKey="btc_close"
              stroke="#f59e0b"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
              legendType="none"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Cluster summary strip */}
      <div className="mt-4 flex flex-wrap gap-2">
        {clusters.map((cl, i) => (
          <div
            key={i}
            className="text-xs bg-red-500/10 border border-red-500/20 rounded px-2 py-1 text-red-400 font-mono"
          >
            {cl.start === cl.end ? cl.start : `${cl.start} → ${cl.end}`}
            <span className="ml-1 text-red-500/60">({cl.count}d)</span>
          </div>
        ))}
      </div>

      <div className="text-xs text-gray-600 text-center mt-3">
        BTC price (log feel) with crash event ticks (z≤−1.5σ) and cluster bands (≤30 day gap) · {data.crashEvents.length} events grouped into {clusters.length} clusters
      </div>
    </div>
  );
}
