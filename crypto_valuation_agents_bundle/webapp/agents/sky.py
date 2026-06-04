"""SKY webapp valuation agent.

Monte Carlo model adapted from src/sky_mc_agent.py.
Uses sky_data_collection.json + sky_research_extra.json from the bundle root
for market-cycle growth distribution.
Market data (spot, mcap, fdv, supply) is fetched live from CoinGecko.

Model framework:
  Gross income / fees - savings-rate cost = GP
  GP - OPEX = net profit
  USDS growth follows capped money-market/yield TVL path; DAI flat in base.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

BUNDLE_ROOT = Path(__file__).parent.parent.parent
DATA_PATH = BUNDLE_ROOT / "sky_data_collection.json"
EXTRA_PATH = BUNDLE_ROOT / "sky_research_extra.json"

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")

_CG_KEY = os.environ.get("COINGECKO_API_KEY", "")
_CG_BASE = "https://pro-api.coingecko.com/api/v3" if _CG_KEY else "https://api.coingecko.com/api/v3"

# Fallback market data from sky_data_collection.json (2026-05-08) used when CG is unavailable
_FALLBACK_SPOT = 0.08084
_FALLBACK_SUPPLY = 23.462665147e9
_FALLBACK_MCAP = 1.876588264e9
_FALLBACK_FDV = 1.896796712e9


def _fetch_cg_market():
    """Fetch live SKY market data from CoinGecko. Returns (spot, mcap, fdv, supply)."""
    url = f"{_CG_BASE}/coins/markets?vs_currency=usd&ids=sky&sparkline=false"
    hdrs = {"User-Agent": "Mozilla/5.0"}
    if _CG_KEY:
        hdrs["x-cg-pro-api-key"] = _CG_KEY
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    m = data[0]
    spot = float(m["current_price"])
    mcap = float(m["market_cap"])
    fdv = float(m.get("fully_diluted_valuation") or mcap)
    supply = float(m.get("circulating_supply") or mcap / spot)
    return spot, mcap, fdv, supply

USDS_SUPPLY = 6.426632076e9
DAI_SUPPLY = 4.165943911e9
SUSDS_SUPPLY = 5.218832683e9
SDAI_SUPPLY = 0.239828197e9
TOTAL_STABLE_SUPPLY = USDS_SUPPLY + DAI_SUPPLY

GROSS_INCOME = 425.2e6
SAVINGS_EXPENSE = 193.49e6
STUSDS_EXPENSE = 13.23e6
CURRENT_OPEX_SITE = 43.93e6

GROSS_INCOME_YIELD = GROSS_INCOME / TOTAL_STABLE_SUPPLY
SAVINGS_RATE = 0.0365
USDS_SAVINGS_PENETRATION = SUSDS_SUPPLY / USDS_SUPPLY
DAI_SAVINGS_PENETRATION = SDAI_SUPPLY / DAI_SUPPLY
STUSDS_EXPENSE_RATE_ON_USDS = STUSDS_EXPENSE / USDS_SUPPLY

HORIZON_MONTHS = 36
DISCOUNT_RATE = 0.25
PATHS = 100_000
SEED = 42

OPEX_SCENARIOS = {
    "bear_90m_opex": 90e6,
    "base_70m_opex": 70e6,
    "bull_50m_opex": 50e6,
}
GP_MULTIPLE = 10.0
NP_MULTIPLE = 15.0

MONTHLY_GROWTH_CAP_LOW = -0.08
MONTHLY_GROWTH_CAP_HIGH = 0.10
GROWTH_DAMPENER = 0.65


def _load_growth_distribution() -> np.ndarray:
    j = json.loads(EXTRA_PATH.read_text())
    rets = np.array(j["money_market_log_returns"], dtype=float)
    return np.clip(rets * GROWTH_DAMPENER, MONTHLY_GROWTH_CAP_LOW, MONTHLY_GROWTH_CAP_HIGH)


def _simulate(opex: float, np_multiple: float, spot: float, sky_supply: float) -> dict:
    rng = np.random.default_rng(SEED)
    monthly_log_returns = _load_growth_distribution()
    sampled = rng.choice(monthly_log_returns, size=(PATHS, HORIZON_MONTHS), replace=True)
    usds = np.full(PATHS, USDS_SUPPLY, dtype=float)
    dai = np.full(PATHS, DAI_SUPPLY, dtype=float)
    monthly_gp = np.zeros((PATHS, HORIZON_MONTHS), dtype=float)
    monthly_np = np.zeros((PATHS, HORIZON_MONTHS), dtype=float)

    for m in range(HORIZON_MONTHS):
        usds *= np.exp(sampled[:, m])
        total = usds + dai
        gross_income_m = total * GROSS_INCOME_YIELD / 12.0
        savings_cost_m = (usds * USDS_SAVINGS_PENETRATION + dai * DAI_SAVINGS_PENETRATION) * SAVINGS_RATE / 12.0
        stusds_cost_m = usds * STUSDS_EXPENSE_RATE_ON_USDS / 12.0
        gp_m = gross_income_m - savings_cost_m - stusds_cost_m
        np_m = gp_m - opex / 12.0
        monthly_gp[:, m] = gp_m
        monthly_np[:, m] = np_m

    y3_ttm_gp = monthly_gp[:, -12:].sum(axis=1)
    y3_ttm_np = monthly_np[:, -12:].sum(axis=1)
    y3_ttm_np_floor = np.maximum(y3_ttm_np, 0.0)
    accumulated_treasury_cash = np.maximum(monthly_np, 0.0).sum(axis=1)

    undiscounted_gp_price = y3_ttm_gp * GP_MULTIPLE / sky_supply
    undiscounted_np_price = y3_ttm_np_floor * np_multiple / sky_supply
    disc = (1.0 + DISCOUNT_RATE) ** 3
    pv_gp = undiscounted_gp_price / disc
    pv_np = undiscounted_np_price / disc

    def pack(arr):
        return {
            "p25": float(np.percentile(arr, 25)),
            "p50": float(np.percentile(arr, 50)),
            "p75": float(np.percentile(arr, 75)),
            "p90": float(np.percentile(arr, 90)),
            "ev_mean": float(np.mean(arr)),
            "prob_spot_justified": float(np.mean(arr >= spot)),
            "prob_3x": float(np.mean(arr >= 3 * spot)),
        }

    return {
        "opex": opex,
        "np_multiple": np_multiple,
        "pv_gp_10x": pack(pv_gp),
        "pv_np": pack(pv_np),
        "y3_ttm_gp": pack(y3_ttm_gp),
        "y3_ttm_net_profit": pack(y3_ttm_np),
        "y3_usds_supply": pack(usds),
        "accumulated_treasury_cash": pack(accumulated_treasury_cash),
    }


def run() -> dict:
    """Fetch live SKY market data, run MC model, return standardized result dict."""
    # Live market data — fallback to locked values if CoinGecko is unavailable
    try:
        spot, mcap, fdv, sky_supply = _fetch_cg_market()
    except Exception as e:
        print(f"[SKY] CoinGecko fetch failed ({e}); using fallback market data")
        spot, mcap, fdv, sky_supply = _FALLBACK_SPOT, _FALLBACK_MCAP, _FALLBACK_FDV, _FALLBACK_SUPPLY

    scenarios_raw = {}
    for name, opex in OPEX_SCENARIOS.items():
        scenarios_raw[name] = _simulate(opex, NP_MULTIPLE, spot, sky_supply)

    current_gp = GROSS_INCOME - SAVINGS_EXPENSE - STUSDS_EXPENSE
    base_opex = OPEX_SCENARIOS["base_70m_opex"]
    current_np_base = current_gp - base_opex

    def _make_scenario(key, label, is_primary, raw_key, value_key):
        s = scenarios_raw[raw_key][value_key]
        return {
            "key": key,
            "label": label,
            "is_primary": is_primary,
            "pv": {"p25": s["p25"], "p50": s["p50"], "p75": s["p75"], "p90": s["p90"]},
            "ev": s["ev_mean"],
            "prob_above_spot": s["prob_spot_justified"],
            "prob_3x": s["prob_3x"],
        }

    scenarios = [
        _make_scenario("base_np15x", "Base OPEX ($70M), 15× NP", True,  "base_70m_opex", "pv_np"),
        _make_scenario("base_gp10x", "Base OPEX ($70M), 10× GP", False, "base_70m_opex", "pv_gp_10x"),
        _make_scenario("bear_np15x", "Bear OPEX ($90M), 15× NP", False, "bear_90m_opex", "pv_np"),
        _make_scenario("bull_np15x", "Bull OPEX ($50M), 15× NP", False, "bull_50m_opex", "pv_np"),
    ]

    result = {
        "token": "SKY",
        "name": "Sky",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "market": {
            "spot": spot,
            "market_cap": mcap,
            "fdv": fdv,
            "circulating_supply": sky_supply,
            "max_supply": sky_supply,
        },
        "model": {
            "type": "3Y GP/NP Monte Carlo",
            "discount_rate": DISCOUNT_RATE,
            "multiple": NP_MULTIPLE,
            "paths": PATHS,
            "note": (
                "GP = gross income - savings-rate cost - stUSDS expense. "
                "NP = GP - OPEX. USDS growth path: money-market TVL returns × 0.65 dampener, "
                "capped ±8%/+10% monthly. DAI supply flat. Treasury = cumulative positive NP. "
                "Protocol financials locked 2026-05-08."
            ),
        },
        "current_gp": {
            "gross_income": GROSS_INCOME,
            "savings_expense": SAVINGS_EXPENSE,
            "stusds_expense": STUSDS_EXPENSE,
            "current_gp": current_gp,
            "base_opex": base_opex,
            "current_np_base_opex": current_np_base,
            "usds_supply": USDS_SUPPLY,
            "dai_supply": DAI_SUPPLY,
            "gross_income_yield_pct": GROSS_INCOME_YIELD * 100,
        },
        "scenarios": scenarios,
        "caveats": [
            "Protocol financials (gross income, savings rate, USDS/DAI supply) locked at 2026-05-08; re-run sky_data_collection to refresh.",
            "USDS growth is modeled on broad money-market TVL returns dampened by 0.65 — Sky may diverge from sector.",
            "No buybacks or SKY supply reduction modeled; treasury accumulates cash only.",
            "Savings rate (3.65%) and USDS savings penetration (81.2%) are point-in-time inputs.",
        ],
        "data_freshness": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "sky_result.json"), "w") as f:
        json.dump(result, f, indent=2)

    return result
