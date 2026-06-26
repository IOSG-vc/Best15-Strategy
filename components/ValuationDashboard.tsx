"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  BarChart, Bar, Cell, LabelList,
} from "recharts";
import type { ValuationsFile, TokenResult, ValuationScenario, McapPoint, MsPoint, ValuationData, Y3Volume, HistCharts, BacktestRow, SecondaryChart } from "@/lib/loadValuations";
import { LineChart, Line, ReferenceLine, ComposedChart } from "recharts";
import Nav from "./Nav";

interface Props {
  data: ValuationsFile;
}

// ── Term definitions ─────────────────────────────────────────────────────────

const TERMS: Record<string, { title: string; body: string }> = {
  p25: {
    title: "P25 — 25th Percentile",
    body: "25% of Monte Carlo paths produce a fair value at or below this price. A conservative estimate — only a bad-luck quarter of simulated futures lands here.",
  },
  p50: {
    title: "P50 — Median",
    body: "The midpoint of simulated fair values. Half of all paths land above this, half below. The model's central estimate with no optimism bias.",
  },
  p75: {
    title: "P75 — 75th Percentile",
    body: "75% of paths land at or below this. Represents a good-but-not-exceptional outcome — the upper edge of the core range.",
  },
  p90: {
    title: "P90 — 90th Percentile",
    body: "Only 10% of simulated paths exceed this value. Reflects a strong bull outcome where growth significantly outperforms the historical base rate.",
  },
  ev: {
    title: "EV — Expected Value (Mean)",
    body: "The probability-weighted average across all 50–100k Monte Carlo paths. Pulled above P50 by the fat right tail of bull scenarios. Not a price target — the mathematical average of all possible futures.",
  },
  dr: {
    title: "Discount Rate",
    body: "The annualised rate used to bring Year-3 GP back to present value. Liquid-token CAPM: risk-free rate + equity risk premium × (token vol ÷ S&P 500 vol). Higher volatility = higher DR = lower present value.",
  },
  multiple: {
    title: "GP Multiple",
    body: "Year-3 trailing-12M gross profit is multiplied by this factor to get an enterprise value. Mid-cycle assumption for a high-growth DeFi protocol. 20x trough / 15x normal / 10x peak volume regime.",
  },
  paths: {
    title: "Monte Carlo Paths",
    body: "The number of simulated futures run. Each path draws random monthly growth shocks from the historical distribution of the protocol's volume/revenue. 50k–100k paths converge well for these distributions.",
  },
  prob_above_spot: {
    title: "Probability Above Spot",
    body: "Fraction of Monte Carlo paths where the model's 3-year discounted fair value exceeds the current spot price. Above 50% means the model's central case implies the token is undervalued.",
  },
  prob_3x: {
    title: "3× Probability",
    body: "Fraction of paths where the model fair value is at least 3× today's spot. A rough screen for asymmetric upside potential.",
  },
  upside: {
    title: "P50 Upside",
    body: "How far the median fair value (P50) is above or below the current spot price. Negative means the model's central estimate implies the token is fairly valued or stretched.",
  },
  gp_capture: {
    title: "GP-Capture Framework",
    body: "Rather than discounting all future cash flows to infinity, this model captures the gross profit the protocol is expected to generate in Year 3 and applies a multiple. Simpler, more robust to uncertainty, and standard in DeFi research.",
  },
  ms90: {
    title: "MS90 — 90-Day Market Share",
    body: "Hyperliquid's 90-day derivatives volume as a fraction of Binance Futures volume (scaled via Blockworks annual totals). Used as the base market share for the Monte Carlo paths.",
  },
  ms30: {
    title: "MS30 — 30-Day Market Share",
    body: "Hyperliquid's 30-day derivatives volume share vs Binance. Higher than MS90 indicates recent momentum; MS30/MS90 trend > 1× is used as the share-growth amplifier.",
  },
};

// ── Per-token methodology ────────────────────────────────────────────────────

const METHODOLOGY: Record<string, { sections: { heading: string; text: string }[] }> = {
  hype: {
    sections: [
      {
        heading: "Core revenue model",
        text: "Perp treasury revenue = Binance Futures monthly volume × HL market share × 0.026% clean revenue take-rate. The ~0.034% total fee rate is tracked as activity context only because DefiLlama dailyFees can include builder-code fees that do not accrue to the treasury. USDC yield = USDC TVL × net yield × 90% capture.",
      },
      {
        heading: "Market share momentum",
        text: "MS30/MS90 is treated as the current 6M share-growth amplifier. Monthly velocity linearly decays to 1.0× over 12 months; the gained share is retained. Absolute cap: 35% of Binance.",
      },
      {
        heading: "Supply / emission scenarios",
        text: "Four scenarios by supply assumption: Bear uses worst-case non-circulating/team overhang release (full over 3Y); Base uses DB-observed ~1M HYPE/month; Bull uses the same with 10% overhang; Sensitivity assumes zero new emissions. Buybacks offset emissions at current GP/price.",
      },
      {
        heading: "Multiple regime",
        text: "20× trough (bottom 20% of Y3 volume paths) / 15× normal / 10× peak (top 20%). Multiple is applied to Y3 trailing-12M GP and discounted at 25% selected rate.",
      },
      {
        heading: "Data sources",
        text: "Binance volume: BTCUSDT Binance Futures ZIP data scaled by Blockworks annual totals. Market share: DefiLlama MCP derivatives volume (fallback: clean treasury revenue ÷ 0.026% take-rate). USDC TVL: DefiLlama stablecoins API. Yield: FRED SOFR minus 50bp haircut.",
      },
    ],
  },
  lighter: {
    sections: [
      {
        heading: "Core revenue model",
        text: "Perps revenue = Binance Futures monthly volume proxy × Lighter/Binance market share × observed net revenue take-rate. The model uses the same HYPE-style MS90 seed and velocity-decay framework, with holder revenue used for token buybacks.",
      },
      {
        heading: "Market share momentum",
        text: "MS30/MS90/180 are measured against the Binance Futures proxy. MS90 is the valuation seed; MS30/MS180 is the current momentum read, floored at 1.0× in the model so short-term share deceleration does not mechanically punish the long-run terminal share below the MS90 base.",
      },
      {
        heading: "Supply / unlock path",
        text: "Fixed token supply increase is modeled per path from the post-cliff unlock schedule. Buybacks offset supply using holder revenue; Year-3 PV is calculated on the resulting supply after cumulative buyback tokens.",
      },
      {
        heading: "Stablecoin yield sensitivity",
        text: "A separate sensitivity adds a HYPE-style TVL yield line using collateral TVL proxy × SOFR-net yield × 90% capture. This is not treated as current Lighter revenue; it is shown as optional upside if the business adds a treasury/yield line.",
      },
      {
        heading: "Multiple regime",
        text: "20× trough / 15× normal / 10× peak regime, applied to Year-3 trailing revenue and discounted at 25%. The +10% optionality case sits on top of the stable-yield case.",
      },
    ],
  },
  cards: {
    sections: [
      {
        heading: "Core revenue model",
        text: "GP = platform gross profit from Gacha pack sales + marketplace trading fees. Gacha packs ($50 Elite / $250 Legendary / $1,000 Pokémon) are 98% of revenue. The 2% marketplace fee (1% platform + 1% royalty) covers secondary trades of tokenized cards. Model: Y3_price = Y3_GP × 15 × 1.10 / Y3_supply. GP is assumed to flow into CARDS buybacks — no explicit buyback % is publicly committed.",
      },
      {
        heading: "Margin structure",
        text: "Gross margin is thin by design: COGS is physical card inventory cost. Q1 2026 margin was 5.9% ($8.6M GP on $146.9M GMV), compressed from 10-12% in Q3 2025. Bull scenario assumes margin partially recovers to ~8% with operating leverage or better card sourcing.",
      },
      {
        heading: "Supply inflation risk",
        text: "Only 12.9% of the 2B max supply (257M CARDS) is circulating. Foundation (36.76%), community (20%), team (19.5%), investors (11.87%), and advisors (4.37%) tokens unlock on vesting schedules. By Y3, an estimated 800M–1.5B tokens could be circulating. Even with strong GP growth, per-token value is compressed by supply expansion — this is the dominant model headwind.",
      },
      {
        heading: "Revenue concentration risk",
        text: "Gacha drives 98% of revenue and is cyclical — tied to Pokémon/TCG hype cycles. Q1 2026 peak weekly Gacha spend was $21.5M; typical weekly spend is $1.5–2.3M. Scenarios model $20M–$65M sustained annual GP to capture this volatility.",
      },
      {
        heading: "Model limitations",
        text: "Scenarios are manually constructed with no Monte Carlo simulation. Distributions approximate log-normal σ=1.0. No formal buyback % is publicly disclosed; full GP→buyback assumption may overstate token demand. Y3 supply estimates are based on tokenomics allocation; specific vesting schedules are not publicly documented.",
      },
    ],
  },
  bp: {
    sections: [
      {
        heading: "Core revenue model",
        text: "Revenue = Spot (Binance spot denominator × BP market share × 9.5 bps) + Perps (Binance futures denominator × BP market share × 1.5 bps) + Securities (manual bear/base/bull). Company valuation = total Y3 revenue × P/S multiple. Equity pool = company valuation × 20% equity stake. PV per BP = equity pool / Y3 staking supply / (1.25)³. P/S benchmarked vs Coinbase (~9×) and Kraken (~7×).",
      },
      {
        heading: "Supply / dilution path",
        text: "Phase 1 (250M, TGE): immediately eligible to stake — current effective supply. Phase 2 (375M): unlocks on business milestones (new regulatory licenses, product launches, geographic expansion); scenarios tie Phase-2 unlock to scenario success: bear=0 unlocks, base=~1/3, bull=majority. Phase 3 (375M): post-IPO treasury, excluded from staking model. Higher business success → more Phase-2 supply but also more revenue, so per-BP equity still improves in good scenarios.",
      },
      {
        heading: "Revenue drivers",
        text: "Perps: Binance Futures annual volume (Blockworks $25.2T/yr 2025) × current BP perps market share × scenario share multiplier × 1.5 bps clean take-rate. Spot: Binance Spot annual volume (Blockworks $7.3T/yr 2025) × current BP spot market share × scenario share multiplier × 9.5 bps blended taker take-rate. Denominator growth 1.0×–1.6× across scenarios. Perps take-rate derived live from DefiLlama fee / volume ratio when available.",
      },
      {
        heading: "Securities (tokenized equities)",
        text: "Manual scenarios: Bear $5M, Base $40M, Bull $120M Y3 annual revenue. Backpack holds regulatory licenses to offer tokenized equities in select jurisdictions (EU/MiCA). No reliable volume series exists to drive a Monte Carlo simulation; scenarios assume moderate adoption in base (comparable to early Robinhood crypto revenue run-rate) and material adoption in bull. Data reference: Blockworks tokenized securities market sizing.",
      },
      {
        heading: "Key risks",
        text: "IPO contingency: if Backpack does not IPO, equity conversion does not occur and BP loses its primary value driver. Phase 2 dilution: milestone unlocks compress per-BP equity value. Legal/regulatory risk: equity-for-token swaps may face regulatory challenges. Securities revenue is speculative — no reported figures. No buyback or revenue-share mechanism currently exists.",
      },
      {
        heading: "Model limitations",
        text: "No Monte Carlo simulation — distributions approximate log-normal σ=1.0. Spot volume estimated via CoinGecko exchange endpoint; Backpack does not disclose spot volume directly. Market share multipliers are scenario assumptions, not derived from a velocity MC path. IPO probability treated as given. P/S range 4–10× captures most plausible outcomes for a regulated mid-tier crypto exchange.",
      },
    ],
  },
  coinbase: {
    sections: [
      {
        heading: "Core revenue model",
        text: "Four product lines: (1) Spot — Binance spot denominator × Coinbase spot MS × 32 bps blended take-rate (calibrated Q1-2026: ~$517M consumer spot / $167.7B vol ≈ 31bps). (2) Deribit (Coinbase-owned) — Binance Futures denominator × Deribit MS × 3.88 bps take-rate (calibrated Q1-2026: ~$136M inst rev / $350.8B Deribit vol). (3) CDE retail — Binance Futures denominator × CDE MS × 119 bps (calibrated Q1-2026: $200M ann / $16.8B ann vol). (4) USDC — USDC circulating supply × SOFR × 37.9% Coinbase net share (calibrated Q1-2026: $1.22B ann on $75B supply × 4.3%). (5) Other services: 17% of spot+deriv. PV = Y3 revenue × P/S / Y3 diluted shares / (1+DR)³.",
      },
      {
        heading: "CAPM discount rate (derived, not hardcoded)",
        text: "DR = risk-free rate (10Y US Treasury) + equity risk premium (5.5%) × CAPM beta. Beta is computed as cov(COIN daily log-returns, S&P 500 daily log-returns) / var(S&P 500 daily log-returns) over the trailing 1Y from Yahoo Finance. Falls back to corr × vol-ratio estimate if fewer than 60 overlapping return dates are available. COIN is a high-beta equity due to its crypto revenue mix; historical beta typically ranges 1.5–3.5 depending on market cycle.",
      },
      {
        heading: "USDC revenue (velocity decay, manual scenarios)",
        text: "USDC revenue = Y3 USDC supply × Y3 SOFR × 37.9% Coinbase net share (calibrated Q1-2026: $305M/Q = $1.22B ann on $75B avg supply × 4.3% SOFR). Supply grows with velocity-decay; SOFR mean-reverts to 2.5% long-run over 36 months. Most volatile revenue line: a 150bps SOFR cut + 20% supply decline reduces USDC revenue ~40%.",
      },
      {
        heading: "Derivatives & market structure",
        text: "Coinbase acquired Deribit (2025), the world's largest crypto options exchange. Deribit revenue is modeled as Binance Futures denominator × Deribit MS × 3.88 bps take-rate. CDE retail (CFTC-regulated US venue) is separate at 119 bps on small notional (~$4.2B/Q). Combined Coinbase derivatives MS vs Binance Futures ≈ 8.2% as of Q1-2026 ($355B total / $1.45T Binance Futures).",
      },
      {
        heading: "Supply & valuation",
        text: "Y3 diluted shares = current shares outstanding × SBC dilution multiplier (Bear 1.25×, Base 1.15×, Bull 1.10×). Coinbase has significant SBC; the bull case assumes buybacks partially offset. Optionality bonus (1.00–1.15×) captures international expansion, Base L2 growth, and favorable US crypto regulation. P/S range 4–11× vs comps: Nasdaq OMX ~7×, ICE ~12×, CME ~20×; Coinbase trades at a crypto premium that compresses in bear markets. FDV = market cap (no token unlock; stock shares).",
      },
      {
        heading: "Key risks",
        text: "USDC revenue sensitivity: Coinbase earns ~$1.5B+/yr from USDC interest; Fed rate cuts compress this materially. Competition: Binance, OKX, Kraken, and Robinhood compete on spot; Deribit and CME on derivatives. Regulatory: favorable crypto regulation in the US is a tailwind, but SEC enforcement risk persists. Derivatives: no separately reported derivatives revenue; Coinbase Advanced Trade derivatives volume is estimated, not disclosed. Equity dilution: SBC is significant and dilutive.",
      },
    ],
  },
  vvv: {
    sections: [
      {
        heading: "Core revenue model",
        text: "GP = estimated total platform revenue (subscription + API). Venice allocates ~9% of subscription revenue to on-chain VVV buybacks-and-burns; the remainder funds the company treasury. On-chain burns ($250K/30D, $3M ann.) are the only measured component. Total platform revenue (~$32M ann.) is estimated from April 2026 subscription burn rates × implied capture ratio. Year-3 GP uses direct revenue growth assumptions — no market-share simulation.",
      },
      {
        heading: "Supply / emission path",
        text: "VVV has no max supply cap. Annual emissions are 3M VVV/yr from July 2026 (stepped down from 14M at launch). 3Y gross issuance ≈ 9M tokens. Burn offset per scenario: burn spend ÷ average price. Bear assumes minimal offset; bull assumes further emission cuts and higher burn spend from growing revenue.",
      },
      {
        heading: "Revenue uncertainty",
        text: "Venice does not publicly disclose platform revenue. The ~$32M/yr estimate derives from subscription tier burn ratios and is not confirmed by Venice. On-chain DefiLlama figures capture only the VVV buyback-and-burn spend — not subscription or API revenue flowing off-chain. Treat all revenue figures as indicative, not measured.",
      },
      {
        heading: "Multiple & discount rate",
        text: "15× revenue multiple (standard across dashboard) applied to Year-3 estimated platform revenue, discounted at 25%. Total revenue is used (not just holder-captured burns) because burns are a discretionary allocation from revenue, not revenue itself. The 15× multiple implies strong sustained growth and may be aggressive for current pricing.",
      },
      {
        heading: "Model limitations",
        text: "Scenarios are manually constructed with no Monte Carlo simulation. Price distributions approximate log-normal σ = 1.0 for comparability with other dashboard tokens. Short price history; no historical backtest is presented. Data freshness: June 17, 2026.",
      },
    ],
  },
  uni: {
    sections: [
      {
        heading: "What is being valued",
        text: "Uniswap's protocol-level gross profit under two fee scenarios: current-state (~0.826bps LP protocol take + 0.30bps frontend) and full-activation (25% of LP fees routed to protocol + 0.30bps frontend). 3-year investment horizon — not a perpetual DCF.",
      },
      {
        heading: "Volume simulation",
        text: "Primary HYPE-style denominator-share model: sample historical Binance spot monthly volume from 2022-present, apply monthly log-return bootstraps from the same window, then multiply by UNI/Binance spot share. Share starts from MS90 and blended velocity — 70% MS30/MS180 + 30% MS7/MS30 monthly-equivalent — decays over 12 months.",
      },
      {
        heading: "DEX-native sensitivity",
        text: "The former total-DEX denominator model remains as a sensitivity: total DEX monthly volume × UNI/total-DEX share, using the same 2022-present sampling window and blended velocity decay.",
      },
      {
        heading: "Discount rate",
        text: "Liquid-token CAPM: risk-free rate + 3% ERP × (UNI daily vol ÷ S&P 500 daily vol), ~24–25% DR. Refreshed on each run.",
      },
      {
        heading: "Supply & multiple",
        text: "15× GP multiple applied to Year-3 GP, discounted at DR. Primary denominator uses effective Year-3 supply: current circulating UNI plus observed reserved-supply release, capped at max supply. FDV remains a max-supply sensitivity. Protocol fees burn UNI via TokenJar → Firepit.",
      },
      { heading: "Model locked", text: "Methodology locked 2026-05-09." },
    ],
  },
  ethfi: {
    sections: [
      {
        heading: "What is being valued",
        text: "ether.fi's gross profit from three revenue streams: (1) card business — GDV × 135bps take × operating margin, (2) liquid staking — staking TVL × staking APY × 5% take, (3) vaults — vault TVL × 1% flat fee.",
      },
      {
        heading: "Scenario weighting",
        text: "Bear (50% card margin, 20% weight), Base (60%, 40%), Bull (70%, 40%). 50k paths per scenario.",
      },
      {
        heading: "Discount rate",
        text: "Fixed at 27.5% — reflecting higher execution risk vs UNI given early-stage card business and ETH price dependency.",
      },
      {
        heading: "Supply & multiple",
        text: "15× GP multiple. Y3 supply uses the larger of scheduled supply and current circulating supply when no burn is modeled. Net profit accumulates to treasury cash and is added back to equity value.",
      },
      {
        heading: "Key risks",
        text: "Card GDV growth is the dominant driver. Staking APY compression reduces staking GP over time.",
      },
    ],
  },
  jup: {
    sections: [
      {
        heading: "What is being valued",
        text: "Jupiter's modeled gross profit from two external-denominator product lines: (1) Perps — Binance Futures volume × JUP/Binance perps share × clean take-rate, (2) Spot aggregator/Ultra + Jupiterz — Binance spot volume × JUP/Binance spot share × observed rake. Smaller products covered by +10% optionality premium.",
      },
      {
        heading: "Buyback mechanics",
        text: "50% of simulated entity GP used for JUP buybacks via Litterbox Trust, reducing Y3 effective supply denominator.",
      },
      {
        heading: "Supply schedule",
        text: "0 scheduled unlocks assumed. The ~3.4B JUP cold-storage/community reserve has no public distribution timeline.",
      },
      {
        heading: "Market-share paths",
        text: "Perps and spot use the updated valuation-skill standard: 70% MS30/MS180 + 30% MS7/MS30 monthly-equivalent share velocity, capped and linearly decayed over 12 months. MC draws sample Binance Futures and Binance spot monthly denominators.",
      },
      {
        heading: "Discount rate & multiple",
        text: "Fixed at 24.4%, 15× GP multiple. Three premium cases: Core, +10% Optionality, +10% Opt + Jupnet.",
      },
      {
        heading: "Model locked",
        text: "Methodology locked 2026-05-09, corrected 2026-05-15 for supply schedule, updated 2026-06-17 for Binance-denominator perps/spot share modeling, 2Y probabilities, and full percentile ladders.",
      },
    ],
  },
  sky: {
    sections: [
      {
        heading: "Core revenue model",
        text: "Sky GP = modeled Sky supply × gross-income take-rate − savings-cost rate − stUSDS-cost rate. NP subtracts OPEX. Protocol financial rates remain locked until the full Sky financial refresh is run.",
      },
      {
        heading: "Money-market share path",
        text: "HYPE-style denominator-share model: sample starting broad money-market / yield-vault TVL from historical monthly denominators, sample monthly denominator shocks from historical money-market returns, then multiply by Sky share.",
      },
      {
        heading: "Market share momentum",
        text: "Sky share starts from MS90. The share path uses the same velocity ensemble standard as the newer models: 70% capped MS30/MS180 monthly-equivalent velocity + 30% capped MS7/MS30 velocity, linearly decayed over 12 months. Absolute cap: 35% of the money-market denominator.",
      },
      {
        heading: "Supply path",
        text: "DAI is held flat in the base model. USDS fills the residual between modeled total Sky stable supply and flat DAI. SKY token supply is held flat; no buybacks or burns are modeled.",
      },
      {
        heading: "Data sources",
        text: "USDS and DAI supply use Sky's official supply page backing API. The growth denominator uses the repo's broad money-market / yield-vault TVL history, not DefiLlama stablecoin market share.",
      },
    ],
  },
};

// ── InfoTooltip ──────────────────────────────────────────────────────────────

function InfoTooltip({ termKey }: { termKey: string }) {
  const def = TERMS[termKey];
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open]);

  if (!def) return null;

  return (
    <div ref={ref} className="relative inline-flex items-center" style={{ verticalAlign: "middle" }}>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        className="ml-1 w-3.5 h-3.5 rounded-full border text-gray-600 border-gray-600 flex items-center justify-center text-xs leading-none hover:border-gray-400 hover:text-gray-400 transition-colors shrink-0"
        style={{ fontSize: "9px", fontStyle: "italic", fontWeight: 700 }}
        aria-label={`Info: ${def.title}`}
      >
        i
      </button>
      {open && (
        <div
          className="absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 rounded-xl border border-[#3d4166] bg-[#1a1d29] shadow-xl p-3"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="text-xs font-semibold text-white mb-1">{def.title}</div>
          <div className="text-xs text-gray-400 leading-relaxed">{def.body}</div>
          <div className="absolute left-1/2 -translate-x-1/2 top-full w-2 h-2 border-r border-b border-[#3d4166] bg-[#1a1d29] rotate-45 -mt-1" />
        </div>
      )}
    </div>
  );
}

// ── ModelMethodology ─────────────────────────────────────────────────────────

function ModelMethodology({ tokenKey }: { tokenKey: string }) {
  const [open, setOpen] = useState(false);
  const m = METHODOLOGY[tokenKey];
  if (!m) return null;

  return (
    <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] overflow-hidden">
      <div
        role="button"
        tabIndex={0}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setOpen((v) => !v); }}
        className="w-full px-6 py-4 flex items-center justify-between text-left hover:bg-[#1e2130] transition-colors cursor-pointer"
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-gray-300">Model &amp; Assumptions</span>
          <InfoTooltip termKey="gp_capture" />
        </div>
        <svg
          className="transition-transform"
          style={{ transform: open ? "rotate(180deg)" : "rotate(0deg)" }}
          width="16" height="16" viewBox="0 0 24 24" fill="none"
          stroke="#6b7280" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </div>
      {open && (
        <div className="px-6 pb-6 space-y-4 border-t border-[#2d3144] pt-4">
          {m.sections.map((s) => (
            <div key={s.heading}>
              <div className="text-sm font-semibold text-gray-200 mb-1">{s.heading}</div>
              <div className="text-sm text-gray-400 leading-relaxed">{s.text}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Formatters ───────────────────────────────────────────────────────────────

function fmtPrice(n: number): string {
  if (n >= 1) return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return `$${n.toFixed(4)}`;
}

function fmtLarge(n: number): string {
  if (n == null || isNaN(n)) return "$0";
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function pct(n: number, decimals = 1): string {
  return `${(n * 100).toFixed(decimals)}%`;
}

// ── MetricCard ───────────────────────────────────────────────────────────────

function valueTextClass(v: string): string {
  if (v.length > 15) return "text-lg";
  if (v.length > 12) return "text-xl";
  if (v.length > 8)  return "text-2xl";
  return "text-3xl";
}

function MetricCard({
  label,
  value,
  sub,
  accent,
  termKey,
  highlighted,
  highlightBg,
  highlightBorder,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: "green" | "red" | "yellow" | "blue" | "default";
  termKey?: string;
  highlighted?: boolean;
  highlightBg?: string;
  highlightBorder?: string;
}) {
  if (highlighted) {
    return (
      <div
        className="rounded-xl border px-5 py-4 flex flex-col gap-1"
        style={{ background: highlightBg ?? "#0d1117", borderColor: highlightBorder ?? "#1e2d40" }}
      >
        <div className="flex items-center gap-1 text-xs text-gray-400 font-mono">
          {label}
          {termKey && <InfoTooltip termKey={termKey} />}
        </div>
        <div className={`${valueTextClass(value)} font-bold text-white font-mono leading-tight`}>
          {value}
        </div>
        {sub && <div className="text-xs text-gray-400 leading-relaxed mt-0.5">{sub}</div>}
      </div>
    );
  }

  const accentColor = {
    green: "#15803d",
    red: "#b91c1c",
    yellow: "#a16207",
    blue: "#1d4ed8",
    default: "#111827",
  }[accent ?? "default"];

  return (
    <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] px-5 py-4 flex flex-col gap-1">
      <div className="flex items-center gap-1 text-xs text-gray-500 font-mono">
        {label}
        {termKey && <InfoTooltip termKey={termKey} />}
      </div>
      <div className={`${valueTextClass(value)} font-bold font-mono leading-tight`} style={{ color: accentColor }}>
        {value}
      </div>
      {sub && <div className="text-xs text-gray-500 leading-relaxed mt-0.5">{sub}</div>}
    </div>
  );
}

// ── McapChart ────────────────────────────────────────────────────────────────

function McapChart({ history, symbol, color }: { history: McapPoint[]; symbol: string; color: string }) {
  if (!history.length) return null;

  const min    = Math.min(...history.map((d) => d.mcap));
  const max    = Math.max(...history.map((d) => d.mcap));
  const latest = history[history.length - 1].mcap;
  const first  = history[0].mcap;
  const change = ((latest / first) - 1) * 100;
  const isUp   = change >= 0;

  function fmtMcap(n: number) {
    if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
    return `$${(n / 1e6).toFixed(0)}M`;
  }

  const step  = Math.max(1, Math.floor(history.length / 12));
  const ticks = history
    .filter((_, i) => i % step === 0 || i === history.length - 1)
    .map((d) => d.date);

  return (
    <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <span className="text-sm font-semibold text-gray-300">{symbol} Market Cap</span>
          <span className="ml-2 text-xs text-gray-500">90 days</span>
        </div>
        <div className="text-right">
          <div className="text-base font-bold font-mono text-white">{fmtMcap(latest)}</div>
          <div className="text-xs font-mono" style={{ color: isUp ? "#4ade80" : "#f87171" }}>
            {isUp ? "+" : ""}{change.toFixed(1)}%
          </div>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={160}>
        <AreaChart data={history} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id={`mcap-grad-${symbol}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.25} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" vertical={false} />
          <XAxis
            dataKey="date"
            ticks={ticks}
            tickFormatter={(d: string) => { const [, m, day] = d.split("-"); return `${parseInt(m)}/${parseInt(day)}`; }}
            tick={{ fill: "#6b7280", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            domain={[min * 0.95, max * 1.05]}
            tickFormatter={fmtMcap}
            tick={{ fill: "#6b7280", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={52}
          />
          <Tooltip
            contentStyle={{ background: "#1a1d29", border: "1px solid #2d3144", borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: "#9ca3af", marginBottom: 2 }}
            formatter={(v: number) => [fmtMcap(v), "MCap"]}
            itemStyle={{ color }}
          />
          <Area
            type="monotone"
            dataKey="mcap"
            stroke={color}
            strokeWidth={1.5}
            fill={`url(#mcap-grad-${symbol})`}
            dot={false}
            activeDot={{ r: 3, fill: color }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── DistributionChart ────────────────────────────────────────────────────────

const DIST_LABELS: { key: string; label: string; isMedian?: boolean }[] = [
  { key: "p95", label: "P95" },
  { key: "p90", label: "P90" },
  { key: "p80", label: "P80" },
  { key: "p75", label: "P75" },
  { key: "p70", label: "P70" },
  { key: "p60", label: "P60" },
  { key: "p50", label: "P50", isMedian: true },
  { key: "p40", label: "P40" },
  { key: "p30", label: "P30" },
  { key: "p25", label: "P25" },
  { key: "p20", label: "P20" },
  { key: "p10", label: "P10" },
  { key: "p5",  label: "P5" },
];

// Fallback: only core percentiles available
const DIST_LABELS_CORE: { key: string; label: string; isMedian?: boolean }[] = [
  { key: "p90", label: "P90" },
  { key: "p75", label: "P75" },
  { key: "p50", label: "P50", isMedian: true },
  { key: "p25", label: "P25" },
];

function DistributionChart({
  scenario,
  spot,
  ev,
}: {
  scenario: ValuationScenario;
  spot: number;
  ev: number;
}) {
  const dist = scenario.distribution;
  const hasFull = dist && Object.keys(dist).length > 4;
  const rowDefs = hasFull ? DIST_LABELS : DIST_LABELS_CORE;
  const source: Record<string, number> = dist ?? (scenario.pv as unknown as Record<string, number>);

  const rows = [...rowDefs]
    .reverse()
    .map((d) => ({ ...d, value: source[d.key] as number | undefined }))
    .filter((r): r is typeof r & { value: number } => r.value !== undefined && r.value > 0);

  if (!rows.length) return null;

  const yMax = Math.max(...rows.map(r => r.value), ev) * 1.12;

  return (
    <div className="space-y-5">
      <h2 className="text-3xl font-bold text-gray-900">Selected-model PV price distribution</h2>

      <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-6">
        <div className="flex items-center justify-between mb-1">
          <div>
            <div className="text-sm font-semibold text-gray-300">Percentile ladder + current spot</div>
            <div className="text-xs text-gray-500 mt-0.5">Percentile ladder + probability-weighted EV</div>
          </div>
          <div className="flex items-center gap-4 text-xs text-gray-500">
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-5 border-t border-orange-400" />
              Spot {fmtPrice(spot)}
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-5 border-t border-dashed border-blue-400" />
              EV {fmtPrice(ev)}
            </span>
          </div>
        </div>

        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={rows} margin={{ top: 24, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fill: "#6b7280", fontSize: 11 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tickFormatter={(v: number) => `$${v >= 1000 ? (v / 1000).toFixed(0) + "k" : v.toFixed(0)}`}
              tick={{ fill: "#6b7280", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              width={40}
              domain={[0, yMax]}
            />
            <Tooltip
              contentStyle={{ background: "#1a1d29", border: "1px solid #2d3144", borderRadius: 8, fontSize: 11 }}
              formatter={(v: number) => [fmtPrice(v), "PV"]}
            />
            <ReferenceLine y={spot} stroke="#fb923c" strokeWidth={1.5} />
            <ReferenceLine y={ev}   stroke="#60a5fa" strokeWidth={1.5} strokeDasharray="4 3" />
            <Bar dataKey="value" radius={[3, 3, 0, 0]} maxBarSize={48}>
              <LabelList
                dataKey="value"
                position="top"
                content={(props) => {
                  const { x, y, width, value, index } = props as { x?: unknown; y?: unknown; width?: unknown; value?: unknown; index?: number };
                  const nx = Number(x), ny = Number(y), nw = Number(width), nv = Number(value);
                  if (!isFinite(nx) || !isFinite(ny) || !isFinite(nw) || !isFinite(nv)) return null;
                  const isP50 = rows[index ?? 0]?.isMedian;
                  return (
                    <text
                      x={nx + nw / 2}
                      y={ny - 4}
                      textAnchor="middle"
                      fontSize={9}
                      fill={isP50 ? "#e2e8f0" : "#6b7280"}
                      fontWeight={isP50 ? 600 : 400}
                    >
                      {fmtPrice(nv)}
                    </text>
                  );
                }}
              />
              {rows.map((row) => (
                <Cell
                  key={row.key}
                  fill={row.isMedian ? "#1e3a4a" : "#1e2a3a"}
                  stroke={row.isMedian ? "#38bdf8" : "#2d3144"}
                  strokeWidth={row.isMedian ? 1.5 : 0.5}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>

        <p className="text-xs text-gray-600 mt-2 leading-relaxed">
          Bars show selected-model PV/token percentiles. Bold bar is P50 {fmtPrice(scenario.pv.p50)}. Blue dashed line is probability-weighted EV {fmtPrice(ev)}, which captures all paths including the right tail.
        </p>
      </div>
    </div>
  );
}

// ── ScenarioTable ────────────────────────────────────────────────────────────

function ScenarioTable({
  scenarios,
  spot,
}: {
  scenarios: ValuationScenario[];
  spot: number;
}) {
  const show2YMove = scenarios.some((s) => s.prob_spot_up_30_2y !== undefined || s.prob_spot_down_30_2y !== undefined);

  return (
    <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] overflow-hidden">
      <div className="px-6 py-4 border-b border-[#2d3144]">
        <span className="text-sm font-semibold text-gray-300">Scenario Comparison</span>
        <span className="ml-2 text-xs text-gray-600">discounted PV / token @ 3Y</span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#2d3144]">
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 whitespace-nowrap">Scenario</th>
              {(["P25", "P50", "P75", "P90"] as const).map((p) => (
                <th key={p} className="text-right px-3 py-3 text-xs font-medium text-gray-500 whitespace-nowrap">
                  {p} <InfoTooltip termKey={p.toLowerCase()} />
                </th>
              ))}
              <th className="text-right px-3 py-3 text-xs font-medium text-gray-500 whitespace-nowrap">
                EV <InfoTooltip termKey="ev" />
              </th>
              <th className="text-right px-4 py-3 text-xs font-medium text-gray-500 whitespace-nowrap">
                P(spot) <InfoTooltip termKey="prob_above_spot" />
              </th>
              {show2YMove && (
                <>
                  <th className="text-right px-4 py-3 text-xs font-medium text-gray-500 whitespace-nowrap">
                    2Y +30%
                  </th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-gray-500 whitespace-nowrap">
                    2Y -30%
                  </th>
                </>
              )}
              <th className="text-right px-4 py-3 text-xs font-medium text-gray-500 whitespace-nowrap">
                3× <InfoTooltip termKey="prob_3x" />
              </th>
            </tr>
          </thead>
          <tbody>
            {scenarios.map((s) => {
              const upside  = spot > 0 ? (s.pv.p50 / spot - 1) * 100 : 0;
              const probColor = s.prob_above_spot >= 0.5
                ? "#4ade80"
                : s.prob_above_spot >= 0.35
                ? "#fbbf24"
                : "#f87171";

              return (
                <tr
                  key={s.key}
                  className="border-b border-[#2d3144] last:border-0 transition-colors"
                  style={s.is_primary ? { background: "rgba(16, 185, 129, 0.04)" } : {}}
                >
                  {/* Label */}
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <span className={`text-sm font-medium ${s.is_primary ? "text-white" : "text-gray-400"}`}>
                        {s.label}
                      </span>
                      {s.is_primary && (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 font-medium">
                          primary
                        </span>
                      )}
                    </div>
                    <div className="text-xs mt-0.5" style={{ color: upside >= 0 ? "#4ade80" : "#f87171" }}>
                      P50 {upside >= 0 ? "+" : ""}{upside.toFixed(0)}% vs spot
                    </div>
                  </td>

                  {/* Percentiles */}
                  {(["p25", "p50", "p75", "p90"] as const).map((p) => (
                    <td key={p} className="px-3 py-4 text-right font-mono text-sm text-gray-300 whitespace-nowrap">
                      {fmtPrice(s.pv[p])}
                    </td>
                  ))}

                  {/* EV */}
                  <td className="px-3 py-4 text-right font-mono text-sm text-blue-300 whitespace-nowrap">
                    {fmtPrice(s.ev)}
                  </td>

                  {/* P(spot) */}
                  <td className="px-4 py-4 text-right whitespace-nowrap">
                    <span className="font-mono text-sm font-semibold" style={{ color: probColor }}>
                      {pct(s.prob_above_spot)}
                    </span>
                  </td>

                  {/* 2Y undiscounted move probabilities */}
                  {show2YMove && (
                    <>
                      <td className="px-4 py-4 text-right whitespace-nowrap">
                        {s.prob_spot_up_30_2y !== undefined
                          ? <span className="font-mono text-sm text-emerald-300">{pct(s.prob_spot_up_30_2y)}</span>
                          : <span className="text-gray-600">—</span>}
                      </td>
                      <td className="px-4 py-4 text-right whitespace-nowrap">
                        {s.prob_spot_down_30_2y !== undefined
                          ? <span className="font-mono text-sm text-red-300">{pct(s.prob_spot_down_30_2y)}</span>
                          : <span className="text-gray-600">—</span>}
                      </td>
                    </>
                  )}

                  {/* 3× prob */}
                  <td className="px-4 py-4 text-right whitespace-nowrap">
                    {s.prob_3x !== undefined
                      ? <span className="font-mono text-sm text-gray-400">{pct(s.prob_3x)}</span>
                      : <span className="text-gray-600">—</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Per-token GP metadata ────────────────────────────────────────────────────

type GpFmt = "pct" | "money" | "x" | "years" | "bps" | "raw";
type GpMeta = { label: string; fmt: GpFmt };

const TOKEN_GP_META: Record<string, Record<string, GpMeta>> = {
  uni: {
    annualized_current_state:   { label: "GP current state (ann.)",   fmt: "money" },
    annualized_full_activation: { label: "GP full activation (ann.)",  fmt: "money" },
    ann_volume:                 { label: "Annual volume",              fmt: "money" },
    base_seed_monthly:          { label: "Base seed monthly vol.",      fmt: "money" },
    start_total_dex_monthly_p50:{ label: "Start total DEX P50",         fmt: "money" },
    latest30_total_dex_volume:  { label: "Latest 30D total DEX",        fmt: "money" },
    trailing12_median_total_dex_volume: { label: "T12M median total DEX", fmt: "money" },
    latest30_volume:            { label: "Latest 30D volume",          fmt: "money" },
    trailing12_median_volume:   { label: "T12M median monthly vol.",    fmt: "money" },
    lp_fee_bps_30d:             { label: "LP take 30D",               fmt: "bps"   },
    trailing12_lp_fee_bps:      { label: "LP take T12M",              fmt: "bps"   },
    take_bps_current:           { label: "Protocol take — current",    fmt: "bps"   },
    take_bps_full:              { label: "Protocol take — full activ.", fmt: "bps"   },
    mcap_current_state_gp:      { label: "Mcap / GP (current)",        fmt: "x"     },
    mcap_full_activation_gp:    { label: "Mcap / GP (full activ.)",    fmt: "x"     },
    fdv_full_activation_gp:     { label: "FDV / GP (full activ.)",     fmt: "x"     },
    ms_momentum_initial:        { label: "MS momentum initial",         fmt: "x"     },
    eoy3_share_model:           { label: "EOY3 share model",            fmt: "pct"   },
    start_binance_spot_monthly_p50: { label: "Start Binance spot P50",  fmt: "money" },
    latest30_binance_spot_volume: { label: "Latest 30D Binance spot",   fmt: "money" },
    ms90_vs_binance_spot:       { label: "MS90 vs Binance spot",        fmt: "pct"   },
    ms30_ms180_binance_spot_trend: { label: "Binance spot MS trend",    fmt: "x"     },
    binance_spot_eoy3_share_model: { label: "Binance spot EOY3 share",  fmt: "pct"   },
    binance_spot_full_activation_p50: { label: "Binance spot P50 PV",   fmt: "money" },
    binance_spot_full_activation_ev: { label: "Binance spot EV PV",     fmt: "money" },
  },
  ethfi: {
    card_annualized:   { label: "Card GP (ann.)",    fmt: "money" },
    staking_annualized:{ label: "Staking GP (ann.)", fmt: "money" },
    vault_annualized:  { label: "Vault GP (ann.)",   fmt: "money" },
    total_annualized:  { label: "Total GP (ann.)",   fmt: "money" },
    card_gdv_30d_ann:  { label: "Card GDV (ann.)",   fmt: "money" },
    staking_apy:       { label: "Staking APY",        fmt: "pct"   },
    stake_tvl:         { label: "Stake TVL",          fmt: "money" },
    vault_tvl:         { label: "Vault TVL",          fmt: "money" },
    card_take_bps_30d: { label: "Card take 30D",      fmt: "bps"   },
    card_mom:          { label: "Card MoM growth",    fmt: "pct"   },
  },
  jup: {
    perps_30d:          { label: "Perps 30D GP",      fmt: "money" },
    perps_30d_volume:   { label: "Perps 30D volume",  fmt: "money" },
    perps_clean_take_rate_bps: { label: "Perps clean take", fmt: "bps" },
    aggregator_30d:     { label: "Aggregator 30D GP", fmt: "money" },
    aggregator_30d_volume: { label: "Aggregator 30D vol.", fmt: "money" },
    jupiterz_30d:       { label: "Jupiterz 30D GP",   fmt: "money" },
    total_30d:          { label: "Total 30D GP",      fmt: "money" },
    spot_30d_volume:    { label: "Spot 30D volume",   fmt: "money" },
    spot_take_rate_bps: { label: "Spot rake",         fmt: "bps" },
    seed_monthly:       { label: "Seed monthly GP",   fmt: "money" },
    seed_annualized:    { label: "Seed GP (ann.)",    fmt: "money" },
    mcap_entity_gp:     { label: "Mcap / entity GP",  fmt: "x" },
    perps_ms30_vs_binance_futures: { label: "Perps MS30 vs Binance", fmt: "pct" },
    perps_share_velocity_capped: { label: "Perps share velocity", fmt: "x" },
    perps_eoy3_share_model: { label: "Perps EOY3 share", fmt: "pct" },
    spot_ms30_vs_binance_spot: { label: "Spot MS30 vs Binance", fmt: "pct" },
    spot_share_velocity_capped: { label: "Spot share velocity", fmt: "x" },
    spot_eoy3_share_model: { label: "Spot EOY3 share", fmt: "pct" },
    start_binance_futures_monthly_p50: { label: "Start Binance futures", fmt: "money" },
    start_binance_spot_monthly_p50: { label: "Start Binance spot", fmt: "money" },
    optional_tracked_30d:{ label: "Optional 30D",     fmt: "money" },
    y3_daily_mean_gp_p50:{ label: "Y3 daily GP P50", fmt: "money" },
    y3_perps_daily_mean_volume_p50: { label: "Y3 perps daily vol.", fmt: "money" },
    y3_spot_daily_mean_volume_p50: { label: "Y3 spot daily vol.", fmt: "money" },
  },
  sky: {
    gross_income:                  { label: "Gross income (ann.)",       fmt: "money" },
    current_gp:                    { label: "Current GP (ann.)",         fmt: "money" },
    current_np_base_opex:          { label: "Current NP @ base OPEX",    fmt: "money" },
    mcap_current_gp:               { label: "Mcap / current GP",         fmt: "x" },
    fdv_current_gp:                { label: "FDV / current GP",          fmt: "x" },
    gross_income_take_rate_bps:    { label: "Gross income take-rate",    fmt: "bps" },
    savings_cost_rate_bps:         { label: "Savings cost rate",         fmt: "bps" },
    stusds_cost_rate_bps:          { label: "stUSDS cost rate",          fmt: "bps" },
    net_gp_take_rate_bps:          { label: "Net GP take-rate",          fmt: "bps" },
    usds_supply:                   { label: "Official USDS",            fmt: "money" },
    dai_supply:                    { label: "Official DAI",             fmt: "money" },
    total_sky_stable_supply:       { label: "Official USDS + DAI",      fmt: "money" },
    money_market_tvl:              { label: "Money-market denominator", fmt: "money" },
    ms7_vs_money_market:           { label: "MS7 vs money markets",     fmt: "pct" },
    ms90_vs_money_market:          { label: "MS90 vs money markets",    fmt: "pct" },
    ms30_vs_money_market:          { label: "MS30 vs money markets",    fmt: "pct" },
    ms180_vs_money_market:         { label: "MS180 vs money markets",   fmt: "pct" },
    ms30_ms180_trend:              { label: "MS30/MS180 trend",         fmt: "x" },
    ms7_ms30_trend:                { label: "MS7/MS30 trend",           fmt: "x" },
    velocity_ensemble_monthly:     { label: "Velocity ensemble",        fmt: "pct" },
    velocity_long_component_monthly: { label: "70% leg velocity",       fmt: "pct" },
    velocity_short_component_monthly:{ label: "30% leg velocity",       fmt: "pct" },
    eoy3_money_market_share:       { label: "EOY3 money-market share",  fmt: "pct" },
    y3_gp_p50:                     { label: "Y3 GP P50",               fmt: "money" },
    y3_gross_income_p50:           { label: "Y3 gross income P50",     fmt: "money" },
    y3_savings_cost_p50:           { label: "Y3 savings cost P50",     fmt: "money" },
    y3_stusds_cost_p50:            { label: "Y3 stUSDS cost P50",      fmt: "money" },
    y3_total_stable_supply_p50:    { label: "Y3 total stable P50",      fmt: "money" },
    y3_usds_supply_p50:            { label: "Y3 USDS P50",              fmt: "money" },
    y3_avg_money_market_tvl_p50:   { label: "Y3 avg money-market TVL", fmt: "money" },
    y3_avg_total_stable_supply_p50:{ label: "Y3 avg Sky supply",       fmt: "money" },
    y3_gp_change_vs_current:       { label: "Y3 GP vs current",         fmt: "pct" },
    y3_total_stable_supply_change_vs_current: { label: "Y3 supply vs current", fmt: "pct" },
    y3_usds_supply_change_vs_current: { label: "Y3 USDS vs current",    fmt: "pct" },
    y3_money_market_tvl_change_vs_current: { label: "Y3 denominator vs current", fmt: "pct" },
    treasury_cash_p50:             { label: "Treasury cash P50",        fmt: "money" },
  },
};

function fmtGpVal(val: number, fmt: GpFmt): string {
  if (fmt === "pct")   return `${(val * 100).toFixed(1)}%`;
  if (fmt === "money") return fmtLarge(val);
  if (fmt === "x")     return `${val.toFixed(1)}×`;
  if (fmt === "years") return `${val.toFixed(1)}y`;
  if (fmt === "bps")   return `${val.toFixed(2)} bps`;
  return val.toFixed(4);
}

// ── TokenKeyMetrics ───────────────────────────────────────────────────────────

function TokenKeyMetrics({ currentGp, tokenKey }: { currentGp: Record<string, number>; tokenKey: string }) {
  const meta = TOKEN_GP_META[tokenKey] ?? {};
  const entries = Object.entries(currentGp)
    .filter(([k, v]) => meta[k] && typeof v === "number" && isFinite(v) && v !== 0)
    .map(([k, v]) => ({ key: k, label: meta[k].label, value: fmtGpVal(v, meta[k].fmt) }));

  if (!entries.length) return null;

  return (
    <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-6">
      <h3 className="text-xl font-bold text-white mb-4">Key metrics</h3>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
        {entries.map(({ key, label, value }) => (
          <div key={key} className="bg-[#252836] rounded-xl border border-[#2d3144] px-4 py-3 flex flex-col gap-0.5">
            <div className="text-xs text-gray-500">{label}</div>
            <div className="text-lg font-bold font-mono text-white leading-tight">{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── TokenModelAssumptions ─────────────────────────────────────────────────────

function TokenModelAssumptions({ tokenKey, model }: {
  tokenKey: string;
  model: { type: string; discount_rate: number; multiple: number; paths: number; note?: string };
}) {
  const m = METHODOLOGY[tokenKey];
  if (!m) return null;

  const drPct = (model.discount_rate * 100).toFixed(1);
  const multipleLine = tokenKey === "sky"
    ? `Multiple: ${model.multiple}× NP primary; 10× GP sensitivity`
    : `Multiple: ${model.multiple}× GP`;

  return (
    <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-6 space-y-4">
      <h3 className="text-xl font-bold text-white">Model assumptions</h3>

      {/* Top row: two code-block cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="bg-[#0d1117] rounded-xl border border-[#2d3144] px-5 py-4">
          <div className="text-xs text-gray-500 mb-2 uppercase tracking-wider font-semibold">Core revenue model</div>
          <pre className="text-xs text-gray-300 leading-relaxed whitespace-pre-wrap font-mono">{m.sections[0]?.text ?? ""}</pre>
        </div>
        <div className="bg-[#0d1117] rounded-xl border border-[#2d3144] px-5 py-4">
          <div className="text-xs text-gray-500 mb-2 uppercase tracking-wider font-semibold">Valuation logic</div>
          <pre className="text-xs text-gray-300 leading-relaxed whitespace-pre-wrap font-mono">{`${multipleLine}
Discount rate: ${drPct}%
${model.paths > 0 ? `Paths: ${(model.paths / 1000).toFixed(0)}k Monte Carlo` : `Manual scenarios (log-normal σ=1.0)`}
Horizon: 3 years`}</pre>
        </div>
      </div>

      {/* Bottom rows: remaining methodology sections */}
      {m.sections.slice(1).length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {m.sections.slice(1).map((s) => (
            <div key={s.heading} className="bg-[#252836] rounded-xl border border-[#2d3144] px-4 py-3">
              <div className="text-xs text-gray-500 mb-1 font-semibold uppercase tracking-wider">{s.heading}</div>
              <div className="text-xs text-gray-400 leading-relaxed">{s.text}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── MarketShareSection (shared for HYPE + UNI) ───────────────────────────────

interface MsConfig {
  chartNote: string;
  tableNote: string;
  driversLabel?: string;
  driversTitle: string;
  driversBody: React.ReactNode;
  tableRows: (gp: Record<string, number>, data: ValuationData) => [string, string][];
  yCapPct: number;   // y-axis max cap as decimal
}

const MS_CONFIG: Record<string, MsConfig> = {
  hype: {
    yCapPct: 0.35,
    chartNote: "Chart uses daily revenue-implied HL volume for rolling continuity; headline cards use DefiLlama MCP derivatives-volume aggregates.",
    tableNote: "DefiLlama fee rows include builder-code fees in dailyFees. Valuation uses clean treasury revenue at ~0.026% of notional; stablecoin yield is modeled separately.",
    driversTitle: "Perps + stablecoin yield",
    driversBody: null,   // filled inline below
    tableRows: (gp, data) => {
      const perpGp = gp["perp_gp_annual"] as number;
      const usdcGp = gp["usdc_gp_annual"] as number;
      const mcap   = data.market.market_cap;
      const ms30   = gp["ms30_vs_binance"] as number;
      const ms180  = gp["ms180_vs_binance"] as number;
      const ms90   = gp["ms90_vs_binance"] as number;
      return ([
        ["DefiLlama 30D revenue ann.",          fmtLarge(gp["defillama_30d_ann"] as number)],
        ["Perps treasury revenue ann.",         fmtLarge(perpGp)],
        ["USDC yield revenue ann.",             fmtLarge(usdcGp)],
        ["P/S: mcap / clean revenue",          perpGp > 0 ? `${(mcap / perpGp).toFixed(1)}x` : "—"],
        ["P/GP: mcap / clean revenue + yield", perpGp > 0 ? `${(mcap / (perpGp + usdcGp)).toFixed(1)}x` : "—"],
        ["Buyback years: clean revenue + yield", `${(gp["buyback_years_base"] as number).toFixed(1)}y`],
        ["Clean-revenue-only buyback years",   `${(gp["buyback_years_fee_only"] as number).toFixed(1)}y`],
        ["30D/180D component",                 `${((ms30 - ms180) * 100).toFixed(1)}%`],
        ["7D/30D component",                   `${(ms90 * 100).toFixed(1)}%`],
      ] as [string, string][]).filter(([, v]) => v && v !== "$0" && v !== "0.0y" && v !== "—");
    },
  },
  lighter: {
    yCapPct: 0.08,
    chartNote: "",
    tableNote: "",
    driversLabel: "Caveat",
    driversTitle: "Short history",
    driversBody: null,
    tableRows: (gp, data) => {
      const protocolRev = gp["defillama_30d_ann"] as number;
      const holderRev   = gp["holders_revenue_30d_ann"] as number;
      const mcap        = data.market.market_cap;
      return ([
        ["30D protocol revenue ann.",        fmtLarge(protocolRev)],
        ["30D holder revenue ann.",          fmtLarge(holderRev)],
        ["P/S: mcap / protocol revenue",     protocolRev > 0 ? `${(mcap / protocolRev).toFixed(1)}x` : "—"],
        ["P/GP: mcap / holder revenue",      holderRev   > 0 ? `${(mcap / holderRev).toFixed(1)}x`   : "—"],
        ["Holder capture",                   pct(gp["holder_capture_30d"] as number)],
        ["30D perps volume",                 fmtLarge(gp["perp_volume_30d"] as number)],
        ["Fee-only buyback years",           `${(gp["buyback_years_fee_only"] as number).toFixed(1)}y`],
        ["Base buyback years incl. yield",   gp["buyback_years_base"] != null ? `${(gp["buyback_years_base"] as number).toFixed(1)}y` : "—"],
      ] as [string, string][]).filter(([, v]) => v && v !== "$0" && v !== "—" && v !== "NaNy");
    },
  },
  uni: {
    yCapPct: 0.50,
    chartNote: "Rolling 30D and 90D UNI DEX volume / total DEX volume (all protocols, DefiLlama). Shows Uniswap's share of on-chain trading.",
    tableNote: "Volume from DefiLlama; denominator is total DEX volume across all chains and protocols.",
    driversTitle: "DEX spot market share",
    driversBody: null,
    tableRows: (gp, _data) => ([
      ["MS30 vs Total DEX",              pct(gp["ms30_vs_dex"] as number)],
      ["MS90 vs Total DEX",              pct(gp["ms90_vs_dex"] as number)],
      ["MS180 vs Total DEX",             pct(gp["ms180_vs_dex"] as number)],
      ["MS30/MS180 trend",               `${(gp["ms30_ms180_trend"] as number)?.toFixed(2)}×`],
      ["UNI 30D volume (ann.)",          fmtLarge(gp["ann_volume"] as number)],
      ["GP current state (ann.)",        fmtLarge(gp["annualized_current_state"] as number)],
      ["GP full activation (ann.)",      fmtLarge(gp["annualized_full_activation"] as number)],
    ] as [string, string][]).filter(([, v]) => v && v !== "$0" && v !== "NaN×"),
  },
  sky: {
    yCapPct: 0.40,
    chartNote: "Rolling 30D and 90D mean of official Sky supply divided by broad money-market / yield-vault TVL. This is the share seed used by the MC path.",
    tableNote: "USDS/DAI supply comes from Sky's official supply page API. The denominator is broad money-market / yield-vault TVL, not DefiLlama total stablecoin supply.",
    driversTitle: "Money-market share x yield spread",
    driversBody: null,
    tableRows: (gp, _data) => ([
      ["MS30 vs Money Markets",          pct(gp["ms30_vs_money_market"] as number)],
      ["MS7 vs Money Markets",           pct(gp["ms7_vs_money_market"] as number)],
      ["MS90 vs Money Markets",          pct(gp["ms90_vs_money_market"] as number)],
      ["MS180 vs Money Markets",         pct(gp["ms180_vs_money_market"] as number)],
      ["MS30/MS180 trend",               `${(gp["ms30_ms180_trend"] as number)?.toFixed(2)}×`],
      ["MS7/MS30 trend",                 `${(gp["ms7_ms30_trend"] as number)?.toFixed(2)}×`],
      ["Velocity ensemble",              `${(((gp["velocity_ensemble_monthly"] as number) ?? 0) * 100).toFixed(2)}% / mo`],
      ["Money-market denominator",       fmtLarge(gp["money_market_tvl"] as number)],
      ["Official USDS supply",           fmtLarge(gp["usds_supply"] as number)],
      ["Official DAI supply",            fmtLarge(gp["dai_supply"] as number)],
      ["Gross income take-rate",         `${((gp["gross_income_take_rate_bps"] as number) ?? 0).toFixed(1)} bps`],
      ["Savings cost rate",              `${((gp["savings_cost_rate_bps"] as number) ?? 0).toFixed(1)} bps`],
      ["stUSDS cost rate",               `${((gp["stusds_cost_rate_bps"] as number) ?? 0).toFixed(1)} bps`],
      ["Net GP take-rate",               `${((gp["net_gp_take_rate_bps"] as number) ?? 0).toFixed(1)} bps`],
    ] as [string, string][]).filter(([, v]) => v && v !== "$0" && v !== "NaN×"),
  },
  jup: {
    yCapPct: 0.03,
    chartNote: "Rolling 30D and 90D JUP perps volume divided by Binance Futures proxy. If direct derivatives volume is unavailable, JUP volume is clean-GP-implied from the modeled perps take-rate.",
    tableNote: "Perps denominator is Binance Futures; spot denominator is Binance spot. Both use BTCUSDT quote-volume histories scaled to Blockworks annual exchange totals.",
    driversTitle: "Binance-denominator perps + spot share",
    driversBody: null,
    tableRows: (gp, _data) => ([
      ["Perps MS30 vs Binance Futures",   pct(gp["perps_ms30_vs_binance_futures"] as number)],
      ["Perps MS90 vs Binance Futures",   pct(gp["perps_ms90_vs_binance_futures"] as number)],
      ["Perps MS180 vs Binance Futures",  pct(gp["perps_ms180_vs_binance_futures"] as number)],
      ["Spot MS30 vs Binance spot",       pct(gp["spot_ms30_vs_binance_spot"] as number)],
      ["Spot MS90 vs Binance spot",       pct(gp["spot_ms90_vs_binance_spot"] as number)],
      ["Perps share velocity",            `${(gp["perps_share_velocity_capped"] as number)?.toFixed(2)}×`],
      ["Spot share velocity",             `${(gp["spot_share_velocity_capped"] as number)?.toFixed(2)}×`],
      ["Perps clean take-rate",           `${((gp["perps_clean_take_rate_bps"] as number) ?? 0).toFixed(2)} bps`],
      ["Spot rake",                       `${((gp["spot_take_rate_bps"] as number) ?? 0).toFixed(2)} bps`],
      ["Y3 perps GP P50",                 fmtLarge(gp["y3_perps_gp_p50"] as number)],
      ["Y3 spot GP P50",                  fmtLarge(gp["y3_spot_gp_p50"] as number)],
    ] as [string, string][]).filter(([, v]) => v && v !== "$0" && v !== "NaN×"),
  },
  ethfi: {
    yCapPct: 0.90,
    chartNote: "Rolling 30D and 90D mean of ether.fi staking TVL / total LRT TVL (ether.fi + Kelp + Renzo + Puffer + Swell). Shows ether.fi dominance within the liquid restaking niche.",
    tableNote: "Denominator sums top LRT protocols from DefiLlama; excludes traditional liquid staking (Lido, Rocket Pool).",
    driversTitle: "LRT restaking market share",
    driversBody: null,
    tableRows: (gp, _data) => ([
      ["MS30 vs Total LRT",              pct(gp["ms30_vs_lrt"] as number)],
      ["MS90 vs Total LRT",              pct(gp["ms90_vs_lrt"] as number)],
      ["MS180 vs Total LRT",             pct(gp["ms180_vs_lrt"] as number)],
      ["MS30/MS180 trend",               `${(gp["ms30_ms180_trend"] as number)?.toFixed(2)}×`],
      ["LRT market total TVL",           fmtLarge(gp["lrt_total_tvl"] as number)],
      ["MS vs all liquid staking",       pct(gp["ms30_vs_all_staking"] as number)],
      ["Staking TVL",                    fmtLarge(gp["stake_tvl"] as number)],
    ] as [string, string][]).filter(([, v]) => v && v !== "$0" && v !== "NaN×"),
  },
};

function MarketShareSection({ data, tokenKey }: { data: ValuationData; tokenKey: string }) {
  const gp = data.current_gp;

  // ── UNI: share history + snapshot layout ─────────────────────────────────
  if (tokenKey === "uni") {
    const bsHistory = data.hist_charts?.binance_spot_eoy3_ms ?? [];
    const startPt   = bsHistory[0];
    const spot      = data.market.spot;
    const mcap      = data.market.market_cap;
    const freshness = data.data_freshness ?? "";
    const tr = (label: string, col1: string, col2: string, col3: string) => (
      <tr key={label} className="border-b border-gray-100 last:border-0">
        <td className="py-3 text-sm text-gray-600 pr-3 w-48">{label}</td>
        <td className="py-3 text-sm font-mono text-gray-700 text-right pr-6 whitespace-nowrap">{col1}</td>
        <td className="py-3 text-sm font-mono font-semibold text-gray-900 text-right pr-6 whitespace-nowrap">{col2}</td>
        <td className="py-3 text-sm font-mono text-gray-700 text-right whitespace-nowrap">{col3}</td>
      </tr>
    );
    const snapshotRow = (label: string, value: string) => (
      <tr key={label} className="border-b border-gray-100 last:border-0">
        <td className="py-3 text-sm text-gray-600 pr-3">{label}</td>
        <td className="py-3 text-sm font-mono font-semibold text-gray-900 text-right whitespace-nowrap">{value}</td>
      </tr>
    );
    const takeFull   = gp["take_bps_full"]     as number ?? 0;
    const takeCurr   = gp["take_bps_current"]  as number ?? 0;
    const lpFee30    = gp["lp_fee_bps_30d"]    as number ?? 0;
    const lpFee12m   = gp["trailing12_lp_fee_bps"] as number ?? 0;
    const frontendBps = Math.max(0, takeFull - 0.25 * lpFee30);
    const circ       = data.market.circulating_supply;
    const maxSup     = data.market.max_supply;
    const reserved   = gp["reserved_supply"]              as number ?? 0;
    const annRelease = gp["annual_reserved_supply_release"] as number ?? 0;
    const y3Release  = gp["y3_reserved_supply_release"]   as number ?? 0;
    const y3EffSup   = gp["y3_effective_supply"]          as number ?? 0;
    const primary    = data.scenarios.find((s) => s.is_primary) ?? data.scenarios[0];
    const prob3x     = primary.prob_3x ?? 0;
    const dr         = data.model.discount_rate;
    const mult       = data.model.multiple;

    return (
      <div className="space-y-5">
        {/* ── Section 1: Share history + snapshot ──────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          <div className="lg:col-span-2 bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
            <h3 className="text-2xl font-bold text-gray-900 mb-5">UNI / Binance spot share history</h3>
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left pb-2 text-xs font-medium text-gray-400 uppercase tracking-wider w-48">Point</th>
                  <th className="text-right pb-2 text-xs font-medium text-gray-400 uppercase tracking-wider pr-6">Date</th>
                  <th className="text-right pb-2 text-xs font-medium text-gray-400 uppercase tracking-wider pr-6">MS30</th>
                  <th className="text-right pb-2 text-xs font-medium text-gray-400 uppercase tracking-wider">MS90</th>
                </tr>
              </thead>
              <tbody>
                {startPt && tr("Start of long series", startPt.date, pct(startPt.ms30), startPt.ms90 ? pct(startPt.ms90) : "—")}
                {tr("Current", freshness, pct(gp["ms30_vs_binance_spot"] as number), pct(gp["ms90_vs_binance_spot"] as number))}
                {tr("Current spot reference", fmtPrice(spot), `P/S ${((gp["mcap_current_state_gp"] as number) ?? 0).toFixed(1)}x`, `P/GP ${((gp["mcap_full_activation_gp"] as number) ?? 0).toFixed(1)}x`)}
                {tr("Model terminal", "EOY3", pct(gp["binance_spot_eoy3_share_model"] as number), `seed ${pct(gp["ms90_vs_binance_spot"] as number)}`)}
              </tbody>
            </table>
            <p className="text-xs text-gray-500 mt-4 leading-relaxed">
              Long-run rolling Uniswap volume divided by BTCUSDT-scaled Binance spot volume, shown from 2022-present. Binance spot is calibrated to Blockworks annual Binance spot totals; current-year daily values use the latest calibrated BTCUSDT share.
            </p>
          </div>
          <div className="flex flex-col gap-5">
            <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-5">
              <div className="text-xs font-mono text-gray-500 mb-3 tracking-wide">Primary Binance spot snapshot</div>
              <table className="w-full"><tbody>
                {snapshotRow("MS30 vs Binance spot",    pct(gp["ms30_vs_binance_spot"]  as number))}
                {snapshotRow("MS90 vs Binance spot",    pct(gp["ms90_vs_binance_spot"]  as number))}
                {snapshotRow("MS180 vs Binance spot",   pct(gp["ms180_vs_binance_spot"] as number))}
                {snapshotRow("Raw blended velocity",    `${((gp["binance_spot_momentum_initial"] as number) ?? 0).toFixed(2)}×`)}
                {snapshotRow("Latest 30D Binance spot", fmtLarge(gp["latest30_binance_spot_volume"] as number))}
              </tbody></table>
            </div>
            <div className="bg-[#0a0c14] rounded-xl border border-[#2d3144] p-5 flex flex-col flex-1">
              <div className="text-xs font-mono text-gray-500 mb-1 tracking-wide">Model pivot</div>
              <div className="text-lg font-bold text-white mb-3 leading-snug">Binance spot is primary; total DEX is sensitivity</div>
              <p className="text-sm text-gray-400 leading-relaxed">
                The total-DEX version remains in the scenario table so we can compare protocol-native share versus the HYPE-like CEX denominator.
              </p>
            </div>
          </div>
        </div>

        {/* ── Section 2: Model assumptions + Supply treatment ──────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
            <h3 className="text-2xl font-bold text-gray-900 mb-5">Model assumptions</h3>
            <pre className="text-xs font-mono text-gray-600 bg-white border border-[#e2e6f0] rounded-lg p-4 leading-relaxed whitespace-pre-wrap">{`binance_spot_volume_t = sampled 2022-present Binance spot month × bootstrapped Binance spot growth
uni_volume_t = binance_spot_volume_t × UNI/Binance spot share_t
full_activation_GP_t = uni_volume_t × ${takeFull.toFixed(2)}bps
PV/token = Year-3 TTM GP × ${mult}× / effective Y3 supply / (1 + DR)^3`}</pre>
            <p className="text-xs text-gray-500 mt-4 leading-relaxed">
              Frontend fee is treated as captured by token under the token-alignment proposal. Total DEX and max-supply cases remain sensitivities.
            </p>
          </div>
          <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
            <h3 className="text-2xl font-bold text-gray-900 mb-5">Supply treatment</h3>
            <table className="w-full"><tbody>
              {snapshotRow("Current circulating supply",      `${(circ / 1e6).toFixed(0)}M`)}
              {snapshotRow("Max supply",                      `${(maxSup / 1e6).toFixed(0)}M`)}
              {snapshotRow("Reserved supply",                 `${(reserved / 1e6).toFixed(0)}M`)}
              {snapshotRow("Observed annual reserved release",`${(annRelease / 1e6).toFixed(0)}M`)}
              {snapshotRow("Modeled 3Y reserved release",     `${(y3Release / 1e6).toFixed(0)}M`)}
              {snapshotRow("Effective Y3 supply",             `${(y3EffSup / 1e6).toFixed(0)}M`)}
            </tbody></table>
            <p className="text-xs text-gray-500 mt-4 leading-relaxed">
              Release is inferred from 365D CoinGecko circulating supply movement, capped at remaining reserved supply.
            </p>
          </div>
        </div>

        {/* ── Section 3: Take-rate assumptions + 3× probability ────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          <div className="lg:col-span-2 bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
            <h3 className="text-2xl font-bold text-gray-900 mb-5">Take-rate assumptions</h3>
            <table className="w-full"><tbody>
              {snapshotRow("LP fee bps, recent 30D",   `${lpFee30.toFixed(2)}bps`)}
              {snapshotRow("LP fee bps, trailing 12M", `${lpFee12m.toFixed(2)}bps`)}
              {snapshotRow("Current protocol take",    `${takeCurr.toFixed(2)}bps`)}
              {snapshotRow("Full-activation take",     `${takeFull.toFixed(2)}bps`)}
              {snapshotRow("Frontend fee assumption",  `${frontendBps.toFixed(2)}bps`)}
            </tbody></table>
            <p className="text-xs text-gray-500 mt-4 leading-relaxed">
              Full activation = 25% of observed LP fees plus the token-captured frontend fee assumption. The fee line uses the recent 30D LP fee rate; the backtest uses a no-lookahead rule that takes the lower of rolling 30D and trailing 12M LP fee bps at each historical date.
            </p>
          </div>
          <div className="bg-[#0a0c14] rounded-xl border border-[#2d3144] p-5 flex flex-col">
            <div className="text-xs font-mono text-gray-500 mb-1 tracking-wide">3× probability interpretation</div>
            <div className="text-lg font-bold text-white mb-3 leading-snug">
              {pct(prob3x)} is a right-tail metric, not the base case
            </div>
            <p className="text-sm text-gray-400 leading-relaxed">
              The selected-model P50 PV is only {fmtPrice(primary.pv.p50)}. The 3× probability comes from high Binance-volume historical regimes in the Monte Carlo tail, so it should be read as asymmetric upside probability rather than central-case conviction.
            </p>
          </div>
        </div>

        {/* ── Section 4: Current-model backtest ────────────────────────── */}
        {(() => {
          const bbt = data.hist_charts?.binance_spot_backtest;
          if (!bbt || !bbt.chart?.length) return null;
          const btChart   = bbt.chart;
          const btSignals = bbt.signals ?? {};
          const fmtRet = (v: number | null) => v == null ? "n/a" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
          const step    = Math.max(1, Math.floor(btChart.length / 180));
          const sampled = btChart.filter((_, i) => i % step === 0);
          const ticks   = sampled
            .filter((_, i) => i % Math.floor(Math.max(sampled.length / 5, 1)) === 0)
            .map(r => r.date);
          const allPvs  = sampled.map(r => r.pv).filter(Boolean);
          const pvMin   = allPvs.length ? Math.min(...allPvs) : 0;
          const pvMax   = allPvs.length ? Math.max(...allPvs) : 10;
          const yDomain: [number, number] = [Math.max(0, pvMin * 0.9), pvMax * 1.05];
          const sigColor: Record<string, string> = { GOOD: "#16a34a", NEUTRAL: "#ca8a04", BAD: "#dc2626" };
          return (
            <div className="space-y-4">
              {/* top: 2-col description + table */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
                <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
                  <h3 className="text-2xl font-bold text-gray-900 mb-4">Current-model backtest</h3>
                  <p className="text-sm text-gray-600 leading-relaxed">
                    Binance spot primary diagnostic, not the old DEX-native replay. Latest signal:{" "}
                    <span className="font-bold" style={{ color: sigColor[bbt.latest_signal] ?? "#374151" }}>
                      {bbt.latest_signal}
                    </span>
                    {bbt.last_realized_row && (
                      <>; last realized-return row: <span className="font-bold text-gray-900">{bbt.last_realized_row}</span></>
                    )}.
                  </p>
                </div>
                <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] overflow-hidden">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-[#e2e6f0]">
                        {["SIGNAL", "OBS", "AVG +30D", "AVG +90D", "RECENT DATES"].map(h => (
                          <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {["GOOD", "NEUTRAL", "BAD"].map(sig => {
                        const s = btSignals[sig];
                        if (!s) return null;
                        return (
                          <tr key={sig} className="border-b border-[#e2e6f0] last:border-0">
                            <td className="px-4 py-3 font-semibold text-xs" style={{ color: sigColor[sig] }}>{sig}</td>
                            <td className="px-4 py-3 font-mono text-gray-700">{s.obs}</td>
                            <td className="px-4 py-3 font-mono text-gray-700">{fmtRet(s.avg_30d)}</td>
                            <td className="px-4 py-3 font-mono text-gray-700">{fmtRet(s.avg_90d)}</td>
                            <td className="px-4 py-3 text-xs text-gray-500">{s.recent_dates?.slice(0,3).join(", ")}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
              {/* bottom: chart */}
              <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
                <div className="flex items-center justify-between mb-1">
                  <h4 className="text-base font-bold text-gray-900">Spot vs current-model PV proxy</h4>
                  <span className="text-xs font-mono text-gray-500">black=spot · blue=Binance-current PV proxy</span>
                </div>
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={sampled} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e6f0" vertical={false} />
                    <XAxis dataKey="date" ticks={ticks} tick={{ fontSize: 11, fill: "#9ca3af" }} axisLine={false} tickLine={false} />
                    <YAxis domain={yDomain} tickFormatter={v => `$${v.toFixed(2)}`} tick={{ fontSize: 11, fill: "#9ca3af" }} axisLine={false} tickLine={false} width={55} />
                    <Tooltip
                      formatter={(v: number, name: string) => [`$${v.toFixed(3)}`, name === "spot" ? "Spot" : "PV proxy"]}
                      labelFormatter={(l: string) => l}
                      contentStyle={{ background: "#fff", border: "1px solid #e2e6f0", borderRadius: 8, fontSize: 12 }}
                    />
                    <Line dataKey="spot" stroke="#111827" strokeWidth={1.5} dot={false} connectNulls />
                    <Line dataKey="pv"   stroke="#2563eb" strokeWidth={1.5} dot={false} connectNulls />
                  </LineChart>
                </ResponsiveContainer>
                <p className="text-xs text-gray-500 mt-3 leading-relaxed">
                  PV proxy = rolling Binance spot denominator × historical UNI/Binance terminal share × no-lookahead full-activation take rate × {mult}× / effective Y3 supply / DR³, normalized to the current selected-model P50. Current spot {fmtPrice(spot)} is the horizontal comparison reference for the selected model. This is the explicit checklist backtest for the selected model.
                </p>
              </div>
            </div>
          );
        })()}
      </div>
    );
  }

  // ── SKY: architecture + snapshot layout ──────────────────────────────────
  if (tokenKey === "sky") {
    const mc = gp["mc_path"] as unknown as {
      start_money_market_tvl_p50: number;
      current_money_market_tvl: number;
      y3_avg_money_market_tvl_p50: number;
    };
    const startP50   = mc?.start_money_market_tvl_p50 ?? 0;
    const currentDen = mc?.current_money_market_tvl   ?? (gp["money_market_tvl"] as number ?? 0);
    const y3AvgDen   = mc?.y3_avg_money_market_tvl_p50 ?? (gp["y3_avg_money_market_tvl_p50"] as number ?? 0);
    const y3VsCurr   = gp["y3_money_market_tvl_change_vs_current"] as number ?? 0;
    const ms7ms30    = gp["ms7_ms30_trend"] as number ?? 0;
    const mult       = data.model.multiple;
    const dr         = (data.model.discount_rate * 100).toFixed(0);

    const sRow = (label: string, value: string) => (
      <tr key={label} className="border-b border-gray-100 last:border-0">
        <td className="py-3 text-sm text-gray-600 pr-4">{label}</td>
        <td className="py-3 text-sm font-mono font-semibold text-gray-900 text-right whitespace-nowrap">{value}</td>
      </tr>
    );

    const y3GpChg     = gp["y3_gp_change_vs_current"]               as number ?? 0;
    const y3TotalSup  = gp["y3_total_stable_supply_p50"]            as number ?? 0;
    const y3TotalChg  = gp["y3_total_stable_supply_change_vs_current"] as number ?? 0;
    const y3Usds      = gp["y3_usds_supply_p50"]                    as number ?? 0;
    const y3UsdsChg   = gp["y3_usds_supply_change_vs_current"]      as number ?? 0;
    const circulSupply = data.market.circulating_supply;
    const maxSupply    = data.market.max_supply;
    const fmtChg = (v: number) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;

    return (
      <div className="space-y-5">
        {/* Row 1: architecture + snapshot */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
            <h3 className="text-2xl font-bold text-gray-900 mb-5">Money-market share architecture</h3>
            <pre className="text-xs font-mono text-gray-600 bg-white border border-[#e2e6f0] rounded-lg p-4 leading-relaxed whitespace-pre-wrap">{`money_market_tvl_start = uniform historical monthly draw
money_market_tvl_t = money_market_tvl_start × sampled monthly return path
share_t = MS90 × decayed_velocity_ensemble_t
Sky_supply_t = money_market_tvl_t × share_t
USDS_t = max(Sky_supply_t - flat_DAI, 0)
GP_t = Sky_supply_t × net_GP_take_rate
NP_t = GP_t - OPEX
PV/token = Year-3 TTM NP × ${mult}x / SKY supply / (1 + ${dr}%)^3`}</pre>
            <p className="text-xs text-gray-500 mt-4 leading-relaxed">
              The MC path is denominator × share: starting money-market TVL is a uniform historical monthly draw with P50 {fmtLarge(startP50)}, not fixed at the current {fmtLarge(currentDen)} denominator. Current short leg MS7/MS30 is {ms7ms30.toFixed(2)}×, so it contributes no positive acceleration right now.
            </p>
          </div>
          <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
            <h3 className="text-2xl font-bold text-gray-900 mb-5">Current snapshot</h3>
            <table className="w-full"><tbody>
              {sRow("MS7 vs money markets",    pct(gp["ms7_vs_money_market"]  as number))}
              {sRow("MS30 vs money markets",   pct(gp["ms30_vs_money_market"] as number))}
              {sRow("MS90 valuation seed",     pct(gp["ms90_vs_money_market"] as number))}
              {sRow("MS180 vs money markets",  pct(gp["ms180_vs_money_market"] as number))}
              {sRow("MS30/MS180 trend",        `${(gp["ms30_ms180_trend"] as number ?? 0).toFixed(2)}×`)}
              {sRow("MS7/MS30 trend",          `${ms7ms30.toFixed(2)}×`)}
              {sRow("Current denominator",     fmtLarge(currentDen))}
              {sRow("Start denominator P50",   fmtLarge(startP50))}
              {sRow("Y3 avg denominator P50",  fmtLarge(y3AvgDen))}
              {sRow("Y3 denominator vs current", fmtChg(y3VsCurr))}
            </tbody></table>
          </div>
        </div>

        {/* Row 2: take-rate + supply mechanics */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
            <h3 className="text-2xl font-bold text-gray-900 mb-5">Take-rate assumptions</h3>
            <table className="w-full"><tbody>
              {sRow("Gross income take-rate", `${((gp["gross_income_take_rate_bps"] as number) ?? 0).toFixed(1)} bps`)}
              {sRow("Savings cost rate",      `${((gp["savings_cost_rate_bps"]      as number) ?? 0).toFixed(1)} bps`)}
              {sRow("stUSDS cost rate",       `${((gp["stusds_cost_rate_bps"]       as number) ?? 0).toFixed(1)} bps`)}
              {sRow("Net GP take-rate",       `${((gp["net_gp_take_rate_bps"]       as number) ?? 0).toFixed(1)} bps`)}
              {sRow("Current GP annualized",  fmtLarge(gp["current_gp"] as number))}
              {sRow("Y3 GP P50 / change",     `${fmtLarge(gp["y3_gp_p50"] as number)} / ${fmtChg(y3GpChg)}`)}
            </tbody></table>
            <p className="text-xs text-gray-500 mt-4 leading-relaxed">
              For SKY, take-rate means stablecoin economics rate on modeled Sky supply, not a perps fee rate.
            </p>
          </div>
          <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
            <h3 className="text-2xl font-bold text-gray-900 mb-5">Supply and token mechanics</h3>
            <table className="w-full"><tbody>
              {sRow("Official USDS supply",      fmtLarge(gp["usds_supply"] as number))}
              {sRow("Official DAI supply",       fmtLarge(gp["dai_supply"]  as number))}
              {sRow("SKY circulating / max supply", `${(circulSupply / 1e9).toFixed(2)}B / ${(maxSupply / 1e9).toFixed(2)}B`)}
              {sRow("Buybacks / burns modeled",  "None")}
              {sRow("Y3 total supply / change",  `${fmtLarge(y3TotalSup)} / ${fmtChg(y3TotalChg)}`)}
              {sRow("Y3 USDS / change",          `${fmtLarge(y3Usds)} / ${fmtChg(y3UsdsChg)}`)}
            </tbody></table>
            <p className="text-xs text-gray-500 mt-4 leading-relaxed">
              No SKY supply reduction is modeled; treasury cash accumulates from positive NP.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // ── CARDS: operating bridge + velocity treatment ────────────────────────
  if (tokenKey === "cards") {
    const primarySc   = data.scenarios.find((s) => s.is_primary) ?? data.scenarios[0];
    const fdv         = data.market.fdv;
    const spot        = data.market.spot;
    const floatVal    = (primarySc.y3_supply_p50 ?? 0) * spot;
    const rev30d      = gp["revenue_30d"]      as number ?? 0;
    const netSpread   = gp["net_spread"]        as number ?? 0;
    const gpConv      = gp["true_gp_conversion"] as number ?? 0;
    const revAnn      = rev30d * 365 / 30;
    const gpProxyAnn  = revAnn * gpConv;
    const gmv30d      = gp["gmv_30d"]           as number ?? 0;
    const gmv30dAnn   = gp["gmv_30d_ann"]       as number ?? 0;
    const gmv7dDaily  = gp["gmv_7d_daily_avg"]  as number ?? 0;
    const gmv30dDaily = gp["gmv_30d_daily_avg"] as number ?? gmv30d / 30;
    const velocity    = gp["gmv_velocity_input"] as number ?? 0;
    const y3Gmv       = gp["y3_gmv_base"]        as number ?? 0;

    const sRow = (label: string, value: string, mono = true) => (
      <tr key={label} className="border-b border-gray-100 last:border-0">
        <td className="py-3 text-sm text-gray-600 pr-4">{label}</td>
        <td className={`py-3 text-sm text-gray-900 text-right whitespace-nowrap ${mono ? "font-mono font-semibold" : ""}`}>{value}</td>
      </tr>
    );

    const revHistory = data.hist_charts?.revenue_history ?? [];
    const runRateRaw = data.hist_charts?.run_rate_chart ?? [];
    // Downsample run-rate chart to monthly (last entry per month)
    const runRateMonthly: { date: string; ann_30d_rev: number }[] = [];
    {
      const seen = new Set<string>();
      for (let i = runRateRaw.length - 1; i >= 0; i--) {
        const ym = runRateRaw[i].date.slice(0, 7);
        if (!seen.has(ym)) { seen.add(ym); runRateMonthly.unshift(runRateRaw[i]); }
      }
    }
    const fmtDailyRev = (v: number) => v >= 1e6 ? `$${(v/1e6).toFixed(2)}M` : v >= 1e3 ? `$${(v/1e3).toFixed(0)}K` : `$${v.toFixed(0)}`;
    const latestDate  = revHistory.length > 0 ? revHistory[revHistory.length - 1].date : "";

    return (
      <div className="space-y-5">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Left: Operating Bridge */}
        <div className="bg-white rounded-xl border border-gray-200 p-8">
          <h3 className="text-3xl font-bold text-gray-900 mb-6">Operating Bridge</h3>
          <table className="w-full"><tbody>
            {sRow("30D Gacha GMV",              fmtLarge(gmv30d))}
            {sRow("Annualized Gacha GMV",       fmtLarge(gmv30dAnn))}
            {sRow("DefiLlama 30D net revenue",  fmtLarge(rev30d))}
            {sRow("Annualized net revenue",     fmtLarge(revAnn))}
            {sRow("Net revenue spread",         `${(netSpread * 100).toFixed(2)}%`)}
            {sRow("Base GP conversion",         `${(gpConv * 100).toFixed(1)}%`)}
            {sRow("Base current GP proxy",      fmtLarge(gpProxyAnn))}
            {sRow("P/GP: float value / GP proxy", gpProxyAnn > 0 ? `${(floatVal / gpProxyAnn).toFixed(1)}x` : "—")}
            {sRow("P/GP: FDV / GP proxy",       gpProxyAnn > 0 ? `${(fdv / gpProxyAnn).toFixed(1)}x` : "—")}
          </tbody></table>
        </div>
        {/* Right: Velocity Treatment */}
        <div className="bg-white rounded-xl border border-gray-200 p-8">
          <h3 className="text-3xl font-bold text-gray-900 mb-6">Velocity Treatment</h3>
          <table className="w-full"><tbody>
            {sRow("Reported inventory velocity",  "n/a")}
            {sRow("Latest 7D avg GMV",            `${fmtLarge(gmv7dDaily)}/day`)}
            {sRow("Prior 30D avg GMV",            `${fmtLarge(gmv30dDaily)}/day`)}
            {sRow("Capped 7D/30D GMV signal",     `${(velocity * 100).toFixed(1)}%/mo`)}
            {sRow("Modeled GMV velocity alpha",   `${(velocity * 100).toFixed(1)}%/mo`)}
            {sRow("Decay schedule",               "Linear to 0 by M12", false)}
            {sRow("Scenario weights",             "40% / 40% / 20%")}
            {sRow("Y3 GMV base case",             fmtLarge(y3Gmv))}
            {sRow("Missing unit-econ data",       "COGS/OPEX", false)}
          </tbody></table>
        </div>
      </div>

      {/* Row 2: Net revenue history + Run-rate chart */}
      {revHistory.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {/* Left: Net revenue history table */}
          <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
            <h3 className="text-2xl font-bold text-gray-900 mb-5">Net revenue history</h3>
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-200">
                  {["DATE","DAILY REV","30D ANN. REV","FDV / REV"].map((h) => (
                    <th key={h} className={`pb-2 text-xs font-medium text-gray-400 uppercase tracking-wider ${h === "DATE" ? "text-left" : "text-right"}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {revHistory.map((r) => (
                  <tr key={r.date} className="border-b border-gray-100 last:border-0">
                    <td className="py-3 text-sm text-gray-600">{r.date}</td>
                    <td className="py-3 text-sm font-mono font-semibold text-gray-900 text-right">{fmtDailyRev(r.daily_rev)}</td>
                    <td className="py-3 text-sm font-mono font-semibold text-gray-900 text-right">{fmtLarge(r.ann_30d_rev)}</td>
                    <td className="py-3 text-sm font-mono text-gray-700 text-right">{r.fdv_rev > 0 ? `${r.fdv_rev.toFixed(2)}x` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* Right: Run-rate chart */}
          <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
            <h3 className="text-2xl font-bold text-gray-900 mb-5">Run-rate chart</h3>
            <p className="text-xs text-gray-400 mb-2 text-center">30D annualized DefiLlama net revenue</p>
            <ResponsiveContainer width="100%" height={240}>
              <ComposedChart data={runRateMonthly} margin={{ top: 4, right: 8, left: 8, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                <XAxis dataKey="date" tickFormatter={(d: string) => new Date(d + "T00:00:00Z").toLocaleString("en-US", { month: "short", timeZone: "UTC" })} tick={{ fontSize: 11 }} />
                <YAxis tickFormatter={(v: number) => `$${(v/1e6).toFixed(0)}M`} tick={{ fontSize: 11 }} width={48} />
                <Tooltip formatter={(v: number) => [`$${(v/1e6).toFixed(1)}M`, "30D ann. rev"]} labelFormatter={(d: string) => d} />
                <Bar dataKey="ann_30d_rev" fill="#bfdbfe" radius={[2,2,0,0]} />
                <Line dataKey="ann_30d_rev" stroke="#ef4444" strokeWidth={2} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
            <p className="text-xs text-gray-500 mt-3 leading-relaxed">
              Bars show selected month-end 30D annualized revenue. The {new Date(latestDate + "T00:00:00Z").toLocaleString("en-US", { month: "long", timeZone: "UTC" })} point is through {latestDate}.
            </p>
          </div>
        </div>
      )}
      </div>
    );
  }

  // ── JUP: current snapshot + model architecture ──────────────────────────
  if (tokenKey === "jup") {
    const mcap        = data.market.market_cap;
    const totalGpAnn  = (gp["total_30d"] as number) * 12;
    const pgRatio     = totalGpAnn > 0 ? (mcap / totalGpAnn).toFixed(1) + "x" : "—";
    const caveats     = data.caveats ?? [];

    const sRow = (label: string, value: string) => (
      <tr key={label} className="border-b border-gray-100 last:border-0">
        <td className="py-3 text-sm text-gray-600 pr-4">{label}</td>
        <td className="py-3 text-sm font-mono font-semibold text-gray-900 text-right whitespace-nowrap">{value}</td>
      </tr>
    );

    return (
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Left: Current snapshot */}
        <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
          <h3 className="text-2xl font-bold text-gray-900 mb-5">Current snapshot</h3>
          <table className="w-full"><tbody>
            {sRow("Perps GP 30D",                   fmtLarge(gp["perps_30d"] as number))}
            {sRow("Perps 30D volume",               fmtLarge(gp["perps_30d_volume"] as number))}
            {sRow("Spot 30D volume",                fmtLarge(gp["spot_30d_volume"] as number))}
            {sRow("P/S: mcap / current GP proxy",   pgRatio)}
            {sRow("P/GP: mcap / current GP proxy",  pgRatio)}
            {sRow("Perps MS90 vs Binance Futures",  pct(gp["perps_ms90_vs_binance_futures"] as number))}
            {sRow("Spot MS90 vs Binance spot",      pct(gp["spot_ms90_vs_binance_spot"] as number))}
            {sRow("Perps share velocity",           `${((gp["perps_share_velocity_capped"] as number) ?? 0).toFixed(2)}×`)}
            {sRow("Spot share velocity",            `${((gp["spot_share_velocity_capped"] as number) ?? 0).toFixed(2)}×`)}
            {sRow("Sampled Binance Futures seed P50", `${fmtLarge(gp["start_binance_futures_monthly_p50"] as number)}/mo`)}
            {sRow("Sampled Binance spot seed P50",  `${fmtLarge(gp["start_binance_spot_monthly_p50"] as number)}/mo`)}
          </tbody></table>
          {caveats.length > 0 && (
            <p className="text-xs text-gray-500 mt-4 leading-relaxed">
              Binance denominators use BTCUSDT quote-volume histories scaled to Blockworks annual exchange totals. {caveats[0]}
            </p>
          )}
        </div>
        {/* Right: Model architecture (dark) */}
        <div className="bg-[#0a0c14] rounded-xl border border-[#2d3144] p-6 flex flex-col">
          <div className="text-xs font-mono text-gray-500 mb-2 tracking-wide">Model architecture</div>
          <div className="text-xl font-bold text-white mb-4">Perps like HYPE; spot like UNI</div>
          <p className="text-sm text-gray-400 leading-relaxed">{data.model.note}</p>
        </div>
      </div>
    );
  }

  // ── ETHFI: two-column layout ─────────────────────────────────────────────
  if (tokenKey === "ethfi") {
    const vel = gp["card_velocity_ensemble"] as unknown as {
      raw_30d_mom: number; velocity_30_180: number; velocity_7_30: number;
      capped_30_180: number; capped_7_30: number;
    };
    const mcap = data.market.market_cap;
    const totalGp = gp["total_annualized"] as number;
    const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`;
    const tableRow = (label: string, value: string) => (
      <tr key={label} className="border-b border-gray-100 last:border-0">
        <td className="py-3 text-sm text-gray-600 pr-3">{label}</td>
        <td className="py-3 text-sm font-mono font-semibold text-gray-900 text-right whitespace-nowrap">{value}</td>
      </tr>
    );
    return (
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
          <h3 className="text-2xl font-bold text-gray-900 mb-5">Velocity Components</h3>
          <table className="w-full"><tbody>
            {tableRow("Raw 30D MoM",               fmtPct(vel?.raw_30d_mom ?? 0))}
            {tableRow("30D/180D monthly-equivalent", fmtPct(vel?.velocity_30_180 ?? 0))}
            {tableRow("7D/30D monthly-equivalent",  fmtPct(vel?.velocity_7_30 ?? 0))}
            {tableRow("Capped 30D/180D",            fmtPct(vel?.capped_30_180 ?? 0))}
            {tableRow("Capped 7D/30D",              fmtPct(vel?.capped_7_30 ?? 0))}
            {(gp["opex_annual"] as number) > 0 && tableRow("OPEX", `${fmtLarge(gp["opex_annual"] as number)}/yr`)}
          </tbody></table>
        </div>
        <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
          <h3 className="text-2xl font-bold text-gray-900 mb-5">Current GP Composition</h3>
          <table className="w-full"><tbody>
            {tableRow("Card GP ann.",              fmtLarge(gp["card_annualized"] as number))}
            {tableRow("Staking GP ann.",           fmtLarge(gp["staking_annualized"] as number))}
            {tableRow("Vault GP ann.",             fmtLarge(gp["vault_annualized"] as number))}
            {tableRow("Total GP ann.",             fmtLarge(totalGp))}
            {tableRow("P/S: mcap / total GP proxy", totalGp > 0 ? `${(mcap / totalGp).toFixed(1)}x` : "—")}
            {tableRow("P/GP: mcap / total GP",     totalGp > 0 ? `${(mcap / totalGp).toFixed(1)}x` : "—")}
            {tableRow("Y3 card GMV P50",           fmtLarge(gp["y3_card_gdv_ann_p50"] as number))}
            {tableRow("Y3 stake TVL P50",          fmtLarge(gp["y3_stake_tvl_p50"] as number))}
          </tbody></table>
        </div>
      </div>
    );
  }

  // ── Generic path (HYPE / LIGHTER / UNI / JUP / SKY / ETHFI) ─────────────
  const cfg = MS_CONFIG[tokenKey];
  if (!cfg) return null;
  const tableRows = cfg.tableRows(gp, data);
  if (!tableRows.length) return null;

  return (
    <div className="space-y-5">
      {/* ── Current Data + Core revenue drivers ─────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Current Data table (light card) */}
        <div className="lg:col-span-2 bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
          <h3 className="text-2xl font-bold text-gray-900 mb-5">Current Data</h3>
          <table className="w-full">
            <tbody>
              {tableRows.map(([label, value]) => (
                <tr key={label} className="border-b border-gray-100 last:border-0">
                  <td className="py-3 text-sm text-gray-600 pr-3">{label}</td>
                  <td className="py-3 text-sm font-mono font-semibold text-gray-900 text-right whitespace-nowrap">{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Core revenue drivers / Caveat (dark card) */}
        <div className="bg-[#0a0c14] rounded-xl border border-[#2d3144] p-5 flex flex-col">
          <div className="text-xs font-mono text-gray-500 mb-1 tracking-wide">{cfg.driversLabel ?? "Core revenue drivers"}</div>
          <div className="text-xl font-bold text-white mb-3">{cfg.driversTitle}</div>
          {tokenKey === "hype" && (
            <p className="text-sm text-gray-400 leading-relaxed">
              HL vol × Binance market share × 0.026% clean treasury take-rate + USDC yield; MS30/MS90 momentum decays over 12 months; 4 supply/emission scenarios
            </p>
          )}
          {tokenKey === "lighter" && (
            <p className="text-sm text-gray-400 leading-relaxed">
              Lighter paid derivatives history is short; historical diagnostics use daily price and trailing 30D revenue where available. Market-share trend uses rolling-window snapshots (30D/90D/180D) against Binance Futures, not a full daily share history.
            </p>
          )}
          {tokenKey === "uni" && (
            <p className="text-sm text-gray-400 leading-relaxed">
              UNI revenue = LP fees × protocol take-rate. Current state: ~0.83bps LP protocol share + 0.30bps frontend. Full activation: 25% of LP fees + 0.30bps frontend. Market share trend shows UNI's share of total DEX volume across all on-chain protocols (DefiLlama).
            </p>
          )}
          {tokenKey === "ethfi" && (
            <p className="text-sm text-gray-400 leading-relaxed">
              ether.fi GP = Card GDV × 135bps take × margin + staking TVL × ETH APY × 5% + vault TVL × 1%. Market share trend shows ether.fi's rolling TVL share of the liquid restaking market (vs Kelp, Renzo, Puffer, Swell).
            </p>
          )}
          {tokenKey === "jup" && (
            <p className="text-sm text-gray-400 leading-relaxed">
              JUP perps GP = Binance Futures volume × JUP/Binance perps share × clean take-rate. Spot GP = Binance spot volume × JUP/Binance spot share × observed aggregator/Jupiterz rake.
            </p>
          )}
          {tokenKey === "sky" && (
            <p className="text-sm text-gray-400 leading-relaxed">
              Sky GP = modeled Sky supply × net GP take-rate. The MC path samples a starting broad money-market / yield-vault TVL, applies Sky&apos;s MS90 share seed, then decays a 70% MS30/MS180 + 30% MS7/MS30 velocity ensemble over 12 months.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function UniBinanceSpotShareSection({ data }: { data: ValuationData }) {
  const history = (data as unknown as { binance_spot_ms_history?: MsPoint[] }).binance_spot_ms_history ?? [];
  const eoy3 = (data.hist_charts as unknown as { binance_spot_eoy3_ms?: Array<MsPoint & { eoy3?: number }> } | undefined)?.binance_spot_eoy3_ms ?? [];
  if (!history.length) return null;

  const eoy3ByDate = new Map(eoy3.map((row) => [row.date, row.eoy3 ?? null]));
  const chart = history.map((row) => ({ ...row, eoy3: eoy3ByDate.get(row.date) ?? null }));
  const step = Math.max(1, Math.floor(chart.length / 6));
  const ticks = chart.filter((_, i) => i % step === 0 || i === chart.length - 1).map((d) => d.date);
  const vals = chart.flatMap((d) => [d.ms30, d.ms90, d.eoy3]).filter((v): v is number => v != null);
  const yMin = Math.max(0, Math.min(...vals) - 0.01);
  const yMax = Math.min(0.70, Math.max(...vals) + 0.01);
  const latest = chart[chart.length - 1];
  const gp = data.current_gp;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
      <div className="lg:col-span-3 bg-[#1a1d29] rounded-xl border border-[#2d3144] p-6">
        <h3 className="text-xl font-bold text-white mb-5">UNI / Binance Spot Share Dynamics</h3>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chart} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" vertical={false} />
            <XAxis
              dataKey="date"
              ticks={ticks}
              tickFormatter={(d: string) => { const [, m, day] = d.split("-"); return `${parseInt(m)}/${parseInt(day)}`; }}
              tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false}
            />
            <YAxis
              domain={[yMin, yMax]}
              tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
              tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} width={36}
            />
            <Tooltip
              contentStyle={{ background: "#1a1d29", border: "1px solid #2d3144", borderRadius: 8, fontSize: 11 }}
              labelStyle={{ color: "#9ca3af", marginBottom: 2 }}
              formatter={(v: number, name: string) => [
                `${(v * 100).toFixed(2)}%`,
                name === "ms30" ? "MS30" : name === "ms90" ? "MS90" : "EOY3 model",
              ]}
            />
            <Line type="monotone" dataKey="eoy3" stroke="#60a5fa" strokeWidth={2} dot={false} connectNulls />
            <Line type="monotone" dataKey="ms90" stroke="#6b7280" strokeWidth={1.5} dot={false} connectNulls />
            <Line type="monotone" dataKey="ms30" stroke="#e5e7eb" strokeWidth={1.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
        <p className="text-xs text-gray-600 mt-4 leading-relaxed">
          Rolling Uniswap volume divided by BTCUSDT-scaled Binance spot volume. This is the primary UNI denominator. Binance spot is calibrated to Blockworks annual Binance spot totals; current-year daily values use the latest calibrated BTCUSDT share.
        </p>
      </div>
      <div className="lg:col-span-2 bg-[#1a1d29] rounded-xl border border-[#2d3144] p-5">
        <div className="text-xs font-mono text-gray-500 mb-4 tracking-wide">Binance spot snapshot</div>
        <table className="w-full">
          <tbody>
            {[
              ["MS30 vs Binance spot", latest?.ms30 != null ? pct(latest.ms30) : "—"],
              ["MS90 vs Binance spot", latest?.ms90 != null ? pct(latest.ms90) : "—"],
              ["EOY3 modeled share", latest?.eoy3 != null ? pct(latest.eoy3) : "—"],
              ["MS30/MS180 trend", gp["ms30_ms180_binance_spot_trend"] != null ? `${(gp["ms30_ms180_binance_spot_trend"] as number).toFixed(2)}×` : "—"],
              ["Start Binance spot P50", fmtLarge(gp["start_binance_spot_monthly_p50"] as number)],
              ["P50 PV sensitivity", fmtPrice(gp["binance_spot_full_activation_p50"] as number)],
            ].map(([label, value]) => (
              <tr key={label} className="border-b border-[#252836] last:border-0">
                <td className="py-2.5 text-sm text-gray-400 pr-3">{label}</td>
                <td className="py-2.5 text-sm font-mono font-semibold text-gray-200 text-right whitespace-nowrap">{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-xs text-gray-600 mt-4 leading-relaxed">
          This is the HYPE-like primary lens: Binance spot denominator × UNI/Binance spot share. The DEX-native chart above remains a protocol-market sensitivity.
        </p>
      </div>
    </div>
  );
}

// ── Tech score helpers ───────────────────────────────────────────────────────

const TECH_DASH_BASE = "https://crypto-tech-dashboard-2nd-try-v2-0.vercel.app";

const TOKEN_CG_ID: Record<string, string> = {
  hype:    "hyperliquid",
  uni:     "uniswap",
  ethfi:   "ether-fi",
  jup:     "jupiter-exchange-solana",
  lighter: "lighter",
  sky:     "sky",
  vvv:     "venice-token",
};

function techGrade(score: number): { letter: string; color: string; bg: string } {
  if (score >= 80) return { letter: "A",  color: "#4ade80", bg: "rgba(74,222,128,0.12)" };
  if (score >= 65) return { letter: "B+", color: "#86efac", bg: "rgba(134,239,172,0.10)" };
  if (score >= 55) return { letter: "B",  color: "#fbbf24", bg: "rgba(251,191,36,0.10)" };
  if (score >= 45) return { letter: "C+", color: "#fb923c", bg: "rgba(251,146,60,0.10)" };
  if (score >= 35) return { letter: "C",  color: "#f87171", bg: "rgba(248,113,113,0.10)" };
  return               { letter: "D",  color: "#ef4444", bg: "rgba(239,68,68,0.10)" };
}

// ── TechScoreCard ────────────────────────────────────────────────────────────

function TechScoreCard({ tokenKey }: { tokenKey: string }) {
  const cgId = TOKEN_CG_ID[tokenKey];
  const [score, setScore] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!cgId) { setLoading(false); return; }
    let cancelled = false;
    fetch(`${TECH_DASH_BASE}/api/scores/${cgId}`)
      .then(r => r.json())
      .then(data => {
        if (!cancelled) {
          setScore(data?.score?.overall_score ?? null);
          setLoading(false);
        }
      })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [cgId]);

  if (!cgId) return null;

  const grade = score !== null ? techGrade(score) : null;

  return (
    <div
      className="rounded-xl border px-5 py-4 flex items-center gap-5"
      style={{ background: grade ? grade.bg : "#1a1d29", borderColor: grade ? grade.color + "55" : "#2d3144" }}
    >
      <div>
        <div className="text-xs text-gray-500 mb-1">Technical Score</div>
        {loading ? (
          <div className="text-lg font-bold text-gray-600">—</div>
        ) : score !== null ? (
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-black font-mono" style={{ color: grade!.color }}>
              {grade!.letter}
            </span>
            <span className="text-lg font-bold font-mono text-gray-700">{score.toFixed(0)}</span>
            <span className="text-xs text-gray-500">/ 100</span>
          </div>
        ) : (
          <div className="text-sm text-gray-600">not tracked</div>
        )}
      </div>
      <div className="text-xs text-gray-600 leading-relaxed max-w-xs">
        Composite of Trend (40%), Reversal (25%), Breadth (15%), Risk (10%) + TS percentiles.{" "}
        <a
          href={`/crypto-tech#token=${cgId}`}
          className="text-blue-400 hover:text-blue-300 underline"
        >
          Full breakdown →
        </a>
      </div>
    </div>
  );
}

// ── TechScoreHistoryChart ────────────────────────────────────────────────────

function TechScoreHistoryChart({ tokenKey }: { tokenKey: string }) {
  const cgId = TOKEN_CG_ID[tokenKey];
  const [months, setMonths] = useState<{ month: string; score: number }[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!cgId) { setLoading(false); return; }
    let cancelled = false;
    fetch(`${TECH_DASH_BASE}/api/scores/${cgId}/monthly`)
      .then(r => r.json())
      .then(data => {
        if (!cancelled) {
          setMonths(data?.months ?? []);
          setLoading(false);
        }
      })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [cgId]);

  if (!cgId) return null;
  if (!loading && months.length === 0) return null;

  const chartData = months.map(m => ({ ...m, grade: techGrade(m.score) }));

  return (
    <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="text-sm font-semibold text-gray-200">Technical Score — monthly history</div>
        <div className="flex items-center gap-3 text-xs text-gray-600">
          {(["A","B+","B","C+","C","D"] as const).map(l => {
            const g = techGrade(l === "A" ? 82 : l === "B+" ? 68 : l === "B" ? 58 : l === "C+" ? 47 : l === "C" ? 37 : 20);
            return (
              <span key={l} className="flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-sm" style={{ background: g.color }} />
                {l}
              </span>
            );
          })}
        </div>
      </div>
      {loading ? (
        <div className="h-36 flex items-center justify-center text-gray-600 text-sm">Loading…</div>
      ) : (
        <ResponsiveContainer width="100%" height={160}>
          <BarChart data={chartData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" vertical={false} />
            <XAxis
              dataKey="month"
              tickFormatter={(m: string) => { const [, mo] = m.split("-"); return mo; }}
              tick={{ fill: "#6b7280", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]}
              tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} width={28} />
            <Tooltip
              contentStyle={{ background: "#1a1d29", border: "1px solid #2d3144", borderRadius: 8, fontSize: 11 }}
              labelFormatter={(m: string) => m}
              formatter={(v: number, _: string, entry: { payload?: { grade?: ReturnType<typeof techGrade> } }) => [
                `${v.toFixed(1)} — ${entry.payload?.grade?.letter ?? ""}`,
                "Overall Score",
              ]}
            />
            <Bar dataKey="score" radius={[3, 3, 0, 0]} maxBarSize={40}>
              {chartData.map((d, i) => (
                <Cell key={i} fill={d.grade.color} fillOpacity={0.75} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
      <p className="text-xs text-gray-600 mt-3">
        Monthly overall_score from the IOSG Tech Dashboard. Last value of each calendar month.
        Grades: A ≥80 · B+ ≥65 · B ≥55 · C+ ≥45 · C ≥35 · D &lt;35.
      </p>
    </div>
  );
}

// ── Token color palette ──────────────────────────────────────────────────────

const TOKEN_COLORS: Record<string, string> = {
  uni:      "#ff007a",
  ethfi:    "#06b6d4",
  jup:      "#9945ff",
  hype:     "#00e5a0",
  lighter:  "#14b8a6",
  sky:      "#f59e0b",
  coinbase: "#0052ff",
};

// ── TokenHistoricalCharts (UNI / ETHFI / JUP / SKY) ─────────────────────────

const SIGNAL_COLOR: Record<string, string> = { GOOD: "#4ade80", NEUTRAL: "#9ca3af", BAD: "#f87171" };

const TOKEN_BACKTEST_NOTE: Record<string, string> = {
  uni:   "PV proxy = rolling total DEX volume × UNI share with no-lookahead fee rule × 15× / DR³ / effective Y3 supply, normalised to current selected-model P50.",
  ethfi: "PV proxy = historical staking TVL × estimated GP/TVL rate × 15× / DR³ / supply, normalised to current P50.",
  jup:   "PV proxy = rolling 30D perps fees × 25% take × 15× / DR³ / circ supply, normalised to current P50.",
  lighter: "PV proxy = trailing 30D Lighter revenue annualized × 15× / DR³ / circulating supply. Short-history diagnostic, not a full historical MC replay.",
  sky:   "PV proxy = historical money-market TVL × Sky share × net GP/supply rate × GP multiple / DR³ / supply, normalised to current P50.",
};

const TOKEN_EOY3_LABEL: Record<string, string> = {
  uni:   "Model implied EOY3 UNI/Total DEX market share",
  ethfi: "Model implied EOY3 ether.fi/LRT market share",
  jup:   "Model implied EOY3 JUP/Binance Futures perps share",
  lighter: "Model implied EOY3 Lighter/Binance Futures market share",
  sky:   "Model implied EOY3 Sky/Money-market denominator share",
};

function TokenHistoricalCharts({ hc, tokenKey }: { hc: HistCharts; tokenKey: string }) {
  const bt      = hc.backtest;
  const chart   = bt?.chart ?? [];
  const signals = bt?.signals ?? {};
  const sec     = hc.secondary_chart;
  const eoy3    = hc.eoy3_ms ?? [];

  const fmtRet = (v: number | null) => v == null ? "n/a" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
  const dateLbl = (d: string) => { const [, m, day] = d.split("-"); return `${parseInt(m)}/${parseInt(day)}`; };

  const fmtSecVal = (v: number, unit: string) => {
    if (unit === "y") return `${v.toFixed(1)}y`;
    if (unit === "pct") return `${(v * 100).toFixed(1)}%`;
    return `${v.toFixed(0)}×`;
  };

  // Backtest chart: colored spot segments + blue PV
  const lastRealized = bt.last_realized_row ?? "";
  const btData = chart.map((row, i) => {
    const isUnscored = lastRealized && row.date > lastRealized;
    const prev = chart[i - 1];
    const next = chart[i + 1];
    const prevSig = prev ? (lastRealized && prev.date > lastRealized ? "unscored" : prev.signal) : row.signal;
    const nextSig = next ? (lastRealized && next.date > lastRealized ? "unscored" : next.signal) : row.signal;
    const curSig  = isUnscored ? "unscored" : row.signal;
    const v = row.spot;
    const inGood    = (curSig === "GOOD"    || prevSig === "GOOD"    || nextSig === "GOOD")    && !isUnscored;
    const inNeutral = (curSig === "NEUTRAL" || prevSig === "NEUTRAL" || nextSig === "NEUTRAL") && !isUnscored;
    const inBad     = (curSig === "BAD"     || prevSig === "BAD"     || nextSig === "BAD")     && !isUnscored;
    const isBoundaryToUnscored = !isUnscored && nextSig === "unscored";
    const unscoredSig = isUnscored ? row.signal : (isBoundaryToUnscored ? row.signal : null);
    return {
      ...row,
      spot_good:             inGood    ? v : null,
      spot_neutral:          inNeutral ? v : null,
      spot_bad:              inBad     ? v : null,
      spot_unscored_good:    (isUnscored || isBoundaryToUnscored) && unscoredSig === "GOOD"    ? v : null,
      spot_unscored_neutral: (isUnscored || isBoundaryToUnscored) && unscoredSig === "NEUTRAL" ? v : null,
      spot_unscored_bad:     (isUnscored || isBoundaryToUnscored) && unscoredSig === "BAD"     ? v : null,
    };
  });
  const btTicks = chart.length > 6
    ? chart.filter((_, i) => i % Math.floor(chart.length / 6) === 0).map(r => r.date)
    : chart.map(r => r.date);

  // Secondary chart
  const secData   = sec?.data ?? [];
  const secLatest = secData[secData.length - 1];
  const secStep   = Math.max(1, Math.floor(secData.length / 180));
  const secSampled = secData.filter((_, i) => i % secStep === 0);
  const secTicks   = secSampled.filter((_, i) => i % Math.floor(Math.max(secSampled.length / 5, 1)) === 0).map(r => r.date);
  const secVals    = secSampled.map(r => r.value);
  const secMin     = secVals.length ? Math.max(0, Math.min(...secVals) - 2) : 0;
  const secMax     = secVals.length ? Math.max(...secVals) + 2 : 100;

  // EOY3 chart
  const e3Step    = Math.max(1, Math.floor(eoy3.length / 180));
  const e3Sampled = eoy3.filter((_, i) => i % e3Step === 0);
  const e3Ticks   = e3Sampled.filter((_, i) => i % Math.floor(Math.max(e3Sampled.length / 5, 1)) === 0).map(r => r.date);
  const e3Latest  = eoy3[eoy3.length - 1];

  return (
    <div className="space-y-5">

      {/* ── 1. Historical entry backtest ────────────────────────────── */}
      {chart.length > 0 && (
        <div className="space-y-3">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Left: description */}
            <div className="lg:col-span-1">
              <h3 className="text-xl font-bold text-white mb-3">Historical entry backtest</h3>
              <p className="text-sm text-gray-400 leading-relaxed">
                Historical model-shaped diagnostic, not a full MC replay: <span className="text-gray-200">GOOD</span> if model PV/spot &gt; 1.25, <span className="text-gray-200">BAD</span> if &lt; 0.75.{" "}
                Latest signal: <span className="font-bold" style={{ color: SIGNAL_COLOR[bt.latest_signal] }}>{bt.latest_signal}</span>
                {bt.last_realized_row && <>; last realized-return row: <span className="font-bold text-gray-200">{bt.last_realized_row}</span></>}.
              </p>
            </div>
            {/* Right: signal table */}
            <div className="lg:col-span-2 bg-[#1a1d29] rounded-xl border border-[#2d3144] overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#2d3144]">
                    {["SIGNAL", "OBS", "AVG +30D", "AVG +90D", "RECENT DATES"].map(h => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {["GOOD", "NEUTRAL", "BAD"].map(sig => {
                    const s = signals[sig];
                    if (!s) return null;
                    return (
                      <tr key={sig} className="border-b border-[#2d3144] last:border-0">
                        <td className="px-4 py-3 font-semibold text-xs tracking-wider" style={{ color: SIGNAL_COLOR[sig] }}>{sig}</td>
                        <td className="px-4 py-3 font-mono text-gray-200">{s.obs}</td>
                        <td className="px-4 py-3 font-mono text-gray-200">{fmtRet(s.avg_30d)}</td>
                        <td className="px-4 py-3 font-mono text-gray-200">{fmtRet(s.avg_90d)}</td>
                        <td className="px-4 py-3 text-xs text-gray-500">
                          {s.recent_dates.slice(-3).join(",\n").split(",").map((d, i) => <div key={i}>{d.trim()}</div>)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Backtest chart */}
          <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-5">
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm font-semibold text-gray-200">Backtest visual: spot vs model-shaped PV</div>
              <div className="text-xs text-gray-600">black=spot · blue=model-shaped PV normalised</div>
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={btData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" vertical={false} />
                <XAxis dataKey="date" ticks={btTicks} tickFormatter={dateLbl}
                  tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tickFormatter={(v: number) => `$${v.toFixed(2)}`} tick={{ fill: "#6b7280", fontSize: 10 }}
                  axisLine={false} tickLine={false} width={42} domain={["auto", "auto"]} scale="log" />
                <Tooltip contentStyle={{ background: "#1a1d29", border: "1px solid #2d3144", borderRadius: 8, fontSize: 11 }}
                  formatter={(v: number, name: string) => {
                    if (name === "pv") return [`$${v.toFixed(4)}`, "Model PV"];
                    if (typeof v === "number") return [`$${v.toFixed(4)}`, "Spot"];
                    return [null, null];
                  }} />
                <Line type="monotone" dataKey="spot_good"             stroke="#4ade80" strokeWidth={2} dot={{ r: 3, fill: "#4ade80", strokeWidth: 0 }} connectNulls={false} legendType="none" />
                <Line type="monotone" dataKey="spot_neutral"          stroke="#6b7280" strokeWidth={2} dot={{ r: 3, fill: "#6b7280", strokeWidth: 0 }} connectNulls={false} legendType="none" />
                <Line type="monotone" dataKey="spot_bad"              stroke="#f87171" strokeWidth={2} dot={{ r: 3, fill: "#f87171", strokeWidth: 0 }} connectNulls={false} legendType="none" />
                <Line type="monotone" dataKey="spot_unscored_good"    stroke="#4ade80" strokeWidth={1.5} strokeOpacity={0.35} dot={{ r: 3, fill: "#4ade80", strokeWidth: 0, fillOpacity: 0.35 }} connectNulls={false} legendType="none" />
                <Line type="monotone" dataKey="spot_unscored_neutral" stroke="#6b7280" strokeWidth={1.5} strokeOpacity={0.35} dot={{ r: 3, fill: "#6b7280", strokeWidth: 0, fillOpacity: 0.35 }} connectNulls={false} legendType="none" />
                <Line type="monotone" dataKey="spot_unscored_bad"     stroke="#f87171" strokeWidth={1.5} strokeOpacity={0.35} dot={{ r: 3, fill: "#f87171", strokeWidth: 0, fillOpacity: 0.35 }} connectNulls={false} legendType="none" />
                <Line type="monotone" dataKey="pv" stroke="#60a5fa" strokeWidth={1.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
            <p className="text-xs text-gray-600 mt-3 leading-relaxed">
              Colored line = {tokenKey.toUpperCase()} spot (green=GOOD, grey=NEUTRAL, red=BAD). Faded tail = recent unscored dates without enough forward return history yet. Blue line = model-shaped PV proxy normalised to current P50.{" "}
              {TOKEN_BACKTEST_NOTE[tokenKey] ?? "Preliminary diagnostic, not a full historical MC replay."}
            </p>
          </div>
        </div>
      )}

      {/* ── 2. Secondary chart (Mcap/GP or buyback horizon) ─────────── */}
      {sec && secSampled.length > 0 && (
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-5">
          <div className="flex items-center justify-between mb-1">
            <div className="text-sm font-semibold text-gray-200">{sec.label}</div>
            {secLatest && <div className="text-xs text-gray-500 font-mono">latest {fmtSecVal(secLatest.value, sec.unit)}</div>}
          </div>
          {sec.subtitle && <div className="text-xs text-gray-600 text-right mb-1">{sec.subtitle}</div>}
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={secSampled} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" vertical={false} />
              <XAxis dataKey="date" ticks={secTicks} tickFormatter={dateLbl}
                tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={(v: number) => fmtSecVal(v, sec.unit)}
                tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} width={38}
                domain={[secMin, secMax]} />
              <Tooltip contentStyle={{ background: "#1a1d29", border: "1px solid #2d3144", borderRadius: 8, fontSize: 11 }}
                formatter={(v: number) => [fmtSecVal(v, sec.unit), sec.label]} />
              <Line type="monotone" dataKey="value" stroke="#e5e7eb" strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
          {sec.note && <p className="text-xs text-gray-600 mt-3 leading-relaxed">{sec.note}</p>}
        </div>
      )}

      {/* ── 3. Model implied EOY3 market share ──────────────────────── */}
      {e3Sampled.length > 0 && (
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-5">
          <div className="flex items-center justify-between mb-1">
            <div className="text-sm font-semibold text-gray-200">{TOKEN_EOY3_LABEL[tokenKey] ?? "Model implied EOY3 market share"}</div>
            {e3Latest && <div className="text-xs text-gray-500 font-mono">12M {pct(e3Latest.eoy3)}</div>}
          </div>
          <div className="text-xs text-gray-600 text-right mb-2">blue=EOY3 decay · grey=MS90 · dashed=MS30</div>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={e3Sampled} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" vertical={false} />
              <XAxis dataKey="date" ticks={e3Ticks} tickFormatter={dateLbl}
                tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} width={36} />
              <Tooltip contentStyle={{ background: "#1a1d29", border: "1px solid #2d3144", borderRadius: 8, fontSize: 11 }}
                formatter={(v: number, name: string) => [`${(v * 100).toFixed(1)}%`,
                  name === "eoy3" ? "EOY3 decay" : name === "ms90" ? "MS90" : "MS30"]} />
              <Line type="monotone" dataKey="eoy3" stroke="#60a5fa" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="ms90" stroke="#6b7280" strokeWidth={1.5} dot={false} />
              <Line type="monotone" dataKey="ms30" stroke="#9ca3af" strokeWidth={1} dot={false} strokeDasharray="4 2" />
            </LineChart>
          </ResponsiveContainer>
          <p className="text-xs text-gray-600 mt-3 leading-relaxed">
            Historical time series of the model-implied Year-3 terminal market share using MS90 as seed and blended velocity decay (12M linear decay). The current EOY3 model point is {e3Latest ? pct(e3Latest.eoy3) : "—"}.
          </p>
        </div>
      )}

    </div>
  );
}

function TokenCaveats({ caveats }: { caveats: string[] }) {
  return (
    <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-6">
      <h3 className="text-lg font-bold text-white mb-3">Caveats</h3>
      <ul className="space-y-2">
        {caveats.map((caveat, i) => (
          <li key={i} className="flex items-start gap-3">
            <span className="mt-2 w-1.5 h-1.5 rounded-full bg-gray-500 shrink-0" />
            <span className="text-sm text-gray-400 leading-relaxed">{caveat}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── HypeHistoricalCharts ─────────────────────────────────────────────────────

function HypeHistoricalCharts({ hc }: { hc: HistCharts }) {
  const bt = hc.backtest;
  const chart = bt?.chart ?? [];
  const signals = bt?.signals ?? {};
  const buyback = hc.buyback_horizon ?? [];
  const eoy3 = hc.eoy3_ms ?? [];

  const fmtRet = (v: number | null) => v == null ? "n/a" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
  const fmtYr = (v: number) => `${v.toFixed(0)}y`;

  // x-axis label helper
  const dateLbl = (d: string) => { const [, m, day] = d.split("-"); return `${parseInt(m)}/${parseInt(day)}`; };

  // Backtest chart: use all points for dense dot coverage; add per-signal columns for colored lines
  const lastRealized = bt.last_realized_row ?? "";
  const btData = chart.map((row, i) => {
    const isUnscored = lastRealized && row.date > lastRealized;
    const prev = chart[i - 1];
    const next = chart[i + 1];
    const prevSig = prev ? (lastRealized && prev.date > lastRealized ? "unscored" : prev.signal) : row.signal;
    const nextSig = next ? (lastRealized && next.date > lastRealized ? "unscored" : next.signal) : row.signal;
    const curSig  = isUnscored ? "unscored" : row.signal;
    const v = row.spot;
    // Scored segments — include boundary points for seamless transitions
    const inGood    = (curSig === "GOOD"    || prevSig === "GOOD"    || nextSig === "GOOD")    && !isUnscored;
    const inNeutral = (curSig === "NEUTRAL" || prevSig === "NEUTRAL" || nextSig === "NEUTRAL") && !isUnscored;
    const inBad     = (curSig === "BAD"     || prevSig === "BAD"     || nextSig === "BAD")     && !isUnscored;
    // Unscored: same boundary logic but keep actual signal so color is preserved
    const isBoundaryToUnscored = !isUnscored && nextSig === "unscored";
    const unscoredSig = isUnscored ? row.signal : (isBoundaryToUnscored ? row.signal : null);
    return {
      ...row,
      spot_good:            inGood    ? v : null,
      spot_neutral:         inNeutral ? v : null,
      spot_bad:             inBad     ? v : null,
      spot_unscored_good:   (isUnscored || isBoundaryToUnscored) && unscoredSig === "GOOD"    ? v : null,
      spot_unscored_neutral:(isUnscored || isBoundaryToUnscored) && unscoredSig === "NEUTRAL" ? v : null,
      spot_unscored_bad:    (isUnscored || isBoundaryToUnscored) && unscoredSig === "BAD"     ? v : null,
    };
  });
  const btTicks = chart.filter((_, i) => i % Math.floor(chart.length / 6) === 0).map(r => r.date);

  // Buyback chart
  const bbStep = Math.max(1, Math.floor(buyback.length / 180));
  const bbSampled = buyback.filter((_, i) => i % bbStep === 0);
  const bbTicks = bbSampled.filter((_, i) => i % Math.floor(bbSampled.length / 5) === 0).map(r => r.date);
  const bbMin = Math.max(0, Math.min(...bbSampled.map(r => r.years)) - 2);
  const bbMax = Math.max(...bbSampled.map(r => r.years)) + 2;
  const bbLatest = buyback[buyback.length - 1];

  // EOY3 chart
  const e3Step = Math.max(1, Math.floor(eoy3.length / 180));
  const e3Sampled = eoy3.filter((_, i) => i % e3Step === 0);
  const e3Ticks = e3Sampled.filter((_, i) => i % Math.floor(e3Sampled.length / 5) === 0).map(r => r.date);
  const e3Latest = eoy3[eoy3.length - 1];

  return (
    <div className="space-y-5">

      {/* ── 1. Historical entry backtest ────────────────────────────── */}
      {chart.length > 0 && (
        <div className="space-y-3">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Left: description */}
            <div className="lg:col-span-1">
              <h3 className="text-xl font-bold text-white mb-3">Historical entry backtest</h3>
              <p className="text-sm text-gray-400 leading-relaxed">
                Historical model-shaped diagnostic, not a full MC replay: <span className="text-gray-200">GOOD</span> if model PV/spot &gt; 1.25, <span className="text-gray-200">BAD</span> if &lt; 0.75.{" "}
                Latest signal: <span className="font-bold" style={{ color: SIGNAL_COLOR[bt.latest_signal] }}>{bt.latest_signal}</span>
                {bt.last_realized_row && <>; last realized-return row: <span className="font-bold text-gray-200">{bt.last_realized_row}</span></>}.
              </p>
            </div>
            {/* Right: signal table */}
            <div className="lg:col-span-2 bg-[#1a1d29] rounded-xl border border-[#2d3144] overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#2d3144]">
                    {["SIGNAL", "OBS", "AVG +30D", "AVG +90D", "RECENT DATES"].map(h => (
                      <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {["GOOD", "NEUTRAL", "BAD"].map(sig => {
                    const s = signals[sig];
                    if (!s) return null;
                    return (
                      <tr key={sig} className="border-b border-[#2d3144] last:border-0">
                        <td className="px-4 py-3 font-semibold text-xs tracking-wider" style={{ color: SIGNAL_COLOR[sig] }}>{sig}</td>
                        <td className="px-4 py-3 font-mono text-gray-200">{s.obs}</td>
                        <td className="px-4 py-3 font-mono text-gray-200">{fmtRet(s.avg_30d)}</td>
                        <td className="px-4 py-3 font-mono text-gray-200">{fmtRet(s.avg_90d)}</td>
                        <td className="px-4 py-3 text-xs text-gray-500">
                          {s.recent_dates.slice(-3).join(",\n").split(",").map((d, i) => <div key={i}>{d.trim()}</div>)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Backtest chart */}
          <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-5">
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm font-semibold text-gray-200">Backtest visual: spot vs model-shaped PV</div>
              <div className="text-xs text-gray-600">black=spot · blue=model-shaped PV normalized</div>
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={btData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" vertical={false} />
                <XAxis dataKey="date" ticks={btTicks} tickFormatter={dateLbl}
                  tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tickFormatter={(v: number) => `$${v.toFixed(0)}`} tick={{ fill: "#6b7280", fontSize: 10 }}
                  axisLine={false} tickLine={false} width={38} domain={["auto", "auto"]} scale="log" />
                <Tooltip contentStyle={{ background: "#1a1d29", border: "1px solid #2d3144", borderRadius: 8, fontSize: 11 }}
                  formatter={(v: number, name: string) => {
                    if (name === "pv") return [`$${(v as number).toFixed(2)}`, "Model PV"];
                    if (typeof v === "number") return [`$${v.toFixed(2)}`, "Spot"];
                    return [null, null];
                  }} />
                {/* Scored segments */}
                <Line type="monotone" dataKey="spot_good"            stroke="#4ade80" strokeWidth={2} dot={{ r: 3, fill: "#4ade80", strokeWidth: 0 }} connectNulls={false} legendType="none" />
                <Line type="monotone" dataKey="spot_neutral"         stroke="#6b7280" strokeWidth={2} dot={{ r: 3, fill: "#6b7280", strokeWidth: 0 }} connectNulls={false} legendType="none" />
                <Line type="monotone" dataKey="spot_bad"             stroke="#f87171" strokeWidth={2} dot={{ r: 3, fill: "#f87171", strokeWidth: 0 }} connectNulls={false} legendType="none" />
                {/* Unscored (faded) — same signal color so you can see the current regime */}
                <Line type="monotone" dataKey="spot_unscored_good"    stroke="#4ade80" strokeWidth={1.5} strokeOpacity={0.35} dot={{ r: 3, fill: "#4ade80", strokeWidth: 0, fillOpacity: 0.35 }} connectNulls={false} legendType="none" />
                <Line type="monotone" dataKey="spot_unscored_neutral" stroke="#6b7280" strokeWidth={1.5} strokeOpacity={0.35} dot={{ r: 3, fill: "#6b7280", strokeWidth: 0, fillOpacity: 0.35 }} connectNulls={false} legendType="none" />
                <Line type="monotone" dataKey="spot_unscored_bad"     stroke="#f87171" strokeWidth={1.5} strokeOpacity={0.35} dot={{ r: 3, fill: "#f87171", strokeWidth: 0, fillOpacity: 0.35 }} connectNulls={false} legendType="none" />
                {/* Blue PV line */}
                <Line type="monotone" dataKey="pv" stroke="#60a5fa" strokeWidth={1.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
            <p className="text-xs text-gray-600 mt-3 leading-relaxed">
              Colored line = HYPE spot (green=GOOD, grey=NEUTRAL, red=BAD). Faded tail = recent unscored dates without enough forward return history yet — same signal color so the current regime is visible. Blue line = model-shaped PV proxy normalized to current P50 PV. Preliminary diagnostic, not a full historical MC replay.
            </p>
          </div>
        </div>
      )}

      {/* ── 2. Historical buyback horizon ───────────────────────────── */}
      {buyback.length > 0 && (
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-5">
          <div className="flex items-center justify-between mb-2">
            <div className="text-sm font-semibold text-gray-200">Historical buyback horizon</div>
            {bbLatest && <div className="text-xs text-gray-500 font-mono">latest {fmtYr(bbLatest.years)}</div>}
          </div>
          <div className="text-xs text-gray-600 text-right mb-1">trailing-30D fee revenue annualized ÷ date price; target=circ+3Y gross issuance</div>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={bbSampled} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" vertical={false} />
              <XAxis dataKey="date" ticks={bbTicks} tickFormatter={dateLbl}
                tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={fmtYr} tick={{ fill: "#6b7280", fontSize: 10 }}
                axisLine={false} tickLine={false} width={32} domain={[bbMin, bbMax]} />
              <Tooltip contentStyle={{ background: "#1a1d29", border: "1px solid #2d3144", borderRadius: 8, fontSize: 11 }}
                formatter={(v: number) => [`${v.toFixed(1)}y`, "Buyback horizon"]} />
              <Line type="monotone" dataKey="years" stroke="#e5e7eb" strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
          <p className="text-xs text-gray-600 mt-3 leading-relaxed">
            Historical line uses each date&apos;s HYPE price and trailing-30D annualized DefiLlama total fees for continuity. Target = current circulating supply + modeled 3Y gross issuance. Corrected current clean-revenue-only horizon is shown in the snapshot table.
          </p>
        </div>
      )}

      {/* ── 3. Model implied EOY3 market share ──────────────────────── */}
      {eoy3.length > 0 && (
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-5">
          <div className="flex items-center justify-between mb-1">
            <div className="text-sm font-semibold text-gray-200">Model implied EOY3 Hyperliquid/Binance market share</div>
            {e3Latest && <div className="text-xs text-gray-500 font-mono">12M {pct(e3Latest.eoy3)}</div>}
          </div>
          <div className="text-xs text-gray-600 text-right mb-2">blue=current 12M decay · grey=MS90 · dashed=MS30</div>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={e3Sampled} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3144" vertical={false} />
              <XAxis dataKey="date" ticks={e3Ticks} tickFormatter={dateLbl}
                tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                tick={{ fill: "#6b7280", fontSize: 10 }} axisLine={false} tickLine={false} width={36} />
              <Tooltip contentStyle={{ background: "#1a1d29", border: "1px solid #2d3144", borderRadius: 8, fontSize: 11 }}
                formatter={(v: number, name: string) => [`${(v * 100).toFixed(1)}%`,
                  name === "eoy3" ? "12M decay EOY3" : name === "ms90" ? "MS90" : "MS30"]} />
              <Line type="monotone" dataKey="eoy3" stroke="#60a5fa" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="ms90" stroke="#6b7280" strokeWidth={1.5} dot={false} />
              <Line type="monotone" dataKey="ms30" stroke="#9ca3af" strokeWidth={1} dot={false} strokeDasharray="4 2" />
            </LineChart>
          </ResponsiveContainer>
          <p className="text-xs text-gray-600 mt-3 leading-relaxed">
            Historical time series of the model-implied Year-3 terminal HL/Binance share using the same MS90 seed and MS30/MS180 velocity-decay rule. The current 12M-decay model point is {e3Latest ? pct(e3Latest.eoy3) : "—"}. Shows the terminal share embedded in the locked valuation model.
          </p>
        </div>
      )}

    </div>
  );
}

// ── HypeModelOutputs ─────────────────────────────────────────────────────────

function HypeModelOutputs({ data }: { data: ValuationData }) {
  const primary = data.scenarios.find((s) => s.is_primary) ?? data.scenarios[0];
  const { y3_price_p50, y3_supply_p50, y3_gp_p50, burn_3y_est, y3_volume } = primary;

  if (!y3_price_p50) return null;

  const vol    = y3_volume as Y3Volume;
  const gp     = data.current_gp;
  const circ   = data.market.circulating_supply;
  const gross3y = gp["gross_3y"] as number | undefined;
  const net3y   = (gross3y ?? 0) - (burn_3y_est ?? 0);

  const currentRevenue = ((gp["clean_treasury_revenue_ann"] as number) ?? 0) + ((gp["usdc_gp_annual"] as number) ?? 0);
  const gpVsCurrent      = currentRevenue > 0 && y3_gp_p50   ? ((y3_gp_p50   / currentRevenue - 1) * 100) : null;
  const supplyVsCurrent  = circ > 0         && y3_supply_p50 ? ((y3_supply_p50 / circ          - 1) * 100) : null;

  return (
    <div className="space-y-5">
      <h2 className="text-3xl font-bold text-gray-900">Model Outputs</h2>

      {/* ── All-scenario table ──────────────────────────────────────── */}
      <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text-left px-6 py-4 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">Case</th>
                {["P25 PV", "P50 PV", "P75 PV", "P90 PV", "EV"].map((h) => (
                  <th key={h} className="text-right px-4 py-4 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">{h}</th>
                ))}
                <th className="text-right px-4 py-4 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">P(Spot)</th>
                <th className="text-right px-4 py-4 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">2Y +30%</th>
                <th className="text-right px-4 py-4 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">2Y -30%</th>
              </tr>
            </thead>
            <tbody>
              {data.scenarios.map((s) => {
                const probColor = s.prob_above_spot >= 0.5 ? "#15803d" : s.prob_above_spot >= 0.35 ? "#a16207" : "#b91c1c";
                return (
                  <tr key={s.key} className="border-b border-gray-100 last:border-0">
                    <td className={`px-6 py-4 text-sm whitespace-nowrap ${s.is_primary ? "font-semibold text-gray-900" : "text-gray-600"}`}>{s.label}</td>
                    {(["p25", "p50", "p75", "p90"] as const).map((p) => (
                      <td key={p} className={`px-4 py-4 text-right font-mono text-sm whitespace-nowrap ${p === "p50" ? "font-semibold text-gray-900" : "text-gray-700"}`}>
                        {fmtPrice(s.pv[p])}
                      </td>
                    ))}
                    <td className="px-4 py-4 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{fmtPrice(s.ev)}</td>
                    <td className="px-4 py-4 text-right font-mono text-sm font-semibold whitespace-nowrap" style={{ color: probColor }}>
                      {pct(s.prob_above_spot)}
                    </td>
                    <td className="px-4 py-4 text-right font-mono text-sm text-gray-700 whitespace-nowrap">
                      {s.prob_spot_up_30_2y != null ? pct(s.prob_spot_up_30_2y) : "—"}
                    </td>
                    <td className="px-4 py-4 text-right font-mono text-sm text-gray-700 whitespace-nowrap">
                      {s.prob_spot_down_30_2y != null ? pct(s.prob_spot_down_30_2y) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Metric cards ────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] px-5 py-4">
          <div className="text-xs text-gray-500 font-mono mb-1">Y3 aggregate GP / supply</div>
          <div className="text-2xl font-bold text-gray-900 font-mono leading-tight">
            {fmtLarge(y3_gp_p50 ?? 0)} /{" "}{((y3_supply_p50 ?? 0) / 1e6).toFixed(1)}M
          </div>
          <div className="text-xs text-gray-500 mt-1 leading-relaxed">
            {gpVsCurrent != null ? `${gpVsCurrent >= 0 ? "+" : ""}${gpVsCurrent.toFixed(1)}% vs current clean revenue + yield` : "P50 end-Year-3."}
            {supplyVsCurrent != null ? `; supply ${supplyVsCurrent >= 0 ? "+" : ""}${supplyVsCurrent.toFixed(1)}% vs current circ.` : ""}
          </div>
        </div>
        <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] px-5 py-4">
          <div className="text-xs text-gray-500 font-mono mb-1">Y3 GP split</div>
          <div className="text-2xl font-bold text-gray-900 font-mono leading-tight">
            {fmtLarge(y3_gp_p50 ?? 0)}
          </div>
          <div className="text-xs text-gray-500 mt-1 leading-relaxed">
            Perps + USDC stablecoin yield. Primary scenario P50.
          </div>
        </div>
        <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] px-5 py-4">
          <div className="text-xs text-gray-500 font-mono mb-1">Y3 daily volume P50</div>
          <div className="text-2xl font-bold text-gray-900 font-mono leading-tight">
            {fmtLarge(vol?.avg ?? 0)}
          </div>
          <div className="text-xs text-gray-500 mt-1 leading-relaxed">
            EOY3 share {pct(vol?.eoy_market_share ?? 0)}. Min {fmtLarge(vol?.min ?? 0)} / max {fmtLarge(vol?.max ?? 0)}.
          </div>
        </div>
        <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] px-5 py-4">
          <div className="text-xs text-gray-500 font-mono mb-1">3Y gross / burn / net</div>
          <div className="text-2xl font-bold text-gray-900 font-mono leading-tight">
            {((gross3y ?? 0) / 1e6).toFixed(1)}M / {((burn_3y_est ?? 0) / 1e6).toFixed(1)}M
          </div>
          <div className="text-xs text-gray-500 mt-1 leading-relaxed">
            Net {net3y >= 0 ? "+" : ""}{(net3y / 1e6).toFixed(1)}M before scenario supply effects.
          </div>
        </div>
      </div>
    </div>
  );
}

// ── HypeModelAssumptions ─────────────────────────────────────────────────────

function HypeModelAssumptions({ data }: { data: ValuationData }) {
  const gp = data.current_gp;
  const supplyVelocity = gp["supply_velocity_monthly"] as number | undefined;
  const gross3y        = gp["gross_3y"] as number | undefined;
  const burn3y         = gp["burn_3y_est"] as number | undefined;
  const dr             = data.model.discount_rate;

  if (!supplyVelocity) return null;

  const net3y = (gross3y ?? 0) - (burn3y ?? 0);
  const drPct = `${(dr * 100).toFixed(0)}%`;

  return (
    <div className="space-y-3">
      <h3 className="text-xl font-bold text-white">Model assumptions</h3>

      {/* ── Top row: formula cards ───────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-5">
          <div className="text-sm font-semibold text-gray-200 mb-3">Core revenue lines</div>
          <pre className="text-xs font-mono text-gray-400 leading-relaxed bg-[#252836] rounded-lg p-4 overflow-x-auto whitespace-pre-wrap">
{`perp_treasury_revenue_t = BinanceVol_t × HLShare_t × 0.026%
USDC_GP_t = USDC_TVL_t × net_yield × 90% / 12
USDC TVL follows HL volume path ^ 0.22`}
          </pre>
        </div>
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-5">
          <div className="text-sm font-semibold text-gray-200 mb-3">Valuation logic</div>
          <pre className="text-xs font-mono text-gray-400 leading-relaxed bg-[#252836] rounded-lg p-4 overflow-x-auto whitespace-pre-wrap">
{`Y3 price = Y3 TTM GP × multiple / Y3 supply × 1.10
PV = Y3 price / (1+${drPct})^3
Multiple: 20× trough / 15× normal / 10× peak`}
          </pre>
        </div>
      </div>

      {/* ── Bottom row: metric cards ─────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] px-5 py-4">
          <div className="text-xs text-gray-500 mb-1">Supply velocity</div>
          <div className="text-2xl font-bold text-white font-mono">
            {(supplyVelocity / 1e6).toFixed(2)}M/mo
          </div>
          <div className="text-xs text-gray-600 mt-1">Selected-model gross release.</div>
        </div>
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] px-5 py-4">
          <div className="text-xs text-gray-500 mb-1">3Y gross / burn / net</div>
          <div className="text-2xl font-bold text-white font-mono">
            {((gross3y ?? 0) / 1e6).toFixed(0)}M / {((burn3y ?? 0) / 1e6).toFixed(0)}M / {net3y >= 0 ? "+" : ""}{(net3y / 1e6).toFixed(0)}M
          </div>
          <div className="text-xs text-gray-600 mt-1">Gross release / estimated burn / net supply change.</div>
        </div>
        <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] px-5 py-4">
          <div className="text-xs text-gray-500 mb-1">Revenue inclusion</div>
          <div className="text-2xl font-bold text-white font-mono">Fees ≠ Yield</div>
          <div className="text-xs text-gray-600 mt-1">DefiLlama fee revenue excludes USDC stablecoin yield; modeled separately.</div>
        </div>
      </div>
    </div>
  );
}

// ── TokenModelOutputs ────────────────────────────────────────────────────────

type GpFn = (gp: Record<string, number>) => string;
interface Y3CardCfg { label: string; value: GpFn; sub: GpFn | string }

function deltaText(future: number | undefined, current: number | undefined, suffix = "vs current"): string {
  if (!future || !current || current <= 0) return suffix;
  const delta = (future / current - 1) * 100;
  const sign = delta >= 0 ? "+" : "";
  return `${sign}${delta.toFixed(1)}% ${suffix}`;
}

const TOKEN_Y3_CARDS: Record<string, Y3CardCfg[]> = {
  uni: [
    { label: "Y3 Binance-volume P50",    value: (gp) => fmtLarge(gp["binance_spot_y3_volume_p50"] ?? gp["y3_volume_p50"]), sub: "Primary P50 Year-3 trailing volume" },
    { label: "Y3 GP P50 (primary)",      value: (gp) => fmtLarge(gp["binance_spot_y3_gp_p50"] ?? gp["y3_gp_p50"]),          sub: (gp) => `DEX sensitivity ${fmtLarge(gp["y3_gp_p50"])}` },
    { label: "Effective supply P50",     value: (gp) => `${((gp["y3_supply_p50"] ?? 0) / 1e6).toFixed(0)}M`,               sub: (gp) => `Reserved release +${((gp["y3_reserved_supply_release"] ?? 0) / 1e6).toFixed(0)}M over 3Y` },
    { label: "Mcap / GP (full activ.)",  value: (gp) => `${(gp["mcap_full_activation_gp"] ?? 0).toFixed(1)}×`,             sub: "At current mcap and full-activation take-rate" },
  ],
  ethfi: [
    {
      label: "Y3 aggregate GP",
      value: (gp) => fmtLarge(gp["y3_gp_p50"] as number),
      sub: (gp) => {
        const curr = gp["total_annualized"] as number ?? 0;
        const y3   = gp["y3_gp_p50"] as number ?? 0;
        const pct  = curr > 0 ? `+${((y3 / curr - 1) * 100).toFixed(1)}%` : "—";
        return `${pct} vs current annualized GP.`;
      },
    },
    {
      label: "Y3 product split",
      value: (gp) => fmtLarge(gp["y3_card_gp_p50"] as number),
      sub: (gp) => {
        const cardPct  = (gp["card_annualized"] as number)  > 0 ? `+${(((gp["y3_card_gp_p50"]  as number) / (gp["card_annualized"]     as number) - 1) * 100).toFixed(1)}%` : "—";
        const stakePct = (gp["staking_annualized"] as number) > 0 ? `+${(((gp["y3_stake_gp_p50"] as number) / (gp["staking_annualized"]  as number) - 1) * 100).toFixed(1)}%` : "—";
        const vaultPct = (gp["vault_annualized"] as number)  > 0 ? `+${(((gp["y3_vault_gp_p50"] as number) / (gp["vault_annualized"]    as number) - 1) * 100).toFixed(1)}%` : "—";
        return `Card ${cardPct} · staking ${stakePct} · vault ${vaultPct} vs current GP lines.`;
      },
    },
    {
      label: "Y3 effective supply",
      value: (gp) => `${((gp["current_circulating_supply"] as number ?? 0) / 1e6).toFixed(1)}M`,
      sub: () => "0.0% vs current circulating supply.",
    },
    {
      label: "Treasury cash P50",
      value: (gp) => fmtLarge(gp["treasury_cash_p50"] as number),
      sub: (gp) => {
        const cash = gp["treasury_cash_p50"] as number ?? 0;
        const mcap = gp["market_cap"] as number ?? 0;
        const pct  = mcap > 0 ? `${((cash / mcap) * 100).toFixed(1)}%` : "—";
        return `${pct} of current market cap accumulated as cash.`;
      },
    },
  ],
  jup: [
    { label: "Y3 Total GP P50",          value: (gp) => fmtLarge(gp["y3_gp_p50"]),            sub: (gp) => deltaText(gp["y3_gp_p50"], (gp["total_30d"] ?? 0) * 12, "vs current annualized GP") },
    { label: "Y3 Perps GP P50",          value: (gp) => fmtLarge(gp["y3_perps_gp_p50"]),      sub: (gp) => deltaText(gp["y3_perps_gp_p50"], (gp["perps_30d"] ?? 0) * 12, "vs current annualized perps GP") },
    { label: "Y3 Spot GP P50",           value: (gp) => fmtLarge(gp["y3_spot_gp_p50"]),       sub: (gp) => deltaText(gp["y3_spot_gp_p50"], ((gp["total_30d"] ?? 0) - (gp["perps_30d"] ?? 0)) * 12, "vs current annualized spot GP") },
    { label: "Y3 perps daily volume",    value: (gp) => fmtLarge(gp["y3_perps_daily_mean_volume_p50"]), sub: (gp) => deltaText(gp["y3_perps_daily_mean_volume_p50"], (gp["perps_30d_volume"] ?? 0) / 30, "vs current daily perps volume") },
    { label: "Y3 spot daily volume",     value: (gp) => fmtLarge(gp["y3_spot_daily_mean_volume_p50"]), sub: (gp) => deltaText(gp["y3_spot_daily_mean_volume_p50"], (gp["spot_30d_volume"] ?? 0) / 30, "vs current daily spot volume") },
    { label: "Buyback tokens P50",       value: (gp) => `${((gp["buyback_tokens_p50"] ?? 0) / 1e6).toFixed(0)}M`, sub: "Cumulative JUP buyback over 3 years" },
    { label: "Effective supply P50",     value: (gp) => `${((gp["y3_supply_p50"] ?? 0) / 1e9).toFixed(2)}B`, sub: (gp) => deltaText(gp["y3_supply_p50"], gp["current_circulating_supply"], "vs current circulating supply") },
  ],
  lighter: [
    {
      label: "Y3 GP / supply",
      value: (gp) => `${fmtLarge(gp["y3_revenue_p50"])} / ${((gp["y3_supply_p50"] ?? 0) / 1e6).toFixed(1)}M`,
      sub: (gp) => {
        const base = (gp["holders_revenue_30d_ann"] as number ?? 0) + (gp["yield_run_rate"] as number ?? 0);
        const gpGrowth = base > 0 ? (((gp["y3_revenue_p50"] as number) / base - 1) * 100).toFixed(1) : "—";
        const circ = gp["current_circulating_supply"] as number ?? 0;
        const supplyGrowth = circ > 0 ? (((gp["y3_supply_p50"] as number) / circ - 1) * 100).toFixed(1) : "—";
        return `+${gpGrowth}% vs current holder revenue + yield; supply +${supplyGrowth}% vs current circ.`;
      },
    },
    {
      label: "Y3 GP split",
      value: (gp) => fmtLarge(gp["y3_perps_gp_p50"] ?? gp["y3_revenue_p50"]),
      sub: (gp) => {
        const holderRev = gp["holders_revenue_30d_ann"] as number ?? 0;
        const perpsGrowth = holderRev > 0 ? (((gp["y3_perps_gp_p50"] as number) / holderRev - 1) * 100).toFixed(1) : "—";
        const yieldShare = (gp["y3_revenue_p50"] as number) > 0
          ? (((gp["yield_run_rate"] as number ?? 0) / (gp["y3_revenue_p50"] as number)) * 100).toFixed(1)
          : "—";
        return `Perps +${perpsGrowth}% vs holder revenue · yield ${yieldShare}% of base GP.`;
      },
    },
    {
      label: "Y3 annual volume P50",
      value: (gp) => fmtLarge((gp["y3_monthly_volume_p50"] ?? 0) * 12),
      sub: (gp) => {
        const currAnn = (gp["perp_volume_30d"] as number ?? 0) * (365 / 30);
        const annVol = (gp["y3_monthly_volume_p50"] as number ?? 0) * 12;
        const growth = currAnn > 0 ? (((annVol / currAnn) - 1) * 100).toFixed(1) : "—";
        const dailyMean = (annVol / 365 / 1e9).toFixed(2);
        return `+${growth}% vs current annualized volume; daily mean $${dailyMean}B.`;
      },
    },
    {
      label: "Buyback tokens P50",
      value: (gp) => `${((gp["buyback_tokens_p50"] ?? 0) / 1e6).toFixed(1)}M`,
      sub: (gp) => {
        const circ = gp["current_circulating_supply"] as number ?? 0;
        const pct = circ > 0 ? (((gp["buyback_tokens_p50"] as number) / circ) * 100).toFixed(1) : "—";
        return `${pct}% of current circ bought back before fixed unlocks.`;
      },
    },
  ],
  sky: [
    { label: "Y3 Total Stable P50",      value: (gp) => fmtLarge(gp["y3_total_stable_supply_p50"]), sub: (gp) => deltaText(gp["y3_total_stable_supply_p50"], gp["total_sky_stable_supply"], "vs current official USDS + DAI") },
    { label: "Y3 USDS Supply P50",       value: (gp) => fmtLarge(gp["y3_usds_supply_p50"]),  sub: (gp) => deltaText(gp["y3_usds_supply_p50"], gp["usds_supply"], "vs current USDS") },
    { label: "Y3 GP P50",                value: (gp) => fmtLarge(gp["y3_gp_p50"]),           sub: (gp) => deltaText(gp["y3_gp_p50"], gp["current_gp"], "vs current annualized GP") },
    { label: "Y3 avg money-market TVL",  value: (gp) => fmtLarge(gp["y3_avg_money_market_tvl_p50"]), sub: (gp) => deltaText(gp["y3_avg_money_market_tvl_p50"], gp["money_market_tvl"], "vs current denominator") },
    { label: "Treasury cash P50",        value: (gp) => fmtLarge(gp["treasury_cash_p50"]),   sub: "Cumulative positive NP over 3 years" },
  ],
  vvv: [
    { label: "Y3 Revenue P50",           value: (gp) => fmtLarge(gp["y3_revenue_p50"]),      sub: "Est. total platform revenue (base scenario)" },
    { label: "Buyback tokens P50",       value: (gp) => `${((gp["buyback_tokens_p50"] ?? 0) / 1e6).toFixed(2)}M`, sub: "Cumulative VVV buyback-and-burn over 3 years" },
    { label: "Effective supply P50",     value: (gp) => `${((gp["y3_supply_p50"] ?? 0) / 1e6).toFixed(0)}M`,     sub: "Supply after emissions and buyback burns at Year 3" },
  ],
  bp: [
    { label: "Y3 total revenue (base)",  value: (gp) => fmtLarge(gp["y3_revenue_p50"]),              sub: (gp) => `Perps ${fmtLarge(gp["y3_perps_revenue_p50"] as number)} · spot ${fmtLarge(gp["y3_spot_revenue_p50"] as number)} · sec ${fmtLarge(gp["y3_securities_revenue_base"] as number)}` },
    { label: "Y3 company val (base)",    value: (gp) => fmtLarge(gp["y3_company_val_p50"] as number),   sub: "Revenue × 7× P/S multiple" },
    { label: "Y3 equity pool (base)",    value: (gp) => fmtLarge(gp["y3_equity_pool_p50"] as number),   sub: "20% of company valuation shared pro-rata by stakers" },
    { label: "Y3 staking supply (base)", value: (gp) => `${((gp["y3_supply_p50"] ?? 0) / 1e6).toFixed(0)}M BP`, sub: "Phase 1 (250M) + partial Phase 2 milestone unlocks" },
  ],
  cards: [
    { label: "Y3 Gross profit P50",      value: (gp) => fmtLarge(gp["y3_gp_p50"]),               sub: "Annual platform GP (base scenario, sustained from Q1 2026)" },
    { label: "Y3 Supply P50",            value: (gp) => `${((gp["y3_supply_p50"] ?? 0) / 1e9).toFixed(2)}B CARDS`, sub: "Est. circulating after team + investor + community unlock" },
    { label: "GP margin (Q1 2026)",      value: (gp) => `${((gp["gross_margin"] as number) * 100).toFixed(1)}%`,    sub: "Compressed from 10–12% at launch; key downside risk" },
  ],
  coinbase: [
    { label: "Y3 total revenue (base P50)", value: (gp) => fmtLarge(gp["y3_revenue_p50"]), sub: (gp) => `Spot ${fmtLarge(gp["y3_spot_revenue_p50"] as number)} · USDC ${fmtLarge(gp["y3_usdc_revenue_p50"] as number)} · deriv+other ${fmtLarge(((gp["y3_deriv_revenue_p50"] as number) ?? 0) + ((gp["y3_other_revenue_p50"] as number) ?? 0))}` },
    { label: "Spot MS (30D vs Binance)",    value: (gp) => `${(((gp["spot_ms30_vs_binance"] as number) ?? 0)*100).toFixed(2)}%`, sub: (gp) => `Vel ${(((gp["spot_vel_monthly"] as number) ?? 0)*100).toFixed(2)}%/mo · Deribit MS ${(((gp["deribit_ms30_vs_binance_futures"] as number) ?? 0)*100).toFixed(2)}%` },
    { label: "Y3 diluted shares (base)",    value: (gp) => `${(((gp["y3_supply_p50"] as number) ?? 0) / 1e6).toFixed(0)}M`, sub: "Current shares × 1.15 SBC dilution (base)" },
  ],
};

function TokenModelOutputs({ data, tokenKey }: { data: ValuationData; tokenKey: string }) {
  // ── COINBASE: CAPM DR + product-line output ──────────────────────────────
  if (tokenKey === "coinbase") {
    const gp   = data.current_gp as Record<string, unknown>;
    const spot = data.market.spot;

    type CoinScenario = {
      key: string; label: string; is_primary: boolean;
      pv: { p25: number; p50: number; p75: number; p90: number };
      ev: number; prob_above_spot: number; prob_3x: number;
      prob_y2_undiscounted_up_30: number; prob_y2_undiscounted_down_30: number;
      y3_revenue_p50: number; y3_supply_p50: number; y3_mcap_p50: number;
      y3_gp_p50: number;
      y3_revenue_by_product_line_p50: {
        spot: number; derivatives: number; stablecoin_gp: number; other_services: number;
      };
      decay_months: number; ps_center: number; sbc_dilution: number;
    };

    const scenarios  = data.scenarios as unknown as CoinScenario[];
    const DR         = (gp["derived_discount_rate"]  as number) ?? 0.22;
    const beta       = (gp["capm_beta"]              as number) ?? 0;
    const rf         = (gp["risk_free_rate"]          as number) ?? 0;
    const coinVol    = (gp["coin_daily_vol"]          as number) ?? 0;
    const spVol      = (gp["sp500_daily_vol"]         as number) ?? 0;
    const sofr       = (gp["sofr_rate"]               as number) ?? 0;
    const spotMs     = (gp["spot_ms30_vs_binance"]    as number) ?? 0;
    const derivMs    = (gp["deribit_ms30_vs_binance_futures"] as number) ?? 0;
    const spotTake   = 32;
    const derivTake  = 3.88;
    const spotAnn    = ((gp["spot_volume_30d"]    as number) ?? 0) * 12;
    const derivAnn   = ((gp["deribit_volume_30d"] as number) ?? 0) * 12;
    const usdcSupply = (gp["usdc_supply"]            as number) ?? 0;
    const spotRev    = (gp["spot_revenue_ann"]        as number) ?? 0;
    const derivRev   = (gp["deriv_revenue_ann"]       as number) ?? 0;
    const usdcRev    = (gp["usdc_revenue_ann"]        as number) ?? 0;
    const otherRev   = (gp["other_revenue_ann"]       as number) ?? 0;
    const totalRev   = (gp["total_revenue_ann"]       as number) ?? 0;
    const shares     = (gp["shares_outstanding"]      as number) ?? 0;
    const bnAnn      = (gp["binance_spot_annual"]     as number) ?? 7.307e12;

    const pct    = (v: number) => `${(v * 100).toFixed(2)}%`;
    const pctMs  = (v: number) => `${(v * 100).toFixed(2)}%`;
    const bpsStr = (v: number) => `${v.toFixed(0)} bps`;

    const SmCard = ({ label, value, sub }: { label: string; value: string; sub: string }) => (
      <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-5">
        <div className="text-xs font-mono text-gray-500 mb-1 leading-snug">{label}</div>
        <div className="text-3xl font-bold text-gray-900 mb-2">{value}</div>
        <div className="text-xs text-gray-500 leading-snug">{sub}</div>
      </div>
    );

    return (
      <div className="space-y-5">
        <h2 className="text-3xl font-bold text-gray-900">Model Outputs</h2>

        {/* ── CAPM block ───────────────────────────────────── */}
        <div className="bg-[#0a0c14] rounded-xl border border-[#2d3144] p-6">
          <div className="text-xs font-mono text-gray-500 mb-3 tracking-wide">CAPM Discount Rate — derived from live market data</div>
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            {[
              { label: "10Y risk-free rate", val: `${(rf*100).toFixed(2)}%` },
              { label: "CAPM beta (1Y daily)", val: beta.toFixed(2) },
              { label: "COIN daily vol", val: `${(coinVol*100).toFixed(2)}%` },
              { label: "SPX daily vol", val: `${(spVol*100).toFixed(2)}%` },
              { label: "Derived DR", val: `${(DR*100).toFixed(1)}%` },
            ].map(c => (
              <div key={c.label} className="text-center">
                <div className="text-xs text-gray-500 mb-1">{c.label}</div>
                <div className="text-2xl font-bold font-mono text-white">{c.val}</div>
              </div>
            ))}
          </div>
          <p className="text-xs text-gray-500 mt-4">DR = {(rf*100).toFixed(2)}% rf + 5.5% ERP × β{beta.toFixed(2)} = {(DR*100).toFixed(1)}%. Beta from cov(COIN,SPX)/var(SPX) trailing 1Y daily returns.</p>
        </div>

        {/* ── Current snapshot ─────────────────────────────── */}
        <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
          <h3 className="text-base font-semibold text-gray-800 mb-4">Current Snapshot</h3>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { label: "Spot vol 30D (ann.)",  val: fmtLarge(spotAnn),   sub: `MS ${pctMs(spotMs)} vs Binance · ${bpsStr(spotTake)} blended take` },
              { label: "Deribit vol 30D (ann.)", val: fmtLarge(derivAnn),  sub: `MS ${pctMs(derivMs)} vs BNB Fut. · ${derivTake.toFixed(2)} bps take` },
              { label: "USDC supply",           val: fmtLarge(usdcSupply), sub: `${(sofr*100).toFixed(2)}% SOFR × 37.9% share = ${fmtLarge(usdcRev)}/yr` },
              { label: "Ann. revenue proxy",    val: fmtLarge(totalRev),  sub: `Spot ${fmtLarge(spotRev)} · USDC ${fmtLarge(usdcRev)} · deriv ${fmtLarge(derivRev)} · other ${fmtLarge(otherRev)}` },
            ].map(c => (
              <div key={c.label} className="bg-white rounded-lg border border-gray-200 px-4 py-3">
                <div className="text-xs text-gray-400 font-mono mb-1">{c.label}</div>
                <div className="text-xl font-bold text-gray-900 font-mono">{c.val}</div>
                <div className="text-xs text-gray-400 mt-1">{c.sub}</div>
              </div>
            ))}
          </div>
        </div>

        {/* ── Scenario assumptions ─────────────────────────── */}
        <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-200">
            <h3 className="text-base font-semibold text-gray-800">Scenario Assumptions — 50k MC paths each</h3>
            <p className="text-xs text-gray-400 mt-1">Velocity decays linearly to 0 over decay window. P/S: log-normal σ=0.30 around center. Exit price = Y3 revenue × sampled P/S ÷ diluted shares, discounted at {(DR*100).toFixed(1)}% DR.</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  {["CASE","VEL. DECAY WINDOW","EXIT P/S CENTER","SBC DILUTION (3Y)","Y3 DILUTED SHARES","P(ABOVE SPOT)","P(3×)"].map(h => (
                    <th key={h} className={`py-3 text-xs font-medium text-gray-400 uppercase tracking-wider whitespace-nowrap ${h==="CASE"?"text-left px-5":"text-right px-4"}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {scenarios.map(s => (
                  <tr key={s.key} className={`border-b border-gray-100 last:border-0 ${s.is_primary?"bg-white":""}`}>
                    <td className={`px-5 py-3 text-sm ${s.is_primary?"font-semibold text-gray-900":"text-gray-600"}`}>{s.label}</td>
                    <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{s.decay_months}M</td>
                    <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{s.ps_center.toFixed(0)}×</td>
                    <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{s.sbc_dilution.toFixed(2)}×</td>
                    <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{`${((s.y3_supply_p50 ?? 0)/1e6).toFixed(0)}M`}</td>
                    <td className="px-4 py-3 text-right font-mono text-sm font-semibold text-gray-700 whitespace-nowrap">{`${(s.prob_above_spot*100).toFixed(1)}%`}</td>
                    <td className="px-4 py-3 text-right font-mono text-sm font-semibold text-gray-700 whitespace-nowrap">{`${(s.prob_3x*100).toFixed(1)}%`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Product-line outputs ──────────────────────────── */}
        <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-200">
            <h3 className="text-base font-semibold text-gray-800">Product-Line Outputs — Y3 P50</h3>
            <p className="text-xs text-gray-400 mt-1">P50 of Y3 TTM (months 25–36). Spot: Binance regime MC × CB MS velocity-decay × 32bps. Deriv: Deribit regime MC × proxy MS × 35bps. USDC: velocity-decay supply × SOFR path × 50% × 62% net.</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  {["CASE","SPOT REV P50","DERIV REV P50","USDC GP P50","OTHER REV P50","TOTAL REV P50"].map(h => (
                    <th key={h} className={`py-3 text-xs font-medium text-gray-400 uppercase tracking-wider whitespace-nowrap ${h==="CASE"?"text-left px-5":"text-right px-4"}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {scenarios.map(s => {
                  const pl = s.y3_revenue_by_product_line_p50 ?? {} as Record<string, number>;
                  return (
                    <tr key={s.key} className={`border-b border-gray-100 last:border-0 ${s.is_primary?"bg-white":""}`}>
                      <td className={`px-5 py-3 text-sm ${s.is_primary?"font-semibold text-gray-900":"text-gray-600"}`}>{s.label}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm font-semibold text-gray-900 whitespace-nowrap">{fmtLarge(pl.spot ?? 0)}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm font-semibold text-gray-900 whitespace-nowrap">{fmtLarge(pl.derivatives ?? 0)}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm font-semibold text-gray-900 whitespace-nowrap">{fmtLarge(pl.stablecoin_gp ?? 0)}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm font-semibold text-gray-900 whitespace-nowrap">{fmtLarge(pl.other_services ?? 0)}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm font-bold text-gray-900 whitespace-nowrap">{fmtLarge(s.y3_revenue_p50 ?? 0)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Valuation chain ───────────────────────────────── */}
        <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-200">
            <h3 className="text-base font-semibold text-gray-800">Valuation Chain — Real MC Percentiles</h3>
            <p className="text-xs text-gray-400 mt-1">Y3 revenue × sampled P/S (log-normal σ=0.30) ÷ diluted shares → discounted at {(DR*100).toFixed(1)}% CAPM DR. P25/P50/P75/P90 from 50k paths. EV = arithmetic mean (fat-tail boosted).</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  {["CASE","Y3 REV P50","MCAP P50","DILUTED SHARES","P25","P50","P75","P90","P(SPOT)","EV"].map(h => (
                    <th key={h} className={`py-3 text-xs font-medium text-gray-400 uppercase tracking-wider whitespace-nowrap ${h==="CASE"?"text-left px-5":"text-right px-4"}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {scenarios.map(s => {
                  const pColor = s.prob_above_spot >= 0.5 ? "#15803d" : s.prob_above_spot >= 0.35 ? "#a16207" : "#b91c1c";
                  return (
                    <tr key={s.key} className={`border-b border-gray-100 last:border-0 ${s.is_primary?"bg-white":""}`}>
                      <td className={`px-5 py-3 text-sm ${s.is_primary?"font-semibold text-gray-900":"text-gray-600"}`}>{s.label}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{fmtLarge(s.y3_revenue_p50 ?? 0)}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{fmtLarge(s.y3_mcap_p50 ?? 0)}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{`${((s.y3_supply_p50 ?? 0)/1e6).toFixed(0)}M`}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm text-gray-500 whitespace-nowrap">{fmtPrice(s.pv.p25)}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm font-semibold text-gray-900 whitespace-nowrap">{fmtPrice(s.pv.p50)}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm text-gray-500 whitespace-nowrap">{fmtPrice(s.pv.p75)}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm text-gray-400 whitespace-nowrap">{fmtPrice(s.pv.p90)}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm font-semibold whitespace-nowrap" style={{ color: pColor }}>
                        {pct(s.prob_above_spot)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{fmtPrice(s.ev)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── 4 summary cards ───────────────────────────────── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <SmCard
            label="Y3 total revenue — base P50"
            value={fmtLarge((gp["y3_revenue_p50"] as number) ?? 0)}
            sub={`Spot ${fmtLarge((gp["y3_spot_revenue_p50"] as number) ?? 0)} · USDC ${fmtLarge((gp["y3_usdc_revenue_p50"] as number) ?? 0)} · deriv+other ${fmtLarge(((gp["y3_deriv_revenue_p50"] as number) ?? 0) + ((gp["y3_other_revenue_p50"] as number) ?? 0))}`}
          />
          <SmCard
            label="Base P50 PV / COIN"
            value={fmtPrice(scenarios.find(s => s.is_primary)?.pv.p50 ?? 0)}
            sub={`P25 ${fmtPrice(scenarios.find(s => s.is_primary)?.pv.p25 ?? 0)} · P75 ${fmtPrice(scenarios.find(s => s.is_primary)?.pv.p75 ?? 0)} · P90 ${fmtPrice(scenarios.find(s => s.is_primary)?.pv.p90 ?? 0)}`}
          />
          <SmCard
            label="Derived discount rate"
            value={`${(DR * 100).toFixed(1)}%`}
            sub={`β${beta.toFixed(2)} (1Y cov/var) · rf ${(rf*100).toFixed(2)}% · COIN vol ${(coinVol*100).toFixed(1)}%/day`}
          />
          <SmCard
            label="Current P/S (market)"
            value={`${((gp["coin_ps_current"] as number) ?? 0).toFixed(1)}×`}
            sub={`Current COIN market cap / annualized revenue proxy`}
          />
        </div>

        {/* ── Revenue Semantics ─────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 pt-2">
          <div className="flex flex-col justify-center">
            <h2 className="text-3xl font-bold text-gray-900 mb-4">Revenue Semantics</h2>
            <p className="text-gray-500 text-base leading-relaxed">
              Driver-based model replaces P&L extrapolation with observable volumes × market-share × take-rate for spot and derivatives. USDC and other services use independent manual scenarios.
            </p>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <ul className="space-y-4 text-sm text-gray-700 leading-relaxed">
              <li><span className="font-bold text-gray-900">Spot:</span> Binance spot ({`$${(bnAnn/1e12).toFixed(1)}T`}/yr 2025) × current MS {pctMs(spotMs)} × {bpsStr(spotTake)} blended. Take calibrated from Q1-2025: $1.26B / $396B = 31.8 bps.</li>
              <li><span className="font-bold text-gray-900">Deribit (Coinbase-owned):</span> Deribit total ({fmtLarge(((gp["deribit_volume_30d"] as number) ?? 0) * 12)}/yr) × current MS {pctMs(derivMs)} vs Binance Futures × 3.88 bps take (calibrated Q1-2026: ~$544M ann). CDE retail adds ~$200M ann at 119 bps on small notional.</li>
              <li><span className="font-bold text-gray-900">USDC:</span> {fmtLarge(usdcSupply)} supply × {(sofr*100).toFixed(2)}% SOFR × 37.9% Coinbase net share = {fmtLarge(usdcRev)}/yr (calibrated Q1-2026: $1.22B ann). SOFR mean-reverts to 2.5% long-run.</li>
              <li><span className="font-bold text-gray-900">Other services:</span> Staking (cbETH), custody, subscriptions, Base L2 = ~17% of spot+derivatives revenue (Q4-2024 empirical ratio).</li>
              <li><span className="font-bold text-gray-900">Discount rate:</span> CAPM from live market data — not fixed. High COIN beta (~{beta.toFixed(1)}×) drives the {(DR*100).toFixed(1)}% DR; this re-prices automatically each run.</li>
            </ul>
          </div>
        </div>

      </div>
    );
  }

  // ── BP: driver-based product-line output ────────────────────────────────
  if (tokenKey === "bp") {
    const gp   = data.current_gp as Record<string, unknown>;
    const spot = data.market.spot;

    type BpScenario = {
      key: string; label: string; is_primary: boolean;
      pv: { p25: number; p50: number; p75: number; p90: number };
      ev: number; prob_above_spot: number; prob_3x: number;
      y3_perps_volume_ann: number; y3_spot_volume_ann: number;
      y3_perps_ms: number; y3_spot_ms: number;
      y3_perps_revenue: number; y3_spot_revenue: number; y3_securities_revenue: number;
      y3_total_revenue: number; y3_company_val: number; y3_equity_pool: number;
      y3_supply_p50: number; ps_multiple: number;
      perps_take_rate_bps: number; spot_take_rate_bps: number; denom_growth: number;
    };

    const scenarios = data.scenarios as unknown as BpScenario[];
    const perpsMs   = (gp["perp_ms30_vs_binance_futures"] as number) ?? 0;
    const spotMs    = (gp["spot_ms30_vs_binance_spot"]    as number) ?? 0;
    const perpsTake = (gp["perp_take_rate_bps"]           as number) ?? 1.5;
    const spotTake  = (gp["spot_take_rate_bps"]           as number) ?? 9.5;
    const perpsAnn  = (gp["perp_volume_30d_ann"]          as number) ?? 0;
    const spotAnn   = (gp["spot_volume_30d_ann"]          as number) ?? 0;
    const perpsRev  = (gp["perp_revenue_ann"]             as number) ?? 0;
    const spotRev   = (gp["spot_revenue_ann"]             as number) ?? 0;
    const totalRev  = (gp["total_revenue_ann"]            as number) ?? 0;
    const bnFutAnn  = (gp["binance_futures_annual"]       as number) ?? 25.241e12;
    const bnSptAnn  = (gp["binance_spot_annual"]          as number) ?? 7.307e12;

    const pct  = (v: number) => `${(v * 100).toFixed(2)}%`;
    const pctMs = (v: number) => `${(v * 100).toFixed(3)}%`;
    const bps  = (v: number) => `${v.toFixed(2)} bps`;

    const SmCard = ({ label, value, sub }: { label: string; value: string; sub: string }) => (
      <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-5">
        <div className="text-xs font-mono text-gray-500 mb-1 leading-snug">{label}</div>
        <div className="text-3xl font-bold text-gray-900 mb-2">{value}</div>
        <div className="text-xs text-gray-500 leading-snug">{sub}</div>
      </div>
    );

    return (
      <div className="space-y-5">
        <h2 className="text-3xl font-bold text-gray-900">Model Outputs</h2>

        {/* ── Current snapshot ─────────────────────────────── */}
        <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
          <h3 className="text-base font-semibold text-gray-800 mb-4">Current Snapshot</h3>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { label: "30D Perps volume (ann.)", val: fmtLarge(perpsAnn),  sub: `MS ${pctMs(perpsMs)} vs Binance futures` },
              { label: "30D Spot volume (ann.)",  val: fmtLarge(spotAnn),   sub: `MS ${pctMs(spotMs)} vs Binance spot` },
              { label: "Take rate: perps / spot", val: `${bps(perpsTake)} / ${bps(spotTake)}`, sub: "Perps derived from DL fees; spot taker blended" },
              { label: "Ann. revenue proxy",      val: fmtLarge(totalRev),  sub: `Perps ${fmtLarge(perpsRev)} · spot ${fmtLarge(spotRev)}` },
            ].map(c => (
              <div key={c.label} className="bg-white rounded-lg border border-gray-200 px-4 py-3">
                <div className="text-xs text-gray-400 font-mono mb-1">{c.label}</div>
                <div className="text-xl font-bold text-gray-900 font-mono">{c.val}</div>
                <div className="text-xs text-gray-400 mt-1">{c.sub}</div>
              </div>
            ))}
          </div>
        </div>

        {/* ── Scenario assumptions table ──────────────────── */}
        <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-200">
            <h3 className="text-base font-semibold text-gray-800">Scenario Assumptions</h3>
            <p className="text-xs text-gray-400 mt-1">Market share multiplier applied to current 30D MS; supply linked to Phase-2 milestone achievements.</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  {["CASE","PERPS MS MULT","SPOT MS MULT","DENOM GROWTH","P/S","SECURITIES Y3","SUPPLY"].map(h => (
                    <th key={h} className={`py-3 text-xs font-medium text-gray-400 uppercase tracking-wider whitespace-nowrap ${h==="CASE"?"text-left px-5":"text-right px-4"}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {scenarios.map(s => {
                  const perpsMsMult = perpsMs > 0 ? s.y3_perps_ms / perpsMs : 0;
                  const spotMsMult  = spotMs > 0  ? s.y3_spot_ms  / spotMs  : 0;
                  return (
                    <tr key={s.key} className={`border-b border-gray-100 last:border-0 ${s.is_primary?"bg-white":""}`}>
                      <td className={`px-5 py-3 text-sm ${s.is_primary?"font-semibold text-gray-900":"text-gray-600"}`}>{s.label}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{perpsMsMult.toFixed(2)}×</td>
                      <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{spotMsMult.toFixed(2)}×</td>
                      <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{s.denom_growth.toFixed(2)}×</td>
                      <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{s.ps_multiple}×</td>
                      <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{fmtLarge(s.y3_securities_revenue)}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{`${(s.y3_supply_p50 / 1e6).toFixed(0)}M`}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Product-line detail table ────────────────────── */}
        <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-200">
            <h3 className="text-base font-semibold text-gray-800">Product-Line Outputs</h3>
            <p className="text-xs text-gray-400 mt-1">Y3 volume, market share, and revenue by product. Perps/spot use Binance denominator × Y3 MS × take-rate.</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  {["CASE","Y3 PERPS VOL","PERPS MS","Y3 SPOT VOL","SPOT MS","PERPS REV","SPOT REV","SECURITIES REV","TOTAL REV"].map(h => (
                    <th key={h} className={`py-3 text-xs font-medium text-gray-400 uppercase tracking-wider whitespace-nowrap ${h==="CASE"?"text-left px-5":"text-right px-4"}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {scenarios.map(s => (
                  <tr key={s.key} className={`border-b border-gray-100 last:border-0 ${s.is_primary?"bg-white":""}`}>
                    <td className={`px-5 py-3 text-sm ${s.is_primary?"font-semibold text-gray-900":"text-gray-600"}`}>{s.label}</td>
                    <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{fmtLarge(s.y3_perps_volume_ann)}</td>
                    <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{pctMs(s.y3_perps_ms)}</td>
                    <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{fmtLarge(s.y3_spot_volume_ann)}</td>
                    <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{pctMs(s.y3_spot_ms)}</td>
                    <td className="px-4 py-3 text-right font-mono text-sm font-semibold text-gray-900 whitespace-nowrap">{fmtLarge(s.y3_perps_revenue)}</td>
                    <td className="px-4 py-3 text-right font-mono text-sm font-semibold text-gray-900 whitespace-nowrap">{fmtLarge(s.y3_spot_revenue)}</td>
                    <td className="px-4 py-3 text-right font-mono text-sm font-semibold text-gray-900 whitespace-nowrap">{fmtLarge(s.y3_securities_revenue)}</td>
                    <td className="px-4 py-3 text-right font-mono text-sm font-bold text-gray-900 whitespace-nowrap">{fmtLarge(s.y3_total_revenue)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Valuation chain table ────────────────────────── */}
        <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-200">
            <h3 className="text-base font-semibold text-gray-800">Valuation Chain</h3>
            <p className="text-xs text-gray-400 mt-1">Total revenue → company valuation → 20% equity pool → discounted PV per BP. P(Spot) uses log-normal σ=1.0.</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  {["CASE","TOTAL REV","CO. VAL","EQUITY POOL","SUPPLY","PV / BP","VS SPOT","P(SPOT)"].map(h => (
                    <th key={h} className={`py-3 text-xs font-medium text-gray-400 uppercase tracking-wider whitespace-nowrap ${h==="CASE"?"text-left px-5":"text-right px-4"}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {scenarios.map(s => {
                  const vsSpot  = spot > 0 ? (s.pv.p50 / spot - 1) * 100 : 0;
                  const pColor  = s.prob_above_spot >= 0.5 ? "#15803d" : s.prob_above_spot >= 0.35 ? "#a16207" : "#b91c1c";
                  return (
                    <tr key={s.key} className={`border-b border-gray-100 last:border-0 ${s.is_primary?"bg-white":""}`}>
                      <td className={`px-5 py-3 text-sm ${s.is_primary?"font-semibold text-gray-900":"text-gray-600"}`}>{s.label}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{fmtLarge(s.y3_total_revenue)}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{fmtLarge(s.y3_company_val)}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{fmtLarge(s.y3_equity_pool)}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{`${(s.y3_supply_p50/1e6).toFixed(0)}M`}</td>
                      <td className="px-4 py-3 text-right font-mono text-sm font-semibold text-gray-900 whitespace-nowrap">{fmtPrice(s.pv.p50)}</td>
                      <td className={`px-4 py-3 text-right font-mono text-sm font-semibold whitespace-nowrap ${vsSpot>=0?"text-green-700":"text-red-700"}`}>
                        {`${vsSpot>=0?"+":""}${vsSpot.toFixed(0)}%`}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-sm font-semibold whitespace-nowrap" style={{ color: pColor }}>
                        {pct(s.prob_above_spot)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── 4 summary cards ─────────────────────────────── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <SmCard
            label="Y3 total revenue (base)"
            value={fmtLarge((gp["y3_revenue_p50"] as number) ?? 0)}
            sub={`Perps ${fmtLarge((gp["y3_perps_revenue_p50"] as number) ?? 0)} · spot ${fmtLarge((gp["y3_spot_revenue_p50"] as number) ?? 0)} · sec ${fmtLarge((gp["y3_securities_revenue_base"] as number) ?? 0)}`}
          />
          <SmCard
            label="Y3 company valuation (base)"
            value={fmtLarge((gp["y3_company_val_p50"] as number) ?? 0)}
            sub={`At 7× P/S on base Y3 total revenue`}
          />
          <SmCard
            label="Y3 equity pool (base)"
            value={fmtLarge((gp["y3_equity_pool_p50"] as number) ?? 0)}
            sub={`20% of company valuation; shared pro-rata by stakers`}
          />
          <SmCard
            label="Y3 staking supply (base)"
            value={`${(((gp["y3_supply_p50"] as number) ?? 0) / 1e6).toFixed(0)}M BP`}
            sub={`Phase 1 (250M) + partial Phase 2 unlocks on milestones`}
          />
        </div>

        {/* ── Revenue Semantics ─────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 pt-2">
          <div className="flex flex-col justify-center">
            <h2 className="text-3xl font-bold text-gray-900 mb-4">Revenue Semantics</h2>
            <p className="text-gray-500 text-base leading-relaxed">
              Driver-based model replaces fixed revenue narratives with observable volume × market-share × take-rate mechanics for spot and perps. Securities use manual scenarios.
            </p>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <ul className="space-y-4 text-sm text-gray-700 leading-relaxed">
              <li><span className="font-bold text-gray-900">Spot:</span> Binance spot denominator (Blockworks {`$${(bnSptAnn/1e12).toFixed(1)}T`}/yr 2025) × BP spot MS × {spotTake.toFixed(1)} bps taker-blended take-rate.</li>
              <li><span className="font-bold text-gray-900">Perps:</span> Binance futures denominator (Blockworks {`$${(bnFutAnn/1e12).toFixed(1)}T`}/yr 2025) × BP perps MS × {perpsTake.toFixed(1)} bps clean take-rate.</li>
              <li><span className="font-bold text-gray-900">Securities:</span> Manual bear/base/bull assumptions ($5M / $40M / $120M Y3 annual revenue); Backpack holds regulatory licenses to offer tokenized equities in select jurisdictions.</li>
              <li><span className="font-bold text-gray-900">Supply:</span> 250M Phase 1 always eligible. Phase 2 (375M) unlocks on KPI milestones — bear assumes none unlock, base assumes ~1/3, bull assumes majority.</li>
              <li><span className="font-bold text-gray-900">Equity claim:</span> Stakers locking BP for 1+ year receive 20% of Backpack company equity at IPO. No buyback or revenue-share exists; IPO non-occurrence is the primary tail risk.</li>
            </ul>
          </div>
        </div>
      </div>
    );
  }

  // ── CARDS: velocity-decay scenario table + 4 output cards ───────────────
  if (tokenKey === "cards") {
    const gp      = data.current_gp as Record<string, unknown>;
    const spot    = data.market.spot;
    const fdvSup  = data.market.max_supply;
    const velScens = (gp["velocity_scenarios"] as Array<{
      label: string; decay_months: number; y3_gmv: number; y3_gp: number; pv: number;
    }>) ?? [];
    const netSpread = gp["net_spread"]        as number ?? 0;
    const gpConv    = gp["true_gp_conversion"] as number ?? 0;
    const multiple  = data.model.multiple;
    const y3GpBase  = gp["y3_gp_base"]        as number ?? 0;
    const floatSup  = gp["y3_supply_float"]    as number ?? gp["float_supply_y3"] as number ?? 0;

    const SmCard = ({ label, value, sub }: { label: string; value: string; sub: string }) => (
      <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-5">
        <div className="text-xs font-mono text-gray-500 mb-1 leading-snug">{label}</div>
        <div className="text-3xl font-bold text-gray-900 mb-2">{value}</div>
        <div className="text-xs text-gray-500 leading-snug">{sub}</div>
      </div>
    );

    return (
      <div className="space-y-5">
        <h2 className="text-3xl font-bold text-gray-900">Model Outputs</h2>
        {/* Scenario table */}
        <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  {["CASE","Y3 GMV","NET SPREAD","GP CONV.","Y3 GP","GP MULT.","PV / CARDS","VS SPOT"].map((h) => (
                    <th key={h} className={`py-4 text-xs font-medium text-gray-400 uppercase tracking-wider whitespace-nowrap ${h === "CASE" ? "text-left px-5" : "text-right px-4"}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {velScens.map((s) => {
                  const vsSpot = spot > 0 ? (s.pv / spot - 1) * 100 : 0;
                  const isWeighted = s.label.startsWith("Weighted");
                  return (
                    <tr key={s.label} className={`border-b border-gray-100 last:border-0 ${isWeighted ? "bg-white" : ""}`}>
                      <td className={`px-5 py-4 text-sm ${isWeighted ? "font-semibold text-gray-900" : "text-gray-600"}`}>{s.label}</td>
                      <td className="px-4 py-4 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{fmtLarge(s.y3_gmv)}</td>
                      <td className="px-4 py-4 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{`${(netSpread * 100).toFixed(2)}%`}</td>
                      <td className="px-4 py-4 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{`${(gpConv * 100).toFixed(0)}%`}</td>
                      <td className="px-4 py-4 text-right font-mono text-sm font-semibold text-gray-900 whitespace-nowrap">{fmtLarge(s.y3_gp)}</td>
                      <td className="px-4 py-4 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{`${multiple}x`}</td>
                      <td className="px-4 py-4 text-right font-mono text-sm font-semibold text-gray-900 whitespace-nowrap">{fmtPrice(s.pv)}</td>
                      <td className={`px-4 py-4 text-right font-mono text-sm font-semibold whitespace-nowrap ${vsSpot >= 0 ? "text-green-700" : "text-red-700"}`}>
                        {`${vsSpot >= 0 ? "+" : ""}${vsSpot.toLocaleString("en-US", { maximumFractionDigits: 0 })}%`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
        {/* 4 bottom cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <SmCard
            label="Y3 aggregate GP"
            value={fmtLarge(y3GpBase)}
            sub={`Base 12M-decay GP after capped 7D/30D GMV velocity and ${(gpConv * 100).toFixed(0)}% conversion.`}
          />
          <SmCard
            label="Y3 product split"
            value={fmtLarge(y3GpBase)}
            sub="Gacha/marketplace only; no separate staking, yield, or card-financing line modeled."
          />
          <SmCard
            label="Y3 effective supply"
            value={`${(floatSup / 1e9).toFixed(3)}B`}
            sub="Float-friendly released non-Foundation supply by Nov 2027."
          />
          <SmCard
            label="Treasury cash / buyback"
            value="$0"
            sub="Excluded until holders revenue or confirmed buyback wallet data appears."
          />
        </div>

        {/* GP Conversion Sensitivity */}
        {(() => {
          const baseGp  = gp["y3_gp_p50"]    as number ?? 0;
          const primaryScen = data.scenarios?.find((s: { is_primary?: boolean }) => s.is_primary);
          const basePv  = (primaryScen as { pv?: { p50?: number } } | undefined)?.pv?.p50 ?? (gp["weighted_pv"] as number ?? 0);
          if (gpConv === 0 || baseGp === 0 || basePv === 0) return null;
          const gpRates = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60];
          return (
            <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-200">
                <h3 className="text-base font-semibold text-gray-800">Gross Profit Estimate Sensitivity</h3>
                <p className="text-xs text-gray-400 mt-1">Varies GP conversion rate on base-scenario Y3 GP ($535M GMV × 8.4% margin); PV uses full 3-year DR³ discount — 60% base matches the card P50. All other model inputs held constant.</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200">
                      {["GP CONV.", "Y3 GP", "PV / CARDS", "VS SPOT"].map((h) => (
                        <th key={h} className={`py-3 text-xs font-medium text-gray-400 uppercase tracking-wider whitespace-nowrap ${h === "GP CONV." ? "text-left px-5" : "text-right px-4"}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {gpRates.map((rate) => {
                      const scaleRatio = rate / gpConv;
                      const sensGp = baseGp * scaleRatio;
                      const sensPv = basePv * scaleRatio;
                      const vsSpot = spot > 0 ? (sensPv / spot - 1) * 100 : 0;
                      const isBase = Math.abs(rate - gpConv) < 0.005;
                      return (
                        <tr key={rate} className={`border-b border-gray-100 last:border-0 ${isBase ? "bg-blue-50" : ""}`}>
                          <td className={`px-5 py-3 text-sm ${isBase ? "font-semibold text-blue-700" : "text-gray-600"}`}>
                            {`${(rate * 100).toFixed(0)}%${isBase ? "  ← base" : ""}`}
                          </td>
                          <td className="px-4 py-3 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{fmtLarge(sensGp)}</td>
                          <td className={`px-4 py-3 text-right font-mono text-sm font-semibold whitespace-nowrap ${isBase ? "text-blue-700" : "text-gray-900"}`}>{fmtPrice(sensPv)}</td>
                          <td className={`px-4 py-3 text-right font-mono text-sm font-semibold whitespace-nowrap ${vsSpot >= 0 ? "text-green-700" : "text-red-700"}`}>
                            {`${vsSpot >= 0 ? "+" : ""}${vsSpot.toLocaleString("en-US", { maximumFractionDigits: 0 })}%`}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })()}

        {/* Revenue Semantics */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 pt-2">
          <div className="flex flex-col justify-center">
            <h2 className="text-3xl font-bold text-gray-900 mb-4">Revenue Semantics</h2>
            <p className="text-gray-500 text-base leading-relaxed">
              Observed data, inferred GP conversion, and missing velocity reporting are separated so the model is easier to audit.
            </p>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <ul className="space-y-4 text-sm text-gray-700 leading-relaxed">
              <li><span className="font-bold text-gray-900">Primary model:</span> GMV × GMV velocity path × net revenue spread × true GP conversion × GP multiple, discounted back 3 years.</li>
              <li><span className="font-bold text-gray-900">Velocity:</span> daily sales/volume is used for GMV growth velocity. Until the 30D/180D window exists, the model uses capped 7D/30D velocity only, then tests linear decay to zero over 6, 12, and 24 months; true inventory turnover velocity is still unavailable because reporting does not expose card turns, inventory base, or repeat-sale cohort data.</li>
              <li><span className="font-bold text-gray-900">Net revenue:</span> DefiLlama revenue equals Gacha sales plus fiat pack sales plus royalty fees minus pack buyback spends.</li>
              <li><span className="font-bold text-gray-900">Unit economics:</span> 60% base GP conversion is a placeholder for grading, shipping, custody, payment fees, rewards, support, and marketing.</li>
              <li><span className="font-bold text-gray-900">Supply:</span> primary denominator is 1.265B released non-Foundation supply; the 735.1M Foundation bucket remains a full-FDV sensitivity.</li>
              <li><span className="font-bold text-gray-900">Value capture:</span> CARDS buybacks are not modeled until the buyback wallet is confirmed and holders revenue is non-zero.</li>
            </ul>
          </div>
        </div>
      </div>
    );
  }

  // ── JUP: scenario comparison table + GP/volume/supply cards ─────────────
  if (tokenKey === "jup") {
    const gp      = data.current_gp as Record<string, unknown>;
    const fmtChg  = (v: number) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
    const y3pcts  = gp["y3_vs_current_pct"] as {
      entity_gp_pct: number; perps_gp_pct: number; spot_gp_pct: number;
      perps_daily_volume_pct: number; spot_daily_volume_pct: number; effective_supply_pct: number;
    } | undefined;
    const y3gp       = gp["y3_gp_p50"]                    as number ?? 0;
    const y3perpsGp  = gp["y3_perps_gp_p50"]              as number ?? 0;
    const y3spotGp   = gp["y3_spot_gp_p50"]               as number ?? 0;
    const y3perpVol  = gp["y3_perps_daily_mean_volume_p50"] as number ?? 0;
    const y3spotVol  = gp["y3_spot_daily_mean_volume_p50"] as number ?? 0;
    const y3supply   = gp["y3_supply_p50"]                 as number ?? 0;

    const SmCard = ({ label, value, sub }: { label: string; value: string; sub: string }) => (
      <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-5">
        <div className="text-xs font-mono text-gray-500 mb-1 leading-snug">{label}</div>
        <div className="text-3xl font-bold text-gray-900 mb-2">{value}</div>
        <div className="text-xs text-gray-500 leading-snug">{sub}</div>
      </div>
    );

    return (
      <div className="space-y-5">
        <h2 className="text-3xl font-bold text-gray-900">Scenario comparison</h2>
        {/* Table */}
        <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  {["CASE","P25","P50","P75","P90","EV","P(SPOT)","2Y +30%","2Y -30%"].map((h) => (
                    <th key={h} className={`py-4 text-xs font-medium text-gray-400 uppercase tracking-wider whitespace-nowrap ${h === "CASE" ? "text-left px-5" : "text-right px-4"}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.scenarios.map((s) => {
                  const probColor = s.prob_above_spot >= 0.5 ? "#15803d" : s.prob_above_spot >= 0.35 ? "#a16207" : "#b91c1c";
                  return (
                    <tr key={s.key} className={`border-b border-gray-100 last:border-0 ${s.is_primary ? "bg-white" : ""}`}>
                      <td className={`px-5 py-4 text-sm ${s.is_primary ? "font-semibold text-gray-900" : "text-gray-600"}`}>{s.label}</td>
                      {(["p25","p50","p75","p90"] as const).map((p) => (
                        <td key={p} className={`px-4 py-4 text-right font-mono text-sm whitespace-nowrap ${p === "p50" ? "font-semibold text-gray-900" : "text-gray-700"}`}>{fmtPrice(s.pv[p])}</td>
                      ))}
                      <td className="px-4 py-4 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{fmtPrice(s.ev)}</td>
                      <td className="px-4 py-4 text-right font-mono text-sm font-semibold whitespace-nowrap" style={{ color: probColor }}>{pct(s.prob_above_spot)}</td>
                      <td className="px-4 py-4 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{s.prob_spot_up_30_2y   != null ? pct(s.prob_spot_up_30_2y)   : "—"}</td>
                      <td className="px-4 py-4 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{s.prob_spot_down_30_2y != null ? pct(s.prob_spot_down_30_2y) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
        {/* Cards row 1: 5 GP/volume cards */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
          <SmCard
            label="Y3 TTM entity GP P50"
            value={fmtLarge(y3gp)}
            sub={`${y3pcts ? fmtChg(y3pcts.entity_gp_pct) : "—"} vs current annualized GP.`}
          />
          <SmCard
            label="Y3 Perps GP P50"
            value={fmtLarge(y3perpsGp)}
            sub={`${y3pcts ? fmtChg(y3pcts.perps_gp_pct) : "—"} vs current annualized perps GP.`}
          />
          <SmCard
            label="Y3 Spot GP P50"
            value={fmtLarge(y3spotGp)}
            sub={`${y3pcts ? fmtChg(y3pcts.spot_gp_pct) : "—"} vs current annualized spot GP.`}
          />
          <SmCard
            label="Y3 perps daily volume"
            value={fmtLarge(y3perpVol)}
            sub={`${y3pcts ? fmtChg(y3pcts.perps_daily_volume_pct) : "—"} vs current daily perps volume.`}
          />
          <SmCard
            label="Y3 spot daily volume"
            value={fmtLarge(y3spotVol)}
            sub={`${y3pcts ? fmtChg(y3pcts.spot_daily_volume_pct) : "—"} vs current daily spot volume.`}
          />
        </div>
        {/* Cards row 2: supply */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
          <SmCard
            label="Effective supply P50"
            value={`${(y3supply / 1e9).toFixed(2)}B`}
            sub={`${y3pcts ? fmtChg(y3pcts.effective_supply_pct) : "—"} vs current circulating supply.`}
          />
        </div>
      </div>
    );
  }

  // ── SKY: scenario comparison table + 5 cards ────────────────────────────
  if (tokenKey === "sky") {
    const primary = data.scenarios.find((s) => s.is_primary) ?? data.scenarios[0];
    const gp      = data.current_gp as Record<string, number>;
    const fmtChg  = (v: number) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
    return (
      <div className="space-y-5">
        <h2 className="text-3xl font-bold text-gray-900">Scenario comparison</h2>
        {/* Table */}
        <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  {["CASE","P25","P50","P75","P90","EV","P(SPOT)","2Y +30%","2Y -30%","P(3X)"].map((h) => (
                    <th key={h} className={`py-4 text-xs font-medium text-gray-400 uppercase tracking-wider whitespace-nowrap ${h === "CASE" ? "text-left px-5" : "text-right px-4"}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.scenarios.map((s) => {
                  const probColor = s.prob_above_spot >= 0.5 ? "#15803d" : s.prob_above_spot >= 0.35 ? "#a16207" : "#b91c1c";
                  return (
                    <tr key={s.key} className={`border-b border-gray-100 last:border-0 ${s.is_primary ? "bg-white" : ""}`}>
                      <td className={`px-5 py-4 text-sm ${s.is_primary ? "font-semibold text-gray-900" : "text-gray-600"}`}>{s.label}</td>
                      {(["p25","p50","p75","p90"] as const).map((p) => (
                        <td key={p} className={`px-4 py-4 text-right font-mono text-sm whitespace-nowrap ${p === "p50" ? "font-semibold text-gray-900" : "text-gray-700"}`}>{fmtPrice(s.pv[p])}</td>
                      ))}
                      <td className="px-4 py-4 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{fmtPrice(s.ev)}</td>
                      <td className="px-4 py-4 text-right font-mono text-sm font-semibold whitespace-nowrap" style={{ color: probColor }}>{pct(s.prob_above_spot)}</td>
                      <td className="px-4 py-4 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{s.prob_spot_up_30_2y   != null ? pct(s.prob_spot_up_30_2y)   : "—"}</td>
                      <td className="px-4 py-4 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{s.prob_spot_down_30_2y != null ? pct(s.prob_spot_down_30_2y) : "—"}</td>
                      <td className="px-4 py-4 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{s.prob_3x              != null ? pct(s.prob_3x)              : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
        {/* 5 bottom cards */}
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          {[
            {
              label: "Y3 total Sky\nstable P50",
              value: fmtLarge(gp["y3_total_stable_supply_p50"]),
              sub: `${fmtChg(gp["y3_total_stable_supply_change_vs_current"])} vs current official USDS + DAI.`,
            },
            {
              label: "Y3 USDS supply P50",
              value: fmtLarge(gp["y3_usds_supply_p50"]),
              sub: `${fmtChg(gp["y3_usds_supply_change_vs_current"])} vs current USDS.`,
            },
            {
              label: "Y3 TTM GP P50",
              value: fmtLarge(gp["y3_gp_p50"]),
              sub: `${fmtChg(gp["y3_gp_change_vs_current"])} vs current annualized GP.`,
            },
            {
              label: "Y3 avg money-\nmarket TVL",
              value: fmtLarge(gp["y3_avg_money_market_tvl_p50"]),
              sub: `${fmtChg(gp["y3_money_market_tvl_change_vs_current"])} vs current denominator.`,
            },
            {
              label: "Treasury cash P50",
              value: fmtLarge(gp["treasury_cash_p50"]),
              sub: "Cumulative positive net profit over 3 years.",
            },
          ].map((c) => (
            <div key={c.label} className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] px-5 py-4">
              <div className="text-xs text-gray-500 font-mono mb-1 whitespace-pre-line">{c.label}</div>
              <div className="text-2xl font-bold text-gray-900 font-mono leading-tight">{c.value}</div>
              <div className="text-xs text-gray-500 mt-1 leading-relaxed">{c.sub}</div>
            </div>
          ))}
        </div>

        {/* Row 2: Y3 GP split + backtest */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {/* Y3 GP product-line split */}
          <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
            <h3 className="text-2xl font-bold text-gray-900 mb-5">Y3 GP product-line split</h3>
            <table className="w-full"><tbody>
              {[
                ["Gross income",  fmtLarge(gp["y3_gross_income_p50"])],
                ["Savings cost",  `$-${fmtLarge(gp["y3_savings_cost_p50"]).replace("$","")}`],
                ["stUSDS cost",   `$-${fmtLarge(gp["y3_stusds_cost_p50"]).replace("$","")}`],
                ["Net GP",        fmtLarge(gp["y3_gp_p50"])],
              ].map(([label, value]) => (
                <tr key={label} className="border-b border-gray-100 last:border-0">
                  <td className="py-3 text-sm text-gray-600 pr-4">{label}</td>
                  <td className="py-3 text-sm font-mono font-semibold text-gray-900 text-right whitespace-nowrap">{value}</td>
                </tr>
              ))}
            </tbody></table>
            <p className="text-xs text-gray-500 mt-4 leading-relaxed">
              Stablecoin economics split, not separate app revenue lines.
            </p>
          </div>
          {/* Historical diagnostic / backtest */}
          {(() => {
            const bt      = data.hist_charts?.backtest;
            const signals = bt?.signals ?? {};
            const fmtRet  = (v: number | null) => v == null ? "n/a" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
            const sigColor: Record<string, string> = { GOOD: "#16a34a", NEUTRAL: "#ca8a04", BAD: "#dc2626" };
            return (
              <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
                <h3 className="text-2xl font-bold text-gray-900 mb-5">Historical diagnostic / backtest</h3>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200">
                      {["SIGNAL","OBS","AVG +30D","AVG +90D","RECENT DATES"].map(h => (
                        <th key={h} className="pb-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider pr-4 last:pr-0">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {["GOOD","NEUTRAL","BAD"].map(sig => {
                      const s = signals[sig];
                      return (
                        <tr key={sig} className="border-b border-gray-100 last:border-0">
                          <td className="py-3 font-semibold text-xs pr-4" style={{ color: sigColor[sig] }}>{sig}</td>
                          <td className="py-3 font-mono text-gray-700 pr-4">{s?.obs ?? 0}</td>
                          <td className="py-3 font-mono text-gray-700 pr-4">{fmtRet(s?.avg_30d ?? null)}</td>
                          <td className="py-3 font-mono text-gray-700 pr-4">{fmtRet(s?.avg_90d ?? null)}</td>
                          <td className="py-3 text-xs text-gray-500">{s?.recent_dates?.slice(0,3).join(", ") || "n/a"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <p className="text-xs text-gray-500 mt-4 leading-relaxed">
                  Latest signal: <span className="font-semibold" style={{ color: sigColor[bt?.latest_signal ?? ""] }}>{bt?.latest_signal}</span>; last realized-return row: {bt?.last_realized_row}. Historical model-shaped diagnostic, not a full MC replay.
                </p>
              </div>
            );
          })()}
        </div>

        {/* Row 3: Historical Mcap/GP + Caveats */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {/* Historical Mcap / GP */}
          {(() => {
            const sc      = data.hist_charts?.secondary_chart;
            const latest  = sc?.data?.[sc.data.length - 1];
            const val     = latest?.value;
            return (
              <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
                <h3 className="text-2xl font-bold text-gray-900 mb-3">Historical Mcap / GP</h3>
                <div className="text-4xl font-bold text-gray-900 mb-3">{val != null ? `${val.toFixed(1)}×` : "—"}</div>
                <p className="text-sm text-gray-500 mb-2 leading-relaxed">{sc?.subtitle}</p>
                <p className="text-sm text-gray-500 leading-relaxed">{sc?.note}</p>
              </div>
            );
          })()}
          {/* Caveats */}
          <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] p-6">
            <h3 className="text-2xl font-bold text-gray-900 mb-5">Caveats</h3>
            <ul className="space-y-2 list-disc list-outside pl-4">
              {(data.caveats ?? []).map((c, i) => (
                <li key={i} className="text-sm text-gray-600 leading-relaxed">{c}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    );
  }

  // ── UNI: custom wide table + 4 cards ────────────────────────────────────
  if (tokenKey === "uni") {
    const primary  = data.scenarios.find((s) => s.is_primary) ?? data.scenarios[0];
    const dexNative = data.scenarios.find((s) => s.key === "full_activation");
    const cols: { label: string; fmt: (s: ValuationScenario) => string }[] = [
      { label: "P50 EOY3\nPrice",            fmt: (s) => fmtPrice(s.y3_price_p50 ?? 0) },
      { label: "P50 EOY3\nMcap",             fmt: (s) => fmtLarge(s.y3_mcap_p50 ?? 0) },
      { label: "P50 EOY Daily\nMean Volume",  fmt: (s) => fmtLarge(s.y3_daily_mean_volume_p50 ?? 0) },
      { label: "P50\nAnnualized GP",         fmt: (s) => fmtLarge(s.y3_gp_p50 ?? 0) },
      { label: "P50 PV",                     fmt: (s) => fmtPrice(s.pv.p50) },
      { label: "EV\nPV/Token",               fmt: (s) => fmtPrice(s.ev) },
      { label: "PV Mcap\nEV",                fmt: (s) => fmtLarge(s.ev_mcap ?? 0) },
      { label: "P(Spot)",                    fmt: (s) => pct(s.prob_above_spot) },
      { label: "2Y\n+30%",                   fmt: (s) => s.prob_spot_up_30_2y   != null ? pct(s.prob_spot_up_30_2y)   : "—" },
      { label: "2Y\n-30%",                   fmt: (s) => s.prob_spot_down_30_2y != null ? pct(s.prob_spot_down_30_2y) : "—" },
      { label: "P(3×)",                      fmt: (s) => s.prob_3x              != null ? pct(s.prob_3x)              : "—" },
    ];
    const pAnn = (primary.y3_daily_mean_volume_p50 ?? 0) * 365;
    return (
      <div className="space-y-5">
        <h2 className="text-3xl font-bold text-gray-900">Model outputs</h2>
        {/* Wide table */}
        <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left px-5 py-4 text-xs font-medium text-gray-400 uppercase tracking-wider whitespace-nowrap">Case</th>
                  {cols.map((c) => (
                    <th key={c.label} className="text-right px-3 py-4 text-xs font-medium text-gray-400 uppercase tracking-wider leading-tight" style={{ whiteSpace: "pre-line" }}>{c.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.scenarios.map((s) => {
                  const probColor = s.prob_above_spot >= 0.5 ? "#15803d" : s.prob_above_spot >= 0.35 ? "#a16207" : "#b91c1c";
                  return (
                    <tr key={s.key} className={`border-b border-gray-100 last:border-0 ${s.is_primary ? "bg-white" : ""}`}>
                      <td className={`px-5 py-4 text-sm max-w-[160px] ${s.is_primary ? "font-semibold text-gray-900" : "text-gray-600"}`}>{s.label}</td>
                      {cols.map((c, i) => (
                        <td key={i} className={`px-3 py-4 text-right font-mono text-sm whitespace-nowrap ${
                          c.label === "P(Spot)" ? "font-semibold" : "text-gray-700"
                        }`} style={c.label === "P(Spot)" ? { color: probColor } : undefined}>
                          {c.fmt(s)}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
        {/* 4 bottom cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] px-5 py-4">
            <div className="text-xs text-gray-500 font-mono mb-1">Y3 GP / supply</div>
            <div className="text-2xl font-bold text-gray-900 font-mono leading-tight">{fmtLarge(primary.y3_gp_p50 ?? 0)} / {((primary.y3_supply_p50 ?? 0) / 1e6).toFixed(0)}M</div>
            <div className="text-xs text-gray-500 mt-1">Primary P50 end-Year-3.</div>
          </div>
          <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] px-5 py-4">
            <div className="text-xs text-gray-500 font-mono mb-1">P50 EOY daily volume</div>
            <div className="text-2xl font-bold text-gray-900 font-mono leading-tight">{fmtLarge(primary.y3_daily_mean_volume_p50 ?? 0)}</div>
            <div className="text-xs text-gray-500 mt-1">Equivalent annualized volume {fmtLarge(pAnn)}.</div>
          </div>
          <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] px-5 py-4">
            <div className="text-xs text-gray-500 font-mono mb-1">DEX-native P50 PV</div>
            <div className="text-2xl font-bold text-gray-900 font-mono leading-tight">{fmtPrice(dexNative?.pv.p50 ?? 0)}</div>
            <div className="text-xs text-gray-500 mt-1">Sensitivity using total DEX denominator.</div>
          </div>
          <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] px-5 py-4">
            <div className="text-xs text-gray-500 font-mono mb-1">3× probability</div>
            <div className="text-2xl font-bold text-gray-900 font-mono leading-tight">{primary.prob_3x != null ? pct(primary.prob_3x) : "—"}</div>
            <div className="text-xs text-gray-500 mt-1">Right-tail metric, not central case.</div>
          </div>
        </div>
      </div>
    );
  }

  const cards = TOKEN_Y3_CARDS[tokenKey];
  if (!cards) return null;

  const gp: Record<string, number> = {
    ...(data.current_gp as Record<string, number>),
    current_circulating_supply: data.market.circulating_supply,
    market_cap: data.market.market_cap,
  };
  const circ = data.market.circulating_supply;
  const spot = data.market.spot;
  const disc = Math.pow(1 + data.model.discount_rate, 3);
  const multiple = data.model.multiple || 15;
  const fullTakeBps = (gp["take_bps_full"] as number | undefined) ?? 0;
  const currentTakeBps = (gp["take_bps_current"] as number | undefined) ?? fullTakeBps;

  const scenarioSupply = (s: ValuationScenario) =>
    s.y3_supply_p50 ?? (s.key.includes("fdv") ? ((data.market.max_supply as number | undefined) ?? circ) : circ);
  const scenarioTakeBps = (s: ValuationScenario) =>
    s.key === "current_state" ? currentTakeBps : fullTakeBps;
  const scenarioP50AnnualGp = (s: ValuationScenario) =>
    s.pv.p50 * scenarioSupply(s) * disc / multiple;
  const scenarioP50DailyMeanVolume = (s: ValuationScenario) => {
    const take = scenarioTakeBps(s);
    return take > 0 ? scenarioP50AnnualGp(s) / (take / 10000) / 365 : 0;
  };


  return (
    <div className="space-y-5">
      <h2 className="text-3xl font-bold text-gray-900">Model Outputs</h2>

      {/* ── Scenario table ──────────────────────────────────────────────── */}
      <div className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200">
                <th className="text-left px-6 py-4 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">Case</th>
                {["P25 PV", "P50 PV", "P75 PV", "P90 PV", "EV"].map((h) => (
                  <th key={h} className="text-right px-4 py-4 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">{h}</th>
                ))}
                <th className="text-right px-4 py-4 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">P(Spot)</th>
                <th className="text-right px-4 py-4 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">2Y +30%</th>
                <th className="text-right px-4 py-4 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">2Y -30%</th>
              </tr>
            </thead>
            <tbody>
              {data.scenarios.map((s) => {
                const probColor = s.prob_above_spot >= 0.5 ? "#15803d" : s.prob_above_spot >= 0.35 ? "#a16207" : "#b91c1c";
                return (
                  <tr key={s.key} className="border-b border-gray-100 last:border-0">
                    <td className={`px-6 py-4 text-sm whitespace-nowrap ${s.is_primary ? "font-semibold text-gray-900" : "text-gray-600"}`}>{s.label}</td>
                    {(["p25", "p50", "p75", "p90"] as const).map((p) => (
                      <td key={p} className={`px-4 py-4 text-right font-mono text-sm whitespace-nowrap ${p === "p50" ? "font-semibold text-gray-900" : "text-gray-700"}`}>
                        {fmtPrice(s.pv[p])}
                      </td>
                    ))}
                    <td className="px-4 py-4 text-right font-mono text-sm text-gray-700 whitespace-nowrap">{fmtPrice(s.ev)}</td>
                    <td className="px-4 py-4 text-right font-mono text-sm font-semibold whitespace-nowrap" style={{ color: probColor }}>
                      {pct(s.prob_above_spot)}
                    </td>
                    <td className="px-4 py-4 text-right font-mono text-sm text-gray-700 whitespace-nowrap">
                      {s.prob_spot_up_30_2y != null ? pct(s.prob_spot_up_30_2y) : "—"}
                    </td>
                    <td className="px-4 py-4 text-right font-mono text-sm text-gray-700 whitespace-nowrap">
                      {s.prob_spot_down_30_2y != null ? pct(s.prob_spot_down_30_2y) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Y3 metric cards ─────────────────────────────────────────────── */}
      <div className={`grid grid-cols-2 ${cards.length === 4 ? "lg:grid-cols-4" : "lg:grid-cols-3"} gap-3`}>
        {cards.map((c) => (
          <div key={c.label} className="bg-[#f8f9fb] rounded-xl border border-[#e2e6f0] px-5 py-4">
            <div className="text-xs text-gray-500 font-mono mb-1">{c.label}</div>
            <div className="text-2xl font-bold text-gray-900 font-mono leading-tight">{c.value(gp)}</div>
            <div className="text-xs text-gray-500 mt-1 leading-relaxed">{typeof c.sub === "function" ? c.sub(gp) : c.sub}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── TokenView ────────────────────────────────────────────────────────────────

function TokenView({ tokenKey, token }: { tokenKey: string; token: TokenResult }) {
  if (token.status === "error") {
    return (
      <div className="bg-[#1a1d29] rounded-xl p-8 border border-red-500/30">
        <div className="text-red-400 font-mono text-sm">{token.error}</div>
      </div>
    );
  }

  const d           = token.data!;
  const primary     = d.scenarios.find((s) => s.is_primary) ?? d.scenarios[0];
  const chartColor  = TOKEN_COLORS[tokenKey] ?? "#60a5fa";
  const spot        = d.market.spot;
  const p50Upside   = spot > 0 ? (primary.pv.p50 / spot - 1) * 100 : 0;
  const dr          = (d.model.discount_rate * 100).toFixed(1);
  const probColor   = primary.prob_above_spot >= 0.5
    ? "green"
    : primary.prob_above_spot >= 0.35
    ? "yellow"
    : "red";

  const gp = d.current_gp;
  const isHypeWithMs = tokenKey === "hype" && typeof gp["ms90_vs_binance"] === "number";
  const isLighterLayout = tokenKey === "lighter" && typeof gp["ms90_vs_binance"] === "number";
  const isEthfiLayout = tokenKey === "ethfi";
  const isUniLayout = tokenKey === "uni";
  const isSkyLayout = tokenKey === "sky";
  const isJupLayout = tokenKey === "jup";
  const isCardsLayout = tokenKey === "cards";
  const velocity = gp["growth_velocity_pp"] as number | undefined;

  return (
    <div className="space-y-5">

      {/* ── Tech score card ──────────────────────────────────────────── */}
      <TechScoreCard tokenKey={tokenKey} />

      {/* ── Metric cards ─────────────────────────────────────────────── */}
      {isHypeWithMs ? (
        /* HYPE-specific cards matching the dashboard design */
        <div className="space-y-3">
          {/* Row 1: 5 cards */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            <MetricCard
              label="Spot / mcap / circ"
              value={fmtPrice(spot)}
              sub={`Mcap ${fmtLarge(d.market.market_cap)} · circ ${(d.market.circulating_supply / 1e6).toFixed(1)}M HYPE.`}
            />
            <MetricCard
              label="MS90 valuation seed"
              value={pct(gp["ms90_vs_binance"] as number)}
              sub="Starting HL/Binance share used in the model."
              termKey="ms90"
            />
            <MetricCard
              label="MS30 vs Binance"
              value={pct(gp["ms30_vs_binance"] as number)}
              sub="DefiLlama derivatives volume / Binance Futures proxy."
              termKey="ms30"
            />
            <MetricCard
              label="Velocity ensemble"
              value={`${velocity !== undefined ? velocity.toFixed(1) : ((gp["ms30_ms180_trend"] as number - 1) * 100).toFixed(1)}%`}
              sub="70% 30D/180D + 30% 7D/30D, capped."
              accent={velocity !== undefined ? (velocity >= 0 ? "green" : "red") : ((gp["ms30_ms180_trend"] as number) >= 1.0 ? "green" : "red")}
            />
            <MetricCard
              label="P50 PV + stablecoin yield"
              value={fmtPrice(primary.pv.p50)}
              sub="Primary P50 PV with clean treasury take-rate."
              highlighted
              termKey="p50"
            />
          </div>
          {/* Row 2: 3 cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {(() => {
              const optScenario = d.scenarios.find((s) => s.key.includes("optionality") || s.key.includes("opt"));
              const optPv = optScenario ? optScenario.pv.p50 : primary.pv.p50 * 1.10;
              return (
                <MetricCard
                  label="PV + 10% optionality"
                  value={fmtPrice(optPv)}
                  sub="Primary P50 PV × 1.10 new-business optionality."
                />
              );
            })()}
            <MetricCard
              label="Discount rate"
              value={`${(d.model.discount_rate * 100).toFixed(1)}%`}
              sub="Applied over the 3-year horizon."
              termKey="dr"
            />
            <MetricCard
              label="Clean revenue take-rate"
              value="0.026%"
              sub="Treasury revenue. Total user fee rate remains about 0.034% including builder-code fees."
            />
          </div>
        </div>
      ) : isLighterLayout ? (
        /* Lighter 5+3 card layout */
        <div className="space-y-3">
          {/* Row 1: 5 cards */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            <MetricCard
              label="Spot / mcap / circ"
              value={fmtPrice(spot)}
              sub={`Mcap ${fmtLarge(d.market.market_cap)} · circ ${(d.market.circulating_supply / 1e6).toFixed(1)}M LIT.`}
            />
            <MetricCard
              label="MS90 valuation seed"
              value={pct(gp["ms90_vs_binance"] as number)}
              sub="Starting Lighter/Binance share."
              termKey="ms90"
            />
            <MetricCard
              label="MS30 / MS180"
              value={`${(gp["ms30_ms180_trend"] as number)?.toFixed(2)}×`}
              sub={(gp["ms30_ms180_trend"] as number) < 1.0
                ? "Momentum below 1.0×, so positive share acceleration is not added."
                : gp["ms30_vs_binance"] == null
                ? "MS30 data unavailable; model uses MS90 seed."
                : `Model momentum floor ${(gp["model_momentum_floor"] as number)?.toFixed(2)}×`}
              accent={(gp["ms30_ms180_trend"] as number) >= 1.0 ? "green" : "red"}
            />
            <MetricCard
              label="Velocity ensemble"
              value={(() => {
                const ms30v = gp["ms30_vs_binance"] as number | null;
                const ms180v = gp["ms180_vs_binance"] as number | null;
                return ms30v != null && ms180v != null ? `${((ms30v - ms180v) * 100).toFixed(1)}%` : "0.0%";
              })()}
              sub={gp["ms30_vs_binance"] == null
                ? "30D/180D is negative; 7D/30D unavailable in imported artifact."
                : "70% 30D/180D + 30% 7D/30D."}
            />
            <MetricCard
              label="P50 PV + HYPE-style yield"
              value={fmtPrice(primary.pv.p50)}
              sub="Primary P50 PV."
              highlighted
              highlightBg="#071d19"
              highlightBorder="#0e3530"
              termKey="p50"
            />
          </div>
          {/* Row 2: 3 cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {(() => {
              const optSc = d.scenarios.find((s) => s.key.includes("optionality") || s.key.includes("opt"));
              const optPv = optSc ? optSc.pv.p50 : primary.pv.p50 * 1.10;
              return <MetricCard label="PV + 10% optionality" value={fmtPrice(optPv)} sub="Yield case × 1.10 optionality." />;
            })()}
            <MetricCard
              label="Discount rate"
              value={`${(d.model.discount_rate * 100).toFixed(1)}%`}
              sub="Applied over the 3-year horizon."
              termKey="dr"
            />
            <MetricCard
              label="Net revenue take-rate"
              value={`${((gp["net_revenue_take_rate"] as number) * 100).toFixed(4)}%`}
              sub="Holder revenue / 30D perps volume."
            />
          </div>
        </div>
      ) : isUniLayout ? (
        /* UNI 5+4 card layout */
        <div className="space-y-3">
          {/* Row 1: 5 cards */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            <MetricCard
              label="Spot / mcap / circ"
              value={fmtPrice(spot)}
              sub={`Mcap ${fmtLarge(d.market.market_cap)} · FDV ${fmtLarge(d.market.fdv)} · circ ${(d.market.circulating_supply / 1e6).toFixed(0)}M ${d.token}.`}
            />
            <MetricCard
              label="MS90 valuation seed"
              value={pct(gp["ms90_vs_binance_spot"] as number)}
              sub="Starting UNI/Binance spot share used in primary model."
              termKey="ms90"
            />
            <MetricCard
              label="Sampled Binance spot seed"
              value={fmtLarge(gp["start_binance_spot_monthly_p50"] as number)}
              sub="P50 2022-present monthly Binance spot starting denominator."
            />
            <MetricCard
              label="Velocity ensemble"
              value={`${((gp["binance_spot_momentum_initial"] as number) ?? 0).toFixed(2)}×`}
              sub="70% MS30/MS180 + 30% MS7/MS30, monthly-equivalent, 12M decay."
              accent={(gp["binance_spot_momentum_initial"] as number) >= 1.0 ? "green" : "red"}
            />
            <MetricCard
              label="Effective Y3 supply"
              value={`${((gp["y3_effective_supply"] as number ?? 0) / 1e6).toFixed(0)}M`}
              sub={`Current circ plus ${((gp["y3_reserved_supply_release"] as number ?? 0) / 1e6).toFixed(0)}M observed reserved release over 3Y.`}
            />
          </div>
          {/* Row 2: 4 cards, first highlighted */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <MetricCard
              label="P50 PV primary"
              value={fmtPrice(primary.pv.p50)}
              sub={`EOY3 price ${fmtPrice(primary.pv.p50 * Math.pow(1 + d.model.discount_rate, 3))} discounted at ${(d.model.discount_rate * 100).toFixed(1)}%.`}
              highlighted
              highlightBg="#1a0a26"
              highlightBorder="#4a1a6a"
              termKey="p50"
            />
            <MetricCard
              label="P(above spot)"
              value={pct(primary.prob_above_spot)}
              sub={`2Y +30% ${primary.prob_spot_up_30_2y != null ? pct(primary.prob_spot_up_30_2y) : "—"} · 2Y -30% ${primary.prob_spot_down_30_2y != null ? pct(primary.prob_spot_down_30_2y) : "—"}.`}
              accent={primary.prob_above_spot >= 0.5 ? "green" : primary.prob_above_spot >= 0.35 ? "yellow" : "red"}
            />
            <MetricCard
              label="Discount / multiple"
              value={`${(d.model.discount_rate * 100).toFixed(1)}% · ${d.model.multiple}×`}
              sub="Liquid-token CAPM and Year-3 GP multiple."
              termKey="dr"
            />
            <MetricCard
              label="EOY3 share model"
              value={pct(gp["binance_spot_eoy3_share_model"] as number)}
              sub="MS90 compounded by decaying blended velocity."
            />
          </div>
        </div>
      ) : isEthfiLayout ? (
        /* ETHFI 5+3 card layout */
        <div className="space-y-3">
          {/* Row 1: 5 cards */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            <MetricCard
              label="Spot / mcap / circ"
              value={fmtPrice(spot)}
              sub={`Mcap ${fmtLarge(d.market.market_cap)} · circ ${(d.market.circulating_supply / 1e6).toFixed(1)}M ${d.token}.`}
            />
            <MetricCard
              label="Card GMV 30D ann."
              value={fmtLarge(gp["card_gdv_30d_ann"] as number)}
              sub="Current Cash card spend proxy."
            />
            <MetricCard
              label="Velocity ensemble"
              value={`${(((gp["card_velocity_ensemble"] as unknown as { ensemble_monthly: number })?.ensemble_monthly ?? 0) * 100).toFixed(1)}%`}
              sub="70% 30D/180D + 30% 7D/30D ensemble."
            />
            <MetricCard
              label="Y3 GP split P50"
              value={fmtLarge(gp["y3_gp_p50"] as number)}
              sub={`Card ${fmtLarge(gp["y3_card_gp_p50"] as number)} · staking ${fmtLarge(gp["y3_stake_gp_p50"] as number)} · vault ${fmtLarge(gp["y3_vault_gp_p50"] as number)}.`}
            />
            <MetricCard
              label="P50 PV + cash + optionality"
              value={fmtPrice(primary.pv.p50)}
              sub="Weighted MC after treasury cash and optionality."
              highlighted
              termKey="p50"
            />
          </div>
          {/* Row 2: 3 cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <MetricCard
              label="P(above spot)"
              value={pct(primary.prob_above_spot)}
              sub={`2Y +30% ${primary.prob_spot_up_30_2y != null ? pct(primary.prob_spot_up_30_2y) : "—"} · 2Y -30% ${primary.prob_spot_down_30_2y != null ? pct(primary.prob_spot_down_30_2y) : "—"}.`}
              accent={primary.prob_above_spot >= 0.5 ? "green" : primary.prob_above_spot >= 0.35 ? "yellow" : "red"}
            />
            <MetricCard
              label="Discount rate"
              value={`${(d.model.discount_rate * 100).toFixed(1)}%`}
              sub="Applied to Year-3 valuation."
              termKey="dr"
            />
            <MetricCard
              label="Card take-rate"
              value={`${((gp["card_take_bps_30d"] as number) ?? 0).toFixed(1)}bps`}
              sub="30D Cash card revenue / GMV proxy."
            />
          </div>
        </div>
      ) : isSkyLayout ? (
        /* SKY 5+4 card layout */
        <div className="space-y-3">
          {/* Row 1: 5 cards */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            <MetricCard
              label="Spot / mcap / FDV"
              value={fmtPrice(spot)}
              sub={`Mcap ${fmtLarge(d.market.market_cap)} · FDV ${fmtLarge(d.market.fdv)} · max ${(d.market.max_supply / 1e9).toFixed(2)}B SKY.`}
            />
            <MetricCard
              label="Official USDS + DAI"
              value={fmtLarge(gp["total_sky_stable_supply"] as number)}
              sub={`Sky supply page API, ${gp["official_supply_date"] != null ? String(gp["official_supply_date"] as unknown as string) : "—"}: USDS ${fmtLarge(gp["usds_supply"] as number)} + DAI ${fmtLarge(gp["dai_supply"] as number)}.`}
            />
            <MetricCard
              label="Gross income take-rate"
              value={`${((gp["gross_income_take_rate_bps"] as number) ?? 0).toFixed(1)} bps`}
              sub="Gross income yield applied to modeled Sky supply."
            />
            <MetricCard
              label="Net GP take-rate"
              value={`${((gp["net_gp_take_rate_bps"] as number) ?? 0).toFixed(1)} bps`}
              sub={`After ${((gp["savings_cost_rate_bps"] as number) ?? 0).toFixed(1)} bps savings cost and ${((gp["stusds_cost_rate_bps"] as number) ?? 0).toFixed(1)} bps stUSDS cost.`}
            />
            <MetricCard
              label="Mcap / current GP"
              value={`${((gp["mcap_current_gp"] as number) ?? 0).toFixed(1)}x`}
              sub={`FDV / current GP ${((gp["fdv_current_gp"] as number) ?? 0).toFixed(1)}x; current GP ${fmtLarge(gp["current_gp"] as number)} annualized.`}
            />
          </div>
          {/* Row 2: 4 cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <MetricCard
              label="Velocity ensemble"
              value={`${(((gp["velocity_ensemble_monthly"] as number) ?? 0) * 100).toFixed(2)}%/mo`}
              sub={`Long ${(((gp["velocity_long_component_monthly"] as number) ?? 0) * 100).toFixed(2)}%/mo · short ${(((gp["velocity_short_component_monthly"] as number) ?? 0) * 100).toFixed(2)}%/mo.`}
              accent={(gp["velocity_ensemble_monthly"] as number) > 0 ? "green" : "default"}
            />
            <MetricCard
              label={`P50 PV · ${d.model.multiple}x NP`}
              value={fmtPrice(primary.pv.p50)}
              sub={`Base ${fmtLarge(gp["base_opex"] as number)} OPEX, ${d.model.multiple}x net-profit valuation; GP case shown as sensitivity.`}
              highlighted
              termKey="p50"
            />
            <MetricCard
              label="2Y +30% / -30%"
              value={`${primary.prob_spot_up_30_2y != null ? pct(primary.prob_spot_up_30_2y) : "—"} / ${primary.prob_spot_down_30_2y != null ? pct(primary.prob_spot_down_30_2y) : "—"}`}
              sub={`Undiscounted two-year path probabilities; P(spot) ${pct(primary.prob_above_spot)}.`}
            />
            <MetricCard
              label="Discount / multiple"
              value={`${(d.model.discount_rate * 100).toFixed(0)}% · ${d.model.multiple}×`}
              sub={`Primary uses NP multiple; 10x GP sensitivity also shown. P(3x) ${primary.prob_3x != null ? pct(primary.prob_3x) : "—"} right-tail.`}
              termKey="dr"
            />
          </div>
        </div>
      ) : isJupLayout ? (
        /* JUP 5+4 card layout */
        <div className="space-y-3">
          {/* Row 1: 5 cards */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            <MetricCard
              label="Spot / mcap / circ"
              value={fmtPrice(spot)}
              sub={`Mcap ${fmtLarge(d.market.market_cap)} · circ ${(d.market.circulating_supply / 1e9).toFixed(2)}B ${d.token}.`}
            />
            <MetricCard
              label="Perps MS30 vs Binance Futures"
              value={pct(gp["perps_ms30_vs_binance_futures"] as number)}
              sub="Clean-GP-implied JUP perps volume / scaled Binance Futures."
              accent={(gp["perps_ms30_ms180_binance_futures_trend"] as number) >= 1.0 ? "green" : "default"}
            />
            <MetricCard
              label="Spot MS30 vs Binance spot"
              value={pct(gp["spot_ms30_vs_binance_spot"] as number)}
              sub="Aggregator + Jupiterz volume / scaled Binance spot."
              accent={(gp["spot_ms30_ms180_binance_spot_trend"] as number) >= 1.0 ? "green" : "default"}
            />
            <MetricCard
              label="Perps take / spot rake"
              value={`${((gp["perps_clean_take_rate_bps"] as number) ?? 0).toFixed(2)} / ${((gp["spot_take_rate_bps"] as number) ?? 0).toFixed(2)} bps`}
              sub="Clean GP take-rate and observed spot rake."
            />
            <MetricCard
              label="Velocity ensemble"
              value={`${((gp["perps_share_velocity_capped"] as number) ?? 0).toFixed(2)}× / ${((gp["spot_share_velocity_capped"] as number) ?? 0).toFixed(2)}×`}
              sub="Perps / spot share velocity; 70% MS30/MS180 + 30% MS7/MS30."
              accent={(gp["perps_share_velocity_capped"] as number) >= 1.0 ? "green" : "default"}
            />
          </div>
          {/* Row 2: 4 cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <MetricCard
              label={`P50 PV + opt + Jupnet`}
              value={fmtPrice(primary.pv.p50)}
              sub={`Primary locked-report case; ${primary.pv.p50 > spot ? "+" : ""}${((primary.pv.p50 / spot - 1) * 100).toFixed(0)}% vs spot.`}
              highlighted
              termKey="p50"
            />
            <MetricCard
              label="P(above spot)"
              value={pct(primary.prob_above_spot)}
              sub={`2Y +30% ${primary.prob_spot_up_30_2y != null ? pct(primary.prob_spot_up_30_2y) : "—"} · 2Y -30% ${primary.prob_spot_down_30_2y != null ? pct(primary.prob_spot_down_30_2y) : "—"}.`}
              accent={primary.prob_above_spot >= 0.5 ? "green" : primary.prob_above_spot >= 0.35 ? "yellow" : "red"}
            />
            <MetricCard
              label="Discount / multiple"
              value={`${(d.model.discount_rate * 100).toFixed(1)}% · ${d.model.multiple}×`}
              sub="Discounted 3Y TTM entity GP multiple."
              termKey="dr"
            />
            <MetricCard
              label="Buyback share"
              value="50%"
              sub="Modeled entity GP used for JUP buybacks via Litterbox Trust."
            />
          </div>
        </div>
      ) : isCardsLayout ? (
        /* CARDS 5+3 card layout */
        (() => {
          const fdv       = d.market.fdv;
          const gmv30d    = gp["gmv_30d"]     as number ?? 0;
          const gmv30dAnn = gp["gmv_30d_ann"] as number ?? 0;
          const netSpread = (gp["net_spread"]  as number) || (gp["gross_margin"] as number) || 0;
          const gpAnn     = gp["gross_profit_ann"] as number ?? 0;
          const lockedSup = gp["locked_supply"] as number ?? 0;
          const primarySc = d.scenarios.find((s) => s.is_primary) ?? d.scenarios[0];
          const floatVal  = (primarySc.y3_supply_p50 ?? 0) * spot;
          const y3SupB    = ((primarySc.y3_supply_p50 ?? 0) / 1e9).toFixed(2);
          const useLive   = gmv30d > 0;
          return (
            <div className="space-y-3">
              {/* Row 1: 5 cards */}
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                <MetricCard
                  label="Spot / FDV / float value"
                  value={fmtPrice(spot)}
                  sub={`FDV ${fmtLarge(fdv)} · float-friendly value ${fmtLarge(floatVal)} using ${y3SupB}B Y3 supply.`}
                />
                <MetricCard
                  label="Gacha GMV 30D ann."
                  value={useLive ? fmtLarge(gmv30dAnn) : fmtLarge((gp["gmv_q1_2026"] as number ?? 0) * 4)}
                  sub={useLive
                    ? `30D DefiLlama Gacha volume of ${fmtLarge(gmv30d)} annualized.`
                    : `Q1 2026 Gacha volume of ${fmtLarge(gp["gmv_q1_2026"] as number ?? 0)} annualized.`}
                />
                <MetricCard
                  label="Net spread"
                  value={`${(netSpread * 100).toFixed(2)}%`}
                  sub="DefiLlama net revenue / Gacha GMV; already net of pack buyback spends."
                />
                <MetricCard
                  label="GMV velocity input"
                  value={`${(((gp["gmv_velocity_input"] as number) ?? 0.20) * 100).toFixed(1)}%`}
                  sub="Capped 7D/30D GMV velocity; used until 30D/180D history exists."
                />
                <MetricCard
                  label={`Base PV at ${d.model.multiple}x GP`}
                  value={fmtPrice(primarySc.pv.p50)}
                  sub={`${fmtLarge(primarySc.y3_gp_p50 ?? 0)} modeled GP × ${d.model.multiple}x, discounted 3Y at ${(d.model.discount_rate * 100).toFixed(0)}%.`}
                  highlighted
                  termKey="p50"
                />
              </div>
              {/* Row 2: 3 cards */}
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                <MetricCard
                  label="Weighted PV"
                  value={fmtPrice((gp["weighted_pv"] as number) ?? primarySc.ev)}
                  sub="40% 6M decay, 40% 12M decay, 20% 24M decay."
                />
                <MetricCard
                  label="Discount rate"
                  value={`${(d.model.discount_rate * 100).toFixed(1)}%`}
                  sub="Applied to Year-3 valuation."
                  termKey="dr"
                />
                <MetricCard
                  label="True GP conversion"
                  value={`${(((gp["true_gp_conversion"] as number) ?? 0.60) * 100).toFixed(0)}%`}
                  sub="Base conversion from DefiLlama net revenue to stricter GP after off-chain costs."
                />
              </div>
            </div>
          );
        })()
      ) : (
        /* Per-token cards matching HYPE style */
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {/* Card 1: always spot/mcap */}
          <MetricCard
            label="Spot / mcap / circ"
            value={fmtPrice(spot)}
            sub={`Mcap ${fmtLarge(d.market.market_cap)} · circ ${(d.market.circulating_supply / 1e6).toFixed(0)}M ${d.token}`}
          />
          {/* Card 2–4: token-specific GP metrics */}
          {tokenKey === "jup" && <>
            <MetricCard label="Total 30D GP" value={fmtLarge(gp["total_30d"] as number)} sub="Perps + aggregator + Jupiterz" />
            <MetricCard label="Perps take / spot rake" value={`${((gp["perps_clean_take_rate_bps"] as number) ?? 0).toFixed(2)} / ${((gp["spot_take_rate_bps"] as number) ?? 0).toFixed(2)} bps`} sub="Clean GP economics" />
            {gp["perps_ms30_vs_binance_futures"] != null
              ? <MetricCard label="Perps MS30 vs Binance" value={pct(gp["perps_ms30_vs_binance_futures"] as number)} sub={`Spot MS30 ${pct(gp["spot_ms30_vs_binance_spot"] as number)}`} accent={(gp["perps_ms30_ms180_binance_futures_trend"] as number) >= 1.0 ? "green" : "default"} />
              : <MetricCard label="Perps 30D" value={fmtLarge(gp["perps_30d"] as number)} sub={`Aggregator ${fmtLarge(gp["aggregator_30d"] as number)}`} />
            }
            <MetricCard
              label="Share velocity"
              value={`${(gp["perps_share_velocity_capped"] as number)?.toFixed(2)}× / ${(gp["spot_share_velocity_capped"] as number)?.toFixed(2)}×`}
              sub="Perps / spot · 70% MS30/MS180 + 30% MS7/MS30"
              accent={(gp["perps_share_velocity_capped"] as number) >= 1.0 ? "green" : "red"}
            />
          </>}
          {tokenKey === "vvv" && <>
            <MetricCard
              label="Est. platform rev. ann."
              value={fmtLarge(gp["est_total_platform_revenue_ann"] as number)}
              sub={`On-chain burns only: ${fmtLarge(gp["defillama_30d_ann"] as number)}/yr`}
            />
            <MetricCard
              label="Buyback years (est. rev.)"
              value={`${(gp["buyback_years_est_revenue"] as number).toFixed(1)}y`}
              sub={`On-chain burns only: ${(gp["buyback_years_onchain"] as number).toFixed(0)}y`}
            />
            <MetricCard
              label="Annual emissions"
              value={`${((gp["annual_emissions"] as number) / 1e6).toFixed(0)}M VVV/yr`}
              sub={`3Y gross unlock ${((gp["gross_3y_unlock_tokens"] as number) / 1e6).toFixed(0)}M tokens · no max supply`}
            />
          </>}
          {tokenKey === "bp" && <>
            <MetricCard
              label="30D perps MS vs Binance"
              value={`${((gp["perp_ms30_vs_binance_futures"] as number ?? 0) * 100).toFixed(3)}%`}
              sub={`${fmtLarge(gp["perp_volume_30d_ann"] as number)} ann. · ${(gp["perp_take_rate_bps"] as number ?? 1.5).toFixed(2)} bps take`}
            />
            <MetricCard
              label="30D spot MS vs Binance"
              value={`${((gp["spot_ms30_vs_binance_spot"] as number ?? 0) * 100).toFixed(3)}%`}
              sub={`${fmtLarge(gp["spot_volume_30d_ann"] as number)} ann. · ${(gp["spot_take_rate_bps"] as number ?? 9.5).toFixed(1)} bps take`}
            />
            <MetricCard
              label="FDV-implied company val."
              value={fmtLarge(gp["implied_company_val_at_fdv"] as number)}
              sub="Current FDV ÷ 20% equity stake"
            />
          </>}
          {tokenKey === "cards" && <>
            <MetricCard
              label="Annual GP run rate"
              value={fmtLarge(gp["gross_profit_ann"] as number)}
              sub={`Q1 2026 ×4 · ${((gp["gross_margin"] as number) * 100).toFixed(1)}% margin on $${((gp["gmv_q1_2026"] as number)/1e6).toFixed(0)}M GMV`}
            />
            <MetricCard
              label="Supply still locked"
              value={`${((gp["locked_supply"] as number) / 1e9).toFixed(2)}B CARDS`}
              sub={`${(((gp["locked_supply"] as number) / 2e9) * 100).toFixed(0)}% of max supply — team, foundation, community`}
            />
            <MetricCard
              label="Physical card treasury"
              value={fmtLarge(gp["treasury_assets"] as number)}
              sub={`${((gp["treasury_card_pct"] as number) * 100).toFixed(0)}% in physical Pokémon & TCG cards`}
            />
          </>}
          {tokenKey === "coinbase" && <>
            <MetricCard
              label="Spot MS vs Binance"
              value={`${((gp["spot_ms30_vs_binance"] as number ?? 0) * 100).toFixed(2)}%`}
              sub={`${fmtLarge(gp["spot_revenue_ann"] as number)} ann. · 32 bps blended take`}
            />
            <MetricCard
              label="Deribit MS vs BNB Fut."
              value={`${((gp["deribit_ms30_vs_binance_futures"] as number ?? 0) * 100).toFixed(2)}%`}
              sub={`${fmtLarge(gp["deribit_revenue_ann"] as number)} ann. · 3.88 bps take · CDE ${fmtLarge(gp["cde_revenue_ann"] as number)}`}
            />
            <MetricCard
              label="CAPM beta / DR"
              value={`β${(gp["capm_beta"] as number ?? 0).toFixed(2)} / ${((gp["derived_discount_rate"] as number ?? 0)*100).toFixed(1)}%`}
              sub={`rf ${((gp["risk_free_rate"] as number ?? 0)*100).toFixed(2)}% + 5.5% ERP × β = DR`}
            />
          </>}
          {/* Fallback for unknown tokens */}
          {!["uni", "ethfi", "jup", "lighter", "sky", "vvv", "bp", "cards", "coinbase"].includes(tokenKey) && <>
            <MetricCard label="Market Cap" value={fmtLarge(d.market.market_cap)} sub={`FDV ${fmtLarge(d.market.fdv)}`} />
            <MetricCard label="Circ. Supply" value={`${(d.market.circulating_supply / 1e6).toFixed(0)}M`} sub={`of ${(d.market.max_supply / 1e6).toFixed(0)}M max`} />
            <MetricCard label="EV (mean)" value={fmtPrice(primary.ev)} accent="blue" termKey="ev" />
          </>}
          {/* Card 5–6: always P50 + P(spot) */}
          <MetricCard
            label="P50 Fair Value"
            value={fmtPrice(primary.pv.p50)}
            sub={`P25 ${fmtPrice(primary.pv.p25)} · P75 ${fmtPrice(primary.pv.p75)}`}
            highlighted
            termKey="p50"
          />
          <MetricCard
            label="P(above spot)"
            value={pct(primary.prob_above_spot)}
            sub={`P50 ${p50Upside >= 0 ? "+" : ""}${p50Upside.toFixed(0)}% vs spot · EV ${fmtPrice(primary.ev)}`}
            accent={probColor as "green" | "red" | "yellow"}
            termKey="prob_above_spot"
          />
        </div>
      )}

      {/* ── Market share trend ───────────────────────────────────────── */}
      {(tokenKey === "hype" || tokenKey === "lighter" || tokenKey === "uni" || tokenKey === "ethfi" || tokenKey === "jup" || tokenKey === "sky" || tokenKey === "cards") && <MarketShareSection data={d} tokenKey={tokenKey} />}

      {/* ── Model outputs ────────────────────────────────────────────── */}
      {tokenKey === "hype" && primary.y3_price_p50 && (
        <HypeModelOutputs data={d} />
      )}
      {tokenKey !== "hype" && <TokenModelOutputs data={d} tokenKey={tokenKey} />}

      {/* ── PV price distribution ─────────────────────────────────────── */}
      <DistributionChart scenario={primary} spot={spot} ev={primary.ev} />

      {/* ── Tech score monthly history ────────────────────────────────── */}
      <TechScoreHistoryChart tokenKey={tokenKey} />
    </div>
  );
}

// ── HypeMcpWeekly ─────────────────────────────────────────────────────────────

function HypeMcpWeekly({ bullets, asOf }: { bullets: string[]; asOf?: string }) {
  return (
    <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] p-6">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h3 className="text-lg font-bold text-white">DefiLlama MCP weekly answer</h3>
          <p className="text-sm text-gray-400 mt-0.5">
            Top 5 trailing-30D updates fetched now, not just scheduled.
          </p>
        </div>
        {asOf && <div className="text-xs text-gray-600 shrink-0">as of {asOf}</div>}
      </div>
      <ul className="space-y-2.5">
        {bullets.map((b, i) => (
          <li key={i} className="flex items-start gap-3">
            <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0" />
            <span className="text-sm text-gray-300 leading-relaxed font-medium">{b}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Landing summary stats ─────────────────────────────────────────────────────

interface SummaryStats {
  p50spot: number | null;
  vel7_30: number | null;
  vel30_180: number | null;
  gmv_vel7_30: number | null;
  gmv_vel30_180: number | null;
  up_beta: number | null;
  down_beta: number | null;
  beta_ratio: number | null;
  signal: string | null;
}

function extractSummaryStats(key: string, token: TokenResult): SummaryStats {
  const data = token.data;
  if (!data) return { p50spot: null, vel7_30: null, vel30_180: null, gmv_vel7_30: null, gmv_vel30_180: null, up_beta: null, down_beta: null, beta_ratio: null, signal: null };

  const spot    = data.market.spot;
  const primary = data.scenarios.find((s) => s.is_primary) ?? data.scenarios[0];
  const p50     = primary?.pv.p50;
  const p50spot = p50 && spot ? p50 / spot : null;

  const gp = data.current_gp as Record<string, unknown>;

  const num = (v: unknown): number | null =>
    typeof v === "number" && isFinite(v) ? v : null;

  // MS velocity 30/180 — try common field names across models
  const vel30_180 =
    num(gp.ms30_ms180_trend) ??
    num(gp.perps_ms30_ms180_binance_futures_trend) ??
    num(gp.ms30_ms180_binance_spot_trend);

  // MS velocity 7/30 — direct field or computed from underlying ms data
  let vel7_30: number | null = num(gp.ms7_ms30_trend);
  if (vel7_30 === null && key === "jup") {
    const ms7 = num(gp.perps_ms7_vs_binance_futures);
    const ms30 = num(gp.perps_ms30_vs_binance_futures);
    if (ms7 !== null && ms30 !== null && ms30 > 0) vel7_30 = ms7 / ms30;
  }
  if (vel7_30 === null && key === "ethfi") {
    const ens = gp.card_velocity_ensemble as Record<string, number> | undefined;
    if (ens?.gdv_7 && ens?.gdv_30) vel7_30 = (ens.gdv_7 / 7) / (ens.gdv_30 / 30);
  }
  if (vel7_30 === null && key === "uni") {
    vel7_30 = num(gp.ms7_ms30_binance_spot_trend);
  }

  // GMV velocity — 7D/30D and 30D/180D daily average ratios (CARDS)
  let gmv_vel7_30: number | null = null;
  let gmv_vel30_180: number | null = null;
  if (key === "cards") {
    const avg7   = num(gp.gmv_7d_daily_avg);
    const avg30  = num(gp.gmv_30d_daily_avg);
    const avg180 = num(gp.gmv_180d_daily_avg);
    if (avg7  !== null && avg30  !== null && avg30  > 0) gmv_vel7_30   = avg7  / avg30;
    if (avg30 !== null && avg180 !== null && avg180 > 0) gmv_vel30_180 = avg30 / avg180;
  }

  const up_beta   = num(gp.up_beta_btc);
  const down_beta = num(gp.down_beta_btc);
  const beta_ratio = num(gp.beta_ratio_btc);

  const signal = (data.hist_charts as { backtest?: { latest_signal?: string } } | undefined)
    ?.backtest?.latest_signal ?? null;

  return { p50spot, vel7_30, vel30_180, gmv_vel7_30, gmv_vel30_180, up_beta, down_beta, beta_ratio, signal };
}

function velColor(v: number): string {
  if (v > 1.05) return "#4ade80";
  if (v < 0.95) return "#f87171";
  return "#9ca3af";
}

type SortCol = "p50spot" | "vel7_30" | "vel30_180" | "gmv_vel7_30" | "gmv_vel30_180" | "up_beta" | "down_beta" | "beta_ratio" | "signal" | null;

function LandingSummary({
  tokens,
  selected,
  onSelect,
}: {
  tokens: [string, TokenResult][];
  selected: string;
  onSelect: (key: string) => void;
}) {
  const [sortCol, setSortCol] = useState<SortCol>(null);
  const [sortDir, setSortDir] = useState<"desc" | "asc">("desc");

  function handleSort(col: SortCol) {
    if (sortCol === col) setSortDir(d => d === "desc" ? "asc" : "desc");
    else { setSortCol(col); setSortDir("desc"); }
  }

  const baseRows = tokens.map(([key, token]) => ({
    key,
    token,
    stats: extractSummaryStats(key, token),
  }));

  const rows = sortCol === null ? baseRows : [...baseRows].sort((a, b) => {
    const av = (a.stats as unknown as Record<string, unknown>)[sortCol] as number | string | null;
    const bv = (b.stats as unknown as Record<string, unknown>)[sortCol] as number | string | null;
    if (av === null && bv === null) return 0;
    if (av === null) return 1;
    if (bv === null) return -1;
    const cmp = typeof av === "string" ? av.localeCompare(bv as string) : (av as number) - (bv as number);
    return sortDir === "desc" ? -cmp : cmp;
  });

  function SortTh({ col, children, className }: { col: SortCol; children: React.ReactNode; className?: string; }) {
    const active = sortCol === col;
    return (
      <th
        className={`px-4 py-2.5 font-medium text-gray-500 whitespace-nowrap cursor-pointer select-none hover:text-gray-300 ${className ?? "text-right"}`}
        onClick={() => handleSort(col)}
      >
        {children}{active ? (sortDir === "desc" ? " ↓" : " ↑") : ""}
      </th>
    );
  }

  const signalStyle: Record<string, { color: string; bg: string; border: string }> = {
    GOOD:    { color: "#4ade80", bg: "rgba(74,222,128,0.12)", border: "rgba(74,222,128,0.35)" },
    NEUTRAL: { color: "#fbbf24", bg: "rgba(251,191,36,0.12)", border: "rgba(251,191,36,0.35)" },
    BAD:     { color: "#f87171", bg: "rgba(248,113,113,0.12)", border: "rgba(248,113,113,0.35)" },
  };

  return (
    <div className="bg-[#1a1d29] rounded-xl border border-[#2d3144] overflow-hidden mb-8">
      <div className="px-5 py-3 border-b border-[#2d3144]">
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Portfolio snapshot</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-[#2d3144]">
              <th className="text-left px-5 py-2.5 font-medium text-gray-500 whitespace-nowrap">Token</th>
              <SortTh col="p50spot">P50 / spot</SortTh>
              <SortTh col="vel7_30">MS Vel 7/30</SortTh>
              <SortTh col="vel30_180">MS Vel 30/180</SortTh>
              <SortTh col="gmv_vel7_30">GMV Vel 7/30</SortTh>
              <SortTh col="gmv_vel30_180">GMV Vel 30/180</SortTh>
              <SortTh col="up_beta">Up β</SortTh>
              <SortTh col="down_beta">Down β</SortTh>
              <SortTh col="beta_ratio">β ratio</SortTh>
              <SortTh col="signal">Signal</SortTh>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ key, token, stats }) => {
              const ring    = TOKEN_RING[key] ?? "#60a5fa";
              const active  = key === selected;
              const { p50spot, vel7_30, vel30_180, gmv_vel7_30, gmv_vel30_180, up_beta, down_beta, beta_ratio, signal } = stats;
              const p50Color = p50spot === null ? "#9ca3af" : p50spot >= 1.1 ? "#4ade80" : p50spot < 0.9 ? "#f87171" : "#fbbf24";
              const ss = signal ? signalStyle[signal] : null;

              return (
                <tr
                  key={key}
                  onClick={() => onSelect(key)}
                  className="border-b border-[#2d3144] last:border-0 cursor-pointer transition-colors hover:bg-[#1e2130]"
                  style={active ? { background: `${ring}12` } : undefined}
                >
                  <td className="px-5 py-2.5 whitespace-nowrap">
                    <span className="font-bold font-mono" style={{ color: active ? ring : "#e5e7eb" }}>
                      {token.symbol}
                    </span>
                    <span className="ml-2 text-gray-600">{token.name}</span>
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono whitespace-nowrap">
                    {p50spot !== null ? (
                      <span style={{ color: p50Color }}>{p50spot.toFixed(2)}×</span>
                    ) : (
                      <span className="text-gray-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono whitespace-nowrap">
                    {vel7_30 !== null ? (
                      <span style={{ color: velColor(vel7_30) }}>{vel7_30.toFixed(2)}×</span>
                    ) : (
                      <span className="text-gray-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono whitespace-nowrap">
                    {vel30_180 !== null ? (
                      <span style={{ color: velColor(vel30_180) }}>{vel30_180.toFixed(2)}×</span>
                    ) : (
                      <span className="text-gray-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono whitespace-nowrap">
                    {gmv_vel7_30 !== null ? (
                      <span style={{ color: velColor(gmv_vel7_30) }}>{gmv_vel7_30.toFixed(2)}×</span>
                    ) : (
                      <span className="text-gray-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono whitespace-nowrap">
                    {gmv_vel30_180 !== null ? (
                      <span style={{ color: velColor(gmv_vel30_180) }}>{gmv_vel30_180.toFixed(2)}×</span>
                    ) : (
                      <span className="text-gray-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono whitespace-nowrap">
                    {up_beta !== null ? (
                      <span style={{ color: up_beta >= 1 ? "#4ade80" : up_beta < 0.5 ? "#f87171" : "#9ca3af" }}>{up_beta.toFixed(2)}</span>
                    ) : <span className="text-gray-600">—</span>}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono whitespace-nowrap">
                    {down_beta !== null ? (
                      <span style={{ color: down_beta <= 1 ? "#4ade80" : down_beta > 1.5 ? "#f87171" : "#9ca3af" }}>{down_beta.toFixed(2)}</span>
                    ) : <span className="text-gray-600">—</span>}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono whitespace-nowrap">
                    {beta_ratio !== null ? (
                      <span style={{ color: beta_ratio >= 1.1 ? "#4ade80" : beta_ratio < 0.85 ? "#f87171" : "#9ca3af" }}>{beta_ratio.toFixed(2)}</span>
                    ) : <span className="text-gray-600">—</span>}
                  </td>
                  <td className="px-5 py-2.5 text-right whitespace-nowrap">
                    {ss ? (
                      <span
                        className="inline-block px-2 py-0.5 rounded-md font-semibold text-xs"
                        style={{ color: ss.color, background: ss.bg, border: `1px solid ${ss.border}` }}
                      >
                        {signal}
                      </span>
                    ) : (
                      <span className="text-gray-600">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Token picker ─────────────────────────────────────────────────────────────

const TOKEN_RING: Record<string, string> = {
  uni:      "#ff007a",
  ethfi:    "#06b6d4",
  jup:      "#9945ff",
  hype:     "#00e5a0",
  sky:      "#f59e0b",
  coinbase: "#0052ff",
};

// ── Main dashboard ───────────────────────────────────────────────────────────

export default function ValuationDashboard({ data }: Props) {
  const tokens      = Object.entries(data.tokens);
  const [selected, setSelected] = useState<string>(tokens[0]?.[0] ?? "");
  const activeToken = data.tokens[selected];

  return (
    <div className="min-h-screen bg-[#f0f3f8] text-gray-900">
      <header className="border-b border-[#e2e6f0] px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Crypto Valuations</h1>
            <p className="text-sm text-gray-500 mt-0.5">updated {data.lastUpdated || "—"}</p>
          </div>
          <Nav />
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 sm:px-6 py-8">
        {tokens.length === 0 ? (
          <div className="text-center py-24 text-gray-400">No valuation data yet.</div>
        ) : (
          <>
            {/* Token picker */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 mb-8">
              {tokens.map(([key, token]) => {
                const active   = key === selected;
                const spot     = token.data?.market.spot;
                const primary  = token.data?.scenarios.find((s) => s.is_primary) ?? token.data?.scenarios[0];
                const p50      = primary?.pv.p50;
                const ring     = TOKEN_RING[key] ?? "#60a5fa";

                return (
                  <button
                    key={key}
                    onClick={() => setSelected(key)}
                    className="w-full flex items-center gap-4 px-5 py-3 rounded-xl border transition-all text-left"
                    style={{
                      background:   active ? `${ring}18` : "#ffffff",
                      borderColor:  active ? ring : "#e2e6f0",
                    }}
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span
                          className="text-base font-bold"
                          style={{ color: active ? ring : "#374151" }}
                        >
                          {token.symbol}
                        </span>
                        <span className="text-xs text-gray-500">{token.chain}</span>
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">{token.name}</div>
                    </div>
                    <div className="text-right ml-2">
                      {spot !== undefined && (
                        <div
                          className="text-base font-mono font-semibold"
                          style={{ color: active ? ring : "#9ca3af" }}
                        >
                          {fmtPrice(spot)}
                        </div>
                      )}
                      {p50 !== undefined && (
                        <div className="text-xs text-gray-600">
                          P50 {fmtPrice(p50)}
                        </div>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Portfolio snapshot */}
            <LandingSummary tokens={tokens} selected={selected} onSelect={setSelected} />

            {/* Active token */}
            {activeToken && (
              <div>
                <div className="flex items-baseline gap-3 mb-6 flex-wrap">
                  <h2 className="text-3xl font-bold text-gray-900">{activeToken.symbol}</h2>
                  <span className="text-lg text-gray-500">{activeToken.name}</span>
                  {activeToken.data && (
                    <span
                      className="text-3xl font-bold font-mono ml-auto"
                      style={{ color: TOKEN_RING[selected] ?? "#60a5fa" }}
                    >
                      {fmtPrice(activeToken.data.market.spot)}
                    </span>
                  )}
                </div>
                <TokenView tokenKey={selected} token={activeToken} />
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
