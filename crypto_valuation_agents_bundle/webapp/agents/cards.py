"""CARDS (Collector Crypt) webapp valuation agent — Gacha GP scenarios.

Model: Y3_price = Y3_GP × 15 × 1.10 / Y3_supply
Revenue: Gacha pack sales (98%) + marketplace fees (2%).
Q1 2026 actuals: $146.9M GMV, 5.9% gross margin = $8.6M GP → $34.4M annualized.
Supply: Max 2B CARDS; circulating ~12.9% (257M); heavy unlock risk over 3Y.
Distributions: log-normal σ=1.0 approximation.
Market data refreshed live from CoinGecko on every run.
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── Research-locked Q1 2026 actuals ──────────────────────────────────────────
GMV_Q1_2026     = 146_900_000.0   # Q1 2026 gross merchandise volume
GROSS_MARGIN_Q1 = 0.059           # 5.9% — compressed from 10–12% at launch
GP_Q1_2026      = GMV_Q1_2026 * GROSS_MARGIN_Q1   # $8.67M
GP_ANN_RUN_RATE = GP_Q1_2026 * 4                   # $34.67M annualized
MAX_SUPPLY       = 2_000_000_000  # 2B CARDS
LOCKED_SUPPLY_EST = 1_743_000_000 # ~87.1% locked (foundation 36.76%, community 20%, team 19.5%, …)
TREASURY_ASSETS  = 10_000_000.0  # estimated physical Pokémon/TCG treasury (not publicly disclosed)
TREASURY_CARD_PCT = 0.80         # ~80% in physical trading cards

# Net spread assumption (DefiLlama net revenue / Gacha GMV, already net of pack buyback spends)
NET_SPREAD = 0.084               # 8.4% — DefiLlama blended margin (was 12.35%; reset to match observed ~8–9%)
MARGIN_FLOOR = 0.05              # ~5% floor — house edge on high-price packs drives most volume

# True GP conversion (DefiLlama net revenue → stricter GP after off-chain costs)
TRUE_GP_CONVERSION = 0.60       # 60% base conversion

# GMV velocity input (capped 7D/30D velocity; used until 30D/180D history exists)
GMV_VELOCITY_INPUT = 0.20       # 20.0% cap

# DefiLlama
DEFILLAMA_SLUG = "collector-crypt"

# Valuation parameters
MULTIPLE         = 15.0
OPTIONALITY      = 1.10          # 10% optionality kicker in the Y3 price formula
DISCOUNT_RATE    = 0.30
LOG_NORMAL_SIGMA = 1.0

# Supply: rules-based from Foundation unlock schedule
# Foundation (36.5% × 2B = 730M) has no need to sell → stays out of float in base/bull;
# only enters bear supply. Bull also assumes incremental buyback.
FOUNDATION_SUPPLY       = 730_000_000  # 36.5% × 2B — locked
NON_FOUNDATION_Y3_FLOAT = 770_000_000  # team + community + ecosystem float by Y3
BUYBACK_BULL_TOKENS     = 100_000_000  # incremental buyback in bull case
FLOAT_SUPPLY_Y3         = NON_FOUNDATION_Y3_FLOAT  # alias for velocity-scenario denominator

_SUPPLY_Y3 = {
    "bear": NON_FOUNDATION_Y3_FLOAT + FOUNDATION_SUPPLY,  # 1.5B — Foundation releases in bear
    "base": NON_FOUNDATION_Y3_FLOAT,                       # 770M — Foundation locked
    "bull": NON_FOUNDATION_Y3_FLOAT - BUYBACK_BULL_TOKENS, # 670M — locked + buybacks
}

# Per-scenario GMV + margin lever (GP = GMV × margin; supply is rules-based above)
Y3_GMV_BEAR, MARGIN_BEAR = 400_000_000, MARGIN_FLOOR  # → $20M GP (margin at floor)
Y3_GMV_BASE, MARGIN_BASE = 535_000_000, NET_SPREAD     # → ~$45M GP (current blend)
Y3_GMV_BULL, MARGIN_BULL = 710_000_000, 0.120          # → ~$85M GP (margin recovery)

# Velocity-decay scenario decay periods (months)
DECAY_PERIODS = [6, 12, 24]  # A, B, C
DECAY_WEIGHTS = [0.4, 0.4, 0.2]  # weighted 40/40/20

# Scenarios: (key, label, y3_gp, y3_supply, is_primary)
SCENARIOS = [
    ("bear", "Bear: $400M GMV × 5% margin",   int(Y3_GMV_BEAR * MARGIN_BEAR),  _SUPPLY_Y3["bear"], False),
    ("base", "Base: $535M GMV × 8.4% margin", int(Y3_GMV_BASE * MARGIN_BASE),  _SUPPLY_Y3["base"], True),
    ("bull", "Bull: $710M GMV × 12% margin",  int(Y3_GMV_BULL * MARGIN_BULL),  _SUPPLY_Y3["bull"], False),
]

CG_ID    = "collector-crypt"
_CG_KEY  = os.environ.get("COINGECKO_API_KEY", "")
_CG_BASE = "https://pro-api.coingecko.com/api/v3" if _CG_KEY else "https://api.coingecko.com/api/v3"
RESULTS_DIR = Path(__file__).parent.parent / "results"
UA = "Mozilla/5.0 CARDS-valuation"

# Fallbacks (June 2026 approximate values)
_FB_SPOT   = 0.05
_FB_MCAP   = 12_000_000.0
_FB_FDV    = 100_000_000.0
_FB_CIRC   = 257_000_000.0


def _get(url: str, timeout: int = 30) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _fetch_defillama_revenue_30d() -> tuple[float, float, list]:
    """Return (30D net revenue, 7D daily avg revenue, full chart) from DefiLlama."""
    try:
        url = f"https://api.llama.fi/summary/fees/{DEFILLAMA_SLUG}?dataType=dailyFees"
        d = _get(url, timeout=20)
        total30d = float(d.get("total30d") or 0)
        chart = d.get("totalDataChart") or []
        last7 = chart[-7:] if len(chart) >= 7 else chart
        avg7d = sum(float(v) for _, v in last7) / len(last7) if last7 else 0.0
        if total30d > 0:
            return total30d, avg7d, chart
    except Exception as e:
        print(f"[CARDS] DefiLlama revenue fetch failed ({e}); using Q1 fallback")
    fallback_daily = GP_ANN_RUN_RATE / 12 / 30
    return GP_ANN_RUN_RATE / 12, fallback_daily, []


def _compute_y3_gmv(gmv_30d: float, velocity: float, decay_months: int = 12) -> float:
    """Project Y3 annual GMV via velocity decaying linearly to 0 by decay_months."""
    monthly_gmv = gmv_30d
    for m in range(1, 37):
        alpha = velocity * max(0.0, (decay_months - (m - 1)) / decay_months) if m <= decay_months else 0.0
        monthly_gmv *= (1.0 + alpha)
    return monthly_gmv * 12


def _fetch_cg_price_history() -> dict[str, float]:
    """Return {date_str: price} for the past 365 days from CoinGecko."""
    try:
        hdrs = {"User-Agent": UA, "Accept": "application/json"}
        if _CG_KEY:
            hdrs["x-cg-pro-api-key"] = _CG_KEY
        url = f"{_CG_BASE}/coins/{CG_ID}/market_chart?vs_currency=usd&days=365&interval=daily"
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        prices = d.get("prices", [])
        result: dict[str, float] = {}
        for ts, price in prices:
            date_str = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            result[date_str] = float(price)
        return result
    except Exception as e:
        print(f"[CARDS] CoinGecko price history failed ({e})")
        return {}


def _build_revenue_history(chart: list, price_hist: dict[str, float]) -> tuple[list, list]:
    """Build month-end snapshot table and full run-rate chart from daily DefiLlama chart."""
    from collections import defaultdict
    import calendar

    if not chart:
        return [], []

    # Convert to sorted (date_str, daily_rev) list
    rows: list[tuple[str, float]] = []
    for ts, rev in chart:
        date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        rows.append((date_str, float(rev)))
    rows.sort(key=lambda x: x[0])

    # Build rolling 30D average at each date
    def rolling_30d(idx: int) -> float:
        start = max(0, idx - 29)
        vals = [rows[i][1] for i in range(start, idx + 1)]
        return sum(vals) / len(vals) if vals else 0.0

    date_to_idx = {r[0]: i for i, r in enumerate(rows)}

    # Select month-end snapshots + latest
    months_seen: set[str] = set()
    snapshot_dates: list[str] = []
    for date_str, _ in rows:
        ym = date_str[:7]  # "YYYY-MM"
        if ym not in months_seen:
            months_seen.add(ym)
        # Check if this is last day of month
        y, m, d_ = map(int, date_str.split("-"))
        last_day = calendar.monthrange(y, m)[1]
        if d_ == last_day:
            snapshot_dates.append(date_str)
    # Always include latest date
    if rows and rows[-1][0] not in snapshot_dates:
        snapshot_dates.append(rows[-1][0])

    history = []
    for date_str in snapshot_dates:
        if date_str not in date_to_idx:
            continue
        idx = date_to_idx[date_str]
        daily_rev = rows[idx][1]
        avg_30d   = rolling_30d(idx)
        ann_rev   = avg_30d * 365
        price     = price_hist.get(date_str, 0.0)
        fdv       = price * MAX_SUPPLY if price > 0 else 0.0
        fdv_rev   = fdv / ann_rev if ann_rev > 0 and fdv > 0 else 0.0
        history.append({
            "date": date_str, "daily_rev": daily_rev,
            "ann_30d_rev": ann_rev, "fdv_rev": fdv_rev,
        })

    # Run-rate chart: all rows with 30D rolling avg (for chart display)
    run_rate = []
    for i, (date_str, _) in enumerate(rows):
        avg = rolling_30d(i)
        run_rate.append({"date": date_str, "ann_30d_rev": avg * 365})

    return history, run_rate


def _fetch_cg_market() -> tuple[float, float, float, float]:
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    if _CG_KEY:
        hdrs["x-cg-pro-api-key"] = _CG_KEY
    url = f"{_CG_BASE}/coins/markets?vs_currency=usd&ids={CG_ID}&sparkline=false"
    req = urllib.request.Request(url, headers=hdrs)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.load(r)
            if not d:
                raise ValueError("empty response")
            m = d[0]
            spot   = float(m["current_price"])
            supply = float(m.get("circulating_supply") or 0)
            mcap   = spot * supply if supply > 0 else float(m.get("market_cap") or 0)
            fdv    = float(m.get("fully_diluted_valuation") or spot * MAX_SUPPLY)
            return spot, mcap, fdv, supply
        except Exception as e:
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
            else:
                raise


def _lognorm_pv(median_pv: float, sigma: float = LOG_NORMAL_SIGMA) -> dict:
    if median_pv <= 0:
        return {"p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0}
    e = math.exp
    return {
        "p25": median_pv * e(-0.6745 * sigma),
        "p50": median_pv,
        "p75": median_pv * e(0.6745 * sigma),
        "p90": median_pv * e(1.2816 * sigma),
    }


def _prob_above(target: float, median: float, sigma: float = LOG_NORMAL_SIGMA) -> float:
    if target <= 0 or median <= 0:
        return 1.0 if target <= 0 else 0.0
    z = math.log(target / median) / sigma
    return 0.5 * math.erfc(z / math.sqrt(2))


def run() -> dict:
    """Fetch live market data, compute CARDS scenarios, return standardized result dict."""
    # ── Market data ───────────────────────────────────────────────────────────
    try:
        spot, mcap, fdv, circ = _fetch_cg_market()
    except Exception as e:
        print(f"[CARDS] CoinGecko failed ({e}); using fallback")
        spot, mcap, fdv, circ = _FB_SPOT, _FB_MCAP, _FB_FDV, _FB_CIRC

    # ── Historical price data ─────────────────────────────────────────────────
    price_hist = _fetch_cg_price_history()

    # ── Live DefiLlama 30D revenue → implied GMV ─────────────────────────────
    revenue_30d, revenue_7d_daily_avg, rev_chart = _fetch_defillama_revenue_30d()
    gmv_30d          = revenue_30d / NET_SPREAD if NET_SPREAD > 0 else 0.0
    gmv_30d_ann      = gmv_30d * 12
    gmv_7d_daily_avg = revenue_7d_daily_avg / NET_SPREAD if NET_SPREAD > 0 else 0.0
    gmv_30d_daily    = gmv_30d / 30.0
    revenue_history, run_rate_chart = _build_revenue_history(rev_chart, price_hist)

    # ── Velocity-decay scenario table (A=6M, B=12M, C=24M) ───────────────────
    disc3 = (1.0 + DISCOUNT_RATE) ** 3
    vel_scenarios = []
    for dp in DECAY_PERIODS:
        y3_gmv_dp  = _compute_y3_gmv(gmv_30d, GMV_VELOCITY_INPUT, dp)
        y3_gp_dp   = y3_gmv_dp * NET_SPREAD * TRUE_GP_CONVERSION
        pv_dp      = y3_gp_dp * MULTIPLE / max(FLOAT_SUPPLY_Y3, 1) / disc3
        vel_scenarios.append({
            "decay_months": dp, "y3_gmv": y3_gmv_dp, "y3_gp": y3_gp_dp, "pv": pv_dp,
        })
    # Weighted
    y3_gmv_wtd = sum(DECAY_WEIGHTS[i] * vel_scenarios[i]["y3_gmv"] for i in range(3))
    y3_gp_wtd  = sum(DECAY_WEIGHTS[i] * vel_scenarios[i]["y3_gp"]  for i in range(3))
    pv_wtd     = sum(DECAY_WEIGHTS[i] * vel_scenarios[i]["pv"]      for i in range(3))
    # Full FDV supply row (use 12M GMV, full 2B supply)
    pv_fdv = vel_scenarios[1]["y3_gp"] * MULTIPLE / max(MAX_SUPPLY, 1) / disc3

    y3_gmv_base = vel_scenarios[1]["y3_gmv"]  # 12M = base

    disc         = (1.0 + DISCOUNT_RATE) ** 3
    scenario_list = []

    y3_gp_p50     = 0.0
    y3_supply_p50 = 0.0

    for sc_key, sc_label, y3_gp, y3_supply, is_primary in SCENARIOS:
        # Y3 price formula from dashboard: Y3_GP × 15 × 1.10 / Y3_supply
        y3_price  = y3_gp * MULTIPLE * OPTIONALITY / max(y3_supply, 1.0)
        pv_median = y3_price / disc

        pv_dist = _lognorm_pv(pv_median)
        ev      = pv_median * math.exp(LOG_NORMAL_SIGMA ** 2 / 2)

        scenario_list.append({
            "key": sc_key,
            "label": sc_label,
            "is_primary": is_primary,
            "pv": pv_dist,
            "ev": ev,
            "prob_above_spot": _prob_above(spot, pv_median),
            "prob_3x": _prob_above(3 * spot, pv_median),
            "y3_price_p50": y3_price,
            "y3_mcap_p50": y3_price * y3_supply,
            "y3_supply_p50": float(y3_supply),
            "y3_gp_p50": float(y3_gp),
        })

        if is_primary:
            y3_gp_p50     = float(y3_gp)
            y3_supply_p50 = float(y3_supply)
            # Weighted PV: 40% 6M decay, 40% 12M decay, 20% 24M decay
            y3_price_primary = y3_gp * MULTIPLE * OPTIONALITY / max(y3_supply, 1.0)
            pv_6m  = y3_price_primary / (1 + DISCOUNT_RATE) ** 0.5
            pv_12m = y3_price_primary / (1 + DISCOUNT_RATE) ** 1.0
            pv_24m = y3_price_primary / (1 + DISCOUNT_RATE) ** 2.0
            weighted_pv = 0.4 * pv_6m + 0.4 * pv_12m + 0.2 * pv_24m

    result = {
        "token": "CARDS",
        "name": "Collector Crypt",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "market": {
            "spot": spot, "market_cap": mcap, "fdv": fdv,
            "circulating_supply": circ, "max_supply": float(MAX_SUPPLY),
        },
        "model": {
            "type": "3Y GP × 15 × 1.10 Manual Scenarios",
            "discount_rate": DISCOUNT_RATE,
            "multiple": MULTIPLE,
            "paths": 1,
            "note": (
                "Y3_price = Y3_GP × 15 × 1.10 / Y3_supply. "
                "GP = Y3_GMV × margin (margin is the scenario lever: bear=5% floor, base=8.4% blend, bull=12%). "
                "Q1 2026: $146.9M GMV at 5.9% margin = $8.6M GP ($34.4M annualized). "
                "Supply is rules-based: Foundation (730M, 36.5%) stays locked in base/bull; only releases in bear. "
                "Bull assumes ~100M additional buyback. Distributions approximate log-normal σ=1.0."
            ),
        },
        "current_gp": {
            "gmv_q1_2026": float(GMV_Q1_2026),
            "gross_margin": float(GROSS_MARGIN_Q1),
            "gross_profit_q1": float(GP_Q1_2026),
            "gross_profit_ann": float(GP_ANN_RUN_RATE),
            "revenue_30d": float(revenue_30d),
            "gmv_30d": float(gmv_30d),
            "gmv_30d_ann": float(gmv_30d_ann),
            "net_spread": float(NET_SPREAD),
            "gmv_velocity_input": float(GMV_VELOCITY_INPUT),
            "gmv_7d_daily_avg": float(gmv_7d_daily_avg),
            "gmv_30d_daily_avg": float(gmv_30d_daily),
            "y3_gmv_base": float(y3_gmv_base),
            "true_gp_conversion": float(TRUE_GP_CONVERSION),
            "float_supply_y3": float(FLOAT_SUPPLY_Y3),
            "weighted_pv": float(weighted_pv),
            "velocity_scenarios": [
                {"label": "A: 6M velocity decay",  **{k: float(v) for k, v in vel_scenarios[0].items()}},
                {"label": "B: 12M velocity decay", **{k: float(v) for k, v in vel_scenarios[1].items()}},
                {"label": "C: 24M velocity decay", **{k: float(v) for k, v in vel_scenarios[2].items()}},
                {"label": "Weighted 40/40/20",     "decay_months": 0,  "y3_gmv": float(y3_gmv_wtd), "y3_gp": float(y3_gp_wtd), "pv": float(pv_wtd)},
                {"label": "Base, full FDV supply",  "decay_months": 12, "y3_gmv": float(vel_scenarios[1]["y3_gmv"]), "y3_gp": float(vel_scenarios[1]["y3_gp"]), "pv": float(pv_fdv)},
            ],
            "y3_gp_base": float(vel_scenarios[1]["y3_gp"]),
            "y3_supply_float": float(FLOAT_SUPPLY_Y3),
            "locked_supply": float(LOCKED_SUPPLY_EST),
            "treasury_assets": float(TREASURY_ASSETS),
            "treasury_card_pct": float(TREASURY_CARD_PCT),
            "y3_gp_p50": float(y3_gp_p50),
            "y3_supply_p50": float(y3_supply_p50),
        },
        "scenarios": scenario_list,
        "caveats": [
            "Gacha revenue is highly seasonal and tied to Pokémon/TCG hype cycles; Q1 2026 peak may not be representative.",
            "Supply expansion (team, foundation, community unlocks) is the dominant model headwind; vesting schedules not fully public.",
            "No formal buyback % is publicly committed; full GP→buyback assumption may overstate token demand.",
            "Gross margin floor set at ~5% (high-price pack house edge); base assumes 8.4% blend, bull 12% — none guaranteed.",
            "Distributions approximate log-normal σ=1.0; no Monte Carlo simulation.",
        ],
        "data_freshness": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "hist_charts": {
            "revenue_history": revenue_history,
            "run_rate_chart":  run_rate_chart,
        },
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "cards_result.json", "w") as f:
        json.dump(result, f, indent=2)

    return result
