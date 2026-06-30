"use client";

import { useState, useEffect } from "react";

// ── Cycle constants ───────────────────────────────────────────────────────────
// Bear market: started 2025-10-06, median bear length 314 days across 6 cycles
const BEAR_START = new Date("2025-10-06T00:00:00Z");
const BEAR_MEDIAN_DAYS = 314;
const BEAR_MEAN_DAYS = 295;
const BEAR_EXPECTED_END = new Date(
  BEAR_START.getTime() + BEAR_MEDIAN_DAYS * 24 * 60 * 60 * 1000
);

// Halving: last at block 840,000 on 2024-04-20, next at block 1,050,000
// ~210,000 blocks × 10 min avg = 1,458 days → ~2028-04-19
const LAST_HALVING = new Date("2024-04-20T00:00:00Z");
const NEXT_HALVING = new Date("2028-04-19T00:00:00Z");
const HALVING_CYCLE_DAYS = Math.round(
  (NEXT_HALVING.getTime() - LAST_HALVING.getTime()) / (1000 * 60 * 60 * 24)
);
const HALVING_TOTAL_BLOCKS = 210_000;

// ── SVG arc helpers ───────────────────────────────────────────────────────────
function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function arcPath(cx: number, cy: number, r: number, progress: number): string {
  // progress 0→1: draw arc clockwise from top
  const clamped = Math.max(0.001, Math.min(0.9999, progress));
  const endAngle = clamped * 360;
  const start = polarToCartesian(cx, cy, r, 0);
  const end = polarToCartesian(cx, cy, r, endAngle);
  const large = endAngle > 180 ? 1 : 0;
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${large} 1 ${end.x} ${end.y}`;
}

// ── Time formatting ───────────────────────────────────────────────────────────
function msToComponents(ms: number) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return { days, hours, minutes, seconds };
}

function pad(n: number) {
  return n.toString().padStart(2, "0");
}

// ── Single arc clock ──────────────────────────────────────────────────────────
function ArcClock({
  label,
  sublabel,
  daysRemaining,
  hoursRemaining,
  minutesRemaining,
  secondsRemaining,
  progress,
  elapsed,
  total,
  accentColor,
  trailColor,
  glowColor,
  bottomStats,
  isExpired,
}: {
  label: string;
  sublabel: string;
  daysRemaining: number;
  hoursRemaining: number;
  minutesRemaining: number;
  secondsRemaining: number;
  progress: number;
  elapsed: number;
  total: number;
  accentColor: string;
  trailColor: string;
  glowColor: string;
  bottomStats: { label: string; value: string }[];
  isExpired: boolean;
}) {
  const cx = 100;
  const cy = 100;
  const r = 82;
  const strokeW = 8;

  return (
    <div className="flex flex-col items-center">
      {/* Arc clock SVG */}
      <div className="relative" style={{ width: 200, height: 200 }}>
        <svg viewBox="0 0 200 200" width={200} height={200}>
          {/* Glow filter */}
          <defs>
            <filter id={`glow-${label.replace(/\s/g, "")}`} x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="3" result="coloredBlur" />
              <feMerge>
                <feMergeNode in="coloredBlur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {/* Outer decorative ring */}
          <circle cx={cx} cy={cy} r={r + 6} fill="none" stroke="#1e2235" strokeWidth={1} />

          {/* Track (full circle) */}
          <circle
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke={trailColor}
            strokeWidth={strokeW}
            strokeLinecap="round"
          />

          {/* Progress arc */}
          {!isExpired && (
            <path
              d={arcPath(cx, cy, r, progress)}
              fill="none"
              stroke={accentColor}
              strokeWidth={strokeW}
              strokeLinecap="round"
              filter={`url(#glow-${label.replace(/\s/g, "")})`}
              style={{ transition: "stroke-dashoffset 0.5s ease" }}
            />
          )}

          {/* Tick marks */}
          {Array.from({ length: 12 }).map((_, i) => {
            const angle = i * 30;
            const inner = polarToCartesian(cx, cy, r - 14, angle);
            const outer = polarToCartesian(cx, cy, r - 10, angle);
            return (
              <line
                key={i}
                x1={inner.x}
                y1={inner.y}
                x2={outer.x}
                y2={outer.y}
                stroke="#2d3144"
                strokeWidth={i % 3 === 0 ? 2 : 1}
              />
            );
          })}

          {/* Center: days */}
          {isExpired ? (
            <text x={cx} y={cy - 6} textAnchor="middle" fill={accentColor} fontSize="13" fontWeight="bold">
              COMPLETE
            </text>
          ) : (
            <>
              <text x={cx} y={cy - 18} textAnchor="middle" fill="#6b7280" fontSize="9" letterSpacing="1">
                DAYS LEFT
              </text>
              <text
                x={cx}
                y={cy + 10}
                textAnchor="middle"
                fill={accentColor}
                fontSize="36"
                fontWeight="bold"
                fontFamily="monospace"
                filter={`url(#glow-${label.replace(/\s/g, "")})`}
              >
                {daysRemaining}
              </text>
              <text
                x={cx}
                y={cy + 26}
                textAnchor="middle"
                fill="#9ca3af"
                fontSize="10"
                fontFamily="monospace"
              >
                {pad(hoursRemaining)}:{pad(minutesRemaining)}:{pad(secondsRemaining)}
              </text>
            </>
          )}

          {/* Progress label at bottom of circle */}
          <text x={cx} y={cy + 54} textAnchor="middle" fill="#4b5563" fontSize="8">
            {elapsed}d elapsed / {total}d median
          </text>
        </svg>
      </div>

      {/* Label */}
      <div className="mt-1 text-center">
        <div className="text-sm font-semibold" style={{ color: accentColor }}>
          {label}
        </div>
        <div className="text-xs text-gray-500 mt-0.5">{sublabel}</div>
      </div>

      {/* Bottom stats */}
      <div className="mt-3 w-full space-y-1">
        {bottomStats.map(({ label: l, value: v }) => (
          <div key={l} className="flex justify-between text-xs">
            <span className="text-gray-500">{l}</span>
            <span className="text-gray-300 font-mono">{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function BtcCycleClock() {
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  if (!now) {
    // SSR placeholder — same layout, no live values
    return (
      <div className="bg-[#1a1d29] rounded-xl p-6 border border-[#2d3144]">
        <div className="h-48 flex items-center justify-center">
          <span className="text-gray-600 text-sm">Loading clocks…</span>
        </div>
      </div>
    );
  }

  // ── Bear market ─────────────────────────────────────────────────────────────
  const bearRemainingMs = BEAR_EXPECTED_END.getTime() - now.getTime();
  const bearIsExpired = bearRemainingMs <= 0;
  const bearElapsedDays = Math.floor(
    (now.getTime() - BEAR_START.getTime()) / (1000 * 60 * 60 * 24)
  );
  const bearProgress = Math.min(1, bearElapsedDays / BEAR_MEDIAN_DAYS);
  const bearComp = msToComponents(bearRemainingMs);

  const bearEndStr = BEAR_EXPECTED_END.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });

  // ── Halving ─────────────────────────────────────────────────────────────────
  const halvingRemainingMs = NEXT_HALVING.getTime() - now.getTime();
  const halvingIsExpired = halvingRemainingMs <= 0;
  const halvingElapsedDays = Math.floor(
    (now.getTime() - LAST_HALVING.getTime()) / (1000 * 60 * 60 * 24)
  );
  const halvingProgress = Math.min(1, halvingElapsedDays / HALVING_CYCLE_DAYS);
  const halvingComp = msToComponents(halvingRemainingMs);

  // Approximate blocks remaining: elapsed days × 144 blocks/day
  const blocksMinedEstimate = Math.round(halvingElapsedDays * 144);
  const blocksRemaining = Math.max(0, HALVING_TOTAL_BLOCKS - blocksMinedEstimate);

  const halvingDateStr = NEXT_HALVING.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });

  return (
    <div className="bg-[#1a1d29] rounded-xl p-6 border border-[#2d3144]">
      {/* Section title */}
      <div className="flex items-center gap-2 mb-6">
        <div className="w-2 h-2 rounded-full bg-[#f7931a] animate-pulse" />
        <span className="text-xs font-semibold uppercase tracking-widest text-gray-400">
          BTC Cycle Clock
        </span>
        <span className="ml-auto text-xs text-gray-600">
          {now.toUTCString().replace(" GMT", " UTC")}
        </span>
      </div>

      {/* Two clocks */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-8">
        {/* Bear market clock */}
        <ArcClock
          label="Bear Market End"
          sublabel={`Based on median bear duration · ${bearEndStr}`}
          daysRemaining={bearComp.days}
          hoursRemaining={bearComp.hours}
          minutesRemaining={bearComp.minutes}
          secondsRemaining={bearComp.seconds}
          progress={bearProgress}
          elapsed={bearElapsedDays}
          total={BEAR_MEDIAN_DAYS}
          accentColor="#e17055"
          trailColor="#2d1a18"
          glowColor="#e17055"
          isExpired={bearIsExpired}
          bottomStats={[
            { label: "Bear started", value: "Oct 6, 2025" },
            { label: "Expected end (median)", value: bearEndStr },
            { label: "Median bear length", value: `${BEAR_MEDIAN_DAYS} days` },
            { label: "Mean bear length", value: `${BEAR_MEAN_DAYS} days` },
            { label: "Elapsed", value: `${bearElapsedDays} days` },
            { label: "% through bear (median)", value: `${(bearProgress * 100).toFixed(1)}%` },
          ]}
        />

        {/* Halving clock */}
        <ArcClock
          label="Next BTC Halving"
          sublabel={`Block 1,050,000 · Est. ${halvingDateStr}`}
          daysRemaining={halvingComp.days}
          hoursRemaining={halvingComp.hours}
          minutesRemaining={halvingComp.minutes}
          secondsRemaining={halvingComp.seconds}
          progress={halvingProgress}
          elapsed={halvingElapsedDays}
          total={HALVING_CYCLE_DAYS}
          accentColor="#f7931a"
          trailColor="#1e1a0f"
          glowColor="#f7931a"
          isExpired={halvingIsExpired}
          bottomStats={[
            { label: "Last halving", value: "Apr 20, 2024 (block 840k)" },
            { label: "Next halving est.", value: halvingDateStr },
            { label: "Blocks remaining (est.)", value: `~${blocksRemaining.toLocaleString()}` },
            { label: "Reward → block", value: "3.125 → 1.5625 BTC" },
            { label: "Elapsed (this cycle)", value: `${halvingElapsedDays} days` },
            { label: "% through cycle", value: `${(halvingProgress * 100).toFixed(1)}%` },
          ]}
        />
      </div>

      {/* Footer note */}
      <div className="mt-6 pt-4 border-t border-[#2d3144]/60 text-xs text-gray-600 text-center">
        Bear end date = bear cycle start + median historical bear duration (314 days across 6 cycles since 2013).
        Halving est. based on 210,000 blocks at 10 min avg from last halving (Apr 20, 2024). Actual timing varies by block time.
      </div>
    </div>
  );
}
