"""SPK (Spark) webapp valuation agent — Sky-ecosystem capital-allocator GP-capture.

Reference model: SKY. Spark is a Sky subDAO / onchain capital allocator that borrows
USDS from Sky at the Sky Savings Rate and deploys it across three products:
  - SparkLend            (stablecoin lending market)
  - Spark Liquidity Layer (SLL — deploys capital across DeFi/CeFi/RWA)
  - Spark Savings         (sUSDS — savings payout is a COST line, not income)

Engine is the lending/yield-basket × share architecture shared with Morpho/SKY:
  denominator   = lending/yield TVL basket (Spark's components live inside it)
  Spark TVL     = denominator x Spark share (MS90 seed + decaying velocity, capped)
  gross income  = Spark TVL x gross-income-yield (SparkLend interest + SLL yield / TVL)
  GP            = gross income x NET MARGIN retained by the Spark DAO / staked SPK

The "net margin" is the spread Spark keeps after paying Sky's cost of capital and the
Spark Savings Rate to sUSDS holders. Anchored to Q1'26 actuals (net returns ~22% of gross,
net surplus ~11%): scenarios 12% (conservative) / 20% (base, PRIMARY) / 28% (bull).

GP-capture: PV / SPK = Y3 TTM GP P50 x 10x / supply / (1+DR)^3. Only ~30% of the 10B
SPK supply circulates, so the 3Y model uses near-fully-diluted supply (heavy overhang).
Basket return distribution is locked in spark_research_extra.json; Spark's own TVL/fees/
supply/price are fetched live (DefiLlama + CoinGecko).
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import urllib.request
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

import numpy as np

_MS_AMPLIFIER_CAP = 1.5
_MS_DECAY_MONTHS = 12
_MS_MONTHS = 36
_VELOCITY_LONG_WEIGHT = 0.70
_VELOCITY_SHORT_WEIGHT = 0.30
_MAX_MONTHLY_LOG_VELOCITY = math.log(_MS_AMPLIFIER_CAP) / 6.0
_SPARK_SHARE_CAP = 0.35

HORIZON_MONTHS = 36
PATHS = 100_000
SEED = 42
GP_MULTIPLE = 10.0   # modest: thin/declining margin, Points-only staking, buyback returns tokens to treasury (not burned). Review band 8-12x; market ~7x

NET_MARGIN_CONSERVATIVE = 0.12   # ≈ net protocol surplus margin (Q1'26 actuals)
NET_MARGIN_BASE = 0.20           # PRIMARY ≈ net protocol returns margin (~22% of gross, Q1'26)
NET_MARGIN_BULL = 0.28

MONTHLY_GROWTH_CAP_LOW = -0.08
MONTHLY_GROWTH_CAP_HIGH = 0.10
GROWTH_DAMPENER = 0.65

BUNDLE_ROOT = Path(__file__).parent.parent.parent
EXTRA_PATH = BUNDLE_ROOT / "spark_research_extra.json"
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")

UA = "Mozilla/5.0 Spark valuation"
_CG_KEY = os.environ.get("COINGECKO_API_KEY", "")
_CG_BASE = "https://pro-api.coingecko.com/api/v3" if _CG_KEY else "https://api.coingecko.com/api/v3"

_SPARK_SLUGS = ["sparklend", "spark-liquidity-layer", "spark-savings"]
_SPARK_FEE_SLUGS = ["sparklend", "spark-liquidity-layer"]   # Savings payout is a cost, not income

# Locked fallbacks (2026-06-30)
_FALLBACK_SPOT = 0.01718244
_FALLBACK_MCAP = 52161515.0
_FALLBACK_FDV = 171824432.0
_FALLBACK_CIRC = 3035744936.227
_FALLBACK_MAX_SUPPLY = 1.0e10
_FALLBACK_TVL = 3411075353.0 + 2000952701.0 + 1556112100.0
_FALLBACK_GROSS_YIELD = 0.0199


def _get_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    if _CG_KEY and "coingecko.com" in url:
        req.add_header("x-cg-pro-api-key", _CG_KEY)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _get_text(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def _ms_velocity_path(months: int = _MS_MONTHS, monthly_log_velocity: float = 0.0) -> np.ndarray:
    monthly_log_velocity = min(max(float(monthly_log_velocity), 0.0), _MAX_MONTHLY_LOG_VELOCITY)
    cumulative, acc = [], 0.0
    for m in range(months):
        decay_weight = max(0.0, 1.0 - (m + 0.5) / _MS_DECAY_MONTHS)
        acc += monthly_log_velocity * decay_weight
        cumulative.append(math.exp(acc))
    return np.array(cumulative, dtype=float)


def _velocity_ensemble(ms7: float | None, ms30: float, ms180: float | None) -> dict:
    long_raw = float(ms30) / max(float(ms180 or ms30), 1e-12)
    short_raw = float(ms7 or ms30) / max(float(ms30), 1e-12)
    long_monthly = min(max(math.log(max(long_raw, 1.0)) / 6.0, 0.0), _MAX_MONTHLY_LOG_VELOCITY)
    short_monthly = min(max(math.log(max(short_raw, 1.0)), 0.0), _MAX_MONTHLY_LOG_VELOCITY)
    monthly = (_VELOCITY_LONG_WEIGHT * long_monthly) + (_VELOCITY_SHORT_WEIGHT * short_monthly)
    return {"monthly_log_velocity": monthly, "long_raw": long_raw, "short_raw": short_raw,
            "long_monthly": long_monthly, "short_monthly": short_monthly,
            "long_weight": _VELOCITY_LONG_WEIGHT, "short_weight": _VELOCITY_SHORT_WEIGHT,
            "monthly_cap": _MAX_MONTHLY_LOG_VELOCITY}


def _ms_eoy3(ms90: float, ms30: float, ms_anchor: float, ms_cap: float, ms7: float | None = None) -> float:
    v = _velocity_ensemble(ms7, ms30, ms_anchor)
    return min(ms90 * float(_ms_velocity_path(_MS_MONTHS, v["monthly_log_velocity"])[-1]), ms_cap)


def _rolling_mean(arr: np.ndarray, w: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    for i in range(w - 1, len(arr)):
        window = arr[i - w + 1: i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) > 0:
            out[i] = float(valid.mean())
    return out


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
                   "recent_dates": g["dates"][-3:]} for s, g in groups.items()}
    return {"chart": backtest_chart, "signals": signals,
            "latest_signal": backtest_chart[-1]["signal"], "last_realized_row": last_real}


def _load_growth_distribution() -> np.ndarray:
    j = json.loads(EXTRA_PATH.read_text())
    rets = np.array(j["lending_universe_log_returns"], dtype=float)
    return np.clip(rets * GROWTH_DAMPENER, MONTHLY_GROWTH_CAP_LOW, MONTHLY_GROWTH_CAP_HIGH)


def _load_basket_monthly() -> tuple[list[str], np.ndarray]:
    j = json.loads(EXTRA_PATH.read_text())
    return [str(m) for m in j["lending_universe_months"]], np.array(j["lending_universe_tvl"], dtype=float)


def _load_discount_fallback() -> float:
    try:
        return float(json.loads(EXTRA_PATH.read_text())["discount"]["formula_discount"])
    except Exception:
        return 0.25


def _load_supply_schedule() -> dict | None:
    """Real published vesting/emission curve (monthly outstanding supply, 0..36M from now)."""
    try:
        return json.loads(EXTRA_PATH.read_text()).get("supply_schedule")
    except Exception:
        return None


def _fetch_combined_tvl_history() -> list[dict]:
    """Daily combined Spark TVL = sum of SparkLend + SLL + Spark Savings, aligned by date."""
    by_date: dict[str, float] = {}
    for slug in _SPARK_SLUGS:
        try:
            d = _get_json(f"https://api.llama.fi/protocol/{slug}")
        except Exception:
            continue
        seen = set()
        for pt in d.get("tvl", []):
            ts, val = pt.get("date"), pt.get("totalLiquidityUSD")
            if ts is None or val is None:
                continue
            ds = str(datetime.fromtimestamp(int(ts), tz=timezone.utc).date())
            if ds in seen:
                continue
            seen.add(ds)
            by_date[ds] = by_date.get(ds, 0.0) + float(val)
    rows = [{"date": d, "tvl": v} for d, v in sorted(by_date.items())]
    return rows


def _fetch_combined_fees_daily() -> dict:
    """Daily combined Spark gross income = SparkLend interest + SLL yield (Savings excluded)."""
    out: dict[str, float] = {}
    for slug in _SPARK_FEE_SLUGS:
        try:
            d = _get_json(f"https://api.llama.fi/summary/fees/{slug}?dataType=dailyFees")
        except Exception:
            continue
        for ts, val in d.get("totalDataChart", []):
            if val is None:
                continue
            ds = str(datetime.fromtimestamp(int(ts), tz=timezone.utc).date())
            out[ds] = out.get(ds, 0.0) + float(val)
    return out


def _fetch_cg_market():
    cg = _get_json(f"{_CG_BASE}/coins/spark-2?localization=false&tickers=false"
                   "&market_data=true&community_data=false&developer_data=false&sparkline=false")
    md = cg["market_data"]
    spot = float(md["current_price"]["usd"])
    mcap = float(md["market_cap"]["usd"])
    circ = float(md.get("circulating_supply") or mcap / spot)
    max_supply = float(md.get("max_supply") or md.get("total_supply") or circ)
    if not max_supply or max_supply < circ:
        max_supply = circ
    fdv = float((md.get("fully_diluted_valuation") or {}).get("usd") or 0) or spot * max_supply
    return spot, mcap, fdv, circ, max_supply


def _fetch_cg_history():
    try:
        d = _get_json(f"{_CG_BASE}/coins/spark-2/market_chart?vs_currency=usd&days=365&interval=daily")
        pbd = {str(datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()): float(p) for ms, p in d.get("prices", [])}
        mbd = {str(datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()): float(m) for ms, m in d.get("market_caps", [])}
        return pbd, mbd
    except Exception:
        return {}, {}


def _compute_share(tvl_rows: list[dict]) -> tuple[dict | None, list[dict], list[dict]]:
    months, tvl = _load_basket_monthly()
    tvl_by_month = dict(zip(months, tvl))
    if not tvl_rows or not tvl_by_month:
        return None, [], []
    latest_tvl = float(tvl[-1])
    rows = []
    for row in sorted(tvl_rows, key=lambda r: r["date"]):
        d = row["date"]
        denom = float(tvl_by_month.get(d[:7], latest_tvl))
        spark_tvl = float(row["tvl"])
        if denom > 0 and spark_tvl > 0:
            rows.append({"date": d, "spark_tvl": spark_tvl, "basket_tvl": denom, "ratio": spark_tvl / denom})
    if not rows:
        return None, [], []
    ratio = np.array([r["ratio"] for r in rows], dtype=float)
    ms7, ms30, ms90, ms180 = (_rolling_mean(ratio, w) for w in (7, 30, 90, 180))
    full, history = [], []
    for i, row in enumerate(rows):
        fr = {**row,
              "ms7": float(ms7[i]) if not np.isnan(ms7[i]) else None,
              "ms30": float(ms30[i]) if not np.isnan(ms30[i]) else None,
              "ms90": float(ms90[i]) if not np.isnan(ms90[i]) else None,
              "ms180": float(ms180[i]) if not np.isnan(ms180[i]) else None}
        full.append(fr)
        if fr["ms30"] is not None:
            history.append({"date": row["date"], "ms30": round(fr["ms30"], 6),
                            "ms90": round(fr["ms90"], 6) if fr["ms90"] is not None else None})
    latest = full[-1]
    snapshot = {"date": latest["date"], "ms7": latest["ms7"], "ms30": latest["ms30"],
                "ms90": latest["ms90"], "ms180": latest["ms180"],
                "spark_tvl": latest["spark_tvl"], "basket_tvl": latest["basket_tvl"],
                "share_cap": _SPARK_SHARE_CAP, "source": "Spark combined TVL / lending-yield basket TVL"}
    return snapshot, history[-365:], full[-365:]


def _simulate(gross_yield_on_tvl: float, spark_tvl_start: float, ms_snapshot: dict | None) -> dict:
    rng = np.random.default_rng(SEED)
    monthly_log_returns = _load_growth_distribution()
    basket_months, basket_tvl = _load_basket_monthly()
    current_denominator = float(ms_snapshot.get("basket_tvl") if ms_snapshot and ms_snapshot.get("basket_tvl")
                                else basket_tvl[-1])
    start_pool = basket_tvl[np.isfinite(basket_tvl) & (basket_tvl > 0)]
    if len(start_pool) == 0:
        start_pool = np.array([current_denominator], dtype=float)
    start_denominator = rng.choice(start_pool, size=PATHS, replace=True)
    sampled = rng.choice(monthly_log_returns, size=(PATHS, HORIZON_MONTHS), replace=True)
    denominator_path = start_denominator[:, None] * np.exp(np.cumsum(sampled, axis=1))

    if ms_snapshot and ms_snapshot.get("ms90") and ms_snapshot.get("ms30"):
        anchor = ms_snapshot.get("ms180") or ms_snapshot.get("ms90")
        velocity = _velocity_ensemble(ms_snapshot.get("ms7"), float(ms_snapshot["ms30"]), float(anchor))
        share_path = np.minimum(
            float(ms_snapshot["ms90"]) * _ms_velocity_path(HORIZON_MONTHS, velocity["monthly_log_velocity"]),
            _SPARK_SHARE_CAP)
    else:
        velocity = _velocity_ensemble(None, 1.0, 1.0)
        current_share = spark_tvl_start / max(current_denominator, 1.0)
        share_path = np.full(HORIZON_MONTHS, min(current_share, _SPARK_SHARE_CAP), dtype=float)

    monthly_tvl = denominator_path * share_path[None, :]
    monthly_gross_income = monthly_tvl * gross_yield_on_tvl / 12.0
    y3_gross = monthly_gross_income[:, -12:].sum(axis=1)
    y2_gross = monthly_gross_income[:, 12:24].sum(axis=1)
    y3_spark_tvl = monthly_tvl[:, -1]
    y3_avg_spark_tvl = monthly_tvl[:, -12:].mean(axis=1)
    y3_money_tvl = denominator_path[:, -1]

    def pack(arr):
        return {"p25": float(np.percentile(arr, 25)), "p50": float(np.percentile(arr, 50)),
                "p75": float(np.percentile(arr, 75)), "p90": float(np.percentile(arr, 90)),
                "ev_mean": float(np.mean(arr))}

    return {
        "y3_ttm_gross_income_arr": y3_gross, "y2_ttm_gross_income_arr": y2_gross,
        "y3_ttm_gross_income": pack(y3_gross), "y2_ttm_gross_income": pack(y2_gross),
        "y3_spark_tvl": pack(y3_spark_tvl), "y3_avg_spark_tvl": pack(y3_avg_spark_tvl),
        "y3_money_tvl": pack(y3_money_tvl),
        "mc_path": {
            "start_basket_tvl_p50": float(np.percentile(start_denominator, 50)),
            "current_basket_tvl": current_denominator,
            "eoy3_share": float(share_path[-1]), "velocity_ensemble": velocity,
            "share_cap": _SPARK_SHARE_CAP, "n_basket_months": len(basket_months),
            "rule": ("sample starting lending/yield-basket TVL; apply sampled monthly shocks (dampened 0.65, "
                     "capped -8%/+10%); seed Spark MS90 share and grow with 70/30 velocity ensemble decaying "
                     "over 12M (cap 35%); Spark TVL = basket TVL x share; gross income = Spark TVL x gross-yield"),
        },
    }


def _distribution(arr) -> dict:
    return {f"p{q}": float(np.percentile(arr, q)) for q in (5, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 95)}


def run() -> dict:
    caveats = []
    try:
        spot, mcap, fdv, circ, max_supply = _fetch_cg_market()
    except Exception as e:
        caveats.append(f"CoinGecko market fetch failed ({e}); using locked fallback")
        spot, mcap, fdv, circ, max_supply = (_FALLBACK_SPOT, _FALLBACK_MCAP, _FALLBACK_FDV,
                                             _FALLBACK_CIRC, _FALLBACK_MAX_SUPPLY)

    ms_snapshot, ms_history, ms_full_hist = None, [], []
    spark_tvl = _FALLBACK_TVL
    try:
        tvl_rows = _fetch_combined_tvl_history()
        if tvl_rows:
            spark_tvl = float(tvl_rows[-1]["tvl"])
        ms_snapshot, ms_history, ms_full_hist = _compute_share(tvl_rows)
    except Exception as e:
        caveats.append(f"Spark TVL / share fetch failed ({e}); using locked fallback")

    gross_yield_on_tvl = _FALLBACK_GROSS_YIELD
    ann_gross_income = spark_tvl * gross_yield_on_tvl
    trailing30_fees = trailing365_fees = None
    try:
        fees_by_date = _fetch_combined_fees_daily()
        if fees_by_date:
            fdates = sorted(fees_by_date)
            last30, last365 = fdates[-30:], fdates[-365:]
            trailing30_fees = sum(fees_by_date[d] for d in last30)
            trailing365_fees = sum(fees_by_date[d] for d in last365)
            ann_30d = trailing30_fees / len(last30) * 365.0
            ann_365d = trailing365_fees / len(last365) * 365.0
            ann_gross_income = min(ann_30d, ann_365d) if len(last365) >= 90 else ann_30d
            if spark_tvl > 0:
                gross_yield_on_tvl = ann_gross_income / spark_tvl
    except Exception as e:
        caveats.append(f"Spark fee history fetch failed ({e}); using locked gross yield")

    price_by_date, mcap_by_date = _fetch_cg_history()
    DR = _load_discount_fallback()
    dr_meta = {"discount_rate_rf": None, "discount_rate_token_stdev": None,
               "discount_rate_sp500_stdev": None, "discount_rate_equity_premium": 0.03,
               "discount_rate_sample_count": 0, "discount_rate_is_fallback": True}
    try:
        rf = 0.045
        rf_is_fallback = True
        try:
            tnx = _get_json("https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX?range=5d&interval=1d")
            rf = float(tnx["chart"]["result"][0]["meta"]["regularMarketPrice"]) / 100.0
            rf_is_fallback = False
        except Exception:
            dgs = _get_text("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10")
            rows = [r for r in csv.DictReader(io.StringIO(dgs)) if r.get("DGS10") not in ("", ".")]
            rf = float(rows[-1]["DGS10"]) / 100.0
            rf_is_fallback = False
        sp_y = _get_json("https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?range=1y&interval=1d")
        sp_close = [x for x in sp_y["chart"]["result"][0]["indicators"]["quote"][0]["close"] if x is not None]
        sp_stdev = float(np.std(np.diff(np.log(np.array(sp_close[-366:], dtype=float))), ddof=1))
        prices = [price_by_date[d] for d in sorted(price_by_date)]
        if len(prices) >= 45 and sp_stdev > 0:
            mp_stdev = float(np.std(np.diff(np.log(np.array(prices[-366:], dtype=float))), ddof=1))
            DR = rf + 0.03 * (mp_stdev / sp_stdev)
            dr_meta = {"discount_rate_rf": rf, "discount_rate_token_stdev": mp_stdev,
                       "discount_rate_sp500_stdev": sp_stdev, "discount_rate_equity_premium": 0.03,
                       "discount_rate_sample_count": len(prices), "discount_rate_is_fallback": False}
        if rf_is_fallback:
            caveats.append("Risk-free rate fetch failed; used 4.5% fallback in the discount rate.")
    except Exception as e:
        caveats.append(f"Discount-rate fetch failed ({e}); using locked DR {DR:.3f}")

    # SPK effective supply — real Sky-Farming/team/ecosystem emission schedule
    # (declining farming 1.625B/yr→…, team 12mo cliff+3yr, ecosystem linear). ~3.04B today
    # → ~6.5B by Y2 → ~7.9B by Y3 (≈79% of the 10B FDV), NOT full dilution.
    reserved_supply = max(max_supply - circ, 0.0)
    sched = _load_supply_schedule()
    float_now = circ
    supply_basis = "empirical trailing-supply extrapolation"
    if sched and sched.get("y3_supply"):
        float_now = float(sched.get("circulating_now") or circ)
        y2_effective_supply = float(sched.get("y2_supply") or sched["y3_supply"])
        y3_effective_supply = float(sched["y3_supply"])
        annual_reserved_release = (y3_effective_supply - float_now) / 3.0
        supply_basis = sched.get("basis", "published emission schedule")
    else:
        annual_reserved_release = reserved_supply / 3.0
        y2_effective_supply = circ + min(reserved_supply, annual_reserved_release * 2.0)
        y3_effective_supply = circ + min(reserved_supply, annual_reserved_release * 3.0)

    sim = _simulate(gross_yield_on_tvl, spark_tvl, ms_snapshot)
    y3_gross = sim["y3_ttm_gross_income_arr"]
    y2_gross = sim["y2_ttm_gross_income_arr"]
    disc = (1.0 + DR) ** 3

    def make_scenario(key, label, margin, supply, is_primary):
        y3_gp = y3_gross * margin
        y2_gp = y2_gross * margin
        pv = y3_gp * GP_MULTIPLE / supply / disc
        y3_price = y3_gp * GP_MULTIPLE / supply
        y2_price = y2_gp * GP_MULTIPLE / supply
        gp_q = {k: float(np.percentile(y3_gp, p)) for k, p in (("p25", 25), ("p50", 50), ("p75", 75))}
        return {
            "key": key, "label": label, "is_primary": is_primary,
            "pv": {"p25": float(np.percentile(pv, 25)), "p50": float(np.percentile(pv, 50)),
                   "p75": float(np.percentile(pv, 75)), "p90": float(np.percentile(pv, 90))},
            "ev": float(np.mean(pv)),
            "prob_above_spot": float(np.mean(pv >= spot)),
            "prob_3x": float(np.mean(pv >= 3 * spot)),
            # Two spellings of the SAME 2Y-undiscounted move probability (sibling key + frontend key); identical by design.
            "prob_spot_up_30_2y": float(np.mean(y2_price >= 1.30 * spot)),
            "prob_spot_down_30_2y": float(np.mean(y2_price <= 0.70 * spot)),
            "prob_y2_undiscounted_up_30": float(np.mean(y2_price >= 1.30 * spot)),
            "prob_y2_undiscounted_down_30": float(np.mean(y2_price <= 0.70 * spot)),
            "y3_price_p50": float(np.percentile(y3_price, 50)),
            "y3_mcap_p50": float(np.percentile(y3_price, 50) * supply),
            "y3_supply_p50": float(supply),
            "y3_gp_p50": gp_q["p50"], "y3_gp_p25": gp_q["p25"], "y3_gp_p75": gp_q["p75"],
            "net_margin": margin,
            "ev_mcap": float(np.mean(pv) * supply), "burn_3y_est": 0.0,
            "y3_volume": {"min": sim["y3_spark_tvl"]["p25"], "avg": sim["y3_spark_tvl"]["p50"],
                          "max": sim["y3_spark_tvl"]["p75"], "eoy_market_share": sim["mc_path"]["eoy3_share"]},
            "y3_spark_tvl_p50": sim["y3_spark_tvl"]["p50"],
            "distribution": _distribution(pv),
        }

    scenarios = [
        make_scenario("base_20", "Base (20% net margin)", NET_MARGIN_BASE, y3_effective_supply, True),
        make_scenario("bull_28", "Bull (28% net margin)", NET_MARGIN_BULL, y3_effective_supply, False),
        make_scenario("cons_12", "Conservative (12% net margin)", NET_MARGIN_CONSERVATIVE, y3_effective_supply, False),
    ]
    # SPK is only ~30% circulating. If the modeled 3Y supply is materially below max, show an explicit
    # FDV (max-supply) downside; otherwise (SPK already ~fully diluted within 3Y) the FDV row would just
    # duplicate the base, so show a circulating-supply upside sensitivity (unlocks slipping past 3Y) instead.
    if y3_effective_supply < 0.98 * max_supply:
        scenarios.append(make_scenario("base_20_fdv", "Base (20%) · max-supply (FDV)",
                                       NET_MARGIN_BASE, max_supply, False))
    else:
        scenarios.append(make_scenario("base_20_circ", "Base (20%) · circulating-supply",
                                       NET_MARGIN_BASE, circ, False))

    base_gp_now = ann_gross_income * NET_MARGIN_BASE
    current_gp = {
        "annualized_full_activation": ann_gross_income * NET_MARGIN_BULL,
        "annualized_current_state": base_gp_now,
        "ann_gross_income": ann_gross_income,
        "gross_income_yield_on_tvl": gross_yield_on_tvl,
        "spark_tvl": spark_tvl,
        "trailing30_fees": trailing30_fees, "trailing365_fees": trailing365_fees,
        "net_margin_base": NET_MARGIN_BASE, "net_margin_bull": NET_MARGIN_BULL,
        "net_margin_conservative": NET_MARGIN_CONSERVATIVE,
        "mcap_base_gp": (mcap / base_gp_now) if base_gp_now > 0 else None,
        "fdv_base_gp": (fdv / base_gp_now) if base_gp_now > 0 else None,
        "circulating_pct_of_max": circ / max_supply if max_supply else None,
        "reserved_supply": reserved_supply,
        "annual_reserved_supply_release": annual_reserved_release,
        "float_supply": float_now, "supply_basis": supply_basis,
        "y2_effective_supply": y2_effective_supply, "y3_effective_supply": y3_effective_supply,
        "y3_gp_p50": scenarios[0]["y3_gp_p50"],
        "y3_spark_tvl_p50": sim["y3_spark_tvl"]["p50"], "y3_basket_tvl_p50": sim["y3_money_tvl"]["p50"],
        "eoy3_share": sim["mc_path"]["eoy3_share"], "mc_path": sim["mc_path"],
        **dr_meta,
        **({"ms7_vs_lending": ms_snapshot["ms7"], "ms30_vs_lending": ms_snapshot["ms30"],
            "ms90_vs_lending": ms_snapshot["ms90"], "ms180_vs_lending": ms_snapshot["ms180"],
            "ms30_ms180_trend": (ms_snapshot["ms30"] / ms_snapshot["ms180"])
                                if ms_snapshot.get("ms30") and ms_snapshot.get("ms180") else None,
            "ms7_ms30_trend": (ms_snapshot["ms7"] / ms_snapshot["ms30"])
                              if ms_snapshot.get("ms7") and ms_snapshot.get("ms30") else None,
            "lending_basket_tvl": ms_snapshot["basket_tvl"]} if ms_snapshot else {}),
    }

    result = {
        "token": "SPK", "name": "Spark",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "market": {"spot": spot, "market_cap": mcap, "fdv": fdv,
                   "circulating_supply": circ, "max_supply": max_supply},
        "model": {
            "type": "3Y Capital-Allocator GP-Capture MC",
            "discount_rate": DR, "multiple": GP_MULTIPLE, "paths": PATHS,
            "note": ("GP = Spark TVL x gross-income-yield (SparkLend interest + SLL yield / combined TVL) x NET MARGIN "
                     "retained after Sky cost-of-capital + Spark Savings Rate payouts. TVL path: lending/yield-basket "
                     "denominator x Spark MS90 share (70/30 velocity ensemble, decay 12M, cap 35%); basket shocks "
                     "dampened 0.65, capped -8%/+10%. Primary = 20% net margin (Q1'26 net-returns margin); 10x GP; "
                     "supply from real emission schedule (~3.04B now → ~7.9B Y3)."),
        },
        "current_gp": current_gp, "scenarios": scenarios, "ms_history": ms_history,
        "caveats": [
            "Spark is a Sky subDAO/capital allocator; gross income = SparkLend interest + Spark Liquidity Layer deployment yield (live DefiLlama fees). Spark Savings (sUSDS) payout is a cost line and is excluded from income.",
            "Net margin (12/20/28%) is anchored to Spark's Q1'26 financials: gross protocol returns ~$126M/yr, net protocol returns ~$28M/yr (~22% margin), net protocol surplus ~$14M/yr (~11%). Base 20% ≈ net-returns margin; conservative 12% ≈ net-surplus margin; bull 28%. Spark is a thin-NIM (~0.6-0.7% spread) balance-sheet business and Q1'26 net surplus fell ~47% QoQ — margin is the dominant lever and is trending down. (Prior model used 30% which over-stated it.)",
            "Supply follows the real emission schedule: ~3.04B circulating today → ~6.5B by Y2 → ~7.9B by Y3 (≈79% of the 10B FDV), driven by declining Sky-Farming emissions + team/ecosystem vesting (NOT full dilution). The FDV row shows the full 10B case. Heavy ongoing farming emission is a real sell-pressure overhang.",
            "Combined component TVL has some internal double-counting (SLL supplies SparkLend / sUSDS); gross yield is derived from the same TVL base so income scales consistently.",
            "Lending/yield TVL denominator distribution is locked (53 monthly obs, 2022-01..2026-05); Spark's own TVL/fees/supply/price are live. 10x GP multiple (review band 8-12x; SPK trades ~7x on 12-mo median — discount for thin/declining margin, Points-only staking, buyback-returns-to-treasury), no separate OPEX line.",
        ] + caveats,
        "data_freshness": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    try:
        result["hist_charts"] = _compute_hist_charts(
            ms_full_hist, price_by_date, mcap_by_date, gross_yield_on_tvl,
            y3_effective_supply, DR, scenarios[0]["pv"]["p50"])
    except Exception as e:
        caveats.append(f"hist_charts failed: {e}")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "spark_result.json"), "w") as f:
        json.dump(result, f, indent=2)
    return result


def _compute_hist_charts(ms_full_hist, price_by_date, mcap_by_date, gross_yield_on_tvl,
                         supply, DR, p50_pv) -> dict:
    eoy3_ms_out = []
    for row in ms_full_hist:
        ms30, ms90, ms180 = row.get("ms30"), row.get("ms90"), row.get("ms180")
        if ms30 is None or ms90 is None:
            continue
        anchor = ms180 if ms180 is not None else ms90
        eoy3 = _ms_eoy3(ms90, ms30, anchor, _SPARK_SHARE_CAP, row.get("ms7"))
        eoy3_ms_out.append({"date": row["date"], "eoy3": round(eoy3, 6),
                            "ms90": round(ms90, 6), "ms30": round(ms30, 6)})

    margin = NET_MARGIN_BASE
    secondary_data, pv_raw_list = [], []
    for row in ms_full_hist:
        d = row["date"]
        spark_tvl_d = row.get("spark_tvl", 0.0)
        ann_gp_d = spark_tvl_d * gross_yield_on_tvl * margin
        mcap = mcap_by_date.get(d)
        if mcap and ann_gp_d > 0:
            ratio = mcap / ann_gp_d
            if 0 < ratio < 5000:
                secondary_data.append({"date": d, "value": round(ratio, 1)})
        price = price_by_date.get(d)
        pv_raw = ann_gp_d * GP_MULTIPLE / ((1 + DR) ** 3) / max(supply, 1.0)
        if price and price > 0 and pv_raw > 0:
            pv_raw_list.append((d, pv_raw, price))

    backtest = {"chart": [], "signals": {}, "latest_signal": "NEUTRAL", "last_realized_row": None}
    if pv_raw_list:
        norm = (p50_pv / pv_raw_list[-1][1]) if pv_raw_list[-1][1] > 0 else 1.0
        bt_chart = []
        for d, pv_r, price in pv_raw_list:
            pv_n = pv_r * norm
            sig = "GOOD" if pv_n / price >= 1.25 else ("BAD" if pv_n / price <= 0.75 else "NEUTRAL")
            bt_chart.append({"date": d, "spot": round(price, 6), "pv": round(pv_n, 6), "signal": sig})
        backtest = _backtest_signals(bt_chart)

    return {
        "backtest": backtest,
        "secondary_chart": {
            "label": "Historical Mcap / base-margin GP",
            "subtitle": "Market cap ÷ (Spark TVL × gross-income-yield × 20% net margin)",
            "note": "Base-margin GP proxy on trailing gross income; gross yield held constant.",
            "unit": "x", "data": secondary_data,
        },
        "eoy3_ms": eoy3_ms_out,
    }


if __name__ == "__main__":
    out = run()
    print("spot", out["market"]["spot"], "| mcap $%.0fM" % (out["market"]["market_cap"]/1e6),
          "| circ %.0f%% of max" % (out["market"]["circulating_supply"]/out["market"]["max_supply"]*100))
    print("DR", round(out["model"]["discount_rate"], 4), "| Y3 eff supply %.2fB" % (out["current_gp"]["y3_effective_supply"]/1e9),
          "| EOY3 share %.1f%%" % (out["current_gp"]["eoy3_share"]*100))
    for s in out["scenarios"]:
        pv = s["pv"]
        print(f"{'*' if s['is_primary'] else ' '} {s['label']:<34} P25 {pv['p25']:.4f}  P50 {pv['p50']:.4f}  P75 {pv['p75']:.4f}  P>spot {s['prob_above_spot']*100:4.1f}%  supply {s['y3_supply_p50']/1e9:.2f}B")
