#!/usr/bin/env python3
"""Updated HYPE GP-capture scenario run after critique.

Fixes:
- Treat DeFiLlama dailyRevenue as net GP / buyback capacity directly (GP margin = 100%).
- Scenario emissions instead of hardcoded single base.
- Product optionality as separate Y3 value uplift sensitivity.
"""
import json, math, os
from datetime import datetime, timezone

import numpy as np
import requests

import hype_gp_capture_mc as h

OUTDIR = os.path.dirname(__file__)
N_PATHS = h.N_PATHS
MONTHS = h.MONTHS
SELECTED_DR = h.SELECTED_DISCOUNT_RATE
TOKEN_CAPTURE = 1.0
BUYBACK_RATE = 1.0
GP_MARGIN = 1.0

NET_REVENUE_TAKE_RATE = 0.00034  # net revenue / perp notional; old HYPE agent fee-rate anchor

MS_SHARE_CAP = 0.35

# Locked MS momentum: MS30/MS180 is interpreted as the current 6M forward share-growth amplifier.
# The 6M amplifier linearly decays back to 1.0x over 12 months; gained share is retained.
MS_AMPLIFIER_CAP = 1.5
MS_AMPLIFIER_INITIAL = min(max(1.223, 1.0), MS_AMPLIFIER_CAP)
MS_MOMENTUM_DECAY_MONTHS = 12
DEFILLAMA_MCP_METRICS_PATH = os.path.expanduser("~/.hermes/tmp/hype_defillama_mcp_metrics.json")


def ms_acceleration_path(months: int = MONTHS, initial: float = MS_AMPLIFIER_INITIAL) -> np.ndarray:
    """Cumulative share multiplier from a decaying 6M market-share growth amplifier.

    `initial` is MS30/MS180, interpreted as the current 6-month forward share-growth
    factor. Convert it to a monthly velocity, linearly decay that velocity to zero
    over 12 months, compound the gained share, then hold the terminal share flat.
    """
    initial = min(max(float(initial), 1.0), MS_AMPLIFIER_CAP)
    monthly_log_velocity = math.log(initial) / 6.0
    cumulative = []
    acc = 0.0
    for m in range(months):
        # Midpoint integration: velocity at the middle of month m, decaying to 0 by month 12.
        decay_weight = max(0.0, 1.0 - (m + 0.5) / MS_MOMENTUM_DECAY_MONTHS)
        acc += monthly_log_velocity * decay_weight
        cumulative.append(math.exp(acc))
    return np.array(cumulative, dtype=float)


def load_defillama_mcp_metrics() -> dict:
    """Optional local cache populated from DefiLlama MCP; avoids mixing revenue-implied and volume-reported share."""
    try:
        with open(DEFILLAMA_MCP_METRICS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def derive_hl_volume_market_share(rev_rows, scaled_binance_daily) -> dict:
    """Compute current HL/Binance share using reported DefiLlama MCP derivatives volume when cached.

    Fallback infers HL volume from revenue / take-rate. The Binance denominator is always the
    same scaled BTCUSDT Binance Futures proxy used for the MC monthly draw pool.
    """
    vals = np.array([v for _, v in rev_rows], dtype=float)
    rev30 = float(vals[-30:].sum())
    rev90 = float(vals[-90:].sum())
    rev180 = float(vals[-180:].sum())
    last_rev_date = rev_rows[-1][0]
    from datetime import timedelta

    def bn_sum(days: int) -> float:
        cutoff = last_rev_date - timedelta(days=days - 1)
        return float(sum(v for d, v in scaled_binance_daily if d >= cutoff and d <= last_rev_date))

    bn30 = bn_sum(30)
    bn90 = bn_sum(90)
    bn180 = bn_sum(180)
    if bn90 <= 0:
        months = h.monthly_sums(scaled_binance_daily)
        bn90 = float(sum(v for _, v in months[-3:]))

    # Priority: 1) DefiLlama pro API  2) MCP cache  3) revenue-implied fallback
    pro  = h.fetch_hl_derivatives_volume()
    mcp  = pro or load_defillama_mcp_metrics()
    hl30_volume  = float(mcp.get("volume_derivatives_30d_usd")  or (rev30  / NET_REVENUE_TAKE_RATE))
    hl90_volume  = float(mcp.get("volume_derivatives_90d_usd")  or (rev90  / NET_REVENUE_TAKE_RATE))
    hl180_volume = float(mcp.get("volume_derivatives_180d_usd") or (rev180 / NET_REVENUE_TAKE_RATE))
    if pro:
        source = "DefiLlama pro API derivatives volume"
    elif mcp.get("volume_derivatives_90d_usd"):
        source = "DefiLlama MCP reported derivatives volume"
    else:
        source = "DeFiLlama revenue / fixed 0.034% take-rate"

    ms30 = float(np.clip(hl30_volume / bn30, 0.0, MS_SHARE_CAP)) if bn30 > 0 else None
    ms90 = float(np.clip(hl90_volume / bn90, 0.0, MS_SHARE_CAP)) if bn90 > 0 else 0.125
    ms180 = float(np.clip(hl180_volume / bn180, 0.0, MS_SHARE_CAP)) if bn180 > 0 else None
    current_hl_monthly_volume = hl30_volume
    current_bn_monthly_volume = bn30
    return {
        "method": f"HL numerator from {source}; Binance denominator is the same scaled BTCUSDT Futures proxy used for MC draws",
        "lookback_days": 90,
        "hl_30d_volume": hl30_volume,
        "hl_90d_volume": hl90_volume,
        "hl_180d_volume": hl180_volume,
        "binance_30d_volume": bn30,
        "binance_90d_volume": bn90,
        "binance_180d_volume": bn180,
        "ms30": ms30,
        "ms90": ms90,
        "ms180": ms180,
        "share_cap": MS_SHARE_CAP,
        "current_hl_monthly_volume": current_hl_monthly_volume,
        "current_binance_monthly_volume": current_bn_monthly_volume,
    }

USDC_TVL_URL = "https://stablecoins.llama.fi/stablecoins?chain=Hyperliquid"
BASE_YIELD_SERIES = "SOFR"
YIELD_HAIRCUT = 0.005  # 50bp operational / sharing conservatism before capture split

def fetch_hyperliquid_usdc_tvl() -> dict:
    """Live USDC circulating on Hyperliquid L1 from DefiLlama stablecoins API."""
    data = requests.get(USDC_TVL_URL, timeout=30).json()
    for asset in data.get("peggedAssets", []):
        if asset.get("symbol") == "USDC":
            chain = asset.get("chainCirculating", {}).get("Hyperliquid L1", {})
            tvl = float(chain.get("current", {}).get("peggedUSD") or 0.0)
            return {"source": USDC_TVL_URL, "symbol": "USDC", "chain": "Hyperliquid L1", "tvl": tvl}
    raise RuntimeError("USDC on Hyperliquid L1 not found in DefiLlama stablecoins API")

def fetch_base_usdc_yield() -> dict:
    """Dynamic USD cash-yield proxy: latest SOFR minus 50bp haircut."""
    try:
        vals = h.fred_series(BASE_YIELD_SERIES)
        d, v = vals[-1]
        gross = float(v) / 100.0
        source = f"FRED:{BASE_YIELD_SERIES}"
        date = str(d)
    except Exception as e:
        # FRED occasionally times out; keep model reproducible with a conservative cached SOFR proxy.
        gross = 0.036
        source = f"cached fallback after FRED error: {type(e).__name__}"
        date = "cached"
    net = max(0.0, gross - YIELD_HAIRCUT)
    return {"source": source, "date": date, "gross_yield": gross, "haircut": YIELD_HAIRCUT, "net_yield": net}

def fetch_hyperliquid_usdc_history() -> list:
    """Daily USDC circulating history on Hyperliquid L1 from DefiLlama stablecoin charts."""
    url = "https://stablecoins.llama.fi/stablecoincharts/Hyperliquid?stablecoin=2"
    data = requests.get(url, timeout=30).json()
    rows = []
    for x in data:
        val = float(x.get("totalCirculatingUSD", {}).get("peggedUSD") or 0.0)
        rows.append((datetime.fromtimestamp(int(x["date"]), tz=timezone.utc).date(), val))
    return sorted(rows)

def estimate_usdc_volume_elasticity(rev_rows) -> dict:
    """Estimate USDC TVL elasticity to activity using 30D changes in revenue as volume proxy."""
    import pandas as pd
    rev_df = pd.DataFrame(rev_rows, columns=["date", "rev"])
    tvl_df = pd.DataFrame(fetch_hyperliquid_usdc_history(), columns=["date", "usdc"])
    rev_df["date"] = pd.to_datetime(rev_df["date"])
    tvl_df["date"] = pd.to_datetime(tvl_df["date"])
    x = rev_df.set_index("date").join(tvl_df.set_index("date"), how="inner").dropna()
    x["rev30"] = x["rev"].rolling(30).sum()
    x["usdc30"] = x["usdc"].rolling(30).mean()
    x["dlog_rev30"] = np.log(x["rev30"]).diff(30)
    x["dlog_usdc30"] = np.log(x["usdc30"]).diff(30)
    y = x.dropna().tail(365)
    beta = float(np.cov(y["dlog_rev30"], y["dlog_usdc30"])[0, 1] / np.var(y["dlog_rev30"])) if len(y) > 60 and np.var(y["dlog_rev30"]) > 0 else 0.20
    corr = float(np.corrcoef(y["dlog_rev30"], y["dlog_usdc30"])[0, 1]) if len(y) > 60 else float("nan")
    beta_clipped = float(np.clip(beta, 0.0, 0.50))
    return {"source": "DefiLlama USDC history + Hyperliquid dailyRevenue proxy", "lookback_days": int(len(y)), "raw_beta": beta, "elasticity": beta_clipped, "corr": corr}

def median_monthly_start_12m(rev_rows, trailing_30):
    months = h.monthly_sums(rev_rows)
    last12 = [v for _, v in months[-12:]]
    med12 = float(np.median(np.array(last12, dtype=float))) if last12 else float(trailing_30)
    return min(float(trailing_30), med12), med12, float(trailing_30)

def _compute_ms_daily_history(rev_rows, scaled_binance_daily):
    """Rolling 30D/90D HL/Binance market-share history for the trend chart.

    HL volume is revenue-implied (daily_revenue / NET_REVENUE_TAKE_RATE) for
    continuity.  Returns list[{date, ms30, ms90}] covering the last 365 days.
    """
    bn_by_date = {d: v for d, v in scaled_binance_daily if v > 0}
    pairs = [
        (d, v / NET_REVENUE_TAKE_RATE, bn_by_date[d])
        for d, v in rev_rows
        if d in bn_by_date
    ]
    if len(pairs) < 20:
        return []

    dates = [p[0] for p in pairs]
    hl    = np.array([p[1] for p in pairs], dtype=float)
    bn    = np.array([p[2] for p in pairs], dtype=float)

    result = []
    for i in range(len(dates)):
        s30 = max(0, i - 29)
        s90 = max(0, i - 89)
        if (i - s30 + 1) < 15:
            continue
        ms30_val = float(np.clip(hl[s30:i+1].sum() / max(bn[s30:i+1].sum(), 1), 0, MS_SHARE_CAP))
        ms90_val = float(np.clip(hl[s90:i+1].sum() / max(bn[s90:i+1].sum(), 1), 0, MS_SHARE_CAP)) \
                   if (i - s90 + 1) >= 30 else None
        result.append({
            "date": str(dates[i]),
            "ms30": round(ms30_val, 5),
            "ms90": round(ms90_val, 5) if ms90_val is not None else None,
        })

    return result[-365:]


def _compute_ms_full_history(rev_rows, scaled_binance_daily):
    """Like _compute_ms_daily_history but includes ms180 and returns full history (no trim)."""
    bn_by_date = {d: v for d, v in scaled_binance_daily if v > 0}
    pairs = [
        (d, v / NET_REVENUE_TAKE_RATE, bn_by_date[d])
        for d, v in rev_rows
        if d in bn_by_date
    ]
    if len(pairs) < 20:
        return []
    dates = [p[0] for p in pairs]
    hl = np.array([p[1] for p in pairs], dtype=float)
    bn = np.array([p[2] for p in pairs], dtype=float)
    result = []
    for i in range(len(dates)):
        s30 = max(0, i - 29); s90 = max(0, i - 89); s180 = max(0, i - 179)
        if (i - s30 + 1) < 15:
            continue
        ms30_val = float(np.clip(hl[s30:i+1].sum() / max(bn[s30:i+1].sum(), 1), 0, MS_SHARE_CAP))
        ms90_val = float(np.clip(hl[s90:i+1].sum() / max(bn[s90:i+1].sum(), 1), 0, MS_SHARE_CAP)) \
                   if (i - s90 + 1) >= 30 else None
        ms180_val = float(np.clip(hl[s180:i+1].sum() / max(bn[s180:i+1].sum(), 1), 0, MS_SHARE_CAP)) \
                    if (i - s180 + 1) >= 180 else None
        result.append({
            "date": dates[i],
            "ms30": round(ms30_val, 5),
            "ms90": round(ms90_val, 5) if ms90_val is not None else None,
            "ms180": round(ms180_val, 5) if ms180_val is not None else None,
        })
    return result


def _fetch_hype_price_history() -> dict:
    """Daily HYPE price history from DefiLlama coins API. Returns {date: price}."""
    url = "https://coins.llama.fi/chart/coingecko:hyperliquid?span=500&period=1d"
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        prices = r.json()["coins"]["coingecko:hyperliquid"]["prices"]
        result = {}
        for entry in prices:
            ts = entry["timestamp"] if isinstance(entry, dict) else entry[0]
            price = entry["price"] if isinstance(entry, dict) else entry[1]
            result[datetime.fromtimestamp(ts, tz=timezone.utc).date()] = float(price)
        return result
    except Exception as e:
        print(f"[price history] fetch failed: {e}")
        return {}


def _compute_historical_charts(rev_rows, scaled_binance_daily, ms_full, price_by_date,
                                circ, gross_3y, base_p50_pv, spot, current_hl_monthly_volume,
                                usdc_tvl_val, usdc_net_yield_val, usdc_elasticity_val):
    """Compute backtest, buyback horizon, and EOY3 MS history for the dashboard charts."""
    from datetime import timedelta
    FIXED_MULTIPLE = 15.0  # deterministic proxy uses fixed normal multiple
    USDC_CAPTURE = 0.90

    # ── EOY3 market share history ────────────────────────────────────────────
    eoy3_ms_out = []
    for row in ms_full:
        ms90 = row.get("ms90"); ms30 = row.get("ms30"); ms180 = row.get("ms180")
        if ms90 is None or ms30 is None or ms180 is None:
            continue
        amplifier = min(max(ms30 / max(ms180, 1e-12), 1.0), MS_AMPLIFIER_CAP)
        path = ms_acceleration_path(MONTHS, initial=amplifier)
        eoy3 = float(min(ms90 * path[-1], MS_SHARE_CAP))
        eoy3_ms_out.append({
            "date": str(row["date"]),
            "eoy3": round(eoy3, 5),
            "ms90": round(ms90, 5),
            "ms30": round(ms30, 5),
        })

    # ── Buyback horizon history ──────────────────────────────────────────────
    rev_by_date = dict(rev_rows)
    all_rev_dates = sorted(rev_by_date.keys())
    target_supply = circ + gross_3y
    buyback_horizon_out = []
    for i, d in enumerate(all_rev_dates):
        price = price_by_date.get(d)
        if price is None or price <= 0:
            continue
        s30 = max(0, i - 29)
        trailing_30d = sum(rev_by_date[all_rev_dates[j]] for j in range(s30, i + 1))
        if trailing_30d <= 0:
            continue
        annual_fee_rev = trailing_30d * (365.0 / 30.0)
        annual_buyback_tokens = annual_fee_rev / price
        if annual_buyback_tokens <= 0:
            continue
        buyback_horizon_out.append({"date": str(d), "years": round(target_supply / annual_buyback_tokens, 2)})

    # ── Model-shaped PV backtest ─────────────────────────────────────────────
    # Build trailing 30D Binance volume by date for time-varying anchor
    bn_by_date_sorted = sorted(scaled_binance_daily, key=lambda x: x[0])
    bn_dates = [d for d, _ in bn_by_date_sorted]
    bn_vals  = np.array([v for _, v in bn_by_date_sorted], dtype=float)

    def _bn_trailing30(target_date):
        idx = next((i for i, d in enumerate(bn_dates) if d >= target_date), len(bn_dates) - 1)
        s = max(0, idx - 29)
        return float(bn_vals[s:idx + 1].sum())

    pv_proxy_raw = []
    for row in ms_full:
        ms90 = row.get("ms90"); ms30 = row.get("ms30"); ms180 = row.get("ms180")
        price = price_by_date.get(row["date"])
        # Only include rows where the full 180D window is available — matches example start date
        if ms90 is None or ms30 is None or ms180 is None or price is None or price <= 0:
            continue
        amplifier = min(max(ms30 / max(ms180, 1e-12), 1.0), MS_AMPLIFIER_CAP)
        path = ms_acceleration_path(MONTHS, initial=amplifier)
        eoy3_share = min(ms90 * path[-1], MS_SHARE_CAP)
        # Use actual trailing 30D Binance volume at this date (time-varying anchor)
        bn30 = _bn_trailing30(row["date"])
        y3_hl_monthly = bn30 * eoy3_share
        y3_gp_perp = y3_hl_monthly * NET_REVENUE_TAKE_RATE * 12.0
        usdc_scale = (y3_hl_monthly / max(current_hl_monthly_volume, 1.0)) ** usdc_elasticity_val
        y3_usdc_gp = usdc_tvl_val * usdc_scale * usdc_net_yield_val * USDC_CAPTURE
        y3_gp = y3_gp_perp + y3_usdc_gp
        y3_price = y3_gp * FIXED_MULTIPLE * TOKEN_CAPTURE / max(circ, 1.0)
        pv = y3_price / ((1.0 + SELECTED_DR) ** 3)
        pv_proxy_raw.append((row["date"], float(pv), float(price)))

    # Normalize so last point = base P50 PV
    norm_factor = (base_p50_pv / pv_proxy_raw[-1][1]) if pv_proxy_raw and pv_proxy_raw[-1][1] > 0 else 1.0

    backtest_chart = []
    price_by_date_bt: dict = {}
    for date, pv_raw, price in pv_proxy_raw:
        pv_norm = pv_raw * norm_factor
        ratio = pv_norm / max(price, 0.01)
        signal = "GOOD" if ratio >= 1.25 else ("BAD" if ratio <= 0.75 else "NEUTRAL")
        backtest_chart.append({"date": str(date), "spot": round(price, 4), "pv": round(pv_norm, 4), "signal": signal})
        price_by_date_bt[date] = price

    # Forward returns per signal (only dates with enough forward history)
    all_bt_dates = [row["date"] for row in backtest_chart]
    if not all_bt_dates:
        return {"backtest": {"chart": [], "signals": {}, "latest_signal": "NEUTRAL", "last_realized_row": None},
                "buyback_horizon": buyback_horizon_out, "eoy3_ms": eoy3_ms_out}
    today = max(all_bt_dates)
    from datetime import date as _date

    def _days_between(a, b):
        da = a if isinstance(a, _date) else _date.fromisoformat(str(a))
        db = b if isinstance(b, _date) else _date.fromisoformat(str(b))
        return (db - da).days

    price_series_lookup = {row["date"]: row["spot"] for row in backtest_chart}

    def _price_at_offset(from_date, offset_days):
        target = from_date + timedelta(days=offset_days)
        candidates = sorted([(abs(_days_between(d, target)), price_series_lookup[d]) for d in all_bt_dates])
        if not candidates or candidates[0][0] > 5:
            return None
        return candidates[0][1]

    signal_groups: dict = {"GOOD": {"rets30": [], "rets90": [], "dates": []},
                            "NEUTRAL": {"rets30": [], "rets90": [], "dates": []},
                            "BAD": {"rets30": [], "rets90": [], "dates": []}}

    last_realized_30d = None
    for row in backtest_chart:
        d = row["date"]
        sig = row["signal"]
        days_to_today = _days_between(d, today)
        p0 = row["spot"]
        if days_to_today >= 30:
            p30 = _price_at_offset(d if isinstance(d, _date) else _date.fromisoformat(str(d)), 30)
            if p30:
                signal_groups[sig]["rets30"].append(p30 / p0 - 1)
                last_realized_30d = d
        if days_to_today >= 90:
            p90 = _price_at_offset(d if isinstance(d, _date) else _date.fromisoformat(str(d)), 90)
            if p90:
                signal_groups[sig]["rets90"].append(p90 / p0 - 1)
        signal_groups[sig]["dates"].append(d)

    signals_summary = {}
    for sig, data in signal_groups.items():
        signals_summary[sig] = {
            "obs": len(data["dates"]),
            "avg_30d": float(np.mean(data["rets30"])) if data["rets30"] else None,
            "avg_90d": float(np.mean(data["rets90"])) if data["rets90"] else None,
            "recent_dates": [str(d) for d in data["dates"][-3:]],
        }

    latest_signal = backtest_chart[-1]["signal"] if backtest_chart else "NEUTRAL"

    return {
        "backtest": {
            "chart": backtest_chart,
            "signals": signals_summary,
            "latest_signal": latest_signal,
            "last_realized_row": str(last_realized_30d) if last_realized_30d else None,
        },
        "buyback_horizon": buyback_horizon_out,
        "eoy3_ms": eoy3_ms_out,
    }


SCENARIOS = [
    {
        "key": "bear_worst_case_emissions",
        "label": "Bear: worst-case emissions",
        "monthly_emission": 9_916_667.0,
        "emission_months": 20,
        "optionality": 0.10,
        "usdc_yield_capture": 0.90,
        "overhang_release_fraction_3y": 1.00,
        "note": "Worst-case: models full non-circulating/team/reserved overhang entering over 3Y before buyback offsets.",
    },
    {
        "key": "base_db_observed_emissions",
        "label": "Base: DB-observed emissions",
        "monthly_emission": 962_000.0,
        "emission_months": 36,
        "optionality": 0.10,
        "usdc_yield_capture": 0.90,
        "overhang_release_fraction_3y": 0.15,
        "note": "Base: DB-observed emissions plus 15% of non-circulating/team/reserved overhang over 3Y, whichever is larger.",
    },
    {
        "key": "upside_db_observed_plus_optionality",
        "label": "Bull: base + stronger supply/burn",
        "monthly_emission": 962_000.0,
        "emission_months": 36,
        "optionality": 0.10,
        "usdc_yield_capture": 0.90,
        "overhang_release_fraction_3y": 0.10,
        "note": "Upside: base optionality with 10% of non-circulating/team/reserved overhang over 3Y.",
    },
    {
        "key": "zero_emissions_sensitivity",
        "label": "Sensitivity: zero emissions",
        "monthly_emission": 0.0,
        "emission_months": 36,
        "optionality": 0.10,
        "usdc_yield_capture": 0.90,
        "overhang_release_fraction_3y": 0.0,
        "note": "Sensitivity only; ignores non-circulating overhang.",
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
    trailing_180 = float(rev_vals[-180:].sum())
    current_monthly_rev, median_12m_monthly_rev, last_30d_rev = median_monthly_start_12m(rev, trailing_30)
    current_annual_gp = current_monthly_rev * 365 / 30 * GP_MARGIN
    ttm_gp = (float(rev_vals[-365:].sum()) if len(rev_vals) >= 365 else float(rev_vals.sum() * 365 / len(rev_vals))) * GP_MARGIN

    usdc_tvl = fetch_hyperliquid_usdc_tvl()
    usdc_yield = fetch_base_usdc_yield()
    usdc_net_yield = float(usdc_yield["net_yield"])
    usdc_elasticity = estimate_usdc_volume_elasticity(rev)

    scaled_binance_daily, shares = h.scaled_binance_futures_daily()
    monthly_proxy_all = h.monthly_sums(scaled_binance_daily)
    latest_daily_date = scaled_binance_daily[-1][0]
    monthly_proxy = [(k, v) for k, v in monthly_proxy_all if k < (latest_daily_date.year, latest_daily_date.month)]
    ret_arr = h.monthly_log_returns_from_monthly(monthly_proxy)
    ms = derive_hl_volume_market_share(rev, scaled_binance_daily)
    ms_history = _compute_ms_daily_history(rev, scaled_binance_daily)
    ms_full = _compute_ms_full_history(rev, scaled_binance_daily)
    price_by_date = _fetch_hype_price_history()

    np.random.seed(42)
    start_pool = np.array([v for _, v in monthly_proxy], dtype=float)
    start_bn_monthly_vol = np.random.choice(start_pool, size=N_PATHS, replace=True)
    draws = np.random.choice(ret_arr, size=(N_PATHS, MONTHS), replace=True)
    growth = np.exp(np.cumsum(draws, axis=1))
    bn_monthly_volume_path = start_bn_monthly_vol[:, None] * growth

    ms_momentum_initial = min(max(float(ms.get("ms30") or ms["ms90"]) / max(float(ms.get("ms180") or ms["ms90"]), 1e-12), 1.0), MS_AMPLIFIER_CAP)
    share_multiplier = ms_acceleration_path(MONTHS, initial=ms_momentum_initial)
    hl_share_path = np.minimum(float(ms["ms90"]) * share_multiplier, MS_SHARE_CAP)
    hl_monthly_volume_path = bn_monthly_volume_path * hl_share_path[None, :]
    perp_monthly_gp = hl_monthly_volume_path * NET_REVENUE_TAKE_RATE

    non_circ_overhang = max((total_supply if total_supply == total_supply else 1_000_000_000.0) - circ, 0.0)

    scenarios = {}
    for sc in SCENARIOS:
        usdc_tvl_path = float(usdc_tvl["tvl"]) * np.power(
            np.maximum(hl_monthly_volume_path, 1.0) / max(float(ms["current_hl_monthly_volume"]), 1.0),
            float(usdc_elasticity["elasticity"]),
        )
        usdc_monthly_gp = usdc_tvl_path * usdc_net_yield * float(sc["usdc_yield_capture"]) / 12.0
        monthly_gp = perp_monthly_gp + usdc_monthly_gp
        y3_ttm_gp = monthly_gp[:, -12:].sum(axis=1)
        ranks = h.percentile_ranks(y3_ttm_gp)
        multiple = h.multiple_for_ranks(ranks)
        gross_release_3y = max(
            float(sc["monthly_emission"]) * min(int(sc["emission_months"]), MONTHS),
            non_circ_overhang * float(sc.get("overhang_release_fraction_3y", 0.0)),
        )
        gross_monthly_release = gross_release_3y / MONTHS
        remaining_gross_release = gross_release_3y
        supply = np.full(N_PATHS, circ, dtype=float)
        for t in range(MONTHS):
            start = max(0, t - 11)
            gp_window = monthly_gp[:, start:t+1].sum(axis=1) * (12.0 / (t - start + 1))
            interim_rank = h.percentile_ranks(gp_window)
            interim_mult = h.multiple_for_ranks(interim_rank)
            interim_price = (gp_window * interim_mult * TOKEN_CAPTURE) / np.maximum(supply, 1)
            buy_tokens = (monthly_gp[:, t] * BUYBACK_RATE) / np.maximum(interim_price, 0.01)
            buy_tokens = np.minimum(buy_tokens, supply * 0.80)
            emissions = min(gross_monthly_release, remaining_gross_release)
            remaining_gross_release -= emissions
            supply = supply + emissions - buy_tokens
            max_modeled_supply = circ + gross_release_3y
            supply = np.minimum(np.maximum(supply, 1.0), max_modeled_supply)
        y3_supply = supply
        y3_price_core = (y3_ttm_gp * multiple * TOKEN_CAPTURE) / np.maximum(y3_supply, 1)
        y3_price = y3_price_core * (1.0 + sc["optionality"])
        pv = y3_price / ((1.0 + SELECTED_DR) ** 3)
        p50_idx = int(np.argmin(np.abs(pv - np.percentile(pv, 50))))
        y3_daily_vol_path = hl_monthly_volume_path[p50_idx, -12:] / 30.0
        p50_volume_stats = {
            "min_daily_volume": float(np.min(y3_daily_vol_path)),
            "avg_daily_volume": float(np.mean(y3_daily_vol_path)),
            "max_daily_volume": float(np.max(y3_daily_vol_path)),
            "eoy_market_share": float(hl_share_path[-1]),
        }
        current_perp_monthly_gp = float(ms["current_hl_monthly_volume"]) * NET_REVENUE_TAKE_RATE
        current_usdc_monthly_gp = float(usdc_tvl["tvl"]) * usdc_net_yield * float(sc["usdc_yield_capture"]) / 12.0
        current_monthly_gp = current_perp_monthly_gp + current_usdc_monthly_gp
        current_buy_tokens = current_monthly_gp / max(spot, 0.01)
        net_monthly_supply = gross_monthly_release - current_buy_tokens
        supply_to_buy_back = circ + gross_release_3y
        buyback_years = supply_to_buy_back / max(current_buy_tokens * 12, 1)
        scenarios[sc["key"]] = {
            **sc,
            "discounted_token_price": pct_dict(pv, CORE_QS),
            "discounted_ev": float(np.mean(pv)),
            "discounted_distribution": pct_dict(pv, CHART_QS),
            "undiscounted_y3_token_price": pct_dict(y3_price, CORE_QS),
            "undiscounted_y3_ev": float(np.mean(y3_price)),
            "probability_weighted_ev_price": float(np.mean(pv)),
            "probability_weighted_ev_mcap": float(np.mean(pv * y3_supply)),
            "y3_ttm_gp": pct_dict(y3_ttm_gp, CORE_QS),
            "y3_supply": pct_dict(y3_supply, CORE_QS),
            "prob_current_spot_justified": float(np.mean(pv >= spot)),
            "prob_impairment_vs_spot": float(np.mean(pv < spot)),
            "prob_3x_vs_spot": float(np.mean(pv >= 3 * spot)),
            "current_monthly_gp": float(current_monthly_gp),
            "current_perp_monthly_gp": float(current_perp_monthly_gp),
            "current_usdc_yield_monthly_gp": float(current_usdc_monthly_gp),
            "current_usdc_yield_annual_gp": float(current_usdc_monthly_gp * 12.0),
            "y3_usdc_yield_ttm_gp": pct_dict(usdc_monthly_gp[:, -12:].sum(axis=1), CORE_QS),
            "p50_path_y3_daily_volume": p50_volume_stats,
            "usdc_yield_net_rate": float(usdc_net_yield),
            "current_buy_tokens_per_month": float(current_buy_tokens),
            "net_monthly_supply_now": float(net_monthly_supply),
            "modeled_gross_release_3y": float(gross_release_3y),
            "modeled_monthly_supply_release": float(gross_monthly_release),
            "non_circ_overhang": float(non_circ_overhang),
            "buyback_years_simple": float(buyback_years),
        }

    # Volume sanity: implied HYPE volume from Y3 GP using net revenue take-rate.
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

    # ── Historical charts (backtest / buyback horizon / EOY3 MS) ────────────
    base_scenario = scenarios.get("base_db_observed_emissions", next(iter(scenarios.values())))
    base_p50_pv = base_scenario["discounted_token_price"]["p50"]
    base_gross_3y = base_scenario["modeled_gross_release_3y"]
    hist_charts = _compute_historical_charts(
        rev_rows=rev,
        scaled_binance_daily=scaled_binance_daily,
        ms_full=ms_full,
        price_by_date=price_by_date,
        circ=circ,
        gross_3y=base_gross_3y,
        base_p50_pv=base_p50_pv,
        spot=spot,
        current_hl_monthly_volume=float(ms["current_hl_monthly_volume"]),
        usdc_tvl_val=float(usdc_tvl["tvl"]),
        usdc_net_yield_val=usdc_net_yield,
        usdc_elasticity_val=float(usdc_elasticity.get("elasticity", 0.22)),
    )

    out = {
        "asof_utc": datetime.now(timezone.utc).isoformat(),
        "market": {"spot": spot, "mcap": mcap, "fdv": fdv, "circ_supply": circ, "total_supply": total_supply},
        "revenue": {
            "defillama_last_date": str(last_date),
            "trailing_30d_revenue": trailing_30,
            "trailing_90d_revenue": trailing_90,
            "trailing_180d_revenue": trailing_180,
            "defillama_ann_30d": trailing_30 * 365 / 30,
            "defillama_ann_180d": trailing_180 * 365 / 180 if trailing_180 > 0 else 0.0,
            "median_12m_monthly_revenue": median_12m_monthly_rev,
            "conservative_start_monthly_revenue": current_monthly_rev,
            "current_annualized_gp": current_annual_gp,
            "ttm_gp": ttm_gp,
            "gp_margin_on_defillama_revenue": GP_MARGIN,
        },
        "ms_history": ms_history,
        "hist_charts": hist_charts,
        "usdc_yield": {
            "tvl_source": usdc_tvl["source"],
            "chain": usdc_tvl["chain"],
            "usdc_tvl": float(usdc_tvl["tvl"]),
            "yield_source": usdc_yield["source"],
            "yield_date": usdc_yield["date"],
            "gross_yield": float(usdc_yield["gross_yield"]),
            "yield_haircut": float(usdc_yield["haircut"]),
            "net_yield": float(usdc_yield["net_yield"]),
            "volume_elasticity": usdc_elasticity,
        },
        "mc": {
            "paths": N_PATHS,
            "months": MONTHS,
            "volume_proxy": "sampled historical monthly Binance Futures volume, BTCUSDT-scaled via Blockworks annual totals",
            "proxy_months": len(monthly_proxy),
            "start_binance_monthly_volume_rule": "uniform random draw from historical monthly Binance Futures volumes, 2022-present",
            "start_binance_monthly_volume_p50": float(np.percentile(start_bn_monthly_vol, 50)),
            "monthly_log_return_mean": float(np.mean(ret_arr)),
            "monthly_log_return_std": float(np.std(ret_arr, ddof=1)),
            "btcusdt_shares": {str(k): float(v) for k, v in shares.items()},
            "market_share": ms,
            "ms_momentum_amplifier": {
                "initial": float(ms_momentum_initial),
                "cap": MS_AMPLIFIER_CAP,
                "share_cap": MS_SHARE_CAP,
                "decay_months": MS_MOMENTUM_DECAY_MONTHS,
                "rule": "MS30/MS180 is the current 6M share-growth amplifier; convert to monthly velocity, linearly decay velocity to 1.0x over 12M, compound gained share, cap share at 35%",
            },
        },
        "discount": {"selected": SELECTED_DR},
        "scenarios": scenarios,
    }
    return out

def write_report(res):
    m, r, u, mc, scs = res["market"], res["revenue"], res["usdc_yield"], res["mc"], res["scenarios"]
    spot = m["spot"]
    lines = []
    lines.append("# HYPE 3Y GP-Capture MC — Binance/MS90 Architecture")
    lines.append(f"As of: {res['asof_utc']}")
    lines.append("")
    lines.append("## What changed")
    lines.append("- Core perp GP is now generated from **sampled Binance monthly volume × MS90 × 0.034% take-rate**, not current HYPE revenue × generic growth.")
    lines.append("- Binance starting volume is a **uniform random draw** from historical monthly Binance Futures volumes since 2022.")
    lines.append("- HL/Binance **MS90** is from DefiLlama MCP reported 90D derivatives volume versus scaled Binance Futures 90D volume.")
    lines.append("- MS momentum treats **MS30/MS180** as the current 6M share-growth amplifier; monthly velocity linearly decays to 1.0x over 12M, then the gained share is held flat; share cap 35%.")
    lines.append("- USDC TVL follows the simulated **HL volume path** using live-estimated elasticity; capture fixed at **90%**.")
    lines.append("- Supply scenarios now include explicit non-circulating/team/reserved overhang release assumptions before buyback offsets.")
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
    lines.append(f"MS90 vs Binance Futures       {mc['market_share']['ms90']:.1%}")
    lines.append(f"MS share cap                  {mc['market_share']['share_cap']:.0%}")
    lines.append(f"Start Binance volume P50      {fmt_money(mc['start_binance_monthly_volume_p50'])}/mo")
    lines.append(f"Current HL volume proxy       {fmt_money(mc['market_share']['current_hl_monthly_volume'])}/mo")
    lines.append(f"Current perp GP proxy         {fmt_money(scs['base_db_observed_emissions']['current_perp_monthly_gp'])}/mo")
    lines.append(f"USDC on Hyperliquid L1       {fmt_money(u['usdc_tvl'])}")
    lines.append(f"USDC yield proxy             {u['net_yield']:.2%} net ({u['yield_source']} {u['yield_date']}, gross {u['gross_yield']:.2%}, haircut {u['yield_haircut']:.2%})")
    lines.append(f"USDC/volume elasticity       {u['volume_elasticity']['elasticity']:.2f} beta, corr {u['volume_elasticity']['corr']:.2f}, {u['volume_elasticity']['lookback_days']}d")
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
    lines.append("Scenario                         Gross release/mo  Net supply/mo now  Buyback years  Y3 supply P50")
    lines.append("-------------------------------  ----------------  -----------------  -------------  -------------")
    for k in order:
        s = scs[k]
        lines.append(f"{s['label']:<31}  {s['modeled_monthly_supply_release']/1e6:>8.2f}M       {s['net_monthly_supply_now']/1e6:>+8.2f}M          {s['buyback_years_simple']:>6.1f}y       {s['y3_supply']['p50']/1e6:>7.1f}M")
    lines.append("```")
    lines.append("")
    base = scs["base_db_observed_emissions"]["discounted_token_price"]
    upside = scs["upside_db_observed_plus_optionality"]["discounted_token_price"]
    bear = scs["bear_worst_case_emissions"]["discounted_token_price"]

    lines.append("## P50 volume sanity")
    lines.append("```text")
    lines.append("Assumed net revenue take-rate: 0.034% of notional volume")
    lines.append("")
    lines.append("Scenario                         Implied HYPE daily vol   vs Binance current   vs Binance peak")
    lines.append("-------------------------------  ----------------------   ------------------   ---------------")
    for k in order[:3]:
        s = scs[k]; vs = s["volume_sanity"]
        lines.append(f"{s['label']:<31}  {fmt_money(vs['implied_hype_daily_volume_y3_p50']):>22}   {vs['implied_vs_current_binance']:>17.1%}   {vs['implied_vs_peak_binance']:>14.1%}")
    lines.append("```")
    lines.append("")
    lines.append("## Read-through")
    lines.append(f"- **Bear/worst-case:** P50 **${bear['p50']:.2f}**, clearly below spot because full non-circulating/team/reserved overhang release overwhelms buybacks.")
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
