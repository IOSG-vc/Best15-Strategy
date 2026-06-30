#!/usr/bin/env python3
"""
update_valuations.py
Runs all available crypto valuation agents (UNI, ETHFI, JUP), fetches 90-day
historical market cap data, and saves consolidated results to data/valuations.json.

Usage:
  python scripts/update_valuations.py
"""

import json
import math
import os
import sys
import datetime
import traceback
import time
from urllib.request import Request, urlopen
from pathlib import Path

import numpy as np

REPO_ROOT    = Path(__file__).parent.parent

# Load .env.local so API keys are available to Python agents
_env_file = REPO_ROOT / ".env.local"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())
BUNDLE_WEBAPP = REPO_ROOT / "crypto_valuation_agents_bundle" / "webapp"
OUTPUT_FILE  = REPO_ROOT / "data" / "valuations.json"

sys.path.insert(0, str(BUNDLE_WEBAPP))

CG_API_KEY = os.environ.get("COINGECKO_API_KEY", "")
CG_BASE    = "https://pro-api.coingecko.com/api/v3" if CG_API_KEY else "https://api.coingecko.com/api/v3"

TOKENS = [
    ("uni",      "agents.uni",      "Uniswap",        "UNI",   "Ethereum",  "uniswap"),
    ("ethfi",    "agents.ethfi",    "ether.fi",       "ETHFI", "Ethereum",  "ether-fi"),
    ("jup",      "agents.jup",      "Jupiter",        "JUP",   "Solana",    "jupiter-exchange-solana"),
    ("hype",     "agents.hype",     "Hyperliquid",    "HYPE",  "HyperEVM",  "hyperliquid"),
    ("sky",      "agents.sky",      "Sky",            "SKY",   "Ethereum",  "sky"),
    ("lighter",  "agents.lighter",  "Lighter",        "LIT",   "zkSync",    "lighter"),
    ("vvv",      "agents.vvv",      "Venice AI",      "VVV",   "Ethereum",  "venice-token"),
    ("bp",       "agents.bp",       "Backpack",       "BP",    "Solana",    "backpack"),
    ("cards",    "agents.cards",    "Collector Crypt","CARDS", "Solana",    "collector-crypt"),
    # Stock tickers (cg_id="" → agent supplies its own mcap_history)
    ("coinbase",   "agents.coinbase",   "Coinbase",   "COIN",  "NYSE",      ""),
    ("robinhood",  "agents.robinhood",  "Robinhood",  "HOOD",  "NASDAQ",    ""),
]

UA = "Mozilla/5.0 Hermes valuation cron"


def fetch_mcap_history(coingecko_id: str, days: int = 90) -> list[dict]:
    """Fetch daily market cap history from CoinGecko API, with retry on rate-limit."""
    url = (
        f"{CG_BASE}/coins/{coingecko_id}/market_chart"
        f"?vs_currency=usd&days={days}&interval=daily"
    )
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if CG_API_KEY:
        headers["x-cg-pro-api-key"] = CG_API_KEY
    req = Request(url, headers=headers)
    for attempt in range(3):
        try:
            with urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
            return [
                {"date": datetime.datetime.fromtimestamp(ts / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%d"),
                 "mcap": round(mc)}
                for ts, mc in data.get("market_caps", [])
            ]
        except Exception as e:
            if attempt < 2:
                wait = 10 * (attempt + 1)
                print(f"  mcap history fetch failed for {coingecko_id} (attempt {attempt+1}): {e} — retrying in {wait}s")
                time.sleep(wait)
            else:
                print(f"  mcap history fetch failed for {coingecko_id} after 3 attempts: {e}")
    return []


def fetch_price_history(cg_id: str, days: int = 180) -> list[tuple[str, float]]:
    """Return [(date_str, price)] from CoinGecko daily market chart."""
    url = f"{CG_BASE}/coins/{cg_id}/market_chart?vs_currency=usd&days={days}&interval=daily"
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if CG_API_KEY:
        headers["x-cg-pro-api-key"] = CG_API_KEY
    req = Request(url, headers=headers)
    for attempt in range(3):
        try:
            with urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
            return [
                (datetime.datetime.fromtimestamp(ts / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%d"), float(p))
                for ts, p in data.get("prices", [])
            ]
        except Exception as e:
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
            else:
                print(f"  price history fetch failed for {cg_id}: {e}")
    return []


def fetch_yahoo_price_history(ticker: str, days: int = 200) -> list[tuple[str, float]]:
    """Return [(date_str, close_price)] from Yahoo Finance chart API."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={days}d&interval=1d"
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
            result = data["chart"]["result"][0]
            timestamps = result.get("timestamp", [])
            closes = result["indicators"]["quote"][0]["close"]
            return [
                (datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d"), float(p))
                for ts, p in zip(timestamps, closes) if p is not None
            ]
        except Exception as e:
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
            else:
                print(f"  Yahoo Finance price fetch failed for {ticker}: {e}")
    return []


# Stock tickers to use Yahoo Finance for beta computation (token_key → yahoo ticker)
YAHOO_BETA_TICKERS: dict[str, str] = {
    "coinbase":  "COIN",
    "robinhood": "HOOD",
}


def compute_up_down_beta(token_prices: list, btc_prices: list) -> tuple:
    """Return (up_beta, down_beta, ratio) vs BTC over common date range."""
    token_by_date = {d: p for d, p in token_prices}
    btc_by_date   = {d: p for d, p in btc_prices}
    common = sorted(set(token_by_date) & set(btc_by_date))
    if len(common) < 40:
        return None, None, None
    tok = np.array([(token_by_date[d1] / token_by_date[d0]) - 1 for d0, d1 in zip(common, common[1:])])
    btc = np.array([(btc_by_date[d1]   / btc_by_date[d0])   - 1 for d0, d1 in zip(common, common[1:])])

    def _beta(t, b):
        if len(b) < 10:
            return None
        var_b = float(np.var(b))
        return float(np.cov(t, b)[0, 1] / var_b) if var_b > 1e-10 else None

    up_beta   = _beta(tok[btc > 0], btc[btc > 0])
    down_beta = _beta(tok[btc < 0], btc[btc < 0])
    ratio = (up_beta / abs(down_beta)) if (up_beta is not None and down_beta and abs(down_beta) > 1e-6) else None
    return up_beta, down_beta, ratio


results: dict = {}

for token_key, module_path, name, symbol, chain, cg_id in TOKENS:
    print(f"[{symbol}] running valuation …")
    try:
        import importlib
        mod = importlib.import_module(module_path)
        data = mod.run()
        results[token_key] = {
            "name":   name,
            "symbol": symbol,
            "chain":  chain,
            "status": "ok",
            "data":   data,
        }
        print(f"[{symbol}] valuation done ✓")
    except Exception:
        err = traceback.format_exc()
        results[token_key] = {
            "name":      name,
            "symbol":    symbol,
            "chain":     chain,
            "status":    "error",
            "error":     err.strip().splitlines()[-1],
            "traceback": err,
        }
        print(f"[{symbol}] ERROR: {err.strip().splitlines()[-1]}")

    # Market cap history: agent-supplied (stocks) or CoinGecko (crypto)
    if "mcap_history" in (results[token_key].get("data") or {}):
        # Agent already embedded its own history (e.g. stock tickers via Yahoo Finance)
        results[token_key]["mcap_history"] = results[token_key]["data"].pop("mcap_history", [])
        print(f"[{symbol}] using agent-supplied mcap history ({len(results[token_key]['mcap_history'])} pts)")
    elif cg_id:
        print(f"[{symbol}] fetching market cap history …")
        mcap_history = fetch_mcap_history(cg_id)
        results[token_key]["mcap_history"] = mcap_history
        print(f"[{symbol}] {len(mcap_history)} market cap data points ✓")
    else:
        results[token_key]["mcap_history"] = []
        print(f"[{symbol}] no CoinGecko id — mcap history skipped")
    time.sleep(4)  # Respect public rate limits between tokens

# ── Up/Down beta vs BTC ───────────────────────────────────────────────────────
print("\n[BETA] Fetching BTC price history for conditional beta computation…")
btc_prices = fetch_price_history("bitcoin", days=200)
if btc_prices:
    time.sleep(3)
    for token_key, _, _, symbol, _, cg_id in TOKENS:
        if results.get(token_key, {}).get("status") != "ok":
            continue
        try:
            yahoo_ticker = YAHOO_BETA_TICKERS.get(token_key)
            if yahoo_ticker:
                tok_prices = fetch_yahoo_price_history(yahoo_ticker, days=200)
            elif cg_id:
                tok_prices = fetch_price_history(cg_id, days=200)
            else:
                continue
            up_b, dn_b, ratio = compute_up_down_beta(tok_prices, btc_prices)
            gp = (results[token_key].get("data") or {}).get("current_gp")
            if gp is not None:
                gp["up_beta_btc"]    = up_b
                gp["down_beta_btc"]  = dn_b
                gp["beta_ratio_btc"] = ratio
            print(f"[{symbol}] up_beta={f'{up_b:.2f}' if up_b is not None else 'N/A'} "
                  f"down_beta={f'{dn_b:.2f}' if dn_b is not None else 'N/A'} "
                  f"ratio={f'{ratio:.2f}' if ratio is not None else 'N/A'}")
        except Exception as e:
            print(f"[{symbol}] beta computation failed: {e}")
        time.sleep(3)
else:
    print("[BETA] BTC price fetch failed — skipping betas")

# ── Implied growth rate from current market price ────────────────────────────
# Formula: implied_y3_gp = spot × y3_supply_p50 × (1+DR)^3 / base_multiple
# base_multiple: ps_center (stock P/S models) or model.multiple (crypto GP models)
# vs_model_pct: how much the implied Y3 GP deviates from the model's P50 projection
# implied_cagr: only computed when a current GP/revenue run-rate is available in current_gp

print("\n[IMPLIED] Computing market-implied growth rates…")
for token_key, _, _, symbol, _, _ in TOKENS:
    try:
        tok_data = (results.get(token_key) or {}).get("data")
        if not tok_data:
            continue
        scenarios = tok_data.get("scenarios", [])
        primary   = next((s for s in scenarios if s.get("is_primary")), None)
        if not primary:
            primary = scenarios[0] if scenarios else None
        if not primary:
            continue

        spot       = float(tok_data.get("market", {}).get("spot", 0) or 0)
        dr         = float(tok_data.get("model", {}).get("discount_rate", 0.20) or 0.20)
        y3_supply  = float(primary.get("y3_supply_p50") or tok_data.get("market", {}).get("circulating_supply", 0) or 0)
        y3_gp_p50  = float(primary.get("y3_gp_p50") or primary.get("y3_revenue_p50") or 0)
        gp_dict    = tok_data.get("current_gp") or {}

        # Pick the exit multiple: P/S-based models store ps_center in the scenario;
        # GP-based models store it in model.multiple
        ps_center = primary.get("ps_center")   # present in COIN and HOOD scenarios
        if ps_center:
            base_multiple = float(ps_center)
        else:
            base_multiple = float(tok_data.get("model", {}).get("multiple", 10) or 10)

        if spot <= 0 or y3_supply <= 0 or base_multiple <= 0:
            continue

        implied_y3_gp = spot * y3_supply * (1 + dr) ** 3 / base_multiple
        vs_model_pct  = ((implied_y3_gp / y3_gp_p50) - 1) * 100 if y3_gp_p50 > 0 else None

        # Current GP/revenue run-rate for CAGR: try common field names
        current_annual = None
        for field in ("total_revenue_ann", "gross_profit_ann", "revenue_ann", "gp_ann",
                      "defillama_30d_ann"):
            v = gp_dict.get(field)
            if v and float(v) > 0:
                current_annual = float(v)
                break

        implied_cagr = None
        if current_annual and implied_y3_gp > 0 and current_annual > 0:
            implied_cagr = (implied_y3_gp / current_annual) ** (1.0 / 3.0) - 1

        gp_dict["implied_y3_gp"]      = implied_y3_gp
        gp_dict["implied_vs_model"]   = vs_model_pct
        gp_dict["implied_cagr"]       = implied_cagr
        gp_dict["implied_multiple"]   = base_multiple
        gp_dict["implied_current_ann"]= current_annual

        vs_str = f"{vs_model_pct:+.0f}%" if vs_model_pct is not None else "N/A"
        label = f"implied_y3={implied_y3_gp/1e9:.2f}B vs_model={vs_str}"
        if implied_cagr is not None:
            label += f" cagr={implied_cagr*100:+.0f}%"
        print(f"  [{symbol}] {label}")
    except Exception as e:
        print(f"  [{symbol}] implied growth computation failed: {e}")

# ── Growth velocity acceleration ─────────────────────────────────────────────
# For each token, derive:
#   accel_vel_short   – most recent velocity window (7D/30D or equivalent)
#   accel_vel_long    – medium-term velocity window (30D/90D–180D or equivalent)
#   acceleration_monthly – vel_short − vel_long (positive = accelerating)
#   positive_streak   – consecutive windows (0-3) with positive velocity
#   trend_label       – "accelerating" | "decelerating" | "stable"
#   vel_unit          – "pct_monthly" (already in %/mo) | "log_ratio" (dimensionless log)

def _compute_acceleration(gp: dict) -> "dict | None":
    vel_w1 = vel_w2 = vel_w3 = None
    unit = "pct_monthly"

    def _f(v) -> "float | None":
        return float(v) if isinstance(v, (int, float)) and v == v else None

    # Pattern 1: JUP-style explicit capped velocity components (perps primary)
    if gp.get("perps_velocity_7d_30d_capped") is not None and gp.get("perps_velocity_30d_180d_capped") is not None:
        vel_w1 = _f(gp["perps_velocity_7d_30d_capped"])
        vel_w2 = _f(gp["perps_velocity_30d_180d_capped"])
    # Pattern 2: UNI-style multiplier-based monthly equiv (convert mult→additive)
    elif gp.get("ms_velocity_short_monthly_equiv") is not None and gp.get("ms_velocity_long_monthly_equiv") is not None:
        s = _f(gp["ms_velocity_short_monthly_equiv"])
        l = _f(gp["ms_velocity_long_monthly_equiv"])
        if s is not None and l is not None:
            vel_w1, vel_w2 = s - 1.0, l - 1.0
    # Pattern 3: ETHFI card velocity ensemble dict
    elif isinstance(gp.get("card_velocity_ensemble"), dict):
        cv = gp["card_velocity_ensemble"]
        vel_w1 = _f(cv.get("capped_7_30") if cv.get("capped_7_30") is not None else cv.get("velocity_7_30"))
        vel_w2 = _f(cv.get("capped_30_180") if cv.get("capped_30_180") is not None else cv.get("velocity_30_180"))
    # Pattern 4: SKY-style named component fields
    elif gp.get("velocity_short_component_monthly") is not None and gp.get("velocity_long_component_monthly") is not None:
        vel_w1 = _f(gp["velocity_short_component_monthly"])
        vel_w2 = _f(gp["velocity_long_component_monthly"])

    # Pattern 5: HYPE / LIGHTER / COIN / HOOD — derive from stored MS trend ratios
    if vel_w1 is None:
        t1 = _f(gp.get("ms7_ms30_trend"))
        t2 = _f(gp.get("ms30_ms180_trend"))
        if t1 and t2 and t1 > 0 and t2 > 0:
            try:
                vel_w1, vel_w2 = math.log(t1), math.log(t2)
                unit = "log_ratio"
            except ValueError:
                pass

    if vel_w1 is None or vel_w2 is None:
        return None

    # Optional 3rd window: ms90 / ms180
    _ms90_keys  = ("ms90_vs_binance", "ms90_vs_money_market", "ms90_vs_dex", "ms90_vs_lrt",
                   "perps_ms90_vs_binance_futures")
    _ms180_keys = ("ms180_vs_binance", "ms180_vs_money_market", "ms180_vs_dex", "ms180_vs_lrt",
                   "perps_ms180_vs_binance_futures")
    ms90  = next((_f(gp[k]) for k in _ms90_keys  if _f(gp.get(k))), None)
    ms180 = next((_f(gp[k]) for k in _ms180_keys if _f(gp.get(k))), None)
    if ms90 and ms180 and ms90 > 0 and ms180 > 0:
        try:
            vel_w3 = math.log(ms90 / ms180)
        except ValueError:
            pass

    vs  = vel_w1
    vl  = vel_w2
    acc = vs - vl

    # Streak: count consecutive positive windows from most recent
    streak = 0
    for v in ([vs, vl] + ([vel_w3] if vel_w3 is not None else [])):
        if v > 0:
            streak += 1
        else:
            break

    # Trend label – threshold depends on unit to avoid spurious "stable" labels
    thr = 0.005 if unit == "pct_monthly" else 0.05
    trend = "stable" if abs(acc) < thr else ("accelerating" if acc > 0 else "decelerating")

    return {
        "accel_vel_short":      round(vs,  6),
        "accel_vel_long":       round(vl,  6),
        "acceleration_monthly": round(acc, 6),
        "positive_streak":      streak,
        "trend_label":          trend,
        "vel_unit":             unit,
    }


print("\n[ACCEL] Computing growth velocity acceleration…")
for token_key, _, _, symbol, _, _ in TOKENS:
    try:
        tok_data = (results.get(token_key) or {}).get("data")
        if not tok_data:
            continue
        gp_dict = tok_data.get("current_gp")
        if not isinstance(gp_dict, dict):
            continue
        acc = _compute_acceleration(gp_dict)
        if acc is None:
            print(f"  [{symbol}] insufficient velocity data — skipped")
            continue
        gp_dict.update(acc)
        streak_str = f"{acc['positive_streak']}-window streak"
        print(f"  [{symbol}] {acc['trend_label']} · accel={acc['acceleration_monthly']:+.4f} · {streak_str}")
    except Exception as e:
        print(f"  [{symbol}] acceleration computation failed: {e}")


output = {
    "lastUpdated": str(datetime.date.today()),
    "tokens": results,
}

OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
with open(OUTPUT_FILE, "w") as f:
    json.dump(output, f, indent=2)

print(f"\nSaved → {OUTPUT_FILE}")
