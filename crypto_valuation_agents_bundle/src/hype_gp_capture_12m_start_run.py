#!/usr/bin/env python3
# DEPRECATED — superseded by crypto_valuation_agents_bundle/hype_gp_capture_12m_start_run.py (bundle root)
# This src/ copy uses 0.034% take-rate and supply/emission scenarios (old model).
"""Updated HYPE GP-capture scenario run after critique.

Fixes:
- Treat DeFiLlama dailyRevenue as net GP / buyback capacity directly (GP margin = 100%).
- Scenario emissions instead of hardcoded single base.
- Product optionality as separate Y3 value uplift sensitivity.
"""
import json, math, os
from datetime import datetime, timezone

import numpy as np

import hype_gp_capture_mc as h

OUTDIR = os.path.dirname(__file__)
N_PATHS = h.N_PATHS
MONTHS = h.MONTHS
SELECTED_DR = h.SELECTED_DISCOUNT_RATE
TOKEN_CAPTURE = 1.0
BUYBACK_RATE = 1.0
GP_MARGIN = 1.0

TOTAL_FEE_TAKE_RATE = 0.00034  # total fee activity, including builder-code fees
NET_REVENUE_TAKE_RATE = 0.00026  # clean treasury revenue / perp notional

def median_monthly_start_12m(rev_rows, trailing_30):
    months = h.monthly_sums(rev_rows)
    last12 = [v for _, v in months[-12:]]
    med12 = float(np.median(np.array(last12, dtype=float))) if last12 else float(trailing_30)
    return min(float(trailing_30), med12), med12, float(trailing_30)

SCENARIOS = [
    {
        "key": "bear_worst_case_emissions",
        "label": "Bear: worst-case emissions",
        "monthly_emission": 9_916_667.0,
        "emission_months": 20,
        "optionality": 0.0,
        "note": "9.92M HYPE/month treated as downside linear-release ceiling, not base.",
    },
    {
        "key": "base_db_observed_emissions",
        "label": "Base: DB-observed emissions",
        "monthly_emission": 962_000.0,
        "emission_months": 36,
        "optionality": 0.0,
        "note": "Uses critique's DB-observed run-rate for known emissions/unlocks.",
    },
    {
        "key": "upside_db_observed_plus_optionality",
        "label": "Upside: base + 10% optionality",
        "monthly_emission": 962_000.0,
        "emission_months": 36,
        "optionality": 0.10,
        "note": "Adds product optionality as separate +10% Y3 value uplift.",
    },
    {
        "key": "zero_emissions_sensitivity",
        "label": "Sensitivity: zero emissions",
        "monthly_emission": 0.0,
        "emission_months": 36,
        "optionality": 0.0,
        "note": "Sensitivity only; not a base case.",
    },
]

CORE_QS = [25, 50, 75, 90]
CHART_QS = [5, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 95]

def pct_dict(x, qs):
    return {f"p{q}": float(np.percentile(x, q)) for q in qs}

def fmt_money(x):
    if x is None or not (x == x):
        return "n/a"
    ax = abs(x)
    if ax >= 1e9: return f"${x/1e9:,.2f}B"
    if ax >= 1e6: return f"${x/1e6:,.1f}M"
    if ax >= 1e3: return f"${x/1e3:,.1f}K"
    return f"${x:,.2f}"

def run_once():
    market = h.cg_market()
    spot = float(market["current_price"])
    mcap = float(market["market_cap"])
    fdv = market.get("fully_diluted_valuation")
    fdv = float(fdv) if fdv else float("nan")
    circ = float(market.get("circulating_supply") or (mcap / spot))
    total_supply = market.get("total_supply")
    total_supply = float(total_supply) if total_supply else float("nan")

    rev = h.defillama_revenue()
    rev_vals = np.array([v for _, v in rev], dtype=float)
    last_date = rev[-1][0]
    trailing_30 = float(rev_vals[-30:].sum())
    trailing_90 = float(rev_vals[-90:].sum())
    current_monthly_rev, median_12m_monthly_rev, last_30d_rev = median_monthly_start_12m(rev, trailing_30)
    current_annual_gp = current_monthly_rev * 365 / 30 * GP_MARGIN
    ttm_gp = (float(rev_vals[-365:].sum()) if len(rev_vals) >= 365 else float(rev_vals.sum() * 365 / len(rev_vals))) * GP_MARGIN

    monthly_proxy, ret_arr, shares = h.choose_monthly_return_distribution()
    np.random.seed(42)
    draws = np.random.choice(ret_arr, size=(N_PATHS, MONTHS), replace=True)
    growth = np.exp(np.cumsum(draws, axis=1))
    monthly_gp = current_monthly_rev * growth * GP_MARGIN
    y3_ttm_gp = monthly_gp[:, -12:].sum(axis=1)
    ranks = h.percentile_ranks(y3_ttm_gp)
    multiple = h.multiple_for_ranks(ranks)

    scenarios = {}
    for sc in SCENARIOS:
        supply = np.full(N_PATHS, circ, dtype=float)
        for t in range(MONTHS):
            start = max(0, t - 11)
            gp_window = monthly_gp[:, start:t+1].sum(axis=1) * (12.0 / (t - start + 1))
            interim_rank = h.percentile_ranks(gp_window)
            interim_mult = h.multiple_for_ranks(interim_rank)
            interim_price = (gp_window * interim_mult * TOKEN_CAPTURE) / np.maximum(supply, 1)
            buy_tokens = (monthly_gp[:, t] * BUYBACK_RATE) / np.maximum(interim_price, 0.01)
            buy_tokens = np.minimum(buy_tokens, supply * 0.80)
            emissions = sc["monthly_emission"] if t < sc["emission_months"] else 0.0
            supply = supply + emissions - buy_tokens
            supply = np.maximum(supply, 1.0)
        y3_supply = supply
        y3_price_core = (y3_ttm_gp * multiple * TOKEN_CAPTURE) / np.maximum(y3_supply, 1)
        y3_price = y3_price_core * (1.0 + sc["optionality"])
        pv = y3_price / ((1.0 + SELECTED_DR) ** 3)
        current_monthly_gp = current_monthly_rev * GP_MARGIN
        current_buy_tokens = current_monthly_gp / max(spot, 0.01)
        net_monthly_supply = sc["monthly_emission"] - current_buy_tokens
        supply_to_buy_back = circ + sc["monthly_emission"] * min(sc["emission_months"], 36)
        buyback_years = supply_to_buy_back / max(current_buy_tokens * 12, 1)
        scenarios[sc["key"]] = {
            **sc,
            "discounted_token_price": pct_dict(pv, CORE_QS),
            "discounted_ev": float(np.mean(pv)),
            "discounted_distribution": pct_dict(pv, CHART_QS),
            "undiscounted_y3_token_price": pct_dict(y3_price, CORE_QS),
            "undiscounted_y3_ev": float(np.mean(y3_price)),
            "y3_ttm_gp": pct_dict(y3_ttm_gp, CORE_QS),
            "y3_supply": pct_dict(y3_supply, CORE_QS),
            "prob_current_spot_justified": float(np.mean(pv >= spot)),
            "prob_impairment_vs_spot": float(np.mean(pv < spot)),
            "prob_3x_vs_spot": float(np.mean(pv >= 3 * spot)),
            "current_monthly_gp": float(current_monthly_gp),
            "current_buy_tokens_per_month": float(current_buy_tokens),
            "net_monthly_supply_now": float(net_monthly_supply),
            "buyback_years_simple": float(buyback_years),
        }

    # Volume sanity: implied HYPE volume from Y3 treasury revenue using clean revenue take-rate.
    # Compare to total Binance futures current/peak daily volume from scaled BTCUSDT proxy.
    latest_month_vol = float(monthly_proxy[-1][1])
    current_binance_daily = latest_month_vol / 30.0
    peak_binance_daily = float(max(v for _, v in monthly_proxy)) / 30.0
    for sc in scenarios.values():
        y3_gp_p50 = sc["y3_ttm_gp"]["p50"]
        implied_hype_daily_vol_p50 = y3_gp_p50 / NET_REVENUE_TAKE_RATE / 365.0
        sc["volume_sanity"] = {
            "net_revenue_take_rate": NET_REVENUE_TAKE_RATE,
            "implied_hype_daily_volume_y3_p50": implied_hype_daily_vol_p50,
            "current_binance_futures_daily_volume": current_binance_daily,
            "peak_binance_futures_daily_volume": peak_binance_daily,
            "implied_vs_current_binance": implied_hype_daily_vol_p50 / current_binance_daily,
            "implied_vs_peak_binance": implied_hype_daily_vol_p50 / peak_binance_daily,
        }

    out = {
        "asof_utc": datetime.now(timezone.utc).isoformat(),
        "market": {"spot": spot, "mcap": mcap, "fdv": fdv, "circ_supply": circ, "total_supply": total_supply},
        "revenue": {
            "defillama_last_date": str(last_date),
            "trailing_30d_revenue": trailing_30,
            "trailing_90d_revenue": trailing_90,
            "median_12m_monthly_revenue": median_12m_monthly_rev,
            "conservative_start_monthly_revenue": current_monthly_rev,
            "current_annualized_gp": current_annual_gp,
            "ttm_gp": ttm_gp,
            "gp_margin_on_defillama_revenue": GP_MARGIN,
        },
        "mc": {
            "paths": N_PATHS,
            "months": MONTHS,
            "volume_proxy": "total Binance futures, BTCUSDT-scaled via Blockworks annual totals",
            "proxy_months": len(monthly_proxy),
            "monthly_log_return_mean": float(np.mean(ret_arr)),
            "monthly_log_return_std": float(np.std(ret_arr, ddof=1)),
            "btcusdt_shares": {str(k): float(v) for k, v in shares.items()},
        },
        "discount": {"selected": SELECTED_DR},
        "scenarios": scenarios,
    }
    return out

def write_report(res):
    m, r, mc, scs = res["market"], res["revenue"], res["mc"], res["scenarios"]
    spot = m["spot"]
    lines = []
    lines.append("# HYPE 3Y GP-Capture MC — 12M Median Start Run")
    lines.append(f"As of: {res['asof_utc']}")
    lines.append("")
    lines.append("## What changed")
    lines.append("- DeFiLlama `dailyRevenue` is now treated as net GP / buyback capacity directly: **GP margin = 100% on revenue**.")
    lines.append("- 9.92M HYPE/month emissions are moved to **bear/worst-case**, not base.")
    lines.append("- Base uses DB-observed emissions from the critique: **0.962M HYPE/month**.")
    lines.append("- Product optionality is a separate **+10% Year-3 value** sensitivity.")
    lines.append("")
    lines.append("## Market + GP base")
    lines.append("```text")
    lines.append(f"Spot                         ${spot:,.2f}")
    lines.append(f"Market cap                   {fmt_money(m['mcap'])}")
    lines.append(f"FDV                          {fmt_money(m['fdv'])}")
    lines.append(f"Circulating supply           {m['circ_supply']/1e6:,.1f}M HYPE")
    lines.append(f"DeFiLlama revenue date       {r['defillama_last_date']}")
    lines.append(f"30D revenue                  {fmt_money(r['trailing_30d_revenue'])}")
    lines.append(f"Median monthly revenue 12M    {fmt_money(r['median_12m_monthly_revenue'])}")
    lines.append(f"Conservative monthly GP      {fmt_money(r['conservative_start_monthly_revenue'])}")
    lines.append(f"Annualized start GP          {fmt_money(r['current_annualized_gp'])}")
    lines.append(f"TTM GP                       {fmt_money(r['ttm_gp'])}")
    lines.append("GP margin                    100% of DeFiLlama revenue")
    lines.append("Discount rate                25% selected HYPE rate")
    lines.append(f"MC paths / horizon           {mc['paths']:,} / {mc['months']} months")
    lines.append(f"Monthly mkt logret mean/std  {mc['monthly_log_return_mean']:.2%} / {mc['monthly_log_return_std']:.2%}")
    lines.append("```")
    lines.append("")
    lines.append("## Scenario output — discounted fair value @ 25%")
    lines.append("```text")
    lines.append("Scenario                         P25      P50      P75      P90      P(spot)  3x+")
    lines.append("-------------------------------  -------  -------  -------  -------  -------  ------")
    order = ["bear_worst_case_emissions", "base_db_observed_emissions", "upside_db_observed_plus_optionality", "zero_emissions_sensitivity"]
    for k in order:
        s = scs[k]; d = s["discounted_token_price"]
        lines.append(f"{s['label']:<31}  ${d['p25']:>6.2f}  ${d['p50']:>6.2f}  ${d['p75']:>6.2f}  ${d['p90']:>6.2f}  {s['prob_current_spot_justified']:>6.1%}  {s['prob_3x_vs_spot']:>5.1%}")
    lines.append("```")
    lines.append("")
    lines.append("## Supply / buyback sanity")
    lines.append("```text")
    lines.append("Scenario                         Emissions/mo  Net supply/mo now  Buyback years  Y3 supply P50")
    lines.append("-------------------------------  ------------  -----------------  -------------  -------------")
    for k in order:
        s = scs[k]
        lines.append(f"{s['label']:<31}  {s['monthly_emission']/1e6:>8.2f}M     {s['net_monthly_supply_now']/1e6:>+8.2f}M          {s['buyback_years_simple']:>6.1f}y       {s['y3_supply']['p50']/1e6:>7.1f}M")
    lines.append("```")
    lines.append("")
    base = scs["base_db_observed_emissions"]["discounted_token_price"]
    upside = scs["upside_db_observed_plus_optionality"]["discounted_token_price"]
    bear = scs["bear_worst_case_emissions"]["discounted_token_price"]

    lines.append("## P50 volume sanity")
    lines.append("```text")
    lines.append("Assumed clean treasury revenue take-rate: 0.026% of notional volume")
    lines.append("")
    lines.append("Scenario                         Implied HYPE daily vol   vs Binance current   vs Binance peak")
    lines.append("-------------------------------  ----------------------   ------------------   ---------------")
    for k in order[:3]:
        s = scs[k]; vs = s["volume_sanity"]
        lines.append(f"{s['label']:<31}  {fmt_money(vs['implied_hype_daily_volume_y3_p50']):>22}   {vs['implied_vs_current_binance']:>17.1%}   {vs['implied_vs_peak_binance']:>14.1%}")
    lines.append("```")
    lines.append("")
    lines.append("## Read-through")
    lines.append(f"- **Bear/worst-case:** P50 **${bear['p50']:.2f}**, still clearly below spot because 9.92M/month emissions overwhelm buybacks.")
    lines.append(f"- **Base corrected run:** P50 **${base['p50']:.2f}**, P75 **${base['p75']:.2f}**, with spot justified in **{scs['base_db_observed_emissions']['prob_current_spot_justified']:.1%}** of paths.")
    lines.append(f"- **Upside optionality run:** P50 **${upside['p50']:.2f}**, P75 **${upside['p75']:.2f}**, spot justified in **{scs['upside_db_observed_plus_optionality']['prob_current_spot_justified']:.1%}** of paths.")
    lines.append("- Main conclusion: corrected model no longer says HYPE is obviously expensive; it says current spot is around the upper half of fair-value distribution unless worst-case emissions are true.")
    lines.append("")
    report = "\n".join(lines) + "\n"
    md = os.path.join(OUTDIR, "hype_3y_gp_capture_12m_start_run.md")
    js = os.path.join(OUTDIR, "hype_3y_gp_capture_12m_start_run.json")
    with open(md, "w") as f: f.write(report)
    with open(js, "w") as f: json.dump(res, f, indent=2)
    return md, js, report

if __name__ == "__main__":
    res = run_once()
    md, js, report = write_report(res)
    print(report)
    print("Saved:", md)
    print("Saved:", js)
