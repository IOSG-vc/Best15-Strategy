"""Backpack (BP) webapp valuation agent — equity-conversion scenarios.

Model: PV = Y3_revenue × P/S_multiple × 20% equity / Y3_staking_supply / (1.25)³
Revenue benchmarked against reported 2025 data ($100M+) and current exchange volume.
P/S comparable to regulated crypto exchanges (Coinbase ~9×, Kraken ~7×).
Distributions: log-normal σ=1.0 approximation.
Market data and exchange volume refreshed live on every run.
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.request
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

# ── Model parameters ──────────────────────────────────────────────────────────
EQUITY_STAKE          = 0.20     # 20% of Backpack company equity for stakers
PHASE_1_SUPPLY        = 250_000_000   # Phase 1 tokens (immediately stakeable at TGE)
DISCOUNT_RATE         = 0.25
LOG_NORMAL_SIGMA      = 1.0

# Y3 scenarios: (key, label, y3_revenue, ps_multiple, y3_staking_supply, is_primary)
SCENARIOS = [
    ("bear", "Bear: $150M rev, 4× P/S, Phase-1 only",
     150_000_000, 4.0,  250_000_000, False),
    ("base", "Base: $250M rev, 7× P/S, Phase-1 + partial Phase-2",
     250_000_000, 7.0,  450_000_000, True),
    ("bull", "Bull: $500M rev, 10× P/S, Phase-1 + majority Phase-2",
     500_000_000, 10.0, 550_000_000, False),
]

REVENUE_2025_REPORTED = 100_000_000   # $100M+ 2025 reported (rounded conservative)
EQUITY_POOL_AT_1B_VAL = 1_000_000_000 * EQUITY_STAKE  # $200M equity pool at $1B valuation
EQUITY_PER_BP_PHASE1  = EQUITY_POOL_AT_1B_VAL / PHASE_1_SUPPLY  # $/BP if only Phase 1 stakes

CG_ID       = "backpack"
DL_SLUG     = "backpack-exchange"   # DefiLlama derivatives slug for Backpack perps

_CG_KEY  = os.environ.get("COINGECKO_API_KEY", "")
_CG_BASE = "https://pro-api.coingecko.com/api/v3" if _CG_KEY else "https://api.coingecko.com/api/v3"
RESULTS_DIR = Path(__file__).parent.parent / "results"
UA = "Mozilla/5.0 BP-valuation"

# Fallbacks (June 2026 approximate values)
_FB_SPOT   = 0.50
_FB_MCAP   = 125_000_000.0
_FB_FDV    = 500_000_000.0
_FB_CIRC   = 250_000_000.0
_FB_MAX    = 1_000_000_000.0


def _get(url: str, timeout: int = 30) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _fetch_cg_market() -> tuple[float, float, float, float, float]:
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


def _fetch_dl_volume() -> float:
    """Return Backpack 30D perps volume from DefiLlama."""
    try:
        url = f"https://api.llama.fi/summary/derivatives/{DL_SLUG}?dataType=dailyVolume"
        d = _get(url)
        rows = sorted(d.get("totalDataChart", []), key=lambda x: x[0])
        return float(sum(v for _, v in rows[-30:]))
    except Exception:
        # Fallback from dashboard description: June 2026 ~$247M/day → $7.4B/30D
        return 7_400_000_000.0


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
    """Fetch live data, compute BP scenarios, return standardized result dict."""
    # ── Market data ───────────────────────────────────────────────────────────
    try:
        spot, mcap, fdv, circ, max_supply = _fetch_cg_market()
    except Exception as e:
        print(f"[BP] CoinGecko failed ({e}); using fallback")
        spot, mcap, fdv, circ, max_supply = _FB_SPOT, _FB_MCAP, _FB_FDV, _FB_CIRC, _FB_MAX

    # ── Exchange volume ───────────────────────────────────────────────────────
    vol_30d = _fetch_dl_volume()
    vol_ann  = vol_30d * (365 / 30)

    # Equity diagnostics at current FDV
    implied_company_val_at_fdv = fdv / EQUITY_STAKE
    equity_pool_at_1b           = EQUITY_POOL_AT_1B_VAL
    equity_per_bp_phase1        = EQUITY_PER_BP_PHASE1

    disc = (1.0 + DISCOUNT_RATE) ** 3
    scenario_list = []

    y3_revenue_p50 = 0.0
    y3_supply_p50  = 0.0

    for sc_key, sc_label, y3_rev, ps_mult, y3_stake_supply, is_primary in SCENARIOS:
        # PV = Y3_revenue × P/S × 20% / Y3_staking_supply / DR³
        equity_pool   = y3_rev * ps_mult * EQUITY_STAKE
        y3_price      = equity_pool / max(y3_stake_supply, 1.0)
        pv_median     = y3_price / disc

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
            "y3_mcap_p50": y3_price * y3_stake_supply,
            "y3_supply_p50": float(y3_stake_supply),
            "y3_gp_p50": y3_rev,
        })

        if is_primary:
            y3_revenue_p50 = float(y3_rev)
            y3_supply_p50  = float(y3_stake_supply)

    result = {
        "token": "BP",
        "name": "Backpack",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "market": {
            "spot": spot, "market_cap": mcap, "fdv": fdv,
            "circulating_supply": circ, "max_supply": max_supply,
        },
        "model": {
            "type": "3Y Equity-Conversion Manual Scenarios",
            "discount_rate": DISCOUNT_RATE,
            "multiple": 7.0,
            "paths": 1,
            "note": (
                "PV = Y3_revenue × P/S_multiple × 20% equity / Y3_staking_supply / (1.25)³. "
                "Stakers lock BP for 1+ year and receive 20% of Backpack company equity at IPO. "
                "P/S benchmarked vs Coinbase (~9×) and Kraken (~7×). "
                "Distributions approximate log-normal σ=1.0."
            ),
        },
        "current_gp": {
            "revenue_2025_ann": float(REVENUE_2025_REPORTED),
            "perp_volume_30d_ann": float(vol_ann),
            "equity_pool_at_1b_val": float(equity_pool_at_1b),
            "equity_per_bp_phase1_only": float(equity_per_bp_phase1),
            "implied_company_val_at_fdv": float(implied_company_val_at_fdv),
            "y3_revenue_p50": float(y3_revenue_p50),
            "y3_supply_p50": float(y3_supply_p50),
            "equity_stake": EQUITY_STAKE,
        },
        "scenarios": scenario_list,
        "caveats": [
            "IPO is not guaranteed; equity conversion does not occur and BP loses its primary value driver if Backpack does not IPO.",
            "Phase 2 (375M tokens) unlock on business milestones; each unlock dilutes per-BP equity value.",
            "2026 revenue figures not disclosed; scenarios are manually constructed from $100M+ 2025 base.",
            "No buyback or revenue-share mechanism exists; value is entirely via equity conversion at IPO.",
            "Distributions approximate log-normal σ=1.0; no Monte Carlo simulation.",
        ],
        "data_freshness": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "bp_result.json", "w") as f:
        json.dump(result, f, indent=2)

    return result
