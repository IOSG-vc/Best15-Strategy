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
import time
from collections import defaultdict
from datetime import datetime, date, timezone, timedelta
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
_MS_AMPLIFIER_CAP = 1.5
_MS_DECELERATOR_FLOOR = 0.75
_MS_DECAY_MONTHS = 12
_MS_MONTHS = 36

# Blockworks annual Binance spot volume benchmark from Centralized Exchange:
# Spot Volume by Exchange. Used to scale Binance BTCUSDT spot quote volume into
# a total Binance spot denominator, mirroring the HYPE Binance Futures scaler.
BLOCKWORKS_BINANCE_SPOT_ANNUAL = {
    2022: 3_554_092_011_672.0,
    2023: 2_940_926_610_673.0,
    2024: 7_135_811_672_301.0,
    2025: 7_306_809_425_664.0,
}


def _ms_acceleration_path(months: int = _MS_MONTHS, initial: float = 1.0,
                           decay_months: int = _MS_DECAY_MONTHS) -> np.ndarray:
    """HYPE-style cumulative share multiplier from a decaying 6M share-growth amplifier."""
    initial = min(max(float(initial), _MS_DECELERATOR_FLOOR), _MS_AMPLIFIER_CAP)
    monthly_log_velocity = math.log(initial) / 6.0
    cumulative = []
    acc = 0.0
    for m in range(months):
        decay_weight = max(0.0, 1.0 - (m + 0.5) / decay_months)
        acc += monthly_log_velocity * decay_weight
        cumulative.append(math.exp(acc))
    return np.array(cumulative, dtype=float)


def _ms_eoy3(ms90: float, ms30: float, ms_anchor: float, ms_cap: float) -> float:
    """Compute model-implied EOY3 market share using momentum decay logic."""
    velocity = _share_velocity({"ms7": None, "ms30": ms30, "ms90": ms90, "ms180": ms_anchor})["velocity_capped"]
    return min(ms90 * float(_ms_acceleration_path(_MS_MONTHS, velocity)[-1]), ms_cap)


def _ms_eoy3_from_snapshot(snapshot: dict, ms_cap: float) -> float:
    """Compute model-implied EOY3 market share from a full MS snapshot."""
    if not snapshot or snapshot.get("ms90") is None:
        return 0.0
    velocity = _share_velocity(snapshot)["velocity_capped"]
    return min(float(snapshot["ms90"]) * float(_ms_acceleration_path(_MS_MONTHS, velocity)[-1]), ms_cap)


def _share_velocity(snapshot) -> dict:
    """Blend 30D/180D and 7D/30D share momentum into a monthly-equivalent velocity."""
    if not snapshot:
        return {
            "velocity_raw": 1.0,
            "velocity_capped": 1.0,
            "long_monthly_equiv": 1.0,
            "short_monthly_equiv": 1.0,
        }
    ms7 = snapshot.get("ms7")
    ms30 = snapshot.get("ms30")
    ms180 = snapshot.get("ms180") or snapshot.get("ms90")
    long_monthly = 1.0
    short_monthly = 1.0
    if ms30 and ms180 and ms180 > 0:
        long_monthly = float(ms30 / ms180) ** (30.0 / 150.0)
    if ms7 and ms30 and ms30 > 0:
        short_monthly = float(ms7 / ms30) ** (30.0 / 23.0)
    raw = 0.70 * long_monthly + 0.30 * short_monthly
    capped = min(max(raw, _MS_DECELERATOR_FLOOR), _MS_AMPLIFIER_CAP)
    return {
        "velocity_raw": float(raw),
        "velocity_capped": float(capped),
        "long_monthly_equiv": float(long_monthly),
        "short_monthly_equiv": float(short_monthly),
    }


def _backtest_signals(backtest_chart: list) -> dict:
    """Compute forward-return statistics per GOOD/NEUTRAL/BAD signal."""
    from datetime import timedelta, date as _date
    if not backtest_chart:
        return {"chart": [], "signals": {}, "latest_signal": "NEUTRAL", "last_realized_row": None}
    price_lookup = {row["date"]: row["spot"] for row in backtest_chart}
    all_dates = sorted(price_lookup)
    today = _date.fromisoformat(max(all_dates))

    def _near_price(from_str: str, offset: int):
        tgt = str(_date.fromisoformat(from_str) + timedelta(days=offset))
        best = sorted((abs((_date.fromisoformat(d) - _date.fromisoformat(tgt)).days), price_lookup[d]) for d in all_dates)
        return best[0][1] if best and best[0][0] <= 5 else None

    groups: dict = {s: {"r30": [], "r90": [], "dates": []} for s in ["GOOD", "NEUTRAL", "BAD"]}
    last_real = None
    for row in backtest_chart:
        d, sig, p0 = row["date"], row["signal"], row["spot"]
        days_ago = (today - _date.fromisoformat(d)).days
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


def fetch_total_dex_daily():
    """Fetch total DEX daily volume from DefiLlama overview; return [(date, usd_volume)]."""
    data = get_json("https://api.llama.fi/overview/dexs?dataType=dailyVolume")
    rows = []
    for ts, val in data.get("totalDataChart", []):
        if val:
            rows.append((ts_date(ts), float(val)))
    return sorted(rows)


def binance_btc_spot_daily():
    """Fetch Binance BTCUSDT spot daily quote volume from public data ZIPs."""
    import zipfile

    by_date = {}

    def ingest_zip(url):
        req = Request(url, headers={"User-Agent": UA})
        try:
            with urlopen(req, timeout=30) as r:
                content = r.read()
        except Exception:
            return
        if content[:2] != b"PK":
            return
        z = zipfile.ZipFile(io.BytesIO(content))
        name = z.namelist()[0]
        text = z.read(name).decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        for row in reader:
            if not row or row[0] == "open_time":
                continue
            try:
                open_time = int(row[0])
                quote_vol = float(row[7])
                if open_time > 10_000_000_000_000:
                    open_time = open_time // 1000
                d = datetime.fromtimestamp(open_time / 1000, tz=timezone.utc).date()
                by_date[d] = quote_vol
            except Exception:
                pass

    now = datetime.now(timezone.utc)
    y, m = 2022, 1
    while (y < now.year) or (y == now.year and m < now.month):
        url = f"https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-{y}-{m:02d}.zip"
        ingest_zip(url)
        m += 1
        if m == 13:
            y += 1
            m = 1
        time.sleep(0.03)

    d = now.replace(day=1).date()
    end = now.date() - timedelta(days=1)
    while d <= end:
        url = f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-{d:%Y-%m-%d}.zip"
        ingest_zip(url)
        d += timedelta(days=1)
        time.sleep(0.03)

    return sorted(by_date.items())


def scaled_binance_spot_daily():
    """Daily total Binance spot proxy: BTCUSDT quote volume scaled by Blockworks annual totals."""
    daily = binance_btc_spot_daily()
    annual_btc = defaultdict(float)
    for d, v in daily:
        annual_btc[d.year] += v
    shares = {
        yr: annual_btc[yr] / bw
        for yr, bw in BLOCKWORKS_BINANCE_SPOT_ANNUAL.items()
        if annual_btc.get(yr, 0) > 0 and bw > 0
    }
    if not shares:
        raise RuntimeError("Binance BTCUSDT spot share calibration failed")
    latest_share = shares[max(shares.keys())]
    scaled_daily = []
    for d, v in daily:
        share = shares.get(d.year, latest_share)
        scaled_daily.append((d, v / share))
    return scaled_daily, shares


def compute_uni_ms(vol_by_date, dex_total_by_date, history_days=365):
    """Compute MS30/MS90/MS180 for UNI vs total DEX volume; return snapshot, history, ms_full."""
    common = sorted(set(vol_by_date) & set(dex_total_by_date))
    if not common:
        return None, [], []

    uni_arr = np.array([vol_by_date.get(d, 0.0)       for d in common], dtype=float)
    dex_arr = np.array([dex_total_by_date.get(d, 0.0) for d in common], dtype=float)

    def rolling_sum(arr, w):
        cs = np.concatenate([[0.0], np.cumsum(arr)])
        out = np.full(len(arr), np.nan)
        if len(arr) >= w:
            out[w - 1:] = cs[w:] - cs[:-w]
        return out

    rs7   = rolling_sum(uni_arr, 7);   rd7   = rolling_sum(dex_arr, 7)
    rs30  = rolling_sum(uni_arr, 30);  rd30  = rolling_sum(dex_arr, 30)
    rs90  = rolling_sum(uni_arr, 90);  rd90  = rolling_sum(dex_arr, 90)
    rs180 = rolling_sum(uni_arr, 180); rd180 = rolling_sum(dex_arr, 180)

    def safe_ratio(u, d): return float(np.clip(u / d, 0, MS_CAP)) if d > 0 else None

    ms7   = safe_ratio(rs7[-1],   rd7[-1])
    ms30  = safe_ratio(rs30[-1],  rd30[-1])
    ms90  = safe_ratio(rs90[-1],  rd90[-1])
    ms180 = safe_ratio(rs180[-1], rd180[-1])

    history = []
    ms_full = []  # includes ms180 for hist_charts computation
    start = 0 if history_days is None else max(0, len(common) - history_days)
    for i, d in enumerate(common[start:], start=start):
        if np.isnan(rs30[i]) or rd30[i] <= 0:
            continue
        ms7_i   = safe_ratio(rs7[i],   rd7[i])   if not np.isnan(rs7[i])   and rd7[i]   > 0 else None
        ms30_i  = safe_ratio(rs30[i],  rd30[i])
        ms90_i  = safe_ratio(rs90[i],  rd90[i])  if not np.isnan(rs90[i])  and rd90[i]  > 0 else None
        ms180_i = safe_ratio(rs180[i], rd180[i]) if not np.isnan(rs180[i]) and rd180[i] > 0 else None
        if ms30_i is not None:
            history.append({"date": str(d), "ms30": round(ms30_i, 5),
                            "ms90": round(ms90_i, 5) if ms90_i is not None else None})
            ms_full.append({"date": str(d), "ms7": ms7_i, "ms30": ms30_i, "ms90": ms90_i, "ms180": ms180_i})

    return {"ms7": ms7, "ms30": ms30, "ms90": ms90, "ms180": ms180}, history, ms_full


def compute_eoy3_ms_history(ms_full, ms_cap=MS_CAP):
    """Build model-implied terminal share history from rolling MS30/MS90/MS180 rows."""
    out = []
    for row in ms_full:
        ms30 = row["ms30"]
        ms90 = row["ms90"]
        ms180 = row.get("ms180")
        if ms30 is None or ms90 is None:
            continue
        anchor = ms180 if ms180 is not None else ms90
        eoy3 = _ms_eoy3_from_snapshot(
            {"ms7": row.get("ms7"), "ms30": ms30, "ms90": ms90, "ms180": anchor},
            ms_cap,
        )
        out.append({
            "date": row["date"],
            "eoy3": round(eoy3, 5),
            "ms90": round(ms90, 5),
            "ms30": round(ms30, 5),
        })
    return out


def compute_uni_hist_charts(vol_by_date, fee_by_date, ms_full, price_by_date, mcap_by_date,
                             circ, DR, multiple, p50_pv):
    """Build hist_charts dict: backtest + Mcap/GP secondary chart + EOY3 DEX market share."""
    # Convert date-object keys to ISO strings
    vol_s = {str(k): v for k, v in vol_by_date.items()}
    fee_s = {str(k): v for k, v in fee_by_date.items()}

    def full_activation_take_bps(dates: list, idx: int):
        """No-lookahead fee rule: min(rolling 30D LP fee bps, trailing 12M LP fee bps)."""
        s30 = max(0, idx - 29)
        s365 = max(0, idx - 364)
        vol30 = sum(vol_s.get(dates[j], 0.0) for j in range(s30, idx + 1))
        fee30 = sum(fee_s.get(dates[j], 0.0) for j in range(s30, idx + 1))
        vol365 = sum(vol_s.get(dates[j], 0.0) for j in range(s365, idx + 1))
        fee365 = sum(fee_s.get(dates[j], 0.0) for j in range(s365, idx + 1))
        if vol30 <= 0 or vol365 <= 0:
            return None
        lp_fee_bps = min(fee30 / vol30, fee365 / vol365) * 10000.0
        return lp_fee_bps * 0.25 + 0.30

    # ── EOY3 DEX market share history ────────────────────────────────────────
    eoy3_ms_out = compute_eoy3_ms_history(ms_full, MS_CAP)

    # ── Secondary chart: Mcap / GP (full activation) over time ───────────────
    common_mc = sorted(set(vol_s) & set(fee_s) & set(mcap_by_date))
    secondary_data = []
    for i, d in enumerate(common_mc):
        s30 = max(0, i - 29)
        t_vol = sum(vol_s.get(common_mc[j], 0.0) for j in range(s30, i + 1))
        if t_vol <= 0:
            continue
        ann_vol = t_vol / 30.0 * 365.0
        full_take_bps = full_activation_take_bps(common_mc, i)
        if full_take_bps is None:
            continue
        ann_gp = ann_vol * full_take_bps / 10000.0
        mcap = mcap_by_date.get(d)
        if mcap and ann_gp > 0:
            ratio = mcap / ann_gp
            if 0 < ratio < 2000:
                secondary_data.append({"date": d, "value": round(ratio, 1)})

    # ── Backtest: model-shaped PV (no-lookahead full-activation) ─────────────
    common_bt = sorted(set(vol_s) & set(fee_s) & set(price_by_date))
    pv_raw_list = []
    for i, d in enumerate(common_bt):
        s30 = max(0, i - 29)
        t_vol = sum(vol_s.get(common_bt[j], 0.0) for j in range(s30, i + 1))
        if t_vol <= 0:
            continue
        ann_vol = t_vol / 30.0 * 365.0
        full_take_bps = full_activation_take_bps(common_bt, i)
        if full_take_bps is None:
            continue
        pv_raw = (ann_vol * full_take_bps / 10000.0) * multiple / ((1 + DR) ** 3) / circ
        price = price_by_date.get(d)
        if price and price > 0:
            pv_raw_list.append((d, pv_raw, price))

    if not pv_raw_list:
        return {"backtest": {"chart": [], "signals": {}, "latest_signal": "NEUTRAL", "last_realized_row": None},
                "secondary_chart": {"label": "Mcap / GP (full activation)", "subtitle": "",
                                    "note": "", "unit": "x", "data": secondary_data},
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
            "label": "Historical Mcap / GP (full activation)",
            "subtitle": "Market cap ÷ annualised full-activation GP",
            "note": "Rolling 30D volume with no-lookahead fee rule: min(rolling 30D LP fee bps, trailing 12M LP fee bps). Full activation = 25% LP fees + 0.30bps frontend.",
            "unit": "x",
            "data": secondary_data,
        },
        "eoy3_ms": eoy3_ms_out,
    }


def compute_binance_spot_backtest(vol_by_date, fee_by_date, binance_spot_by_date,
                                  binance_spot_full_hist, price_by_date,
                                  supply, DR, multiple, p50_pv):
    """Build current-model historical diagnostic from Binance spot denominator × UNI share."""
    vol_s = {str(k): v for k, v in vol_by_date.items()}
    fee_s = {str(k): v for k, v in fee_by_date.items()}
    binance_s = {str(k): v for k, v in binance_spot_by_date.items()}
    share_by_date = {
        row["date"]: _ms_eoy3_from_snapshot(row, MS_CAP)
        for row in binance_spot_full_hist
        if row.get("ms30") is not None and row.get("ms90") is not None
    }

    common = sorted(set(vol_s) & set(fee_s) & set(binance_s) & set(price_by_date) & set(share_by_date))
    pv_raw_list = []
    for i, d in enumerate(common):
        s30 = max(0, i - 29)
        s365 = max(0, i - 364)
        uni_vol30 = sum(vol_s.get(common[j], 0.0) for j in range(s30, i + 1))
        uni_fee30 = sum(fee_s.get(common[j], 0.0) for j in range(s30, i + 1))
        uni_vol365 = sum(vol_s.get(common[j], 0.0) for j in range(s365, i + 1))
        uni_fee365 = sum(fee_s.get(common[j], 0.0) for j in range(s365, i + 1))
        binance_vol30 = sum(binance_s.get(common[j], 0.0) for j in range(s30, i + 1))
        if uni_vol30 <= 0 or uni_vol365 <= 0 or binance_vol30 <= 0:
            continue
        lp_fee_bps = min(uni_fee30 / uni_vol30, uni_fee365 / uni_vol365) * 10000.0
        take_bps = lp_fee_bps * 0.25 + 0.30
        ann_uni_volume = binance_vol30 / 30.0 * 365.0 * share_by_date[d]
        pv_raw = (ann_uni_volume * take_bps / 10000.0) * multiple / supply / ((1 + DR) ** 3)
        price = price_by_date.get(d)
        if price and price > 0:
            pv_raw_list.append((d, pv_raw, price))

    if not pv_raw_list:
        return {"chart": [], "signals": {}, "latest_signal": "NEUTRAL", "last_realized_row": None}

    norm = (p50_pv / pv_raw_list[-1][1]) if pv_raw_list[-1][1] > 0 else 1.0
    chart = []
    for d, pv_r, price in pv_raw_list:
        pv_n = pv_r * norm
        sig = "GOOD" if pv_n / price >= 1.25 else ("BAD" if pv_n / price <= 0.75 else "NEUTRAL")
        chart.append({"date": d, "spot": round(price, 4), "pv": round(pv_n, 4), "signal": sig})
    return _backtest_signals(chart)


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
    ms_full_hist = []
    try:
        dex_daily = fetch_total_dex_daily()
        dex_by_date = dict(dex_daily)
        ms_snapshot, ms_history, ms_full_hist = compute_uni_ms(vol_by_date, dex_by_date)
    except Exception as e:
        caveats.append(f"DEX market share fetch failed: {e}")
        ms_snapshot, ms_history = None, []

    # ── Binance spot proxy market share ───────────────────────────────────────
    binance_spot_daily = []
    binance_spot_by_date = {}
    binance_spot_shares = {}
    binance_spot_snapshot = None
    binance_spot_history = []
    binance_spot_full_hist = []
    try:
        binance_spot_daily, binance_spot_shares = scaled_binance_spot_daily()
        binance_spot_by_date = dict(binance_spot_daily)
        binance_spot_snapshot, binance_spot_history, binance_spot_full_hist = compute_uni_ms(
            vol_by_date, binance_spot_by_date, history_days=None
        )
    except Exception as e:
        caveats.append(f"Binance spot proxy fetch failed: {e}")

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
    monthly_dex = defaultdict(float)
    for d, v in vol_daily:
        if ym(d) < cur_ym:
            monthly_vol[ym(d)] += v
    for d, v in fee_daily:
        if ym(d) < cur_ym:
            monthly_fee[ym(d)] += v
    if ms_snapshot:
        for d, v in dex_daily:
            if ym(d) < cur_ym:
                monthly_dex[ym(d)] += v
    else:
        monthly_dex = monthly_vol.copy()
    months = sorted(
        k for k, v in monthly_vol.items()
        if k >= (2022, 1) and v > 0 and k in monthly_fee and k in monthly_dex and monthly_dex[k] > 0
    )
    last12 = months[-12:]
    trailing12_median_vol = statistics.median([monthly_vol[m] for m in last12])
    trailing12_vol = sum(monthly_vol[m] for m in last12)
    trailing12_fees = sum(monthly_fee[m] for m in last12)
    trailing12_lp_bps = trailing12_fees / trailing12_vol * 10000
    lp_fee_bps = recent_lp_bps
    latest30_dex_vol = sum(dex_by_date.get(d, 0.0) for d in latest_dates) if ms_snapshot else latest30_vol
    trailing12_median_dex_vol = statistics.median([monthly_dex[m] for m in last12])
    base_seed = min(latest30_vol, trailing12_median_vol)

    dex_month_vols = np.array([monthly_dex[m] for m in months], dtype=float)
    logrets = np.diff(np.log(dex_month_vols))
    rng = np.random.default_rng(20260525)
    N = 80_000
    start_dex_monthly_vol = rng.choice(dex_month_vols, size=N, replace=True)
    idx = rng.integers(0, len(logrets), size=(N, 36))
    rets = logrets[idx]
    dex_paths = start_dex_monthly_vol[:, None] * np.exp(np.cumsum(rets, axis=1))
    if ms_snapshot:
        dex_velocity = _share_velocity(ms_snapshot)
        ms_momentum_initial = dex_velocity["velocity_capped"]
        share_multiplier = _ms_acceleration_path(_MS_MONTHS, ms_momentum_initial)
        uni_share_path = np.minimum(float(ms_snapshot["ms90"]) * share_multiplier, MS_CAP)
    else:
        dex_velocity = _share_velocity(None)
        ms_momentum_initial = 1.0
        uni_share_path = np.full(_MS_MONTHS, 1.0, dtype=float)
    paths = dex_paths * uni_share_path[None, :]
    y3_ttm_vol = paths[:, -12:].sum(axis=1)
    y2_ttm_vol = paths[:, 12:24].sum(axis=1)

    binance_spot_outputs = None
    if binance_spot_snapshot:
        try:
            monthly_binance_spot = defaultdict(float)
            for d, v in binance_spot_daily:
                if ym(d) < cur_ym:
                    monthly_binance_spot[ym(d)] += v
            binance_spot_months = sorted(
                k for k, v in monthly_vol.items()
                if k >= (2022, 1) and v > 0 and k in monthly_fee
                and k in monthly_binance_spot and monthly_binance_spot[k] > 0
            )
            binance_spot_month_vols = np.array([monthly_binance_spot[m] for m in binance_spot_months], dtype=float)
            binance_spot_logrets = np.diff(np.log(binance_spot_month_vols))
            if len(binance_spot_logrets) == 0:
                raise RuntimeError("insufficient Binance spot monthly return history")
            start_binance_spot_monthly_vol = rng.choice(binance_spot_month_vols, size=N, replace=True)
            spot_idx = rng.integers(0, len(binance_spot_logrets), size=(N, 36))
            spot_rets = binance_spot_logrets[spot_idx]
            binance_spot_paths = start_binance_spot_monthly_vol[:, None] * np.exp(np.cumsum(spot_rets, axis=1))
            binance_spot_velocity = _share_velocity(binance_spot_snapshot)
            binance_spot_momentum_initial = binance_spot_velocity["velocity_capped"]
            binance_spot_share_multiplier = _ms_acceleration_path(_MS_MONTHS, binance_spot_momentum_initial)
            uni_binance_spot_share_path = np.minimum(
                float(binance_spot_snapshot["ms90"]) * binance_spot_share_multiplier,
                MS_CAP,
            )
            binance_spot_uni_paths = binance_spot_paths * uni_binance_spot_share_path[None, :]
            binance_spot_outputs = {
                "start": start_binance_spot_monthly_vol,
                "y3_ttm_vol": binance_spot_uni_paths[:, -12:].sum(axis=1),
                "y2_ttm_vol": binance_spot_uni_paths[:, 12:24].sum(axis=1),
                "share_path": uni_binance_spot_share_path,
                "momentum_initial": binance_spot_momentum_initial,
                "velocity": binance_spot_velocity,
                "latest30_binance_spot_volume": sum(binance_spot_by_date.get(d, 0.0) for d in latest_dates),
                "trailing12_median_binance_spot_volume": statistics.median(
                    [monthly_binance_spot[m] for m in last12 if m in monthly_binance_spot]
                ),
                "monthly_log_return_mean": float(np.mean(binance_spot_logrets)),
                "monthly_log_return_std": float(np.std(binance_spot_logrets, ddof=1)),
            }
        except Exception as e:
            caveats.append(f"Binance spot proxy MC failed: {e}")

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

    price_by_date_hist: dict = {}
    mcap_by_date_hist: dict = {}
    supply_by_date_hist: dict = {}
    try:
        uni_hist = get_json(
            f"{_CG_BASE}/coins/uniswap/market_chart?vs_currency=usd&days=365&interval=daily"
        )
        prices = []
        seen_p: set = set()
        for ms, p in uni_hist["prices"]:
            d = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
            d_str = str(d)
            if d_str not in seen_p:
                seen_p.add(d_str)
                price_by_date_hist[d_str] = float(p)
                prices.append(float(p))
        seen_m: set = set()
        for ms, m_val in uni_hist.get("market_caps", []):
            d_str = str(datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date())
            if d_str not in seen_m:
                seen_m.add(d_str)
                mcap_by_date_hist[d_str] = float(m_val)
        for d_str, p in price_by_date_hist.items():
            m_val = mcap_by_date_hist.get(d_str)
            if p > 0 and m_val and m_val > 0:
                supply_by_date_hist[d_str] = float(m_val) / float(p)
        prices = prices[-366:]
        uni_rets = np.diff(np.log(np.array(prices)))
        uni_stdev = float(np.std(uni_rets, ddof=1))
    except Exception:
        caveats.append("UNI history fetch failed; used 7.0% daily stdev fallback")
        uni_stdev = 0.070

    DR = rf + 0.03 * (uni_stdev / sp_stdev)

    reserved_supply = max(max_supply - circ, 0.0)
    supply_hist_dates = sorted(supply_by_date_hist)
    if len(supply_hist_dates) >= 30:
        start_supply = supply_by_date_hist[supply_hist_dates[0]]
        end_supply = supply_by_date_hist[supply_hist_dates[-1]]
        hist_days = max((date.fromisoformat(supply_hist_dates[-1]) - date.fromisoformat(supply_hist_dates[0])).days, 1)
        annual_reserved_release = max((end_supply - start_supply) * 365.0 / hist_days, 0.0)
    else:
        annual_reserved_release = 0.0
    y2_reserved_release = min(reserved_supply, annual_reserved_release * 2.0)
    y3_reserved_release = min(reserved_supply, annual_reserved_release * 3.0)
    y2_effective_supply = circ + y2_reserved_release
    y3_effective_supply = circ + y3_reserved_release

    frontend_bps = 0.30
    current_lp_protocol_bps = 0.826
    current_take_bps = current_lp_protocol_bps + frontend_bps
    full_take_bps = lp_fee_bps * 0.25 + frontend_bps
    multiple = 15.0
    disc = (1 + DR) ** 3

    # Velocity scenario analysis: vary momentum-decay window (bear 6M / base 12M / bull 24M)
    # holding full-activation take and base supply fixed; reuses the already-computed dex_paths.
    _velocity_scenarios = []
    if ms_snapshot and ms_snapshot.get("ms90"):
        for _dm, _vlabel in ((6, "Bear: 6M momentum decay"), (12, "Base: 12M momentum decay"), (24, "Bull: 24M momentum decay")):
            _sp = np.minimum(float(ms_snapshot["ms90"]) * _ms_acceleration_path(_MS_MONTHS, ms_momentum_initial, _dm), MS_CAP)
            _y3_vol = (dex_paths * _sp[None, :])[:, -12:].sum(axis=1)
            _y3_gp = _y3_vol * full_take_bps / 10000.0
            _pv = _y3_gp * multiple / y3_effective_supply / disc
            _velocity_scenarios.append({
                "label": _vlabel, "decay_months": _dm,
                "y3_gp_p50": float(np.percentile(_y3_gp, 50)),
                "pv": {"p25": float(np.percentile(_pv, 25)), "p50": float(np.percentile(_pv, 50)),
                       "p75": float(np.percentile(_pv, 75))},
                "eoy3_share": float(_sp[-1]),
                "prob_above_spot": float(np.mean(_pv > spot)),
            })

    def value_arrays(vol_arr, take_bps, supply):
        gp = vol_arr * take_bps / 10000.0
        pv = gp * multiple / supply / disc
        return gp, pv

    def undiscounted_price_arrays(vol_arr, take_bps, supply):
        gp = vol_arr * take_bps / 10000.0
        price = gp * multiple / supply
        return gp, price

    cur_gp, cur_pv = value_arrays(y3_ttm_vol, current_take_bps, y3_effective_supply)
    full_gp, full_pv = value_arrays(y3_ttm_vol, full_take_bps, y3_effective_supply)
    _, full_pv_fdv = value_arrays(y3_ttm_vol, full_take_bps, max_supply)
    cur_y2_gp, cur_y2_price = undiscounted_price_arrays(y2_ttm_vol, current_take_bps, y2_effective_supply)
    full_y2_gp, full_y2_price = undiscounted_price_arrays(y2_ttm_vol, full_take_bps, y2_effective_supply)
    _, fdv_y2_price = undiscounted_price_arrays(y2_ttm_vol, full_take_bps, max_supply)
    binance_spot_gp = binance_spot_pv = None
    binance_spot_y2_gp = binance_spot_y2_price = None
    if binance_spot_outputs:
        binance_spot_gp, binance_spot_pv = value_arrays(
            binance_spot_outputs["y3_ttm_vol"], full_take_bps, y3_effective_supply
        )
        binance_spot_y2_gp, binance_spot_y2_price = undiscounted_price_arrays(
            binance_spot_outputs["y2_ttm_vol"], full_take_bps, y2_effective_supply
        )

    q = [25, 50, 75, 90]

    def qs(arr):
        return [float(np.percentile(arr, p)) for p in q]

    cur_gp_q = qs(cur_gp)
    cur_pv_q = qs(cur_pv)
    full_gp_q = qs(full_gp)
    full_pv_q = qs(full_pv)
    vol_q = qs(y3_ttm_vol)
    fdv_pv_q = qs(full_pv_fdv)
    binance_spot_gp_q = qs(binance_spot_gp) if binance_spot_gp is not None else None
    binance_spot_pv_q = qs(binance_spot_pv) if binance_spot_pv is not None else None
    binance_spot_vol_q = qs(binance_spot_outputs["y3_ttm_vol"]) if binance_spot_outputs else None

    prob_gt_spot = float(np.mean(full_pv > spot))
    prob_gt_3x = float(np.mean(full_pv > 3 * spot))

    current_ann_vol = latest30_vol * 365.0 / 30.0
    current_state_ann_gp = current_ann_vol * current_take_bps / 10000.0
    full_ann_gp = current_ann_vol * full_take_bps / 10000.0
    mcap_cur = market_cap / current_state_ann_gp
    mcap_full = market_cap / full_ann_gp

    def make_pv_dict(q_list):
        return {f"p{q[i]}": q_list[i] for i in range(len(q))}

    def make_distribution(arr):
        return {f"p{p}": float(np.percentile(arr, p)) for p in [5, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 95]}

    def make_scenario(key, label, pv_arr, gp_arr, vol_arr, supply, y2_price_arr, is_primary):
        pv_q = qs(pv_arr)
        gp_q = qs(gp_arr)
        vol_q_local = qs(vol_arr)
        y3_price_p50 = gp_q[1] * multiple / supply
        return {
            "key": key,
            "label": label,
            "pv": make_pv_dict(pv_q),
            "ev": float(np.mean(pv_arr)),
            "prob_above_spot": float(np.mean(pv_arr > spot)),
            "prob_3x": float(np.mean(pv_arr > 3 * spot)),
            "prob_spot_up_30_2y": float(np.mean(y2_price_arr > 1.30 * spot)),
            "prob_spot_down_30_2y": float(np.mean(y2_price_arr < 0.70 * spot)),
            "distribution": make_distribution(pv_arr),
            "is_primary": is_primary,
            "y3_price_p50": float(y3_price_p50),
            "y3_mcap_p50": float(y3_price_p50 * supply),
            "y3_supply_p50": float(supply),
            "y3_gp_p50": float(gp_q[1]),
            "y3_daily_mean_volume_p50": float(vol_q_local[1] / 365.0),
            "ev_mcap": float(np.mean(pv_arr) * supply),
        }

    binance_primary = binance_spot_pv is not None

    scenarios = [
        make_scenario(
            "current_state",
            "Current-state economics",
            cur_pv,
            cur_gp,
            y3_ttm_vol,
            y3_effective_supply,
            cur_y2_price,
            False,
        ),
    ]
    if binance_spot_pv is not None:
        scenarios.append(make_scenario(
            "full_activation_binance_spot",
            "Full activation · Binance spot proxy",
            binance_spot_pv,
            binance_spot_gp,
            binance_spot_outputs["y3_ttm_vol"],
            y3_effective_supply,
            binance_spot_y2_price,
            True,
        ))
    scenarios.extend([
        make_scenario(
            "full_activation",
            "Full activation · DEX-native sensitivity",
            full_pv,
            full_gp,
            y3_ttm_vol,
            y3_effective_supply,
            full_y2_price,
            not binance_primary,
        ),
        make_scenario(
            "full_activation_fdv",
            "Full activation · max-supply sensitivity",
            full_pv_fdv,
            full_gp,
            y3_ttm_vol,
            max_supply,
            fdv_y2_price,
            False,
        ),
    ])

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
            "note": "Primary case maps UNI volume to Binance spot denominator × UNI/Binance spot share, sampled from 2022-present; blended 70% MS30/MS180 + 30% MS7/MS30 velocity decays over 12M; 25% LP fee switch + 0.30bps frontend fee; Y3 effective supply includes observed reserved-supply release.",
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
            "fdv_full_activation_gp": (fdv if fdv else spot * max_supply) / full_ann_gp,
            "base_seed_monthly": base_seed,
            "start_total_dex_monthly_p50": float(np.percentile(start_dex_monthly_vol, 50)),
            "start_total_dex_monthly_p25": float(np.percentile(start_dex_monthly_vol, 25)),
            "start_total_dex_monthly_p75": float(np.percentile(start_dex_monthly_vol, 75)),
            "latest30_total_dex_volume": latest30_dex_vol,
            "trailing12_median_total_dex_volume": trailing12_median_dex_vol,
            "latest30_volume": latest30_vol,
            "trailing12_median_volume": trailing12_median_vol,
            "trailing12_lp_fee_bps": trailing12_lp_bps,
            "ms_momentum_initial": ms_momentum_initial,
            "ms_velocity_raw": dex_velocity["velocity_raw"],
            "ms_velocity_long_monthly_equiv": dex_velocity["long_monthly_equiv"],
            "ms_velocity_short_monthly_equiv": dex_velocity["short_monthly_equiv"],
            "ms_amplifier_cap": _MS_AMPLIFIER_CAP,
            "ms_decelerator_floor": _MS_DECELERATOR_FLOOR,
            "ms_momentum_decay_months": _MS_DECAY_MONTHS,
            "eoy3_share_model": float(uni_share_path[-1]),
            "reserved_supply": reserved_supply,
            "annual_reserved_supply_release": annual_reserved_release,
            "y2_effective_supply": y2_effective_supply,
            "y3_effective_supply": y3_effective_supply,
            "y3_reserved_supply_release": y3_reserved_release,
            # Y3 model outputs
            "y3_gp_p50":     full_gp_q[1],
            "y3_gp_p25":     full_gp_q[0],
            "y3_gp_p75":     full_gp_q[2],
            "y3_volume_p50": vol_q[1],
            "y3_daily_mean_volume_p50": vol_q[1] / 365.0,
            "y3_volume_p25": vol_q[0],
            "y3_volume_p75": vol_q[2],
            "y3_supply_p50": y3_effective_supply,
            # Market share vs total DEX volume
            **({"ms7_vs_dex":   ms_snapshot["ms7"],
                "ms30_vs_dex":  ms_snapshot["ms30"],
                "ms90_vs_dex":  ms_snapshot["ms90"],
                "ms180_vs_dex": ms_snapshot["ms180"],
                "ms30_ms180_trend": (ms_snapshot["ms30"] / ms_snapshot["ms180"])
                                    if ms_snapshot and ms_snapshot["ms30"] and ms_snapshot["ms180"] else None,
               } if ms_snapshot else {}),
            **(({
                "binance_spot_proxy_method": "BTCUSDT spot quote volume scaled by Blockworks annual Binance spot totals",
                "blockworks_binance_spot_annual": BLOCKWORKS_BINANCE_SPOT_ANNUAL,
                "binance_spot_btcusdt_shares": {str(k): float(v) for k, v in binance_spot_shares.items()},
                "start_binance_spot_monthly_p50": float(np.percentile(binance_spot_outputs["start"], 50)),
                "start_binance_spot_monthly_p25": float(np.percentile(binance_spot_outputs["start"], 25)),
                "start_binance_spot_monthly_p75": float(np.percentile(binance_spot_outputs["start"], 75)),
                "latest30_binance_spot_volume": binance_spot_outputs["latest30_binance_spot_volume"],
                "trailing12_median_binance_spot_volume": binance_spot_outputs["trailing12_median_binance_spot_volume"],
                "ms30_vs_binance_spot": binance_spot_snapshot["ms30"],
                "ms90_vs_binance_spot": binance_spot_snapshot["ms90"],
                "ms180_vs_binance_spot": binance_spot_snapshot["ms180"],
                "ms7_ms30_binance_spot_trend": (
                    binance_spot_snapshot["ms7"] / binance_spot_snapshot["ms30"]
                    if binance_spot_snapshot and binance_spot_snapshot.get("ms7") and binance_spot_snapshot.get("ms30")
                    and binance_spot_snapshot["ms30"] > 0
                    else None
                ),
                "ms30_ms180_binance_spot_trend": (
                    binance_spot_snapshot["ms30"] / binance_spot_snapshot["ms180"]
                    if binance_spot_snapshot and binance_spot_snapshot["ms30"] and binance_spot_snapshot["ms180"]
                    else None
                ),
                "binance_spot_momentum_initial": binance_spot_outputs["momentum_initial"],
                "binance_spot_velocity_raw": binance_spot_outputs["velocity"]["velocity_raw"],
                "binance_spot_velocity_long_monthly_equiv": binance_spot_outputs["velocity"]["long_monthly_equiv"],
                "binance_spot_velocity_short_monthly_equiv": binance_spot_outputs["velocity"]["short_monthly_equiv"],
                "binance_spot_eoy3_share_model": float(binance_spot_outputs["share_path"][-1]),
                "binance_spot_y3_volume_p50": binance_spot_vol_q[1],
                "binance_spot_y3_daily_mean_volume_p50": binance_spot_vol_q[1] / 365.0,
                "binance_spot_y3_volume_p25": binance_spot_vol_q[0],
                "binance_spot_y3_volume_p75": binance_spot_vol_q[2],
                "binance_spot_y3_gp_p50": binance_spot_gp_q[1],
                "binance_spot_y3_gp_p25": binance_spot_gp_q[0],
                "binance_spot_y3_gp_p75": binance_spot_gp_q[2],
                "binance_spot_full_activation_p50": binance_spot_pv_q[1],
                "binance_spot_full_activation_ev": float(np.mean(binance_spot_pv)),
                "binance_spot_full_activation_prob_above_spot": float(np.mean(binance_spot_pv > spot)),
            }) if binance_spot_outputs and binance_spot_pv is not None else {}),
        },
        "scenarios": scenarios,
        "velocity_scenarios": _velocity_scenarios,
        "ms_history": ms_history,
        "binance_spot_ms_history": binance_spot_history,
        "caveats": caveats,
        "data_freshness": str(latest_data_date),
    }

    # ── Historical charts (backtest / secondary / EOY3 MS) ───────────────────
    try:
        primary_scenario = next((s for s in scenarios if s.get("is_primary")), scenarios[0])
        p50_pv_uni = primary_scenario["pv"]["p50"]
        result["hist_charts"] = compute_uni_hist_charts(
            vol_by_date, fee_by_date, ms_full_hist,
            price_by_date_hist, mcap_by_date_hist,
            circ, DR, multiple, p50_pv_uni,
        )
        if binance_spot_full_hist:
            result["hist_charts"]["binance_spot_eoy3_ms"] = compute_eoy3_ms_history(
                binance_spot_full_hist, MS_CAP
            )
            result["hist_charts"]["binance_spot_backtest"] = compute_binance_spot_backtest(
                vol_by_date, fee_by_date, binance_spot_by_date,
                binance_spot_full_hist, price_by_date_hist,
                y3_effective_supply, DR, multiple, p50_pv_uni,
            )
    except Exception as _hce:
        caveats.append(f"UNI hist_charts failed: {_hce}")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "uni_result.json"), "w") as f:
        json.dump(result, f, indent=2)

    return result
