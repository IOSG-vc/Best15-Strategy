"use client";

import { useState, useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
} from "recharts";
import type { ChartPoint } from "@/lib/privateFundTypes";

export interface SeriesConfig {
  key: string;
  label: string;
  color: string;
}

interface Props {
  chartSeries: ChartPoint[];
  series: SeriesConfig[];
}

interface TooltipPayload {
  dataKey: string;
  value: number;
  color: string;
}

function CustomTooltip({
  active,
  label,
  payload,
  seriesMap,
}: {
  active?: boolean;
  label?: string;
  payload?: TooltipPayload[];
  seriesMap: Map<string, SeriesConfig>;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#1a1d29] border border-[#2d3144] rounded-lg p-3 text-xs shadow-xl">
      <div className="text-gray-400 mb-2">{label}</div>
      {[...payload]
        .sort((a, b) => b.value - a.value)
        .map((p) => {
          const pct = ((p.value / 1000 - 1) * 100).toFixed(2);
          const pctNum = parseFloat(pct);
          const s = seriesMap.get(p.dataKey);
          return (
            <div key={p.dataKey} className="flex items-center gap-2 mb-1">
              <span className="w-2 h-2 rounded-full shrink-0" style={{ background: p.color }} />
              <span className="text-gray-300 w-40">{s?.label ?? p.dataKey}</span>
              <span className="font-mono ml-auto text-right" style={{ color: pctNum >= 0 ? "#4ade80" : "#f87171" }}>
                {pctNum >= 0 ? "+" : ""}
                {pct}%
              </span>
              <span className="font-mono text-gray-500 w-16 text-right">{p.value.toFixed(1)}</span>
            </div>
          );
        })}
    </div>
  );
}

export default function PrivateFundIndexChart({ chartSeries, series }: Props) {
  const [active, setActive] = useState<Set<string>>(() => new Set(series.map((s) => s.key)));

  const seriesMap = useMemo(() => new Map(series.map((s) => [s.key, s])), [series]);

  const toggle = (key: string) =>
    setActive((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });

  const filteredData = useMemo(
    () => chartSeries.filter((p) => series.some((s) => active.has(s.key) && p[s.key] !== undefined)),
    [chartSeries, series, active],
  );

  const allValues = filteredData.flatMap((p) =>
    series
      .filter((s) => active.has(s.key))
      .map((s) => p[s.key])
      .filter((v): v is number => typeof v === "number"),
  );
  const minVal = allValues.length ? Math.floor(Math.min(...allValues) * 0.998) : 950;
  const maxVal = allValues.length ? Math.ceil(Math.max(...allValues) * 1.002) : 1100;

  return (
    <div>
      {/* Legend / toggle */}
      <div className="flex flex-wrap gap-2 mb-4">
        {series.map((s) => {
          const on = active.has(s.key);
          return (
            <button
              key={s.key}
              onClick={() => toggle(s.key)}
              className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium transition-all"
              style={{
                background: on ? `${s.color}22` : "transparent",
                border: `1px solid ${on ? s.color : "#3d4166"}`,
                color: on ? s.color : "#6b7280",
              }}
            >
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: on ? s.color : "#6b7280" }} />
              {s.label}
            </button>
          );
        })}
      </div>

      <ResponsiveContainer width="100%" height={400}>
        <LineChart data={chartSeries} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" />
          <XAxis
            dataKey="date"
            tick={{ fill: "#6b7280", fontSize: 11 }}
            tickFormatter={(d: string) => d.slice(5)}
            minTickGap={30}
          />
          <YAxis
            domain={[minVal, maxVal]}
            tick={{ fill: "#6b7280", fontSize: 11 }}
            width={60}
            tickFormatter={(v: number) => v.toFixed(0)}
          />
          <Tooltip
            content={(props) => (
              <CustomTooltip
                active={props.active}
                label={props.label as string}
                payload={props.payload as TooltipPayload[]}
                seriesMap={seriesMap}
              />
            )}
          />
          <ReferenceLine y={1000} stroke="#4b5563" strokeDasharray="4 3" strokeWidth={1} />
          {series.filter((s) => active.has(s.key)).map((s) => (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              stroke={s.color}
              dot={false}
              strokeWidth={2}
              connectNulls
              activeDot={{ r: 4, strokeWidth: 0 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>

      <div className="mt-2 text-center text-xs text-gray-600">
        Base 1,000 · May 1, 2026 · Index+Signal = 50% index / 50% cash, fixed until next rebalance
      </div>
    </div>
  );
}
