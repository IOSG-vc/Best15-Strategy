#!/usr/bin/env python3
import json
import os
import shutil
import sys
import tempfile

import pandas as pd
import yfinance as yf

_OUT_PREFIX = "__CS_YF_BUNDLE_JSON__="


def _emit(payload):
    print(f"{_OUT_PREFIX}{json.dumps(payload, ensure_ascii=True)}", flush=True)


def main():
    if len(sys.argv) < 3:
        _emit({"ok": False, "error": "usage: helper <comma_tickers> <start>"})
        sys.exit(2)

    ticker_arg = sys.argv[1]
    start = sys.argv[2]
    tickers = [t for t in ticker_arg.split(",") if t]
    quant_dir = os.path.dirname(os.path.abspath(__file__))
    cache_root = os.path.join(quant_dir, "cache")
    temp_cache_dir = None

    try:
        import yfinance.cache as yf_cache

        os.makedirs(cache_root, exist_ok=True)
        temp_cache_dir = tempfile.mkdtemp(prefix="yf_cache_", dir=cache_root)
        yf_cache.set_cache_location(temp_cache_dir)

        download_arg = tickers[0] if len(tickers) == 1 else tickers
        df = yf.download(download_arg, start=start, progress=False, threads=False)
        if df is None or len(df) == 0:
            _emit({"ok": False, "error": "returned 0 rows"})
            sys.exit(1)

        close_df = df["Close"].copy()
        if isinstance(close_df, pd.Series):
            close_df = close_df.to_frame(name=tickers[0])

        close_df.index = pd.to_datetime(close_df.index).tz_localize(None)
        close_df = close_df.dropna(how="all")

        payload = {}
        for col in close_df.columns:
            s = close_df[col].dropna()
            payload[str(col)] = {str(idx.date()): float(val) for idx, val in s.items()}

        if not payload:
            _emit({"ok": False, "error": "returned 0 rows"})
            sys.exit(1)

        _emit({"ok": True, "tickers": tickers, "close_map": payload})
        sys.exit(0)
    except Exception as e:
        _emit({"ok": False, "error": f"{type(e).__name__}: {e}"})
        sys.exit(1)
    finally:
        if temp_cache_dir:
            shutil.rmtree(temp_cache_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
