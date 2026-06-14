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
from datetime import datetime, date, timedelta, timezone

import numpy as np

_MS_AMPLIFIER_CAP = 1.5
_MS_DECAY_MONTHS = 12
_MS_MONTHS = 36
_JUP_PERPS_CAP = 1.0


def _ms_eoy3(ms90: float, ms30: float, ms_anchor: float, ms_cap: float) -> float:
    velocity = min(max(ms30 / max(ms_anchor, 1e-12), 1.0), _MS_AMPLIFIER_CAP)
    log_v = math.log(velocity) / 6.0
    acc = 0.0
    for m in range(_MS_MONTHS):
        acc += log_v * max(0.0, 1.0 - (m + 0.5) / _MS_DECAY_MONTHS)
    return min(ms90 * math.exp(acc), ms_cap)


def _backtest_signals(backtest_chart: list) -> dict:
    if not backtest_chart:
        return {"chart": [], "signals": {}, "latest_signal": "NEUTRAL", "last_realized_row": None}
    price_lookup = {row["date"]: row["spot"] for row in backtest_chart}
    all_dates = sorted(price_lookup)
    today = date.fromisoformat(max(all_dates))

    def _near_price(from_str: str, offset: int):
        tgt = str(date.fromisoformat(from_str) + timedelta(days=offset))
        best = sorted((abs((date.fromisoformat(d) - date.fromisoformat(tgt)).days), price_lookup[d]) for d in all_dates)
        return best[0][1] if best and best[0][0] <= 5 else None

    groups: dict = {s: {"r30": [], "r90": [], "dates": []} for s in ["GOOD", "NEUTRAL", "BAD"]}
    last_real = None
    for row in backtest_chart:
        d, sig, p0 = row["date"], row["signal"], row["spot"]
        days_ago = (today - date.fromisoformat(d)).days
        if days_ago >= 30:
            p30 = _near_price(d, 30)
            if p30:
                groups[sig]["r30"].append(p30 / p0 - 1)
                last_real = d
        if days_ago >= 90:
            p90 = _near_price(d, 90)
            if p90:
                groups[sig]["r90"].append(p90 / p0 - 1)
        groups[sig]["dates"].append(d)
    signals = {s: {"obs": len(g["dates"]),
                   "avg_30d": float(np.mean(g["r30"])) if g["r30"] else None,
                   "avg_90d": float(np.mean(g["r90"])) if g["r90"] else None,
                   "recent_dates": g["dates"][-3:]}
               for s, g in groups.items()}
    return {"chart": backtest_chart, "signals": signals,
            "latest_signal": backtest_chart[-1]["signal"], "last_realized_row": last_real}

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")

_CG_KEY = os.environ.get("COINGECKO_API_KEY", "")
_CG_BASE = "https://pro-api.coingecko.com/api/v3" if _CG_KEY else "https://api.coingecko.com/api/v3"

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
    hdrs = {"User-Agent": "Mozilla/5.0"}
    if _CG_KEY and "coingecko.com" in url:
        hdrs["x-cg-pro-api-key"] = _CG_KEY
    req = urllib.request.Request(url, headers=hdrs)
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception:
            if i == 2:
                raise
            time.sleep(2 * (i + 1))


def cg_market():
    url = f"{_CG_BASE}/coins/markets?vs_currency=usd&ids=jupiter-exchange-solana"
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
    supply = np.maximum(supply, circ * 0.10)

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


# Solana perps peers tracked in DefiLlama fees (volume proxy)
PERPS_PEER_SLUGS = ["drift", "flash-trade"]


def fetch_perps_fees_daily(slug: str):
    """Return [(date_str, fees_usd)] from DefiLlama fees endpoint."""
    try:
        data = fetch_json(f"https://api.llama.fi/summary/fees/{slug}?dataType=dailyFees")
        rows = []
        for ts, val in data.get("totalDataChart", []) or []:
            rows.append((datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat(), float(val or 0)))
        rows.sort()
        return rows
    except Exception:
        return []


def compute_jup_ms(jup_rows, peer_rows_list):
    """Compute rolling 30D/90D/180D JUP perps fee share vs Solana perps peers; return snapshot, history, ms_full."""
    jup_by_date = dict(jup_rows)
    peer_by_date: dict[str, float] = {}
    for rows in peer_rows_list:
        for d, v in rows:
            peer_by_date[d] = peer_by_date.get(d, 0.0) + v

    common = sorted(set(jup_by_date) & set(peer_by_date))
    if not common:
        return None, [], []

    jup_arr  = np.array([jup_by_date.get(d, 0.0)  for d in common], dtype=float)
    peer_arr = np.array([peer_by_date.get(d, 0.0) for d in common], dtype=float)
    total_arr = jup_arr + peer_arr

    def rolling_sum(arr, w):
        cs = np.concatenate([[0.0], np.cumsum(arr)])
        out = np.full(len(arr), np.nan)
        if len(arr) >= w:
            out[w - 1:] = cs[w:] - cs[:-w]
        return out

    rj30  = rolling_sum(jup_arr, 30);  rt30  = rolling_sum(total_arr, 30)
    rj90  = rolling_sum(jup_arr, 90);  rt90  = rolling_sum(total_arr, 90)
    rj180 = rolling_sum(jup_arr, 180); rt180 = rolling_sum(total_arr, 180)

    def safe_ratio(j, t): return float(np.clip(j / t, 0, 1.0)) if t > 0 else None

    ms30  = safe_ratio(rj30[-1],  rt30[-1])
    ms90  = safe_ratio(rj90[-1],  rt90[-1])
    ms180 = safe_ratio(rj180[-1], rt180[-1])

    snapshot = {
        "ms30": ms30,
        "ms90": ms90,
        "ms180": ms180,
        "jup_perps_30d_fees": float(rj30[-1]) if not np.isnan(rj30[-1]) else None,
        "solana_perps_30d_fees": float(rt30[-1]) if not np.isnan(rt30[-1]) else None,
    }

    start = max(0, len(common) - 365)
    history = []
    ms_full = []
    for i, d in enumerate(common[start:], start=start):
        if np.isnan(rj30[i]) or rt30[i] <= 0:
            continue
        ms30_i  = safe_ratio(rj30[i],  rt30[i])
        ms90_i  = safe_ratio(rj90[i],  rt90[i])  if not np.isnan(rj90[i])  and rt90[i]  > 0 else None
        ms180_i = safe_ratio(rj180[i], rt180[i]) if not np.isnan(rj180[i]) and rt180[i] > 0 else None
        if ms30_i is not None:
            history.append({"date": d, "ms30": round(ms30_i, 5),
                            "ms90": round(ms90_i, 5) if ms90_i is not None else None})
            ms_full.append({"date": d, "ms30": ms30_i, "ms90": ms90_i, "ms180": ms180_i})

    return snapshot, history, ms_full


def fetch_jup_price_history():
    """Return (price_by_date, _) dicts from CoinGecko market_chart."""
    try:
        url = f"{_CG_BASE}/coins/jupiter-exchange-solana/market_chart?vs_currency=usd&days=365&interval=daily"
        d = fetch_json(url)
        price_by_date: dict = {}
        seen: set = set()
        for ms, p in d.get("prices", []):
            ds = str(datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date())
            if ds not in seen:
                seen.add(ds)
                price_by_date[ds] = float(p)
        return price_by_date
    except Exception:
        return {}


def compute_jup_hist_charts(jup_perps_rows, ms_full, price_by_date, circ, DR, multiple, p50_pv, spot):
    """Build hist_charts for JUP: backtest + buyback-horizon secondary chart + EOY3 Solana perps share."""
    perps_by_date = dict(jup_perps_rows)

    # ── EOY3 Solana perps MS history ─────────────────────────────────────────
    eoy3_ms_out = []
    for row in ms_full:
        ms30 = row["ms30"]; ms90 = row["ms90"]; ms180 = row.get("ms180")
        if ms30 is None or ms90 is None:
            continue
        anchor = ms180 if ms180 is not None else ms90
        eoy3 = _ms_eoy3(ms90, ms30, anchor, _JUP_PERPS_CAP)
        eoy3_ms_out.append({"date": row["date"], "eoy3": round(eoy3, 5),
                             "ms90": round(ms90, 5), "ms30": round(ms30, 5)})

    # ── Secondary chart: buyback horizon (years to buy circ at current GP×50%) ─
    perps_dates = sorted(perps_by_date)
    secondary_data = []
    for i, d in enumerate(perps_dates):
        price = price_by_date.get(d)
        if price is None or price <= 0:
            continue
        s30 = max(0, i - 29)
        trailing_30d = sum(perps_by_date.get(perps_dates[j], 0.0) for j in range(s30, i + 1))
        if trailing_30d <= 0:
            continue
        # Annualise perps GP (25% take) and apply 50% buyback share
        ann_perps_gp = trailing_30d * 0.25 * (365.0 / 30.0)
        ann_buyback_tokens = ann_perps_gp * BUYBACK_SHARE / max(price, 0.001)
        if ann_buyback_tokens <= 0:
            continue
        years = circ / ann_buyback_tokens
        if 0 < years < 200:
            secondary_data.append({"date": d, "value": round(years, 2)})

    # ── Backtest: model-shaped PV (perps GP × core premium, no MC) ───────────
    common_bt = sorted(set(perps_by_date) & set(price_by_date))
    pv_raw_list = []
    for i, d in enumerate(common_bt):
        s30 = max(0, i - 29)
        trailing = sum(perps_by_date.get(common_bt[j], 0.0) for j in range(s30, i + 1))
        ann_gp = trailing * 0.25 * (365.0 / 30.0)  # core perps GP
        pv_raw = ann_gp * multiple / ((1 + DR) ** 3) / max(circ, 1.0)
        price = price_by_date.get(d)
        if price and price > 0 and pv_raw > 0:
            pv_raw_list.append((d, pv_raw, price))

    if not pv_raw_list:
        return {"backtest": {"chart": [], "signals": {}, "latest_signal": "NEUTRAL", "last_realized_row": None},
                "secondary_chart": {"label": "Buyback horizon", "subtitle": "",
                                    "note": "", "unit": "y", "data": secondary_data},
                "eoy3_ms": eoy3_ms_out}

    norm = (p50_pv / pv_raw_list[-1][1]) if pv_raw_list[-1][1] > 0 else 1.0
    bt_chart = []
    for d, pv_r, price in pv_raw_list:
        pv_n = pv_r * norm
        sig = "GOOD" if pv_n / price >= 1.25 else ("BAD" if pv_n / price <= 0.75 else "NEUTRAL")
        bt_chart.append({"date": d, "spot": round(price, 4), "pv": round(pv_n, 4), "signal": sig})

    return {
        "backtest": _backtest_signals(bt_chart),
        "secondary_chart": {
            "label": "Historical perps GP buyback horizon",
            "subtitle": "Years to buy circ supply at 50% of annualised perps GP",
            "note": "Uses trailing 30D JUP Perps fees × 25% take × 50% buyback share. Perps GP only; spot GP excluded.",
            "unit": "y",
            "data": secondary_data,
        },
        "eoy3_ms": eoy3_ms_out,
    }


def run() -> dict:
    """Fetch live data, run MC, return standardized result dict for the frontend."""
    market = cg_market()
    gpdata = gp_series_and_seeds()
    valuation = run_mc(market, gpdata)

    # ── Solana perps market share ─────────────────────────────────────────────
    ms_snapshot, ms_history, ms_full_hist = None, [], []
    jup_perps_rows_saved = []
    try:
        jup_perps_rows_saved = fetch_perps_fees_daily("jupiter-perpetual-exchange")
        peer_perps_rows = [fetch_perps_fees_daily(s) for s in PERPS_PEER_SLUGS]
        ms_snapshot, ms_history, ms_full_hist = compute_jup_ms(jup_perps_rows_saved, peer_perps_rows)
    except Exception:
        pass

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
            # Y3 model outputs
            "y3_gp_p50":          valuation["y3_state"]["y3_ttm_gp"]["p50"],
            "y3_perps_gp_p50":    valuation["y3_state"]["y3_perps_gp"]["p50"],
            "y3_supply_p50":      valuation["y3_state"]["y3_effective_supply"]["p50"],
            "buyback_tokens_p50": valuation["y3_state"]["buyback_accum_tokens"]["p50"],
            # Solana perps market share (fee-based)
            **({"ms30_vs_sol_perps":  ms_snapshot["ms30"],
                "ms90_vs_sol_perps":  ms_snapshot["ms90"],
                "ms180_vs_sol_perps": ms_snapshot["ms180"],
                "ms30_ms180_trend": (ms_snapshot["ms30"] / ms_snapshot["ms180"])
                                    if ms_snapshot and ms_snapshot["ms30"] and ms_snapshot["ms180"] else None,
                "jup_perps_30d_fees": ms_snapshot["jup_perps_30d_fees"],
                "sol_perps_30d_fees": ms_snapshot["solana_perps_30d_fees"],
               } if ms_snapshot else {}),
        },
        "y3_state": valuation["y3_state"],
        "scenarios": scenarios,
        "ms_history": ms_history,
    }

    # ── Historical charts (backtest / buyback horizon / EOY3 perps MS) ───────
    try:
        price_hist = fetch_jup_price_history()
        circ_jup = float(market.get("circulating_supply") or market["market_cap"] / spot)
        p50_pv_jup = c["core"]["discounted_pv"]["p50"]
        result["hist_charts"] = compute_jup_hist_charts(
            jup_perps_rows_saved, ms_full_hist,
            price_hist, circ_jup, DISCOUNT, MULTIPLE, p50_pv_jup, spot,
        )
    except Exception:
        pass

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "jup_result.json"), "w") as f:
        json.dump(result, f, indent=2)

    return result
