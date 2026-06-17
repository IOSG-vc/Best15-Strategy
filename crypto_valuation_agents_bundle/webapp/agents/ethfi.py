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
from datetime import datetime, date, timedelta, timezone

import numpy as np

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
OPEX_ANNUAL = 9e6
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
    d = fetch_dune_query_results(query_id)
    if not d:
        return None
    rows = sorted(d.get("result", {}).get("rows", []), key=lambda r: parse_dune_day(r["day"]))
    if len(rows) < 40:
        return None
    latest = parse_dune_day(rows[-1]["day"])
    full = [r for r in rows if parse_dune_day(r["day"]) < latest]
    if not full:
        return None
    last_full = parse_dune_day(full[-1]["day"])

    def spend_between(start, end):
        return sum(float(r.get("spend_usd") or 0.0) for r in full if start <= parse_dune_day(r["day"]) <= end)

    records = []
    for intervals in range(4, 49, 4):
        weeks = []
        for i in range(intervals + 1):
            end = last_full - timedelta(days=7 * i)
            start = end - timedelta(days=6)
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
    logs = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i] > 0 and closes[i - 1] > 0]
    return logs


def growth_path(start_m, m12, m24, m36):
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

    def q(p):
        return s[min(len(s) - 1, int(len(s) * p))]

    d = {"p25": q(0.25), "p50": q(0.50), "p75": q(0.75), "p90": q(0.90), "ev": sum(s) / len(s)}
    if spot is not None:
        d["p_spot_justified"] = sum(1 for x in s if x >= spot) / len(s)
    return d


_MS_AMPLIFIER_CAP = 1.5
_MS_DECAY_MONTHS = 12
_MS_MONTHS = 36
_ETHFI_LRT_CAP = 0.95


def _ms_eoy3(ms90: float, ms30: float, ms_anchor: float, ms_cap: float) -> float:
    velocity = min(max(ms30 / max(ms_anchor, 1e-12), 1.0), _MS_AMPLIFIER_CAP)
    log_v = math.log(velocity) / 6.0
    acc = 0.0
    for m in range(_MS_MONTHS):
        acc += log_v * max(0.0, 1.0 - (m + 0.5) / _MS_DECAY_MONTHS)
    return min(ms90 * math.exp(acc), ms_cap)


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


# Top LRT peers by TVL (excluding ether.fi itself)
LRT_PEER_SLUGS = ["kelp", "renzo", "puffer-stake", "swell-liquid-restaking"]


def fetch_protocol_tvl_daily(slug):
    """Return [(date_str, tvl_usd)] from DefiLlama protocol TVL history."""
    try:
        d = fetch(f"https://api.llama.fi/protocol/{slug}")
        rows = []
        for item in d.get("tvl", []):
            dt = str(datetime.fromtimestamp(item["date"], tz=timezone.utc).date())
            rows.append((dt, float(item["totalLiquidityUSD"])))
        return sorted(rows)
    except Exception:
        return []


def fetch_lst_total_tvl():
    """Return current total liquid staking TVL from DefiLlama protocols list."""
    try:
        protos = fetch("https://api.llama.fi/protocols")
        total = sum(p.get("tvl") or 0.0 for p in protos if p.get("category") == "Liquid Staking")
        return float(total)
    except Exception:
        return None


def compute_ethfi_ms(ethfi_rows, peer_rows_list):
    """Compute rolling 30D/90D mean LRT market share; return snapshot, history, ms_full."""
    ethfi_by_date = dict(ethfi_rows)
    peer_by_date: dict[str, float] = {}
    for rows in peer_rows_list:
        for d, v in rows:
            peer_by_date[d] = peer_by_date.get(d, 0.0) + v

    common = sorted(set(ethfi_by_date) & set(peer_by_date))
    if not common:
        return None, [], []

    ethfi_arr = np.array([ethfi_by_date.get(d, 0.0) for d in common], dtype=float)
    total_arr  = np.array([ethfi_arr[i] + peer_by_date.get(d, 0.0) for i, d in enumerate(common)], dtype=float)
    ratio = np.where(total_arr > 0, ethfi_arr / total_arr, np.nan)

    def rolling_mean(arr, w):
        out = np.full(len(arr), np.nan)
        for i in range(w - 1, len(arr)):
            window = arr[i - w + 1: i + 1]
            valid = window[~np.isnan(window)]
            if len(valid) > 0:
                out[i] = float(valid.mean())
        return out

    ms30  = rolling_mean(ratio, 30)
    ms90  = rolling_mean(ratio, 90)
    ms180 = rolling_mean(ratio, 180)

    def _f(arr): return float(arr[-1]) if not np.isnan(arr[-1]) else None

    snapshot = {
        "ms30": _f(ms30),
        "ms90": _f(ms90),
        "ms180": _f(ms180),
        "lrt_total_tvl": float(total_arr[-1]),
        "ethfi_stake_tvl": float(ethfi_arr[-1]),
    }

    start = max(0, len(common) - 365)
    history = []
    ms_full = []
    for i, d in enumerate(common[start:], start=start):
        if np.isnan(ms30[i]):
            continue
        ms30_i  = float(ms30[i])
        ms90_i  = float(ms90[i])  if not np.isnan(ms90[i])  else None
        ms180_i = float(ms180[i]) if not np.isnan(ms180[i]) else None
        history.append({"date": d, "ms30": round(ms30_i, 5),
                        "ms90": round(ms90_i, 5) if ms90_i is not None else None})
        ms_full.append({"date": d, "ms30": ms30_i, "ms90": ms90_i, "ms180": ms180_i})

    return snapshot, history, ms_full


def fetch_ethfi_price_history():
    """Return (price_by_date, mcap_by_date) dicts from CoinGecko market_chart."""
    try:
        url = f"{_CG_BASE}/coins/ether-fi/market_chart?vs_currency=usd&days=365&interval=daily"
        d = fetch(url)
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


def compute_ethfi_hist_charts(ethfi_tvl_rows, ms_full, price_by_date, mcap_by_date,
                               circ, total_annualized, stake_tvl, vault_tvl,
                               DR, multiple, p50_pv):
    """Build hist_charts for ETHFI: backtest + Mcap/GP secondary + EOY3 LRT share."""
    tvl_by_date = dict(ethfi_tvl_rows)
    total_tvl_cur = max(stake_tvl + vault_tvl, 1.0)
    gp_rate = total_annualized / total_tvl_cur  # GP / total TVL (fixed current rate)

    # ── EOY3 LRT market share history ────────────────────────────────────────
    eoy3_ms_out = []
    for row in ms_full:
        ms30 = row["ms30"]; ms90 = row["ms90"]; ms180 = row.get("ms180")
        if ms30 is None or ms90 is None:
            continue
        anchor = ms180 if ms180 is not None else ms90
        eoy3 = _ms_eoy3(ms90, ms30, anchor, _ETHFI_LRT_CAP)
        eoy3_ms_out.append({"date": row["date"], "eoy3": round(eoy3, 5),
                             "ms90": round(ms90, 5), "ms30": round(ms30, 5)})

    # ── Secondary chart: Mcap / GP ratio over time ───────────────────────────
    secondary_data = []
    for d in sorted(set(tvl_by_date) & set(mcap_by_date)):
        tvl_d = tvl_by_date.get(d, 0.0)
        ann_gp_d = tvl_d * gp_rate
        mcap = mcap_by_date.get(d)
        if mcap and ann_gp_d > 0:
            ratio = mcap / ann_gp_d
            if 0 < ratio < 2000:
                secondary_data.append({"date": d, "value": round(ratio, 1)})

    # ── Backtest: model-shaped PV proxy (TVL-anchored GP) ────────────────────
    common_bt = sorted(set(tvl_by_date) & set(price_by_date))
    pv_raw_list = []
    for d in common_bt:
        tvl_d = tvl_by_date.get(d, 0.0)
        ann_gp_d = tvl_d * gp_rate
        pv_raw = ann_gp_d * multiple / ((1 + DR) ** 3) / max(circ, 1.0)
        price = price_by_date.get(d)
        if price and price > 0 and pv_raw > 0:
            pv_raw_list.append((d, pv_raw, price))

    if not pv_raw_list:
        return {"backtest": {"chart": [], "signals": {}, "latest_signal": "NEUTRAL", "last_realized_row": None},
                "secondary_chart": {"label": "Mcap / GP (TVL-proxy)", "subtitle": "",
                                    "note": "", "unit": "x", "data": secondary_data},
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
            "label": "Historical Mcap / GP (TVL-anchored proxy)",
            "subtitle": "Market cap ÷ TVL × current GP/TVL rate",
            "note": "TVL-anchored GP proxy; card business growth is not captured historically.",
            "unit": "x",
            "data": secondary_data,
        },
        "eoy3_ms": eoy3_ms_out,
    }


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
    card_velocity = card_velocity_ensemble(vol)

    stake_tvl = protocol_tvl("ether.fi-stake")
    vault_tvl = protocol_tvl("ether.fi-liquid")

    # ── LRT market share ──────────────────────────────────────────────────────
    ms_snapshot, ms_history, ms_full_hist = None, [], []
    lst_total_tvl = None
    ethfi_tvl_rows_saved = []
    try:
        ethfi_tvl_rows_saved = fetch_protocol_tvl_daily("ether.fi-stake")
        peer_tvl_rows  = [fetch_protocol_tvl_daily(s) for s in LRT_PEER_SLUGS]
        ms_snapshot, ms_history, ms_full_hist = compute_ethfi_ms(ethfi_tvl_rows_saved, peer_tvl_rows)
        lst_total_tvl = fetch_lst_total_tvl()
    except Exception as _e:
        pass

    market = get_market()
    staking_apy, apy_sources = get_avg_staking_apy()
    eth_logs = get_eth_daily_logs()

    price = market["current_price"]
    mcap = market["market_cap"]
    fdv = market.get("fully_diluted_valuation") or price * SUPPLY_Y3
    effective_supply_y3 = max(SUPPLY_Y3, float(market.get("circulating_supply") or 0.0))

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
        "y3_card_gp": [],
        "y3_stake_gp": [],
        "y3_vault_gp": [],
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
        y3_card_gp = []
        y3_stake_gp = []
        y3_vault_gp = []
        y3_card_gdv_ann = []
        y3_stake_tvl = []
        treasury_cash = []
        y2_price_cash_optionality = []
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
            y2 = sum(monthly_gp[12:24])
            cash = sum(max(gp - OPEX_ANNUAL / 12, 0.0) for gp in monthly_gp)
            cash_24 = sum(max(gp - OPEX_ANNUAL / 12, 0.0) for gp in monthly_gp[:24])
            y3_gp.append(y3)
            y3_card_gp.append(sum(card_monthly_gp[-12:]))
            y3_stake_gp.append(sum(stake_monthly_gp[-12:]))
            y3_vault_gp.append(sum(vault_monthly_gp[-12:]))
            treasury_cash.append(cash)
            y3_card_gdv_ann.append(card_gdv_ann)
            y3_stake_tvl.append(final_stake_tvl)
            ev = y3 * Y3_GP_MULTIPLE
            y2_ev = y2 * Y3_GP_MULTIPLE
            y2_price_cash_optionality.append(((y2_ev + cash_24) / effective_supply_y3) * (1 + OPTIONALITY_BONUS))
            pv_gp.append(ev / effective_supply_y3 / ((1 + DISCOUNT_RATE) ** 3))
            pv_gp_cash.append((ev + cash) / effective_supply_y3 / ((1 + DISCOUNT_RATE) ** 3))

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
            "prob_y2_undiscounted_up_30": float(np.mean(np.array(y2_price_cash_optionality) >= 1.30 * price)),
            "prob_y2_undiscounted_down_30": float(np.mean(np.array(y2_price_cash_optionality) <= 0.70 * price)),
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
        weighted_samples.setdefault("y2_price_cash_optionality", []).extend(y2_price_cash_optionality[:sample_n])

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
        "prob_y2_undiscounted_up_30": float(np.mean(np.array(weighted_samples["y2_price_cash_optionality"]) >= 1.30 * price)),
        "prob_y2_undiscounted_down_30": float(np.mean(np.array(weighted_samples["y2_price_cash_optionality"]) <= 0.70 * price)),
        "scenario_weights": SCENARIO_WEIGHTS,
        "optionality_bonus": OPTIONALITY_BONUS,
    }

    # Build standardized frontend scenarios
    frontend_scenarios = []
    for name in ["bear", "base", "bull"]:
        r = results[name]["pv_15x_gp_plus_cash_plus_optionality"]
        frontend_scenarios.append({
            "key": name,
            "label": name.title(),
            "weight": SCENARIO_WEIGHTS[name],
            "margin": results[name]["margin"],
            "pv": {"p25": r["p25"], "p50": r["p50"], "p75": r["p75"], "p90": r["p90"]},
            "ev": r["ev"],
            "prob_above_spot": r.get("p_spot_justified", 0),
            "prob_y2_undiscounted_up_30": results[name].get("prob_y2_undiscounted_up_30"),
            "prob_y2_undiscounted_down_30": results[name].get("prob_y2_undiscounted_down_30"),
            "is_primary": False,
        })
    w = results["weighted_20_40_40"]
    frontend_scenarios.append({
        "key": "weighted",
        "label": "Weighted 20/40/40",
        "weight": 1.0,
        "pv": {
            "p25": w["pv_15x_gp_plus_cash_plus_optionality"]["p25"],
            "p50": w["pv_15x_gp_plus_cash_plus_optionality"]["p50"],
            "p75": w["pv_15x_gp_plus_cash_plus_optionality"]["p75"],
            "p90": w["pv_15x_gp_plus_cash_plus_optionality"]["p90"],
        },
        "ev": w["pv_15x_gp_plus_cash_plus_optionality"]["ev"],
        "prob_above_spot": w["pv_15x_gp_plus_cash_plus_optionality"].get("p_spot_justified", 0),
        "prob_y2_undiscounted_up_30": w.get("prob_y2_undiscounted_up_30"),
        "prob_y2_undiscounted_down_30": w.get("prob_y2_undiscounted_down_30"),
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
            "opex_optional": OPEX_ANNUAL,
            "supply_y3": effective_supply_y3,
            "scheduled_supply_y3": SUPPLY_Y3,
            "note": "Card GP = GDV × 135bps take × margin; staking GP = ETH bootstrap; vault flat; net profit accumulates to treasury cash",
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
            "card_wow": float(card_wow),
            "card_velocity_ensemble": card_velocity,
            # Y3 model outputs (weighted 20/40/40)
            "y3_gp_p50":          results["weighted_20_40_40"]["y3_gp"]["p50"],
            "y3_card_gp_p50":     results["weighted_20_40_40"]["y3_card_gp"]["p50"],
            "y3_stake_gp_p50":    results["weighted_20_40_40"]["y3_stake_gp"]["p50"],
            "y3_vault_gp_p50":    results["weighted_20_40_40"]["y3_vault_gp"]["p50"],
            "y3_card_gdv_ann_p50": results["weighted_20_40_40"]["y3_card_gdv_ann"]["p50"],
            "y3_stake_tvl_p50":   results["weighted_20_40_40"]["y3_stake_tvl"]["p50"],
            "treasury_cash_p50":  results["weighted_20_40_40"]["treasury_cash"]["p50"],
            # LRT market share
            **({"ms30_vs_lrt":      ms_snapshot["ms30"],
                "ms90_vs_lrt":      ms_snapshot["ms90"],
                "ms180_vs_lrt":     ms_snapshot["ms180"],
                "lrt_total_tvl":    ms_snapshot["lrt_total_tvl"],
                "ms30_ms180_trend": (ms_snapshot["ms30"] / ms_snapshot["ms180"])
                                    if ms_snapshot and ms_snapshot["ms30"] and ms_snapshot["ms180"] else None,
                **({"ms30_vs_all_staking": ms_snapshot["ethfi_stake_tvl"] / (lst_total_tvl + ms_snapshot["lrt_total_tvl"])
                    } if lst_total_tvl and lst_total_tvl > 0 else {}),
               } if ms_snapshot else {}),
        },
        "scenarios": frontend_scenarios,
        "ms_history": ms_history,
        "raw_results": results,
    }

    # ── Historical charts (backtest / secondary / EOY3 LRT MS) ──────────────
    try:
        price_hist, mcap_hist = fetch_ethfi_price_history()
        w = results["weighted_20_40_40"]
        p50_pv_ethfi = w["pv_15x_gp"]["p50"]
        result["hist_charts"] = compute_ethfi_hist_charts(
            ethfi_tvl_rows_saved, ms_full_hist,
            price_hist, mcap_hist,
            float(market.get("circulating_supply") or 0),
            float(current_gp), float(stake_tvl), float(vault_tvl),
            DISCOUNT_RATE, Y3_GP_MULTIPLE, p50_pv_ethfi,
        )
    except Exception as _hce:
        pass  # hist_charts is optional

    with open(os.path.join(RESULTS_DIR, "ethfi_result.json"), "w") as f:
        json.dump(result, f, indent=2)

    return result
