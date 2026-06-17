"""Lighter webapp valuation adapter.

The imported Lighter run is a saved HYPE-style MC artifact. This adapter makes it
canonical for the dashboard by attaching the shared valuation-template fields
that were added after the original run: velocity score, product-line Y3 split,
and two-year undiscounted +/-30% probabilities.
"""
import json
import math
import os
from pathlib import Path

import numpy as np

RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULT_PATH = RESULTS_DIR / "lighter_result.json"
DISCOUNT_RATE = 0.25


def _prob_from_distribution(distribution: dict, threshold: float, *, side: str) -> float:
    """Approximate probability from exported quantiles when path samples are absent."""
    if not distribution:
        return 0.0
    pts = []
    for key, value in distribution.items():
        if key.startswith("p"):
            try:
                pts.append((float(key[1:]) / 100.0, float(value)))
            except Exception:
                continue
    pts = sorted(pts)
    if not pts:
        return 0.0
    qs = np.array([p for p, _ in pts], dtype=float)
    vals = np.array([v for _, v in pts], dtype=float)
    cdf = float(np.interp(threshold, vals, qs, left=0.0, right=1.0))
    return cdf if side == "below" else 1.0 - cdf


def _velocity_ensemble(current_gp: dict) -> dict:
    ms30 = float(current_gp.get("ms30_vs_binance") or 0)
    ms180 = float(current_gp.get("ms180_vs_binance") or ms30 or 1e-12)
    velocity_30_180 = math.exp(math.log(max(ms30, 1e-12) / max(ms180, 1e-12)) / 6.0) - 1.0
    capped_30_180 = float(np.clip(velocity_30_180, -0.05, 0.12))
    return {
        "velocity_30_180": float(velocity_30_180),
        "velocity_7_30": None,
        "capped_30_180": capped_30_180,
        "capped_7_30": None,
        "ensemble": float(np.clip(capped_30_180, 0.0, 0.12)),
        "weights": {"thirty_over_180": 0.70, "seven_over_30": 0.30},
        "note": "7D/30D unavailable in imported Lighter artifact; score uses capped 30D/180D until live daily history is added.",
    }


def normalize(result: dict) -> dict:
    spot = float(result.get("market", {}).get("spot") or 0)
    current_gp = result.setdefault("current_gp", {})
    current_gp["market_share_velocity"] = _velocity_ensemble(current_gp)
    current_gp.setdefault("y3_daily_mean_volume_p50", (current_gp.get("y3_annual_volume_p50") or 0) / 365.0)

    base_y3 = float(current_gp.get("base_y3_revenue_p50") or current_gp.get("y3_revenue_p50") or 0)
    total_y3 = float(current_gp.get("y3_revenue_p50") or base_y3)
    yield_y3 = max(total_y3 - base_y3, 0.0)

    for sc in result.get("scenarios", []):
        label = sc.get("key", "")
        dist = sc.get("distribution") or sc.get("pv") or {}
        # Convert discounted PV distribution back to undiscounted Y3 price as
        # the nearest available proxy; original path-level M24 values were not
        # exported in the imported Lighter run.
        undiscounted_y3_dist = {
            k: float(v) * ((1.0 + DISCOUNT_RATE) ** 3)
            for k, v in dist.items()
            if isinstance(v, (int, float))
        }
        if spot:
            sc["prob_y2_undiscounted_up_30"] = _prob_from_distribution(
                undiscounted_y3_dist, 1.30 * spot, side="above"
            )
            sc["prob_y2_undiscounted_down_30"] = _prob_from_distribution(
                undiscounted_y3_dist, 0.70 * spot, side="below"
            )
        if label == "base_no_yield":
            sc["y3_perp_gp_p50"] = float(sc.get("y3_gp_p50") or base_y3)
            sc["y3_stable_yield_gp_p50"] = 0.0
        else:
            sc["y3_perp_gp_p50"] = base_y3
            sc["y3_stable_yield_gp_p50"] = yield_y3

    caveats = result.setdefault("caveats", [])
    caveat = (
        "Two-year +/-30% probabilities are approximated from exported PV quantiles because "
        "the imported Lighter artifact did not include path-level M24 samples."
    )
    if caveat not in caveats:
        caveats.append(caveat)
    return result


def run() -> dict:
    with open(RESULT_PATH) as f:
        result = json.load(f)
    result = normalize(result)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(RESULT_PATH, "w") as f:
        json.dump(result, f, indent=2)
    return result
