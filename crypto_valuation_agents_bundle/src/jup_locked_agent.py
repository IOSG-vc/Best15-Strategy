#!/usr/bin/env python3
"""JUP locked valuation agent.

Implements / refreshes JUP_LOCKED_MODEL.md with public DefiLlama + CoinGecko data.
The model is intentionally simple and transparent:
- Core entity GP = Jupiter Perps GP + Aggregator/Ultra GP + Jupiterz implied GP.
- Perps GP = 25% of Jupiter Perpetual Exchange gross fees (75% to JLP).
- Aggregator/Ultra GP = DefiLlama Jupiter Aggregator fees/revenue.
- Jupiterz GP = Jupiterz volume * aggregator rake. If live aggregator volume is unavailable,
  use the prior audited current rake anchor from the locked report lineage (~3.55bps).
- Lending / jupSOL / DCA / Ape / Prediction are tracked as live optional lines, but not separately MC-simulated unless they become material.
- Jupnet is a separate additional +10% premium.
- Scheduled unlock pressure is 0 until Jupiter announces a new distribution plan for the cold-storage/community reserve.
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

OUTDIR = os.path.dirname(__file__)
N_PATHS = int(os.environ.get("JUP_MC_PATHS", "100000"))
MONTHS = 36
DISCOUNT = 0.244
MULTIPLE = 15.0
# No public forward unlock/distribution schedule for the ~3.4B cold-storage/community reserve.
# Treat scheduled unlock pressure as 0 until Jupiter announces a plan. Do not assume
# the old 53.47M/mo distribution continues or restarts against treasury/reserve tokens.
SCHEDULED_UNLOCKS_PER_MONTH = 0.0
COLD_STORAGE_COMMUNITY_RESERVE = 3.405e9
BUYBACK_SHARE = 0.50
# From 2026-05-11 active run: aggregator rev 30D $1.88M / aggregator vol 30D $5.29B = 3.55bps.
# Public DefiLlama currently exposes Jupiterz volume but not Jupiter aggregator volume via free endpoint.
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
    # Combine spot by month: aggregator fees + Jupiterz implied GP.
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
        "rows": {"perps_gp_daily": perps_gp_daily, "agg_gp_daily": agg_gp_daily, "jupz_vol_daily": jupz_vol, "jupz_gp_daily": jupz_gp_daily, "dca_fees_daily": dca_fees},
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
            "ape_revenue": ape_revenue[-1][0] if ape_revenue else None,
            "prediction_revenue": prediction_revenue[-1][0] if prediction_revenue else None,
        },
    }


def sample_returns(months):
    # Exclude tiny-launch history and the current incomplete month. Early JUP product
    # months create absurd bootstrap tails that swamp the locked model. Use mature
    # completed months and cap single-month log shocks to keep the MC a valuation
    # model rather than a launch-base extrapolator.
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
    # Guard against bootstrap-tail explosions in a young product series. This is
    # a 3Y valuation dashboard, not an unconstrained launch-phase extrapolation.
    # Cap each mature product line at 8x the live monthly seed; breakout/Jupnet
    # remains represented by the +10%/+20% premium cases rather than infinite GP.
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
            "perps_return_months": int(len(perps_rets)),
            "spot_return_months": int(len(spot_rets)),
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


def write_report(out):
    m = out["market"]
    s = out["gpdata"]["seeds"]
    c = out["valuation"]["cases"]
    st = out["valuation"]["y3_state"]
    spot = m["current_price"]
    lines = []
    lines.append(f"**JUP locked valuation refresh — {out['as_of_utc'][:10]}**")
    lines.append("")
    lines.append("```text")
    lines.append("KEY ASSUMPTIONS / LIVE SEEDS")
    lines.append(f"Spot / MCap / FDV       ${spot:.4f} / {fmt_money(m['market_cap'])} / {fmt_money(m['fully_diluted_valuation'])}")
    lines.append(f"Circ / total supply     {m['circulating_supply']/1e9:.2f}B / {m['total_supply']/1e9:.2f}B JUP")
    lines.append(f"Discount / multiple     {DISCOUNT*100:.1f}% / {MULTIPLE:.0f}x Y3 TTM entity GP")
    lines.append(f"Scheduled unlocks        {SCHEDULED_UNLOCKS_PER_MONTH/1e6:.2f}M JUP/mo (0 until new reserve plan)")
    lines.append(f"Buybacks                50% entity GP at current spot")
    lines.append(f"Perps GP seed           {fmt_money(s['perps_seed_gp'])}/mo = min({fmt_money(s['perps_30d_gp'])}, {fmt_money(s['perps_12m_median_gp'])})")
    lines.append(f"Aggregator GP 30D       {fmt_money(s['aggregator_30d_gp'])}")
    lines.append(f"Jupiterz vol / GP 30D   {fmt_money(s['jupiterz_30d_volume'])} / {fmt_money(s['jupiterz_implied_30d_gp'])} @ {s['jupiterz_rake_bps']:.2f}bps")
    lines.append(f"Spot GP seed            {fmt_money(s['spot_seed_gp'])}/mo = min({fmt_money(s['spot_30d_gp'])}, {fmt_money(s['spot_12m_median_gp'])})")
    lines.append(f"Total GP seed           {fmt_money(s['total_seed_gp'])}/mo; 30D run-rate {fmt_money(s['total_30d_gp'])}/mo")
    lines.append(f"DCA fees optional       {fmt_money(s['dca_30d_fees_optional'])}/30D, not in core")
    lines.append(f"Lend revenue optional   {fmt_money(s['lend_30d_revenue_optional'])}/30D, not in core")
    lines.append(f"jupSOL revenue optional {fmt_money(s['jupsol_30d_revenue_optional'])}/30D, not in core")
    lines.append(f"Tracked optional total  {fmt_money(s['tracked_optional_30d_revenue'])}/30D")
    lines.append("```")
    lines.append("")
    lines.append("```text")
    lines.append("RESULTS — discounted PV / JUP")
    lines.append("Case              P25    P50    P75    EV     P50x  EVx   P>spot")
    for key, lab in [("core", "Core"), ("opt_10", "+10% opt"), ("opt_10_jupnet_10", "+opt+Jupnet")]:
        pv = c[key]["discounted_pv"]
        lines.append(f"{lab:<16} ${pv['p25']:.3f} ${pv['p50']:.3f} ${pv['p75']:.3f} ${c[key]['discounted_ev']:.3f}  {c[key]['p50_to_spot']:.2f}x {c[key]['ev_to_spot']:.2f}x {c[key]['prob_pv_gt_spot']*100:5.1f}%")
    lines.append("```")
    lines.append("")
    lines.append("```text")
    lines.append("P50 MODEL STATE / PRODUCT SPLIT")
    lines.append(f"Y3 TTM entity GP P50       {fmt_money(st['y3_ttm_gp']['p50'])}")
    lines.append(f"  Perps GP P50             {fmt_money(st['y3_perps_gp']['p50'])}")
    lines.append(f"  Spot/Agg+Jupiterz GP P50 {fmt_money(st['y3_spot_gp']['p50'])}")
    lines.append(f"Y3 effective supply P50    {st['y3_effective_supply']['p50']/1e9:.2f}B JUP")
    lines.append(f"P50 buyback accumulation   {st['buyback_accum_tokens']['p50']/1e6:.0f}M JUP")
    lines.append("```")
    lines.append("")
    lines.append("Read-through: supply assumption corrected. The prior 53.47M JUP/mo gross unlock path is removed because the scheduled unlocks are finished; the ~3.405B cold-storage/community reserve has no public distribution timeline. PV is now driven by current core GP seed (" + fmt_money(s['total_seed_gp']) + "/mo, ~" + fmt_money(s['total_seed_gp']*12) + "/yr), simulated buybacks, and current circulating/effective supply. Lend/jupSOL are tracked explicitly but remain small optional lines, not separate MC drivers yet.")
    return "\n".join(lines)


def main():
    market = cg_market()
    gpdata = gp_series_and_seeds()
    valuation = run_mc(market, gpdata)
    out = {
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "market": market,
        "methodology": {
            "discount_rate": DISCOUNT,
            "multiple": MULTIPLE,
            "scheduled_unlocks_per_month": SCHEDULED_UNLOCKS_PER_MONTH,
            "cold_storage_community_reserve": COLD_STORAGE_COMMUNITY_RESERVE,
            "supply_note": "Scheduled unlock pressure set to 0 until Jupiter announces a new distribution plan for cold-storage/community reserve tokens.",
            "buyback_share": BUYBACK_SHARE,
            "aggregator_rake_bps_fallback": AGG_RAKE_BPS_FALLBACK,
            "note": "Jupiterz GP uses fallback aggregator rake because free public DefiLlama endpoint exposes Jupiterz volume but not current aggregator/Ultra volume.",
        },
        "gpdata": gpdata,
        "valuation": valuation,
    }
    # Avoid dumping daily rows into json artifact size? Keep monthly + seeds, not raw rows.
    out_slim = dict(out)
    out_slim["gpdata"] = {"months": gpdata["months"], "seeds": gpdata["seeds"], "last_dates": gpdata["last_dates"]}
    json_path = os.path.join(OUTDIR, "jup_locked_result.json")
    md_path = os.path.join(OUTDIR, "jup_locked_report.md")
    with open(json_path, "w") as f:
        json.dump(out_slim, f, indent=2)
    report = write_report(out)
    with open(md_path, "w") as f:
        f.write(report + "\n")
    print(report)
    print(f"\nSaved: {json_path}")
    print(f"Saved: {md_path}")


if __name__ == "__main__":
    main()
