#!/usr/bin/env python3
"""
update_valuations.py
Runs all available crypto valuation agents (UNI, ETHFI, JUP) and saves
consolidated results to data/valuations.json.

Usage:
  python scripts/update_valuations.py
"""

import json
import sys
import datetime
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
BUNDLE_WEBAPP = REPO_ROOT / "crypto_valuation_agents_bundle" / "webapp"
OUTPUT_FILE  = REPO_ROOT / "data" / "valuations.json"

# Make the bundle's agents importable
sys.path.insert(0, str(BUNDLE_WEBAPP))

TOKENS = [
    ("uni",   "agents.uni",   "Uniswap",  "UNI",   "Ethereum"),
    ("ethfi", "agents.ethfi", "ether.fi", "ETHFI",  "Ethereum"),
    ("jup",   "agents.jup",  "Jupiter",  "JUP",    "Solana"),
]

results: dict = {}

for token_key, module_path, name, symbol, chain in TOKENS:
    print(f"[{symbol}] running …")
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
        print(f"[{symbol}] done ✓")
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

output = {
    "lastUpdated": str(datetime.date.today()),
    "tokens": results,
}

OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
with open(OUTPUT_FILE, "w") as f:
    json.dump(output, f, indent=2)

print(f"\nSaved → {OUTPUT_FILE}")
