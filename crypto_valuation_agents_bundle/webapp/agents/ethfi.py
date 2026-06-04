"""ETHFI bottom-up GP valuation agent — adapted for webapp (local output, run() entrypoint).

Logic identical to ethfi_mc_agent.py. Changes:
- OUT_DIR points to webapp/results/
- run() returns a standardized dict for the frontend
- Dune fallback used when key unavailable (no Dune key required)
"""
import json
import math
import os
import random
import statistics
import urllib.request
from datetime import datetime, timezone

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
UA = {"User-Agent": "Mozilla/5.0"}

_CG_KEY = os.environ.get("COINGECKO_API_KEY", "")
_CG_BASE = "https://pro-api.coingecko.com/api/v3" if _CG_KEY else "https://api.coingecko.com/api/v3"

CARD_TAKE = 0.0135
CARD_MARGIN_BASE = 0.60
CARD_MARGIN_BEAR = 0.50
CARD_MARGIN_BULL = 0.70
STAKE_TAKE = 0.05
VAULT_FEE = 0.01
SUPPLY_Y3 = 854.7e6
OPEX_ANNUAL = 30e6
DISCOUNT_RATE = 0.275
N_PATHS = 50_000
SEED = 42
Y3_GP_MULTIPLE = 15.0
Y1_MOMENTUM_MULTIPLE = 20.0
SCENARIO_WEIGHTS = {"bear": 0.20, "base": 0.40, "bull": 0.40}
OPTIONALITY_BONUS = 0.10
MONTHLY_CARD_NOISE_SD = 0.015


def fetch(url):
    hdrs = {**UA, "x-cg-pro-api-key": _CG_KEY} if (_CG_KEY and "coingecko.com" in url) else UA
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=hdrs), timeout=45).read().decode())


def chart(url):
    d = fetch(url)
    arr = sorted(d.get("totalDataChart", []), key=lambda x: x[0])
    return [(int(ts), float(v)) for ts, v in arr]


def sum_last(arr, n):
    return sum(v for _, v in arr[-n:]) if arr else 0.0


def protocol_tvl(slug):
    d = fetch(f"https://api.llama.fi/protocol/{slug}")
    tvls = d.get("currentChainTvls", {}) or {}
    vals = [v for v in tvls.values() if isinstance(v, (int, float))]
    return sum(vals) if vals else float(d.get("tvl") or 0.0)


def get_market():
    d = fetch(f"{_CG_BASE}/coins/markets?vs_currency=usd&ids=ether-fi&sparkline=false")
    return d[0]


def get_avg_staking_apy():
    pools = fetch("https://yields.llama.fi/pools").get("data", [])
    lido = []
    ethfi = []
    for p in pools:
        if p.get("chain") != "Ethereum":
            continue
        sym = str(p.get("symbol", "")).upper()
        proj = p.get("project")
        if proj == "lido" and ("STETH" in sym or "WSTETH" in sym):
            lido.append(p)
        if proj == "ether.fi-stake" and "WEETH" in sym:
            ethfi.append(p)
    lido = sorted(lido, key=lambda x: x.get("tvlUsd") or 0, reverse=True)
    ethfi = sorted(ethfi, key=lambda x: x.get("tvlUsd") or 0, reverse=True)
    selected = []
    if lido:
        selected.append(lido[0])
    if ethfi:
        selected.append(ethfi[0])
    apys = [float(p.get("apy") or 0.0) / 100 for p in selected]
    avg = statistics.mean(apys) if apys else 0.0325
    return avg, selected


def get_eth_daily_logs():
    d = fetch("https://query1.finance.yahoo.com/v8/finance/chart/ETH-USD?range=4y&interval=1d")
    r = d["chart"]["result"][0]
    closes = [p for p in r["indicators"]["quote"][0]["close"] if p is not None]
    logs = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i] > 0 and closes[i - 1] > 0]
    return logs


def growth_path(start_m, m12, m24, m36):
    pts = [(0, start_m), (11, m12), (23, m24), (35, m36)]
    out = []
    for i in range(36):
        for (a, ga), (b, gb) in zip(pts[:-1], pts[1:]):
            if a <= i <= b:
                t = (i - a) / max(1, b - a)
                out.append(ga + (gb - ga) * t)
                break
    return out


def summarize(arr, spot=None):
    s = sorted(arr)

    def q(p):
        return s[min(len(s) - 1, int(len(s) * p))]

    d = {"p25": q(0.25), "p50": q(0.50), "p75": q(0.75), "p90": q(0.90), "ev": sum(s) / len(s)}
    if spot is not None:
        d["p_spot_justified"] = sum(1 for x in s if x >= spot) / len(s)
    return d


def run() -> dict:
    """Fetch live data, run ETHFI MC, return standardized result dict."""
    random.seed(SEED)
    os.makedirs(RESULTS_DIR, exist_ok=True)

    vol = chart("https://api.llama.fi/summary/dexs/etherfi-cash-liquid?dataType=dailyVolume")
    rev = chart("https://api.llama.fi/summary/fees/etherfi-cash-liquid?dataType=dailyRevenue")
    gdv_7 = sum_last(vol, 7)
    gdv_30 = sum_last(vol, 30)
    gdv_prev7 = sum(v for _, v in vol[-14:-7])
    gdv_prev30 = sum(v for _, v in vol[-60:-30])
    rev_30 = sum_last(rev, 30)
    gdv_ann_30 = gdv_30 * 365 / 30
    gdv_ann_7 = gdv_7 * 365 / 7
    take_bps_30 = rev_30 / gdv_30 * 10000 if gdv_30 else 0
    card_mom = gdv_30 / gdv_prev30 - 1 if gdv_prev30 else 0
    card_wow = gdv_7 / gdv_prev7 - 1 if gdv_prev7 else 0

    stake_tvl = protocol_tvl("ether.fi-stake")
    vault_tvl = protocol_tvl("ether.fi-liquid")
    market = get_market()
    staking_apy, apy_sources = get_avg_staking_apy()
    eth_logs = get_eth_daily_logs()

    price = market["current_price"]
    mcap = market["market_cap"]
    fdv = market.get("fully_diluted_valuation") or price * SUPPLY_Y3

    current_card_gp = gdv_ann_30 * CARD_TAKE * CARD_MARGIN_BASE
    current_stake_gp = stake_tvl * staking_apy * STAKE_TAKE
    current_vault_gp = vault_tvl * VAULT_FEE
    current_gp = current_card_gp + current_stake_gp + current_vault_gp

    # No Dune key in this env — use fixed fallback
    base_start_m = 0.09
    bear_start_m = max(0.015, base_start_m * 0.50)
    bull_start_m = min(0.12, base_start_m * 1.35)
    card_anchor = None

    scenarios = {
        "bear": {"margin": CARD_MARGIN_BEAR, "growth": growth_path(bear_start_m, 0.005, 0.000, 0.000)},
        "base": {"margin": CARD_MARGIN_BASE, "growth": growth_path(base_start_m, 0.030, 0.010, 0.003)},
        "bull": {"margin": CARD_MARGIN_BULL, "growth": growth_path(bull_start_m, 0.050, 0.020, 0.010)},
    }

    rng_stake = random.Random(SEED + 202)
    stake_monthly_gp_paths = []
    stake_final_tvl_paths = []
    for _ in range(N_PATHS):
        s = 0.0
        eth_mult_months = []
        for m in range(36):
            for _d in range(30):
                s += rng_stake.choice(eth_logs)
            eth_mult_months.append(math.exp(s))
        stake_final_tvl_paths.append(stake_tvl * eth_mult_months[-1])
        stake_monthly_gp_paths.append(
            [stake_tvl * mult * staking_apy * STAKE_TAKE / 12 for mult in eth_mult_months]
        )

    results = {}
    weighted_samples = {
        "pv_15x_gp": [],
        "pv_15x_gp_plus_cash": [],
        "y3_gp": [],
        "y3_card_gdv_ann": [],
        "y3_stake_tvl": [],
        "treasury_cash": [],
    }
    scenario_seed_offsets = {"bear": 0, "base": 1_000_000, "bull": 2_000_000}
    for name, sc in scenarios.items():
        rng_card = random.Random(SEED + scenario_seed_offsets[name] + 101)
        pv_gp = []
        pv_gp_cash = []
        y3_gp = []
        y3_card_gdv_ann = []
        y3_stake_tvl = []
        treasury_cash = []
        for path_i in range(N_PATHS):
            card_gdv_ann = gdv_ann_30
            card_monthly_gp = []
            for gm in sc["growth"]:
                noise = rng_card.gauss(0.0, MONTHLY_CARD_NOISE_SD)
                monthly_growth = max(-0.05, min(0.08, gm + noise))
                card_gdv_ann *= (1 + monthly_growth)
                card_monthly_gp.append(card_gdv_ann * CARD_TAKE * sc["margin"] / 12)
            final_stake_tvl = stake_final_tvl_paths[path_i]
            stake_monthly_gp = stake_monthly_gp_paths[path_i]
            vault = vault_tvl
            vault_monthly_gp = []
            vault_g = {"bear": 0.0, "base": 0.005, "bull": 0.01}[name]
            for _m in range(36):
                vault *= (1 + vault_g)
                vault_monthly_gp.append(vault * VAULT_FEE / 12)
            monthly_gp = [card_monthly_gp[i] + stake_monthly_gp[i] + vault_monthly_gp[i] for i in range(36)]
            y3 = sum(monthly_gp[-12:])
            cash = sum(max(gp - OPEX_ANNUAL / 12, 0.0) for gp in monthly_gp)
            y3_gp.append(y3)
            treasury_cash.append(cash)
            y3_card_gdv_ann.append(card_gdv_ann)
            y3_stake_tvl.append(final_stake_tvl)
            ev = y3 * Y3_GP_MULTIPLE
            pv_gp.append(ev / SUPPLY_Y3 / ((1 + DISCOUNT_RATE) ** 3))
            pv_gp_cash.append((ev + cash) / SUPPLY_Y3 / ((1 + DISCOUNT_RATE) ** 3))

        y3_gp_summary = summarize(y3_gp)
        cash_summary = summarize(treasury_cash)
        sensitivity_rates = [
            max(0.01, DISCOUNT_RATE - 0.10),
            DISCOUNT_RATE - 0.05,
            DISCOUNT_RATE,
            DISCOUNT_RATE + 0.05,
            DISCOUNT_RATE + 0.10,
        ]
        sensitivity = {
            f"{rate:.1%}": {
                "pv_15x_gp_p50": (y3_gp_summary["p50"] * Y3_GP_MULTIPLE) / SUPPLY_Y3 / ((1 + rate) ** 3),
                "pv_15x_gp_plus_cash_p50": (y3_gp_summary["p50"] * Y3_GP_MULTIPLE + cash_summary["p50"]) / SUPPLY_Y3 / ((1 + rate) ** 3),
            }
            for rate in sensitivity_rates
        }
        results[name] = {
            "pv_15x_gp": summarize(pv_gp, price),
            "pv_15x_gp_plus_cash": summarize(pv_gp_cash, price),
            "y3_gp": summarize(y3_gp),
            "y3_card_gdv_ann": summarize(y3_card_gdv_ann),
            "y3_stake_tvl": summarize(y3_stake_tvl),
            "treasury_cash": summarize(treasury_cash),
            "hurdle_sensitivity": sensitivity,
            "margin": sc["margin"],
            "start_growth": sc["growth"][0],
        }
        sample_n = int(round(N_PATHS * SCENARIO_WEIGHTS.get(name, 0.0)))
        weighted_samples["pv_15x_gp"].extend(pv_gp[:sample_n])
        weighted_samples["pv_15x_gp_plus_cash"].extend(pv_gp_cash[:sample_n])
        weighted_samples["y3_gp"].extend(y3_gp[:sample_n])
        weighted_samples["y3_card_gdv_ann"].extend(y3_card_gdv_ann[:sample_n])
        weighted_samples["y3_stake_tvl"].extend(y3_stake_tvl[:sample_n])
        weighted_samples["treasury_cash"].extend(treasury_cash[:sample_n])

    weighted_pv = weighted_samples["pv_15x_gp"]
    weighted_pv_cash = weighted_samples["pv_15x_gp_plus_cash"]
    results["weighted_20_40_40"] = {
        "pv_15x_gp": summarize(weighted_pv, price),
        "pv_15x_gp_plus_cash": summarize(weighted_pv_cash, price),
        "pv_15x_gp_plus_optionality": summarize([x * (1 + OPTIONALITY_BONUS) for x in weighted_pv], price),
        "pv_15x_gp_plus_cash_plus_optionality": summarize([x * (1 + OPTIONALITY_BONUS) for x in weighted_pv_cash], price),
        "y3_gp": summarize(weighted_samples["y3_gp"]),
        "y3_card_gdv_ann": summarize(weighted_samples["y3_card_gdv_ann"]),
        "y3_stake_tvl": summarize(weighted_samples["y3_stake_tvl"]),
        "treasury_cash": summarize(weighted_samples["treasury_cash"]),
        "scenario_weights": SCENARIO_WEIGHTS,
        "optionality_bonus": OPTIONALITY_BONUS,
    }

    # Build standardized frontend scenarios
    frontend_scenarios = []
    for name in ["bear", "base", "bull"]:
        r = results[name]["pv_15x_gp"]
        frontend_scenarios.append({
            "key": name,
            "label": name.title(),
            "weight": SCENARIO_WEIGHTS[name],
            "margin": results[name]["margin"],
            "pv": {"p25": r["p25"], "p50": r["p50"], "p75": r["p75"], "p90": r["p90"]},
            "ev": r["ev"],
            "prob_above_spot": r.get("p_spot_justified", 0),
            "is_primary": name == "base",
        })
    w = results["weighted_20_40_40"]
    frontend_scenarios.append({
        "key": "weighted",
        "label": "Weighted 20/40/40",
        "weight": 1.0,
        "pv": {
            "p25": w["pv_15x_gp"]["p25"],
            "p50": w["pv_15x_gp"]["p50"],
            "p75": w["pv_15x_gp"]["p75"],
            "p90": w["pv_15x_gp"]["p90"],
        },
        "ev": w["pv_15x_gp"]["ev"],
        "prob_above_spot": w["pv_15x_gp"].get("p_spot_justified", 0),
        "is_primary": True,
    })

    result = {
        "token": "ETHFI",
        "name": "ether.fi",
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "market": {
            "spot": float(price),
            "market_cap": float(mcap),
            "fdv": float(fdv),
            "circulating_supply": float(market.get("circulating_supply") or 0),
        },
        "model": {
            "type": "3Y Bottom-Up GP Monte Carlo",
            "discount_rate": DISCOUNT_RATE,
            "multiple": Y3_GP_MULTIPLE,
            "paths": N_PATHS,
            "supply_y3": SUPPLY_Y3,
            "note": "Card GP = GDV × 135bps take × margin; staking GP = ETH bootstrap; vault flat",
        },
        "current_gp": {
            "card_annualized": float(current_card_gp),
            "staking_annualized": float(current_stake_gp),
            "vault_annualized": float(current_vault_gp),
            "total_annualized": float(current_gp),
            "card_gdv_30d_ann": float(gdv_ann_30),
            "staking_apy": float(staking_apy),
            "stake_tvl": float(stake_tvl),
            "vault_tvl": float(vault_tvl),
            "card_take_bps_30d": float(take_bps_30),
            "card_mom": float(card_mom),
        },
        "scenarios": frontend_scenarios,
        "raw_results": results,
    }

    with open(os.path.join(RESULTS_DIR, "ethfi_result.json"), "w") as f:
        json.dump(result, f, indent=2)

    return result
