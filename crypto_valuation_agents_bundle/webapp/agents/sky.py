"""SKY webapp valuation agent.

Monte Carlo model adapted from src/sky_mc_agent.py.
Uses sky_data_collection.json + sky_research_extra.json from the bundle root
for market-cycle growth distribution.
Market data (spot, mcap, fdv, supply) is fetched live from CoinGecko.

Model framework:
  Gross income / fees - savings-rate cost = GP
  GP - OPEX = net profit
  USDS follows a HYPE-style money-market denominator x Sky share path;
  DAI is flat in base.
"""
from __future__ import annotations

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
_SKY_MONEY_MARKET_SHARE_CAP = 0.35
_SKY_INFO_BASE = "https://info-sky.blockanalitica.com"


def _ms_acceleration_path(months: int = _MS_MONTHS, initial: float = 1.0) -> np.ndarray:
    """HYPE-style cumulative share multiplier from a decaying 6M share-growth amplifier."""
    initial = min(max(float(initial), 1.0), _MS_AMPLIFIER_CAP)
    monthly_log_velocity = math.log(initial) / 6.0
    return _ms_velocity_path(months, monthly_log_velocity)


def _ms_velocity_path(months: int = _MS_MONTHS, monthly_log_velocity: float = 0.0) -> np.ndarray:
    """Cumulative share multiplier from a capped monthly velocity that decays over 12M."""
    monthly_log_velocity = min(max(float(monthly_log_velocity), 0.0), _MAX_MONTHLY_LOG_VELOCITY)
    cumulative = []
    acc = 0.0
    for m in range(months):
        decay_weight = max(0.0, 1.0 - (m + 0.5) / _MS_DECAY_MONTHS)
        acc += monthly_log_velocity * decay_weight
        cumulative.append(math.exp(acc))
    return np.array(cumulative, dtype=float)


def _velocity_ensemble(ms7: float | None, ms30: float, ms180: float | None) -> dict:
    """Blend medium-term and short-term market-share velocities.

    Long component follows the legacy 30D/180D six-month amplifier.
    Short component adds a 7D/30D near-term read, both capped and floored at zero
    monthly acceleration so deceleration does not mechanically compress MS90.
    """
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

BUNDLE_ROOT = Path(__file__).parent.parent.parent
DATA_PATH = BUNDLE_ROOT / "sky_data_collection.json"
EXTRA_PATH = BUNDLE_ROOT / "sky_research_extra.json"

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")

_CG_KEY = os.environ.get("COINGECKO_API_KEY", "")
_CG_BASE = "https://pro-api.coingecko.com/api/v3" if _CG_KEY else "https://api.coingecko.com/api/v3"

# Fallback market data from sky_data_collection.json (2026-05-08) used when CG is unavailable
_FALLBACK_SPOT = 0.08084
_FALLBACK_SUPPLY = 23.462665147e9
_FALLBACK_MCAP = 1.876588264e9
_FALLBACK_FDV = 1.896796712e9


def _fetch_cg_market():
    """Fetch live SKY market data from CoinGecko. Returns (spot, mcap, fdv, supply)."""
    import time as _time
    url = f"{_CG_BASE}/coins/markets?vs_currency=usd&ids=sky&sparkline=false"
    hdrs = {"User-Agent": "Mozilla/5.0"}
    if _CG_KEY:
        hdrs["x-cg-pro-api-key"] = _CG_KEY
    req = urllib.request.Request(url, headers=hdrs)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.load(r)
            m = data[0]
            spot = float(m["current_price"])
            mcap = float(m["market_cap"])
            fdv = float(m.get("fully_diluted_valuation") or mcap)
            supply = float(m.get("circulating_supply") or mcap / spot)
            return spot, mcap, fdv, supply
        except Exception as e:
            if attempt < 2:
                _time.sleep(10 * (attempt + 1))
            else:
                raise

USDS_SUPPLY = 6.426632076e9
DAI_SUPPLY = 4.165943911e9
SUSDS_SUPPLY = 5.218832683e9
SDAI_SUPPLY = 0.239828197e9
TOTAL_STABLE_SUPPLY = USDS_SUPPLY + DAI_SUPPLY

GROSS_INCOME = 425.2e6
SAVINGS_EXPENSE = 193.49e6
STUSDS_EXPENSE = 13.23e6
CURRENT_OPEX_SITE = 43.93e6

GROSS_INCOME_YIELD = GROSS_INCOME / TOTAL_STABLE_SUPPLY
SAVINGS_RATE = 0.0365
USDS_SAVINGS_PENETRATION = SUSDS_SUPPLY / USDS_SUPPLY
DAI_SAVINGS_PENETRATION = SDAI_SUPPLY / DAI_SUPPLY
STUSDS_EXPENSE_RATE_ON_USDS = STUSDS_EXPENSE / USDS_SUPPLY

HORIZON_MONTHS = 36
DISCOUNT_RATE = 0.25
PATHS = 100_000
SEED = 42

OPEX_SCENARIOS = {
    "bear_90m_opex": 90e6,
    "base_70m_opex": 70e6,
    "bull_50m_opex": 50e6,
}
GP_MULTIPLE = 10.0
NP_MULTIPLE = 15.0

MONTHLY_GROWTH_CAP_LOW = -0.08
MONTHLY_GROWTH_CAP_HIGH = 0.10
GROWTH_DAMPENER = 0.65


def _load_growth_distribution() -> np.ndarray:
    j = json.loads(EXTRA_PATH.read_text())
    rets = np.array(j["money_market_log_returns"], dtype=float)
    return np.clip(rets * GROWTH_DAMPENER, MONTHLY_GROWTH_CAP_LOW, MONTHLY_GROWTH_CAP_HIGH)


def _load_money_market_monthly() -> tuple[list[str], np.ndarray]:
    j = json.loads(EXTRA_PATH.read_text())
    months = [str(m) for m in j["money_market_months"]]
    tvl = np.array(j["money_market_tvl"], dtype=float)
    return months, tvl


def _rolling_mean(arr: np.ndarray, w: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    for i in range(w - 1, len(arr)):
        window = arr[i - w + 1: i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) > 0:
            out[i] = float(valid.mean())
    return out


def _fetch_sky_supply_official() -> tuple[dict, list[dict]]:
    """Fetch official Sky supply data from the info.skyeco.com backing API."""
    snapshot = _get_json(f"{_SKY_INFO_BASE}/overall/?days_ago=1")
    hist = _get_json(f"{_SKY_INFO_BASE}/overall/historic/?days_ago=365")
    rows = hist.get("data", []) if isinstance(hist, dict) else []
    return snapshot, rows


def _official_supply_snapshot(snapshot: dict) -> dict:
    usds = float(snapshot["total_usds"])
    dai = float(snapshot["total_dai"])
    return {
        "date": snapshot.get("date"),
        "usds_supply": usds,
        "dai_supply": dai,
        "total_sky_stable_supply": usds + dai,
        "source": "https://info.skyeco.com/supply",
    }


def _compute_money_market_ms(supply_rows: list[dict]) -> tuple[dict | None, list[dict], list[dict]]:
    """Compute Sky share of broad money-market/yield-vault TVL from official supply rows."""
    months, tvl = _load_money_market_monthly()
    tvl_by_month = dict(zip(months, tvl))
    if not supply_rows or not tvl_by_month:
        return None, [], []

    latest_tvl = float(tvl[-1])
    rows = []
    for row in sorted(supply_rows, key=lambda r: r.get("date", "")):
        d = row.get("date")
        if not d:
            continue
        month = str(d)[:7]
        denom = float(tvl_by_month.get(month, latest_tvl))
        usds = float(row.get("total_usds") or 0.0)
        dai = float(row.get("total_dai") or 0.0)
        total = usds + dai
        if denom > 0 and total > 0:
            rows.append({
                "date": d,
                "sky_supply": total,
                "usds_supply": usds,
                "dai_supply": dai,
                "money_market_tvl": denom,
                "ratio": total / denom,
            })
    if not rows:
        return None, [], []

    ratio = np.array([r["ratio"] for r in rows], dtype=float)
    ms7 = _rolling_mean(ratio, 7)
    ms30 = _rolling_mean(ratio, 30)
    ms90 = _rolling_mean(ratio, 90)
    ms180 = _rolling_mean(ratio, 180)

    full = []
    history = []
    for i, row in enumerate(rows):
        full_row = {
            **row,
            "ms7": float(ms7[i]) if not np.isnan(ms7[i]) else None,
            "ms30": float(ms30[i]) if not np.isnan(ms30[i]) else None,
            "ms90": float(ms90[i]) if not np.isnan(ms90[i]) else None,
            "ms180": float(ms180[i]) if not np.isnan(ms180[i]) else None,
        }
        full.append(full_row)
        if full_row["ms30"] is not None:
            history.append({
                "date": row["date"],
                "ms30": round(full_row["ms30"], 6),
                "ms90": round(full_row["ms90"], 6) if full_row["ms90"] is not None else None,
            })

    latest = full[-1]
    snapshot = {
        "date": latest["date"],
        "ms7": latest["ms7"],
        "ms30": latest["ms30"],
        "ms90": latest["ms90"],
        "ms180": latest["ms180"],
        "sky_supply": latest["sky_supply"],
        "usds_supply": latest["usds_supply"],
        "dai_supply": latest["dai_supply"],
        "money_market_tvl": latest["money_market_tvl"],
        "share_cap": _SKY_MONEY_MARKET_SHARE_CAP,
        "source": "Sky official supply / broad money-market TVL",
    }
    return snapshot, history[-365:], full[-365:]


def _simulate(opex: float, np_multiple: float, spot: float, sky_supply: float,
              usds_start: float, dai_start: float, ms_snapshot: dict | None) -> dict:
    rng = np.random.default_rng(SEED)
    monthly_log_returns = _load_growth_distribution()
    money_market_months, money_market_tvl = _load_money_market_monthly()
    current_denominator = float(
        ms_snapshot.get("money_market_tvl") if ms_snapshot and ms_snapshot.get("money_market_tvl")
        else money_market_tvl[-1]
    )
    start_pool = money_market_tvl[np.isfinite(money_market_tvl) & (money_market_tvl > 0)]
    if len(start_pool) == 0:
        start_pool = np.array([current_denominator], dtype=float)
    start_denominator = rng.choice(start_pool, size=PATHS, replace=True)
    sampled = rng.choice(monthly_log_returns, size=(PATHS, HORIZON_MONTHS), replace=True)
    denominator_path = start_denominator[:, None] * np.exp(np.cumsum(sampled, axis=1))

    if ms_snapshot and ms_snapshot.get("ms90") and ms_snapshot.get("ms30"):
        anchor = ms_snapshot.get("ms180") or ms_snapshot.get("ms90")
        velocity = _velocity_ensemble(ms_snapshot.get("ms7"), float(ms_snapshot["ms30"]), float(anchor))
        momentum = math.exp(velocity["monthly_log_velocity"] * 6.0)
        share_path = np.minimum(
            float(ms_snapshot["ms90"]) * _ms_velocity_path(HORIZON_MONTHS, velocity["monthly_log_velocity"]),
            _SKY_MONEY_MARKET_SHARE_CAP,
        )
    else:
        momentum = 1.0
        velocity = _velocity_ensemble(None, 1.0, 1.0)
        current_share = (usds_start + dai_start) / max(float(money_market_tvl[-1]), 1.0)
        share_path = np.full(HORIZON_MONTHS, min(current_share, _SKY_MONEY_MARKET_SHARE_CAP), dtype=float)

    dai = np.full(PATHS, dai_start, dtype=float)
    monthly_gp = np.zeros((PATHS, HORIZON_MONTHS), dtype=float)
    monthly_np = np.zeros((PATHS, HORIZON_MONTHS), dtype=float)
    monthly_gross_income = np.zeros((PATHS, HORIZON_MONTHS), dtype=float)
    monthly_savings_cost = np.zeros((PATHS, HORIZON_MONTHS), dtype=float)
    monthly_stusds_cost = np.zeros((PATHS, HORIZON_MONTHS), dtype=float)
    monthly_usds_supply = np.zeros((PATHS, HORIZON_MONTHS), dtype=float)
    monthly_total_supply = np.zeros((PATHS, HORIZON_MONTHS), dtype=float)
    usds = np.full(PATHS, usds_start, dtype=float)
    sky_total = np.full(PATHS, usds_start + dai_start, dtype=float)

    for m in range(HORIZON_MONTHS):
        sky_total = denominator_path[:, m] * share_path[m]
        usds = np.maximum(sky_total - dai, 0.0)
        total = usds + dai
        gross_income_m = total * GROSS_INCOME_YIELD / 12.0
        savings_cost_m = (usds * USDS_SAVINGS_PENETRATION + dai * DAI_SAVINGS_PENETRATION) * SAVINGS_RATE / 12.0
        stusds_cost_m = usds * STUSDS_EXPENSE_RATE_ON_USDS / 12.0
        gp_m = gross_income_m - savings_cost_m - stusds_cost_m
        np_m = gp_m - opex / 12.0
        monthly_gross_income[:, m] = gross_income_m
        monthly_savings_cost[:, m] = savings_cost_m
        monthly_stusds_cost[:, m] = stusds_cost_m
        monthly_usds_supply[:, m] = usds
        monthly_total_supply[:, m] = total
        monthly_gp[:, m] = gp_m
        monthly_np[:, m] = np_m

    y3_ttm_gp = monthly_gp[:, -12:].sum(axis=1)
    y3_ttm_np = monthly_np[:, -12:].sum(axis=1)
    y3_ttm_gross_income = monthly_gross_income[:, -12:].sum(axis=1)
    y3_ttm_savings_cost = monthly_savings_cost[:, -12:].sum(axis=1)
    y3_ttm_stusds_cost = monthly_stusds_cost[:, -12:].sum(axis=1)
    y2_ttm_gp = monthly_gp[:, 12:24].sum(axis=1)
    y2_ttm_np = monthly_np[:, 12:24].sum(axis=1)
    y3_ttm_np_floor = np.maximum(y3_ttm_np, 0.0)
    y2_ttm_np_floor = np.maximum(y2_ttm_np, 0.0)
    accumulated_treasury_cash = np.maximum(monthly_np, 0.0).sum(axis=1)

    undiscounted_gp_price = y3_ttm_gp * GP_MULTIPLE / sky_supply
    undiscounted_np_price = y3_ttm_np_floor * np_multiple / sky_supply
    y2_undiscounted_gp_price = y2_ttm_gp * GP_MULTIPLE / sky_supply
    y2_undiscounted_np_price = y2_ttm_np_floor * np_multiple / sky_supply
    disc = (1.0 + DISCOUNT_RATE) ** 3
    pv_gp = undiscounted_gp_price / disc
    pv_np = undiscounted_np_price / disc

    def pack(arr):
        return {
            "p25": float(np.percentile(arr, 25)),
            "p50": float(np.percentile(arr, 50)),
            "p75": float(np.percentile(arr, 75)),
            "p90": float(np.percentile(arr, 90)),
            "ev_mean": float(np.mean(arr)),
            "prob_spot_justified": float(np.mean(arr >= spot)),
            "prob_up_30": float(np.mean(arr >= 1.3 * spot)),
            "prob_down_30": float(np.mean(arr <= 0.7 * spot)),
            "prob_3x": float(np.mean(arr >= 3 * spot)),
        }

    def distribution(arr):
        return {
            f"p{q}": float(np.percentile(arr, q))
            for q in (5, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 95)
        }

    y3_money_market_tvl = denominator_path[:, -1]
    y3_total_supply = usds + dai
    y3_avg_money_market_tvl = denominator_path[:, -12:].mean(axis=1)
    y3_avg_total_supply = monthly_total_supply[:, -12:].mean(axis=1)
    y3_avg_usds_supply = monthly_usds_supply[:, -12:].mean(axis=1)

    return {
        "opex": opex,
        "np_multiple": np_multiple,
        "pv_gp_10x": pack(pv_gp),
        "pv_np": pack(pv_np),
        "pv_gp_10x_distribution": distribution(pv_gp),
        "pv_np_distribution": distribution(pv_np),
        "undiscounted_gp_price": pack(undiscounted_gp_price),
        "undiscounted_np_price": pack(undiscounted_np_price),
        "y2_undiscounted_gp_price": pack(y2_undiscounted_gp_price),
        "y2_undiscounted_np_price": pack(y2_undiscounted_np_price),
        "y3_ttm_gp": pack(y3_ttm_gp),
        "y3_ttm_net_profit": pack(y3_ttm_np),
        "y3_ttm_gross_income": pack(y3_ttm_gross_income),
        "y3_ttm_savings_cost": pack(y3_ttm_savings_cost),
        "y3_ttm_stusds_cost": pack(y3_ttm_stusds_cost),
        "y3_usds_supply": pack(usds),
        "y3_total_stable_supply": pack(y3_total_supply),
        "y3_money_market_tvl": pack(y3_money_market_tvl),
        "y3_avg_money_market_tvl": pack(y3_avg_money_market_tvl),
        "y3_avg_total_stable_supply": pack(y3_avg_total_supply),
        "y3_avg_usds_supply": pack(y3_avg_usds_supply),
        "accumulated_treasury_cash": pack(accumulated_treasury_cash),
        "mc_path": {
            "start_money_market_tvl_p50": float(np.percentile(start_denominator, 50)),
            "start_money_market_tvl_p25": float(np.percentile(start_denominator, 25)),
            "start_money_market_tvl_p75": float(np.percentile(start_denominator, 75)),
            "start_money_market_tvl_rule": "uniform random draw from historical monthly money-market/yield-vault TVL",
            "start_money_market_tvl_months": len(money_market_months),
            "current_money_market_tvl": current_denominator,
            "y3_money_market_tvl_p50": float(np.percentile(y3_money_market_tvl, 50)),
            "y3_total_stable_supply_p50": float(np.percentile(y3_total_supply, 50)),
            "eoy3_money_market_share": float(share_path[-1]),
            "ms_momentum_initial": float(momentum),
            "velocity_ensemble": velocity,
            "share_cap": _SKY_MONEY_MARKET_SHARE_CAP,
            "rule": "sample starting money-market/yield-vault TVL uniformly from historical monthly denominators; sample monthly denominator shocks; apply Sky MS90 share seed; 70% MS30/MS180 + 30% MS7/MS30 velocity ensemble decays over 12M; DAI stays flat and USDS fills the remainder",
        },
    }


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 SKY valuation"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_sky_price_history():
    """Return (price_by_date, mcap_by_date) from CoinGecko."""
    try:
        url = f"{_CG_BASE}/coins/sky/market_chart?vs_currency=usd&days=365&interval=daily"
        hdrs = {"User-Agent": "Mozilla/5.0"}
        if _CG_KEY:
            hdrs["x-cg-pro-api-key"] = _CG_KEY
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        price_by_date: dict = {}
        mcap_by_date: dict = {}
        seen_p: set = set()
        for ms, p in d.get("prices", []):
            ds = str(datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date())
            if ds not in seen_p:
                seen_p.add(ds)
                price_by_date[ds] = float(p)
        seen_m: set = set()
        for ms, m_v in d.get("market_caps", []):
            ds = str(datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date())
            if ds not in seen_m:
                seen_m.add(ds)
                mcap_by_date[ds] = float(m_v)
        return price_by_date, mcap_by_date
    except Exception:
        return {}, {}


def compute_sky_hist_charts(ms_full_with_supply, price_by_date, mcap_by_date,
                             sky_supply, DR, gp_multiple, p50_pv):
    """Build hist_charts for SKY: backtest + Mcap/GP secondary + EOY3 money-market share."""
    stable_supply_base = max(TOTAL_STABLE_SUPPLY, 1.0)
    stusds_cost_rate = STUSDS_EXPENSE / stable_supply_base
    net_gp_rate = (
        GROSS_INCOME_YIELD
        - (SAVINGS_RATE * USDS_SAVINGS_PENETRATION)
        - stusds_cost_rate
    )

    # ── EOY3 money-market MS history ─────────────────────────────────────────
    eoy3_ms_out = []
    for row in ms_full_with_supply:
        ms30 = row["ms30"]; ms90 = row["ms90"]; ms180 = row.get("ms180")
        if ms30 is None or ms90 is None:
            continue
        anchor = ms180 if ms180 is not None else ms90
        eoy3 = _ms_eoy3(ms90, ms30, anchor, _SKY_MONEY_MARKET_SHARE_CAP, row.get("ms7"))
        eoy3_ms_out.append({"date": row["date"], "eoy3": round(eoy3, 6),
                             "ms90": round(ms90, 6), "ms30": round(ms30, 6)})

    # ── Secondary chart: Mcap / GP ratio over time ────────────────────────────
    secondary_data = []
    for row in ms_full_with_supply:
        d = row["date"]
        sky_sup_d = row.get("sky_supply", 0.0)
        ann_gp_d = sky_sup_d * net_gp_rate
        mcap = mcap_by_date.get(d)
        if mcap and ann_gp_d > 0:
            ratio = mcap / ann_gp_d
            if 0 < ratio < 2000:
                secondary_data.append({"date": d, "value": round(ratio, 1)})

    # ── Backtest: model-shaped PV from official supply history ───────────────
    pv_raw_list = []
    for row in ms_full_with_supply:
        d = row["date"]
        sky_sup_d = row.get("sky_supply", 0.0)
        ann_gp_d = sky_sup_d * net_gp_rate
        pv_raw = ann_gp_d * gp_multiple / ((1 + DR) ** 3) / max(sky_supply, 1.0)
        price = price_by_date.get(d)
        if price and price > 0 and pv_raw > 0:
            pv_raw_list.append((d, pv_raw, price))

    if not pv_raw_list:
        return {"backtest": {"chart": [], "signals": {}, "latest_signal": "NEUTRAL", "last_realized_row": None},
                "secondary_chart": {"label": "Mcap / GP", "subtitle": "", "note": "", "unit": "x",
                                    "data": secondary_data},
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
            "label": "Historical Mcap / GP (money-market-share proxy)",
            "subtitle": "Market cap ÷ (money-market TVL × Sky share × net GP/supply rate)",
            "note": "GP proxy = official Sky supply × (gross-income yield − savings penetration × savings rate − stUSDS cost rate). Fixed rates.",
            "unit": "x",
            "data": secondary_data,
        },
        "eoy3_ms": eoy3_ms_out,
    }


def run() -> dict:
    """Fetch live SKY market data, run MC model, return standardized result dict."""
    # Live market data — fallback to locked values if CoinGecko is unavailable
    try:
        spot, mcap, fdv, sky_supply = _fetch_cg_market()
    except Exception as e:
        print(f"[SKY] CoinGecko fetch failed ({e}); using fallback market data")
        spot, mcap, fdv, sky_supply = _FALLBACK_SPOT, _FALLBACK_MCAP, _FALLBACK_FDV, _FALLBACK_SUPPLY

    # ── Official Sky supply + money-market share ─────────────────────────────
    official_supply = {
        "date": "2026-05-08",
        "usds_supply": USDS_SUPPLY,
        "dai_supply": DAI_SUPPLY,
        "total_sky_stable_supply": TOTAL_STABLE_SUPPLY,
        "source": "locked fallback",
    }
    ms_snapshot, ms_history, ms_full_hist = None, [], []
    try:
        supply_snapshot_raw, supply_hist = _fetch_sky_supply_official()
        official_supply = _official_supply_snapshot(supply_snapshot_raw)
        ms_snapshot, ms_history, ms_full_hist = _compute_money_market_ms(supply_hist)
    except Exception as e:
        print(f"[SKY] Sky official supply fetch failed ({e}); using locked supply fallback")

    usds_start = float(official_supply["usds_supply"])
    dai_start = float(official_supply["dai_supply"])
    total_start = usds_start + dai_start

    scenarios_raw = {}
    for name, opex in OPEX_SCENARIOS.items():
        scenarios_raw[name] = _simulate(
            opex, NP_MULTIPLE, spot, sky_supply, usds_start, dai_start, ms_snapshot
        )

    current_gp = GROSS_INCOME - SAVINGS_EXPENSE - STUSDS_EXPENSE
    base_opex = OPEX_SCENARIOS["base_70m_opex"]
    current_np_base = current_gp - base_opex
    net_gp_rate = current_gp / TOTAL_STABLE_SUPPLY
    mcap_current_gp = mcap / current_gp if current_gp > 0 else float("nan")
    fdv_current_gp = fdv / current_gp if current_gp > 0 else float("nan")

    def _make_scenario(key, label, is_primary, raw_key, value_key):
        raw = scenarios_raw[raw_key]
        s = scenarios_raw[raw_key][value_key]
        price_key = "undiscounted_gp_price" if value_key == "pv_gp_10x" else "undiscounted_np_price"
        y2_price_key = "y2_undiscounted_gp_price" if value_key == "pv_gp_10x" else "y2_undiscounted_np_price"
        dist_key = "pv_gp_10x_distribution" if value_key == "pv_gp_10x" else "pv_np_distribution"
        y3_price_p50 = raw[price_key]["p50"]
        y3_money_market = raw["y3_money_market_tvl"]
        y2_price = raw[y2_price_key]
        return {
            "key": key,
            "label": label,
            "is_primary": is_primary,
            "pv": {"p25": s["p25"], "p50": s["p50"], "p75": s["p75"], "p90": s["p90"]},
            "ev": s["ev_mean"],
            "prob_above_spot": s["prob_spot_justified"],
            "prob_3x": s["prob_3x"],
            "prob_spot_up_30_2y": y2_price["prob_up_30"],
            "prob_spot_down_30_2y": y2_price["prob_down_30"],
            "y3_price_p50": y3_price_p50,
            "y3_mcap_p50": y3_price_p50 * sky_supply,
            "y3_supply_p50": sky_supply,
            "y3_gp_p50": raw["y3_ttm_gp"]["p50"],
            "y3_gp_by_product_line_p50": {
                "gross_income": raw["y3_ttm_gross_income"]["p50"],
                "savings_cost": -raw["y3_ttm_savings_cost"]["p50"],
                "stusds_cost": -raw["y3_ttm_stusds_cost"]["p50"],
                "net_gp": raw["y3_ttm_gp"]["p50"],
            },
            "y3_daily_mean_tvl_p50": raw["y3_avg_money_market_tvl"]["p50"],
            "y3_avg_total_stable_supply_p50": raw["y3_avg_total_stable_supply"]["p50"],
            "y3_avg_usds_supply_p50": raw["y3_avg_usds_supply"]["p50"],
            "ev_mcap": s["ev_mean"] * sky_supply,
            "burn_3y_est": 0.0,
            "y3_volume": {
                "min": y3_money_market["p25"],
                "avg": y3_money_market["p50"],
                "max": y3_money_market["p75"],
                "eoy_market_share": raw["mc_path"]["eoy3_money_market_share"],
            },
            "y3_total_stable_supply_p50": raw["y3_total_stable_supply"]["p50"],
            "y3_usds_supply_p50": raw["y3_usds_supply"]["p50"],
            "y3_money_market_tvl_p50": y3_money_market["p50"],
            "distribution": raw[dist_key],
        }

    scenarios = [
        _make_scenario("base_np15x", "Base OPEX ($70M), 15× NP", True,  "base_70m_opex", "pv_np"),
        _make_scenario("base_gp10x", "Base OPEX ($70M), 10× GP", False, "base_70m_opex", "pv_gp_10x"),
        _make_scenario("bear_np15x", "Bear OPEX ($90M), 15× NP", False, "bear_90m_opex", "pv_np"),
        _make_scenario("bull_np15x", "Bull OPEX ($50M), 15× NP", False, "bull_50m_opex", "pv_np"),
    ]

    result = {
        "token": "SKY",
        "name": "Sky",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "market": {
            "spot": spot,
            "market_cap": mcap,
            "fdv": fdv,
            "circulating_supply": sky_supply,
            "max_supply": sky_supply,
        },
        "model": {
            "type": "3Y GP/NP Monte Carlo",
            "discount_rate": DISCOUNT_RATE,
            "multiple": NP_MULTIPLE,
            "paths": PATHS,
            "note": (
                "GP = gross income - savings-rate cost - stUSDS expense. "
                "NP = GP - OPEX. HYPE-style path: sampled historical monthly "
                "money-market/yield-vault TVL denominator × sampled monthly shocks × "
                "Sky MS90 share seed; "
                "70% MS30/MS180 + 30% MS7/MS30 velocity ensemble decays over 12M; "
                "DAI supply flat and USDS fills the remainder. Money-market returns are "
                "dampened 0.65 and capped -8%/+10% monthly. Treasury = cumulative positive NP. "
                "Protocol financial rates locked 2026-05-08."
            ),
        },
        "current_gp": {
            "gross_income": GROSS_INCOME,
            "savings_expense": SAVINGS_EXPENSE,
            "stusds_expense": STUSDS_EXPENSE,
            "current_gp": current_gp,
            "base_opex": base_opex,
            "current_np_base_opex": current_np_base,
            "mcap_current_gp": mcap_current_gp,
            "fdv_current_gp": fdv_current_gp,
            "usds_supply": usds_start,
            "dai_supply": dai_start,
            "total_sky_stable_supply": total_start,
            "official_supply_source": official_supply["source"],
            "official_supply_date": official_supply.get("date"),
            "locked_usds_supply": USDS_SUPPLY,
            "locked_dai_supply": DAI_SUPPLY,
            "gross_income_yield_pct": GROSS_INCOME_YIELD * 100,
            "net_gp_yield_pct": net_gp_rate * 100,
            "gross_income_take_rate_bps": GROSS_INCOME_YIELD * 10000,
            "savings_cost_rate_bps": (SAVINGS_EXPENSE / TOTAL_STABLE_SUPPLY) * 10000,
            "stusds_cost_rate_bps": (STUSDS_EXPENSE / TOTAL_STABLE_SUPPLY) * 10000,
            "net_gp_take_rate_bps": net_gp_rate * 10000,
            # Y3 model outputs (base $70M OPEX scenario)
            "y3_gp_p50":          scenarios_raw["base_70m_opex"]["y3_ttm_gp"]["p50"],
            "y3_gross_income_p50": scenarios_raw["base_70m_opex"]["y3_ttm_gross_income"]["p50"],
            "y3_savings_cost_p50": scenarios_raw["base_70m_opex"]["y3_ttm_savings_cost"]["p50"],
            "y3_stusds_cost_p50": scenarios_raw["base_70m_opex"]["y3_ttm_stusds_cost"]["p50"],
            "y3_usds_supply_p50": scenarios_raw["base_70m_opex"]["y3_usds_supply"]["p50"],
            "y3_total_stable_supply_p50": scenarios_raw["base_70m_opex"]["y3_total_stable_supply"]["p50"],
            "y3_avg_money_market_tvl_p50": scenarios_raw["base_70m_opex"]["y3_avg_money_market_tvl"]["p50"],
            "y3_avg_total_stable_supply_p50": scenarios_raw["base_70m_opex"]["y3_avg_total_stable_supply"]["p50"],
            "treasury_cash_p50":  scenarios_raw["base_70m_opex"]["accumulated_treasury_cash"]["p50"],
            "y3_gp_change_vs_current": (
                scenarios_raw["base_70m_opex"]["y3_ttm_gp"]["p50"] / current_gp - 1.0
                if current_gp > 0 else None
            ),
            "y3_total_stable_supply_change_vs_current": (
                scenarios_raw["base_70m_opex"]["y3_total_stable_supply"]["p50"] / total_start - 1.0
                if total_start > 0 else None
            ),
            "y3_usds_supply_change_vs_current": (
                scenarios_raw["base_70m_opex"]["y3_usds_supply"]["p50"] / usds_start - 1.0
                if usds_start > 0 else None
            ),
            "y3_money_market_tvl_change_vs_current": (
                scenarios_raw["base_70m_opex"]["y3_money_market_tvl"]["p50"] /
                scenarios_raw["base_70m_opex"]["mc_path"]["current_money_market_tvl"] - 1.0
                if scenarios_raw["base_70m_opex"]["mc_path"]["current_money_market_tvl"] > 0 else None
            ),
            "mc_path": scenarios_raw["base_70m_opex"]["mc_path"],
            # Money-market / yield-vault market share
            **({"ms7_vs_money_market":   ms_snapshot["ms7"],
                "ms30_vs_money_market":  ms_snapshot["ms30"],
                "ms90_vs_money_market":  ms_snapshot["ms90"],
                "ms180_vs_money_market": ms_snapshot["ms180"],
                "ms30_ms180_trend": (ms_snapshot["ms30"] / ms_snapshot["ms180"])
                                    if ms_snapshot and ms_snapshot["ms30"] and ms_snapshot["ms180"] else None,
                "ms7_ms30_trend": (ms_snapshot["ms7"] / ms_snapshot["ms30"])
                                  if ms_snapshot and ms_snapshot["ms7"] and ms_snapshot["ms30"] else None,
                "velocity_ensemble_monthly": scenarios_raw["base_70m_opex"]["mc_path"]["velocity_ensemble"]["monthly_log_velocity"],
                "velocity_long_component_monthly": scenarios_raw["base_70m_opex"]["mc_path"]["velocity_ensemble"]["long_monthly"],
                "velocity_short_component_monthly": scenarios_raw["base_70m_opex"]["mc_path"]["velocity_ensemble"]["short_monthly"],
                "velocity_long_weight": scenarios_raw["base_70m_opex"]["mc_path"]["velocity_ensemble"]["long_weight"],
                "velocity_short_weight": scenarios_raw["base_70m_opex"]["mc_path"]["velocity_ensemble"]["short_weight"],
                "money_market_tvl": ms_snapshot["money_market_tvl"],
                "eoy3_money_market_share": scenarios_raw["base_70m_opex"]["mc_path"]["eoy3_money_market_share"],
               } if ms_snapshot else {}),
        },
        "scenarios": scenarios,
        "ms_history": ms_history,
        "caveats": [
            "USDS/DAI supply is sourced from Sky's official supply page API; financial rates and savings/stUSDS assumptions remain locked at the prior run.",
            "USDS path now follows broad money-market/yield-vault TVL denominator × Sky share, not DefiLlama stablecoin market share.",
            "No buybacks or SKY supply reduction modeled; treasury accumulates cash only.",
            "Take-rate assumptions are stablecoin economics rates on modeled Sky supply: gross income yield, savings cost, stUSDS cost, and net GP spread.",
            "Savings rate (3.65%) and USDS savings penetration (81.2%) are point-in-time inputs.",
        ],
        "data_freshness": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    # ── Historical charts (backtest / secondary / EOY3 money-market MS) ──────
    try:
        price_hist, mcap_hist = fetch_sky_price_history()
        p50_pv_sky = scenarios_raw["base_70m_opex"]["pv_np"]["p50"]
        result["hist_charts"] = compute_sky_hist_charts(
            ms_full_hist, price_hist, mcap_hist,
            sky_supply, DISCOUNT_RATE, GP_MULTIPLE, p50_pv_sky,
        )
    except Exception:
        pass

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "sky_result.json"), "w") as f:
        json.dump(result, f, indent=2)

    return result
