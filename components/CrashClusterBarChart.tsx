"use client";

import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Legend,
  CartesianGrid, ResponsiveContainer, ReferenceLine,
} from "recharts";
import type { CrashClusterData } from "@/lib/loadCrashClusterData";

function CustomTooltip({ active, label, payload }: {
  active?: boolean; label?: string; payload?: { name: string; value: number; color: string }[];
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#1a1d29] border border-[#2d3144] rounded-lg p-3 text-xs shadow-xl">
      <div className="text-gray-400 mb-2">{label}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2 mb-1">
          <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: p.color }} />
          <span className="text-gray-300 w-32">{p.name}</span>
          <span className="font-mono ml-auto">{p.value.toFixed(3)}</span>
        </div>
      ))}
    </div>
  );
}

export default function CrashClusterBarChart({ data }: { data: CrashClusterData }) {
  const chartData = data.windows.map((win) => {
    const entry: Record<string, string | number> = { window: win.label };
    data.variants.forEach((v) => {
      const row = data.metrics.find((m) => m.window === win.key && m.strategy === v.key);
      if (row) entry[v.label] = row.cagr_sharpe;
    });
    return entry;
  });

  return (
    <div>
      <ResponsiveContainer width="100%" height={320}>
        <BarChart data={chartData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }} barCategoryGap="20%">
          <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" vertical={false} />
          <XAxis
            dataKey="window"
            tick={{ fill: "#6b7280", fontSize: 11 }}
            axisLine={{ stroke: "#2d3144" }}
            tickLine={false}
          />
          <YAxis
            domain={[0, "auto"]}
            tick={{ fill: "#6b7280", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={40}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: "#ffffff08" }} />
          <Legend
            wrapperStyle={{ fontSize: 11, color: "#9ca3af", paddingTop: 12 }}
          />
          <ReferenceLine y={1.0} stroke="#4b5563" strokeDasharray="4 4" />
          {data.variants.map((v) => (
            <Bar
              key={v.key}
              dataKey={v.label}
              fill={v.color}
              fillOpacity={v.isBaseline ? 0.5 : 0.85}
              radius={[3, 3, 0, 0]}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
      <div className="text-xs text-gray-600 text-center mt-2">
        Dashed line at Sharpe = 1.0 for reference
      </div>
    </div>
  );
}
