"""Coinbase (COIN) valuation agent — 3Y Monte Carlo model.

Three-engine simulation:
  1. Spot:    Binance spot denominator (regime-switching) × Coinbase spot MS
              (velocity-decay from CoinGecko 180D history) × 32 bps take rate
  2. Deribit: Binance Futures denominator × Deribit/Binance MS × 3.88 bps take rate
              (Deribit acquired by Coinbase; calibrated Q1-2026: $136M inst rev / $350.8B vol)
  3. CDE:     Binance Futures denominator × CDE retail MS × 119 bps take rate
              (CDE = Coinbase retail derivatives; Q1-2026: $200M ann / $16.8B ann vol)
  4. USDC:    Supply (velocity-decay) × SOFR path × 37.9% CB net share
              (calibrated Q1-2026: $1.22B ann / ($75B supply × 4.3% SOFR) = 37.9%)

Denominators: spot uses Binance spot (Blockworks); derivatives use Binance Futures.
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

SPOT_TAKE_BPS    = 32.0
DERIBIT_TAKE_BPS = 3.88    # Q1-2026: ~$136M inst rev / $350.8B Deribit vol = 3.88bps
CDE_TAKE_BPS     = 119.0   # Q1-2026: ~$200M ann / $16.8B ann CDE vol = 119bps
SPOT_MS_CAP      = 0.25
DERIBIT_MS_CAP   = 0.40    # Deribit vs Binance Futures (Deribit is largest options venue)
CDE_MS_CAP       = 0.005   # CDE retail is small vs Binance Futures

# USDC: calibrated Q1-2026 ($305M/Q × 4 = $1.22B ann on $75B avg supply × 4.3% SOFR)
USDC_CB_SHARE  = 0.379
SOFR_LONGRUN   = 0.025

OTHER_SERVICES_RATIO = 0.17   # staking/custody/subs/Base as % of spot+deriv rev
PS_SIGMA             = 0.30   # log-normal σ around exit P/S center

VEL_LONG_WEIGHT  = 0.70
VEL_SHORT_WEIGHT = 0.30
VEL_MAX_MONTHLY  = 0.08

BLOCKWORKS_BINANCE_SPOT_ANNUAL: dict[int, float] = {
    2022: 3.554e12, 2023: 2.941e12, 2024: 7.136e12, 2025: 7.307e12,
}
BLOCKWORKS_BINANCE_FUTURES_ANNUAL: dict[int, float] = {
    2022: 9.543e12, 2023: 8.401e12, 2024: 15.971e12, 2025: 25.241e12,
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
_FB_PRICE    = 142.0
_FB_MCAP     = 34_500_000_000.0
_FB_SHARES   = 243_000_000.0
_FB_SPOT30   = 47_500_000_000.0   # $47.5B/month Coinbase spot (from DefiLlama)
_FB_CDE30    = 1_400_000_000.0    # $1.4B/month CDE retail (Q1-2026: $4.2B / 3)
_FB_DERIBIT30 = 116_900_000_000.0 # $116.9B/month Deribit (Q1-2026: $350.8B / 3)
_FB_BNFUT30  = 1_450_000_000_000.0 # $1.45T/month Binance Futures observed
_FB_USDC     = 73_000_000_000.0
_FB_SOFR     = 0.043
_FB_RF       = 0.044
_FB_COINV    = 0.040
_FB_SPV      = 0.010
_FB_BTC      = 100_000.0


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
    """Return [(date_str, usd_volume)] from Coinbase public API for CDE retail futures."""
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
        # contract_size used only to filter invalid products; Coinbase candle
        # `volume` field for futures is already USD notional (quote currency)
        contract_size = float(p.get("contract_size") or p.get("base_increment") or 0)
        if contract_size <= 0:
            continue
        try:
            candles = _get(f"{CB_API}/products/{pid}/candles?granularity=ONE_DAY")
            rows = candles if isinstance(candles, list) else candles.get("candles", [])
            if not rows:
                continue
            for row in rows:
                if isinstance(row, dict):
                    ts  = int(row.get("start", 0))
                    vol = float(row.get("volume", 0))
                elif isinstance(row, (list, tuple)) and len(row) >= 6:
                    ts  = int(row[0])
                    vol = float(row[5])
                else:
                    continue
                if ts <= 0 or vol <= 0:
                    continue
                day = date.fromtimestamp(ts).isoformat()
                daily_totals[day] = daily_totals.get(day, 0.0) + vol
            fetched += 1
            time.sleep(0.15)
        except Exception:
            continue

    if not daily_totals:
        return []
    print(f"[COIN] CDE deriv: {fetched} products, {len(daily_totals)} days history")
    return sorted(daily_totals.items())


def _fetch_deribit_history() -> list[float]:
    """Return daily Deribit total derivatives volumes, oldest→newest."""
    try:
        d = _get("https://api.llama.fi/summary/derivatives/deribit?dataType=dailyVolume")
        rows = sorted(d.get("totalDataChart", []), key=lambda x: x[0])
        return [float(v) for _, v in rows]
    except Exception:
        return []


def _fetch_binance_futures_monthly() -> float:
    """Fetch Binance Futures 30D volume; falls back to Blockworks calibration."""
    for slug in ["binance-futures", "binance"]:
        try:
            d = _get(f"https://api.llama.fi/summary/derivatives/{slug}?dataType=dailyVolume",
                     timeout=15)
            rows = sorted(d.get("totalDataChart", []), key=lambda x: x[0])
            total = float(sum(v for _, v in rows[-30:]))
            if total > 1e11:
                return total
        except Exception:
            pass
    return _FB_BNFUT30


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

def _binance_futures_annual() -> float:
    for yr in (2025, 2024):
        if yr in BLOCKWORKS_BINANCE_FUTURES_ANNUAL:
            return BLOCKWORKS_BINANCE_FUTURES_ANNUAL[yr]
    return 25.241e12


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

    ms7   = min(avg7   / bn_daily, SPOT_MS_CAP) if bn_daily > 0 else None
    ms30  = min(avg30  / bn_daily, SPOT_MS_CAP) if bn_daily > 0 else None
    ms180 = min(avg180 / bn_daily, SPOT_MS_CAP) if bn_daily > 0 else None

    return {
        "ms7": ms7, "ms30": ms30, "ms180": ms180,
        "vel_monthly": _velocity_ensemble(ms7, ms30, ms180),
        "spot_30d": avg30 * 30,
    }


def _compute_deriv_ms_data(
    deribit_history: list[float],
    cde_history: list[tuple[str, float]],
    bn_futures_monthly: float,
) -> dict:
    """Compute Deribit and CDE retail market share vs Binance Futures.

    Deribit is now Coinbase-owned (acquired 2025); its volume is Coinbase derivatives revenue.
    CDE retail is Coinbase's US CFTC-regulated retail futures venue.
    Both are benchmarked vs Binance Futures (the global derivatives denominator).
    """
    bn_daily = bn_futures_monthly / 30.0

    # ── Deribit MS vs Binance Futures ─────────────────────────────────────────
    if deribit_history and len(deribit_history) >= 30:
        dh = deribit_history
        n  = len(dh)
        dl7   = sum(dh[-min(7,   n):]) / min(7,   n)
        dl30  = sum(dh[-min(30,  n):]) / min(30,  n)
        dl180 = sum(dh[-min(180, n):]) / min(180, n)
        deribit_ms7   = min(dl7   / bn_daily, DERIBIT_MS_CAP) if bn_daily > 0 else None
        deribit_ms30  = min(dl30  / bn_daily, DERIBIT_MS_CAP) if bn_daily > 0 else None
        deribit_ms180 = min(dl180 / bn_daily, DERIBIT_MS_CAP) if bn_daily > 0 else None
        deribit_30d   = dl30 * 30
    else:
        deribit_ms7 = deribit_ms30 = deribit_ms180 = _FB_DERIBIT30 / bn_futures_monthly
        deribit_30d = _FB_DERIBIT30

    deribit_vel = _velocity_ensemble(deribit_ms7, deribit_ms30, deribit_ms180)

    # ── CDE retail MS vs Binance Futures ──────────────────────────────────────
    # The public brokerage API returns incomplete volume (misses institutional
    # flow and uses inconsistent units across product types). Use API data only
    # when the computed monthly total is within 5×–0.2× of the Q1-2026 baseline.
    _cde_api_ok = False
    if cde_history and len(cde_history) >= 30:
        cde_vols = [v for _, v in sorted(cde_history)]
        n = len(cde_vols)
        ca30_api = sum(cde_vols[-min(30, n):]) / min(30, n)
        cde_30d_api = ca30_api * 30
        if _FB_CDE30 * 0.2 < cde_30d_api < _FB_CDE30 * 5:
            _cde_api_ok = True
            ca7   = sum(cde_vols[-min(7,   n):]) / min(7,   n)
            ca30  = ca30_api
            ca180 = sum(cde_vols[-min(180, n):]) / min(180, n)
            cde_ms7   = min(ca7   / bn_daily, CDE_MS_CAP) if bn_daily > 0 else None
            cde_ms30  = min(ca30  / bn_daily, CDE_MS_CAP) if bn_daily > 0 else None
            cde_ms180 = min(ca180 / bn_daily, CDE_MS_CAP) if bn_daily > 0 else None
            cde_30d   = cde_30d_api
            cde_source = "cde_api"
    if not _cde_api_ok:
        cde_ms7 = cde_ms30 = cde_ms180 = _FB_CDE30 / bn_futures_monthly
        cde_30d = _FB_CDE30
        cde_source = "cde_fallback"

    cde_vel = _velocity_ensemble(cde_ms7, cde_ms30, cde_ms180)

    print(f"[COIN] Deribit MS vs BN Futures: "
          f"7D={deribit_ms7 and f'{deribit_ms7*100:.2f}%'} "
          f"30D={deribit_ms30 and f'{deribit_ms30*100:.2f}%'} | "
          f"CDE MS: 30D={cde_ms30 and f'{cde_ms30*100:.3f}%'} ({cde_source})")

    return {
        "deribit_ms7": deribit_ms7, "deribit_ms30": deribit_ms30,
        "deribit_ms180": deribit_ms180, "deribit_vel_monthly": deribit_vel,
        "cde_ms7": cde_ms7, "cde_ms30": cde_ms30,
        "cde_ms180": cde_ms180, "cde_vel_monthly": cde_vel,
        "deribit_30d": deribit_30d, "cde_30d": cde_30d,
        "bn_futures_30d": bn_futures_monthly,
        "cde_source": cde_source,
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


def _usdc_supply_path(supply0: float, vel_monthly: float, decay_months: int) -> np.ndarray:
    path = np.empty(MONTHS)
    s = supply0
    for m in range(MONTHS):
        w = max(0.0, 1.0 - m / decay_months) if decay_months > 0 else 0.0
        s *= math.exp(vel_monthly * w)
        path[m] = s
    return path


def _sofr_path(sofr0: float) -> np.ndarray:
    return np.linspace(sofr0, SOFR_LONGRUN, MONTHS)


# ── Scenario simulation ───────────────────────────────────────────────────────

def _run_scenario(
    sc_key: str, sc_label: str, is_primary: bool,
    decay_months: int, ps_center: float, sbc_dilution: float,
    coin_price: float, shares_out: float, DR: float,
    spot_ms: float,    spot_vel: float,
    deribit_ms: float, deribit_vel: float,
    cde_ms: float,     cde_vel: float,
    spot_denom_paths: np.ndarray,
    bn_futures_paths: np.ndarray,
    usdc_supply: float, usdc_vel: float,
    sofr_path_arr: np.ndarray,
    rng: np.random.Generator,
) -> dict:
    N = spot_denom_paths.shape[0]

    spot_ms_abs    = np.clip(spot_ms    * _ms_mult_path(spot_vel,    decay_months), 0.0, SPOT_MS_CAP)
    deribit_ms_abs = np.clip(deribit_ms * _ms_mult_path(deribit_vel, decay_months), 0.0, DERIBIT_MS_CAP)
    cde_ms_abs     = np.clip(cde_ms     * _ms_mult_path(cde_vel,     decay_months), 0.0, CDE_MS_CAP)

    spot_rev_m    = spot_denom_paths  * spot_ms_abs[np.newaxis, :]    * (SPOT_TAKE_BPS    / 10_000)
    deribit_rev_m = bn_futures_paths  * deribit_ms_abs[np.newaxis, :] * (DERIBIT_TAKE_BPS / 10_000)
    cde_rev_m     = bn_futures_paths  * cde_ms_abs[np.newaxis, :]     * (CDE_TAKE_BPS     / 10_000)

    tx_rev_m    = spot_rev_m + deribit_rev_m + cde_rev_m
    other_rev_m = tx_rev_m * OTHER_SERVICES_RATIO

    # USDC GP: supply × annual_SOFR/12 × net CB share (37.9%, calibrated Q1-2026)
    usdc_path_m = _usdc_supply_path(usdc_supply, usdc_vel, decay_months)
    usdc_gp_m   = usdc_path_m * sofr_path_arr / 12.0 * USDC_CB_SHARE

    total_m = tx_rev_m + other_rev_m + usdc_gp_m[np.newaxis, :]

    # Y3 TTM (months 25–36)
    y3_total   = total_m[:, 24:].sum(axis=1)
    y3_spot    = spot_rev_m[:, 24:].sum(axis=1)
    y3_deribit = deribit_rev_m[:, 24:].sum(axis=1)
    y3_cde     = cde_rev_m[:, 24:].sum(axis=1)
    y3_other   = other_rev_m[:, 24:].sum(axis=1)
    y3_usdc    = float(usdc_gp_m[24:].sum())

    # Y2 TTM (months 13–24)
    y2_total = total_m[:, 12:24].sum(axis=1)

    ps_paths  = np.clip(np.exp(rng.normal(math.log(ps_center), PS_SIGMA, N)), 2.0, 25.0)
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
            "spot":          float(np.percentile(y3_spot,    50)),
            "deribit":       float(np.percentile(y3_deribit, 50)),
            "cde_retail":    float(np.percentile(y3_cde,     50)),
            "stablecoin_gp": y3_usdc,
            "other_services": float(np.percentile(y3_other,  50)),
        },
        "y3_gp_p50": float(np.percentile(y3_total, 50)),
        "decay_months": decay_months,
        "ps_center":    ps_center,
        "sbc_dilution": sbc_dilution,
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
    bn_futures_monthly            = _fetch_binance_futures_monthly()
    usdc_supply                   = _fetch_usdc_supply()
    usdc_vel                      = _fetch_usdc_velocity()

    DR = float(np.clip(rf + ERP * beta, 0.08, 0.50))
    print(f"[COIN] DR={DR*100:.1f}% rf={rf*100:.2f}% β={beta:.2f} BTC=${btc_price:,.0f}")

    spot_ms_data  = _compute_spot_ms_data(spot_history_btc, btc_price)
    deriv_ms_data = _compute_deriv_ms_data(deribit_history, cde_deriv_history,
                                           bn_futures_monthly)

    spot_ms   = spot_ms_data.get("ms30")      or 0.04
    spot_vel  = spot_ms_data.get("vel_monthly", 0.0)
    spot_30d  = spot_ms_data.get("spot_30d",  _FB_SPOT30)

    deribit_ms  = deriv_ms_data.get("deribit_ms30")      or (_FB_DERIBIT30 / bn_futures_monthly)
    deribit_vel = deriv_ms_data.get("deribit_vel_monthly", 0.0)
    deribit_30d = deriv_ms_data.get("deribit_30d",        _FB_DERIBIT30)

    cde_ms  = deriv_ms_data.get("cde_ms30")      or (_FB_CDE30 / bn_futures_monthly)
    cde_vel = deriv_ms_data.get("cde_vel_monthly", 0.0)
    cde_30d = deriv_ms_data.get("cde_30d",        _FB_CDE30)

    bn_fut_monthly = deriv_ms_data.get("bn_futures_30d", bn_futures_monthly)

    print(f"[COIN] spot_ms30={spot_ms*100:.2f}% vel={spot_vel*100:.2f}%/mo | "
          f"deribit_ms30={deribit_ms*100:.2f}% | cde_ms30={cde_ms*100:.4f}% | "
          f"usdc_vel={usdc_vel*100:.2f}%/mo")

    bn_spot_daily = _binance_spot_annual() / 365.0
    spot_rev_ann    = spot_ms  * bn_spot_daily * 365 * (SPOT_TAKE_BPS    / 10_000)
    deribit_rev_ann = deribit_ms * (bn_fut_monthly / 30) * 365 * (DERIBIT_TAKE_BPS / 10_000)
    cde_rev_ann     = cde_ms     * (bn_fut_monthly / 30) * 365 * (CDE_TAKE_BPS     / 10_000)
    deriv_rev_ann   = deribit_rev_ann + cde_rev_ann
    usdc_rev_ann    = usdc_supply * sofr * USDC_CB_SHARE
    other_rev_ann   = (spot_rev_ann + deriv_rev_ann) * OTHER_SERVICES_RATIO
    total_rev_ann   = spot_rev_ann + deriv_rev_ann + usdc_rev_ann + other_rev_ann

    print(f"[COIN] rev_ann ~${total_rev_ann/1e9:.2f}B "
          f"(spot ${spot_rev_ann/1e9:.2f}B + deribit ${deribit_rev_ann/1e9:.2f}B "
          f"+ CDE ${cde_rev_ann/1e6:.0f}M + USDC ${usdc_rev_ann/1e9:.2f}B "
          f"+ other ${other_rev_ann/1e9:.2f}B)")

    rng = np.random.default_rng(SEED)
    spot_denom_paths = _regime_paths(_binance_spot_annual() / 12.0, N_PATHS, rng)
    bn_futures_paths = _regime_paths(bn_fut_monthly, N_PATHS, rng)
    sofr_path_arr    = _sofr_path(sofr)

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
            spot_ms,    spot_vel,
            deribit_ms, deribit_vel,
            cde_ms,     cde_vel,
            spot_denom_paths, bn_futures_paths,
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
                f"Spot: Binance regime-switching × CB spot MS × {SPOT_TAKE_BPS}bps. "
                f"Deribit (Coinbase-owned): Binance Futures regime-switching × Deribit MS × {DERIBIT_TAKE_BPS}bps "
                f"(calibrated Q1-2026). "
                f"CDE retail: Binance Futures × CDE MS × {CDE_TAKE_BPS:.0f}bps. "
                f"USDC: supply velocity-decay × SOFR path × {USDC_CB_SHARE*100:.1f}% CB net share "
                f"(calibrated Q1-2026: $1.22B ann on $75B supply × 4.3% SOFR). "
                "Other services: staking/custody/subs/Base = 17% of spot+deriv revenue. "
                f"Exit P/S: log-normal σ=0.30 around bear/base/bull centers (4×/7×/11×). "
                f"{N_PATHS:,} MC paths; real percentiles."
            ),
        },
        "current_gp": {
            "ms7_ms30_trend":          vel7_30,
            "ms30_ms180_trend":        vel30_180,
            # Spot
            "spot_ms7_vs_binance":     _ms7,
            "spot_ms30_vs_binance":    float(spot_ms),
            "spot_ms180_vs_binance":   _ms180,
            "spot_vel_monthly":        float(spot_vel),
            # Deribit (Coinbase-owned) vs Binance Futures
            "deribit_ms30_vs_binance_futures":  float(deribit_ms),
            "deribit_ms7_vs_binance_futures":   deriv_ms_data.get("deribit_ms7"),
            "deribit_ms180_vs_binance_futures": deriv_ms_data.get("deribit_ms180"),
            "deribit_vel_monthly":              float(deribit_vel),
            # CDE retail vs Binance Futures
            "cde_ms30_vs_binance_futures":  float(cde_ms),
            "cde_ms7_vs_binance_futures":   deriv_ms_data.get("cde_ms7"),
            "cde_ms180_vs_binance_futures": deriv_ms_data.get("cde_ms180"),
            "cde_vel_monthly":              float(cde_vel),
            # Combined derivatives MS (Deribit + CDE) vs Binance Futures
            "deriv_ms30_vs_binance_futures": float(deribit_ms + cde_ms),
            # Volume diagnostics
            "spot_volume_30d":        float(spot_30d),
            "deribit_volume_30d":     float(deribit_30d),
            "cde_volume_30d":         float(cde_30d),
            "bn_futures_volume_30d":  float(bn_fut_monthly),
            "binance_spot_annual":    float(_binance_spot_annual()),
            "cde_deriv_history_days": len(cde_deriv_history),
            "cde_data_source":        deriv_ms_data.get("cde_source", "cde_fallback"),
            # Revenue run-rates (annualized)
            "spot_revenue_ann":    float(spot_rev_ann),
            "deribit_revenue_ann": float(deribit_rev_ann),
            "cde_revenue_ann":     float(cde_rev_ann),
            "deriv_revenue_ann":   float(deriv_rev_ann),
            "usdc_revenue_ann":    float(usdc_rev_ann),
            "other_revenue_ann":   float(other_rev_ann),
            "total_revenue_ann":   float(total_rev_ann),
            # USDC / rates
            "usdc_supply":         float(usdc_supply),
            "usdc_vel_monthly":    float(usdc_vel),
            "sofr_rate":           float(sofr),
            "risk_free_rate":      float(rf),
            # CAPM
            "coin_daily_vol":      float(coin_vol),
            "sp500_daily_vol":     float(sp_vol),
            "capm_beta":           float(beta),
            "derived_discount_rate": float(DR),
            # Share data
            "shares_outstanding":  float(shares_out),
            "coin_ps_current":     float(mcap / max(total_rev_ann, 1.0)),
            # Base scenario Y3 summary
            "y3_revenue_p50":      float(base_sc["y3_revenue_p50"]),
            "y3_supply_p50":       float(base_sc["y3_supply_p50"]),
            "y3_spot_revenue_p50":   float(base_sc["y3_revenue_by_product_line_p50"]["spot"]),
            "y3_deribit_revenue_p50": float(base_sc["y3_revenue_by_product_line_p50"]["deribit"]),
            "y3_cde_revenue_p50":    float(base_sc["y3_revenue_by_product_line_p50"]["cde_retail"]),
            "y3_deriv_revenue_p50":  float(base_sc["y3_revenue_by_product_line_p50"]["deribit"])
                                    + float(base_sc["y3_revenue_by_product_line_p50"]["cde_retail"]),
            "y3_usdc_revenue_p50":   float(base_sc["y3_revenue_by_product_line_p50"]["stablecoin_gp"]),
            "y3_other_revenue_p50":  float(base_sc["y3_revenue_by_product_line_p50"]["other_services"]),
        },
        "scenarios":   scenario_list,
        "hist_charts": {},
        "caveats": [
            f"Spot MS from CoinGecko /exchanges/gdax/volume_chart; Binance denom BLOCKWORKS ${_binance_spot_annual()/1e12:.1f}T ann.",
            f"Deribit is Coinbase-owned (acquired 2025). Deribit MS vs Binance Futures denominator "
            f"(${bn_fut_monthly/1e12:.2f}T/month observed). Take rate {DERIBIT_TAKE_BPS}bps calibrated Q1-2026.",
            f"CDE retail (CFTC-regulated US venue) volume from Coinbase public API. "
            f"Take rate {CDE_TAKE_BPS:.0f}bps calibrated Q1-2026 ($200M ann / $16.8B ann vol). "
            f"Source: {deriv_ms_data.get('cde_source','cde_fallback')}.",
            f"USDC GP: supply × SOFR × {USDC_CB_SHARE*100:.1f}% CB net share "
            f"(calibrated Q1-2026: $305M/Q = $1.22B ann on $75B avg supply × 4.3% SOFR).",
            "SOFR mean-reverts linearly to 2.5% long-run over 36 months.",
            "Other services (staking/custody/subs/Base) = 17% of spot+deriv revenue.",
            f"Exit P/S log-normal σ=0.30; {N_PATHS:,} paths; real percentiles.",
        ],
        "data_freshness": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

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
