"""Robinhood (HOOD) valuation agent — 3Y Monte Carlo model.

Four revenue engines:
  1. Crypto TRR:   Binance spot denominator × HOOD crypto MS × ~170bps blended spread.
                   CoinGecko /exchanges/robinhood/volume_chart for live crypto volume.
                   Calibrated Q1-2025: $252M/Q on ~$13B crypto notional ≈ 193bps.
  2. Equities + Options TRR:
                   Regime-switching multiplier on current run-rate (no clean public API
                   for PFOF/options volume per venue; growth modeled via MC multiplier).
                   Calibrated Q1-2025: $218M options + $70M equities = $288M/Q.
  3. Net Interest Revenue (NIR):
                   AUC estimate × cash_ratio × Fed Funds rate (SOFR proxy).
                   Calibrated Q1-2025: $290M/Q on ~$225B AUC, ~6% cash, 4.3% rate.
  4. Other Revenue: Gold subscriptions + credit card + other.
                   Calibrated Q1-2025: $54M/Q, 10% CAGR base.

DR: CAPM-derived (live HOOD vs SPX beta, 5.5% ERP).
Exit multiple: P/Revenue (P/S), log-normal σ=0.30.
Scenarios: Bear (6M decay, 2×P/S) / Base (12M, 4×) / Bull (24M, 7×).
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import time
import urllib.request
from datetime import datetime, timezone, date
from pathlib import Path

import numpy as np

# ── Constants ──────────────────────────────────────────────────────────────────
N_PATHS = 50_000
MONTHS  = 36
SEED    = 42
ERP     = 0.055

# Crypto: blended spread (Q1-2025 calibration: $252M/Q / ~$13B notional ≈ 193bps;
# competition compresses this over time, model uses 170bps as forward base)
CRYPTO_TAKE_BPS   = 170.0
CRYPTO_MS_CAP     = 0.08     # cap HOOD crypto share vs Binance spot at 8%

# NIR: cash as fraction of AUC, and Fed Funds capture rate
CASH_RATIO        = 0.06     # ~6% of AUC kept in cash sweep (observed Q1-2025)
NIR_CAPTURE_RATE  = 0.85     # Robinhood nets ~85% of Fed Funds on cash sweep
SOFR_LONGRUN      = 0.025    # SOFR long-run mean-reversion target (2.5%)

# Other revenue CAGR assumptions by scenario (annualized)
OTHER_CAGR = {"bear": 0.00, "base": 0.10, "bull": 0.20}

PS_SIGMA = 0.30              # log-normal σ around exit P/S center

VEL_LONG_WEIGHT  = 0.70
VEL_SHORT_WEIGHT = 0.30
VEL_MAX_MONTHLY  = 0.08

# 2025-2026 calibration fallbacks (annualized) — updated from Q1-2025 trajectory
# Q1-2025 was $927M/Q; crypto bull market sustained into 2026
_BASE_CRYPTO_ANN    = 2_000_000_000.0   # $2.0B (crypto TRR scaled with 2× volume growth)
_BASE_EQ_OPT_ANN    = 1_500_000_000.0   # $1.5B (options + equities, modest growth)
_BASE_NIR_ANN       = 1_200_000_000.0   # $1.2B (AUC appreciated with bull market)
_BASE_OTHER_ANN     =   350_000_000.0   # $0.35B (Gold + card growth)
_BASE_TOTAL_ANN     = _BASE_CRYPTO_ANN + _BASE_EQ_OPT_ANN + _BASE_NIR_ANN + _BASE_OTHER_ANN

BLOCKWORKS_BINANCE_SPOT_ANNUAL: dict[int, float] = {
    2022: 3.554e12, 2023: 2.941e12, 2024: 7.136e12, 2025: 7.307e12,
}

# (key, label, is_primary, decay_months, ps_center, sbc_dilution_3y)
# P/S calibrated to HOOD's growth premium: bear 4× (down-cycle) / base 10× / bull 18×
SCENARIOS = [
    ("bear", "Bear: activity decline + rate compression", False,  6,  4.0, 1.20),
    ("base", "Base: moderate growth + stable rates",      True,  12, 10.0, 1.15),
    ("bull", "Bull: crypto supercycle + margin expansion",False, 24, 18.0, 1.10),
]

RESULTS_DIR = Path(__file__).parent.parent / "results"
UA = "Mozilla/5.0 Robinhood-valuation"

# ── Fallbacks ─────────────────────────────────────────────────────────────────
_FB_PRICE    = 45.0
_FB_MCAP     = 39_000_000_000.0
_FB_SHARES   = 869_000_000.0
_FB_CRYPTO30 = 4_500_000_000.0   # $4.5B/month Robinhood crypto volume
_FB_BNSPOT30 = 609_000_000_000.0  # $609B/month Binance spot
_FB_AUC      = 200_000_000_000.0  # $200B AUC estimate (Q1-2025: $220B, normalized)
_FB_SOFR     = 0.043
_FB_RF       = 0.044
_FB_HOODV    = 0.038
_FB_SPV      = 0.010


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(url: str, timeout: int = 30) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def _get_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


# ── Data fetch ────────────────────────────────────────────────────────────────

def _fetch_hood_stock() -> tuple[float, float, float]:
    try:
        d = _get("https://query1.finance.yahoo.com/v8/finance/chart/HOOD?range=1d&interval=1d")
        price = float(d["chart"]["result"][0]["meta"]["regularMarketPrice"])
        try:
            qs = _get("https://query2.finance.yahoo.com/v10/finance/quoteSummary/HOOD"
                      "?modules=defaultKeyStatistics,summaryDetail")
            st = qs["quoteSummary"]["result"][0]
            shares = float(
                st["defaultKeyStatistics"].get("sharesOutstanding", {}).get("raw", 0)
                or st["summaryDetail"].get("sharesOutstanding", {}).get("raw", 0)
                or _FB_SHARES
            )
        except Exception:
            shares = _FB_SHARES
        return price, price * shares, shares
    except Exception as e:
        print(f"[HOOD] Yahoo price fetch failed ({e}); using fallback")
        return _FB_PRICE, _FB_MCAP, _FB_SHARES


def _fetch_risk_free_rate() -> float:
    try:
        d = _get("https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX?range=5d&interval=1d")
        return float(d["chart"]["result"][0]["meta"]["regularMarketPrice"]) / 100.0
    except Exception:
        pass
    try:
        txt = _get_text("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10")
        rows = [r for r in csv.DictReader(io.StringIO(txt)) if r.get("DGS10") not in ("", ".")]
        return float(rows[-1]["DGS10"]) / 100.0
    except Exception:
        return _FB_RF


def _fetch_sofr() -> float:
    try:
        txt = _get_text("https://fred.stlouisfed.org/graph/fredgraph.csv?id=SOFR")
        rows = [r for r in csv.DictReader(io.StringIO(txt)) if r.get("SOFR") not in ("", ".")]
        return float(rows[-1]["SOFR"]) / 100.0
    except Exception:
        return _FB_SOFR


def _fetch_capm_inputs() -> tuple[float, float, float]:
    hood_vol, sp_vol, beta = _FB_HOODV, _FB_SPV, None
    hood_rets: dict[str, float] = {}
    sp_rets:   dict[str, float] = {}

    for ticker, store in [("HOOD", hood_rets), ("%5EGSPC", sp_rets)]:
        try:
            d = _get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1y&interval=1d")
            ts_list = d["chart"]["result"][0].get("timestamp", [])
            cl_list = d["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            pairs = [(ts_list[i], cl_list[i]) for i in range(len(ts_list)) if cl_list[i]]
            if len(pairs) >= 30:
                dates  = [date.fromtimestamp(t).isoformat() for t, _ in pairs]
                closes = [c for _, c in pairs]
                log_r  = np.diff(np.log(np.array(closes, dtype=float)))
                for i, r in enumerate(log_r):
                    store[dates[i + 1]] = float(r)
        except Exception:
            pass

    if len(hood_rets) >= 30:
        hood_vol = float(np.std(list(hood_rets.values()), ddof=1))
    if len(sp_rets) >= 30:
        sp_vol = float(np.std(list(sp_rets.values()), ddof=1))

    common = sorted(set(hood_rets) & set(sp_rets))
    if len(common) >= 60:
        h_arr = np.array([hood_rets[d] for d in common])
        s_arr = np.array([sp_rets[d]   for d in common])
        sp_var = float(np.var(s_arr, ddof=1))
        if sp_var > 0:
            beta = float(np.cov(h_arr, s_arr, ddof=1)[0, 1] / sp_var)
    if beta is None:
        beta = 0.35 * (hood_vol / max(sp_vol, 1e-6))

    return hood_vol, sp_vol, beta


def _fetch_robinhood_crypto_volume(days: int = 180) -> list[tuple[float, float]]:
    """Fetch Robinhood crypto exchange volume from CoinGecko (BTC-denominated)."""
    for ex_id in ("robinhood", "robinhood-crypto"):
        try:
            rows = _get(f"https://api.coingecko.com/api/v3/exchanges/{ex_id}/volume_chart?days={days}")
            if rows and len(rows) >= 14:
                return [(float(ts), float(v)) for ts, v in rows]
        except Exception:
            continue
    return []


def _fetch_binance_spot_monthly() -> float:
    try:
        d = _get("https://api.llama.fi/summary/dexs/binance?dataType=dailyVolume", timeout=15)
        rows = sorted(d.get("totalDataChart", []), key=lambda x: x[0])
        total = float(sum(v for _, v in rows[-30:]))
        if total > 1e11:
            return total
    except Exception:
        pass
    return _FB_BNSPOT30


def _fetch_btc_price() -> float:
    try:
        d = _get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd")
        return float(d["bitcoin"]["usd"])
    except Exception:
        return 100_000.0


# ── Market share computation ──────────────────────────────────────────────────

def _velocity_ensemble(ms7: float | None, ms30: float | None, ms180: float | None) -> float:
    long_v = short_v = 0.0
    if ms30 and ms180 and ms180 > 0 and ms30 / ms180 > 0:
        long_v  = math.log(ms30 / ms180) / 6.0
    if ms7 and ms30 and ms30 > 0 and ms7 / ms30 > 0:
        short_v = math.log(ms7 / ms30) / (30.0 / 7.0)
    return float(np.clip(VEL_LONG_WEIGHT * long_v + VEL_SHORT_WEIGHT * short_v,
                         -VEL_MAX_MONTHLY, VEL_MAX_MONTHLY))


def _compute_crypto_ms_data(crypto_history_btc: list, btc_price: float,
                             bn_spot_monthly: float) -> dict:
    bn_daily = bn_spot_monthly / 30.0
    if not crypto_history_btc:
        fallback_ms = _FB_CRYPTO30 / bn_spot_monthly
        return {
            "ms7": fallback_ms, "ms30": fallback_ms, "ms180": fallback_ms,
            "vel_monthly": 0.0, "crypto_30d": _FB_CRYPTO30,
        }

    vols = [v * btc_price for _, v in crypto_history_btc]
    n = len(vols)
    avg7   = sum(vols[-min(7,   n):]) / min(7,   n)
    avg30  = sum(vols[-min(30,  n):]) / min(30,  n)
    avg180 = sum(vols[-min(180, n):]) / min(180, n)

    ms7   = min(avg7   / bn_daily, CRYPTO_MS_CAP) if bn_daily > 0 else None
    ms30  = min(avg30  / bn_daily, CRYPTO_MS_CAP) if bn_daily > 0 else None
    ms180 = min(avg180 / bn_daily, CRYPTO_MS_CAP) if bn_daily > 0 else None

    return {
        "ms7": ms7, "ms30": ms30, "ms180": ms180,
        "vel_monthly": _velocity_ensemble(ms7, ms30, ms180),
        "crypto_30d": avg30 * 30,
    }


# ── Monte Carlo primitives ────────────────────────────────────────────────────

def _regime_paths(monthly_base: float, N: int, rng: np.random.Generator) -> np.ndarray:
    """(N, MONTHS) monthly volume via regime-switching log-normal."""
    log_med = math.log(max(monthly_base, 1.0))
    n_bear, n_base = int(round(N * 0.25)), int(round(N * 0.50))
    n_bull = N - n_bear - n_base
    segs = []
    for n_seg, shift, sig in [(n_bear, -0.80, 0.50), (n_base, 0.00, 0.50), (n_bull, 1.00, 0.50)]:
        if n_seg > 0:
            segs.append(np.exp(rng.normal(log_med + shift, sig, (n_seg, MONTHS))))
    paths = np.vstack(segs)
    rng.shuffle(paths)
    return paths


def _ms_mult_path(vel_monthly: float, decay_months: int) -> np.ndarray:
    path = np.ones(MONTHS)
    acc = 0.0
    for m in range(MONTHS):
        w = max(0.0, 1.0 - m / decay_months) if decay_months > 0 else 0.0
        acc += vel_monthly * w
        path[m] = math.exp(acc)
    return path


def _sofr_path(sofr0: float) -> np.ndarray:
    return np.linspace(sofr0, SOFR_LONGRUN, MONTHS)


def _auc_path(auc0: float, vel_monthly: float, decay_months: int) -> np.ndarray:
    """AUC grows with market; velocity decays over scenario window."""
    path = np.empty(MONTHS)
    s = auc0
    for m in range(MONTHS):
        w = max(0.0, 1.0 - m / decay_months) if decay_months > 0 else 0.0
        s *= math.exp(vel_monthly * w)
        path[m] = s
    return path


# ── Scenario simulation ───────────────────────────────────────────────────────

def _run_scenario(
    sc_key: str, sc_label: str, is_primary: bool,
    decay_months: int, ps_center: float, sbc_dilution: float,
    hood_price: float, shares_out: float, DR: float,
    crypto_ms: float, crypto_vel: float,
    eq_opt_run_rate_monthly: float,
    auc0: float, sofr_path_arr: np.ndarray,
    crypto_denom_paths: np.ndarray,
    eq_opt_paths: np.ndarray,
    other_ann: float,
    rng: np.random.Generator,
) -> dict:
    N = crypto_denom_paths.shape[0]

    # 1. Crypto TRR
    crypto_ms_abs  = np.clip(crypto_ms * _ms_mult_path(crypto_vel, decay_months),
                             0.0, CRYPTO_MS_CAP)
    crypto_rev_m   = crypto_denom_paths * crypto_ms_abs[np.newaxis, :] * (CRYPTO_TAKE_BPS / 10_000)

    # 2. Equities + Options TRR (regime-switching multiplier on run-rate)
    eq_opt_rev_m = eq_opt_paths  # already in monthly $

    # 3. NIR: AUC × cash_ratio × SOFR × NIR_CAPTURE_RATE
    auc_arr = _auc_path(auc0, crypto_vel * 0.5, decay_months)   # AUC grows at half crypto vel
    nir_m   = auc_arr * CASH_RATIO * sofr_path_arr / 12.0 * NIR_CAPTURE_RATE

    # 4. Other revenue: flat compounding
    other_cagr = OTHER_CAGR.get(sc_key, 0.10)
    other_m    = np.array([other_ann / 12.0 * (1 + other_cagr) ** (m / 12) for m in range(MONTHS)])

    # Total monthly revenue per path
    total_m = crypto_rev_m + eq_opt_rev_m + nir_m[np.newaxis, :] + other_m[np.newaxis, :]

    # Y3 TTM (months 25–36)
    y3_crypto  = crypto_rev_m[:, 24:].sum(axis=1)
    y3_eq_opt  = eq_opt_rev_m[:, 24:].sum(axis=1)
    y3_nir     = float(nir_m[24:].sum())
    y3_other   = float(other_m[24:].sum())
    y3_total   = total_m[:, 24:].sum(axis=1)

    # Y2 TTM (months 13–24)
    y2_total = total_m[:, 12:24].sum(axis=1)

    ps_paths  = np.clip(np.exp(rng.normal(math.log(ps_center), PS_SIGMA, N)), 1.0, 20.0)
    y3_shares = shares_out * sbc_dilution
    y2_shares = shares_out * (1.0 + (sbc_dilution - 1.0) * 2.0 / 3.0)

    y3_price_paths = (y3_total * ps_paths) / max(y3_shares, 1.0)
    y2_price_paths = (y2_total * ps_paths) / max(y2_shares, 1.0)
    pv_paths       = y3_price_paths / (1.0 + DR) ** 3

    p25, p50, p75, p90 = (float(np.percentile(pv_paths, p)) for p in (25, 50, 75, 90))

    return {
        "key":        sc_key,
        "label":      sc_label,
        "is_primary": is_primary,
        "pv":         {"p25": p25, "p50": p50, "p75": p75, "p90": p90},
        "ev":         float(np.mean(pv_paths)),
        "prob_above_spot":              float(np.mean(pv_paths       > hood_price)),
        "prob_3x":                      float(np.mean(pv_paths       > 3.0 * hood_price)),
        "prob_spot_up_30_2y":           float(np.mean(y2_price_paths >= 1.3 * hood_price)),
        "prob_spot_down_30_2y":         float(np.mean(y2_price_paths <= 0.7 * hood_price)),
        "prob_y2_undiscounted_up_30":   float(np.mean(y2_price_paths >= 1.3 * hood_price)),
        "prob_y2_undiscounted_down_30": float(np.mean(y2_price_paths <= 0.7 * hood_price)),
        "y3_price_p50":  float(np.percentile(y3_price_paths, 50)),
        "y3_mcap_p50":   float(np.percentile(y3_price_paths, 50)) * y3_shares,
        "y3_supply_p50": float(y3_shares),
        "y3_revenue_p50": float(np.percentile(y3_total, 50)),
        "y3_gp_p50":      float(np.percentile(y3_total, 50)),
        "y3_revenue_by_product_line_p50": {
            "crypto":       float(np.percentile(y3_crypto,  50)),
            "equities_options": float(np.percentile(y3_eq_opt, 50)),
            "net_interest": y3_nir,
            "other":        y3_other,
        },
        "decay_months": decay_months,
        "ps_center":    ps_center,
        "sbc_dilution": sbc_dilution,
    }


# ── Main run ──────────────────────────────────────────────────────────────────

def run() -> dict:
    hood_price, mcap, shares_out = _fetch_hood_stock()
    rf                            = _fetch_risk_free_rate()
    sofr                          = _fetch_sofr()
    hood_vol, sp_vol, beta        = _fetch_capm_inputs()
    btc_price                     = _fetch_btc_price()
    crypto_history_btc            = _fetch_robinhood_crypto_volume(days=180)
    bn_spot_monthly               = _fetch_binance_spot_monthly()

    DR = float(np.clip(rf + ERP * beta, 0.08, 0.50))
    print(f"[HOOD] DR={DR*100:.1f}% rf={rf*100:.2f}% β={beta:.2f} BTC=${btc_price:,.0f}")

    crypto_ms_data = _compute_crypto_ms_data(crypto_history_btc, btc_price, bn_spot_monthly)

    crypto_ms   = crypto_ms_data.get("ms30")       or (_FB_CRYPTO30 / bn_spot_monthly)
    crypto_vel  = crypto_ms_data.get("vel_monthly", 0.0)
    crypto_30d  = crypto_ms_data.get("crypto_30d", _FB_CRYPTO30)

    _ms7   = crypto_ms_data.get("ms7")
    _ms30  = crypto_ms_data.get("ms30")
    _ms180 = crypto_ms_data.get("ms180")
    vel7_30   = (_ms7  / _ms30)  if (_ms7  and _ms30  and _ms30  > 0) else None
    vel30_180 = (_ms30 / _ms180) if (_ms30 and _ms180 and _ms180 > 0) else None

    # Annualized run-rates
    crypto_rev_ann  = crypto_ms * (bn_spot_monthly / 30) * 365 * (CRYPTO_TAKE_BPS / 10_000)
    # AUC: Robinhood reported $220B in Q1-2025; normalize for market level
    # mcap × 5 heuristic does not apply (high P/S growth stock has low AUC/mcap ratio)
    auc_est = _FB_AUC

    eq_opt_run_ann  = _BASE_EQ_OPT_ANN     # no live API; use 2025-2026 calibration
    nir_ann         = auc_est * CASH_RATIO * sofr * NIR_CAPTURE_RATE
    other_ann       = _BASE_OTHER_ANN
    total_rev_ann   = crypto_rev_ann + eq_opt_run_ann + nir_ann + other_ann

    print(f"[HOOD] crypto_ms30={crypto_ms*100:.2f}% vel={crypto_vel*100:.2f}%/mo "
          f"crypto_30d=${crypto_30d/1e9:.1f}B")
    print(f"[HOOD] AUC_est=${auc_est/1e9:.0f}B NIR=${nir_ann/1e9:.2f}B")
    print(f"[HOOD] rev_ann ~${total_rev_ann/1e9:.2f}B "
          f"(crypto ${crypto_rev_ann/1e9:.2f}B + eq/opt ${eq_opt_run_ann/1e9:.2f}B "
          f"+ NIR ${nir_ann/1e9:.2f}B + other ${other_ann/1e9:.2f}B)")

    rng = np.random.default_rng(SEED)
    # Crypto denominator: Binance spot regime-switching
    crypto_denom_paths = _regime_paths(bn_spot_monthly, N_PATHS, rng)
    # Equities + Options: regime-switching around current run-rate (monthly)
    eq_opt_paths = _regime_paths(eq_opt_run_ann / 12.0, N_PATHS, rng)
    sofr_path_arr = _sofr_path(sofr)

    scenario_list: list[dict] = []
    base_sc: dict | None = None

    for sc_key, sc_label, is_primary, decay_months, ps_center, sbc_dilution in SCENARIOS:
        sc_rng = np.random.default_rng(SEED + abs(hash(sc_key)) % 1_000)
        sc = _run_scenario(
            sc_key, sc_label, is_primary, decay_months, ps_center, sbc_dilution,
            hood_price, shares_out, DR,
            crypto_ms, crypto_vel,
            eq_opt_run_ann / 12.0,
            auc_est, sofr_path_arr,
            crypto_denom_paths, eq_opt_paths,
            other_ann,
            sc_rng,
        )
        scenario_list.append(sc)
        if is_primary:
            base_sc = sc
        print(f"[HOOD] {sc_key}: p50=${sc['pv']['p50']:.2f} "
              f"prob_above={sc['prob_above_spot']*100:.1f}%")

    if base_sc is None:
        base_sc = scenario_list[0]

    result = {
        "token":     "HOOD",
        "name":      "Robinhood",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "market": {
            "spot":               hood_price,
            "market_cap":         mcap,
            "fdv":                mcap,
            "circulating_supply": shares_out,
            "max_supply":         shares_out * 1.20,
        },
        "model": {
            "type":          f"3Y Revenue MC ({N_PATHS:,} paths)",
            "discount_rate": DR,
            "multiple":      4.0,
            "paths":         N_PATHS,
            "note": (
                f"DR={DR*100:.1f}% (CAPM: {rf*100:.2f}%rf + 5.5%ERP × β{beta:.2f}). "
                f"Crypto: Binance spot regime-switching × HOOD crypto MS × {CRYPTO_TAKE_BPS:.0f}bps. "
                f"Equities+Options: regime-switching on Q1-2025 calibrated run-rate "
                f"($288M/Q = options $218M + equities $70M). "
                f"NIR: AUC × {CASH_RATIO*100:.0f}% cash × SOFR × {NIR_CAPTURE_RATE*100:.0f}% capture. "
                f"Other: Gold subs + card at {OTHER_CAGR['base']*100:.0f}% CAGR base. "
                f"Exit P/S: log-normal σ=0.30 around bear/base/bull centers (2×/4×/7×). "
                f"{N_PATHS:,} MC paths; real percentiles."
            ),
        },
        "current_gp": {
            "ms7_ms30_trend":    vel7_30,
            "ms30_ms180_trend":  vel30_180,
            # Crypto MS vs Binance spot
            "crypto_ms7_vs_binance":   _ms7,
            "crypto_ms30_vs_binance":  float(crypto_ms),
            "crypto_ms180_vs_binance": _ms180,
            "crypto_vel_monthly":      float(crypto_vel),
            # Volume diagnostics
            "crypto_volume_30d":       float(crypto_30d),
            "bn_spot_volume_30d":      float(bn_spot_monthly),
            # Revenue run-rates (annualized)
            "crypto_revenue_ann":      float(crypto_rev_ann),
            "eq_opt_revenue_ann":      float(eq_opt_run_ann),
            "nir_ann":                 float(nir_ann),
            "other_revenue_ann":       float(other_ann),
            "total_revenue_ann":       float(total_rev_ann),
            # Interest rates
            "sofr_rate":               float(sofr),
            "risk_free_rate":          float(rf),
            # AUC estimate
            "auc_estimate":            float(auc_est),
            "cash_ratio":              float(CASH_RATIO),
            # CAPM
            "hood_daily_vol":          float(hood_vol),
            "sp500_daily_vol":         float(sp_vol),
            "capm_beta":               float(beta),
            "derived_discount_rate":   float(DR),
            # Share data
            "shares_outstanding":      float(shares_out),
            "hood_ps_current":         float(mcap / max(total_rev_ann, 1.0)),
            # Base scenario Y3 summary
            "y3_revenue_p50":          float(base_sc["y3_revenue_p50"]),
            "y3_supply_p50":           float(base_sc["y3_supply_p50"]),
            "y3_crypto_revenue_p50":   float(base_sc["y3_revenue_by_product_line_p50"]["crypto"]),
            "y3_eq_opt_revenue_p50":   float(base_sc["y3_revenue_by_product_line_p50"]["equities_options"]),
            "y3_nir_p50":              float(base_sc["y3_revenue_by_product_line_p50"]["net_interest"]),
            "y3_other_revenue_p50":    float(base_sc["y3_revenue_by_product_line_p50"]["other"]),
        },
        "scenarios":   scenario_list,
        "hist_charts": {},
        "caveats": [
            f"Crypto MS from CoinGecko /exchanges/robinhood; Binance denom ${bn_spot_monthly/1e9:.0f}B/month.",
            f"Equities+Options TRR calibrated Q1-2025 ($288M/Q); no live per-venue PFOF data available.",
            f"NIR modeled as AUC × {CASH_RATIO*100:.0f}% cash × SOFR × {NIR_CAPTURE_RATE*100:.0f}% capture. "
            f"SOFR mean-reverts to 2.5% over 36 months.",
            f"AUC proxy = {auc_est/1e9:.0f}B (5× market cap heuristic); no real-time AUC API.",
            f"Crypto take rate {CRYPTO_TAKE_BPS:.0f}bps (spread-based, compressed from Q1-2025 ~193bps).",
            f"Exit P/S log-normal σ=0.30; {N_PATHS:,} paths; real percentiles.",
            "Regulatory: PFOF ban risk (EU-style) could materially reduce equities/options TRR.",
            "Bitstamp acquisition (2024) adds institutional crypto revenue not modeled separately.",
        ],
        "data_freshness": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    # Embed mcap history from Yahoo Finance
    try:
        h = _get("https://query1.finance.yahoo.com/v8/finance/chart/HOOD?range=90d&interval=1d")
        ts_list = h["chart"]["result"][0].get("timestamp", [])
        cl_list = h["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        result["mcap_history"] = [
            {"date": date.fromtimestamp(ts).isoformat(), "mcap": round(float(cl) * shares_out)}
            for ts, cl in zip(ts_list, cl_list) if cl
        ]
    except Exception:
        result["mcap_history"] = []

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "robinhood_result.json", "w") as f:
        json.dump(result, f, indent=2)

    return result
