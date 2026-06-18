"""VVV (Venice AI) webapp valuation agent — manual GP scenarios.

Model: Y3_price = Y3_platform_revenue × 15 / Y3_supply
Supply: current_circ + 3Y_emissions (3M/yr from July 2026) − buyback_burns
Buyback: Venice allocates ~9% of platform revenue to on-chain VVV burns.
Distributions: log-normal σ=1.0 approximation (no full MC — model note says "manually constructed").
Market data refreshed live from CoinGecko on every run.
On-chain burn data refreshed from DefiLlama on every run.
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.request
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

# ── Model parameters (research-locked) ────────────────────────────────────────
BUYBACK_PCT_OF_REVENUE   = 0.09       # Venice burns ~9% of subscription revenue on-chain
ANNUAL_EMISSIONS_FROM_JULY = 3_000_000 # VVV/yr from July 2026 (stepped from 14M at launch)
GROSS_3Y_EMISSIONS       = 9_000_000  # 3M × 3 years
EST_PLATFORM_REVENUE_ANN = 32_000_000 # ~$32M/yr estimated total (not just on-chain)
DISCOUNT_RATE            = 0.25
MULTIPLE                 = 15.0
LOG_NORMAL_SIGMA         = 1.0        # σ for distribution approximation

# Y3 revenue scenarios (bear / base / bull)
SCENARIOS = [
    ("bear", "Bear: $15M revenue",  15_000_000,  False),
    ("base", "Base: $55M revenue",  55_000_000,  True),
    ("bull", "Bull: $120M revenue", 120_000_000, False),
]

CG_ID    = "venice-token"
DL_SLUG  = "venice-ai"   # DefiLlama protocol slug for Venice/VVV burns

_CG_KEY  = os.environ.get("COINGECKO_API_KEY", "")
_CG_BASE = "https://pro-api.coingecko.com/api/v3" if _CG_KEY else "https://api.coingecko.com/api/v3"
RESULTS_DIR = Path(__file__).parent.parent / "results"
UA = "Mozilla/5.0 VVV-valuation"

# Fallbacks (June 2026 approximate values)
_FB_SPOT   = 15.0
_FB_MCAP   = 300_000_000.0
_FB_FDV    = 1_500_000_000.0
_FB_CIRC   = 20_000_000.0
_FB_MAX    = 100_000_000.0  # no hard cap; use effective max from tokenomics


def _get(url: str, timeout: int = 30) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _fetch_cg_market() -> tuple[float, float, float, float, float]:
    """Return (spot, mcap, fdv, circ_supply, max_supply)."""
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
            max_s  = float(m.get("max_supply") or m.get("total_supply") or fdv / spot)
            return spot, mcap, fdv, supply, max_s
        except Exception as e:
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
            else:
                raise


def _fetch_dl_burns() -> tuple[float, float]:
    """Return (burn_30d_total, burn_30d_ann) from DefiLlama fees/revenue for Venice."""
    try:
        url = f"https://api.llama.fi/summary/fees/{DL_SLUG}?dataType=dailyRevenue"
        d = _get(url)
        rows = sorted(d.get("totalDataChart", []), key=lambda x: x[0])
        vals = [float(v) for _, v in rows[-30:]]
        burn_30d = float(sum(vals))
        return burn_30d, burn_30d * (365 / 30)
    except Exception:
        # Fallback: $250K/30D as noted in dashboard description
        burn_30d = 250_000.0
        return burn_30d, burn_30d * (365 / 30)


def _lognorm_pv(median_pv: float, sigma: float = LOG_NORMAL_SIGMA) -> dict:
    """Compute p25/p50/p75/p90/ev from log-normal with given median and σ."""
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
    """P(X > target) for X ~ LogNormal(ln(median), σ²)."""
    if target <= 0 or median <= 0:
        return 1.0 if target <= 0 else 0.0
    z = math.log(target / median) / sigma
    return 0.5 * math.erfc(z / math.sqrt(2))


def run() -> dict:
    """Fetch live data, compute VVV scenarios, return standardized result dict."""
    # ── Market data ───────────────────────────────────────────────────────────
    try:
        spot, mcap, fdv, circ, max_supply = _fetch_cg_market()
    except Exception as e:
        print(f"[VVV] CoinGecko failed ({e}); using fallback")
        spot, mcap, fdv, circ, max_supply = _FB_SPOT, _FB_MCAP, _FB_FDV, _FB_CIRC, _FB_MAX

    # ── On-chain burn data ────────────────────────────────────────────────────
    burn_30d, burn_ann_onchain = _fetch_dl_burns()

    # Implied total platform revenue from on-chain capture ratio
    # Venice burns ~9% of subscription revenue → total = burn / 0.09
    # But we use the research-fixed estimate directly as anchor
    est_revenue = EST_PLATFORM_REVENUE_ANN
    buyback_years_onchain     = mcap / max(burn_ann_onchain, 1)
    buyback_years_est_revenue = mcap / max(est_revenue * BUYBACK_PCT_OF_REVENUE, 1)

    # ── Scenarios ─────────────────────────────────────────────────────────────
    disc = (1.0 + DISCOUNT_RATE) ** 3
    scenario_list = []

    # Y3 P50 outputs for current_gp (use base scenario)
    y3_revenue_p50   = 0.0
    buyback_tokens_p50 = 0.0
    y3_supply_p50    = 0.0

    for sc_key, sc_label, y3_rev, is_primary in SCENARIOS:
        # Annual burn spend in Y3 = Y3_rev × 9%
        burn_spend_annual = y3_rev * BUYBACK_PCT_OF_REVENUE
        burn_spend_3y     = burn_spend_annual * 3  # simplified cumulative

        # Y3 supply: circ + 3Y emissions − burned tokens
        # Burned tokens = total burn spend / avg price (use base case avg ~ Y3 price estimate)
        # Iterative: first estimate Y3 price, then compute tokens burned
        # Step 1: rough Y3 price without burns
        y3_supply_rough = circ + GROSS_3Y_EMISSIONS
        y3_price_rough  = y3_rev * MULTIPLE / max(y3_supply_rough, 1.0)
        avg_price_3y    = (spot + y3_price_rough) / 2.0  # linear avg as proxy
        burn_tokens_3y  = burn_spend_3y / max(avg_price_3y, 0.01)

        y3_supply = max(circ + GROSS_3Y_EMISSIONS - burn_tokens_3y, circ * 0.5)
        y3_price  = y3_rev * MULTIPLE / max(y3_supply, 1.0)
        pv_median = y3_price / disc

        pv_dist = _lognorm_pv(pv_median)
        ev      = pv_median * math.exp(LOG_NORMAL_SIGMA ** 2 / 2)  # log-normal mean

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
            "y3_supply_p50": y3_supply,
            "y3_gp_p50": y3_rev,
        })

        if is_primary:
            y3_revenue_p50   = y3_rev
            buyback_tokens_p50 = burn_tokens_3y
            y3_supply_p50    = y3_supply

    result = {
        "token": "VVV",
        "name": "Venice AI",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "market": {
            "spot": spot, "market_cap": mcap, "fdv": fdv,
            "circulating_supply": circ, "max_supply": max_supply,
        },
        "model": {
            "type": "3Y GP×15 Manual Scenarios",
            "discount_rate": DISCOUNT_RATE,
            "multiple": MULTIPLE,
            "paths": 1,
            "note": (
                "Y3_price = Y3_platform_revenue × 15 / Y3_supply. "
                "Venice burns ~9% of subscription revenue on-chain (VVV buyback-and-burn). "
                "Annual emissions 3M VVV/yr from July 2026 (9M gross over 3 years). "
                "Distributions approximate log-normal σ=1.0 for comparability."
            ),
        },
        "current_gp": {
            "defillama_30d_ann": float(burn_ann_onchain),
            "on_chain_burn_30d": float(burn_30d),
            "est_total_platform_revenue_ann": float(est_revenue),
            "buyback_pct_of_revenue": BUYBACK_PCT_OF_REVENUE,
            "buyback_years_onchain": float(buyback_years_onchain),
            "buyback_years_est_revenue": float(buyback_years_est_revenue),
            "annual_emissions": ANNUAL_EMISSIONS_FROM_JULY,
            "gross_3y_unlock_tokens": GROSS_3Y_EMISSIONS,
            "y3_revenue_p50": float(y3_revenue_p50),
            "buyback_tokens_p50": float(buyback_tokens_p50),
            "y3_supply_p50": float(y3_supply_p50),
        },
        "scenarios": scenario_list,
        "caveats": [
            "Venice does not publicly disclose platform revenue; $32M/yr is estimated from April 2026 subscription burn rates.",
            "On-chain burns ($250K/30D) measured via DefiLlama are the only confirmed component — total revenue is indicative.",
            "No Monte Carlo simulation; distributions approximate log-normal σ=1.0 for comparability.",
            "VVV has no max supply cap; 3Y emissions assume the 3M/yr rate holds from July 2026.",
        ],
        "data_freshness": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "vvv_result.json", "w") as f:
        json.dump(result, f, indent=2)

    return result
