"""JUP locked valuation agent — adapted for webapp (local output paths, run() entrypoint).

Logic is identical to jup_locked_agent.py from the bundle. Changes:
- OUTDIR points to webapp/results/ instead of src/
- run() function returns a standardized dict for the frontend
"""
from __future__ import annotations

import json
import math
import os
import statistics
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")

N_PATHS = 100_000
MONTHS = 36
DISCOUNT = 0.244
MULTIPLE = 15.0
SCHEDULED_UNLOCKS_PER_MONTH = 0.0
COLD_STORAGE_COMMUNITY_RESERVE = 3.405e9
BUYBACK_SHARE = 0.50
AGG_RAKE_BPS_FALLBACK = 3.55
PREMIUMS = {
    "core": 1.00,
    "opt_10": 1.10,
    "opt_10_jupnet_10": 1.20,
}


def fetch_json(url: str, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception:
            if i == 2:
                raise
            time.sleep(2 * (i + 1))


def cg_market():
    url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=jupiter-exchange-solana"
    arr = fetch_json(url)
    if not arr:
        raise RuntimeError("CoinGecko returned no JUP market data")
    return arr[0]


def llama_summary(kind: str, slug: str, data_type: str):
    return fetch_json(f"https://api.llama.fi/summary/{kind}/{slug}?dataType={data_type}")


def chart_rows(data):
    rows = []
    for ts, val in data.get("totalDataChart", []) or []:
        try:
            rows.append((datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat(), float(val or 0)))
        except Exception:
            pass
    rows.sort()
    return rows


def monthly_sums(rows):
    d = defaultdict(float)
    for day, val in rows:
        d[day[:7]] += float(val)
    return sorted(d.items())


def trailing_sum(rows, n=30):
    return float(sum(v for _, v in rows[-n:])) if rows else 0.0


def median_last12(months):
    vals = [v for _, v in months[-12:] if v > 0]
    return float(statistics.median(vals)) if vals else 0.0


def pct_dict(x, qs=(25, 50, 75, 90)):
    return {f"p{q}": float(np.percentile(x, q)) for q in qs}


def fmt_money(x):
    ax = abs(float(x))
    if ax >= 1e9:
        return f"${x/1e9:.2f}B"
    if ax >= 1e6:
        return f"${x/1e6:.1f}M"
    if ax >= 1e3:
        return f"${x/1e3:.1f}K"
    return f"${x:.3f}"


def gp_series_and_seeds():
    perps_fees = chart_rows(llama_summary("fees", "jupiter-perpetual-exchange", "dailyFees"))
    agg_fees = chart_rows(llama_summary("fees", "jupiter-aggregator", "dailyFees"))
    jupz_vol = chart_rows(llama_summary("dexs", "jupiterz", "dailyVolume"))
    lend_revenue = chart_rows(llama_summary("fees", "jupiter-lend", "dailyRevenue"))
    jupsol_revenue = chart_rows(llama_summary("fees", "jupiter-staked-sol", "dailyRevenue"))
    ape_revenue = chart_rows(llama_summary("fees", "ape-jupiter", "dailyRevenue"))
    prediction_revenue = chart_rows(llama_summary("fees", "jupiter-prediction", "dailyRevenue"))
    dca_fees = chart_rows(llama_summary("fees", "jupiter-dca", "dailyFees"))

    rake = AGG_RAKE_BPS_FALLBACK / 10000.0
    perps_gp_daily = [(d, v * 0.25) for d, v in perps_fees]
    agg_gp_daily = agg_fees
    jupz_gp_daily = [(d, v * rake) for d, v in jupz_vol]

    perps_months = monthly_sums(perps_gp_daily)
    spot_by_month = defaultdict(float)
    for d, v in agg_gp_daily:
        spot_by_month[d[:7]] += v
    for d, v in jupz_gp_daily:
        spot_by_month[d[:7]] += v
    spot_months = sorted(spot_by_month.items())

    perps_30 = trailing_sum(perps_gp_daily, 30)
    agg_30 = trailing_sum(agg_gp_daily, 30)
    jupz_vol_30 = trailing_sum(jupz_vol, 30)
    jupz_gp_30 = jupz_vol_30 * rake
    lend_30 = trailing_sum(lend_revenue, 30)
    jupsol_30 = trailing_sum(jupsol_revenue, 30)
    ape_30 = trailing_sum(ape_revenue, 30)
    prediction_30 = trailing_sum(prediction_revenue, 30)
    dca_30 = trailing_sum(dca_fees, 30)
    tracked_optional_30 = lend_30 + jupsol_30 + ape_30 + prediction_30 + dca_30
    spot_30 = agg_30 + jupz_gp_30
    total_30 = perps_30 + spot_30

    perps_med12 = median_last12(perps_months)
    spot_med12 = median_last12(spot_months)
    perps_seed = min(perps_30, perps_med12) if perps_med12 else perps_30
    spot_seed = min(spot_30, spot_med12) if spot_med12 else spot_30

    return {
        "months": {"perps_gp": perps_months, "spot_gp": spot_months},
        "seeds": {
            "perps_30d_gp": perps_30,
            "perps_12m_median_gp": perps_med12,
            "perps_seed_gp": perps_seed,
            "aggregator_30d_gp": agg_30,
            "jupiterz_30d_volume": jupz_vol_30,
            "jupiterz_implied_30d_gp": jupz_gp_30,
            "spot_30d_gp": spot_30,
            "spot_12m_median_gp": spot_med12,
            "spot_seed_gp": spot_seed,
            "total_30d_gp": total_30,
            "total_seed_gp": perps_seed + spot_seed,
            "dca_30d_fees_optional": dca_30,
            "lend_30d_revenue_optional": lend_30,
            "jupsol_30d_revenue_optional": jupsol_30,
            "ape_30d_revenue_optional": ape_30,
            "prediction_30d_revenue_optional": prediction_30,
            "tracked_optional_30d_revenue": tracked_optional_30,
            "jupiterz_rake_bps": AGG_RAKE_BPS_FALLBACK,
        },
        "last_dates": {
            "perps_fees": perps_fees[-1][0] if perps_fees else None,
            "aggregator_fees": agg_fees[-1][0] if agg_fees else None,
            "jupiterz_volume": jupz_vol[-1][0] if jupz_vol else None,
            "dca_fees": dca_fees[-1][0] if dca_fees else None,
            "lend_revenue": lend_revenue[-1][0] if lend_revenue else None,
            "jupsol_revenue": jupsol_revenue[-1][0] if jupsol_revenue else None,
        },
    }


def sample_returns(months):
    current_month = datetime.now(timezone.utc).date().isoformat()[:7]
    vals = [v for m, v in months if v > 0 and m >= "2024-01" and m < current_month]
    rets = []
    for a, b in zip(vals, vals[1:]):
        if a > 0 and b > 0:
            rets.append(max(-0.75, min(0.75, math.log(b / a))))
    if len(rets) < 6:
        return np.array([0.0])
    return np.array(rets, dtype=float)


def run_mc(market, gpdata):
    spot = float(market["current_price"])
    circ = float(market.get("circulating_supply") or market["market_cap"] / spot)
    perps_seed = gpdata["seeds"]["perps_seed_gp"]
    spot_seed = gpdata["seeds"]["spot_seed_gp"]
    perps_rets = sample_returns(gpdata["months"]["perps_gp"])
    spot_rets = sample_returns(gpdata["months"]["spot_gp"])

    rng = np.random.default_rng(42)
    perps_draws = rng.choice(perps_rets, size=(N_PATHS, MONTHS), replace=True)
    spot_draws = rng.choice(spot_rets, size=(N_PATHS, MONTHS), replace=True)
    perps_monthly = perps_seed * np.exp(np.cumsum(perps_draws, axis=1))
    spot_monthly = spot_seed * np.exp(np.cumsum(spot_draws, axis=1))
    perps_monthly = np.minimum(perps_monthly, perps_seed * 8.0)
    spot_monthly = np.minimum(spot_monthly, spot_seed * 8.0)
    total_monthly = perps_monthly + spot_monthly
    y3_perps_gp = perps_monthly[:, -12:].sum(axis=1)
    y3_spot_gp = spot_monthly[:, -12:].sum(axis=1)
    y3_gp = y3_perps_gp + y3_spot_gp

    supply = np.full(N_PATHS, circ, dtype=float)
    buyback_tokens_accum = np.zeros(N_PATHS, dtype=float)
    for t in range(MONTHS):
        buy_tokens = (total_monthly[:, t] * BUYBACK_SHARE) / max(spot, 0.01)
        supply += SCHEDULED_UNLOCKS_PER_MONTH - buy_tokens
        buyback_tokens_accum += buy_tokens
    supply = np.maximum(supply, 1.0)

    y3_price_core = y3_gp * MULTIPLE / supply
    result_cases = {}
    for key, premium in PREMIUMS.items():
        y3_price = y3_price_core * premium
        pv = y3_price / ((1 + DISCOUNT) ** 3)
        result_cases[key] = {
            "discounted_pv": pct_dict(pv),
            "discounted_ev": float(np.mean(pv)),
            "p50_to_spot": float(np.percentile(pv, 50) / spot),
            "ev_to_spot": float(np.mean(pv) / spot),
            "prob_pv_gt_spot": float(np.mean(pv > spot)),
            "prob_pv_gt_2x": float(np.mean(pv > 2 * spot)),
            "prob_pv_gt_3x": float(np.mean(pv > 3 * spot)),
        }

    return {
        "mc": {
            "paths": N_PATHS,
            "months": MONTHS,
            "perps_logret_mean": float(np.mean(perps_rets)),
            "perps_logret_std": float(np.std(perps_rets, ddof=1)) if len(perps_rets) > 1 else 0.0,
            "spot_logret_mean": float(np.mean(spot_rets)),
            "spot_logret_std": float(np.std(spot_rets, ddof=1)) if len(spot_rets) > 1 else 0.0,
        },
        "y3_state": {
            "y3_ttm_gp": pct_dict(y3_gp),
            "y3_perps_gp": pct_dict(y3_perps_gp),
            "y3_spot_gp": pct_dict(y3_spot_gp),
            "y3_effective_supply": pct_dict(supply),
            "buyback_accum_tokens": pct_dict(buyback_tokens_accum),
        },
        "cases": result_cases,
    }


def run() -> dict:
    """Fetch live data, run MC, return standardized result dict for the frontend."""
    market = cg_market()
    gpdata = gp_series_and_seeds()
    valuation = run_mc(market, gpdata)

    spot = float(market["current_price"])
    s = gpdata["seeds"]
    c = valuation["cases"]

    scenarios = []
    case_labels = [
        ("core", "Core GP", True),
        ("opt_10", "+10% Optionality", False),
        ("opt_10_jupnet_10", "+10% Opt + Jupnet", False),
    ]
    for key, label, is_primary in case_labels:
        case = c[key]
        pv = case["discounted_pv"]
        scenarios.append({
            "key": key,
            "label": label,
            "pv": {"p25": pv["p25"], "p50": pv["p50"], "p75": pv["p75"], "p90": pv["p90"]},
            "ev": case["discounted_ev"],
            "prob_above_spot": case["prob_pv_gt_spot"],
            "prob_3x": case["prob_pv_gt_3x"],
            "is_primary": is_primary,
        })

    result = {
        "token": "JUP",
        "name": "Jupiter",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "market": {
            "spot": spot,
            "market_cap": float(market["market_cap"]),
            "fdv": float(market.get("fully_diluted_valuation") or 0),
            "circulating_supply": float(market.get("circulating_supply") or 0),
        },
        "model": {
            "type": "3Y GP-Capture Monte Carlo",
            "discount_rate": DISCOUNT,
            "multiple": MULTIPLE,
            "paths": N_PATHS,
            "note": "50% of entity GP used for buybacks; 0 scheduled unlocks until Jupiter announces reserve plan",
        },
        "current_gp": {
            "perps_30d": s["perps_30d_gp"],
            "aggregator_30d": s["aggregator_30d_gp"],
            "jupiterz_30d": s["jupiterz_implied_30d_gp"],
            "total_30d": s["total_30d_gp"],
            "seed_monthly": s["total_seed_gp"],
            "seed_annualized": s["total_seed_gp"] * 12,
            "optional_tracked_30d": s["tracked_optional_30d_revenue"],
        },
        "y3_state": valuation["y3_state"],
        "scenarios": scenarios,
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "jup_result.json"), "w") as f:
        json.dump(result, f, indent=2)

    return result
