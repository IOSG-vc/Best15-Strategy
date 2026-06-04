"""HYPE webapp valuation agent.

Wraps hype_gp_capture_mc.run_model() and returns the standardized dict
expected by update_valuations.py / ValuationDashboard.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# hype_gp_capture_mc lives at the bundle root, one level above webapp/
BUNDLE_ROOT = Path(__file__).parent.parent.parent
if str(BUNDLE_ROOT) not in sys.path:
    sys.path.insert(0, str(BUNDLE_ROOT))

import hype_gp_capture_mc as _hype  # noqa: E402

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")


def run() -> dict:
    """Fetch live data, run HYPE MC model, return standardized result dict."""
    res = _hype.run_model()

    m = res["market"]
    r = res["revenue"]
    d = res["discount"]
    o = res["outputs"]
    pd_disc = o["price_distribution"]["discounted"]
    pd_undisc = o["price_distribution"]["undiscounted_y3"]

    spot = m["spot"]

    # Build scenarios -------------------------------------------------------
    # Sensitivity dict (pv_sensitivity) only has p25/p50/p75 and no probability
    # vs spot, so we use it to build ±5% DR scenarios with p75 as p90 proxy.
    pv_sens = res.get("pv_sensitivity", {})

    def _sens_scenario(rate_str, label, is_primary):
        s = pv_sens[rate_str]
        return {
            "key": f"pv_{rate_str.replace('%','pct').replace('.','_')}",
            "label": label,
            "is_primary": is_primary,
            "pv": {"p25": s["p25"], "p50": s["p50"], "p75": s["p75"], "p90": s["p75"]},
            "ev": s["p50"],
            "prob_above_spot": 0.0,  # not computable from quantiles alone
        }

    # Primary uses the full distribution (has ev_mean, p90, and probabilities).
    primary_rate_str = f"{d['selected']:.1%}"
    scenarios = [
        {
            "key": "pv_25pct",
            "label": "25% discount rate (selected)",
            "is_primary": True,
            "pv": {
                "p25": o["discounted_token_price"]["p25"],
                "p50": o["discounted_token_price"]["p50"],
                "p75": o["discounted_token_price"]["p75"],
                "p90": pd_disc["p90"],
            },
            "ev": o["ev_mean"],
            "prob_above_spot": o["prob_current_spot_justified"],
            "prob_3x": o["prob_3x_vs_spot"],
        },
    ]

    # Add ±5% sensitivity scenarios (skip the selected rate)
    for rate_str, pv_vals in sorted(pv_sens.items(), key=lambda x: float(x[0].rstrip("%"))):
        rate_float = float(rate_str.rstrip("%")) / 100
        if abs(rate_float - d["selected"]) < 0.001:
            continue
        tag = "bull" if rate_float < d["selected"] else "bear"
        scenarios.append(_sens_scenario(rate_str, f"{rate_str} discount rate ({tag})", False))

    scenarios.append({
        "key": "undiscounted_y3",
        "label": "Undiscounted Y3 price",
        "is_primary": False,
        "pv": {
            "p25": o["y3_token_price"]["p25"],
            "p50": o["y3_token_price"]["p50"],
            "p75": o["y3_token_price"]["p75"],
            "p90": pd_undisc["p90"],
        },
        "ev": o["undiscounted_ev_mean"],
        "prob_above_spot": o["undiscounted_prob_current_spot_justified_y3"],
        "prob_3x": o["undiscounted_prob_3x_vs_spot"],
    })

    result = {
        "token": "HYPE",
        "name": "Hyperliquid",
        "as_of_utc": res["asof_utc"],
        "market": {
            "spot": spot,
            "market_cap": m["mcap"],
            "fdv": m["fdv"] if m["fdv"] == m["fdv"] else 0,
            "circulating_supply": m["circ_supply"],
            "max_supply": m["total_supply"] if m["total_supply"] == m["total_supply"] else 0,
        },
        "model": {
            "type": "3Y GP-Capture Monte Carlo",
            "discount_rate": d["selected"],
            "multiple": 15.0,
            "paths": res["mc"]["paths"],
            "note": (
                "Protocol revenue × 98.5% GP margin; buybacks reduce future supply "
                "offset by core emissions (~9.9M HYPE/month for 20 months); "
                "volume proxy: Binance futures monthly returns 2022+"
            ),
        },
        "current_gp": {
            "trailing_30d_revenue": r["trailing_30d_revenue"],
            "median_6m_monthly_revenue": r["median_6m_monthly_revenue"],
            "conservative_monthly_start": r["conservative_start_monthly_revenue"],
            "annualized_gp_30d": r["current_annualized_gp_30d"],
            "ttm_gp": r["ttm_gp"],
            "gp_margin": r["gp_margin"],
        },
        "scenarios": scenarios,
        "caveats": [
            "DeFiLlama revenue used as GP base; verify against protocol-native fee data.",
            "Supply model assumes buybacks proportional to GP and ~198M HYPE core emissions over 20 months.",
            "Volume proxy is total Binance futures (BTCUSDT-scaled via Blockworks annual totals). HYPE's own growth may diverge.",
        ],
        "data_freshness": res["asof_utc"][:10],
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "hype_result.json"), "w") as f:
        json.dump(result, f, indent=2)

    return result
