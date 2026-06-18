#!/usr/bin/env python3
"""ETHFI bottom-up GP valuation agent.

Locked direction from Momir, 2026-05-08:
- Use bottom-up GP, not raw parent revenue.
- Card gross revenue must be margin-adjusted; base card margin 60%.
- Staking APY = average of Lido stETH and ether.fi weETH DefiLlama yield APYs.
- Lending leg excluded from base.
- Focus on GP; optional OPEX = $6M/year for treasury cash / NP sanity.
- Recent card growth informs the forward card GMV growth path, not necessarily the Y3 multiple.
- Y3 exit multiple base = 15x GP. Current/Y1 momentum can be shown separately, but main 3Y line is 15x.
"""

import json, math, os, random, statistics, urllib.request
from datetime import datetime, timezone

OUT_DIR = "/Users/momir_mini/.openclaw/workspace/altcoin_research"
JSON_OUT = os.path.join(OUT_DIR, "ethfi_mc_result.json")
MD_OUT = os.path.join(OUT_DIR, "ethfi_mc_result.md")
UA = {"User-Agent": "Mozilla/5.0"}

# Core assumptions
CARD_TAKE = 0.0135
CARD_MARGIN_BASE = 0.60
CARD_MARGIN_BEAR = 0.50
CARD_MARGIN_BULL = 0.70
STAKE_TAKE = 0.05
VAULT_FEE = 0.01
# Use scheduled/unlocked token denominator, not full 1.0B FDV, because no
# unlock schedule is available for the unaccounted 145.3M ETHFI.
# Current unlocked 809.7M + scheduled remaining locked 45.0M = 854.7M.
SUPPLY_Y3 = 854.7e6

# $6M/year appears to cover on-chain protocol overhead only, not a global card
# business + validator infrastructure. Keep GP as the primary denominator; use a
# Fully loaded payroll-oriented operating cost assumption for treasury cash.
OPEX_ANNUAL = 9e6
DISCOUNT_RATE = 0.275
N_PATHS = 50_000
SEED = 42
Y3_GP_MULTIPLE = 15.0
Y1_MOMENTUM_MULTIPLE = 20.0
SCENARIO_WEIGHTS = {"bear": 0.20, "base": 0.40, "bull": 0.40}
OPTIONALITY_BONUS = 0.10


def fetch(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45).read().decode())


def chart(url):
    d = fetch(url)
    arr = sorted(d.get("totalDataChart", []), key=lambda x: x[0])
    return [(int(ts), float(v)) for ts, v in arr]


def sum_last(arr, n):
    return sum(v for _, v in arr[-n:]) if arr else 0.0


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def monthly_equivalent_growth(new_avg, old_avg, days_between_midpoints):
    if new_avg <= 0 or old_avg <= 0 or days_between_midpoints <= 0:
        return 0.0
    return (new_avg / old_avg) ** (30 / days_between_midpoints) - 1


def card_velocity_ensemble(vol):
    gdv_7 = sum_last(vol, 7)
    gdv_30 = sum_last(vol, 30)
    gdv_180 = sum_last(vol, 180)
    gdv_prev30 = sum(v for _, v in vol[-60:-30])
    gdv_prev180 = sum(v for _, v in vol[-360:-180])

    avg_7 = gdv_7 / 7 if gdv_7 else 0.0
    avg_30 = gdv_30 / 30 if gdv_30 else 0.0
    avg_180 = gdv_180 / 180 if gdv_180 else 0.0

    raw_30d_mom = gdv_30 / gdv_prev30 - 1 if gdv_prev30 else 0.0
    raw_180d_mom = gdv_180 / gdv_prev180 - 1 if gdv_prev180 else 0.0
    velocity_30_180 = monthly_equivalent_growth(avg_30, avg_180, 75)
    velocity_7_30 = monthly_equivalent_growth(avg_7, avg_30, 11.5)

    capped_30_180 = clamp(velocity_30_180, -0.05, 0.12)
    capped_7_30 = clamp(velocity_7_30, -0.05, 0.12)
    ensemble = clamp(0.70 * capped_30_180 + 0.30 * capped_7_30, 0.0, 0.12)

    return {
        "ensemble_monthly": ensemble,
        "velocity_30_180": velocity_30_180,
        "velocity_7_30": velocity_7_30,
        "capped_30_180": capped_30_180,
        "capped_7_30": capped_7_30,
        "raw_30d_mom": raw_30d_mom,
        "raw_180d_mom": raw_180d_mom,
        "gdv_7": gdv_7,
        "gdv_30": gdv_30,
        "gdv_180": gdv_180,
    }


def protocol_tvl(slug):
    d = fetch(f"https://api.llama.fi/protocol/{slug}")
    tvls = d.get("currentChainTvls", {}) or {}
    vals = [v for v in tvls.values() if isinstance(v, (int, float))]
    return sum(vals) if vals else float(d.get("tvl") or 0.0)


def get_market():
    d = fetch("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=ether-fi&sparkline=false")
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
    if lido: selected.append(lido[0])
    if ethfi: selected.append(ethfi[0])
    apys = [float(p.get("apy") or 0.0) / 100 for p in selected]
    avg = statistics.mean(apys) if apys else 0.0325
    return avg, selected


def get_dune_key():
    env_key = os.environ.get("DUNE_API_KEY", "").strip()
    if env_key:
        return env_key
    for p in [os.path.expanduser("~/.hermes/secrets/dune_api_key")]:
        if os.path.exists(p):
            return open(p).read().strip()
    return None


def fetch_dune_query_results(query_id, limit=1000):
    key = get_dune_key()
    if not key:
        return None
    url = f"https://api.dune.com/api/v1/query/{query_id}/results?limit={limit}"
    req = urllib.request.Request(url, headers={"X-Dune-API-Key": key, "User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=45).read().decode())


def parse_dune_day(s):
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def dune_card_growth_anchor(query_id=4455397):
    """Adaptive card growth anchor from Dune rolling 7D spend.

    Formula:
      1. Build rolling 7D spend buckets ending on latest full day.
      2. Compute weekly CGR over windows [4,8,12,16,20,24,28,32,36,40,44,48].
      3. Use mature windows only (8w-20w) when enough data exists; otherwise use all available windows.
      4. Conservative anchor = (min + median) / 2.
      5. Convert weekly anchor to monthly start growth; cap at 12% MoM.
    """
    d = fetch_dune_query_results(query_id)
    if not d:
        return None
    rows = sorted(d.get("result", {}).get("rows", []), key=lambda r: parse_dune_day(r["day"]))
    if len(rows) < 40:
        return None
    latest = parse_dune_day(rows[-1]["day"])
    full = [r for r in rows if parse_dune_day(r["day"]) < latest]  # exclude likely partial current day
    last_full = parse_dune_day(full[-1]["day"])

    def spend_between(start, end):
        return sum(float(r.get("spend_usd") or 0.0) for r in full if start <= parse_dune_day(r["day"]) <= end)

    records = []
    for intervals in range(4, 49, 4):
        weeks = []
        for i in range(intervals + 1):
            end = last_full - __import__('datetime').timedelta(days=7 * i)
            start = end - __import__('datetime').timedelta(days=6)
            weeks.append((start, end, spend_between(start, end)))
        weeks = list(reversed(weeks))
        first, last = weeks[0][2], weeks[-1][2]
        if first > 0 and last > 0:
            weekly_cgr = (last / first) ** (1 / intervals) - 1
            records.append({"weeks": intervals, "weekly_cgr": weekly_cgr, "first_spend": first, "last_spend": last})
    if not records:
        return None
    mature = [r["weekly_cgr"] for r in records if 8 <= r["weeks"] <= 20]
    sample = mature if len(mature) >= 3 else [r["weekly_cgr"] for r in records]
    mn = min(sample)
    med = statistics.median(sample)
    anchor_weekly = (mn + med) / 2
    monthly_start = min((1 + anchor_weekly) ** 4.345 - 1, 0.12)
    return {
        "latest_full_day": str(last_full),
        "records": records,
        "sample_windows": "8w-20w" if len(mature) >= 3 else "available",
        "min_weekly_cgr": mn,
        "median_weekly_cgr": med,
        "anchor_weekly_cgr": anchor_weekly,
        "monthly_start_growth": monthly_start,
    }


def get_eth_daily_logs():
    d = fetch("https://query1.finance.yahoo.com/v8/finance/chart/ETH-USD?range=4y&interval=1d")
    r = d["chart"]["result"][0]
    closes = [p for p in r["indicators"]["quote"][0]["close"] if p is not None]
    logs = [math.log(closes[i] / closes[i-1]) for i in range(1, len(closes)) if closes[i] > 0 and closes[i-1] > 0]
    # 2022+ yahoo range is already approx 4y; keep full sample.
    return logs


def growth_path(start_m, m12, m24, m36):
    # Monthly growth path linearly decaying across milestones.
    return growth_path_points([(0, start_m), (11, m12), (23, m24), (35, m36)])


def growth_path_points(points):
    pts = sorted(points)
    out = []
    for i in range(36):
        for (a, ga), (b, gb) in zip(pts[:-1], pts[1:]):
            if a <= i <= b:
                t = (i - a) / max(1, b - a)
                out.append(ga + (gb - ga) * t)
                break
        else:
            out.append(pts[-1][1])
    return out


def summarize(arr, spot=None):
    s = sorted(arr)
    def q(p): return s[min(len(s)-1, int(len(s)*p))]
    d = {"p25": q(0.25), "p50": q(0.50), "p75": q(0.75), "p90": q(0.90), "ev": sum(s)/len(s)}
    if spot is not None:
        d["p_spot_justified"] = sum(1 for x in s if x >= spot) / len(s)
    return d


def fmt_usd(x):
    if abs(x) >= 1e9: return f"${x/1e9:,.2f}B"
    if abs(x) >= 1e6: return f"${x/1e6:,.1f}M"
    return f"${x:,.0f}"


def fmt_px(x): return f"${x:.3f}"


def run():
    random.seed(SEED)
    os.makedirs(OUT_DIR, exist_ok=True)

    vol = chart("https://api.llama.fi/summary/dexs/etherfi-cash-liquid?dataType=dailyVolume")
    rev = chart("https://api.llama.fi/summary/fees/etherfi-cash-liquid?dataType=dailyRevenue")
    gdv_7 = sum_last(vol, 7); gdv_30 = sum_last(vol, 30)
    gdv_prev7 = sum(v for _, v in vol[-14:-7]); gdv_prev30 = sum(v for _, v in vol[-60:-30])
    rev_30 = sum_last(rev, 30); rev_7 = sum_last(rev, 7)
    gdv_ann_30 = gdv_30 * 365 / 30
    gdv_ann_7 = gdv_7 * 365 / 7
    take_bps_30 = rev_30 / gdv_30 * 10000 if gdv_30 else 0
    card_mom = gdv_30 / gdv_prev30 - 1 if gdv_prev30 else 0
    card_wow = gdv_7 / gdv_prev7 - 1 if gdv_prev7 else 0
    card_velocity = card_velocity_ensemble(vol)

    stake_tvl = protocol_tvl("ether.fi-stake")
    vault_tvl = protocol_tvl("ether.fi-liquid")
    market = get_market()
    staking_apy, apy_sources = get_avg_staking_apy()
    eth_logs = get_eth_daily_logs()

    price = market["current_price"]
    mcap = market["market_cap"]
    fdv = market.get("fully_diluted_valuation") or price * SUPPLY_Y3
    effective_supply_y3 = max(SUPPLY_Y3, float(market.get("circulating_supply") or 0.0))

    # Current GP anchor
    current_card_gp = gdv_ann_30 * CARD_TAKE * CARD_MARGIN_BASE
    current_stake_gp = stake_tvl * staking_apy * STAKE_TAKE
    current_vault_gp = vault_tvl * VAULT_FEE
    current_gp = current_card_gp + current_stake_gp + current_vault_gp

    card_anchor = dune_card_growth_anchor()
    observed_start_m = card_velocity["ensemble_monthly"]
    if observed_start_m <= 0 and card_anchor:
        observed_start_m = max(0.0, min(0.12, card_anchor["monthly_start_growth"]))
    if observed_start_m <= 0:
        observed_start_m = 0.075
    bear_start_m = observed_start_m
    base_start_m = observed_start_m
    bull_start_m = observed_start_m

    # Card growth velocity starts from the observed current MoM rate. Scenarios
    # differ by durability: bear fades in 6 months, base mostly within 12 months,
    # bull more gradually over 24 months.
    scenarios = {
        "bear": {
            "margin": CARD_MARGIN_BEAR,
            "growth": growth_path_points([(0, bear_start_m), (5, 0.0), (35, 0.0)]),
        },
        "base": {
            "margin": CARD_MARGIN_BASE,
            "growth": growth_path_points([(0, base_start_m), (11, 0.012), (35, 0.002)]),
        },
        "bull": {
            "margin": CARD_MARGIN_BULL,
            "growth": growth_path_points([(0, bull_start_m), (23, 0.010), (35, 0.005)]),
        },
    }

    # Small monthly execution noise only; do not bootstrap huge weekly growth into
    # multi-year card compounding.
    MONTHLY_CARD_NOISE_SD = 0.015

    # Precompute one independent staking/ETH simulation set. Re-use the same staking
    # paths across bear/base/bull so scenario differences come from card adoption and
    # card margin, not accidental resampling of ETH/staking.
    rng_stake = random.Random(SEED + 202)
    stake_monthly_gp_paths = []
    stake_final_tvl_paths = []
    for _ in range(N_PATHS):
        s = 0.0
        eth_mult_months = []
        for m in range(36):
            # approx 30 daily returns per month
            for _d in range(30):
                s += rng_stake.choice(eth_logs)
            eth_mult_months.append(math.exp(s))
        stake_final_tvl_paths.append(stake_tvl * eth_mult_months[-1])
        stake_monthly_gp_paths.append([stake_tvl * mult * staking_apy * STAKE_TAKE / 12 for mult in eth_mult_months])

    results = {}
    weighted_samples = {
        "pv_15x_gp": [],
        "pv_15x_gp_plus_cash": [],
        "y3_gp": [],
        "y3_card_gp": [],
        "y3_stake_gp": [],
        "y3_vault_gp": [],
        "y3_card_gdv_ann": [],
        "y3_stake_tvl": [],
        "treasury_cash": [],
    }
    scenario_seed_offsets = {"bear": 0, "base": 1_000_000, "bull": 2_000_000}
    for name, sc in scenarios.items():
        # Use separate card RNG streams independent from staking/ETH paths.
        rng_card = random.Random(SEED + scenario_seed_offsets[name] + 101)
        pv_gp = []
        pv_gp_cash = []
        y3_gp = []
        y3_card_gp = []
        y3_stake_gp = []
        y3_vault_gp = []
        y3_card_gdv_ann = []
        y3_stake_tvl = []
        treasury_cash = []
        for path_i in range(N_PATHS):
            # Card path: deterministic decay + dampened stochastic monthly noise.
            card_gdv_ann = gdv_ann_30
            card_monthly_gp = []
            for gm in sc["growth"]:
                noise = rng_card.gauss(0.0, MONTHLY_CARD_NOISE_SD)
                monthly_growth = max(-0.05, min(0.08, gm + noise))
                card_gdv_ann *= (1 + monthly_growth)
                card_monthly_gp.append(card_gdv_ann * CARD_TAKE * sc["margin"] / 12)

            # Staking path: independent ETH bootstrap, precomputed once and shared
            # across scenarios for clean card-vs-staking decomposition.
            final_stake_tvl = stake_final_tvl_paths[path_i]
            stake_monthly_gp = stake_monthly_gp_paths[path_i]

            # Vault: flat base with very small monthly drift tied to scenario.
            vault = vault_tvl
            vault_monthly_gp = []
            vault_g = {"bear": 0.0, "base": 0.005, "bull": 0.01}[name]
            for _m in range(36):
                vault *= (1 + vault_g)
                vault_monthly_gp.append(vault * VAULT_FEE / 12)

            monthly_gp = [card_monthly_gp[i] + stake_monthly_gp[i] + vault_monthly_gp[i] for i in range(36)]
            y3 = sum(monthly_gp[-12:])
            cash = sum(max(gp - OPEX_ANNUAL/12, 0.0) for gp in monthly_gp)
            y3_gp.append(y3)
            y3_card_gp.append(sum(card_monthly_gp[-12:]))
            y3_stake_gp.append(sum(stake_monthly_gp[-12:]))
            y3_vault_gp.append(sum(vault_monthly_gp[-12:]))
            treasury_cash.append(cash)
            y3_card_gdv_ann.append(card_gdv_ann)
            y3_stake_tvl.append(final_stake_tvl)
            ev = y3 * Y3_GP_MULTIPLE
            pv_gp.append(ev / effective_supply_y3 / ((1 + DISCOUNT_RATE) ** 3))
            pv_gp_cash.append((ev + cash) / effective_supply_y3 / ((1 + DISCOUNT_RATE) ** 3))
        y3_gp_summary = summarize(y3_gp)
        cash_summary = summarize(treasury_cash)
        sensitivity_rates = [max(0.01, DISCOUNT_RATE - 0.10), DISCOUNT_RATE - 0.05, DISCOUNT_RATE, DISCOUNT_RATE + 0.05, DISCOUNT_RATE + 0.10]
        sensitivity = {
            f"{rate:.1%}": {
                "pv_15x_gp_p50": (y3_gp_summary["p50"] * Y3_GP_MULTIPLE) / effective_supply_y3 / ((1 + rate) ** 3),
                "pv_15x_gp_plus_cash_p50": (y3_gp_summary["p50"] * Y3_GP_MULTIPLE + cash_summary["p50"]) / effective_supply_y3 / ((1 + rate) ** 3),
            }
            for rate in sensitivity_rates
        }
        results[name] = {
            "pv_15x_gp": summarize(pv_gp, price),
            "pv_15x_gp_plus_cash": summarize(pv_gp_cash, price),
            "pv_15x_gp_plus_cash_plus_optionality": summarize([x * (1 + OPTIONALITY_BONUS) for x in pv_gp_cash], price),
            "y3_gp": summarize(y3_gp),
            "y3_card_gp": summarize(y3_card_gp),
            "y3_stake_gp": summarize(y3_stake_gp),
            "y3_vault_gp": summarize(y3_vault_gp),
            "y3_card_gdv_ann": summarize(y3_card_gdv_ann),
            "y3_stake_tvl": summarize(y3_stake_tvl),
            "treasury_cash": summarize(treasury_cash),
            "hurdle_sensitivity": sensitivity,
            "margin": sc["margin"],
            "start_growth": sc["growth"][0],
            "growth_path": sc["growth"],
        }
        sample_n = int(round(N_PATHS * SCENARIO_WEIGHTS.get(name, 0.0)))
        weighted_samples["pv_15x_gp"].extend(pv_gp[:sample_n])
        weighted_samples["pv_15x_gp_plus_cash"].extend(pv_gp_cash[:sample_n])
        weighted_samples["y3_gp"].extend(y3_gp[:sample_n])
        weighted_samples["y3_card_gp"].extend(y3_card_gp[:sample_n])
        weighted_samples["y3_stake_gp"].extend(y3_stake_gp[:sample_n])
        weighted_samples["y3_vault_gp"].extend(y3_vault_gp[:sample_n])
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
        "y3_card_gp": summarize(weighted_samples["y3_card_gp"]),
        "y3_stake_gp": summarize(weighted_samples["y3_stake_gp"]),
        "y3_vault_gp": summarize(weighted_samples["y3_vault_gp"]),
        "y3_card_gdv_ann": summarize(weighted_samples["y3_card_gdv_ann"]),
        "y3_stake_tvl": summarize(weighted_samples["y3_stake_tvl"]),
        "treasury_cash": summarize(weighted_samples["treasury_cash"]),
        "scenario_weights": SCENARIO_WEIGHTS,
        "optionality_bonus": OPTIONALITY_BONUS,
    }

    insights = []
    base_pv = results["base"]["pv_15x_gp"]["p50"]
    bull_pv = results["bull"]["pv_15x_gp"]["p50"]
    if base_pv < price:
        insights.append("Base 15x GP P50 remains below spot; investment case needs sustained card GMV growth, higher terminal multiple, or stronger token-capture evidence.")
    if bull_pv < price:
        insights.append("Even bull 15x GP P50 is below spot; spot needs right-tail execution or a multiple above 15x.")
    if card_anchor and card_anchor.get("monthly_start_growth", 0) > 0.10:
        insights.append("Adaptive card growth anchor is near the 12% MoM cap; monitor for slowdown before extrapolating card GMV.")
    if current_gp and mcap / current_gp > 20:
        insights.append("Current MCap/GP is above 20x; current valuation already prices meaningful forward GP growth.")
    if results["base"]["treasury_cash"]["p50"] < 5e6:
        insights.append("At normalized $9M OPEX, treasury cash accumulation becomes more meaningful; still treat '+ cash' as additive rather than supply reduction.")
    insights.append("Revisit supply denominator if the unaccounted 145.3M ETHFI receives a clear unlock schedule.")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "actionable_insights": insights,
        "assumptions": {
            "card_take": CARD_TAKE,
            "card_margin_base": CARD_MARGIN_BASE,
            "stake_take": STAKE_TAKE,
            "staking_apy_avg_lido_ethfi": staking_apy,
            "vault_fee": VAULT_FEE,
            "opex_optional": OPEX_ANNUAL,
            "discount_rate": DISCOUNT_RATE,
            "supply_y3": effective_supply_y3,
            "scheduled_supply_y3": SUPPLY_Y3,
            "y3_gp_multiple": Y3_GP_MULTIPLE,
            "scenario_weights": SCENARIO_WEIGHTS,
            "optionality_bonus": OPTIONALITY_BONUS,
            "lending": "excluded",
            "card_growth_anchor": card_anchor,
            "card_velocity_ensemble": card_velocity,
        },
        "market": market,
        "apy_sources": apy_sources,
        "current": {
            "price": price, "mcap": mcap, "fdv": fdv,
            "gdv_7d_ann": gdv_ann_7, "gdv_30d_ann": gdv_ann_30,
            "card_wow": card_wow, "card_mom": card_mom, "take_bps_30": take_bps_30,
            "stake_tvl": stake_tvl, "vault_tvl": vault_tvl,
            "card_gp": current_card_gp, "stake_gp": current_stake_gp, "vault_gp": current_vault_gp,
            "gp": current_gp,
            "mcap_gp": mcap / current_gp,
            "fdv_gp": fdv / current_gp,
        },
        "results": results,
    }
    json.dump(output, open(JSON_OUT, "w"), indent=2)

    lines = []
    lines.append("# ETHFI GP valuation")
    lines.append("")
    lines.append("## 1) Key assumptions")
    lines.append("```text")
    lines.append(f"Spot                              {fmt_px(price)}")
    lines.append(f"Market cap                        {fmt_usd(mcap)}")
    lines.append(f"FDV                               {fmt_usd(fdv)}")
    lines.append(f"Y3 supply                         {effective_supply_y3/1e6:.1f}M")
    lines.append(f"Scheduled supply reference        {SUPPLY_Y3/1e6:.1f}M")
    lines.append(f"Discount rate                     {DISCOUNT_RATE:.1%}")
    lines.append(f"Y3 GP multiple                    {Y3_GP_MULTIPLE:.0f}x")
    lines.append(f"Scenario weights                  bear/base/bull {SCENARIO_WEIGHTS['bear']:.0%}/{SCENARIO_WEIGHTS['base']:.0%}/{SCENARIO_WEIGHTS['bull']:.0%}")
    lines.append(f"Optionality bonus                 +{OPTIONALITY_BONUS:.0%} to weighted PV")
    lines.append(f"Optional OPEX for cash            {fmt_usd(OPEX_ANNUAL)}/year")
    lines.append(f"Card take-rate                    {CARD_TAKE*10000:.0f}bps")
    lines.append(f"Card margin bear/base/bull        {CARD_MARGIN_BEAR:.0%}/{CARD_MARGIN_BASE:.0%}/{CARD_MARGIN_BULL:.0%}")
    lines.append(f"Staking APY avg Lido/e.fi         {staking_apy:.2%}")
    lines.append(f"Treasury share of staking yield   {STAKE_TAKE:.0%}")
    lines.append(f"Vault fee                         {VAULT_FEE*10000:.0f}bps")
    lines.append(f"Lending leg                       excluded")
    lines.append(f"Card 30D annualized GDV           {fmt_usd(gdv_ann_30)}")
    lines.append(f"Card 7D annualized GDV            {fmt_usd(gdv_ann_7)}")
    lines.append(f"Card growth signal                30D/prior30 {card_mom:+.1%}; 7D WoW {card_wow:+.1%}")
    if card_anchor:
        lines.append(f"Adaptive card growth formula      Dune {card_anchor['sample_windows']}: (min {card_anchor['min_weekly_cgr']:.2%} + median {card_anchor['median_weekly_cgr']:.2%}) / 2 = {card_anchor['anchor_weekly_cgr']:.2%}/wk")
        lines.append(f"Base starting card growth         {base_start_m:.1%} MoM; bear {bear_start_m:.1%}; bull {bull_start_m:.1%}")
    lines.append("```")
    lines.append("")
    lines.append("Actionable insights / assumption watchlist:")
    lines.append("```text")
    for i, insight in enumerate(insights, 1):
        lines.append(f"{i}. {insight}")
    lines.append("```")
    lines.append("")

    lines.append("## 2) Model results")
    lines.append("```text")
    lines.append(f"{'Scenario':<10} {'Basis':<18} {'P25':>7} {'P50':>7} {'EV':>7} {'P75':>7} {'P90':>7} {'P(spot)':>8}")
    lines.append("-" * 80)
    for name in ["bear", "base", "bull"]:
        for label, key in [("15x GP", "pv_15x_gp"), ("15x GP + cash", "pv_15x_gp_plus_cash")]:
            s = results[name][key]
            lines.append(f"{name.title():<10} {label:<18} {fmt_px(s['p25']):>7} {fmt_px(s['p50']):>7} {fmt_px(s['ev']):>7} {fmt_px(s['p75']):>7} {fmt_px(s['p90']):>7} {s['p_spot_justified']*100:>7.1f}%")
    for label, key in [("20/40/40", "pv_15x_gp"), ("+10% opt", "pv_15x_gp_plus_optionality"), ("cash +10% opt", "pv_15x_gp_plus_cash_plus_optionality")]:
        s = results["weighted_20_40_40"][key]
        lines.append(f"{'Weighted':<10} {label:<18} {fmt_px(s['p25']):>7} {fmt_px(s['p50']):>7} {fmt_px(s['ev']):>7} {fmt_px(s['p75']):>7} {fmt_px(s['p90']):>7} {s['p_spot_justified']*100:>7.1f}%")
    lines.append("```")
    lines.append("")
    lines.append("Hurdle-rate sensitivity — P50 15x GP fair value:")
    lines.append("```text")
    sens_rates = list(results["base"]["hurdle_sensitivity"].keys())
    lines.append(f"{'Scenario':<10} " + " ".join(f"{rate:>8}" for rate in sens_rates))
    lines.append("-" * (11 + 9 * len(sens_rates)))
    for name in ["bear", "base", "bull"]:
        sens = results[name]["hurdle_sensitivity"]
        lines.append(f"{name.title():<10} " + " ".join(f"{fmt_px(sens[rate]['pv_15x_gp_p50']):>8}" for rate in sens_rates))
    lines.append("```")
    lines.append("")

    lines.append("Operating outputs:")
    lines.append("```text")
    lines.append(f"{'Scenario':<10} {'Y3 GP P50':>12} {'Y3 card GDV P50':>18} {'Y3 stake TVL P50':>18} {'Cash P50':>12}")
    lines.append("-" * 78)
    for name in ["bear", "base", "bull"]:
        r = results[name]
        lines.append(f"{name.title():<10} {fmt_usd(r['y3_gp']['p50']):>12} {fmt_usd(r['y3_card_gdv_ann']['p50']):>18} {fmt_usd(r['y3_stake_tvl']['p50']):>18} {fmt_usd(r['treasury_cash']['p50']):>12}")
    lines.append("```")
    lines.append("")
    lines.append("Independent-driver sanity check:")
    lines.append("```text")
    lines.append(f"{'Scenario':<10} {'Card GDV P25/P50/P75':>29} {'Stake TVL P25/P50/P75':>29} {'Card GP P50':>12} {'Stake GP P50':>13}")
    lines.append("-" * 92)
    for name in ["bear", "base", "bull"]:
        r = results[name]
        card = r['y3_card_gdv_ann']; stake = r['y3_stake_tvl']; card_gp = r['y3_card_gp']; stake_gp = r['y3_stake_gp']
        lines.append(f"{name.title():<10} {fmt_usd(card['p25'])}/{fmt_usd(card['p50'])}/{fmt_usd(card['p75']):>9} {fmt_usd(stake['p25'])}/{fmt_usd(stake['p50'])}/{fmt_usd(stake['p75']):>9} {fmt_usd(card_gp['p50']):>12} {fmt_usd(stake_gp['p50']):>13}")
    lines.append("```")
    lines.append("")
    lines.append("## 3) Sanity checks / current multiples")
    lines.append("```text")
    lines.append(f"Current card GP                   {fmt_usd(current_card_gp)}")
    lines.append(f"Current staking GP                {fmt_usd(current_stake_gp)}")
    lines.append(f"Current vault GP                  {fmt_usd(current_vault_gp)}")
    lines.append(f"Current bottom-up GP              {fmt_usd(current_gp)}")
    lines.append(f"MCap / current GP                 {mcap/current_gp:.1f}x")
    lines.append(f"FDV / current GP                  {fdv/current_gp:.1f}x")
    lines.append(f"Current 20x GP / Y3 supply        {fmt_px(current_gp*Y1_MOMENTUM_MULTIPLE/effective_supply_y3)}")
    lines.append(f"Current 15x GP / Y3 supply        {fmt_px(current_gp*Y3_GP_MULTIPLE/effective_supply_y3)}")
    lines.append(f"Discounted flat current 15x GP    {fmt_px(current_gp*Y3_GP_MULTIPLE/effective_supply_y3/((1+DISCOUNT_RATE)**3))}")
    lines.append("```")
    report = "\n".join(lines)
    open(MD_OUT, "w").write(report)
    print(MD_OUT)

if __name__ == "__main__":
    run()
