"use client";

import { useState, useEffect } from "react";
import {
  ComposedChart, Line, Bar, XAxis, YAxis, Tooltip,
  CartesianGrid, ResponsiveContainer, ReferenceLine,
} from "recharts";

interface DailyRow {
  date: string;
  exposure_baseline: number;
  exposure_A_locked_SH: number;
  exposure_B_floor35: number;
  exposure_C_strong: number;
  gate_A_locked_SH: number;
  gate_B_floor35: number;
  gate_C_strong: number;
  crash_event: number;
}

interface DailyData {
  daily: DailyRow[];
}

const VARIANTS = [
  { key: "A_locked_SH", label: "A — SH Gate",      color: "#a78bfa" },
  { key: "B_floor35",   label: "B — Floor 35%",    color: "#60a5fa" },
  { key: "C_strong",    label: "C — Strong Filter", color: "#34d399" },
];

const YEAR_TICKS = ["2020-01-01","2021-01-01","2022-01-01","2023-01-01","2024-01-01","2025-01-01","2026-01-01"];

type Mode = "exposure" | "gate";

function CustomTooltip({ active, label, payload, mode }: {
  active?: boolean; label?: string;
  payload?: { dataKey: string; value: number; color: string }[];
  mode: Mode;
}) {
  if (!active || !payload?.length || !label) return null;
  const prefix = mode === "gate" ? "gate_" : "exposure_";
  const lines = payload.filter(p => typeof p.value === "number" && p.dataKey.startsWith(prefix));
  return (
    <div className="bg-[#1a1d29] border border-[#2d3144] rounded-lg p-3 text-xs shadow-xl">
      <div className="text-gray-400 mb-2">{label}</div>
      {mode === "exposure" && (
        <div className="flex items-center gap-2 mb-1">
          <span className="w-2 h-2 rounded-full shrink-0 bg-gray-400" />
          <span className="text-gray-300 w-28">Baseline V4</span>
          <span className="font-mono ml-auto text-gray-400">
            {(payload.find(p => p.dataKey === "exposure_baseline")?.value ?? 0 * 100).toFixed(0)}%
          </span>
        </div>
      )}
      {lines.map(p => {
        const v = VARIANTS.find(v => `${prefix}${v.key}` === p.dataKey);
        if (!v) return null;
        return (
          <div key={p.dataKey} className="flex items-center gap-2 mb-1">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: v.color }} />
            <span className="text-gray-300 w-28">{v.label}</span>
            <span className="font-mono ml-auto" style={{ color: v.color }}>
              {(p.value * 100).toFixed(1)}%
            </span>
          </div>
        );
      })}
    </div>
  );
}

export default function CrashClusterExposureChart() {
  const [data, setData] = useState<DailyData | null>(null);
  const [visible, setVisible] = useState<Record<string, boolean>>({
    A_locked_SH: true, B_floor35: true, C_strong: true,
  });
  const [mode, setMode] = useState<Mode>("exposure");

  useEffect(() => {
    fetch("/data/crash_cluster_daily.json")
      .then(r => r.json())
      .then(setData)
      .catch(console.error);
  }, []);

  if (!data) {
    return (
      <div className="h-72 flex items-center justify-center text-gray-500 text-sm">
        Loading chart data…
      </div>
    );
  }

  const prefix = mode === "gate" ? "gate_" : "exposure_";

  const chartData = data.daily.map(row => {
    const r: Record<string, string | number | undefined> = {
      date: row.date,
      exposure_baseline: row.exposure_baseline,
      crash: row.crash_event === 1 ? 0.05 : undefined,
    };
    VARIANTS.forEach(v => {
      r[`${prefix}${v.key}`] = mode === "gate"
        ? row[`gate_${v.key}` as keyof DailyRow] as number
        : row[`exposure_${v.key}` as keyof DailyRow] as number;
    });
    return r;
  });

  return (
    <div>
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        {/* Mode toggle */}
        <div className="flex rounded-lg overflow-hidden border border-[#2d3144] text-xs mr-2">
          {(["exposure","gate"] as Mode[]).map(m => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className="px-3 py-1 transition-colors"
              style={{
                background: mode === m ? "#2d3144" : "transparent",
                color: mode === m ? "#e5e7eb" : "#6b7280",
              }}
            >
              {m === "exposure" ? "Exposure" : "Gate multiplier"}
            </button>
          ))}
        </div>
        {/* Variant toggles */}
        {VARIANTS.map(v => (
          <button
            key={v.key}
            onClick={() => setVisible(vis => ({ ...vis, [v.key]: !vis[v.key] }))}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-all"
            style={{
              background: visible[v.key] ? `${v.color}18` : "transparent",
              color: visible[v.key] ? v.color : "#4b5563",
              border: `1px solid ${visible[v.key] ? v.color : "#2d3144"}`,
            }}
          >
            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: visible[v.key] ? v.color : "#374151" }} />
            {v.label}
          </button>
        ))}
        <span className="flex items-center gap-1.5 px-2.5 py-1 text-xs text-gray-500">
          <span className="w-3 h-2 rounded-sm bg-red-500/40 shrink-0" />
          Crash event
        </span>
      </div>

      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart data={chartData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
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
          <YAxis
            yAxisId="main"
            domain={[0, 1]}
            tick={{ fill: "#6b7280", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={42}
            tickFormatter={v => `${(v * 100).toFixed(0)}%`}
          />
          <YAxis yAxisId="crash" domain={[0, 1]} hide />
          <Tooltip
            content={<CustomTooltip mode={mode} />}
            cursor={{ stroke: "#4b5563", strokeWidth: 1 }}
          />
          {/* Baseline exposure reference (only in exposure mode) */}
          {mode === "exposure" && (
            <Line
              yAxisId="main"
              dataKey="exposure_baseline"
              stroke="#9ca3af"
              strokeWidth={1}
              strokeOpacity={0.4}
              strokeDasharray="4 3"
              dot={false}
              isAnimationActive={false}
              legendType="none"
            />
          )}
          {/* Gate = 1.0 reference line in gate mode */}
          {mode === "gate" && (
            <ReferenceLine yAxisId="main" y={1} stroke="#4b5563" strokeDasharray="4 3" />
          )}
          {/* Crash rug */}
          <Bar
            yAxisId="crash"
            dataKey="crash"
            fill="#ef4444"
            fillOpacity={0.4}
            barSize={2}
            isAnimationActive={false}
            legendType="none"
          />
          {/* Variant lines */}
          {VARIANTS.map(v =>
            visible[v.key] ? (
              <Line
                key={v.key}
                yAxisId="main"
                dataKey={`${prefix}${v.key}`}
                stroke={v.color}
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
                legendType="none"
              />
            ) : null
          )}
        </ComposedChart>
      </ResponsiveContainer>

      <div className="text-xs text-gray-600 text-center mt-2">
        {mode === "exposure"
          ? "Effective exposure after gate · Dashed gray = baseline V4 exposure"
          : "Gate multiplier (1.0 = no reduction) · Drops toward floor after crash events"}
      </div>
    </div>
  );
}
