"""UNI locked valuation agent — adapted for webapp.

Logic identical to run_uni_locked_report.py. Change: all module-level code
wrapped in run() function; returns standardized dict for the frontend.
"""
import csv
import io
import json
import math
import os
import statistics
from collections import defaultdict
from datetime import datetime, date, timezone
from urllib.request import Request, urlopen

import numpy as np

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
UA = "Mozilla/5.0 Hermes UNI locked valuation cron"

_CG_KEY = os.environ.get("COINGECKO_API_KEY", "")
_CG_BASE = "https://pro-api.coingecko.com/api/v3" if _CG_KEY else "https://api.coingecko.com/api/v3"


def get_json(url, timeout=30):
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    if _CG_KEY and "coingecko.com" in url:
        hdrs["x-cg-pro-api-key"] = _CG_KEY
    req = Request(url, headers=hdrs)
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def get_text(url, timeout=30):
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def ts_date(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).date()


def ym(d):
    return (d.year, d.month)


def money(x):
    ax = abs(x)
    if ax >= 1e12:
        return f"${x/1e12:.2f}T"
    if ax >= 1e9:
        return f"${x/1e9:.2f}B"
    if ax >= 1e6:
        return f"${x/1e6:.1f}M"
    return f"${x:,.0f}"


def parse_chart(data):
    out = []
    for ts, val in data["totalDataChart"]:
        if val is None:
            continue
        d = ts_date(ts)
        out.append((d, float(val)))
    out.sort()
    return out


MS_CAP = 0.70   # UNI/total-DEX ratio cap


def fetch_total_dex_daily():
    """Fetch total DEX daily volume from DefiLlama overview; return [(date, usd_volume)]."""
    data = get_json("https://api.llama.fi/overview/dexs?dataType=dailyVolume")
    rows = []
    for ts, val in data.get("totalDataChart", []):
        if val:
            rows.append((ts_date(ts), float(val)))
    return sorted(rows)


def compute_uni_ms(vol_by_date, dex_total_by_date):
    """Compute MS30/MS90/MS180 for UNI vs total DEX volume and return daily history."""
    common = sorted(set(vol_by_date) & set(dex_total_by_date))
    if not common:
        return None, []

    uni_arr = np.array([vol_by_date.get(d, 0.0)       for d in common], dtype=float)
    dex_arr = np.array([dex_total_by_date.get(d, 0.0) for d in common], dtype=float)

    def rolling_sum(arr, w):
        cs = np.concatenate([[0.0], np.cumsum(arr)])
        out = np.full(len(arr), np.nan)
        if len(arr) >= w:
            out[w - 1:] = cs[w:] - cs[:-w]
        return out

    rs30  = rolling_sum(uni_arr, 30);  rd30  = rolling_sum(dex_arr, 30)
    rs90  = rolling_sum(uni_arr, 90);  rd90  = rolling_sum(dex_arr, 90)
    rs180 = rolling_sum(uni_arr, 180); rd180 = rolling_sum(dex_arr, 180)

    def safe_ratio(u, d): return float(np.clip(u / d, 0, MS_CAP)) if d > 0 else None

    ms30  = safe_ratio(rs30[-1],  rd30[-1])
    ms90  = safe_ratio(rs90[-1],  rd90[-1])
    ms180 = safe_ratio(rs180[-1], rd180[-1])

    history = []
    start = max(0, len(common) - 365)
    for i, d in enumerate(common[start:], start=start):
        if np.isnan(rs30[i]) or rd30[i] <= 0:
            continue
        ms30_i = safe_ratio(rs30[i], rd30[i])
        ms90_i = safe_ratio(rs90[i], rd90[i]) if not np.isnan(rs90[i]) and rd90[i] > 0 else None
        if ms30_i is not None:
            history.append({"date": str(d), "ms30": round(ms30_i, 5),
                            "ms90": round(ms90_i, 5) if ms90_i is not None else None})

    return {"ms30": ms30, "ms90": ms90, "ms180": ms180}, history


def run() -> dict:
    """Fetch live data, run UNI GP-capture MC, return standardized result dict."""
    caveats = []

    vol_data = get_json("https://api.llama.fi/summary/dexs/uniswap?dataType=dailyVolume")
    fee_data = get_json("https://api.llama.fi/summary/fees/uniswap?dataType=dailyFees")
    vol_daily = parse_chart(vol_data)
    fee_daily = parse_chart(fee_data)
    vol_by_date = dict(vol_daily)
    fee_by_date = dict(fee_daily)

    # ── DEX market share ─────────────────────────────────────────────────────
    try:
        dex_daily = fetch_total_dex_daily()
        dex_by_date = dict(dex_daily)
        ms_snapshot, ms_history = compute_uni_ms(vol_by_date, dex_by_date)
    except Exception as e:
        caveats.append(f"DEX market share fetch failed: {e}")
        ms_snapshot, ms_history = None, []
    latest_vol_date = max(vol_by_date)
    latest_fee_date = max(fee_by_date)
    latest_data_date = min(latest_vol_date, latest_fee_date)

    all_dates = sorted(set(vol_by_date) & set(fee_by_date))
    latest_dates = [d for d in all_dates if d <= latest_data_date][-30:]
    latest30_vol = sum(vol_by_date[d] for d in latest_dates)
    latest30_fees = sum(fee_by_date[d] for d in latest_dates)
    recent_lp_bps = latest30_fees / latest30_vol * 10000

    cur_ym = ym(latest_data_date)
    monthly_vol = defaultdict(float)
    monthly_fee = defaultdict(float)
    for d, v in vol_daily:
        if ym(d) < cur_ym:
            monthly_vol[ym(d)] += v
    for d, v in fee_daily:
        if ym(d) < cur_ym:
            monthly_fee[ym(d)] += v
    months = sorted(k for k, v in monthly_vol.items() if k >= (2021, 1) and v > 0 and k in monthly_fee)
    last12 = months[-12:]
    trailing12_median_vol = statistics.median([monthly_vol[m] for m in last12])
    trailing12_vol = sum(monthly_vol[m] for m in last12)
    trailing12_fees = sum(monthly_fee[m] for m in last12)
    trailing12_lp_bps = trailing12_fees / trailing12_vol * 10000
    lp_fee_bps = recent_lp_bps
    base_seed = min(latest30_vol, trailing12_median_vol)

    month_vols = np.array([monthly_vol[m] for m in months], dtype=float)
    logrets = np.diff(np.log(month_vols))
    rng = np.random.default_rng(20260525)
    N = 80_000
    idx = rng.integers(0, len(logrets), size=(N, 36))
    rets = logrets[idx]
    paths = base_seed * np.exp(np.cumsum(rets, axis=1))
    y3_ttm_vol = paths[:, -12:].sum(axis=1)

    cg = get_json(
        f"{_CG_BASE}/coins/uniswap?localization=false&tickers=false"
        "&market_data=true&community_data=false&developer_data=false&sparkline=false"
    )
    md = cg["market_data"]
    spot = float(md["current_price"]["usd"])
    market_cap = float(md["market_cap"]["usd"])
    fdv = float((md.get("fully_diluted_valuation") or {}).get("usd") or 0)
    circ = float(md.get("circulating_supply") or market_cap / spot)
    max_supply = float(md.get("max_supply") or md.get("total_supply") or (fdv / spot if fdv else circ))
    if not max_supply or max_supply < circ:
        max_supply = circ

    # Discount rate: 10Y yield + UNI beta-adjusted equity premium
    try:
        tnx = get_json("https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX?range=5d&interval=1d")
        rf_pct = float(tnx["chart"]["result"][0]["meta"].get("regularMarketPrice"))
        rf = rf_pct / 100.0
    except Exception as e1:
        try:
            dgs = get_text("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10", timeout=15)
            rows = list(csv.DictReader(io.StringIO(dgs)))
            vals = [(r["observation_date"], float(r["DGS10"])) for r in rows if r.get("DGS10") not in ("", ".")]
            _, rf_pct = vals[-1]
            rf = rf_pct / 100.0
        except Exception:
            caveats.append("10Y yield fetch failed; used 4.5% fallback")
            rf_pct, rf = 4.5, 0.045

    try:
        sp_y = get_json("https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?range=1y&interval=1d")
        sp_vals = [x for x in sp_y["chart"]["result"][0]["indicators"]["quote"][0]["close"] if x is not None]
        sp_rets = np.diff(np.log(np.array(sp_vals[-366:], dtype=float)))
        sp_stdev = float(np.std(sp_rets, ddof=1))
    except Exception:
        caveats.append("S&P stdev fetch failed; used 1.0% fallback")
        sp_stdev = 0.010

    try:
        uni_hist = get_json(
            f"{_CG_BASE}/coins/uniswap/market_chart?vs_currency=usd&days=365&interval=daily"
        )
        prices = []
        seen = set()
        for ms, p in uni_hist["prices"]:
            d = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
            if d in seen:
                continue
            seen.add(d)
            prices.append(float(p))
        prices = prices[-366:]
        uni_rets = np.diff(np.log(np.array(prices)))
        uni_stdev = float(np.std(uni_rets, ddof=1))
    except Exception:
        caveats.append("UNI history fetch failed; used 7.0% daily stdev fallback")
        uni_stdev = 0.070

    DR = rf + 0.03 * (uni_stdev / sp_stdev)

    frontend_bps = 0.30
    current_lp_protocol_bps = 0.826
    current_take_bps = current_lp_protocol_bps + frontend_bps
    full_take_bps = lp_fee_bps * 0.25 + frontend_bps
    multiple = 15.0
    disc = (1 + DR) ** 3

    def value_arrays(take_bps, supply):
        gp = y3_ttm_vol * take_bps / 10000.0
        pv = gp * multiple / supply / disc
        return gp, pv

    cur_gp, cur_pv = value_arrays(current_take_bps, circ)
    full_gp, full_pv = value_arrays(full_take_bps, circ)
    _, full_pv_fdv = value_arrays(full_take_bps, max_supply)

    q = [25, 50, 75, 90]

    def qs(arr):
        return [float(np.percentile(arr, p)) for p in q]

    cur_gp_q = qs(cur_gp)
    cur_pv_q = qs(cur_pv)
    full_gp_q = qs(full_gp)
    full_pv_q = qs(full_pv)
    vol_q = qs(y3_ttm_vol)
    fdv_pv_q = qs(full_pv_fdv)

    prob_gt_spot = float(np.mean(full_pv > spot))
    prob_gt_3x = float(np.mean(full_pv > 3 * spot))

    current_ann_vol = latest30_vol * 365.0 / 30.0
    current_state_ann_gp = current_ann_vol * current_take_bps / 10000.0
    full_ann_gp = current_ann_vol * full_take_bps / 10000.0
    mcap_cur = market_cap / current_state_ann_gp
    mcap_full = market_cap / full_ann_gp

    def make_pv_dict(q_list):
        return {f"p{q[i]}": q_list[i] for i in range(len(q))}

    scenarios = [
        {
            "key": "current_state",
            "label": "Current-state economics",
            "pv": make_pv_dict(cur_pv_q),
            "ev": float(np.mean(cur_pv)),
            "prob_above_spot": float(np.mean(cur_pv > spot)),
            "prob_3x": float(np.mean(cur_pv > 3 * spot)),
            "is_primary": False,
        },
        {
            "key": "full_activation",
            "label": "Full-activation (fee switch on)",
            "pv": make_pv_dict(full_pv_q),
            "ev": float(np.mean(full_pv)),
            "prob_above_spot": prob_gt_spot,
            "prob_3x": prob_gt_3x,
            "is_primary": True,
        },
        {
            "key": "full_activation_fdv",
            "label": "Full-activation (max supply)",
            "pv": make_pv_dict(fdv_pv_q),
            "ev": float(np.mean(full_pv_fdv)),
            "prob_above_spot": float(np.mean(full_pv_fdv > spot)),
            "prob_3x": float(np.mean(full_pv_fdv > 3 * spot)),
            "is_primary": False,
        },
    ]

    result = {
        "token": "UNI",
        "name": "Uniswap",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "market": {
            "spot": spot,
            "market_cap": market_cap,
            "fdv": fdv,
            "circulating_supply": circ,
            "max_supply": max_supply,
        },
        "model": {
            "type": "3Y GP-Capture Monte Carlo",
            "discount_rate": DR,
            "multiple": multiple,
            "paths": N,
            "note": "25% fee-switch GP on LP fees + 0.30bps frontend fee; volume bootstrapped from 2021+ monthly history",
        },
        "current_gp": {
            "annualized_current_state": current_state_ann_gp,
            "annualized_full_activation": full_ann_gp,
            "lp_fee_bps_30d": lp_fee_bps,
            "take_bps_current": current_take_bps,
            "take_bps_full": full_take_bps,
            "ann_volume": current_ann_vol,
            "mcap_current_state_gp": mcap_cur,
            "mcap_full_activation_gp": mcap_full,
            # Y3 model outputs
            "y3_gp_p50":     full_gp_q[1],
            "y3_gp_p25":     full_gp_q[0],
            "y3_gp_p75":     full_gp_q[2],
            "y3_volume_p50": vol_q[1],
            "y3_volume_p25": vol_q[0],
            "y3_volume_p75": vol_q[2],
            # Market share vs total DEX volume
            **({"ms30_vs_dex":  ms_snapshot["ms30"],
                "ms90_vs_dex":  ms_snapshot["ms90"],
                "ms180_vs_dex": ms_snapshot["ms180"],
                "ms30_ms180_trend": (ms_snapshot["ms30"] / ms_snapshot["ms180"])
                                    if ms_snapshot and ms_snapshot["ms30"] and ms_snapshot["ms180"] else None,
               } if ms_snapshot else {}),
        },
        "scenarios": scenarios,
        "ms_history": ms_history,
        "caveats": caveats,
        "data_freshness": str(latest_data_date),
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "uni_result.json"), "w") as f:
        json.dump(result, f, indent=2)

    return result
