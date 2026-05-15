#!/usr/bin/env python3
"""
update_performance.py
Reads weight CSVs from 'Weights History Top15 BTC 50% Cap/',
fetches CoinGecko prices (crypto) + yfinance prices (stocks),
computes returns & metrics, writes data/performance.json.

Usage:
  COINGECKO_API_KEY=<key> python scripts/update_performance.py
"""

import os
import sys
import json
import datetime
import time
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent
WEIGHTS_DIR = REPO_ROOT / "Weights History Top15 BTC 50% Cap"
OUTPUT_FILE = REPO_ROOT / "data" / "performance.json"

# ── CoinGecko ──────────────────────────────────────────────────────────────

API_KEY = os.environ.get("COINGECKO_API_KEY", "")
HEADERS = {
    "accept": "application/json",
    "x-cg-pro-api-key": API_KEY,
}
BASE_URL = "https://pro-api.coingecko.com/api/v3"

# ── Strategy config ────────────────────────────────────────────────────────

WEIGHT_FILES = {
    "etf":     ("MinVar_Tech_Adj_Weights_ETF_WEIGHTS.csv",  "gecko_id", "weight_risk_tech"),
    "quality": ("Quality_Factor_weights.csv",                "gecko_id", "weight"),
    "risk":    ("Risk_Factor_weights.csv",                   None,       "weight"),
    "private": ("Private_Fund_Weights.csv",                  "gecko_id", "weight_risk_tech_quality2"),
}

DISPLAY_NAMES = {
    "etf":     "ETF",
    "quality": "Quality",
    "risk":    "Risk",
    "private": "Private Fund",
}

COLORS = {
    "etf":     "#3b82f6",
    "quality": "#10b981",
    "risk":    "#f59e0b",
    "private": "#8b5cf6",
}

# Mapping from lowercase weight-file IDs → yfinance tickers
STOCK_ID_TO_TICKER: dict[str, str] = {
    "mstr":      "MSTR",
    "hood":      "HOOD",
    "coin":      "COIN",
    "crcl":      "CRCL",
    "robinhood": "HOOD",
    "coinbase":  "COIN",
    "circle":    "CRCL",
}

# Display names for individual assets
ASSET_DISPLAY_NAMES: dict[str, str] = {
    "bitcoin":      "BTC",
    "ethereum":     "ETH",
    "binancecoin":  "BNB",
    "ripple":       "XRP",
    "solana":       "SOL",
    "cardano":      "ADA",
    "litecoin":     "LTC",
    "bitcoin-cash": "BCH",
    "chainlink":    "LINK",
    "stellar":      "XLM",
    "hyperliquid":  "HYPE",
    "uniswap":      "UNI",
    "ethena":       "ENA",
    "morpho":       "MORPHO",
    "ether-fi":     "ETHFI",
    "zcash":        "ZEC",
    "mstr":         "MSTR",
    "hood":         "HOOD",
    "coin":         "COIN",
    "crcl":         "CRCL",
    "sky":          "SKY",
    "aave":         "AAVE",
    "sui":          "SUI",
}

# Fixed colors per asset for consistent display
ASSET_COLORS: dict[str, str] = {
    "bitcoin":      "#f7931a",
    "ethereum":     "#627eea",
    "binancecoin":  "#f3ba2f",
    "ripple":       "#00aae4",
    "solana":       "#9945ff",
    "cardano":      "#0033ad",
    "litecoin":     "#b8b8b8",
    "bitcoin-cash": "#2a5ada",
    "chainlink":    "#375bd2",
    "stellar":      "#e6c34a",
    "hyperliquid":  "#00b4d8",
    "uniswap":      "#ff007a",
    "ethena":       "#1db3a0",
    "morpho":       "#7c3aed",
    "ether-fi":     "#06b6d4",
    "zcash":        "#a1a1aa",
    "mstr":         "#e11d48",
    "hood":         "#22c55e",
    "coin":         "#f59e0b",
    "crcl":         "#818cf8",
    "sky":          "#10b981",
    "aave":         "#b6509e",
    "sui":          "#4da2ff",
}
ASSET_COLOR_FALLBACKS = ["#94a3b8", "#64748b", "#475569", "#334155", "#1e293b"]

# Extra assets to always fetch even if not in any weight CSV
# (used by benchmark construction stages in benchmarkWeights.ts)
EXTRA_CRYPTO_ASSETS: list[str] = ["sky", "aave", "sui"]


# ── Weight loading ─────────────────────────────────────────────────────────

def discover_rebalance_dates():
    result = []
    if not WEIGHTS_DIR.exists():
        print(f"ERROR: weights dir not found: {WEIGHTS_DIR}", file=sys.stderr)
        return result
    for item in WEIGHTS_DIR.iterdir():
        if item.is_dir():
            try:
                d = datetime.datetime.strptime(item.name, "%Y-%m-%d").date()
                result.append((d, item))
            except ValueError:
                continue
    return sorted(result)


def load_weights(folder: Path, filename: str, index_col, weight_col: str):
    """
    Load a weight series from a CSV file.
    Returns pd.Series(index=id, values=weight%) normalised to 100%, or None.
    """
    fpath = folder / filename
    if not fpath.exists():
        for f in folder.iterdir():
            if f.name.lower() == filename.lower():
                fpath = f
                break
        else:
            return None

    df = pd.read_csv(fpath)

    if index_col and index_col in df.columns:
        id_col = index_col
    else:
        unnamed = [c for c in df.columns if c.lower() in ("", "unnamed: 0", "index")]
        id_col = unnamed[0] if unnamed else df.columns[0]

    if weight_col not in df.columns:
        return None

    s = df.set_index(id_col)[weight_col].dropna()
    s = s[s > 0]
    s.index = s.index.astype(str).str.strip().str.lower()
    s.index.name = "id"

    if s.empty:
        return None

    s = s / s.sum() * 100
    return s


# ── Price fetching ─────────────────────────────────────────────────────────

def fetch_crypto_prices(coin_id: str, start_date: datetime.date, end_date: datetime.date):
    """Fetch daily closing prices from CoinGecko. Returns pd.Series or None."""
    start_dt = datetime.datetime.combine(start_date, datetime.time.min)
    end_dt   = datetime.datetime.combine(end_date,   datetime.time(23, 59, 59))

    if (end_dt - start_dt).days < 2:
        start_dt = end_dt - datetime.timedelta(days=90)

    url = f"{BASE_URL}/coins/{coin_id}/market_chart/range"
    params = {
        "vs_currency": "usd",
        "from": int(start_dt.timestamp()),
        "to":   int(end_dt.timestamp()),
    }

    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=30)
            if r.status_code == 429:
                print(f"  Rate limited on {coin_id}, waiting 65s…")
                time.sleep(65)
                continue
            if r.status_code != 200:
                print(f"  HTTP {r.status_code} for {coin_id}: {r.text[:80]}")
                return None

            prices = r.json().get("prices", [])
            if not prices:
                return None

            df = pd.DataFrame(prices, columns=["ts", "price"])
            df["date"] = pd.to_datetime(df["ts"], unit="ms").dt.date
            return df.drop_duplicates("date", keep="last").set_index("date")["price"]
        except Exception as exc:
            print(f"  Error fetching {coin_id} (attempt {attempt + 1}): {exc}")
            time.sleep(5)
    return None


def fetch_stock_prices(
    stock_ids: list[str],
    start_date: datetime.date,
    end_date: datetime.date,
) -> pd.DataFrame:
    """
    Fetch adjusted closing prices for stock tickers via yfinance.
    Returns a DataFrame with lowercase stock IDs as column names.
    Weekend/holiday gaps are forward-filled so the index aligns with crypto.
    """
    if not stock_ids:
        return pd.DataFrame()

    result: dict[str, pd.Series] = {}
    # yfinance end date is exclusive
    yf_end = end_date + datetime.timedelta(days=1)

    for sid in stock_ids:
        ticker = STOCK_ID_TO_TICKER.get(sid)
        if not ticker:
            print(f"  ! No yfinance ticker mapping for: {sid}")
            continue
        try:
            data = yf.download(
                ticker,
                start=str(start_date),
                end=str(yf_end),
                auto_adjust=True,
                progress=False,
            )
            if data.empty:
                print(f"  ! No yfinance data for {ticker}")
                continue

            close = data["Close"].squeeze()  # handles single or MultiIndex columns
            close.index = pd.to_datetime(close.index).normalize()
            result[sid] = close
            print(f"  ✓ {ticker} ({sid}): {len(close)} trading days")
        except Exception as exc:
            print(f"  ! yfinance error for {ticker}: {exc}")

    if not result:
        return pd.DataFrame()

    df = pd.DataFrame(result)
    df.index = pd.to_datetime(df.index)
    return df


# ── Portfolio computation ──────────────────────────────────────────────────

def compute_portfolio_returns(
    weights_by_date: dict,
    prices_df: pd.DataFrame,
) -> pd.Series:
    daily_returns = prices_df.pct_change().dropna(how="all")
    reb_dates = sorted(weights_by_date.keys())
    port_returns = []

    for i, rd in enumerate(reb_dates):
        start = pd.Timestamp(rd)
        end = (
            pd.Timestamp(reb_dates[i + 1]) - pd.Timedelta(days=1)
            if i + 1 < len(reb_dates)
            else daily_returns.index[-1]
        )
        mask = (daily_returns.index >= start) & (daily_returns.index <= end)
        period = daily_returns.loc[mask]
        if period.empty:
            continue

        w = weights_by_date[rd].copy()
        common = w.index.intersection(period.columns)
        if len(common) == 0:
            continue
        w = w[common] / w[common].sum()
        port_returns.append(period[common].dot(w))

    if not port_returns:
        return pd.Series(dtype=float)
    return pd.concat(port_returns).sort_index()


def compute_metrics(returns: pd.Series) -> dict | None:
    if len(returns) < 3:
        return None

    total_ret = (1 + returns).prod() - 1
    n_days = max((returns.index[-1] - returns.index[0]).days, 1)
    ann_factor = 365 / n_days
    ann_ret = (1 + total_ret) ** ann_factor - 1
    vol = returns.std() * np.sqrt(365)
    down_std = returns[returns < 0].std() * np.sqrt(365)
    cum = (1 + returns).cumprod()
    max_dd = (cum / cum.cummax() - 1).min()

    def safe(x):
        return None if (x is None or np.isnan(x) or np.isinf(x)) else round(float(x), 4)

    return {
        "totalReturn":   round(total_ret * 100, 2),
        "annReturn":     round(ann_ret * 100, 2),
        "annVolatility": round(vol * 100, 2),
        "sharpe":        safe(ann_ret / vol if vol > 0 else None),
        "sortino":       safe(ann_ret / down_std if down_std > 0 else None),
        "maxDrawdown":   round(max_dd * 100, 2),
        "calmar":        safe(ann_ret / abs(max_dd) if max_dd != 0 else None),
        "winRate":       round(float((returns > 0).mean() * 100), 1),
        "bestDay":       round(float(returns.max()) * 100, 2),
        "worstDay":      round(float(returns.min()) * 100, 2),
        "numDays":       len(returns),
    }


def compute_monthly_returns(daily_returns: pd.Series) -> list:
    if len(daily_returns) == 0:
        return []
    monthly = daily_returns.resample("ME").apply(lambda x: (1 + x).prod() - 1) * 100
    return [
        {"year": int(d.year), "month": int(d.month), "return": round(float(r), 2)}
        for d, r in monthly.items()
        if not np.isnan(r)
    ]


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    today = datetime.date.today()
    print(f"=== update_performance.py  {today} ===")

    if not API_KEY:
        print("WARNING: COINGECKO_API_KEY not set — crypto requests may fail.")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    rebalance_dates = discover_rebalance_dates()
    print(f"Rebalance dates: {[str(d) for d, _ in rebalance_dates]}")
    if not rebalance_dates:
        sys.exit("ERROR: No rebalance date folders found.")

    # Load all weights (stocks included)
    all_weights: dict[str, dict] = {}
    for strat, (fname, idx_col, wt_col) in WEIGHT_FILES.items():
        all_weights[strat] = {}
        for d, folder in rebalance_dates:
            w = load_weights(folder, fname, idx_col, wt_col)
            if w is not None:
                all_weights[strat][d] = w
        n = len(all_weights[strat])
        print(f"  {'✓' if n else '!'} {DISPLAY_NAMES[strat]:20s} {n} date(s)")

    # Partition IDs into crypto (CoinGecko) and stocks (yfinance)
    all_ids = {
        gid
        for dd in all_weights.values()
        for w in dd.values()
        for gid in w.index
    }
    stock_ids  = sorted(all_ids & set(STOCK_ID_TO_TICKER))
    crypto_ids = sorted((all_ids - set(STOCK_ID_TO_TICKER)) | set(EXTRA_CRYPTO_ASSETS))

    start_date = min(d for dd in all_weights.values() for d in dd)
    end_date   = today

    # ── Fetch crypto prices ──
    print(f"\nFetching CoinGecko prices for {len(crypto_ids)} coins …")
    crypto_prices: dict[str, pd.Series] = {}
    for i, gid in enumerate(crypto_ids):
        print(f"  [{i+1}/{len(crypto_ids)}] {gid}")
        s = fetch_crypto_prices(gid, start_date, end_date)
        if s is not None and len(s) > 0:
            crypto_prices[gid] = s
        time.sleep(0.2)
    print(f"  → {len(crypto_prices)}/{len(crypto_ids)} fetched")

    # ── Fetch stock prices ──
    print(f"\nFetching yfinance prices for {len(stock_ids)} stocks …")
    stock_df = fetch_stock_prices(stock_ids, start_date, end_date)

    # ── Merge into a single price matrix ──
    crypto_df = pd.DataFrame(crypto_prices)
    crypto_df.index = pd.to_datetime(crypto_df.index)

    if not crypto_df.empty and not stock_df.empty:
        # Reindex stocks to the full date range, then ffill for weekends/holidays
        full_idx = crypto_df.index.union(stock_df.index)
        stock_df = stock_df.reindex(full_idx).ffill().bfill()
        prices_df = pd.concat([crypto_df, stock_df], axis=1)
    elif not crypto_df.empty:
        prices_df = crypto_df
    else:
        sys.exit("ERROR: No price data fetched.")

    prices_df = prices_df.sort_index().ffill().bfill()
    print(f"\nPrice matrix: {prices_df.shape[0]} days × {prices_df.shape[1]} assets")
    print(f"  Crypto: {len(crypto_prices)}  |  Stocks: {len(stock_df.columns) if not stock_df.empty else 0}")

    # ── Compute strategy returns ──
    latest_reb_date = max(d for d, _ in rebalance_dates)
    strategies_out: dict = {}

    for strat_key, dates_dict in all_weights.items():
        if not dates_dict:
            continue

        daily_returns = compute_portfolio_returns(dates_dict, prices_df)
        if len(daily_returns) < 2:
            print(f"  Skipping {strat_key}: only {len(daily_returns)} return(s)")
            continue

        cum = (1 + daily_returns).cumprod()
        metrics = compute_metrics(daily_returns)
        monthly = compute_monthly_returns(daily_returns)

        latest_w = dates_dict.get(latest_reb_date)
        if latest_w is None:
            latest_w = dates_dict[max(dates_dict)]
        latest_weights = [
            {"coin": coin, "weight": round(float(wt), 2)}
            for coin, wt in latest_w.sort_values(ascending=False).items()
        ]

        daily_data = [
            {
                "date": str(idx.date()),
                "return": round(float(r), 6),
                "cumReturn": round(float(cum[idx]), 6),
            }
            for idx, r in daily_returns.items()
        ]

        strategies_out[strat_key] = {
            "displayName":    DISPLAY_NAMES[strat_key],
            "color":          COLORS[strat_key],
            "dailyData":      daily_data,
            "metrics":        metrics,
            "latestWeights":  latest_weights,
            "monthlyReturns": monthly,
        }
        print(f"  ✓ {DISPLAY_NAMES[strat_key]}: {len(daily_data)} days")

    # ── Compute individual asset performance ──
    all_strategy_assets = (
        {
            asset_id
            for dates_dict in all_weights.values()
            for w in dates_dict.values()
            for asset_id in w.index
        }
        | set(EXTRA_CRYPTO_ASSETS)
    )
    common_start = pd.Timestamp(start_date)
    assets_out: dict = {}
    fallback_idx = 0

    for asset_id in sorted(all_strategy_assets):
        if asset_id not in prices_df.columns:
            continue
        price_series = prices_df[asset_id]
        price_series = price_series[price_series.index >= common_start].dropna()
        if len(price_series) < 2:
            continue

        cum = price_series / price_series.iloc[0]
        daily_data = [
            {"date": str(idx.date()), "cumReturn": round(float(v), 6)}
            for idx, v in cum.items()
        ]

        color = ASSET_COLORS.get(asset_id)
        if color is None:
            color = ASSET_COLOR_FALLBACKS[fallback_idx % len(ASSET_COLOR_FALLBACKS)]
            fallback_idx += 1

        assets_out[asset_id] = {
            "displayName": ASSET_DISPLAY_NAMES.get(asset_id, asset_id.upper()),
            "type":        "stock" if asset_id in STOCK_ID_TO_TICKER else "crypto",
            "color":       color,
            "dailyData":   daily_data,
        }

    print(f"  ✓ Individual assets: {len(assets_out)}")

    output = {
        "lastUpdated":         str(today),
        "latestRebalanceDate": str(latest_reb_date),
        "rebalanceDates":      [str(d) for d, _ in rebalance_dates],
        "strategies":          strategies_out,
        "assets":              assets_out,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
