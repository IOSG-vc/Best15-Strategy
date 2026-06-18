"""CARDS valuation agent.

Collector Crypt is modeled as a GMV-to-GP bridge rather than a generic
revenue multiple. Until enough history exists for a 30D/180D velocity signal,
the model uses capped 7D/30D GMV velocity and tests linear decay to zero over
6, 12, and 24 months.
"""

import json
import os
from datetime import datetime, timezone

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")

TOKEN = "CARDS"
NAME = "Collector Crypt"
SPOT = 0.2338976713
FDV = 467_795_342.6
FLOAT_VALUE = 295_879_688.0
SUPPLY_Y3 = 1_264_934_993.0
FULL_FDV_SUPPLY = 2_000_000_000.0
DISCOUNT_RATE = 0.30
MULTIPLE = 15.0
GMV_30D = 109_016_833.0
GMV_30D_ANNUALIZED = 1_326_371_468.1666665
NET_REVENUE_30D = 13_463_563.0
NET_REVENUE_30D_ANNUALIZED = 163_806_683.16666666
NET_SPREAD = 0.1235
GP_CONVERSION = 0.60
GMV_VELOCITY_MONTHLY = 0.20
LATEST_7D_AVG_GMV = 6_403_403.285714285
PRIOR_30D_AVG_GMV = 2_503_460.3333333335


def _discount_factor():
    return (1.0 + DISCOUNT_RATE) ** 3


def _velocity_factor(decay_months):
    factor = 1.0
    for month in range(decay_months):
        factor *= 1.0 + GMV_VELOCITY_MONTHLY * (1.0 - month / decay_months)
    return factor


def _scenario(key, label, weight, decay_months, primary=False):
    factor = _velocity_factor(decay_months)
    y3_gmv = GMV_30D_ANNUALIZED * factor
    y3_net_revenue = y3_gmv * NET_SPREAD
    y3_gp = y3_net_revenue * GP_CONVERSION
    terminal_value = y3_gp * MULTIPLE
    pv_per_token = terminal_value / SUPPLY_Y3 / _discount_factor()
    return {
        "key": key,
        "label": label,
        "weight": weight,
        "velocity_decay_months": decay_months,
        "y3_gmv": y3_gmv,
        "net_spread": NET_SPREAD,
        "gp_conversion": GP_CONVERSION,
        "y3_gp": y3_gp,
        "multiple": MULTIPLE,
        "terminal_value": terminal_value,
        "pv": {
            "p25": pv_per_token,
            "p50": pv_per_token,
            "p75": pv_per_token,
            "p90": pv_per_token,
        },
        "ev": pv_per_token,
        "prob_above_spot": 1.0 if pv_per_token > SPOT else 0.0,
        "prob_y2_undiscounted_up_30": None,
        "prob_y2_undiscounted_down_30": None,
        "is_primary": primary,
    }


def build_result():
    scenarios = [
        _scenario("decay_6m", "A: 6M velocity decay", 0.40, 6),
        _scenario("decay_12m", "B: 12M velocity decay", 0.40, 12, primary=True),
        _scenario("decay_24m", "C: 24M velocity decay", 0.20, 24),
    ]
    weighted_pv = sum(sc["weight"] * sc["pv"]["p50"] for sc in scenarios)
    weighted_gmv = sum(sc["weight"] * sc["y3_gmv"] for sc in scenarios)
    weighted_gp = sum(sc["weight"] * sc["y3_gp"] for sc in scenarios)
    primary = scenarios[1]
    full_fdv_pv = primary["terminal_value"] / FULL_FDV_SUPPLY / _discount_factor()

    return {
        "token": TOKEN,
        "name": NAME,
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "market": {
            "spot": SPOT,
            "market_cap": FLOAT_VALUE,
            "fdv": FDV,
            "circulating_supply": SUPPLY_Y3,
            "max_supply": FULL_FDV_SUPPLY,
        },
        "model": {
            "type": "3Y GMV-to-GP velocity decay model",
            "discount_rate": DISCOUNT_RATE,
            "multiple": MULTIPLE,
            "paths": 3,
            "supply_y3": SUPPLY_Y3,
            "note": (
                "CARDS uses 30D annualized Gacha GMV, fixed 12.35% net spread, "
                "60% GP conversion, 15x GP, and capped 7D/30D GMV velocity "
                "decaying linearly to zero over 6/12/24 months with 40/40/20 weights."
            ),
        },
        "current_gp": {
            "gacha_gmv_30d": GMV_30D,
            "gacha_gmv_30d_ann": GMV_30D_ANNUALIZED,
            "net_revenue_30d": NET_REVENUE_30D,
            "net_revenue_30d_ann": NET_REVENUE_30D_ANNUALIZED,
            "net_spread": NET_SPREAD,
            "gp_conversion": GP_CONVERSION,
            "current_gp_proxy": NET_REVENUE_30D_ANNUALIZED * GP_CONVERSION,
            "latest_7d_avg_gmv": LATEST_7D_AVG_GMV,
            "prior_30d_avg_gmv": PRIOR_30D_AVG_GMV,
            "gmv_velocity_monthly": GMV_VELOCITY_MONTHLY,
            "velocity_source": "Capped 7D/30D GMV velocity; 30D/180D unavailable until enough history exists.",
            "y3_gp_p50": primary["y3_gp"],
            "y3_gmv_p50": primary["y3_gmv"],
            "weighted_pv": weighted_pv,
            "weighted_y3_gmv": weighted_gmv,
            "weighted_y3_gp": weighted_gp,
            "base_full_fdv_pv": full_fdv_pv,
            "fdv_to_net_revenue_30d_ann": FDV / NET_REVENUE_30D_ANNUALIZED,
            "float_value_to_gp_proxy": FLOAT_VALUE / (NET_REVENUE_30D_ANNUALIZED * GP_CONVERSION),
        },
        "scenarios": scenarios
        + [
            {
                "key": "weighted",
                "label": "Weighted 40/40/20",
                "weight": 1.0,
                "y3_gmv": weighted_gmv,
                "net_spread": NET_SPREAD,
                "gp_conversion": GP_CONVERSION,
                "y3_gp": weighted_gp,
                "multiple": MULTIPLE,
                "pv": {"p25": weighted_pv, "p50": weighted_pv, "p75": weighted_pv, "p90": weighted_pv},
                "ev": weighted_pv,
                "prob_above_spot": 1.0 if weighted_pv > SPOT else 0.0,
                "prob_y2_undiscounted_up_30": None,
                "prob_y2_undiscounted_down_30": None,
                "is_primary": False,
            }
        ],
        "caveats": [
            "DefiLlama revenue is net of pack buyback spends, but not audited company GP.",
            "True inventory turnover velocity is unavailable without card-base or cohort reporting.",
            "Foundation unlock bucket remains excluded from the float-friendly primary denominator.",
        ],
    }


def run():
    result = build_result()
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "cards_result.json"), "w") as f:
        json.dump(result, f, indent=2)
    return result


if __name__ == "__main__":
    run()
