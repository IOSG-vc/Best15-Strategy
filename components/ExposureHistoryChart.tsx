"use client";

import { useState, useMemo } from "react";
import {
  ComposedChart, Line, Area, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, ReferenceLine,
} from "recharts";
import type { CycleHistoryPoint } from "@/lib/types";

const RANGES = ["3M", "6M", "1Y", "ALL"] as const;
type Range = typeof RANGES[number];
const RANGE_DAYS: Record<Range, number> = { "3M": 90, "6M": 180, "1Y": 365, ALL: Infinity };

function CustomTooltip({ active, label, payload }: {
  active?: boolean; label?: string; payload?: { name: string; value: number; color: string }[];
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#1a1d29] border border-[#2d3144] rounded-lg p-3 text-xs shadow-xl">
      <div className="text-gray-400 mb-2">{label}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2 mb-1">
          <span className="w-2 h-2 rounded-full shrink-0" style={{ background: p.color }} />
          <span className="text-gray-300 w-28">{p.name}</span>
          <span className="font-mono ml-auto">
            {p.value != null ? `${(p.value * 100).toFixed(0)}%` : "—"}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function ExposureHistoryChart({ history }: { history: CycleHistoryPoint[] }) {
  const [range, setRange] = useState<Range>("1Y");

  const data = useMemo(() => {
    const days = RANGE_DAYS[range];
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - days);
    return (range === "ALL" ? history : history.filter((p) => new Date(p.date) >= cutoff))
      .map((p) => ({
        ...p,
        Strategy: p.exposure,
        Base: p.base_exposure ?? null,
      }));
  }, [history, range]);

  return (
    <div>
      <div className="flex gap-2 mb-4">
        {RANGES.map((r) => {
          const active = range === r;
          return (
            <button
              key={r}
              onClick={() => setRange(r)}
              className="px-3 py-1 rounded text-xs font-medium transition-all"
              style={{
                background: active ? "#6c5ce722" : "transparent",
                border: `1px solid ${active ? "#6c5ce7" : "#3d4166"}`,
                color: active ? "#a78bfa" : "#6b7280",
              }}
            >
              {r}
            </button>
          );
        })}
      </div>

      {data.length === 0 ? (
        <div className="h-64 flex items-center justify-center text-gray-500 text-sm">No history data</div>
      ) : (
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={data} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" />
            <XAxis
              dataKey="date"
              tick={{ fill: "#6b7280", fontSize: 11 }}
              tickFormatter={(d: string) => d.slice(5)}
              minTickGap={40}
            />
            <YAxis
              domain={[0, 1]}
              tick={{ fill: "#6b7280", fontSize: 11 }}
              tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
              width={42}
            />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine y={0.5} stroke="#4b5563" strokeDasharray="4 4" />
            <Area
              type="stepAfter" dataKey="Strategy"
              stroke="#6c5ce7" fill="#6c5ce7" fillOpacity={0.12}
              dot={false} strokeWidth={2} connectNulls
            />
            <Line
              type="stepAfter" dataKey="Base"
              stroke="#f59e0b" dot={false} strokeWidth={1.5}
              connectNulls activeDot={{ r: 3, strokeWidth: 0 }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      )}

      <div className="flex gap-5 mt-3 text-xs text-gray-500">
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-0.5 bg-[#6c5ce7] inline-block rounded" /> Strategy exposure (V4)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-0.5 bg-[#f59e0b] inline-block rounded" /> Base exposure (K10/sqrtN)
        </span>
      </div>
    </div>
  );
}
