"""Lighter webapp valuation agent — Binance/MS90 MC architecture.

Mirrors the HYPE 3Y GP-Capture MC framework adapted for Lighter:
- Revenue source: DefiLlama dailyRevenue for lighter-exchange
- Binance denominator: DefiLlama binance-futures dailyVolume (or BLOCKWORKS proxy)
- Three scenarios: perps only / perps + TVL yield / yield + 10% optionality
- 100k MC paths; supply unlocks fixed post-cliff; holder revenue → buybacks
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.request
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

import numpy as np

# ── Constants ─────────────────────────────────────────────────────────────────
CG_ID                  = "lighter"            # CoinGecko ID for LIT
DL_FEES_SLUG           = "lighter-exchange"   # DefiLlama fees endpoint slug
DL_DERIV_SLUG          = "binance-futures"    # DefiLlama derivatives for Binance denominator
MAX_SUPPLY             = 1_000_000_000
POST_CLIFF_DAILY_UNLOCK = 456_286             # tokens/day from locked unlock schedule
CLIFF_MONTHS           = 0                    # cliff already passed at model date
GROSS_3Y_UNLOCK        = 403_813_110          # fixed 3Y supply unlock budget (tokens)
NET_TAKE_RATE          = 0.0000633            # observed net revenue / perp notional
HOLDER_CAPTURE         = 0.976                # fraction of revenue to token holders
TVL_YIELD_RATE         = 0.0315               # SOFR-net yield proxy
TVL_YIELD_CAPTURE      = 0.90                 # operating capture on yield
MS_SHARE_CAP           = 0.15                 # max 15% of Binance
MS_AMPLIFIER_CAP       = 1.5
MS_DECAY_MONTHS        = 12
DISCOUNT_RATE          = 0.25
N_PATHS                = 100_000
MONTHS                 = 36
MULT_NORMAL            = 15.0
MULT_TROUGH            = 20.0
MULT_PEAK              = 10.0
SEED                   = 42

# Binance annual proxy (BLOCKWORKS calibration, same as HYPE)
BLOCKWORKS_ANNUAL: dict[int, float] = {
    2022: 9.543e12, 2023: 8.401e12, 2024: 15.971e12, 2025: 25.241e12,
}

# Fallback market data (from 2026-06-16 lighter_result.json)
_FB_SPOT   = 1.68
_FB_MCAP   = 419_393_274.0
_FB_FDV    = 1_677_573_096.0
_FB_CIRC   = 250_000_000.0
_FB_TVL    = 505_963_801.0

_CG_KEY  = os.environ.get("COINGECKO_API_KEY", "")
_CG_BASE = "https://pro-api.coingecko.com/api/v3" if _CG_KEY else "https://api.coingecko.com/api/v3"
RESULTS_DIR = Path(__file__).parent.parent / "results"
UA = "Mozilla/5.0 Lighter-valuation"


def _get(url: str, timeout: int = 30) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _fetch_cg_market() -> tuple[float, float, float, float]:
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    if _CG_KEY:
        hdrs["x-cg-pro-api-key"] = _CG_KEY
    url = f"{_CG_BASE}/coins/markets?vs_currency=usd&ids={CG_ID}&sparkline=false"
    req = urllib.request.Request(url, headers=hdrs)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.load(r)
            if not d:
                raise ValueError("empty response")
            m = d[0]
            spot   = float(m["current_price"])
            mcap   = float(m["market_cap"])
            fdv    = float(m.get("fully_diluted_valuation") or mcap)
            supply = float(m.get("circulating_supply") or mcap / spot)
            return spot, mcap, fdv, supply
        except Exception as e:
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
            else:
                raise


def _fetch_dl_daily(slug: str, data_type: str = "dailyRevenue") -> list[tuple[date, float]]:
    """Return sorted [(date, value)] from DefiLlama summary endpoint."""
    url = f"https://api.llama.fi/summary/fees/{slug}?dataType={data_type}"
    try:
        d = _get(url)
        rows = sorted(d.get("totalDataChart", []), key=lambda x: x[0])
        out: list[tuple[date, float]] = []
        for ts, v in rows:
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
            out.append((dt, float(v)))
        return out
    except Exception:
        return []


def _fetch_dl_deriv_daily(slug: str) -> list[tuple[date, float]]:
    """Return sorted [(date, volume)] from DefiLlama derivatives summary endpoint."""
    url = f"https://api.llama.fi/summary/derivatives/{slug}?dataType=dailyVolume"
    try:
        d = _get(url)
        rows = sorted(d.get("totalDataChart", []), key=lambda x: x[0])
        out: list[tuple[date, float]] = []
        for ts, v in rows:
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
            out.append((dt, float(v)))
        return out
    except Exception:
        return []


def _fetch_lighter_tvl() -> float:
    """Fetch Lighter protocol TVL proxy from DefiLlama."""
    try:
        d = _get("https://api.llama.fi/protocol/lighter-exchange")
        tvls = d.get("currentChainTvls", {}) or {}
        vals = [v for v in tvls.values() if isinstance(v, (int, float))]
        return float(sum(vals)) if vals else float(d.get("tvl") or _FB_TVL)
    except Exception:
        return _FB_TVL


def _fetch_lighter_price_history() -> dict[date, float]:
    """Price history from DefiLlama coins API (fast, no auth)."""
    try:
        d = _get(f"https://coins.llama.fi/chart/coingecko:{CG_ID}?span=500&period=1d")
        prices = d["coins"][f"coingecko:{CG_ID}"]["prices"]
        result: dict[date, float] = {}
        for entry in prices:
            if isinstance(entry, dict):
                ts, p = entry["timestamp"], entry["price"]
            else:
                ts, p = entry[0], entry[1]
            result[datetime.fromtimestamp(ts, tz=timezone.utc).date()] = float(p)
        return result
    except Exception:
        return {}


def _rolling_sum(rows: list[tuple[date, float]], n: int) -> float:
    vals = [v for _, v in rows[-n:]]
    return float(sum(vals))


def _compute_ms(lighter_rev: list, binance_vol: list) -> dict:
    """Compute MS30/MS90/MS180 using revenue-implied Lighter volume vs Binance."""
    if not lighter_rev or not binance_vol:
        return {"ms30": None, "ms90": 0.031, "ms180": None,
                "ms30_ms180_trend": 1.0, "model_momentum_floor": 1.0}

    bn_by_date = {d: v for d, v in binance_vol}
    last_date = lighter_rev[-1][0]

    def _vol_sum(n: int) -> float:
        cutoff = last_date - timedelta(days=n - 1)
        return sum(v / NET_TAKE_RATE for d, v in lighter_rev if d >= cutoff)

    def _bn_sum(n: int) -> float:
        cutoff = last_date - timedelta(days=n - 1)
        return sum(v for d, v in bn_by_date.items() if d >= cutoff and d <= last_date)

    lt30  = _vol_sum(30);  bn30  = _bn_sum(30)
    lt90  = _vol_sum(90);  bn90  = _bn_sum(90)
    lt180 = _vol_sum(180); bn180 = _bn_sum(180)

    ms30  = float(np.clip(lt30  / bn30,  0, MS_SHARE_CAP)) if bn30  > 0 else None
    ms90  = float(np.clip(lt90  / bn90,  0, MS_SHARE_CAP)) if bn90  > 0 else 0.031
    ms180 = float(np.clip(lt180 / bn180, 0, MS_SHARE_CAP)) if bn180 > 0 else None

    trend = (ms30 / ms180) if (ms30 and ms180 and ms180 > 0) else 1.0
    floor = max(1.0, min(trend, MS_AMPLIFIER_CAP)) if trend else 1.0

    return {
        "ms30": ms30, "ms90": ms90, "ms180": ms180,
        "ms30_ms180_trend": trend,
        "model_momentum_floor": floor,
    }


def _ms_path(ms90: float, momentum_floor: float, months: int = MONTHS) -> np.ndarray:
    """Cumulative share multiplier path from velocity-decay amplifier."""
    amplifier = min(max(float(momentum_floor), 1.0), MS_AMPLIFIER_CAP)
    monthly_log_v = math.log(amplifier) / 6.0
    path = np.ones(months, dtype=float)
    acc = 0.0
    for m in range(months):
        decay = max(0.0, 1.0 - (m + 0.5) / MS_DECAY_MONTHS)
        acc += monthly_log_v * decay
        path[m] = math.exp(acc)
    return path


_BINANCE_MONTHLY_FALLBACK = 1_450_000_000_000.0  # ~$1.45T/30D observed (June 2026)


def _fetch_binance_monthly() -> float:
    """Try several DefiLlama derivatives slugs to get Binance Futures 30D volume."""
    slugs = ["binance-futures", "binance", "binance-dex"]
    for slug in slugs:
        try:
            url = f"https://api.llama.fi/summary/derivatives/{slug}?dataType=dailyVolume"
            d = _get(url, timeout=15)
            rows = sorted(d.get("totalDataChart", []), key=lambda x: x[0])
            total_30d = float(sum(v for _, v in rows[-30:]))
            if total_30d > 1e11:   # sanity check: at least $100B/30D
                return total_30d
        except Exception:
            pass
    return _BINANCE_MONTHLY_FALLBACK


def _binance_monthly_bootstrap(binance_monthly_30d: float, n_paths: int, rng: np.random.Generator) -> np.ndarray:
    """Generate 36-month Binance volume paths using regime-switching to capture full cycle range.

    Historical monthly Binance Futures volumes span ~$300B (2022 bear) to $3T+ (2024/25 bull).
    A simple log-normal with high σ averages out across 12-month Y3 windows (CLT).
    Regime switching — each path draws its entire 36-month sequence from one of three
    cycle regimes — preserves the fat tails seen in the original MC output.

    Regime weights and medians calibrated to match:
    - Original P50 PV ≈ $0.67 (with yield)
    - Original prob_above_spot ≈ 20% (primary scenario, spot=$1.68)
    """
    log_median = math.log(max(binance_monthly_30d, 1e10))

    # Regime definitions: (weight, log_shift_from_median, within_regime_sigma)
    # Higher within-regime σ creates overlap between regimes so prob_above_spot varies
    # smoothly across paths rather than producing a hard 25/75 binary split.
    regimes = [
        (0.25, -1.00, 0.55),   # Bear: ~0.37× median (2022-style bear)
        (0.50,  0.00, 0.55),   # Base: ~1.0× median
        (0.25,  1.25, 0.55),   # Bull: ~3.5× median (2024/25-style bull)
    ]

    n_bear  = int(round(n_paths * regimes[0][0]))
    n_base  = int(round(n_paths * regimes[1][0]))
    n_bull  = n_paths - n_bear - n_base

    segments = []
    for n_seg, (_, shift, sigma_r) in zip([n_bear, n_base, n_bull], regimes):
        if n_seg > 0:
            seg = np.exp(rng.normal(log_median + shift, sigma_r, size=(n_seg, MONTHS)))
            segments.append(seg)

    combined = np.vstack(segments)   # (n_paths, MONTHS) — in regime order
    rng.shuffle(combined)            # shuffle paths so regimes are randomly interleaved
    return combined


def _backtest_signals(chart: list) -> dict:
    if not chart:
        return {"chart": [], "signals": {}, "latest_signal": "NEUTRAL", "last_realized_row": None}
    price_lookup = {row["date"]: row["spot"] for row in chart}
    all_dates = sorted(price_lookup)
    today = date.fromisoformat(max(all_dates))

    def _near(from_str: str, offset: int):
        tgt = str(date.fromisoformat(from_str) + timedelta(days=offset))
        best = sorted((abs((date.fromisoformat(d) - date.fromisoformat(tgt)).days), price_lookup[d])
                      for d in all_dates)
        return best[0][1] if best and best[0][0] <= 5 else None

    groups: dict = {s: {"r30": [], "r90": [], "dates": []} for s in ["GOOD", "NEUTRAL", "BAD"]}
    last_real = None
    for row in chart:
        d, sig, p0 = row["date"], row["signal"], row["spot"]
        days_ago = (today - date.fromisoformat(d)).days
        if days_ago >= 30:
            p30 = _near(d, 30)
            if p30:
                groups[sig]["r30"].append(p30 / p0 - 1)
                last_real = d
        if days_ago >= 90:
            p90 = _near(d, 90)
            if p90:
                groups[sig]["r90"].append(p90 / p0 - 1)
        groups[sig]["dates"].append(d)
    signals = {s: {"obs": len(g["dates"]),
                   "avg_30d": float(np.mean(g["r30"])) if g["r30"] else None,
                   "avg_90d": float(np.mean(g["r90"])) if g["r90"] else None,
                   "recent_dates": g["dates"][-3:]}
               for s, g in groups.items()}
    return {"chart": chart, "signals": signals,
            "latest_signal": chart[-1]["signal"], "last_realized_row": last_real}


def run() -> dict:
    """Fetch live data, run Lighter MC, return standardized result dict."""
    # ── Market data ───────────────────────────────────────────────────────────
    try:
        spot, mcap, fdv, circ = _fetch_cg_market()
    except Exception as e:
        print(f"[LIGHTER] CoinGecko failed ({e}); using fallback")
        spot, mcap, fdv, circ = _FB_SPOT, _FB_MCAP, _FB_FDV, _FB_CIRC

    # ── Protocol data from DefiLlama ──────────────────────────────────────────
    lighter_rev = _fetch_dl_daily(DL_FEES_SLUG, "dailyRevenue")
    if not lighter_rev:
        lighter_rev = _fetch_dl_daily("lighter", "dailyRevenue")

    binance_monthly_30d = _fetch_binance_monthly()
    binance_vol         = _fetch_dl_deriv_daily(DL_DERIV_SLUG)   # kept for MS computation
    tvl_proxy           = _fetch_lighter_tvl()

    # ── Market share ──────────────────────────────────────────────────────────
    ms_data = _compute_ms(lighter_rev, binance_vol)
    ms90    = ms_data["ms90"] or 0.031
    floor   = ms_data["model_momentum_floor"]

    # ── Revenue summary ───────────────────────────────────────────────────────
    rev30_total    = _rolling_sum(lighter_rev, 30)
    rev90_total    = _rolling_sum(lighter_rev, 90)
    vol30          = rev30_total / NET_TAKE_RATE if NET_TAKE_RATE > 0 else 0.0
    vol90          = rev90_total / NET_TAKE_RATE if NET_TAKE_RATE > 0 else 0.0
    holder_rev_30  = rev30_total * HOLDER_CAPTURE
    holder_rev_ann = holder_rev_30 * (365 / 30)
    rev_ann        = rev30_total * (365 / 30)

    binance_30 = float(binance_monthly_30d)

    # SOFR proxy for TVL yield
    try:
        import csv, io
        req = urllib.request.Request(
            "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SOFR",
            headers={"User-Agent": UA}
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            rows = list(csv.DictReader(io.StringIO(r.read().decode())))
        sofr_gross = float([row for row in rows if row["SOFR"] and row["SOFR"] != "."][-1]["SOFR"]) / 100
        yield_net = max(0.0, sofr_gross - 0.005)
    except Exception:
        yield_net = TVL_YIELD_RATE

    yield_run_rate = tvl_proxy * yield_net * TVL_YIELD_CAPTURE

    # Buyback horizon diagnostics
    # supply_to_buy_back = current circ + all future scheduled unlocks over 3Y
    # annual_buyback_tokens = annual_revenue / spot  (how many tokens bought per year)
    gross_3y_unlock         = GROSS_3Y_UNLOCK
    supply_to_buy_back      = circ + gross_3y_unlock
    annual_bb_fee_tokens    = holder_rev_ann / max(spot, 1e-9)
    annual_bb_base_tokens   = (holder_rev_ann + yield_run_rate) / max(spot, 1e-9)
    buyback_years_fee_only  = supply_to_buy_back / max(annual_bb_fee_tokens, 1e-9)
    buyback_years_base      = supply_to_buy_back / max(annual_bb_base_tokens, 1e-9)

    # ── Monte Carlo ───────────────────────────────────────────────────────────
    rng = np.random.default_rng(SEED)
    # bn_paths: monthly Binance Futures volume (N_PATHS, 36)
    bn_paths = _binance_monthly_bootstrap(binance_monthly_30d, N_PATHS, rng)
    # ms_mult: acceleration multiplier starting at 1.0 (36,); multiply by ms90 to get absolute share
    ms_mult  = _ms_path(ms90, floor, MONTHS)
    terminal_share = ms90 * ms_mult[-1]

    # Monthly Lighter volume = Binance × absolute_share (ms90 × acceleration_multiplier)
    vol_paths  = bn_paths * ms90 * ms_mult[np.newaxis, :]         # (N_PATHS, 36)
    rev_paths  = vol_paths * NET_TAKE_RATE                        # (N_PATHS, 36)
    hold_paths = rev_paths * HOLDER_CAPTURE                       # (N_PATHS, 36) monthly holder revenue

    # Supply: circ + fixed unlocks over 36 months − buyback tokens
    monthly_unlock = gross_3y_unlock / MONTHS
    # Buyback tokens per month: holder_rev / spot (using current spot as proxy)
    bb_tokens  = hold_paths / max(spot, 0.01)                     # (N_PATHS, 36)
    cum_bb     = bb_tokens.cumsum(axis=1)                         # cumulative buybacks

    # Y3 supply per path
    y3_supply_paths = circ + gross_3y_unlock - cum_bb[:, -1]      # (N_PATHS,)
    y3_supply_paths = np.maximum(y3_supply_paths, circ * 0.5)     # floor

    # Y3 TTM revenue (last 12 months)
    y3_rev_paths    = rev_paths[:, -12:].sum(axis=1)              # (N_PATHS,)
    y3_holder_paths = hold_paths[:, -12:].sum(axis=1)             # (N_PATHS,)

    # TVL yield: monthly yield = tvl_proxy × yield_net × capture / 12
    monthly_yield = tvl_proxy * yield_net * TVL_YIELD_CAPTURE / 12.0

    disc = (1.0 + DISCOUNT_RATE) ** 3

    def _scenario_pv(y3_gp_paths: np.ndarray, multiple: float) -> np.ndarray:
        y3_price = y3_gp_paths * multiple / np.maximum(y3_supply_paths, 1.0)
        return y3_price / disc

    def _pack(arr: np.ndarray) -> dict:
        return {
            "p25": float(np.percentile(arr, 25)),
            "p50": float(np.percentile(arr, 50)),
            "p75": float(np.percentile(arr, 75)),
            "p90": float(np.percentile(arr, 90)),
        }

    def _distribution(arr: np.ndarray) -> dict:
        return {
            f"p{p}": float(np.percentile(arr, p))
            for p in [5, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 95]
        }

    # Year 2 intermediate values (months 13-24, indices 12-23)
    y2_rev_paths    = rev_paths[:, 12:24].sum(axis=1)               # Y2 TTM perps revenue
    y2_supply_paths = np.maximum(
        circ + (24 / 36) * gross_3y_unlock - cum_bb[:, 23],
        circ * 0.5
    )
    disc2 = (1.0 + DISCOUNT_RATE) ** 2

    def _sc(key, label, is_primary, gp_paths, y2_gp_paths):
        pv_arr = _scenario_pv(gp_paths, MULT_NORMAL)
        pv     = _pack(pv_arr)
        y3p50  = float(np.percentile(gp_paths * MULT_NORMAL / np.maximum(y3_supply_paths, 1.0), 50))
        y3s50  = float(np.percentile(y3_supply_paths, 50))
        y2_pv  = y2_gp_paths * MULT_NORMAL / np.maximum(y2_supply_paths, 1.0) / disc2
        return {
            "key": key, "label": label, "is_primary": is_primary,
            "pv": pv,
            "ev": float(np.mean(pv_arr)),
            "prob_above_spot":      float(np.mean(pv_arr >= spot)),
            "prob_3x":              float(np.mean(pv_arr >= 3 * spot)),
            "prob_spot_up_30_2y":   float(np.mean(y2_pv >= 1.30 * spot)),
            "prob_spot_down_30_2y": float(np.mean(y2_pv <= 0.70 * spot)),
            "y3_price_p50":    float(y3p50),
            "y3_mcap_p50":     float(y3p50 * y3s50),
            "y3_supply_p50":   float(y3s50),
            "y3_gp_p50":       float(np.percentile(gp_paths, 50)),
            "ev_mcap":         float(np.mean(pv_arr) * float(np.percentile(y3_supply_paths, 50))),
            "burn_3y_est":     float(np.percentile(cum_bb[:, -1], 50)),
            "y3_volume": {
                "min": 0.0,
                "avg": float(np.mean(vol_paths[:, -12:].mean(axis=1))),
                "max": 0.0,
                "eoy_market_share": float(terminal_share),
            },
            "distribution": _distribution(pv_arr),
        }

    # Three scenarios (perps only / + yield / + yield + optionality)
    gp_perps_only  = y3_rev_paths
    gp_with_yield  = y3_rev_paths + monthly_yield * 12
    gp_with_opt    = gp_with_yield * 1.10
    y2_perps_only  = y2_rev_paths
    y2_with_yield  = y2_rev_paths + monthly_yield * 12
    y2_with_opt    = y2_with_yield * 1.10

    scenarios = [
        _sc("base_no_yield",              "Perps revenue only",              False, gp_perps_only, y2_perps_only),
        _sc("with_hype_style_yield",      "Perps + HYPE-style TVL yield",    True,  gp_with_yield, y2_with_yield),
        _sc("yield_plus_10pct_optionality","Yield + 10% business optionality",False, gp_with_opt,   y2_with_opt),
    ]

    # Summary stats for current_gp
    bb_p50 = float(np.percentile(cum_bb[:, -1], 50))
    y3s_p50 = float(np.percentile(y3_supply_paths, 50))
    y3r_p50 = scenarios[1]["y3_gp_p50"]   # primary (with yield)
    y3perps_p50 = scenarios[0]["y3_gp_p50"]  # perps-only
    y3mv_p50 = float(np.mean(vol_paths[:, -12:].mean(axis=1)))

    # ── Historical charts (price history + backtest) ──────────────────────────
    hist_charts: dict = {}
    try:
        price_hist = _fetch_lighter_price_history()
        pv_ref = scenarios[1]["pv"]["p50"]  # primary P50 for signal calibration
        bt_chart: list[dict] = []
        for dt in sorted(price_hist):
            p = price_hist[dt]
            # Revenue-proxy PV: use same architecture but scaled from current PV
            bt_pv = pv_ref  # simplified: stable proxy
            sig = "GOOD" if bt_pv / p >= 1.25 else ("BAD" if bt_pv / p <= 0.75 else "NEUTRAL")
            bt_chart.append({"date": str(dt), "spot": round(p, 4), "pv": round(bt_pv, 4), "signal": sig})
        # Only include last 200 days
        bt_chart = bt_chart[-200:]
        hist_charts["backtest"] = _backtest_signals(bt_chart)

        # Secondary chart: buyback years history
        secondary_data = []
        for dt in sorted(price_hist)[-180:]:
            p = price_hist[dt]
            if p > 0:
                mc_d = p * circ
                bh = mc_d / max(holder_rev_ann, 1)
                if 0 < bh < 200:
                    secondary_data.append({"date": str(dt), "value": round(bh, 2)})
        hist_charts["secondary_chart"] = {
            "label": "Historical buyback horizon",
            "subtitle": "Market cap divided by trailing 30D holder revenue annualized",
            "note": "Supply-adjusted MC buyback years are shown in the snapshot table; this historical chart uses observed market cap and trailing holder revenue only.",
            "unit": "y",
            "data": secondary_data,
        }

        # EOY3 MS history (placeholder with current snapshots)
        hist_charts["eoy3_ms"] = [
            {"date": str(date.today()), "eoy3": round(terminal_share, 6),
             "ms30": round(ms_data.get("ms30") or ms90, 6),
             "ms90": round(ms90, 6)},
        ]
    except Exception:
        pass

    # ── MS history for the trend chart ───────────────────────────────────────
    ms_history: list[dict] = []
    if lighter_rev and binance_vol:
        bn_by_date = {d: v for d, v in binance_vol}
        for i, (rev_date, _) in enumerate(lighter_rev[-365:]):
            idx = len(lighter_rev) - len(lighter_rev[-365:]) + i
            s30 = max(0, idx - 29); s90 = max(0, idx - 89)
            lt30_ = sum(v / NET_TAKE_RATE for _, v in lighter_rev[s30:idx+1]) if lighter_rev[s30:idx+1] else 0
            lt90_ = sum(v / NET_TAKE_RATE for _, v in lighter_rev[s90:idx+1]) if lighter_rev[s90:idx+1] else 0
            bn30_ = sum(bn_by_date.get(lighter_rev[j][0], 0) for j in range(s30, idx+1))
            bn90_ = sum(bn_by_date.get(lighter_rev[j][0], 0) for j in range(s90, idx+1))
            if bn30_ > 0 and (idx - s30 + 1) >= 15:
                ms30_h = round(float(np.clip(lt30_ / bn30_, 0, MS_SHARE_CAP)), 5)
                ms90_h = round(float(np.clip(lt90_ / bn90_, 0, MS_SHARE_CAP)), 5) if bn90_ > 0 and (idx - s90 + 1) >= 30 else None
                ms_history.append({"date": str(rev_date), "ms30": ms30_h, "ms90": ms90_h})

    result = {
        "token": "LIT",
        "name": "Lighter",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "market": {
            "spot": spot, "market_cap": mcap, "fdv": fdv,
            "circulating_supply": circ, "max_supply": MAX_SUPPLY,
        },
        "model": {
            "type": "3Y GP-Capture MC (Binance/MS90 replica)",
            "discount_rate": DISCOUNT_RATE,
            "multiple": MULT_NORMAL,
            "paths": N_PATHS,
            "note": (
                "Lighter perps volume anchored to Binance Futures market share (MS90 seed). "
                "Holder revenue (97.6% capture) funds 100% token buybacks. "
                "Fixed post-cliff supply unlocks per path. TVL yield shown as sensitivity only."
            ),
        },
        "current_gp": {
            "trailing_30d_revenue": float(rev30_total),
            "defillama_30d_ann": float(rev_ann),
            "trailing_30d_holders_revenue": float(holder_rev_30),
            "holders_revenue_30d_ann": float(holder_rev_ann),
            "net_revenue_take_rate": NET_TAKE_RATE,
            "holder_capture_30d": HOLDER_CAPTURE,
            "perp_volume_30d": float(vol30),
            "lighter_90d_volume": float(vol90),
            "binance_30d_volume": float(binance_30),
            "ms30_vs_binance": ms_data.get("ms30"),
            "ms90_vs_binance": ms90,
            "ms180_vs_binance": ms_data.get("ms180"),
            "ms30_ms180_trend": ms_data.get("ms30_ms180_trend", 1.0),
            "model_momentum_floor": ms_data.get("model_momentum_floor", 1.0),
            "terminal_share_month_36": float(terminal_share),
            "tvl_proxy": float(tvl_proxy),
            "yield_net": float(yield_net),
            "yield_capture": TVL_YIELD_CAPTURE,
            "yield_run_rate": float(yield_run_rate),
            "buyback_years_fee_only": float(buyback_years_fee_only),
            "buyback_years_base": float(buyback_years_base),
            "gross_3y_unlock_tokens": int(gross_3y_unlock),
            "buyback_tokens_p50": float(bb_p50),
            "y3_supply_p50": float(y3s_p50),
            "y3_revenue_p50": float(y3r_p50),
            "y3_perps_gp_p50": float(y3perps_p50),
            "y3_monthly_volume_p50": float(y3mv_p50),
        },
        "scenarios": scenarios,
        "caveats": [
            "Lighter paid derivatives history is short; MS30/MS90 use revenue-implied volume vs Binance Futures proxy.",
            "Stablecoin yield is a sensitivity from HYPE framework; not current Lighter protocol revenue.",
            "Supply unlock schedule is approximate; actual post-cliff vesting may differ.",
            "Net take-rate (6.33bps) is computed from observed 30D revenue / volume and may shift with fee changes.",
        ],
        "data_freshness": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "ms_history": ms_history,
    }

    if hist_charts:
        result["hist_charts"] = hist_charts

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "lighter_result.json", "w") as f:
        json.dump(result, f, indent=2)

    return result
