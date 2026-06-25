"""Backpack (BP) webapp valuation agent — driver-based product-line model.

Model structure:
  1. Spot:        Binance spot denominator × BP spot MS × spot take-rate (9.5 bps)
  2. Perps:       Binance futures denominator × BP perps MS × perps take-rate (1.5 bps)
  3. Securities:  Manual bear/base/bull Y3 revenue assumptions (tokenized equities/stocks)

  Company valuation = (spot rev + perps rev + securities rev) × P/S multiple
  Equity pool       = company valuation × 20% equity stake
  PV per BP         = equity pool / Y3 staking supply / (1 + DR)^3

  Supply treatment:
    Phase 1 (250M): currently circulating, always stakeable.
    Phase 2 (375M): unlocks on business milestones — scenarios assume partial/full unlock
                    proportional to business success.
    Phase 3 (375M): post-IPO treasury, excluded from staking model.
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── Model parameters ──────────────────────────────────────────────────────────
EQUITY_STAKE   = 0.20
DISCOUNT_RATE  = 0.25
LOG_NORMAL_SIGMA = 1.0
PHASE_1_SUPPLY   = 250_000_000

# Take rates
SPOT_TAKE_RATE_BPS  = 9.5    # 0.095% spot taker blended
PERPS_TAKE_RATE_BPS = 1.5    # clean treasury revenue take-rate (consistent with HYPE/JUP)

# Blockworks annual Binance denominators (same source as hype_gp_capture_12m_start_run.py / uni.py)
BLOCKWORKS_BINANCE_FUTURES_ANNUAL = {2022: 9.543e12, 2023: 8.401e12, 2024: 15.971e12, 2025: 25.241e12}
BLOCKWORKS_BINANCE_SPOT_ANNUAL    = {2022: 3.554e12, 2023: 2.941e12, 2024: 7.136e12, 2025: 7.307e12}

# Market share caps (fraction of Binance denominator)
PERPS_MS_CAP = 0.15
SPOT_MS_CAP  = 0.10

# Scenarios: (key, label, perps_ms_mult, spot_ms_mult, denominator_growth,
#             securities_y3_rev, ps_multiple, y3_staking_supply, is_primary)
#
# perps_ms_mult / spot_ms_mult: scalar applied to current 30D MS to get Y3 MS.
#   < 1 → share shrinks (bear); ≈ 1 → flat (base); > 1 → share grows (bull).
# denominator_growth: Y3 Binance annual volume vs 2025 Blockworks baseline.
# y3_staking_supply: Phase 1 + Phase 2 unlocked by scenario milestone achievements.
SCENARIOS = [
    ("bear", "Bear: fast decay, 4× P/S, Phase-1 only",
     0.50, 0.50, 1.00, 5_000_000,   4.0, 250_000_000, False),
    ("base", "Base: 12M decay, 7× P/S, Phase-1 + partial Phase-2",
     1.00, 1.00, 1.30, 40_000_000,  7.0, 375_000_000, True),
    ("bull", "Bull: slow decay, 10× P/S, Phase-1 + majority Phase-2",
     1.50, 1.50, 1.60, 120_000_000, 10.0, 550_000_000, False),
]

REVENUE_2025_REPORTED = 100_000_000

CG_ID    = "backpack"
DL_PERPS_SLUG = "backpack-exchange"
DL_FEES_SLUG  = "backpack-exchange"

_CG_KEY  = os.environ.get("COINGECKO_API_KEY", "")
_CG_BASE = "https://pro-api.coingecko.com/api/v3" if _CG_KEY else "https://api.coingecko.com/api/v3"
RESULTS_DIR = Path(__file__).parent.parent / "results"
UA = "Mozilla/5.0 BP-valuation"

# Fallbacks (June 2026)
_FB_SPOT  = 0.594
_FB_MCAP  = 148_000_000.0
_FB_FDV   = 594_000_000.0
_FB_CIRC  = 250_000_000.0
_FB_MAX   = 1_000_000_000.0
_FB_PERPS_30D = 7_400_000_000.0   # ~$247M/day × 30
_FB_SPOT_30D  = 1_200_000_000.0   # ~$40M/day × 30 (estimated)


def _get(url: str, timeout: int = 30) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _fetch_cg_market() -> tuple[float, float, float, float, float]:
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
            max_s  = float(m.get("max_supply") or m.get("total_supply") or fdv / spot)
            return spot, mcap, fdv, supply, max_s
        except Exception as e:
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
            else:
                raise


def _fetch_dl_perps_volumes() -> tuple[float, float, float]:
    """Return (7D, 30D, 180D) perps volume sums from DefiLlama derivatives."""
    try:
        url = f"https://api.llama.fi/summary/derivatives/{DL_PERPS_SLUG}?dataType=dailyVolume"
        d = _get(url)
        rows = sorted(d.get("totalDataChart", []), key=lambda x: x[0])
        vol7  = float(sum(v for _, v in rows[-7:]))
        vol30 = float(sum(v for _, v in rows[-30:]))
        vol180 = float(sum(v for _, v in rows[-180:])) if len(rows) >= 180 else 0.0
        return vol7, vol30, vol180
    except Exception:
        return _FB_PERPS_30D / 30 * 7, _FB_PERPS_30D, 0.0


def _fetch_dl_perps_fees_30d() -> float:
    """Sum last 30 daily fee revenue from DefiLlama fees (for take-rate derivation)."""
    try:
        url = f"https://api.llama.fi/summary/fees/{DL_FEES_SLUG}?dataType=dailyFees"
        d = _get(url)
        rows = sorted(d.get("totalDataChart", []), key=lambda x: x[0])
        return float(sum(v for _, v in rows[-30:]))
    except Exception:
        return 0.0


def _fetch_cg_spot_volume_30d(spot_price: float) -> float:
    """
    Estimate 30D Backpack spot volume via CoinGecko exchange endpoint.
    Returns 30D USD spot volume or falls back to ratio of perps.
    """
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    if _CG_KEY:
        hdrs["x-cg-pro-api-key"] = _CG_KEY
    for ex_id in ("backpack-exchange", "backpack"):
        try:
            url = f"{_CG_BASE}/exchanges/{ex_id}"
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.load(r)
            # CoinGecko returns trade_volume_24h_btc; convert to USD and to 30D
            vol_24h_btc = float(d.get("trade_volume_24h_btc_normalized") or d.get("trade_volume_24h_btc") or 0)
            if vol_24h_btc > 0 and spot_price > 0:
                # Use BTC price implied from spot-price context or just take at face value
                # CoinGecko normalizes to BTC already; use approximate BTC price
                btc_price = 106_000.0  # approximate; will be close enough for MS calculation
                return vol_24h_btc * btc_price * 30
        except Exception:
            continue
    return 0.0


def _binance_annual(table: dict[int, float]) -> float:
    """Return most recent available year's Binance annual volume."""
    for yr in [2025, 2024, 2023, 2022]:
        if yr in table:
            return table[yr]
    return list(table.values())[-1]


def _compute_y3_volume_and_ms(
    current_30d_vol: float,
    binance_annual_current: float,
    binance_annual_y3: float,
    ms_mult: float,
    ms_cap: float,
) -> tuple[float, float, float]:
    """
    Compute Y3 annual volume, current MS, and Y3 MS.

    current_30d_vol:     observed 30D volume for BP product line
    binance_annual_*:    Blockworks-scaled Binance annual volume for denominator
    ms_mult:             scenario multiplier on current MS to derive Y3 MS
    ms_cap:              hard cap on Y3 market share (fraction of Binance)
    """
    binance_30d = binance_annual_current / 12.0
    current_ms = current_30d_vol / max(binance_30d, 1.0)
    y3_ms = min(current_ms * ms_mult, ms_cap)
    y3_annual_vol = binance_annual_y3 * y3_ms
    return y3_annual_vol, current_ms, y3_ms


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


def run() -> dict:
    # ── Market data ───────────────────────────────────────────────────────────
    try:
        spot, mcap, fdv, circ, max_supply = _fetch_cg_market()
    except Exception as e:
        print(f"[BP] CoinGecko failed ({e}); using fallback")
        spot, mcap, fdv, circ, max_supply = _FB_SPOT, _FB_MCAP, _FB_FDV, _FB_CIRC, _FB_MAX

    # ── Volume / fee data ────────────────────────────────────────────────────
    perps_7d, perps_30d, perps_180d = _fetch_dl_perps_volumes()
    perps_fees_30d = _fetch_dl_perps_fees_30d()

    # Spot volume: try CoinGecko exchange endpoint, fall back to ratio of perps
    spot_vol_30d = _fetch_cg_spot_volume_30d(spot)
    if spot_vol_30d <= 0:
        spot_vol_30d = perps_30d * 0.15   # fallback: ~15% of perps (Backpack is perps-heavy)

    # Derive observed perps take rate from DL fees if available
    if perps_fees_30d > 0 and perps_30d > 0:
        obs_perps_take_bps = (perps_fees_30d / perps_30d) * 10_000
        # Blend observed vs model assumption; if observed is wildly off, prefer model
        perps_take_bps = obs_perps_take_bps if 0.5 <= obs_perps_take_bps <= 5.0 else PERPS_TAKE_RATE_BPS
    else:
        perps_take_bps = PERPS_TAKE_RATE_BPS

    # Annualized volumes
    perps_30d_ann = perps_30d * (365 / 30)
    spot_30d_ann  = spot_vol_30d * (365 / 30)

    # Current annualized GP proxy from live volumes
    perp_rev_30d_ann = perps_30d_ann * (perps_take_bps / 10_000)
    spot_rev_30d_ann = spot_30d_ann  * (SPOT_TAKE_RATE_BPS / 10_000)

    # ── Binance denominators ─────────────────────────────────────────────────
    bn_fut_ann  = _binance_annual(BLOCKWORKS_BINANCE_FUTURES_ANNUAL)  # current year
    bn_spot_ann = _binance_annual(BLOCKWORKS_BINANCE_SPOT_ANNUAL)

    # Current market share (30D vs Binance annual / 12)
    perps_ms_current = perps_30d / max(bn_fut_ann / 12.0, 1.0)
    spot_ms_current  = spot_vol_30d / max(bn_spot_ann / 12.0, 1.0)

    # Velocity ratios (daily-avg basis: 7D/30D and 30D/180D)
    perps_avg7  = perps_7d  / 7.0
    perps_avg30 = perps_30d / 30.0
    perps_avg180 = perps_180d / 180.0 if perps_180d > 0 else 0.0
    perps_ms7_ms30_trend   = perps_avg7  / perps_avg30  if perps_avg30  > 0 else None
    perps_ms30_ms180_trend = perps_avg30 / perps_avg180 if perps_avg180 > 0 else None

    # Equity diagnostics at current FDV
    implied_company_val_at_fdv = fdv / EQUITY_STAKE
    equity_pool_at_1b = 1_000_000_000.0 * EQUITY_STAKE
    equity_per_bp_phase1 = equity_pool_at_1b / PHASE_1_SUPPLY

    disc = (1.0 + DISCOUNT_RATE) ** 3
    scenario_list = []

    y3_revenue_p50 = 0.0
    y3_supply_p50  = 0.0

    for (sc_key, sc_label, perps_ms_mult, spot_ms_mult, denom_growth,
         sec_rev, ps_mult, y3_stake_supply, is_primary) in SCENARIOS:

        bn_fut_y3  = bn_fut_ann  * denom_growth
        bn_spot_y3 = bn_spot_ann * denom_growth

        # Y3 volumes and market shares
        y3_perps_vol, _, y3_perps_ms = _compute_y3_volume_and_ms(
            perps_30d, bn_fut_ann, bn_fut_y3, perps_ms_mult, PERPS_MS_CAP
        )
        y3_spot_vol, _, y3_spot_ms = _compute_y3_volume_and_ms(
            spot_vol_30d, bn_spot_ann, bn_spot_y3, spot_ms_mult, SPOT_MS_CAP
        )

        # Y3 revenue by product line
        y3_perps_rev = y3_perps_vol * (perps_take_bps / 10_000)
        y3_spot_rev  = y3_spot_vol  * (SPOT_TAKE_RATE_BPS / 10_000)
        y3_total_rev = y3_perps_rev + y3_spot_rev + sec_rev

        # Valuation chain
        y3_company_val = y3_total_rev * ps_mult
        y3_equity_pool = y3_company_val * EQUITY_STAKE
        y3_price       = y3_equity_pool / max(y3_stake_supply, 1.0)
        pv_median      = y3_price / disc

        pv_dist = _lognorm_pv(pv_median)
        ev      = pv_median * math.exp(LOG_NORMAL_SIGMA ** 2 / 2)

        scenario_list.append({
            "key": sc_key,
            "label": sc_label,
            "is_primary": is_primary,
            "pv": pv_dist,
            "ev": ev,
            "prob_above_spot": _prob_above(spot, pv_median),
            "prob_3x": _prob_above(3 * spot, pv_median),
            "y3_price_p50": y3_price,
            "y3_mcap_p50": y3_price * y3_stake_supply,
            "y3_supply_p50": float(y3_stake_supply),
            "y3_gp_p50": y3_total_rev,
            # Product-line detail
            "y3_perps_volume_ann": y3_perps_vol,
            "y3_spot_volume_ann": y3_spot_vol,
            "y3_perps_ms": y3_perps_ms,
            "y3_spot_ms": y3_spot_ms,
            "y3_perps_revenue": y3_perps_rev,
            "y3_spot_revenue": y3_spot_rev,
            "y3_securities_revenue": float(sec_rev),
            "y3_total_revenue": y3_total_rev,
            "y3_company_val": y3_company_val,
            "y3_equity_pool": y3_equity_pool,
            "ps_multiple": ps_mult,
            "perps_take_rate_bps": perps_take_bps,
            "spot_take_rate_bps": SPOT_TAKE_RATE_BPS,
            "denom_growth": denom_growth,
        })

        if is_primary:
            y3_revenue_p50 = float(y3_total_rev)
            y3_supply_p50  = float(y3_stake_supply)

    base_sc = next((s for s in scenario_list if s["is_primary"]), scenario_list[0])

    result = {
        "token": "BP",
        "name": "Backpack",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "market": {
            "spot": spot, "market_cap": mcap, "fdv": fdv,
            "circulating_supply": circ, "max_supply": max_supply,
        },
        "model": {
            "type": "3Y Driver-Based Equity-Conversion Scenarios",
            "discount_rate": DISCOUNT_RATE,
            "multiple": 7.0,
            "paths": 1,
            "note": (
                "Revenue = Spot (Binance spot denom × MS × 9.5 bps) + "
                "Perps (Binance futures denom × MS × 1.5 bps) + Securities (manual). "
                "Company val = revenue × P/S. Equity pool = co. val × 20%. "
                "PV = equity pool / Y3 staking supply / (1.25)³. "
                "Supply: Phase 1 (250M) always eligible; Phase 2 (375M) unlocks on "
                "business milestones proportional to scenario success. "
                "Distributions approximate log-normal σ=1.0."
            ),
        },
        "current_gp": {
            # Live volume / revenue
            "perp_volume_30d": float(perps_30d),
            "spot_volume_30d": float(spot_vol_30d),
            "perp_volume_30d_ann": float(perps_30d_ann),
            "spot_volume_30d_ann": float(spot_30d_ann),
            "perp_fees_30d": float(perps_fees_30d),
            "perp_take_rate_bps": float(perps_take_bps),
            "spot_take_rate_bps": float(SPOT_TAKE_RATE_BPS),
            "perp_revenue_ann": float(perp_rev_30d_ann),
            "spot_revenue_ann": float(spot_rev_30d_ann),
            "total_revenue_ann": float(perp_rev_30d_ann + spot_rev_30d_ann),
            # Market share (vs Binance denominators)
            "perp_ms30_vs_binance_futures": float(perps_ms_current),
            "spot_ms30_vs_binance_spot": float(spot_ms_current),
            "binance_futures_annual": float(bn_fut_ann),
            "binance_spot_annual": float(bn_spot_ann),
            # Perps velocity ratios (daily-avg basis)
            "ms7_ms30_trend":   perps_ms7_ms30_trend,
            "ms30_ms180_trend": perps_ms30_ms180_trend,
            # Historical / reported
            "revenue_2025_ann": float(REVENUE_2025_REPORTED),
            # Equity diagnostics
            "equity_stake": EQUITY_STAKE,
            "equity_pool_at_1b_val": float(equity_pool_at_1b),
            "equity_per_bp_phase1_only": float(equity_per_bp_phase1),
            "implied_company_val_at_fdv": float(implied_company_val_at_fdv),
            # Base-case Y3 summary
            "y3_revenue_p50": float(y3_revenue_p50),
            "y3_supply_p50": float(y3_supply_p50),
            "y3_perps_revenue_p50": float(base_sc["y3_perps_revenue"]),
            "y3_spot_revenue_p50": float(base_sc["y3_spot_revenue"]),
            "y3_securities_revenue_base": float(base_sc["y3_securities_revenue"]),
            "y3_company_val_p50": float(base_sc["y3_company_val"]),
            "y3_equity_pool_p50": float(base_sc["y3_equity_pool"]),
        },
        "scenarios": scenario_list,
        "caveats": [
            "IPO is not guaranteed; equity conversion does not occur if Backpack does not IPO.",
            "Phase 2 (375M tokens) unlocks on business milestones; each unlock dilutes per-BP equity value.",
            "Spot volume estimated via CoinGecko exchange API; Backpack does not publish spot volume directly.",
            "Perps take-rate derived from DefiLlama fee data; not publicly disclosed by Backpack.",
            "Securities revenue is manually assumed; Backpack has not launched tokenized securities at scale.",
            "No buyback or revenue-share mechanism exists; value is entirely via equity conversion at IPO.",
            "Distributions approximate log-normal σ=1.0; no Monte Carlo simulation.",
        ],
        "data_freshness": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "bp_result.json", "w") as f:
        json.dump(result, f, indent=2)

    return result
