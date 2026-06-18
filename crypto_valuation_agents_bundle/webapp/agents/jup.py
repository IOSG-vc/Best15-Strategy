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
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

import numpy as np

BUNDLE_ROOT = Path(__file__).resolve().parents[2]
WEBAPP_ROOT = Path(__file__).resolve().parents[1]
if str(BUNDLE_ROOT) not in sys.path:
    sys.path.insert(0, str(BUNDLE_ROOT))
if str(WEBAPP_ROOT) not in sys.path:
    sys.path.insert(0, str(WEBAPP_ROOT))

import hype_gp_capture_mc as hype_mc
from agents.uni import (
    BLOCKWORKS_BINANCE_SPOT_ANNUAL,
    _ms_acceleration_path,
    _share_velocity,
    scaled_binance_spot_daily,
)

_MS_AMPLIFIER_CAP = 1.5
_MS_DECAY_MONTHS = 12
_MS_MONTHS = 36
_JUP_PERPS_CAP = 1.0
JUP_BINANCE_PERPS_MS_CAP = 0.10
JUP_BINANCE_SPOT_MS_CAP = 0.10
VELOCITY_FLOOR = -0.05
VELOCITY_CAP = 0.12
VELOCITY_DECAY_MONTHS = 12
CHART_QS = (5, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 95)


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
PERPS_CLEAN_TAKE_RATE_FALLBACK = 0.00015
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


def try_llama_summary(kind: str, slug: str, data_type: str):
    try:
        return llama_summary(kind, slug, data_type)
    except Exception:
        return {"totalDataChart": []}


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


def _date_str(d):
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def _monthly_sums_any(rows):
    d = defaultdict(float)
    for day, val in rows:
        ds = _date_str(day)
        d[ds[:7]] += float(val)
    return sorted(d.items())


def _monthly_log_returns(months):
    vals = [float(v) for _, v in months if v > 0]
    rets = []
    for a, b in zip(vals, vals[1:]):
        if a > 0 and b > 0:
            rets.append(max(-0.75, min(0.75, math.log(b / a))))
    return np.array(rets or [0.0], dtype=float)


def _sample_denominator_paths(rows, rng):
    current_month = datetime.now(timezone.utc).date().isoformat()[:7]
    months = [(m, v) for m, v in _monthly_sums_any(rows) if m < current_month and v > 0]
    if not months:
        raise RuntimeError("No monthly denominator history available")
    start_pool = np.array([v for _, v in months], dtype=float)
    rets = _monthly_log_returns(months)
    starts = rng.choice(start_pool, size=N_PATHS, replace=True)
    draws = rng.choice(rets, size=(N_PATHS, MONTHS), replace=True)
    paths = starts[:, None] * np.exp(np.cumsum(draws, axis=1))
    monthly_cap = float(np.max(start_pool) * 2.0)
    paths = np.minimum(paths, monthly_cap)
    return paths, starts, rets, months


def compute_volume_ms(numerator_rows, denominator_rows, cap, history_days=365):
    num_by_date = {_date_str(d): float(v) for d, v in numerator_rows if v and v > 0}
    den_by_date = {_date_str(d): float(v) for d, v in denominator_rows if v and v > 0}
    common = sorted(set(num_by_date) & set(den_by_date))
    if not common:
        return None, [], []

    num_arr = np.array([num_by_date.get(d, 0.0) for d in common], dtype=float)
    den_arr = np.array([den_by_date.get(d, 0.0) for d in common], dtype=float)

    def rolling_sum(arr, w):
        cs = np.concatenate([[0.0], np.cumsum(arr)])
        out = np.full(len(arr), np.nan)
        if len(arr) >= w:
            out[w - 1:] = cs[w:] - cs[:-w]
        return out

    rn7 = rolling_sum(num_arr, 7);   rd7 = rolling_sum(den_arr, 7)
    rn30 = rolling_sum(num_arr, 30); rd30 = rolling_sum(den_arr, 30)
    rn90 = rolling_sum(num_arr, 90); rd90 = rolling_sum(den_arr, 90)
    rn180 = rolling_sum(num_arr, 180); rd180 = rolling_sum(den_arr, 180)

    def safe_ratio(n, d):
        return float(np.clip(n / d, 0.0, cap)) if d and d > 0 else None

    snapshot = {
        "ms7": safe_ratio(rn7[-1], rd7[-1]) if not np.isnan(rn7[-1]) else None,
        "ms30": safe_ratio(rn30[-1], rd30[-1]) if not np.isnan(rn30[-1]) else None,
        "ms90": safe_ratio(rn90[-1], rd90[-1]) if not np.isnan(rn90[-1]) else None,
        "ms180": safe_ratio(rn180[-1], rd180[-1]) if not np.isnan(rn180[-1]) else None,
        "numerator_30d_volume": float(rn30[-1]) if not np.isnan(rn30[-1]) else None,
        "numerator_90d_volume": float(rn90[-1]) if not np.isnan(rn90[-1]) else None,
        "numerator_180d_volume": float(rn180[-1]) if not np.isnan(rn180[-1]) else None,
        "denominator_30d_volume": float(rd30[-1]) if not np.isnan(rd30[-1]) else None,
        "denominator_90d_volume": float(rd90[-1]) if not np.isnan(rd90[-1]) else None,
        "denominator_180d_volume": float(rd180[-1]) if not np.isnan(rd180[-1]) else None,
        "share_cap": cap,
    }

    history = []
    full = []
    start = max(0, len(common) - history_days) if history_days is not None else 0
    for i, d in enumerate(common[start:], start=start):
        if np.isnan(rn30[i]) or rd30[i] <= 0:
            continue
        ms7_i = safe_ratio(rn7[i], rd7[i]) if not np.isnan(rn7[i]) and rd7[i] > 0 else None
        ms30_i = safe_ratio(rn30[i], rd30[i])
        ms90_i = safe_ratio(rn90[i], rd90[i]) if not np.isnan(rn90[i]) and rd90[i] > 0 else None
        ms180_i = safe_ratio(rn180[i], rd180[i]) if not np.isnan(rn180[i]) and rd180[i] > 0 else None
        history.append({"date": d, "ms30": round(ms30_i, 5), "ms90": round(ms90_i, 5) if ms90_i is not None else None})
        full.append({"date": d, "ms7": ms7_i, "ms30": ms30_i, "ms90": ms90_i, "ms180": ms180_i})
    return snapshot, history, full


def share_path_from_snapshot(snapshot, cap):
    if not snapshot or snapshot.get("ms90") is None:
        return np.full(MONTHS, 0.0, dtype=float), {"velocity_raw": 1.0, "velocity_capped": 1.0}
    velocity = _share_velocity(snapshot)
    path = float(snapshot["ms90"]) * _ms_acceleration_path(MONTHS, velocity["velocity_capped"])
    return np.minimum(path, cap), velocity


def trailing_sum(rows, n=30):
    return float(sum(v for _, v in rows[-n:])) if rows else 0.0


def median_last12(months):
    vals = [v for _, v in months[-12:] if v > 0]
    return float(statistics.median(vals)) if vals else 0.0


def pct_dict(x, qs=(25, 50, 75, 90)):
    return {f"p{q}": float(np.percentile(x, q)) for q in qs}


def pct_change(future, current):
    if future is None or current is None or current == 0:
        return None
    return float(future / current - 1.0)


def growth_velocity(rows):
    """Return capped 70/30 growth velocity using 30D/180D and 7D/30D daily GP averages."""
    vals = [float(v) for _, v in rows if v is not None]

    def avg_last(n):
        if not vals:
            return 0.0
        window = vals[-min(n, len(vals)):]
        return float(np.mean(window)) if window else 0.0

    avg_7 = avg_last(7)
    avg_30 = avg_last(30)
    avg_180 = avg_last(180)

    def monthly_equiv(short, long, midpoint_gap_days):
        if short <= 0 or long <= 0:
            return 0.0
        return float((short / long) ** (30.0 / midpoint_gap_days) - 1.0)

    raw_30_180 = monthly_equiv(avg_30, avg_180, 75.0)
    raw_7_30 = monthly_equiv(avg_7, avg_30, 11.5)
    capped_30_180 = float(np.clip(raw_30_180, VELOCITY_FLOOR, VELOCITY_CAP))
    capped_7_30 = float(np.clip(raw_7_30, VELOCITY_FLOOR, VELOCITY_CAP))
    starting = 0.70 * capped_30_180 + 0.30 * capped_7_30
    return {
        "avg_7d": avg_7,
        "avg_30d": avg_30,
        "avg_180d": avg_180,
        "raw_30d_180d_monthly": raw_30_180,
        "raw_7d_30d_monthly": raw_7_30,
        "capped_30d_180d_monthly": capped_30_180,
        "capped_7d_30d_monthly": capped_7_30,
        "starting_velocity_monthly": float(starting),
        "velocity_floor_monthly": VELOCITY_FLOOR,
        "velocity_cap_monthly": VELOCITY_CAP,
        "decay_months": VELOCITY_DECAY_MONTHS,
    }


def velocity_log_curve(starting_velocity):
    monthly_log = math.log(max(1.0 + float(starting_velocity), 1e-6))
    decay = np.maximum(0.0, 1.0 - (np.arange(MONTHS, dtype=float) + 0.5) / VELOCITY_DECAY_MONTHS)
    return monthly_log * decay


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
    perps_volume_direct = chart_rows(try_llama_summary("derivatives", "jupiter-perpetual-exchange", "dailyVolume"))
    agg_volume_direct = chart_rows(try_llama_summary("dexs", "jupiter", "dailyVolume"))
    if not agg_volume_direct:
        agg_volume_direct = chart_rows(try_llama_summary("dexs", "jupiter-aggregator", "dailyVolume"))
    lend_revenue = chart_rows(llama_summary("fees", "jupiter-lend", "dailyRevenue"))
    jupsol_revenue = chart_rows(llama_summary("fees", "jupiter-staked-sol", "dailyRevenue"))
    ape_revenue = chart_rows(llama_summary("fees", "ape-jupiter", "dailyRevenue"))
    prediction_revenue = chart_rows(llama_summary("fees", "jupiter-prediction", "dailyRevenue"))
    dca_fees = chart_rows(llama_summary("fees", "jupiter-dca", "dailyFees"))

    rake = AGG_RAKE_BPS_FALLBACK / 10000.0
    perps_gp_daily = [(d, v * 0.25) for d, v in perps_fees]
    agg_gp_daily = agg_fees
    jupz_gp_daily = [(d, v * rake) for d, v in jupz_vol]
    spot_gp_daily = []
    spot_daily = defaultdict(float)
    for d, v in agg_gp_daily:
        spot_daily[d] += v
    for d, v in jupz_gp_daily:
        spot_daily[d] += v
    spot_gp_daily = sorted(spot_daily.items())

    if perps_volume_direct:
        perps_volume_daily = perps_volume_direct
        perps_volume_source = "DefiLlama derivatives dailyVolume"
    else:
        perps_volume_daily = [(d, v / PERPS_CLEAN_TAKE_RATE_FALLBACK) for d, v in perps_gp_daily if v > 0]
        perps_volume_source = f"fallback: JUP Perps clean GP / {PERPS_CLEAN_TAKE_RATE_FALLBACK * 10000:.2f}bps clean take-rate"

    if agg_volume_direct:
        agg_volume_daily = agg_volume_direct
        agg_volume_source = "DefiLlama DEX dailyVolume"
    else:
        agg_volume_daily = [(d, v / rake) for d, v in agg_gp_daily if v > 0]
        agg_volume_source = f"fallback: aggregator fees / {AGG_RAKE_BPS_FALLBACK:.2f}bps rake"
    spot_volume_by_date = defaultdict(float)
    for d, v in agg_volume_daily:
        spot_volume_by_date[d] += v
    for d, v in jupz_vol:
        spot_volume_by_date[d] += v
    spot_volume_daily = sorted(spot_volume_by_date.items())

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
    perps_vol_30 = trailing_sum(perps_volume_daily, 30)
    spot_vol_30 = trailing_sum(spot_volume_daily, 30)
    perps_take_rate = perps_30 / perps_vol_30 if perps_vol_30 > 0 else PERPS_CLEAN_TAKE_RATE_FALLBACK
    spot_take_rate = spot_30 / spot_vol_30 if spot_vol_30 > 0 else rake

    perps_med12 = median_last12(perps_months)
    spot_med12 = median_last12(spot_months)
    perps_seed = min(perps_30, perps_med12) if perps_med12 else perps_30
    spot_seed = min(spot_30, spot_med12) if spot_med12 else spot_30

    binance_futures_daily, binance_futures_shares = hype_mc.scaled_binance_futures_daily()
    binance_spot_daily, binance_spot_shares = scaled_binance_spot_daily()
    perps_ms_snapshot, perps_ms_history, perps_ms_full = compute_volume_ms(
        perps_volume_daily, binance_futures_daily, JUP_BINANCE_PERPS_MS_CAP
    )
    spot_ms_snapshot, spot_ms_history, spot_ms_full = compute_volume_ms(
        spot_volume_daily, binance_spot_daily, JUP_BINANCE_SPOT_MS_CAP
    )

    return {
        "months": {"perps_gp": perps_months, "spot_gp": spot_months},
        "denominators": {
            "binance_futures_daily": binance_futures_daily,
            "binance_spot_daily": binance_spot_daily,
            "binance_futures_btcusdt_shares": binance_futures_shares,
            "binance_spot_btcusdt_shares": binance_spot_shares,
        },
        "volume_rows": {
            "perps": perps_volume_daily,
            "spot": spot_volume_daily,
        },
        "market_share": {
            "perps_snapshot": perps_ms_snapshot,
            "perps_history": perps_ms_history,
            "perps_full": perps_ms_full,
            "spot_snapshot": spot_ms_snapshot,
            "spot_history": spot_ms_history,
            "spot_full": spot_ms_full,
        },
        "seeds": {
            "perps_30d_gp": perps_30,
            "perps_12m_median_gp": perps_med12,
            "perps_seed_gp": perps_seed,
            "perps_30d_volume": perps_vol_30,
            "perps_clean_take_rate": perps_take_rate,
            "perps_volume_source": perps_volume_source,
            "aggregator_30d_gp": agg_30,
            "aggregator_30d_volume": trailing_sum(agg_volume_daily, 30),
            "aggregator_volume_source": agg_volume_source,
            "jupiterz_30d_volume": jupz_vol_30,
            "jupiterz_implied_30d_gp": jupz_gp_30,
            "spot_30d_gp": spot_30,
            "spot_30d_volume": spot_vol_30,
            "spot_take_rate": spot_take_rate,
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
            "perps_velocity": growth_velocity(perps_gp_daily),
            "spot_velocity": growth_velocity(spot_gp_daily),
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


def centered_returns(months):
    rets = sample_returns(months)
    if len(rets) <= 1:
        return rets
    return rets - float(np.mean(rets))


def run_mc(market, gpdata):
    spot = float(market["current_price"])
    circ = float(market.get("circulating_supply") or market["market_cap"] / spot)

    rng = np.random.default_rng(42)
    perps_den_paths, perps_start, perps_rets, perps_months = _sample_denominator_paths(
        gpdata["denominators"]["binance_futures_daily"], rng
    )
    spot_den_paths, spot_start, spot_rets, spot_months = _sample_denominator_paths(
        gpdata["denominators"]["binance_spot_daily"], rng
    )
    perps_share_path, perps_velocity = share_path_from_snapshot(
        gpdata["market_share"]["perps_snapshot"], JUP_BINANCE_PERPS_MS_CAP
    )
    spot_share_path, spot_velocity = share_path_from_snapshot(
        gpdata["market_share"]["spot_snapshot"], JUP_BINANCE_SPOT_MS_CAP
    )
    perps_volume_monthly = perps_den_paths * perps_share_path[None, :]
    spot_volume_monthly = spot_den_paths * spot_share_path[None, :]
    perps_monthly = perps_volume_monthly * float(gpdata["seeds"]["perps_clean_take_rate"])
    spot_monthly = spot_volume_monthly * float(gpdata["seeds"]["spot_take_rate"])
    total_monthly = perps_monthly + spot_monthly
    y3_perps_gp = perps_monthly[:, -12:].sum(axis=1)
    y3_spot_gp = spot_monthly[:, -12:].sum(axis=1)
    y3_perps_volume = perps_volume_monthly[:, -12:].sum(axis=1)
    y3_spot_volume = spot_volume_monthly[:, -12:].sum(axis=1)
    y3_gp = y3_perps_gp + y3_spot_gp
    y2_gp = total_monthly[:, 12:24].sum(axis=1)

    supply = np.full(N_PATHS, circ, dtype=float)
    buyback_tokens_accum = np.zeros(N_PATHS, dtype=float)
    y2_supply = None
    for t in range(MONTHS):
        buy_tokens = (total_monthly[:, t] * BUYBACK_SHARE) / max(spot, 0.01)
        supply += SCHEDULED_UNLOCKS_PER_MONTH - buy_tokens
        buyback_tokens_accum += buy_tokens
        if t == 23:
            y2_supply = supply.copy()
    supply = np.maximum(supply, circ * 0.10)
    if y2_supply is None:
        y2_supply = supply.copy()
    y2_supply = np.maximum(y2_supply, circ * 0.10)

    y3_price_core = y3_gp * MULTIPLE / supply
    y2_price_core = y2_gp * MULTIPLE / y2_supply
    result_cases = {}
    for key, premium in PREMIUMS.items():
        y3_price = y3_price_core * premium
        y2_price = y2_price_core * premium
        pv = y3_price / ((1 + DISCOUNT) ** 3)
        result_cases[key] = {
            "discounted_pv": pct_dict(pv),
            "distribution": pct_dict(pv, CHART_QS),
            "discounted_ev": float(np.mean(pv)),
            "p50_to_spot": float(np.percentile(pv, 50) / spot),
            "ev_to_spot": float(np.mean(pv) / spot),
            "prob_pv_gt_spot": float(np.mean(pv > spot)),
            "prob_spot_up_30_2y": float(np.mean(y2_price >= 1.30 * spot)),
            "prob_spot_down_30_2y": float(np.mean(y2_price <= 0.70 * spot)),
            "prob_pv_gt_2x": float(np.mean(pv > 2 * spot)),
            "prob_pv_gt_3x": float(np.mean(pv > 3 * spot)),
            "y3_price_p50": float(np.percentile(y3_price, 50)),
            "y3_mcap_p50": float(np.percentile(y3_price * supply, 50)),
            "y3_supply_p50": float(np.percentile(supply, 50)),
            "y3_gp_p50": float(np.percentile(y3_gp, 50)),
            "y3_gp_by_product_line_p50": {
                "perps": float(np.percentile(y3_perps_gp, 50)),
                "spot_aggregator_jupiterz": float(np.percentile(y3_spot_gp, 50)),
            },
            "y3_volume_by_product_line_p50": {
                "perps": float(np.percentile(y3_perps_volume, 50)),
                "spot_aggregator_jupiterz": float(np.percentile(y3_spot_volume, 50)),
            },
            "y3_daily_mean_gp_p50": float(np.percentile(y3_gp / 365.0, 50)),
            "y3_daily_mean_volume_by_product_line_p50": {
                "perps": float(np.percentile(y3_perps_volume / 365.0, 50)),
                "spot_aggregator_jupiterz": float(np.percentile(y3_spot_volume / 365.0, 50)),
            },
        }

    return {
        "mc": {
            "paths": N_PATHS,
            "months": MONTHS,
            "perps_logret_mean": float(np.mean(perps_rets)),
            "perps_logret_std": float(np.std(perps_rets, ddof=1)) if len(perps_rets) > 1 else 0.0,
            "spot_logret_mean": float(np.mean(spot_rets)),
            "spot_logret_std": float(np.std(spot_rets, ddof=1)) if len(spot_rets) > 1 else 0.0,
            "perps_return_months": int(len(perps_rets)),
            "spot_return_months": int(len(spot_rets)),
            "volume_proxy": "Perps use sampled Binance Futures monthly volume; spot uses sampled Binance spot monthly volume.",
            "perps_denominator_months": len(perps_months),
            "spot_denominator_months": len(spot_months),
            "start_binance_futures_monthly_p50": float(np.percentile(perps_start, 50)),
            "start_binance_spot_monthly_p50": float(np.percentile(spot_start, 50)),
            "perps_share_velocity": perps_velocity,
            "spot_share_velocity": spot_velocity,
            "perps_eoy3_share_model": float(perps_share_path[-1]),
            "spot_eoy3_share_model": float(spot_share_path[-1]),
            "perps_clean_take_rate": float(gpdata["seeds"]["perps_clean_take_rate"]),
            "spot_take_rate": float(gpdata["seeds"]["spot_take_rate"]),
            "velocity_method": "70% MS30/MS180 + 30% MS7/MS30 monthly-equivalent share velocity, capped and decayed over 12 months; MC draws sample external Binance denominator monthly log returns.",
        },
        "y3_state": {
            "y3_ttm_gp": pct_dict(y3_gp),
            "y3_perps_gp": pct_dict(y3_perps_gp),
            "y3_spot_gp": pct_dict(y3_spot_gp),
            "y3_perps_volume": pct_dict(y3_perps_volume),
            "y3_spot_volume": pct_dict(y3_spot_volume),
            "y3_effective_supply": pct_dict(supply),
            "buyback_accum_tokens": pct_dict(buyback_tokens_accum),
            "y3_daily_mean_gp": pct_dict(y3_gp / 365.0),
            "y3_daily_mean_perps_volume": pct_dict(y3_perps_volume / 365.0),
            "y3_daily_mean_spot_volume": pct_dict(y3_spot_volume / 365.0),
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
    current_baselines = {
        "entity_gp_annualized": s["total_seed_gp"] * 12,
        "perps_gp_annualized": s["perps_seed_gp"] * 12,
        "spot_gp_annualized": s["spot_seed_gp"] * 12,
        "perps_daily_volume": s["perps_30d_volume"] / 30.0 if s["perps_30d_volume"] else 0.0,
        "spot_daily_volume": s["spot_30d_volume"] / 30.0 if s["spot_30d_volume"] else 0.0,
        "circulating_supply": float(market.get("circulating_supply") or 0),
    }
    y3_vs_current_pct = {
        "entity_gp_pct": pct_change(valuation["y3_state"]["y3_ttm_gp"]["p50"], current_baselines["entity_gp_annualized"]),
        "perps_gp_pct": pct_change(valuation["y3_state"]["y3_perps_gp"]["p50"], current_baselines["perps_gp_annualized"]),
        "spot_gp_pct": pct_change(valuation["y3_state"]["y3_spot_gp"]["p50"], current_baselines["spot_gp_annualized"]),
        "perps_daily_volume_pct": pct_change(valuation["y3_state"]["y3_daily_mean_perps_volume"]["p50"], current_baselines["perps_daily_volume"]),
        "spot_daily_volume_pct": pct_change(valuation["y3_state"]["y3_daily_mean_spot_volume"]["p50"], current_baselines["spot_daily_volume"]),
        "effective_supply_pct": pct_change(valuation["y3_state"]["y3_effective_supply"]["p50"], current_baselines["circulating_supply"]),
    }

    scenarios = []
    case_labels = [
        ("core", "Core GP", False),
        ("opt_10", "+10% Optionality", False),
        ("opt_10_jupnet_10", "+10% Opt + Jupnet", True),
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
            "prob_spot_up_30_2y": case["prob_spot_up_30_2y"],
            "prob_spot_down_30_2y": case["prob_spot_down_30_2y"],
            "prob_3x": case["prob_pv_gt_3x"],
            "distribution": case["distribution"],
            "y3_price_p50": case["y3_price_p50"],
            "y3_mcap_p50": case["y3_mcap_p50"],
            "y3_supply_p50": case["y3_supply_p50"],
            "y3_gp_p50": case["y3_gp_p50"],
            "y3_gp_by_product_line_p50": case["y3_gp_by_product_line_p50"],
            "y3_volume_by_product_line_p50": case["y3_volume_by_product_line_p50"],
            "y3_daily_mean_gp_p50": case["y3_daily_mean_gp_p50"],
            "y3_daily_mean_volume_by_product_line_p50": case["y3_daily_mean_volume_by_product_line_p50"],
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
            "type": "3Y Binance-denominator Market-Share Monte Carlo",
            "discount_rate": DISCOUNT,
            "multiple": MULTIPLE,
            "paths": N_PATHS,
            "note": "Perps = Binance Futures volume × JUP/Binance perps share × clean take-rate; spot = Binance spot volume × JUP/Binance spot share × rake. 50% of modeled GP used for buybacks; 0 scheduled unlocks until Jupiter announces reserve plan.",
        },
        "current_gp": {
            "perps_30d": s["perps_30d_gp"],
            "perps_30d_volume": s["perps_30d_volume"],
            "perps_clean_take_rate": s["perps_clean_take_rate"],
            "perps_clean_take_rate_bps": s["perps_clean_take_rate"] * 10000,
            "perps_volume_source": s["perps_volume_source"],
            "aggregator_30d": s["aggregator_30d_gp"],
            "aggregator_30d_volume": s["aggregator_30d_volume"],
            "aggregator_volume_source": s["aggregator_volume_source"],
            "jupiterz_30d": s["jupiterz_implied_30d_gp"],
            "total_30d": s["total_30d_gp"],
            "spot_30d_volume": s["spot_30d_volume"],
            "spot_take_rate": s["spot_take_rate"],
            "spot_take_rate_bps": s["spot_take_rate"] * 10000,
            "seed_monthly": s["total_seed_gp"],
            "seed_annualized": s["total_seed_gp"] * 12,
            "optional_tracked_30d": s["tracked_optional_30d_revenue"],
            "entity_gp_annualized": s["total_seed_gp"] * 12,
            "mcap_entity_gp": float(market["market_cap"]) / max(s["total_seed_gp"] * 12, 1.0),
            "binance_futures_proxy_method": "BTCUSDT futures quote volume scaled by Blockworks annual Binance Futures totals",
            "binance_futures_btcusdt_shares": {str(k): float(v) for k, v in gpdata["denominators"]["binance_futures_btcusdt_shares"].items()},
            "binance_spot_proxy_method": "BTCUSDT spot quote volume scaled by Blockworks annual Binance spot totals",
            "blockworks_binance_spot_annual": BLOCKWORKS_BINANCE_SPOT_ANNUAL,
            "binance_spot_btcusdt_shares": {str(k): float(v) for k, v in gpdata["denominators"]["binance_spot_btcusdt_shares"].items()},
            "start_binance_futures_monthly_p50": valuation["mc"]["start_binance_futures_monthly_p50"],
            "start_binance_spot_monthly_p50": valuation["mc"]["start_binance_spot_monthly_p50"],
            "perps_growth_velocity_monthly": s["perps_velocity"]["starting_velocity_monthly"],
            "perps_velocity_30d_180d_raw": s["perps_velocity"]["raw_30d_180d_monthly"],
            "perps_velocity_7d_30d_raw": s["perps_velocity"]["raw_7d_30d_monthly"],
            "perps_velocity_30d_180d_capped": s["perps_velocity"]["capped_30d_180d_monthly"],
            "perps_velocity_7d_30d_capped": s["perps_velocity"]["capped_7d_30d_monthly"],
            "spot_growth_velocity_monthly": s["spot_velocity"]["starting_velocity_monthly"],
            "spot_velocity_30d_180d_raw": s["spot_velocity"]["raw_30d_180d_monthly"],
            "spot_velocity_7d_30d_raw": s["spot_velocity"]["raw_7d_30d_monthly"],
            "spot_velocity_30d_180d_capped": s["spot_velocity"]["capped_30d_180d_monthly"],
            "spot_velocity_7d_30d_capped": s["spot_velocity"]["capped_7d_30d_monthly"],
            "velocity_floor_monthly": VELOCITY_FLOOR,
            "velocity_cap_monthly": VELOCITY_CAP,
            "velocity_decay_months": VELOCITY_DECAY_MONTHS,
            # Y3 model outputs
            "y3_gp_p50":          valuation["y3_state"]["y3_ttm_gp"]["p50"],
            "y3_perps_gp_p50":    valuation["y3_state"]["y3_perps_gp"]["p50"],
            "y3_spot_gp_p50":     valuation["y3_state"]["y3_spot_gp"]["p50"],
            "y3_daily_mean_gp_p50": valuation["y3_state"]["y3_daily_mean_gp"]["p50"],
            "y3_perps_volume_p50": valuation["y3_state"]["y3_perps_volume"]["p50"],
            "y3_spot_volume_p50": valuation["y3_state"]["y3_spot_volume"]["p50"],
            "y3_perps_daily_mean_volume_p50": valuation["y3_state"]["y3_daily_mean_perps_volume"]["p50"],
            "y3_spot_daily_mean_volume_p50": valuation["y3_state"]["y3_daily_mean_spot_volume"]["p50"],
            "y3_supply_p50":      valuation["y3_state"]["y3_effective_supply"]["p50"],
            "buyback_tokens_p50": valuation["y3_state"]["buyback_accum_tokens"]["p50"],
            "current_baselines": current_baselines,
            "y3_vs_current_pct": y3_vs_current_pct,
            # Primary external-denominator market share.
            **(({"perps_ms7_vs_binance_futures": gpdata["market_share"]["perps_snapshot"]["ms7"],
                 "perps_ms30_vs_binance_futures": gpdata["market_share"]["perps_snapshot"]["ms30"],
                 "perps_ms90_vs_binance_futures": gpdata["market_share"]["perps_snapshot"]["ms90"],
                 "perps_ms180_vs_binance_futures": gpdata["market_share"]["perps_snapshot"]["ms180"],
                 "perps_ms30_ms180_binance_futures_trend": (
                    gpdata["market_share"]["perps_snapshot"]["ms30"] / gpdata["market_share"]["perps_snapshot"]["ms180"]
                    if gpdata["market_share"]["perps_snapshot"]["ms30"] and gpdata["market_share"]["perps_snapshot"]["ms180"] else None
                 ),
                 "perps_binance_futures_30d_volume": gpdata["market_share"]["perps_snapshot"]["denominator_30d_volume"],
                 "perps_eoy3_share_model": valuation["mc"]["perps_eoy3_share_model"],
                 "perps_share_velocity_raw": valuation["mc"]["perps_share_velocity"]["velocity_raw"],
                 "perps_share_velocity_capped": valuation["mc"]["perps_share_velocity"]["velocity_capped"],
                }) if gpdata["market_share"]["perps_snapshot"] else {}),
            **(({"spot_ms7_vs_binance_spot": gpdata["market_share"]["spot_snapshot"]["ms7"],
                 "spot_ms30_vs_binance_spot": gpdata["market_share"]["spot_snapshot"]["ms30"],
                 "spot_ms90_vs_binance_spot": gpdata["market_share"]["spot_snapshot"]["ms90"],
                 "spot_ms180_vs_binance_spot": gpdata["market_share"]["spot_snapshot"]["ms180"],
                 "spot_ms30_ms180_binance_spot_trend": (
                    gpdata["market_share"]["spot_snapshot"]["ms30"] / gpdata["market_share"]["spot_snapshot"]["ms180"]
                    if gpdata["market_share"]["spot_snapshot"]["ms30"] and gpdata["market_share"]["spot_snapshot"]["ms180"] else None
                 ),
                 "spot_binance_spot_30d_volume": gpdata["market_share"]["spot_snapshot"]["denominator_30d_volume"],
                 "spot_eoy3_share_model": valuation["mc"]["spot_eoy3_share_model"],
                 "spot_share_velocity_raw": valuation["mc"]["spot_share_velocity"]["velocity_raw"],
                 "spot_share_velocity_capped": valuation["mc"]["spot_share_velocity"]["velocity_capped"],
                }) if gpdata["market_share"]["spot_snapshot"] else {}),
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
        "ms_history": gpdata["market_share"]["perps_history"] or ms_history,
        "binance_perps_ms_history": gpdata["market_share"]["perps_history"],
        "binance_spot_ms_history": gpdata["market_share"]["spot_history"],
        "solana_perps_ms_history": ms_history,
        "caveats": [
            "JUP Perps direct DefiLlama derivatives volume is not available from the public summary endpoint in this environment; perps numerator falls back to clean-GP-implied volume unless a live dailyVolume series is returned.",
            "Jupiter aggregator volume falls back to fee-implied volume if the public DEX summary endpoint does not expose dailyVolume for the aggregator slug.",
        ],
    }

    # ── Historical charts (backtest / buyback horizon / EOY3 perps MS) ───────
    try:
        price_hist = fetch_jup_price_history()
        circ_jup = float(market.get("circulating_supply") or market["market_cap"] / spot)
        primary_key = next((sc["key"] for sc in scenarios if sc["is_primary"]), "core")
        p50_pv_jup = c[primary_key]["discounted_pv"]["p50"]
        result["hist_charts"] = compute_jup_hist_charts(
            jup_perps_rows_saved, gpdata["market_share"]["perps_full"] or ms_full_hist,
            price_hist, circ_jup, DISCOUNT, MULTIPLE, p50_pv_jup, spot,
        )
    except Exception:
        pass

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "jup_result.json"), "w") as f:
        json.dump(result, f, indent=2)

    return result
