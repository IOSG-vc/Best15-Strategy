"""MORPHO webapp valuation agent — lending fee-switch GP-capture.

Adapts the SKY money-market architecture for Morpho (lending infrastructure):

  denominator    = lending/yield TVL basket (the universe Morpho competes across)
  Morpho TVL     = denominator x Morpho share   (MS90 seed + decaying velocity, capped)
  gross interest = Morpho TVL x fee-yield-on-TVL (annualised interest paid by borrowers / TVL)
  protocol GP    = gross interest x fee-switch take

Morpho Blue's protocol fee switch is OFF by default (the MORPHO token captures ~0 today);
the on-chain max is 25% of interest (MAX_FEE = 0.25e18). So this is a UNI-style fee-ACTIVATION
valuation, not a current-cashflow one:

  - current-state (fee switch ~0%) is surfaced as the reality check
  - activated takes (10% / 15% / 25%) are the model scenarios

GP-capture (no OPEX line — an activated fee routes to the DAO/token, mirroring UNI):
  PV / MORPHO = Y3 TTM GP P50 x 8x / supply / (1 + DR)^3

Lending/yield TVL denominator distribution is locked in morpho_research_extra.json;
Morpho's own TVL / fees / supply / price are fetched live (DefiLlama + CoinGecko).
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

# ── Share / velocity tuning (mirrors SKY) ─────────────────────────────────────
_MS_AMPLIFIER_CAP = 1.5
_MS_DECAY_MONTHS = 12
_MS_MONTHS = 36
_VELOCITY_LONG_WEIGHT = 0.70
_VELOCITY_SHORT_WEIGHT = 0.30
_MAX_MONTHLY_LOG_VELOCITY = math.log(_MS_AMPLIFIER_CAP) / 6.0
_MORPHO_LENDING_SHARE_CAP = 0.35   # Morpho ~13% of the basket today; cap terminal share at 35%

# ── Model constants ───────────────────────────────────────────────────────────
HORIZON_MONTHS = 36
PATHS = 100_000
SEED = 42
GP_MULTIPLE = 8.0   # lowest of the three: zero current accrual + curator risk + pure fee-switch option. Below Spark 10x / Aave 18x

# Fee-switch take scenarios (fraction of borrower interest captured by the protocol).
# Kept BELOW Aave (~14% effective) and Spark (~20%): Morpho competes as cheap, curator-dependent infra,
# so a realistic activated take is lower even though the on-chain ceiling is 25%.
FEE_SWITCH_CURRENT = 0.0     # reality check — protocol fee is off today
FEE_SWITCH_CONSERVATIVE = 0.05
FEE_SWITCH_BASE = 0.10       # activated base -> PRIMARY (below Aave/Spark effective take)
FEE_SWITCH_FULL = 0.25       # Morpho Blue on-chain max (ceiling case, low probability)

# Monthly basket-TVL shock shaping (mirrors SKY money-market dampener/caps)
MONTHLY_GROWTH_CAP_LOW = -0.08
MONTHLY_GROWTH_CAP_HIGH = 0.10
GROWTH_DAMPENER = 0.65

BUNDLE_ROOT = Path(__file__).parent.parent.parent
EXTRA_PATH = BUNDLE_ROOT / "morpho_research_extra.json"
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")

UA = "Mozilla/5.0 Morpho valuation"
_CG_KEY = os.environ.get("COINGECKO_API_KEY", "")
_CG_BASE = "https://pro-api.coingecko.com/api/v3" if _CG_KEY else "https://api.coingecko.com/api/v3"

# ── Locked fallbacks (2026-06-30) used when a live source is unavailable ──────
_FALLBACK_SPOT = 1.90
_FALLBACK_MCAP = 1.232899225e9
_FALLBACK_FDV = 1.90e9
_FALLBACK_CIRC = 649790946.7973064
_FALLBACK_MAX_SUPPLY = 1.0e9
_FALLBACK_TVL = 6.638716210e9
_FALLBACK_FEE_YIELD_ON_TVL = 0.0344     # ann interest / TVL


# ── Generic helpers (shared shape with SKY / UNI) ─────────────────────────────
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


def _ms_velocity_path(months: int = _MS_MONTHS, monthly_log_velocity: float = 0.0,
                      decay_months: int = _MS_DECAY_MONTHS) -> np.ndarray:
    """Cumulative share multiplier from a capped monthly velocity that decays over 12M."""
    monthly_log_velocity = min(max(float(monthly_log_velocity), 0.0), _MAX_MONTHLY_LOG_VELOCITY)
    cumulative = []
    acc = 0.0
    for m in range(months):
        decay_weight = max(0.0, 1.0 - (m + 0.5) / decay_months)
        acc += monthly_log_velocity * decay_weight
        cumulative.append(math.exp(acc))
    return np.array(cumulative, dtype=float)


def _velocity_ensemble(ms7: float | None, ms30: float, ms180: float | None) -> dict:
    """Blend medium-term (30D/180D) and short-term (7D/30D) market-share velocities."""
    long_raw = float(ms30) / max(float(ms180 or ms30), 1e-12)
    short_raw = float(ms7 or ms30) / max(float(ms30), 1e-12)
    long_monthly = min(max(math.log(max(long_raw, 1.0)) / 6.0, 0.0), _MAX_MONTHLY_LOG_VELOCITY)
    short_monthly = min(max(math.log(max(short_raw, 1.0)), 0.0), _MAX_MONTHLY_LOG_VELOCITY)
    monthly = (_VELOCITY_LONG_WEIGHT * long_monthly) + (_VELOCITY_SHORT_WEIGHT * short_monthly)
    return {
        "monthly_log_velocity": monthly,
        "long_raw": long_raw,
        "short_raw": short_raw,
        "long_monthly": long_monthly,
        "short_monthly": short_monthly,
        "long_weight": _VELOCITY_LONG_WEIGHT,
        "short_weight": _VELOCITY_SHORT_WEIGHT,
        "monthly_cap": _MAX_MONTHLY_LOG_VELOCITY,
    }


def _ms_eoy3(ms90: float, ms30: float, ms_anchor: float, ms_cap: float, ms7: float | None = None) -> float:
    velocity = _velocity_ensemble(ms7, ms30, ms_anchor)
    return min(ms90 * float(_ms_velocity_path(_MS_MONTHS, velocity["monthly_log_velocity"])[-1]), ms_cap)


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
                   "recent_dates": g["dates"][-3:]}
               for s, g in groups.items()}
    return {"chart": backtest_chart, "signals": signals,
            "latest_signal": backtest_chart[-1]["signal"], "last_realized_row": last_real}


# ── Locked denominator (lending/yield TVL basket) ─────────────────────────────
def _load_growth_distribution() -> np.ndarray:
    j = json.loads(EXTRA_PATH.read_text())
    rets = np.array(j["lending_universe_log_returns"], dtype=float)
    return np.clip(rets * GROWTH_DAMPENER, MONTHLY_GROWTH_CAP_LOW, MONTHLY_GROWTH_CAP_HIGH)


def _load_basket_monthly() -> tuple[list[str], np.ndarray]:
    j = json.loads(EXTRA_PATH.read_text())
    months = [str(m) for m in j["lending_universe_months"]]
    tvl = np.array(j["lending_universe_tvl"], dtype=float)
    return months, tvl


def _load_discount_fallback() -> float:
    try:
        j = json.loads(EXTRA_PATH.read_text())
        return float(j["discount"]["formula_discount"])
    except Exception:
        return 0.25


def _load_supply_schedule() -> dict | None:
    """Real published vesting/emission curve (monthly outstanding supply, 0..36M from now)."""
    try:
        return json.loads(EXTRA_PATH.read_text()).get("supply_schedule")
    except Exception:
        return None


# ── Live Morpho data ──────────────────────────────────────────────────────────
def _fetch_morpho_tvl_history() -> list[dict]:
    """Daily Morpho Blue TVL: [{date 'YYYY-MM-DD', tvl}]."""
    d = _get_json("https://api.llama.fi/protocol/morpho-blue")
    rows = []
    seen = set()
    for pt in d.get("tvl", []):
        ts = pt.get("date")
        val = pt.get("totalLiquidityUSD")
        if ts is None or val is None:
            continue
        ds = str(datetime.fromtimestamp(int(ts), tz=timezone.utc).date())
        if ds not in seen:
            seen.add(ds)
            rows.append({"date": ds, "tvl": float(val)})
    rows.sort(key=lambda r: r["date"])
    return rows


def _fetch_morpho_fees_daily() -> dict:
    """Daily Morpho Blue fees (interest paid by borrowers): {date: fee_usd}."""
    d = _get_json("https://api.llama.fi/summary/fees/morpho-blue?dataType=dailyFees")
    out = {}
    for ts, val in d.get("totalDataChart", []):
        if val is None:
            continue
        ds = str(datetime.fromtimestamp(int(ts), tz=timezone.utc).date())
        out[ds] = float(val)
    return out


def _fetch_cg_market() -> tuple[float, float, float, float, float]:
    """(spot, mcap, fdv, circ, max_supply) from CoinGecko."""
    cg = _get_json(
        f"{_CG_BASE}/coins/morpho?localization=false&tickers=false"
        "&market_data=true&community_data=false&developer_data=false&sparkline=false"
    )
    md = cg["market_data"]
    spot = float(md["current_price"]["usd"])
    mcap = float(md["market_cap"]["usd"])
    circ = float(md.get("circulating_supply") or mcap / spot)
    max_supply = float(md.get("max_supply") or md.get("total_supply") or circ)
    if not max_supply or max_supply < circ:
        max_supply = circ
    fdv = float((md.get("fully_diluted_valuation") or {}).get("usd") or 0) or spot * max_supply
    return spot, mcap, fdv, circ, max_supply


def _fetch_cg_history() -> tuple[dict, dict]:
    """(price_by_date, mcap_by_date) from CoinGecko 365D daily chart."""
    try:
        d = _get_json(f"{_CG_BASE}/coins/morpho/market_chart?vs_currency=usd&days=365&interval=daily")
        price_by_date, mcap_by_date = {}, {}
        for ms, p in d.get("prices", []):
            ds = str(datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date())
            price_by_date[ds] = float(p)
        for ms, m_v in d.get("market_caps", []):
            ds = str(datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date())
            mcap_by_date[ds] = float(m_v)
        return price_by_date, mcap_by_date
    except Exception:
        return {}, {}


# ── Market-share of the lending basket (Morpho daily TVL / basket monthly TVL) ─
def _compute_lending_ms(tvl_rows: list[dict]) -> tuple[dict | None, list[dict], list[dict]]:
    months, tvl = _load_basket_monthly()
    tvl_by_month = dict(zip(months, tvl))
    if not tvl_rows or not tvl_by_month:
        return None, [], []
    latest_tvl = float(tvl[-1])

    rows = []
    for row in sorted(tvl_rows, key=lambda r: r["date"]):
        d = row["date"]
        month = d[:7]
        denom = float(tvl_by_month.get(month, latest_tvl))
        morpho_tvl = float(row["tvl"])
        if denom > 0 and morpho_tvl > 0:
            rows.append({"date": d, "morpho_tvl": morpho_tvl, "basket_tvl": denom, "ratio": morpho_tvl / denom})
    if not rows:
        return None, [], []

    ratio = np.array([r["ratio"] for r in rows], dtype=float)
    ms7 = _rolling_mean(ratio, 7)
    ms30 = _rolling_mean(ratio, 30)
    ms90 = _rolling_mean(ratio, 90)
    ms180 = _rolling_mean(ratio, 180)

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
    snapshot = {
        "date": latest["date"], "ms7": latest["ms7"], "ms30": latest["ms30"],
        "ms90": latest["ms90"], "ms180": latest["ms180"],
        "morpho_tvl": latest["morpho_tvl"], "basket_tvl": latest["basket_tvl"],
        "share_cap": _MORPHO_LENDING_SHARE_CAP,
        "source": "Morpho Blue daily TVL / lending-yield basket TVL",
    }
    return snapshot, history[-365:], full[-365:]


# ── Monte Carlo: gross interest fees over 36 months ───────────────────────────
def _simulate(fee_yield_on_tvl: float, morpho_tvl_start: float, ms_snapshot: dict | None,
              velocity_decay_months: int = _MS_DECAY_MONTHS) -> dict:
    rng = np.random.default_rng(SEED)
    monthly_log_returns = _load_growth_distribution()
    basket_months, basket_tvl = _load_basket_monthly()
    current_denominator = float(
        ms_snapshot.get("basket_tvl") if ms_snapshot and ms_snapshot.get("basket_tvl")
        else basket_tvl[-1]
    )

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
            float(ms_snapshot["ms90"]) * _ms_velocity_path(HORIZON_MONTHS, velocity["monthly_log_velocity"],
                                                           velocity_decay_months),
            _MORPHO_LENDING_SHARE_CAP,
        )
    else:
        velocity = _velocity_ensemble(None, 1.0, 1.0)
        current_share = morpho_tvl_start / max(current_denominator, 1.0)
        share_path = np.full(HORIZON_MONTHS, min(current_share, _MORPHO_LENDING_SHARE_CAP), dtype=float)

    monthly_tvl = denominator_path * share_path[None, :]               # Morpho TVL per path/month
    monthly_gross_fees = monthly_tvl * fee_yield_on_tvl / 12.0          # interest paid by borrowers

    y3_ttm_gross_fees = monthly_gross_fees[:, -12:].sum(axis=1)
    y2_ttm_gross_fees = monthly_gross_fees[:, 12:24].sum(axis=1)
    y3_morpho_tvl = monthly_tvl[:, -1]
    y3_avg_morpho_tvl = monthly_tvl[:, -12:].mean(axis=1)
    y3_money_tvl = denominator_path[:, -1]
    y3_avg_money_tvl = denominator_path[:, -12:].mean(axis=1)

    def pack(arr):
        return {"p25": float(np.percentile(arr, 25)), "p50": float(np.percentile(arr, 50)),
                "p75": float(np.percentile(arr, 75)), "p90": float(np.percentile(arr, 90)),
                "ev_mean": float(np.mean(arr))}

    return {
        "y3_ttm_gross_fees_arr": y3_ttm_gross_fees,
        "y2_ttm_gross_fees_arr": y2_ttm_gross_fees,
        "y3_ttm_gross_fees": pack(y3_ttm_gross_fees),
        "y2_ttm_gross_fees": pack(y2_ttm_gross_fees),
        "y3_morpho_tvl": pack(y3_morpho_tvl),
        "y3_avg_morpho_tvl": pack(y3_avg_morpho_tvl),
        "y3_money_tvl": pack(y3_money_tvl),
        "y3_avg_money_tvl": pack(y3_avg_money_tvl),
        "mc_path": {
            "start_basket_tvl_p50": float(np.percentile(start_denominator, 50)),
            "start_basket_tvl_p25": float(np.percentile(start_denominator, 25)),
            "start_basket_tvl_p75": float(np.percentile(start_denominator, 75)),
            "current_basket_tvl": current_denominator,
            "eoy3_lending_share": float(share_path[-1]),
            "velocity_ensemble": velocity,
            "share_cap": _MORPHO_LENDING_SHARE_CAP,
            "n_basket_months": len(basket_months),
            "rule": ("sample starting lending/yield-basket TVL uniformly from historical monthly denominators; "
                     "apply sampled monthly shocks (dampened 0.65, capped -8%/+10%); seed Morpho MS90 share and "
                     "grow it with a 70% MS30/MS180 + 30% MS7/MS30 velocity ensemble decaying over 12M (cap 35%); "
                     "Morpho TVL = basket TVL x share; gross interest = Morpho TVL x fee-yield-on-TVL"),
        },
    }


def _distribution(arr) -> dict:
    return {f"p{q}": float(np.percentile(arr, q))
            for q in (5, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 95)}


def run() -> dict:
    """Fetch live Morpho data, run the fee-switch GP-capture MC, return standardized dict."""
    caveats = []

    # ── Market data ───────────────────────────────────────────────────────────
    try:
        spot, mcap, fdv, circ, max_supply = _fetch_cg_market()
    except Exception as e:
        caveats.append(f"CoinGecko market fetch failed ({e}); using locked fallback market data")
        spot, mcap, fdv, circ, max_supply = (_FALLBACK_SPOT, _FALLBACK_MCAP, _FALLBACK_FDV,
                                             _FALLBACK_CIRC, _FALLBACK_MAX_SUPPLY)

    # ── Morpho TVL + market share of the lending basket ───────────────────────
    ms_snapshot, ms_history, ms_full_hist = None, [], []
    morpho_tvl = _FALLBACK_TVL
    try:
        tvl_rows = _fetch_morpho_tvl_history()
        if tvl_rows:
            morpho_tvl = float(tvl_rows[-1]["tvl"])
        ms_snapshot, ms_history, ms_full_hist = _compute_lending_ms(tvl_rows)
    except Exception as e:
        caveats.append(f"Morpho TVL / market-share fetch failed ({e}); using locked fallback")

    # ── Fee yield on TVL (annualised interest paid by borrowers / TVL) ────────
    fee_yield_on_tvl = _FALLBACK_FEE_YIELD_ON_TVL
    ann_interest_fees = morpho_tvl * fee_yield_on_tvl
    trailing30_fees = trailing365_fees = daily_fee_stdev = None
    try:
        fees_by_date = _fetch_morpho_fees_daily()
        if fees_by_date:
            fdates = sorted(fees_by_date)
            last30 = fdates[-30:]
            last365 = fdates[-365:]
            trailing30_fees = sum(fees_by_date[d] for d in last30)
            trailing365_fees = sum(fees_by_date[d] for d in last365)
            daily_fee_stdev = float(np.std(np.array([fees_by_date[d] for d in last365], dtype=float)))
            # No-lookahead style: blend short and long run-rates, take the more conservative
            ann_30d = trailing30_fees / len(last30) * 365.0
            ann_365d = trailing365_fees / len(last365) * 365.0
            ann_interest_fees = min(ann_30d, ann_365d) if len(last365) >= 90 else ann_30d
            if morpho_tvl > 0:
                fee_yield_on_tvl = ann_interest_fees / morpho_tvl
    except Exception as e:
        caveats.append(f"Morpho fee history fetch failed ({e}); using locked fee yield")

    # ── Discount rate: rf + ERP x (MORPHO stdev / S&P stdev), UNI-style ───────
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
        if len(prices) >= 60 and sp_stdev > 0:
            mp_stdev = float(np.std(np.diff(np.log(np.array(prices[-366:], dtype=float))), ddof=1))
            DR = rf + 0.03 * (mp_stdev / sp_stdev)
            dr_meta = {"discount_rate_rf": rf, "discount_rate_token_stdev": mp_stdev,
                       "discount_rate_sp500_stdev": sp_stdev, "discount_rate_equity_premium": 0.03,
                       "discount_rate_sample_count": len(prices), "discount_rate_is_fallback": False}
        if rf_is_fallback:
            caveats.append("Risk-free rate fetch failed; used 4.5% fallback in the discount rate.")
    except Exception as e:
        caveats.append(f"Discount-rate fetch failed ({e}); using locked DR {DR:.3f}")

    # ── MORPHO effective supply — real published vesting schedule (float basis) ─
    # CoinGecko over-reports MORPHO circulating (~649.8M) by counting the DAO reserve as
    # circulating. The schedule's float basis (320M today → 525M by Y3) covers only the
    # contractual tranches; the 47.5% DAO/TBD reserve is represented by the FDV (max-supply) row.
    reserved_supply = max(max_supply - circ, 0.0)
    sched = _load_supply_schedule()
    float_now = circ
    supply_basis = "empirical trailing-supply extrapolation"
    if sched and sched.get("y3_supply"):
        float_now = float(sched.get("circulating_now") or circ)
        y2_effective_supply = float(sched.get("y2_supply") or sched["y3_supply"])
        y3_effective_supply = float(sched["y3_supply"])
        annual_reserved_release = (y3_effective_supply - float_now) / 3.0
        supply_basis = sched.get("basis", "published vesting schedule")
    else:
        annual_reserved_release = reserved_supply / 3.0
        y2_effective_supply = circ + min(reserved_supply, annual_reserved_release * 2.0)
        y3_effective_supply = circ + min(reserved_supply, annual_reserved_release * 3.0)

    # ── Run the MC once (gross interest fees), scale per fee-switch take ───────
    sim = _simulate(fee_yield_on_tvl, morpho_tvl, ms_snapshot)
    y3_gross = sim["y3_ttm_gross_fees_arr"]
    y2_gross = sim["y2_ttm_gross_fees_arr"]
    disc = (1.0 + DR) ** 3

    def make_scenario(key, label, take, supply, is_primary, gross_mult=1.0):
        # gross_mult scales the simulated gross interest fees (e.g. 0.5 = borrow-APR compression)
        y3_gp = y3_gross * take * gross_mult
        y2_gp = y2_gross * take * gross_mult
        pv = y3_gp * GP_MULTIPLE / supply / disc
        y3_price = y3_gp * GP_MULTIPLE / supply
        y2_price = y2_gp * GP_MULTIPLE / supply
        gp_q = {k: float(np.percentile(y3_gp, p)) for k, p in (("p25", 25), ("p50", 50), ("p75", 75))}
        return {
            "key": key,
            "label": label,
            "is_primary": is_primary,
            "pv": {"p25": float(np.percentile(pv, 25)), "p50": float(np.percentile(pv, 50)),
                   "p75": float(np.percentile(pv, 75)), "p90": float(np.percentile(pv, 90))},
            "ev": float(np.mean(pv)),
            "prob_above_spot": float(np.mean(pv >= spot)),
            "prob_3x": float(np.mean(pv >= 3 * spot)),
            # 2Y undiscounted move probabilities (provide both key spellings used across the app)
            "prob_spot_up_30_2y": float(np.mean(y2_price >= 1.30 * spot)),
            "prob_spot_down_30_2y": float(np.mean(y2_price <= 0.70 * spot)),
            "prob_y2_undiscounted_up_30": float(np.mean(y2_price >= 1.30 * spot)),
            "prob_y2_undiscounted_down_30": float(np.mean(y2_price <= 0.70 * spot)),
            "y3_price_p50": float(np.percentile(y3_price, 50)),
            "y3_mcap_p50": float(np.percentile(y3_price, 50) * supply),
            "y3_supply_p50": float(supply),
            "y3_gp_p50": gp_q["p50"],
            "y3_gp_p25": gp_q["p25"],
            "y3_gp_p75": gp_q["p75"],
            "fee_switch_take": take,
            "fee_yield_mult": gross_mult,
            "ev_mcap": float(np.mean(pv) * supply),
            "burn_3y_est": 0.0,
            "y3_volume": {
                "min": sim["y3_morpho_tvl"]["p25"],
                "avg": sim["y3_morpho_tvl"]["p50"],
                "max": sim["y3_morpho_tvl"]["p75"],
                "eoy_market_share": sim["mc_path"]["eoy3_lending_share"],
            },
            "y3_morpho_tvl_p50": sim["y3_morpho_tvl"]["p50"],
            "distribution": _distribution(pv),
        }

    scenarios = [
        make_scenario("base_10", "Base activation (10% fee switch)", FEE_SWITCH_BASE, y3_effective_supply, True),
        make_scenario("full_25", "Full activation (25% — on-chain max)", FEE_SWITCH_FULL, y3_effective_supply, False),
        make_scenario("cons_5", "Conservative activation (5%)", FEE_SWITCH_CONSERVATIVE, y3_effective_supply, False),
        # Rate-risk sensitivity: borrow APRs (hence fee-yield-on-TVL) compress ~50% if rates normalize.
        make_scenario("base_10_apr50", "Base (10%) · APR compression (−50% fee-yield)",
                      FEE_SWITCH_BASE, y3_effective_supply, False, gross_mult=0.5),
    ]
    # If the modeled 3Y supply is materially below max, show an explicit FDV (max-supply) downside;
    # otherwise (MORPHO already ~fully diluted within 3Y) show a circulating-supply upside sensitivity.
    if y3_effective_supply < 0.98 * max_supply:
        scenarios.append(make_scenario("base_10_fdv", "Base activation (10%) · max-supply (FDV)",
                                       FEE_SWITCH_BASE, max_supply, False))
    else:
        scenarios.append(make_scenario("base_10_circ", "Base activation (10%) · circulating-supply",
                                       FEE_SWITCH_BASE, circ, False))

    # Velocity scenario analysis: vary the momentum-decay window (bear 6M / base 12M / bull 24M)
    # holding the primary fee-switch take and supply fixed. Shows share-momentum sensitivity.
    _vel_sims = {
        6:  _simulate(fee_yield_on_tvl, morpho_tvl, ms_snapshot, 6),
        12: sim,
        24: _simulate(fee_yield_on_tvl, morpho_tvl, ms_snapshot, 24),
    }
    velocity_scenarios = []
    for _dm, _vlabel in ((6, "Bear: 6M momentum decay"), (12, "Base: 12M momentum decay"), (24, "Bull: 24M momentum decay")):
        _vsim = _vel_sims[_dm]
        _vy3_gp = _vsim["y3_ttm_gross_fees_arr"] * FEE_SWITCH_BASE
        _vpv = _vy3_gp * GP_MULTIPLE / y3_effective_supply / disc
        velocity_scenarios.append({
            "label": _vlabel, "decay_months": _dm,
            "y3_gp_p50": float(np.percentile(_vy3_gp, 50)),
            "pv": {"p25": float(np.percentile(_vpv, 25)), "p50": float(np.percentile(_vpv, 50)),
                   "p75": float(np.percentile(_vpv, 75))},
            "eoy3_share": _vsim["mc_path"]["eoy3_lending_share"],
            "prob_above_spot": float(np.mean(_vpv >= spot)),
        })

    # ── current_gp block (cards + diagnostics) ────────────────────────────────
    current_full_gp = ann_interest_fees * FEE_SWITCH_FULL
    current_base_gp = ann_interest_fees * FEE_SWITCH_BASE
    current_gp = {
        "annualized_full_activation": current_full_gp,           # ann interest x 25%
        "annualized_current_state": ann_interest_fees * FEE_SWITCH_CURRENT,   # ~0 (fee switch off)
        "ann_interest_fees": ann_interest_fees,
        "fee_yield_on_tvl": fee_yield_on_tvl,
        "morpho_tvl": morpho_tvl,
        "trailing30_fees": trailing30_fees,
        "trailing365_fees": trailing365_fees,
        "daily_fee_stdev": daily_fee_stdev,
        "fee_switch_base_take": FEE_SWITCH_BASE,
        "fee_switch_full_take": FEE_SWITCH_FULL,
        "fee_switch_current_take": FEE_SWITCH_CURRENT,
        "mcap_full_activation_gp": (mcap / current_full_gp) if current_full_gp > 0 else None,
        "mcap_base_activation_gp": (mcap / current_base_gp) if current_base_gp > 0 else None,
        "fdv_full_activation_gp": (fdv / current_full_gp) if current_full_gp > 0 else None,
        "reserved_supply": reserved_supply,
        "annual_reserved_supply_release": annual_reserved_release,
        "float_supply": float_now,
        "reported_circulating_coingecko": circ,
        "supply_basis": supply_basis,
        "y2_effective_supply": y2_effective_supply,
        "y3_effective_supply": y3_effective_supply,
        "y3_gp_p50": scenarios[0]["y3_gp_p50"],
        "y3_morpho_tvl_p50": sim["y3_morpho_tvl"]["p50"],
        "y3_basket_tvl_p50": sim["y3_money_tvl"]["p50"],
        "eoy3_lending_share": sim["mc_path"]["eoy3_lending_share"],
        "mc_path": sim["mc_path"],
        **dr_meta,
        **({"ms7_vs_lending": ms_snapshot["ms7"],
            "ms30_vs_lending": ms_snapshot["ms30"],
            "ms90_vs_lending": ms_snapshot["ms90"],
            "ms180_vs_lending": ms_snapshot["ms180"],
            "ms30_ms180_trend": (ms_snapshot["ms30"] / ms_snapshot["ms180"])
                                if ms_snapshot.get("ms30") and ms_snapshot.get("ms180") else None,
            "ms7_ms30_trend": (ms_snapshot["ms7"] / ms_snapshot["ms30"])
                              if ms_snapshot.get("ms7") and ms_snapshot.get("ms30") else None,
            "lending_basket_tvl": ms_snapshot["basket_tvl"],
            } if ms_snapshot else {}),
    }

    result = {
        "token": "MORPHO",
        "name": "Morpho",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "market": {
            "spot": spot,
            "market_cap": mcap,
            "fdv": fdv,
            "circulating_supply": circ,
            "max_supply": max_supply,
        },
        "model": {
            "type": "3Y Lending Fee-Switch GP-Capture MC",
            "discount_rate": DR,
            "multiple": GP_MULTIPLE,
            "paths": PATHS,
            "note": (
                "GP = Morpho TVL x fee-yield-on-TVL (annualised borrower interest / TVL) x fee-switch take. "
                "TVL path: sampled lending/yield-basket TVL denominator x Morpho MS90 share, "
                "70% MS30/MS180 + 30% MS7/MS30 velocity ensemble decaying over 12M (share cap 35%); "
                "basket shocks dampened 0.65, capped -8%/+10% monthly. "
                "Morpho Blue protocol fee is OFF today (token revenue ~0); on-chain max take is 25%. "
                "Primary = 10% activation (kept below Aave ~14% / Spark ~20% effective take — Morpho is cheap, "
                "curator-dependent infra); 8x GP multiple (below Spark 10x / Aave 18x for zero current accrual + "
                "curator risk); no OPEX (activated fee routes to DAO/token)."
            ),
        },
        "current_gp": current_gp,
        "scenarios": scenarios,
        "velocity_scenarios": velocity_scenarios,
        "ms_history": ms_history,
        "caveats": [
            "Morpho Blue's protocol fee switch is OFF by default — the MORPHO token captures ~0 of borrower interest today. This is a fee-ACTIVATION valuation, not a current-cashflow one.",
            "DefiLlama 'fees' = interest paid by borrowers (accrues to suppliers today). Modeled GP applies a governance fee-switch take (10/15/25%) to that interest.",
            "Fee-switch take is capped at 25% on-chain (MAX_FEE = 0.25e18); a high take reduces supplier yields and may pressure competitiveness.",
            "Lending/yield TVL denominator distribution is locked (53 monthly obs, 2022-01..2026-05); Morpho's own TVL/fees/price are live.",
            "Supply: primary scenarios use the published vesting schedule on a FLOAT basis (~320M today → ~525M by Y3, contractual tranches only). CoinGecko's ~650M 'circulating' over-counts the DAO reserve. The 47.5% DAO/TBD reserve is governance-controlled with no fixed schedule and is shown as the separate FDV (max-supply 1B) row.",
            "Fee-yield-on-TVL (~trailing borrow APR) is held constant across all paths, so the P25–P90 spread reflects TVL/share variation only — NOT rate compression. Borrow APRs are cyclical: if rates normalize ~50% lower, Y3 GP and PV roughly halve. The 'APR compression (−50% fee-yield)' scenario quantifies this tail. Annualized fees are the conservative min(30D, 365D) run-rate; daily fee data (DefiLlama) is volatile (see daily_fee_stdev). No OPEX line (GP-capture framing, mirrors UNI).",
        ] + caveats,
        "data_freshness": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    # ── Historical charts (Mcap / full-activation GP + EOY3 share) ────────────
    try:
        result["hist_charts"] = _compute_hist_charts(
            ms_full_hist, price_by_date, mcap_by_date, fee_yield_on_tvl,
            y3_effective_supply, DR, scenarios[0]["pv"]["p50"],
        )
    except Exception as e:
        caveats.append(f"hist_charts failed: {e}")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "morpho_result.json"), "w") as f:
        json.dump(result, f, indent=2)
    return result


def _compute_hist_charts(ms_full_hist, price_by_date, mcap_by_date, fee_yield_on_tvl,
                         supply, DR, p50_pv) -> dict:
    """Mcap / full-activation GP ratio over time + EOY3 lending-share history + model backtest."""
    eoy3_ms_out = []
    for row in ms_full_hist:
        ms30, ms90, ms180 = row.get("ms30"), row.get("ms90"), row.get("ms180")
        if ms30 is None or ms90 is None:
            continue
        anchor = ms180 if ms180 is not None else ms90
        eoy3 = _ms_eoy3(ms90, ms30, anchor, _MORPHO_LENDING_SHARE_CAP, row.get("ms7"))
        eoy3_ms_out.append({"date": row["date"], "eoy3": round(eoy3, 6),
                            "ms90": round(ms90, 6), "ms30": round(ms30, 6)})

    full_take = FEE_SWITCH_FULL
    secondary_data, pv_raw_list = [], []
    for row in ms_full_hist:
        d = row["date"]
        morpho_tvl_d = row.get("morpho_tvl", 0.0)
        ann_gp_d = morpho_tvl_d * fee_yield_on_tvl * full_take   # full-activation GP proxy
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
            bt_chart.append({"date": d, "spot": round(price, 4), "pv": round(pv_n, 4), "signal": sig})
        backtest = _backtest_signals(bt_chart)

    return {
        "backtest": backtest,
        "secondary_chart": {
            "label": "Historical Mcap / full-activation GP",
            "subtitle": "Market cap ÷ (Morpho TVL × fee-yield-on-TVL × 25% full-activation take)",
            "note": "Full-activation GP proxy assumes the 25% Morpho Blue protocol fee on trailing borrower interest. Fee yield held constant.",
            "unit": "x",
            "data": secondary_data,
        },
        "eoy3_ms": eoy3_ms_out,
    }


if __name__ == "__main__":
    import pprint
    out = run()
    pprint.pprint({k: v for k, v in out.items() if k not in ("ms_history", "hist_charts", "scenarios")})
    for s in out["scenarios"]:
        print(s["key"], "P50 PV", round(s["pv"]["p50"], 4), "prob>spot", round(s["prob_above_spot"], 3))
