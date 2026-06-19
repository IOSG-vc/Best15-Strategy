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
NET_SPREAD = 0.1235              # 12.35% — research estimate

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

# Scenarios: (key, label, y3_gp, y3_supply, is_primary)
SCENARIOS = [
    ("bear", "Bear: $20M GP, 1.5B supply",  20_000_000,  1_500_000_000, False),
    ("base", "Base: $45M GP, 1.0B supply",  45_000_000,  1_000_000_000, True),
    ("bull", "Bull: $85M GP, 0.8B supply",  85_000_000,    800_000_000, False),
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


def _fetch_defillama_revenue_30d() -> float:
    """Return 30D net revenue from DefiLlama fees endpoint; fallback to Q1 run-rate."""
    try:
        url = f"https://api.llama.fi/summary/fees/{DEFILLAMA_SLUG}?dataType=dailyFees"
        d = _get(url, timeout=20)
        val = float(d.get("total30d") or 0)
        if val > 0:
            return val
    except Exception as e:
        print(f"[CARDS] DefiLlama revenue fetch failed ({e}); using Q1 fallback")
    return GP_ANN_RUN_RATE / 12  # monthly run-rate fallback


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
            mcap   = float(m["market_cap"])
            fdv    = float(m.get("fully_diluted_valuation") or mcap)
            supply = float(m.get("circulating_supply") or mcap / spot)
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

    # ── Live DefiLlama 30D revenue → implied GMV ─────────────────────────────
    revenue_30d    = _fetch_defillama_revenue_30d()
    gmv_30d        = revenue_30d / NET_SPREAD if NET_SPREAD > 0 else 0.0
    gmv_30d_ann    = gmv_30d * 12

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
                "GP = Gacha pack sales GP + marketplace fees. "
                "Q1 2026: $146.9M GMV at 5.9% margin = $8.6M GP ($34.4M annualized). "
                "Y3 supply risk is the dominant headwind (team + foundation + community unlocks). "
                "Distributions approximate log-normal σ=1.0."
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
            "true_gp_conversion": float(TRUE_GP_CONVERSION),
            "weighted_pv": float(weighted_pv),
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
            "Gross margin (5.9% Q1 2026) is highly compressed; recovery to 8%+ is assumed in base/bull but not guaranteed.",
            "Distributions approximate log-normal σ=1.0; no Monte Carlo simulation.",
        ],
        "data_freshness": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "cards_result.json", "w") as f:
        json.dump(result, f, indent=2)

    return result
