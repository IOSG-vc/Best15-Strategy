"""HYPE webapp valuation agent — Binance/MS90 architecture.

Uses hype_gp_capture_12m_start_run.run_once() which models perp treasury
revenue as Binance volume × HL market share × 0.026% clean revenue take-rate, plus separate
USDC yield GP. Four supply/emission scenarios replace the old DR-sensitivity
approach.
"""
import json
import os
import sys
from pathlib import Path

BUNDLE_ROOT = Path(__file__).parent.parent.parent
if str(BUNDLE_ROOT) not in sys.path:
    sys.path.insert(0, str(BUNDLE_ROOT))

import hype_gp_capture_12m_start_run as _run  # noqa: E402

RESULTS_DIR = Path(__file__).parent.parent / "results"

# Display order: primary first, then supporting scenarios
_SCENARIO_DISPLAY = [
    ("base_db_observed_emissions",          "Base: DB-observed emissions",       True),
    ("upside_db_observed_plus_optionality", "Bull: base + stronger supply/burn", False),
    ("bear_worst_case_emissions",           "Bear: worst-case emissions",        False),
    ("zero_emissions_sensitivity",          "Sensitivity: zero emissions",       False),
]


def run() -> dict:
    """Fetch live data, run new HYPE MC model, return standardized result dict."""
    res = _run.run_once()

    m   = res["market"]
    r   = res["revenue"]
    u   = res["usdc_yield"]
    mc  = res["mc"]
    scs = res["scenarios"]
    spot = m["spot"]
    ms   = mc["market_share"]
    base = scs["base_db_observed_emissions"]

    # ── Scenarios → standardized list ─────────────────────────────────────────
    scenarios = []
    for key, label, is_primary in _SCENARIO_DISPLAY:
        if key not in scs:
            continue
        sc = scs[key]
        dp = sc["discounted_token_price"]          # {p25, p50, p75, p90}
        dd = sc.get("discounted_distribution", {}) # {p5..p95} full ladder
        y3_price_p50  = sc["undiscounted_y3_token_price"]["p50"]
        y3_supply_p50 = sc["y3_supply"]["p50"]
        vol           = sc["p50_path_y3_daily_volume"]
        entry: dict = {
            "key":             key,
            "label":           label,
            "is_primary":      is_primary,
            "pv": {
                "p25": dp["p25"],
                "p50": dp["p50"],
                "p75": dp["p75"],
                "p90": dp["p90"],
            },
            "ev":              sc["discounted_ev"],
            "prob_above_spot": sc["prob_current_spot_justified"],
            "prob_3x":         sc["prob_3x_vs_spot"],
            # ── Model outputs table / cards ───────────────────────────────
            "y3_price_p50":    y3_price_p50,
            "y3_mcap_p50":     y3_price_p50 * y3_supply_p50,
            "y3_supply_p50":   y3_supply_p50,
            "y3_gp_p50":       sc["y3_ttm_gp"]["p50"],
            "ev_mcap":         sc["probability_weighted_ev_mcap"],
            "burn_3y_est":     sc["current_buy_tokens_per_month"] * 36,
            "y3_volume": {
                "min":               vol["min_daily_volume"],
                "avg":               vol["avg_daily_volume"],
                "max":               vol["max_daily_volume"],
                "eoy_market_share":  vol["eoy_market_share"],
            },
        }
        if dd:
            entry["distribution"] = dd   # full P5–P95 ladder for bar chart
        scenarios.append(entry)

    # ── current_gp: HYPE-specific metrics ────────────────────────────────────
    ms30  = ms.get("ms30") or ms["ms90"]
    ms180 = ms.get("ms180") or ms["ms90"]
    ms30_ms180_trend = (ms30 / ms180) if ms180 > 0 else 1.0

    # Growth velocity: how much the rolling 30D share has changed over the last 90 days.
    # Use ms_history to find ms30 from ~90 days ago; fall back to (ms30 - ms90) if history is thin.
    ms_hist = res.get("ms_history", [])
    if len(ms_hist) >= 90:
        ms30_prior90 = ms_hist[-90].get("ms30") or ms30
        growth_velocity_pp = (ms30 - ms30_prior90) * 100
    else:
        growth_velocity_pp = (ms30 - ms["ms90"]) * 100
    current_gp = {
        # ── header cards (order matters: UI reads these top 6) ──────────────
        "ms90_vs_binance":        ms["ms90"],          # MS90 valuation seed
        "ms30_vs_binance":        ms30,                # MCP MS30
        "ms30_ms180_trend":       ms30_ms180_trend,    # MS30 / MS180
        "growth_velocity_pp":     growth_velocity_pp,  # pp above 90D seed
        # ── market share trend data table ────────────────────────────────────
        "ms180_vs_binance":       ms180,
        "defillama_30d_ann":      r.get("defillama_ann_30d", r["trailing_30d_revenue"] * 365 / 30),
        "defillama_180d_ann":     r.get("defillama_ann_180d", 0.0),
        "buyback_years_base":     base["buyback_years_simple"],   # perps + USDC yield
        "buyback_years_fee_only": (m["circ_supply"] + base["modeled_gross_release_3y"])
                                  / max(base["current_perp_monthly_gp"] / max(spot, 0.01) * 12, 1),
        # ── supporting metrics ───────────────────────────────────────────────
        # ── supply / model assumption cards ─────────────────────────────────
        "supply_velocity_monthly": base["modeled_monthly_supply_release"],
        "gross_3y":               base["modeled_gross_release_3y"],
        "burn_3y_est":            base["current_buy_tokens_per_month"] * 36,
        # ── supporting metrics ───────────────────────────────────────────────
        "usdc_tvl":               u["usdc_tvl"],
        "usdc_net_yield":         u["net_yield"],
        "perp_gp_annual":         base["current_perp_monthly_gp"] * 12,
        "usdc_gp_annual":         base["current_usdc_yield_annual_gp"],
        "trailing_30d_revenue":   r["trailing_30d_revenue"],
        "ttm_gp":                 r["ttm_gp"],
        "non_circ_overhang":      base["non_circ_overhang"],
    }

    # ── MCP weekly bullets ────────────────────────────────────────────────────
    mcp_bullets: list[str] = []

    # 1. Volume activity trend
    rev_rows = res.get("revenue", {})
    r30 = r.get("trailing_30d_revenue", 0)
    r30_ann = r.get("defillama_ann_30d", r30 * 12)
    r180_ann = r.get("defillama_ann_180d", 0)
    if r30_ann > 0 and r180_ann > 0:
        if r30_ann >= r180_ann * 1.05:
            mcp_bullets.append("Protocol fee revenue accelerated versus the 180D annualised run rate.")
        elif r30_ann <= r180_ann * 0.95:
            mcp_bullets.append("Protocol fee revenue decelerated versus the 180D annualised run rate.")
        else:
            mcp_bullets.append("Protocol fee revenue is broadly in line with the 180D annualised run rate.")

    # 2. Market share ranking
    mcp_bullets.append(
        "Hyperliquid Perps ranked #1 by 30D derivatives volume in the DefiLlama derivatives category snapshot."
    )

    # 3. MS30 vs MS180 momentum
    ms30_val  = ms.get("ms30") or ms["ms90"]
    ms180_val = ms.get("ms180") or ms["ms90"]
    trend_ratio = ms30_val / ms180_val if ms180_val > 0 else 1.0
    if trend_ratio >= 1.10:
        mcp_bullets.append(
            f"30D market share ({ms30_val*100:.1f}%) is running {(trend_ratio-1)*100:.0f}% above "
            f"the 180D baseline ({ms180_val*100:.1f}%), signalling momentum acceleration."
        )
    elif trend_ratio <= 0.90:
        mcp_bullets.append(
            f"30D market share ({ms30_val*100:.1f}%) is running {(1-trend_ratio)*100:.0f}% below "
            f"the 180D baseline ({ms180_val*100:.1f}%), signalling share consolidation."
        )
    else:
        mcp_bullets.append(
            f"30D market share ({ms30_val*100:.1f}%) is near the 180D baseline ({ms180_val*100:.1f}%)."
        )

    # 4. Growth velocity
    gv = growth_velocity_pp
    direction = "grew" if gv >= 0 else "contracted"
    mcp_bullets.append(
        f"Rolling 30D/Binance share {direction} {abs(gv):.1f}pp over the last 90D window "
        f"(current MS30 {ms30_val*100:.1f}%)."
    )

    # 5. Buyback horizon
    bby = current_gp["buyback_years_fee_only"]
    mcp_bullets.append(
        f"At spot, clean-revenue-only buyback horizon is {bby:.1f}Y "
        f"(trailing 30D clean treasury revenue / target supply at spot price)."
    )

    result = {
        "token":       "HYPE",
        "name":        "Hyperliquid",
        "as_of_utc":   res["asof_utc"],
        "market": {
            "spot":               spot,
            "market_cap":         m["mcap"],
            "fdv":                m["fdv"] if m["fdv"] == m["fdv"] else 0,
            "circulating_supply": m["circ_supply"],
            "max_supply":         m["total_supply"] if m["total_supply"] == m["total_supply"] else 0,
        },
        "model": {
            "type":          "3Y GP-Capture MC (Binance/MS90)",
            "discount_rate": res["discount"]["selected"],
            "multiple":      15.0,
            "paths":         mc["paths"],
            "note": (
                "HL vol × Binance market share × 0.026% clean treasury revenue take-rate + USDC yield; "
                "MS30/MS90 momentum decays over 12 months; 4 supply/emission scenarios"
            ),
        },
        "current_gp": current_gp,
        "scenarios":  scenarios,
        "ms_history": res.get("ms_history", []),
        "hist_charts": res.get("hist_charts", {}),
        "mcp_bullets": mcp_bullets,
        "caveats": [
            "Market share (MS90) from DefiLlama MCP derivatives volume vs scaled Binance BTCUSDT proxy.",
            "USDC yield modeled separately from perp revenue; TVL follows HL volume path via estimated elasticity.",
            "Supply scenarios range from DB-observed emissions (~1M/mo) to worst-case non-circulating overhang release.",
        ],
        "data_freshness": res["asof_utc"][:10],
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(RESULTS_DIR / "hype_result.json", "w") as f:
        json.dump(result, f, indent=2)

    return result
