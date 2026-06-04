#!/usr/bin/env python3
"""
update_valuations.py
Runs all available crypto valuation agents (UNI, ETHFI, JUP), fetches 90-day
historical market cap data, and saves consolidated results to data/valuations.json.

Usage:
  python scripts/update_valuations.py
"""

import json
import os
import sys
import datetime
import traceback
import time
from urllib.request import Request, urlopen
from pathlib import Path

REPO_ROOT    = Path(__file__).parent.parent
BUNDLE_WEBAPP = REPO_ROOT / "crypto_valuation_agents_bundle" / "webapp"
OUTPUT_FILE  = REPO_ROOT / "data" / "valuations.json"

sys.path.insert(0, str(BUNDLE_WEBAPP))

CG_API_KEY = os.environ.get("COINGECKO_API_KEY", "")
CG_BASE    = "https://pro-api.coingecko.com/api/v3" if CG_API_KEY else "https://api.coingecko.com/api/v3"

TOKENS = [
    ("uni",   "agents.uni",   "Uniswap",     "UNI",   "Ethereum",  "uniswap"),
    ("ethfi", "agents.ethfi", "ether.fi",    "ETHFI", "Ethereum",  "ether-fi"),
    ("jup",   "agents.jup",   "Jupiter",     "JUP",   "Solana",    "jupiter-exchange-solana"),
    ("hype",  "agents.hype",  "Hyperliquid", "HYPE",  "HyperEVM",  "hyperliquid"),
    ("sky",   "agents.sky",   "Sky",         "SKY",   "Ethereum",  "sky-governance-token"),
]

UA = "Mozilla/5.0 Hermes valuation cron"


def fetch_mcap_history(coingecko_id: str, days: int = 90) -> list[dict]:
    """Fetch daily market cap history from CoinGecko API."""
    url = (
        f"{CG_BASE}/coins/{coingecko_id}/market_chart"
        f"?vs_currency=usd&days={days}&interval=daily"
    )
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if CG_API_KEY:
        headers["x-cg-pro-api-key"] = CG_API_KEY
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        return [
            {"date": datetime.datetime.fromtimestamp(ts / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%d"),
             "mcap": round(mc)}
            for ts, mc in data.get("market_caps", [])
        ]
    except Exception as e:
        print(f"  mcap history fetch failed for {coingecko_id}: {e}")
        return []


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

    # Fetch historical market cap (independent of valuation success)
    print(f"[{symbol}] fetching market cap history …")
    mcap_history = fetch_mcap_history(cg_id)
    results[token_key]["mcap_history"] = mcap_history
    print(f"[{symbol}] {len(mcap_history)} market cap data points ✓")
    time.sleep(1.5)  # Respect public rate limits between tokens

output = {
    "lastUpdated": str(datetime.date.today()),
    "tokens": results,
}

OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
with open(OUTPUT_FILE, "w") as f:
    json.dump(output, f, indent=2)

print(f"\nSaved → {OUTPUT_FILE}")
