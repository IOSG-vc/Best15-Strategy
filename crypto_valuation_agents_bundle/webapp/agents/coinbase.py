"""Coinbase (COIN) valuation agent — driver-based multi-product model.

Revenue model:
  1. Spot:         Binance spot denominator × Coinbase spot MS × blended take-rate
  2. Derivatives:  Deribit total volume × Coinbase derivatives MS × blended take-rate
  3. USDC:         USDC supply × short-term interest rate × 50% revenue share (manual velocity decay)
  4. Other svcs:   Staking (cbETH) + custody + subscriptions/Base — modeled as flat multiple of
                   transaction revenue plus an independent staking base

Valuation:
  Company valuation = Y3 total revenue × P/S multiple × optionality bonus
  PV per COIN share = company valuation / Y3 diluted shares / (1 + DR)^3

Discount rate (CAPM-derived, not hardcoded):
  DR = risk_free_rate + ERP × (COIN_daily_vol / SP500_daily_vol)
  ERP = 5.5% (standard US equity risk premium)
  Volatility from Yahoo Finance 1Y daily return history.

Supply:
  Current diluted shares outstanding; Y3 shares include SBC dilution minus any buybacks.
  Bear: net +25% dilution (stressed equity issuance), Base: +15%, Bull: +10%.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import time
import urllib.request
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

import numpy as np

# ── Model parameters ──────────────────────────────────────────────────────────
ERP = 0.055                    # equity risk premium (standard US equity)
LOG_NORMAL_SIGMA = 1.0

# Take rates — blended institutional+retail, derived from Q1-2025 actuals:
#   Q1-2025: $1.26B transaction revenue / $396B spot volume = 31.8 bps
SPOT_TAKE_RATE_BPS_FALLBACK  = 32.0    # blended (retail taker ~110 bps but offset by Prime/institutional)
DERIV_TAKE_RATE_BPS_FALLBACK = 35.0    # ~0.35% blended options/futures taker
USDC_COINBASE_SHARE          = 0.50    # Coinbase's ~50% share of USDC interest income

# Other services multiplier on transaction revenue (staking, custody, subs, Base)
# Q4-2024 empirical: other services ≈ 15–20% of transaction revenue
OTHER_SERVICES_TX_RATIO = 0.17

# Blockworks annual Binance spot denominator (same source as uni.py / jup.py)
BLOCKWORKS_BINANCE_SPOT_ANNUAL = {2022: 3.554e12, 2023: 2.941e12, 2024: 7.136e12, 2025: 7.307e12}

# Scenarios: (key, label,
#  spot_ms_mult,      # scalar on current spot MS → Y3 spot MS
#  deriv_ms_mult,     # scalar on current derivatives MS → Y3 derivatives MS
#  denom_growth,      # Binance + Deribit volume growth by Y3
#  usdc_cagr,         # 3Y CAGR for USDC supply
#  sofr_retention,    # fraction of current short rate still in effect at Y3
#  ps_multiple,       # P/S applied to Y3 total revenue
#  optionality_mult,  # valuation bonus for international/Base/M&A optionality
#  sbc_dilution_3y,   # cumulative diluted-share multiplier at Y3 (incl SBC net of buybacks)
#  is_primary)
SCENARIOS = [
    ("bear",
     "Bear: volume decay, USDC shrinks, 4× P/S",
     0.65, 0.65, 1.00, -0.10, 0.60, 4.0, 1.00, 1.25, False),
    ("base",
     "Base: stable share, USDC grows, 7× P/S",
     1.00, 1.00, 1.30, 0.25,  0.85, 7.0, 1.05, 1.15, True),
    ("bull",
     "Bull: share gains, USDC thrives, 11× P/S",
     1.40, 1.60, 1.60, 0.50,  0.90, 11.0, 1.15, 1.10, False),
]

RESULTS_DIR = Path(__file__).parent.parent / "results"
UA = "Mozilla/5.0 Coinbase-valuation"

# ── Fallbacks ─────────────────────────────────────────────────────────────────
_FB_COIN_PRICE  = 280.0
_FB_MCAP        = 68_000_000_000.0   # ~$68B market cap
_FB_SHARES_OUT  = 243_000_000.0      # ~243M diluted shares
_FB_SPOT_30D    = 130_000_000_000.0  # ~$130B/30D (Coinbase Q1-2025: $396B/qtr → $132B/30D)
_FB_DERIV_30D   = 8_000_000_000.0    # ~$8B/30D Coinbase derivatives (estimated)
_FB_DERIBIT_30D = 200_000_000_000.0  # ~$200B/30D Deribit total derivatives
_FB_USDC_SUPPLY = 58_000_000_000.0   # ~$58B USDC in circulation
_FB_SOFR        = 0.043              # ~4.3%
_FB_RF          = 0.045              # 10Y Treasury fallback
_FB_COIN_VOL    = 0.040              # COIN daily return std dev (~4%, annualized ~63%)
_FB_SP_VOL      = 0.010              # SPX daily return std dev (~1%)


def _get(url: str, timeout: int = 30) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _get_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


# ── Market / price data ───────────────────────────────────────────────────────

def _fetch_coin_stock() -> tuple[float, float, float]:
    """Return (COIN price, market cap, diluted shares outstanding) from Yahoo Finance."""
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/COIN?range=1d&interval=1d"
        d = _get(url)
        meta = d["chart"]["result"][0]["meta"]
        price = float(meta["regularMarketPrice"])
        # Shares from quoteSummary
        try:
            qs = _get("https://query2.finance.yahoo.com/v10/finance/quoteSummary/COIN"
                      "?modules=defaultKeyStatistics,summaryDetail")
            stats = qs["quoteSummary"]["result"][0]
            shares = float(stats["defaultKeyStatistics"].get("sharesOutstanding", {}).get("raw", 0)
                           or stats["summaryDetail"].get("sharesOutstanding", {}).get("raw", 0)
                           or _FB_SHARES_OUT)
        except Exception:
            shares = _FB_SHARES_OUT
        mcap = price * shares
        return price, mcap, shares
    except Exception as e:
        print(f"[COIN] Yahoo price fetch failed ({e}); using fallback")
        return _FB_COIN_PRICE, _FB_MCAP, _FB_SHARES_OUT


def _fetch_risk_free_rate() -> float:
    """10Y US Treasury yield from Yahoo Finance (^TNX) or FRED fallback."""
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
    """Current SOFR from FRED."""
    try:
        txt = _get_text("https://fred.stlouisfed.org/graph/fredgraph.csv?id=SOFR")
        rows = [r for r in csv.DictReader(io.StringIO(txt)) if r.get("SOFR") not in ("", ".")]
        return float(rows[-1]["SOFR"]) / 100.0
    except Exception:
        return _FB_SOFR


def _fetch_capm_inputs() -> tuple[float, float, float]:
    """
    Return (COIN_daily_vol, SPX_daily_vol, CAPM_beta) from Yahoo Finance 1Y history.
    Beta = cov(COIN_rets, SPX_rets) / var(SPX_rets) — proper CAPM beta.
    Falls back to vol-ratio estimate if histories can't be aligned.
    """
    coin_vol, sp_vol, beta = _FB_COIN_VOL, _FB_SP_VOL, None
    coin_rets_by_date: dict[str, float] = {}
    sp_rets_by_date:   dict[str, float] = {}

    for ticker, store in [("COIN", coin_rets_by_date), ("%5EGSPC", sp_rets_by_date)]:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1y&interval=1d"
            d   = _get(url)
            ts_list  = d["chart"]["result"][0].get("timestamp", [])
            cl_list  = d["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            pairs    = [(ts_list[i], cl_list[i]) for i in range(len(ts_list)) if cl_list[i]]
            if len(pairs) >= 30:
                dates  = [date.fromtimestamp(t).isoformat() for t, _ in pairs]
                closes = [c for _, c in pairs]
                log_r  = np.diff(np.log(np.array(closes, dtype=float)))
                for i, r in enumerate(log_r):
                    store[dates[i + 1]] = float(r)
        except Exception:
            pass

    if len(coin_rets_by_date) >= 30:
        coin_vol = float(np.std(list(coin_rets_by_date.values()), ddof=1))
    if len(sp_rets_by_date) >= 30:
        sp_vol = float(np.std(list(sp_rets_by_date.values()), ddof=1))

    # Compute proper beta on overlapping dates
    common = sorted(set(coin_rets_by_date) & set(sp_rets_by_date))
    if len(common) >= 60:
        c_arr = np.array([coin_rets_by_date[d] for d in common])
        s_arr = np.array([sp_rets_by_date[d]   for d in common])
        sp_var = float(np.var(s_arr, ddof=1))
        if sp_var > 0:
            beta = float(np.cov(c_arr, s_arr, ddof=1)[0, 1] / sp_var)

    if beta is None:
        # Fallback: volatility-ratio beta with 0.35 correlation assumption for a public equity
        beta = 0.35 * (coin_vol / max(sp_vol, 1e-6))

    return coin_vol, sp_vol, beta


# ── Volume / revenue data ─────────────────────────────────────────────────────

def _fetch_coinbase_spot_30d() -> tuple[float, float]:
    """
    Return (30D spot volume USD, derived take rate bps) from CoinGecko exchange API.
    Coinbase exchange ID on CoinGecko is 'gdax'.
    """
    for ex_id in ("gdax", "coinbase-exchange"):
        try:
            d = _get(f"https://api.coingecko.com/api/v3/exchanges/{ex_id}")
            vol_24h_btc = float(
                d.get("trade_volume_24h_btc_normalized") or
                d.get("trade_volume_24h_btc") or 0
            )
            if vol_24h_btc > 0:
                # Convert BTC volume to USD (BTC ~$100k approx)
                btc_price_approx = 100_000.0
                vol_30d = vol_24h_btc * btc_price_approx * 30
                return vol_30d, SPOT_TAKE_RATE_BPS_FALLBACK
        except Exception:
            continue
    return _FB_SPOT_30D, SPOT_TAKE_RATE_BPS_FALLBACK


def _fetch_deribit_volume_30d() -> float:
    """Sum last 30 daily Deribit total derivatives volume from DefiLlama."""
    try:
        url = "https://api.llama.fi/summary/derivatives/deribit?dataType=dailyVolume"
        d = _get(url)
        rows = sorted(d.get("totalDataChart", []), key=lambda x: x[0])
        total = float(sum(v for _, v in rows[-30:]))
        return total if total > 0 else _FB_DERIBIT_30D
    except Exception:
        return _FB_DERIBIT_30D


def _fetch_usdc_supply() -> float:
    """USDC total circulating supply from DefiLlama stablecoins API."""
    try:
        coins = _get("https://stablecoins.llama.fi/stablecoins?includePrices=false")
        for c in coins.get("peggedAssets", []):
            if c.get("symbol", "").upper() == "USDC":
                circ = c.get("circulating", {})
                # DL returns peggedUSD key for the pegged value
                supply = float(
                    circ.get("peggedUSD") or
                    sum(v for k, v in circ.items() if isinstance(v, (int, float)))
                )
                if supply > 1e9:
                    return supply
    except Exception:
        pass
    return _FB_USDC_SUPPLY


def _binance_spot_annual() -> float:
    for yr in [2025, 2024]:
        if yr in BLOCKWORKS_BINANCE_SPOT_ANNUAL:
            return BLOCKWORKS_BINANCE_SPOT_ANNUAL[yr]
    return 7.307e12


# ── Math helpers ──────────────────────────────────────────────────────────────

def _lognorm_pv(median_pv: float, sigma: float = LOG_NORMAL_SIGMA) -> dict:
    if median_pv <= 0:
        return {"p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0}
    e = math.exp
    return {
        "p25": median_pv * e(-0.6745 * sigma),
        "p50": median_pv,
        "p75": median_pv * e(0.6745 * sigma),
        "p90": median_pv * e(1.2816 * sigma),
    }


def _prob_above(target: float, median: float, sigma: float = LOG_NORMAL_SIGMA) -> float:
    if target <= 0 or median <= 0:
        return 1.0 if target <= 0 else 0.0
    z = math.log(target / median) / sigma
    return 0.5 * math.erfc(z / math.sqrt(2))


def _usdc_y3_supply(current: float, cagr: float) -> float:
    """Project USDC supply 3 years forward with constant-growth assumption."""
    return current * ((1.0 + cagr) ** 3)


# ── Main run ──────────────────────────────────────────────────────────────────

def run() -> dict:
    # ── COIN stock data ───────────────────────────────────────────────────────
    coin_price, mcap, shares_out = _fetch_coin_stock()

    # ── Interest rates & volatility ───────────────────────────────────────────
    rf     = _fetch_risk_free_rate()
    sofr   = _fetch_sofr()
    coin_vol, sp_vol, beta = _fetch_capm_inputs()

    # CAPM discount rate: rf + ERP × beta (proper covariance-based beta)
    DR = rf + ERP * beta
    DR = max(0.08, min(DR, 0.50))   # clamp [8%, 50%]

    print(f"[COIN] DR={DR*100:.1f}% | rf={rf*100:.2f}% | beta={beta:.2f} | coin_vol={coin_vol*100:.2f}%/day | sp_vol={sp_vol*100:.2f}%/day")

    # ── Volume data ───────────────────────────────────────────────────────────
    spot_30d, spot_take_bps = _fetch_coinbase_spot_30d()
    deribit_30d             = _fetch_deribit_volume_30d()
    usdc_supply             = _fetch_usdc_supply()

    # Coinbase derivatives volume estimated as ratio of spot
    # (Q1-2025: ~$16.7B deriv / ~$396B spot ≈ 4.2% over the quarter)
    deriv_30d = spot_30d * 0.042
    deriv_take_bps = DERIV_TAKE_RATE_BPS_FALLBACK

    # Annualised volumes
    spot_ann  = spot_30d  * (365 / 30)
    deriv_ann = deriv_30d * (365 / 30)

    # Binance spot denominator (annual)
    bn_spot_ann = _binance_spot_annual()
    bn_spot_30d = bn_spot_ann / 12.0

    # Current market shares
    spot_ms  = spot_30d  / max(bn_spot_30d, 1.0)      # vs Binance spot
    deriv_ms = deriv_30d / max(deribit_30d, 1.0)      # vs Deribit derivatives

    # Current revenue proxies (annualised from 30D)
    spot_rev_ann  = spot_ann  * (spot_take_bps  / 10_000)
    deriv_rev_ann = deriv_ann * (deriv_take_bps / 10_000)
    usdc_rev_ann  = usdc_supply * sofr * USDC_COINBASE_SHARE
    other_rev_ann = (spot_rev_ann + deriv_rev_ann) * OTHER_SERVICES_TX_RATIO
    total_rev_ann = spot_rev_ann + deriv_rev_ann + usdc_rev_ann + other_rev_ann

    print(f"[COIN] spot_ms={spot_ms*100:.2f}% | deriv_ms={deriv_ms*100:.2f}% vs Deribit")
    print(f"[COIN] current_rev_ann ~${total_rev_ann/1e9:.2f}B "
          f"(spot ${spot_rev_ann/1e9:.2f}B + deriv ${deriv_rev_ann/1e9:.2f}B "
          f"+ USDC ${usdc_rev_ann/1e9:.2f}B + other ${other_rev_ann/1e9:.2f}B)")

    disc = (1.0 + DR) ** 3
    scenario_list = []
    y3_revenue_p50 = 0.0
    y3_supply_p50  = 0.0

    for (sc_key, sc_label, spot_ms_mult, deriv_ms_mult, denom_growth,
         usdc_cagr, sofr_retention, ps_mult, opt_bonus, sbc_dilution, is_primary) in SCENARIOS:

        # Y3 market shares (capped at realistic maximums)
        y3_spot_ms  = min(spot_ms  * spot_ms_mult,  0.30)   # cap 30% of Binance spot
        y3_deriv_ms = min(deriv_ms * deriv_ms_mult, 0.20)   # cap 20% of Deribit

        # Y3 denominator volumes
        bn_spot_y3  = bn_spot_ann  * denom_growth
        deribit_y3  = deribit_30d * 12 * denom_growth  # Deribit annual

        # Y3 trading volumes
        y3_spot_vol  = bn_spot_y3  * y3_spot_ms
        y3_deriv_vol = deribit_y3  * y3_deriv_ms

        # Y3 transaction revenue
        y3_spot_rev  = y3_spot_vol  * (spot_take_bps  / 10_000)
        y3_deriv_rev = y3_deriv_vol * (deriv_take_bps / 10_000)
        y3_tx_rev    = y3_spot_rev + y3_deriv_rev

        # Y3 USDC revenue (velocity-decay manual scenarios)
        y3_usdc_supply = _usdc_y3_supply(usdc_supply, usdc_cagr)
        y3_sofr_rate   = sofr * sofr_retention
        y3_usdc_rev    = y3_usdc_supply * y3_sofr_rate * USDC_COINBASE_SHARE

        # Y3 other services (staking, custody, subs, Base) — flat ratio of Y3 tx rev
        y3_other_rev = y3_tx_rev * OTHER_SERVICES_TX_RATIO

        # Y3 total revenue
        y3_total_rev = y3_tx_rev + y3_usdc_rev + y3_other_rev

        # Company valuation with optionality
        y3_company_val = y3_total_rev * ps_mult * opt_bonus

        # Y3 diluted shares
        y3_shares = shares_out * sbc_dilution

        # PV per COIN share
        y3_price   = y3_company_val / max(y3_shares, 1.0)
        pv_median  = y3_price / disc

        pv_dist = _lognorm_pv(pv_median)
        ev      = pv_median * math.exp(LOG_NORMAL_SIGMA ** 2 / 2)

        scenario_list.append({
            "key":              sc_key,
            "label":            sc_label,
            "is_primary":       is_primary,
            "pv":               pv_dist,
            "ev":               ev,
            "prob_above_spot":  _prob_above(coin_price, pv_median),
            "prob_3x":          _prob_above(3 * coin_price, pv_median),
            "y3_price_p50":     y3_price,
            "y3_mcap_p50":      y3_price * y3_shares,
            "y3_supply_p50":    float(y3_shares),
            "y3_gp_p50":        y3_total_rev,
            # Product-line detail
            "y3_spot_volume_ann":   y3_spot_vol,
            "y3_deriv_volume_ann":  y3_deriv_vol,
            "y3_spot_ms":           y3_spot_ms,
            "y3_deriv_ms":          y3_deriv_ms,
            "y3_spot_revenue":      y3_spot_rev,
            "y3_deriv_revenue":     y3_deriv_rev,
            "y3_usdc_supply":       y3_usdc_supply,
            "y3_usdc_revenue":      y3_usdc_rev,
            "y3_other_revenue":     y3_other_rev,
            "y3_total_revenue":     y3_total_rev,
            "y3_company_val":       y3_company_val,
            "y3_shares":            y3_shares,
            "ps_multiple":          ps_mult,
            "optionality_mult":     opt_bonus,
            "spot_take_rate_bps":   spot_take_bps,
            "deriv_take_rate_bps":  deriv_take_bps,
            "usdc_cagr":            usdc_cagr,
            "sofr_y3":              y3_sofr_rate,
            "denom_growth":         denom_growth,
        })

        if is_primary:
            y3_revenue_p50 = float(y3_total_rev)
            y3_supply_p50  = float(y3_shares)

    base_sc = next((s for s in scenario_list if s["is_primary"]), scenario_list[0])

    result = {
        "token":       "COIN",
        "name":        "Coinbase",
        "as_of_utc":   datetime.now(timezone.utc).isoformat(),
        "market": {
            "spot":               coin_price,
            "market_cap":         mcap,
            "fdv":                mcap,                   # stock: FDV = market cap (diluted)
            "circulating_supply": shares_out,
            "max_supply":         shares_out * 1.20,      # rough max diluted shares estimate
        },
        "model": {
            "type":          "3Y Driver-Based Equity Scenarios (CAPM DR)",
            "discount_rate": DR,
            "multiple":      7.0,   # base P/S
            "paths":         1,
            "note": (
                f"DR = {rf*100:.2f}% rf + 5.5% ERP × β{beta:.2f} = {DR*100:.1f}%. "
                f"β from 1Y daily cov(COIN,SPX)/var(SPX). "
                "Revenue = Spot (Binance denom × Coinbase MS × 32 bps blended) + "
                "Derivatives (Deribit denom × Coinbase MS × 35 bps) + "
                "USDC (supply × SOFR × 50%) + Other (staking/custody/subs/Base ≈17% of tx). "
                "PV = Y3 co. val / Y3 diluted shares / (1+DR)³."
            ),
        },
        "current_gp": {
            # Live volume / MS
            "spot_volume_30d":            float(spot_30d),
            "deriv_volume_30d":           float(deriv_30d),
            "spot_volume_30d_ann":        float(spot_ann),
            "deriv_volume_30d_ann":       float(deriv_ann),
            "deribit_volume_30d":         float(deribit_30d),
            "spot_take_rate_bps":         float(spot_take_bps),
            "deriv_take_rate_bps":        float(deriv_take_bps),
            "spot_ms_vs_binance":         float(spot_ms),
            "deriv_ms_vs_deribit":        float(deriv_ms),
            "binance_spot_annual":        float(bn_spot_ann),
            # Current revenue proxies
            "spot_revenue_ann":           float(spot_rev_ann),
            "deriv_revenue_ann":          float(deriv_rev_ann),
            "usdc_revenue_ann":           float(usdc_rev_ann),
            "other_revenue_ann":          float(other_rev_ann),
            "total_revenue_ann":          float(total_rev_ann),
            # USDC / rates
            "usdc_supply":                float(usdc_supply),
            "sofr_rate":                  float(sofr),
            "risk_free_rate":             float(rf),
            # CAPM inputs
            "coin_daily_vol":             float(coin_vol),
            "sp500_daily_vol":            float(sp_vol),
            "capm_beta":                  float(beta),
            "derived_discount_rate":      float(DR),
            # Stock diagnostics
            "shares_outstanding":         float(shares_out),
            "coin_ps_current":            float(mcap / max(total_rev_ann, 1.0)),
            # Base-case Y3 summary
            "y3_revenue_p50":             float(y3_revenue_p50),
            "y3_supply_p50":              float(y3_supply_p50),
            "y3_spot_revenue_p50":        float(base_sc["y3_spot_revenue"]),
            "y3_deriv_revenue_p50":       float(base_sc["y3_deriv_revenue"]),
            "y3_usdc_revenue_p50":        float(base_sc["y3_usdc_revenue"]),
            "y3_other_revenue_p50":       float(base_sc["y3_other_revenue"]),
            "y3_company_val_p50":         float(base_sc["y3_company_val"]),
        },
        "scenarios": scenario_list,
        "caveats": [
            "Coinbase spot volume estimated via CoinGecko exchange (gdax); derivatives estimated as ~4.2% of spot (Q1-2025 empirical ratio).",
            "USDC revenue depends on interest rate environment; SOFR compression in a rate-cut cycle materially reduces base revenue.",
            "Deribit is used as derivatives denominator; Coinbase derivatives market share is small and subject to high estimation error.",
            "Optionality bonus captures International, Base L2, and regulatory tailwinds — not modeled with simulation.",
            "P/S range 4–11× vs comps: Nasdaq ~7×, CME ~20×, ICE ~12×; crypto premium compresses in bear markets.",
            "Discount rate is CAPM-derived from live volatility; will be higher in high-vol periods, lowering PV.",
            "Distributions approximate log-normal σ=1.0; no Monte Carlo simulation.",
        ],
        "data_freshness": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    # ── Embed COIN price history (replaces CoinGecko mcap_history for stocks) ──
    try:
        h = _get("https://query1.finance.yahoo.com/v8/finance/chart/COIN?range=90d&interval=1d")
        ts_list = h["chart"]["result"][0].get("timestamp", [])
        cl_list = h["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        mcap_hist = []
        for i, (ts, cl) in enumerate(zip(ts_list, cl_list)):
            if cl:
                d_str = date.fromtimestamp(ts).isoformat()
                mcap_hist.append({"date": d_str, "mcap": round(float(cl) * shares_out)})
        result["mcap_history"] = mcap_hist
    except Exception:
        result["mcap_history"] = []

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "coinbase_result.json", "w") as f:
        json.dump(result, f, indent=2)

    return result
