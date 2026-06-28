"use client";

import { useState, useEffect } from "react";
import {
  ComposedChart, Line, Bar, XAxis, YAxis, Tooltip,
  CartesianGrid, ResponsiveContainer,
} from "recharts";

interface DailyRow {
  date: string;
  equity_baseline: number;
  equity_A_locked_SH: number;
  equity_B_floor35: number;
  equity_C_strong: number;
  crash_event: number;
}

interface DailyData {
  crashEvents: string[];
  daily: DailyRow[];
}

const STRATEGIES = [
  { key: "baseline",    label: "Baseline V4",      color: "#9ca3af", width: 1,   opacity: 0.55 },
  { key: "A_locked_SH", label: "A — SH Gate",     color: "#a78bfa", width: 1.5, opacity: 1 },
  { key: "B_floor35",   label: "B — Floor 35%",   color: "#60a5fa", width: 1.5, opacity: 1 },
  { key: "C_strong",    label: "C — Strong Filter",color: "#34d399", width: 1.5, opacity: 1 },
];

const YEAR_TICKS = ["2020-01-01","2021-01-01","2022-01-01","2023-01-01","2024-01-01","2025-01-01","2026-01-01"];

function CustomTooltip({ active, label, payload }: {
  active?: boolean; label?: string; payload?: { dataKey: string; value: number; color: string }[];
}) {
  if (!active || !payload?.length || !label) return null;
  const lines = payload.filter(p => p.dataKey.startsWith("equity_"));
  return (
    <div className="bg-[#1a1d29] border border-[#2d3144] rounded-lg p-3 text-xs shadow-xl">
      <div className="text-gray-400 mb-2">{label}</div>
      {lines.map(p => {
        const s = STRATEGIES.find(s => `equity_${s.key}` === p.dataKey);
        if (!s) return null;
        return (
          <div key={p.dataKey} className="flex items-center gap-2 mb-1">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: s.color }} />
            <span className="text-gray-300 w-28">{s.label}</span>
            <span className="font-mono ml-auto" style={{ color: s.color }}>{p.value.toFixed(3)}x</span>
          </div>
        );
      })}
    </div>
  );
}

export default function CrashClusterLineChart() {
  const [data, setData] = useState<DailyData | null>(null);
  const [visible, setVisible] = useState<Record<string, boolean>>({
    baseline: true, A_locked_SH: true, B_floor35: true, C_strong: true,
  });

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

  const chartData = data.daily.map(row => ({
    date: row.date,
    equity_baseline:    row.equity_baseline,
    equity_A_locked_SH: row.equity_A_locked_SH,
    equity_B_floor35:   row.equity_B_floor35,
    equity_C_strong:    row.equity_C_strong,
    crash: row.crash_event === 1 ? 0.06 : undefined,
  }));

  return (
    <div>
      {/* Legend + toggles */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        {STRATEGIES.map(s => (
          <button
            key={s.key}
            onClick={() => setVisible(v => ({ ...v, [s.key]: !v[s.key] }))}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-all"
            style={{
              background: visible[s.key] ? `${s.color}18` : "transparent",
              color: visible[s.key] ? s.color : "#4b5563",
              border: `1px solid ${visible[s.key] ? s.color : "#2d3144"}`,
            }}
          >
            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: visible[s.key] ? s.color : "#374151" }} />
            {s.label}
          </button>
        ))}
        <span className="flex items-center gap-1.5 px-2.5 py-1 text-xs text-gray-500">
          <span className="w-3 h-2 rounded-sm bg-red-500/40 shrink-0" />
          Crash event (z≤−1.5σ)
        </span>
      </div>

      <ResponsiveContainer width="100%" height={380}>
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
          {/* Left axis: equity */}
          <YAxis
            yAxisId="eq"
            domain={[0, "auto"]}
            tick={{ fill: "#6b7280", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={42}
            tickFormatter={v => `${v.toFixed(0)}x`}
          />
          {/* Right hidden axis: crash event bars occupy bottom 6% */}
          <YAxis yAxisId="crash" domain={[0, 1]} hide />
          <Tooltip
            content={<CustomTooltip />}
            cursor={{ stroke: "#4b5563", strokeWidth: 1 }}
          />
          {/* Crash event rug */}
          <Bar
            yAxisId="crash"
            dataKey="crash"
            fill="#ef4444"
            fillOpacity={0.4}
            barSize={2}
            isAnimationActive={false}
            legendType="none"
          />
          {/* Equity lines */}
          {STRATEGIES.map(s =>
            visible[s.key] ? (
              <Line
                key={s.key}
                yAxisId="eq"
                dataKey={`equity_${s.key}`}
                stroke={s.color}
                strokeWidth={s.width}
                strokeOpacity={s.opacity}
                dot={false}
                isAnimationActive={false}
                legendType="none"
              />
            ) : null
          )}
        </ComposedChart>
      </ResponsiveContainer>

      <div className="text-xs text-gray-600 text-center mt-2">
        Equity indexed to 1.0 on 2020-01-01 · Red ticks = crash event days (z≤−1.5σ) · Turnover cost 0.1% applied
      </div>
    </div>
  );
}
