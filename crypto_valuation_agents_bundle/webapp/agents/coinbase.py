"""Coinbase (COIN) valuation agent — 3Y Monte Carlo model.

Three-engine simulation:
  1. Spot:        Binance denominator (regime-switching) × Coinbase spot MS
                  (velocity-decay from CoinGecko 180D history) × 32 bps take rate
  2. Derivatives: Deribit denominator (regime-switching) × Coinbase deriv MS
                  (proxy via spot share) × 35 bps take rate
  3. USDC:        Supply (velocity-decay) × SOFR path × 50% CB share × 62% net retention

Three scenarios differ in velocity decay months and exit P/S distribution.
All run 50,000 MC paths; outputs are real percentiles — no fake log-normal bands.

DR: CAPM-derived (live COIN vs SPX beta, 5.5% ERP).
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

SPOT_TAKE_BPS  = 32.0
DERIV_TAKE_BPS = 35.0
SPOT_MS_CAP    = 0.25
DERIV_MS_CAP   = 0.15

# USDC: calibrated to 2024 actuals ($910M net on $56B supply @ 5.3% SOFR)
USDC_CB_SHARE  = 0.50
USDC_NET_RATIO = 0.62

OTHER_SERVICES_RATIO = 0.17   # staking/custody/subs/Base as % of spot+deriv rev
SOFR_LONGRUN         = 0.025  # long-run neutral SOFR
PS_SIGMA             = 0.30   # log-normal σ around exit P/S center

VEL_LONG_WEIGHT  = 0.70       # ms30/ms180 component
VEL_SHORT_WEIGHT = 0.30       # ms7/ms30 component
VEL_MAX_MONTHLY  = 0.08       # cap on monthly log velocity

DERIV_SPOT_PROXY = 0.042      # CB deriv vol / CB spot vol (Q1-2025 empirical)

BLOCKWORKS_BINANCE_SPOT_ANNUAL: dict[int, float] = {
    2022: 3.554e12, 2023: 2.941e12, 2024: 7.136e12, 2025: 7.307e12,
}

# (key, label, is_primary, decay_months, ps_center, sbc_dilution_3y)
SCENARIOS = [
    ("bear", "Bear: velocity decays to 0 by M6",  False,  6,  4.0, 1.25),
    ("base", "Base: velocity decays to 0 by M12", True,  12,  7.0, 1.15),
    ("bull", "Bull: velocity decays to 0 by M24", False, 24, 11.0, 1.10),
]

RESULTS_DIR = Path(__file__).parent.parent / "results"
UA = "Mozilla/5.0 Coinbase-valuation"

# ── Fallbacks ─────────────────────────────────────────────────────────────────
_FB_PRICE   = 280.0
_FB_MCAP    = 68_000_000_000.0
_FB_SHARES  = 243_000_000.0
_FB_SPOT30  = 130_000_000_000.0
_FB_DER30   = 8_000_000_000.0
_FB_DER30DL = 200_000_000_000.0
_FB_USDC    = 58_000_000_000.0
_FB_SOFR    = 0.043
_FB_RF      = 0.045
_FB_COINV   = 0.040
_FB_SPV     = 0.010
_FB_BTC     = 100_000.0


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

def _fetch_coin_stock() -> tuple[float, float, float]:
    try:
        d = _get("https://query1.finance.yahoo.com/v8/finance/chart/COIN?range=1d&interval=1d")
        price = float(d["chart"]["result"][0]["meta"]["regularMarketPrice"])
        try:
            qs = _get("https://query2.finance.yahoo.com/v10/finance/quoteSummary/COIN"
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
        print(f"[COIN] Yahoo price fetch failed ({e}); using fallback")
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
    coin_vol, sp_vol, beta = _FB_COINV, _FB_SPV, None
    coin_rets: dict[str, float] = {}
    sp_rets:   dict[str, float] = {}

    for ticker, store in [("COIN", coin_rets), ("%5EGSPC", sp_rets)]:
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

    if len(coin_rets) >= 30:
        coin_vol = float(np.std(list(coin_rets.values()), ddof=1))
    if len(sp_rets) >= 30:
        sp_vol = float(np.std(list(sp_rets.values()), ddof=1))

    common = sorted(set(coin_rets) & set(sp_rets))
    if len(common) >= 60:
        c_arr = np.array([coin_rets[d] for d in common])
        s_arr = np.array([sp_rets[d]   for d in common])
        sp_var = float(np.var(s_arr, ddof=1))
        if sp_var > 0:
            beta = float(np.cov(c_arr, s_arr, ddof=1)[0, 1] / sp_var)
    if beta is None:
        beta = 0.35 * (coin_vol / max(sp_vol, 1e-6))

    return coin_vol, sp_vol, beta


def _fetch_btc_price() -> float:
    try:
        d = _get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd")
        return float(d["bitcoin"]["usd"])
    except Exception:
        return _FB_BTC


def _fetch_coinbase_spot_history(days: int = 180) -> list[tuple[float, float]]:
    """Return [(timestamp_ms, btc_volume)] from CoinGecko exchange volume chart."""
    for ex_id in ("gdax", "coinbase-exchange"):
        try:
            rows = _get(f"https://api.coingecko.com/api/v3/exchanges/{ex_id}/volume_chart?days={days}")
            if rows and len(rows) >= 30:
                return [(float(ts), float(v)) for ts, v in rows]
        except Exception:
            continue
    return []


def _fetch_coinbase_cde_deriv_history() -> list[tuple[str, float]]:
    """Return [(date_str, usd_volume)] from Coinbase's own public API for CDE futures.

    Coinbase Derivatives Exchange (CDE, formerly FairX) is CFTC-regulated.
    The public brokerage market API requires no authentication for market data.
    Candle volume is in contracts; we convert to USD via contract_size × close_price.
    This does NOT cover Coinbase International Exchange (CIE) perps — no public API.
    """
    CB_API = "https://api.coinbase.com/api/v3/brokerage/market"
    try:
        products = _get(f"{CB_API}/products?product_type=FUTURE&limit=250")
        items = products if isinstance(products, list) else products.get("products", [])
    except Exception as e:
        print(f"[COIN] CDE product list failed ({e})")
        return []

    daily_totals: dict[str, float] = {}
    fetched = 0
    for p in items:
        pid = p.get("product_id") or p.get("id", "")
        if not pid:
            continue
        # contract_size: BTC perp = 0.01, ETH perp = 0.1, others vary
        contract_size = float(p.get("contract_size") or p.get("base_increment") or 0)
        if contract_size <= 0:
            continue
        try:
            candles = _get(f"{CB_API}/products/{pid}/candles?granularity=ONE_DAY")
            rows = candles if isinstance(candles, list) else candles.get("candles", [])
            if not rows:
                continue
            for row in rows:
                # row may be dict or list [start, low, high, open, close, volume]
                if isinstance(row, dict):
                    ts    = int(row.get("start", 0))
                    close = float(row.get("close", 0))
                    vol   = float(row.get("volume", 0))
                elif isinstance(row, (list, tuple)) and len(row) >= 6:
                    ts, _, _, _, close, vol = int(row[0]), *row[1:5], float(row[5])
                else:
                    continue
                if ts <= 0 or vol <= 0 or close <= 0:
                    continue
                day = date.fromtimestamp(ts).isoformat()
                usd_vol = vol * contract_size * close
                daily_totals[day] = daily_totals.get(day, 0.0) + usd_vol
            fetched += 1
            time.sleep(0.15)   # ~6 req/s — well within public rate limits
        except Exception:
            continue

    if not daily_totals:
        return []
    print(f"[COIN] CDE deriv: {fetched} products fetched, "
          f"{len(daily_totals)} days of history")
    return sorted(daily_totals.items())


def _fetch_deribit_history() -> list[float]:
    """Return list of daily Deribit volumes sorted oldest→newest."""
    try:
        d = _get("https://api.llama.fi/summary/derivatives/deribit?dataType=dailyVolume")
        rows = sorted(d.get("totalDataChart", []), key=lambda x: x[0])
        return [float(v) for _, v in rows]
    except Exception:
        return []


def _fetch_usdc_supply() -> float:
    try:
        coins = _get("https://stablecoins.llama.fi/stablecoins?includePrices=false")
        for c in coins.get("peggedAssets", []):
            if c.get("symbol", "").upper() == "USDC":
                circ = c.get("circulating", {})
                supply = float(
                    circ.get("peggedUSD") or
                    sum(v for v in circ.values() if isinstance(v, (int, float)))
                )
                if supply > 1e9:
                    return supply
    except Exception:
        pass
    return _FB_USDC


def _fetch_usdc_velocity() -> float:
    """Observed monthly log growth rate of USDC supply (last ~180 days)."""
    try:
        coins = _get("https://stablecoins.llama.fi/stablecoins?includePrices=false")
        usdc_id = next((c["id"] for c in coins.get("peggedAssets", [])
                        if c.get("symbol", "").upper() == "USDC"), None)
        if not usdc_id:
            return 0.02
        hist = _get(f"https://stablecoins.llama.fi/stablecoincharts/all?stablecoin={usdc_id}")
        if not hist or len(hist) < 30:
            return 0.02
        recent = hist[-180:]
        supplies = [float(e.get("totalCirculating", {}).get("peggedUSD", 0)) for e in recent]
        supplies = [s for s in supplies if s > 1e9]
        if len(supplies) < 2:
            return 0.02
        months = len(supplies) / 30.0
        return float(np.clip(math.log(supplies[-1] / supplies[0]) / max(months, 1.0), -0.03, 0.05))
    except Exception:
        return 0.02


def _binance_spot_annual() -> float:
    for yr in (2025, 2024):
        if yr in BLOCKWORKS_BINANCE_SPOT_ANNUAL:
            return BLOCKWORKS_BINANCE_SPOT_ANNUAL[yr]
    return 7.307e12


# ── Market share computation ──────────────────────────────────────────────────

def _velocity_ensemble(ms7: float | None, ms30: float | None, ms180: float | None) -> float:
    long_v = short_v = 0.0
    if ms30 and ms180 and ms180 > 0 and ms30 / ms180 > 0:
        long_v  = math.log(ms30 / ms180) / 6.0
    if ms7 and ms30 and ms30 > 0 and ms7 / ms30 > 0:
        short_v = math.log(ms7 / ms30) / (30.0 / 7.0)
    return float(np.clip(VEL_LONG_WEIGHT * long_v + VEL_SHORT_WEIGHT * short_v,
                         -VEL_MAX_MONTHLY, VEL_MAX_MONTHLY))


def _compute_spot_ms_data(spot_history_btc: list, btc_price: float) -> dict:
    bn_daily = _binance_spot_annual() / 365.0
    if not spot_history_btc:
        return {"ms7": None, "ms30": None, "ms180": None,
                "vel_monthly": 0.0, "spot_30d": _FB_SPOT30}

    vols = [v * btc_price for _, v in spot_history_btc]
    n = len(vols)

    avg7   = sum(vols[-min(7,   n):]) / min(7,   n)
    avg30  = sum(vols[-min(30,  n):]) / min(30,  n)
    avg180 = sum(vols[-min(180, n):]) / min(180, n)

    ms7   = min(avg7   / bn_daily, SPOT_MS_CAP)  if bn_daily > 0 else None
    ms30  = min(avg30  / bn_daily, SPOT_MS_CAP)  if bn_daily > 0 else None
    ms180 = min(avg180 / bn_daily, SPOT_MS_CAP)  if bn_daily > 0 else None

    return {
        "ms7": ms7, "ms30": ms30, "ms180": ms180,
        "vel_monthly": _velocity_ensemble(ms7, ms30, ms180),
        "spot_30d": avg30 * 30,
    }


def _compute_deriv_ms_data(deribit_history: list, spot_ms_data: dict,
                           cde_history: list[tuple[str, float]] | None = None) -> dict:
    """Compute CB derivatives market share vs Deribit.

    Uses real CDE volume history when available (Coinbase public API).
    Falls back to the 4.2% spot proxy when CDE data is insufficient.
    Note: CDE covers CFTC-regulated US venue only; CIE (international perps)
    has no public API — total CB derivatives share is therefore understated when
    CIE is excluded.
    """
    ms30_spot  = spot_ms_data.get("ms30")  or 0.04
    ms7_spot   = spot_ms_data.get("ms7")   or ms30_spot
    ms180_spot = spot_ms_data.get("ms180") or ms30_spot

    deribit_ok = deribit_history and len(deribit_history) >= 30

    # ── Real CDE data path ────────────────────────────────────────────────────
    if cde_history and len(cde_history) >= 30:
        cde_vols = [v for _, v in sorted(cde_history)]
        n = len(cde_vols)

        cb7   = sum(cde_vols[-min(7,   n):]) / min(7,   n)
        cb30  = sum(cde_vols[-min(30,  n):]) / min(30,  n)
        n180  = min(180, n)
        cb180 = sum(cde_vols[-n180:]) / n180

        if deribit_ok:
            dl7   = sum(deribit_history[-7:])  / 7
            dl30  = sum(deribit_history[-30:]) / 30
            dl180 = sum(deribit_history[-min(180, len(deribit_history)):]) / min(180, len(deribit_history))
        else:
            dl7 = dl30 = dl180 = _FB_DER30DL / 30.0

        ms7   = min(cb7   / dl7,   DERIV_MS_CAP) if dl7   > 0 else None
        ms30  = min(cb30  / dl30,  DERIV_MS_CAP) if dl30  > 0 else None
        ms180 = min(cb180 / dl180, DERIV_MS_CAP) if dl180 > 0 else None

        print(f"[COIN] CDE deriv MS (real): 7D={ms7 and f'{ms7*100:.2f}%'} "
              f"30D={ms30 and f'{ms30*100:.2f}%'} "
              f"180D={ms180 and f'{ms180*100:.2f}%'}")
        return {
            "ms7": ms7, "ms30": ms30, "ms180": ms180,
            "vel_monthly": _velocity_ensemble(ms7, ms30, ms180),
            "deriv_30d":   cb30 * 30,
            "deribit_30d": dl30 * 30,
            "source": "cde_api",
        }

    # ── Spot-proxy fallback ───────────────────────────────────────────────────
    bn_daily = _binance_spot_annual() / 365.0

    if not deribit_ok:
        dl_daily = _FB_DER30DL / 30.0
        cb_d_daily = ms30_spot * bn_daily * DERIV_SPOT_PROXY
        ms = min(cb_d_daily / dl_daily, DERIV_MS_CAP) if dl_daily > 0 else 0.04
        return {"ms7": ms, "ms30": ms, "ms180": ms, "vel_monthly": 0.0,
                "deriv_30d": cb_d_daily * 30, "deribit_30d": _FB_DER30DL,
                "source": "proxy_fallback"}

    dl7   = sum(deribit_history[-7:])  / 7
    dl30  = sum(deribit_history[-30:]) / 30
    n180  = min(180, len(deribit_history))
    dl180 = sum(deribit_history[-n180:]) / n180

    cb7   = ms7_spot   * bn_daily * DERIV_SPOT_PROXY
    cb30  = ms30_spot  * bn_daily * DERIV_SPOT_PROXY
    cb180 = ms180_spot * bn_daily * DERIV_SPOT_PROXY

    ms7   = min(cb7   / dl7,   DERIV_MS_CAP) if dl7   > 0 else None
    ms30  = min(cb30  / dl30,  DERIV_MS_CAP) if dl30  > 0 else None
    ms180 = min(cb180 / dl180, DERIV_MS_CAP) if dl180 > 0 else None

    print(f"[COIN] CDE deriv MS (proxy): 7D={ms7 and f'{ms7*100:.2f}%'} "
          f"30D={ms30 and f'{ms30*100:.2f}%'}")
    return {
        "ms7": ms7, "ms30": ms30, "ms180": ms180,
        "vel_monthly": _velocity_ensemble(ms7, ms30, ms180),
        "deriv_30d":   cb30 * 30,
        "deribit_30d": dl30 * 30,
        "source": "proxy_spot",
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
    """Cumulative MS multiplier (MONTHS,) with linear velocity decay."""
    path = np.ones(MONTHS)
    acc = 0.0
    for m in range(MONTHS):
        w = max(0.0, 1.0 - m / decay_months) if decay_months > 0 else 0.0
        acc += vel_monthly * w
        path[m] = math.exp(acc)
    return path


def _usdc_supply_path(supply0: float, vel_monthly: float, decay_months: int) -> np.ndarray:
    """Deterministic USDC supply path with velocity decaying to 0 by decay_months."""
    path = np.empty(MONTHS)
    s = supply0
    for m in range(MONTHS):
        w = max(0.0, 1.0 - m / decay_months) if decay_months > 0 else 0.0
        s *= math.exp(vel_monthly * w)
        path[m] = s
    return path


def _sofr_path(sofr0: float) -> np.ndarray:
    """Linear mean-reversion from current SOFR to long-run over 36 months."""
    return np.linspace(sofr0, SOFR_LONGRUN, MONTHS)


# ── Scenario simulation ───────────────────────────────────────────────────────

def _run_scenario(
    sc_key: str, sc_label: str, is_primary: bool,
    decay_months: int, ps_center: float, sbc_dilution: float,
    coin_price: float, shares_out: float, DR: float,
    spot_ms: float,  spot_vel: float,
    deriv_ms: float, deriv_vel: float,
    spot_denom_paths: np.ndarray,
    deriv_denom_paths: np.ndarray,
    usdc_supply: float, usdc_vel: float,
    sofr_path_arr: np.ndarray,
    rng: np.random.Generator,
) -> dict:
    N = spot_denom_paths.shape[0]

    # MS multiplier paths (deterministic per scenario, broadcast over N)
    spot_ms_abs  = np.clip(spot_ms  * _ms_mult_path(spot_vel,  decay_months), 0.0, SPOT_MS_CAP)
    deriv_ms_abs = np.clip(deriv_ms * _ms_mult_path(deriv_vel, decay_months), 0.0, DERIV_MS_CAP)

    # Monthly revenue paths (N, 36)
    spot_rev_m  = spot_denom_paths  * spot_ms_abs[np.newaxis, :]  * (SPOT_TAKE_BPS  / 10_000)
    deriv_rev_m = deriv_denom_paths * deriv_ms_abs[np.newaxis, :] * (DERIV_TAKE_BPS / 10_000)
    tx_rev_m    = spot_rev_m + deriv_rev_m
    other_rev_m = tx_rev_m * OTHER_SERVICES_RATIO

    # USDC monthly GP (deterministic (36,)): supply × annual_SOFR/12 × share × net_ratio
    usdc_path_m  = _usdc_supply_path(usdc_supply, usdc_vel, decay_months)
    usdc_gp_m    = usdc_path_m * sofr_path_arr / 12.0 * USDC_CB_SHARE * USDC_NET_RATIO

    # Total monthly (N, 36)
    total_m = tx_rev_m + other_rev_m + usdc_gp_m[np.newaxis, :]

    # Y3 TTM = sum months 25–36  (12 months → annual)
    y3_total  = total_m[:, 24:].sum(axis=1)
    y3_spot   = spot_rev_m[:, 24:].sum(axis=1)
    y3_deriv  = deriv_rev_m[:, 24:].sum(axis=1)
    y3_other  = other_rev_m[:, 24:].sum(axis=1)
    y3_usdc   = float(usdc_gp_m[24:].sum())       # deterministic scalar

    # Y2 TTM = sum months 13–24
    y2_total = total_m[:, 12:24].sum(axis=1)

    # Exit multiple: stochastic log-normal around scenario center
    ps_paths = np.clip(np.exp(rng.normal(math.log(ps_center), PS_SIGMA, N)), 2.0, 25.0)

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
        "prob_above_spot":              float(np.mean(pv_paths       > coin_price)),
        "prob_3x":                      float(np.mean(pv_paths       > 3.0 * coin_price)),
        "prob_spot_up_30_2y":           float(np.mean(y2_price_paths >= 1.3 * coin_price)),
        "prob_spot_down_30_2y":         float(np.mean(y2_price_paths <= 0.7 * coin_price)),
        "prob_y2_undiscounted_up_30":   float(np.mean(y2_price_paths >= 1.3 * coin_price)),
        "prob_y2_undiscounted_down_30": float(np.mean(y2_price_paths <= 0.7 * coin_price)),
        "y3_price_p50":  float(np.percentile(y3_price_paths, 50)),
        "y3_mcap_p50":   float(np.percentile(y3_price_paths, 50)) * y3_shares,
        "y3_supply_p50": float(y3_shares),
        "y3_revenue_p50": float(np.percentile(y3_total, 50)),
        "y3_revenue_by_product_line_p50": {
            "spot":          float(np.percentile(y3_spot,  50)),
            "derivatives":   float(np.percentile(y3_deriv, 50)),
            "stablecoin_gp": y3_usdc,
            "other_services": float(np.percentile(y3_other, 50)),
        },
        "y3_gp_p50": float(np.percentile(y3_total, 50)),   # compat alias
        # Scenario parameters (for dashboard display)
        "decay_months":  decay_months,
        "ps_center":     ps_center,
        "sbc_dilution":  sbc_dilution,
    }


# ── Main run ──────────────────────────────────────────────────────────────────

def run() -> dict:
    coin_price, mcap, shares_out = _fetch_coin_stock()
    rf                            = _fetch_risk_free_rate()
    sofr                          = _fetch_sofr()
    coin_vol, sp_vol, beta        = _fetch_capm_inputs()
    btc_price                     = _fetch_btc_price()
    spot_history_btc              = _fetch_coinbase_spot_history(days=180)
    cde_deriv_history             = _fetch_coinbase_cde_deriv_history()
    deribit_history               = _fetch_deribit_history()
    usdc_supply                   = _fetch_usdc_supply()
    usdc_vel                      = _fetch_usdc_velocity()

    DR = float(np.clip(rf + ERP * beta, 0.08, 0.50))
    print(f"[COIN] DR={DR*100:.1f}% rf={rf*100:.2f}% β={beta:.2f} BTC=${btc_price:,.0f}")

    spot_ms_data  = _compute_spot_ms_data(spot_history_btc, btc_price)
    deriv_ms_data = _compute_deriv_ms_data(deribit_history, spot_ms_data,
                                           cde_history=cde_deriv_history)

    spot_ms   = spot_ms_data.get("ms30")       or 0.04
    spot_vel  = spot_ms_data.get("vel_monthly", 0.0)
    spot_30d  = spot_ms_data.get("spot_30d",   _FB_SPOT30)

    deriv_ms    = deriv_ms_data.get("ms30")       or 0.04
    deriv_vel   = deriv_ms_data.get("vel_monthly", 0.0)
    deriv_30d   = deriv_ms_data.get("deriv_30d",   _FB_DER30)
    deribit_30d = deriv_ms_data.get("deribit_30d", _FB_DER30DL)

    print(f"[COIN] spot_ms30={spot_ms*100:.2f}% vel={spot_vel*100:.2f}%/mo | "
          f"deriv_ms30={deriv_ms*100:.2f}% | usdc_vel={usdc_vel*100:.2f}%/mo")

    bn_daily = _binance_spot_annual() / 365.0
    spot_rev_ann  = spot_ms  * bn_daily * 365 * (SPOT_TAKE_BPS  / 10_000)
    deriv_rev_ann = deriv_ms * (deribit_30d / 30) * 365 * (DERIV_TAKE_BPS / 10_000)
    usdc_rev_ann  = usdc_supply * sofr * USDC_CB_SHARE * USDC_NET_RATIO
    other_rev_ann = (spot_rev_ann + deriv_rev_ann) * OTHER_SERVICES_RATIO
    total_rev_ann = spot_rev_ann + deriv_rev_ann + usdc_rev_ann + other_rev_ann

    print(f"[COIN] rev_ann ~${total_rev_ann/1e9:.2f}B "
          f"(spot ${spot_rev_ann/1e9:.2f}B + deriv ${deriv_rev_ann/1e9:.2f}B "
          f"+ USDC ${usdc_rev_ann/1e9:.2f}B + other ${other_rev_ann/1e9:.2f}B)")

    # Shared denominator paths (reused across scenarios)
    rng = np.random.default_rng(SEED)
    spot_denom_paths  = _regime_paths(_binance_spot_annual() / 12.0, N_PATHS, rng)
    deriv_denom_paths = _regime_paths((deribit_30d / 30.0) * (365.0 / 12.0), N_PATHS, rng)
    sofr_path_arr     = _sofr_path(sofr)

    # Velocity ratios for portfolio snapshot
    _ms7   = spot_ms_data.get("ms7")
    _ms30  = spot_ms_data.get("ms30")
    _ms180 = spot_ms_data.get("ms180")
    vel7_30   = (_ms7  / _ms30)  if (_ms7  and _ms30  and _ms30  > 0) else None
    vel30_180 = (_ms30 / _ms180) if (_ms30 and _ms180 and _ms180 > 0) else None

    scenario_list: list[dict] = []
    base_sc: dict | None = None
    for sc_key, sc_label, is_primary, decay_months, ps_center, sbc_dilution in SCENARIOS:
        sc_rng = np.random.default_rng(SEED + abs(hash(sc_key)) % 1_000)
        sc = _run_scenario(
            sc_key, sc_label, is_primary, decay_months, ps_center, sbc_dilution,
            coin_price, shares_out, DR,
            spot_ms, spot_vel, deriv_ms, deriv_vel,
            spot_denom_paths, deriv_denom_paths,
            usdc_supply, usdc_vel, sofr_path_arr,
            sc_rng,
        )
        scenario_list.append(sc)
        if is_primary:
            base_sc = sc
        print(f"[COIN] {sc_key}: p50=${sc['pv']['p50']:.1f} "
              f"prob_above={sc['prob_above_spot']*100:.1f}%")

    if base_sc is None:
        base_sc = scenario_list[0]

    result = {
        "token":     "COIN",
        "name":      "Coinbase",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "market": {
            "spot":               coin_price,
            "market_cap":         mcap,
            "fdv":                mcap,
            "circulating_supply": shares_out,
            "max_supply":         shares_out * 1.20,
        },
        "model": {
            "type":          f"3Y GP-Capture MC ({N_PATHS:,} paths)",
            "discount_rate": DR,
            "multiple":      7.0,
            "paths":         N_PATHS,
            "note": (
                f"DR={DR*100:.1f}% (CAPM: {rf*100:.2f}%rf + 5.5%ERP × β{beta:.2f}). "
                "Spot: Binance regime-switching × CB spot MS velocity-decay × 32bps. "
                f"Derivatives: Deribit regime-switching × CB deriv MS ({deriv_ms_data.get('source','proxy_spot')}) × 35bps. "
                "USDC: supply velocity-decay × SOFR path × 50% CB share × 62% net retention. "
                "Other services: staking/custody/subs/Base = 17% of spot+deriv revenue. "
                f"Exit P/S: log-normal σ=0.30 around bear/base/bull centers (4×/7×/11×). "
                f"{N_PATHS:,} MC paths per scenario; real percentiles, no synthetic bands."
            ),
        },
        "current_gp": {
            # Portfolio snapshot velocity
            "ms7_ms30_trend":          vel7_30,
            "ms30_ms180_trend":        vel30_180,
            # Spot MS inputs
            "spot_ms7_vs_binance":     _ms7,
            "spot_ms30_vs_binance":    float(spot_ms),
            "spot_ms180_vs_binance":   _ms180,
            "spot_vel_monthly":        float(spot_vel),
            # Derivatives MS inputs
            "deriv_ms30_vs_deribit":   float(deriv_ms),
            "deriv_ms7_vs_deribit":    deriv_ms_data.get("ms7"),
            "deriv_ms180_vs_deribit":  deriv_ms_data.get("ms180"),
            "deriv_vel_monthly":       float(deriv_vel),
            # Volume diagnostics
            "spot_volume_30d":         float(spot_30d),
            "deriv_volume_30d":        float(deriv_30d),
            "deribit_volume_30d":      float(deribit_30d),
            "binance_spot_annual":     float(_binance_spot_annual()),
            "cde_deriv_history_days":  len(cde_deriv_history),
            "deriv_data_source":       deriv_ms_data.get("source", "proxy_spot"),
            # Current revenue run-rates (annualized)
            "spot_revenue_ann":        float(spot_rev_ann),
            "deriv_revenue_ann":       float(deriv_rev_ann),
            "usdc_revenue_ann":        float(usdc_rev_ann),
            "other_revenue_ann":       float(other_rev_ann),
            "total_revenue_ann":       float(total_rev_ann),
            # USDC / rates
            "usdc_supply":             float(usdc_supply),
            "usdc_vel_monthly":        float(usdc_vel),
            "sofr_rate":               float(sofr),
            "risk_free_rate":          float(rf),
            # CAPM
            "coin_daily_vol":          float(coin_vol),
            "sp500_daily_vol":         float(sp_vol),
            "capm_beta":               float(beta),
            "derived_discount_rate":   float(DR),
            # Share data
            "shares_outstanding":      float(shares_out),
            "coin_ps_current":         float(mcap / max(total_rev_ann, 1.0)),
            # Base scenario Y3 summary
            "y3_revenue_p50":          float(base_sc["y3_revenue_p50"]),
            "y3_supply_p50":           float(base_sc["y3_supply_p50"]),
            "y3_spot_revenue_p50":     float(base_sc["y3_revenue_by_product_line_p50"]["spot"]),
            "y3_deriv_revenue_p50":    float(base_sc["y3_revenue_by_product_line_p50"]["derivatives"]),
            "y3_usdc_revenue_p50":     float(base_sc["y3_revenue_by_product_line_p50"]["stablecoin_gp"]),
            "y3_other_revenue_p50":    float(base_sc["y3_revenue_by_product_line_p50"]["other_services"]),
        },
        "scenarios":   scenario_list,
        "hist_charts": {},
        "caveats": [
            f"Spot MS from CoinGecko /exchanges/gdax/volume_chart; Binance denom BLOCKWORKS ${_binance_spot_annual()/1e12:.1f}T ann.",
            f"Deriv MS source: {deriv_ms_data.get('source','proxy_spot')}. "
            "CDE (CFTC-regulated, US) volume from Coinbase public API (no key required). "
            "CIE (international perps) excluded — no public API. If CDE fetch fails, fallback = 4.2% of spot MS (proxy).",
            "USDC GP: supply × SOFR/12 × 50% CB share × 62% net retention (calibrated to 2024 actuals).",
            "SOFR mean-reverts linearly to 2.5% long-run over 36 months.",
            "Other services (staking/custody/subs/Base) = 17% of spot+deriv revenue — labeled fallback ratio.",
            f"Exit P/S log-normal σ=0.30 per scenario; {N_PATHS:,} paths; real percentiles from simulated paths.",
        ],
        "data_freshness": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    # Embed COIN price history (Yahoo Finance → mcap proxy)
    try:
        h = _get("https://query1.finance.yahoo.com/v8/finance/chart/COIN?range=90d&interval=1d")
        ts_list = h["chart"]["result"][0].get("timestamp", [])
        cl_list = h["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        result["mcap_history"] = [
            {"date": date.fromtimestamp(ts).isoformat(), "mcap": round(float(cl) * shares_out)}
            for ts, cl in zip(ts_list, cl_list) if cl
        ]
    except Exception:
        result["mcap_history"] = []

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "coinbase_result.json", "w") as f:
        json.dump(result, f, indent=2)

    return result
