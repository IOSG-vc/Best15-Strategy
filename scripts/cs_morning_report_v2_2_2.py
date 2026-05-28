#!/usr/bin/env python3
"""
CycleSignal Morning Report V2.2.2
===================================
Outputs to data/ directory (repo root) for the Next.js web dashboard:
  data/cycle_state.json    – latest run state (rich, includes signal lists)
  data/cycle_history.json  – append-only daily time series (combo + exposure)
  data/combo_v2_vol_regime.csv   – historical combo (used internally for gate)
  data/exposure_v2_vol_regime.csv – historical exposure

All other behaviour is identical to cs_morning_report_v2_2_2 (PATCH-A + PATCH-B).
"""
import sys, os, json, math, warnings, importlib.util, time, shutil, subprocess, random
import numpy as np, pandas as pd
import requests
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import matplotlib.dates as mdates
from datetime import datetime, timezone, timedelta
from scipy.stats import binomtest
from itertools import combinations
warnings.filterwarnings('ignore')

QUANT_DIR  = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT  = os.path.dirname(QUANT_DIR)
DATA_DIR   = os.path.join(REPO_ROOT, "data")

# All persisted data goes to data/ so it survives GitHub Actions fresh checkouts
STATE_FILE = os.path.join(DATA_DIR, "cycle_state.json")
OUT_PNG    = os.path.join(QUANT_DIR, "cs_morning_report_v2_2.png")

# Ephemeral API cache – kept in scripts/cache/ (use GitHub Actions cache action)
CACHE_DIR        = os.path.join(QUANT_DIR, "cache")
CACHE_BTC        = os.path.join(CACHE_DIR, "cache_btc.json")
CACHE_MACRO      = os.path.join(CACHE_DIR, "cache_macro.json")
CACHE_CQUANT     = os.path.join(CACHE_DIR, "cache_cquant.json")
CACHE_FRED       = os.path.join(CACHE_DIR, "cache_fred.json")
YF_HELPER_FILE   = os.path.join(QUANT_DIR, "cs_morning_report_v2_2_2_yf_helper.py")

# ── Config ────────────────────────────────────────────────────────────────────
TRAIN_START          = "2014-01-01"
EVAL_START           = "2020-01-01"
PRIMARY_HORIZON      = 90
DELTA                = 0.10
N_THRESHOLDS         = 5
COOLDOWN_DAYS        = 7
TOP_N_PCT            = 0.01
MIN_PAIRS            = 5
SIG_FLOOR_SIGMA      = 1.0
ACTIVITY_THRESHOLD   = 0.05
GATE_THRESHOLD_LOOKBACK = 3
HELD_OUT_SPLIT       = 0.70
CQ_KEY   = os.environ.get("CRYPTOQUANT_KEY", "")
FRED_KEY = os.environ.get("FRED_API_KEY", "")
RETRY_MAX            = 300
RETRY_WAIT           = 3
RETRY_WAIT_JITTER    = 2
YF_BUNDLE_TICKERS    = ["BTC-USD", "^GSPC", "^VIX", "DX-Y.NYB", "GC=F", "HYG"]

_CACHE_WARNINGS = []
_DATA_SOURCES   = []
_YF_BUNDLE_DATA = None
_YF_BUNDLE_ERROR = None

# ── Load audited library ──────────────────────────────────────────────────────
LIB_PATH = os.path.join(QUANT_DIR, "btc_combined_backtest_lib.py")
spec = importlib.util.spec_from_file_location("bbt", LIB_PATH)
_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_mod)
_mod.HORIZON_WEIGHTS.clear()
_mod.HORIZON_WEIGHTS.update({3: 1/6, 7: 1/6, 14: 1/6, 30: 1/6, 90: 1/6, 180: 1/6})

# MABreak fix (verbatim from v2 audited)
def _patched_find_events(self, brk_df, close, bit, dirn, holding, before, horizons):
    m = ((brk_df["bit"] == bit) & (brk_df["direction"] == dirn) & (brk_df["date"] < before))
    cands = brk_df[m].copy()
    if cands.empty: return pd.DataFrame()
    for k in self._related_keys(bit, list(holding.keys())):
        if cands.empty: break
        if k in holding and k != bit:
            try: cands = cands[cands["holding"].apply(lambda h: isinstance(h, dict) and h.get(k) == holding[k])]
            except Exception: break
    if cands.empty: return pd.DataFrame()
    clustered, ld = [], None
    for _, r in cands.iterrows():
        if ld is None or (r["date"] - ld).days >= _mod.CLUSTER_GAP: clustered.append(r); ld = r["date"]
    cands = pd.DataFrame(clustered)
    if cands.empty: return pd.DataFrame()
    evts = []
    for _, r in cands.iterrows():
        d = r["date"]
        if d not in close.index: continue
        p0 = close.loc[d]
        rec = {"date": d, "bit": bit, "direction": dirn, "price": p0}
        for h in horizons:
            fi = close.index.searchsorted(d) + h
            if fi < len(close) and close.index[fi] < before: rec[f"fwd_{h}d"] = close.iloc[fi] / p0 - 1
            else: rec[f"fwd_{h}d"] = np.nan
        evts.append(rec)
    return pd.DataFrame(evts)
_mod.MABreakSignal._find_events = _patched_find_events

import yfinance as yf


def _next_yf_retry_wait():
    low = max(0.0, RETRY_WAIT - RETRY_WAIT_JITTER)
    high = RETRY_WAIT + RETRY_WAIT_JITTER
    return random.uniform(low, high)


def _run_yf_bundle_helper(start=TRAIN_START):
    marker = "__CS_YF_BUNDLE_JSON__="
    cmd = [sys.executable, YF_HELPER_FILE, ",".join(YF_BUNDLE_TICKERS), str(start)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

    helper_line = None
    for line in proc.stdout.splitlines():
        if line.startswith(marker):
            helper_line = line[len(marker):]

    if helper_line is None:
        raw = "\n".join(x for x in [proc.stdout.strip(), proc.stderr.strip()] if x).strip()
        return None, raw or f"helper exited with code {proc.returncode}"

    try:
        payload = json.loads(helper_line)
    except json.JSONDecodeError as e:
        raw = "\n".join(x for x in [proc.stdout.strip(), proc.stderr.strip()] if x).strip()
        return None, f"invalid helper JSON ({e}) :: {raw[:300]}"

    if not payload.get("ok"):
        return None, payload.get("error") or f"helper exited with code {proc.returncode}"

    close_map = payload.get("close_map", {})
    out = {}
    for ticker in YF_BUNDLE_TICKERS:
        s_map = close_map.get(ticker, {})
        if not s_map:
            continue
        s = pd.Series(s_map, dtype=float)
        s.index = pd.to_datetime(s.index)
        out[ticker] = s.sort_index()
    return out, None


def _get_yf_bundle(start=TRAIN_START):
    global _YF_BUNDLE_DATA, _YF_BUNDLE_ERROR

    if _YF_BUNDLE_DATA is not None:
        return _YF_BUNDLE_DATA
    if _YF_BUNDLE_ERROR is not None:
        return None

    last_error = None
    for attempt in range(1, RETRY_MAX + 1):
        bundle, err = _run_yf_bundle_helper(start)
        if bundle is not None:
            missing = [ticker for ticker in YF_BUNDLE_TICKERS if ticker not in bundle or len(bundle[ticker]) < 10]
            if not missing:
                _YF_BUNDLE_DATA = bundle
                return _YF_BUNDLE_DATA
            err = f"missing/short series: {missing}"

        last_error = err or "returned 0 rows"
        wait_s = _next_yf_retry_wait()
        print(f"  [Yahoo bundle] attempt {attempt}/{RETRY_MAX} failed: {last_error} -- retry in {wait_s:.1f}s...")
        time.sleep(wait_s)

    _YF_BUNDLE_ERROR = last_error or "bundle unavailable"
    return None


# ── Binance gap-fill (PATCH-B) ────────────────────────────────────────────────

def _fetch_binance_daily_close(start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.Series:
    try:
        start_ms = int(pd.Timestamp(start_date).tz_localize("UTC").timestamp() * 1000)
        end_ms   = int((pd.Timestamp(end_date) + pd.Timedelta(days=1)).tz_localize("UTC").timestamp() * 1000)
        url = (
            "https://data-api.binance.vision/api/v3/klines"
            f"?symbol=BTCUSDT&interval=1d&startTime={start_ms}&endTime={end_ms}&limit=1000"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            return pd.Series(dtype=float)
        data = {}
        for k in rows:
            dt = pd.Timestamp(k[0], unit="ms").normalize()
            data[dt] = float(k[4])
        return pd.Series(data).sort_index()
    except Exception as e:
        print(f"  [Binance] gap-fill fetch failed: {e}")
        return pd.Series(dtype=float)


def _patch_btc_gaps(close: pd.Series) -> pd.Series:
    if close is None or len(close) < 2:
        return close

    full_idx = pd.date_range(close.index.min().normalize(), close.index.max().normalize(), freq="D")
    have     = pd.DatetimeIndex([d.normalize() for d in close.index])
    missing  = full_idx.difference(have)

    if len(missing) == 0:
        print("  [gap-fill] no BTC gap detected in Yahoo daily bars")
        return close

    print(f"\n  [gap-fill] yfinance is missing {len(missing)} BTC daily bar(s):")
    print(f"             {[str(d.date()) for d in missing[:10]]}{'...' if len(missing) > 10 else ''}")

    patch_start = missing.min() - pd.Timedelta(days=2)
    patch_end   = missing.max() + pd.Timedelta(days=1)
    binance_s   = _fetch_binance_daily_close(patch_start, patch_end)

    if binance_s.empty:
        warn_msg = f"⚠️ GAP: yfinance missing {len(missing)} BTC day(s); Binance backfill ALSO failed"
        print(f"\n{'!'*65}\n  {warn_msg}\n{'!'*65}\n")
        _CACHE_WARNINGS.append(warn_msg)
        return close

    patch = binance_s.reindex(missing).dropna()

    if patch.empty:
        warn_msg = f"⚠️ GAP: yfinance missing {len(missing)} BTC day(s); Binance returned no overlap"
        _CACHE_WARNINGS.append(warn_msg)
        return close

    out = pd.concat([close, patch]).sort_index()
    out = out[~out.index.duplicated(keep="first")]

    filled_dates = [str(d.date()) for d in patch.index]
    warn_msg = f"⚠️ MIXED SOURCE: BTC patched {len(patch)} day(s) from Binance (yfinance missing {filled_dates})"
    print(f"\n{'!'*65}\n  {warn_msg}\n{'!'*65}\n")
    _CACHE_WARNINGS.append(warn_msg)
    _DATA_SOURCES.append(("BTC-USD (patched)", "MIXED (yfinance + Binance)", f"patched {len(patch)} day(s)"))
    return out


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _ensure_cache_dir():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)


def _save_series_cache(cache_path, series_or_df, label=""):
    _ensure_cache_dir()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if isinstance(series_or_df, pd.Series):
        payload = series_or_df.copy()
        payload.index = payload.index.astype(str)
        data_dict = payload.to_dict()
    else:
        df = series_or_df.copy()
        df.index = df.index.astype(str)
        data_dict = df.to_dict()
    cache_obj = {"date": today_str, "data": data_dict}
    with open(cache_path, "w") as f:
        json.dump(cache_obj, f)
    if label:
        print(f"  [cache] Saved {label} -> {os.path.basename(cache_path)}")


def _load_series_cache(cache_path):
    if not os.path.exists(cache_path):
        return None, None
    with open(cache_path, "r") as f:
        raw = f.read().strip()
    if not raw:
        return None, None
    cache_obj = json.loads(raw)
    cache_date = cache_obj.get("date", "unknown")
    data_dict  = cache_obj.get("data", {})
    if not data_dict:
        return cache_date, None
    first_val = next(iter(data_dict.values()))
    if isinstance(first_val, dict):
        df = pd.DataFrame(data_dict)
        df.index = pd.to_datetime(df.index)
        return cache_date, df
    else:
        s = pd.Series(data_dict)
        s.index = pd.to_datetime(s.index)
        s = s.sort_index()
        return cache_date, s


def _load_df_cache(cache_path):
    cache_date, obj = _load_series_cache(cache_path)
    if obj is None:
        return cache_date, None
    if isinstance(obj, pd.DataFrame):
        return cache_date, obj
    return cache_date, obj.to_frame()


# ── Data fetch with retry + cache fallback ────────────────────────────────────

def _yf_download_retry(ticker, start=TRAIN_START):
    bundle = _get_yf_bundle(start)
    if bundle is not None and ticker in bundle and len(bundle[ticker]) >= 10:
        s = bundle[ticker].copy()
        s = _patch_btc_gaps(s)
        _save_series_cache(CACHE_BTC, s, label="BTC-USD")
        _DATA_SOURCES.append(("BTC-USD", "LIVE (yfinance)", f"{s.index[0].date()} to {s.index[-1].date()}"))
        return s

    print(f"\n{'!'*65}")
    print(f"  WARNING: {ticker} yfinance download failed after {RETRY_MAX} attempts.")
    print(f"  Attempting to load from cache: {CACHE_BTC}")
    print(f"{'!'*65}\n")

    cache_date, cached_s = _load_series_cache(CACHE_BTC)
    if cached_s is None:
        print(f"FATAL: {ticker} cache file missing or empty. Cannot continue.")
        sys.exit(1)

    today_dt = pd.Timestamp(datetime.now(timezone.utc).date())
    if today_dt not in cached_s.index:
        last_val = cached_s.iloc[-1]
        cached_s.loc[today_dt] = last_val
        cached_s = cached_s.sort_index()
    cached_s = cached_s.ffill()

    warn_msg = f"WARNING: BTC price using CACHED data from {cache_date}"
    _CACHE_WARNINGS.append(f"⚠️ CACHED: BTC from {cache_date}")
    _DATA_SOURCES.append(("BTC-USD", f"CACHED ({cache_date})", f"to {cached_s.index[-1].date()}"))
    return cached_s


def _fetch_macro_all(ref_index):
    bundle = _get_yf_bundle(TRAIN_START)
    macro_tickers = ["^GSPC", "^VIX", "DX-Y.NYB", "GC=F", "HYG"]
    if bundle is None:
        print(f"\nFATAL: Yahoo bundle unavailable after {RETRY_MAX} retries.")
        sys.exit(1)

    missing = [ticker for ticker in macro_tickers if ticker not in bundle or len(bundle[ticker]) < 10]
    if missing:
        print(f"\nFATAL: Yahoo bundle missing macro ticker(s): {missing}")
        sys.exit(1)

    sp500 = bundle["^GSPC"].reindex(ref_index, method="ffill")
    vix   = bundle["^VIX"].reindex(ref_index, method="ffill")
    dxy   = bundle["DX-Y.NYB"].reindex(ref_index, method="ffill")
    gold  = bundle["GC=F"].reindex(ref_index, method="ffill")
    hy    = bundle["HYG"].reindex(ref_index, method="ffill")

    macro_df = pd.DataFrame({"SP500": sp500, "VIX": vix, "DXY": dxy, "Gold": gold, "HYG": hy})
    _save_series_cache(CACHE_MACRO, macro_df, label="Macro(SP500/VIX/DXY/Gold/HYG)")
    _DATA_SOURCES.append(("SP500", "LIVE (yfinance)", f"to {sp500.dropna().index[-1].date()}"))
    return sp500, vix, dxy, gold, hy


def _fetch_cquant_retry(cq_key, start):
    last_error = None
    for attempt in range(1, RETRY_MAX + 1):
        _mod._session = requests.Session()
        result = _mod.fetch_cquant_signals(cq_key, start=start)
        if result is not None and len(result) > 0:
            cq_df = pd.DataFrame(result)
            _save_series_cache(CACHE_CQUANT, cq_df, label="CryptoQuant")
            last_dt = cq_df.index[-1] if hasattr(cq_df.index[-1], 'date') else "unknown"
            _DATA_SOURCES.append(("CryptoQuant", "LIVE (API)", f"to {last_dt}"))
            return result
        last_error = "empty result"
        print(f"  [CryptoQuant] attempt {attempt}/{RETRY_MAX} failed: {last_error} -- retry in {RETRY_WAIT}s...")
        time.sleep(RETRY_WAIT)

    print(f"\n{'!'*65}")
    print(f"  WARNING: CryptoQuant fetch failed after {RETRY_MAX} attempts.")
    print(f"  Attempting to load from cache: {CACHE_CQUANT}")
    print(f"{'!'*65}\n")

    cache_date, cached_obj = _load_df_cache(CACHE_CQUANT)
    if cached_obj is None:
        print("FATAL: CryptoQuant cache file missing or empty. Cannot continue.")
        sys.exit(1)

    today_dt = pd.Timestamp(datetime.now(timezone.utc).date())
    if isinstance(cached_obj, pd.DataFrame):
        cached_obj.index = pd.to_datetime(cached_obj.index)
        if today_dt not in cached_obj.index:
            last_row = cached_obj.iloc[[-1]].copy()
            last_row.index = [today_dt]
            cached_obj = pd.concat([cached_obj, last_row])
        cached_obj = cached_obj.ffill()
        result = {col: cached_obj[col] for col in cached_obj.columns}
    else:
        result = {}

    warn_msg = f"⚠️ CACHED: CryptoQuant data from {cache_date} (API unavailable)"
    _CACHE_WARNINGS.append(warn_msg)
    _DATA_SOURCES.append(("CryptoQuant", f"CACHED ({cache_date})", "API unavailable"))
    return result


def _fetch_fred_retry(fred_api_key, sid, lag_days=0, close_index=None):
    from fredapi import Fred
    last_error = None
    for attempt in range(1, RETRY_MAX + 1):
        fresh_fred = Fred(api_key=fred_api_key)
        s = None
        fetch_ok = True
        try:
            s = fresh_fred.get_series(sid, observation_start=TRAIN_START)
        except (ValueError, Exception) as e:
            last_error = str(e)[:80]
            fetch_ok = False
        if fetch_ok and s is not None:
            s = s.dropna()
            if len(s) > 0:
                if lag_days:
                    s.index = s.index + pd.Timedelta(days=lag_days)
                _save_fred_series_to_cache(sid, s)
                _DATA_SOURCES.append((f"FRED:{sid}", "LIVE (FRED API)", f"to {s.index[-1].date()}"))
                if close_index is not None:
                    return s.reindex(close_index, method="ffill")
                return s
            last_error = f"empty series for {sid}"
        print(f"  [FRED {sid}] attempt {attempt}/{RETRY_MAX} failed: {last_error} -- retry in {RETRY_WAIT}s...")
        time.sleep(RETRY_WAIT)

    print(f"\n  WARNING: FRED fetch for {sid} failed after {RETRY_MAX} attempts.")
    cached_s = _load_fred_series_from_cache(sid)
    if cached_s is None:
        print(f"FATAL: FRED cache for {sid} missing or empty. Cannot continue.")
        sys.exit(1)

    if lag_days:
        cached_s.index = cached_s.index + pd.Timedelta(days=lag_days)

    today_dt = pd.Timestamp(datetime.now(timezone.utc).date())
    if today_dt not in cached_s.index:
        last_val = cached_s.iloc[-1]
        cached_s.loc[today_dt] = last_val
        cached_s = cached_s.sort_index()
    cached_s = cached_s.ffill()

    cache_date_str = _load_fred_cache_date()
    if not any("FRED" in w for w in _CACHE_WARNINGS):
        _CACHE_WARNINGS.append(f"⚠️ CACHED: FRED data from {cache_date_str}")
    _DATA_SOURCES.append((f"FRED:{sid}", f"CACHED ({cache_date_str})", "API unavailable"))

    if close_index is not None:
        return cached_s.reindex(close_index, method="ffill")
    return cached_s


def _save_fred_series_to_cache(sid, s):
    _ensure_cache_dir()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    existing_data = {}
    if os.path.exists(CACHE_FRED):
        with open(CACHE_FRED, "r") as f:
            raw = f.read().strip()
        if raw:
            existing_cache = json.loads(raw)
            existing_data  = existing_cache.get("data", {})
    s_copy = s.copy()
    s_copy.index = s_copy.index.astype(str)
    existing_data[sid] = s_copy.to_dict()
    with open(CACHE_FRED, "w") as f:
        json.dump({"date": today_str, "data": existing_data}, f)


def _load_fred_series_from_cache(sid):
    if not os.path.exists(CACHE_FRED):
        return None
    with open(CACHE_FRED, "r") as f:
        raw = f.read().strip()
    if not raw:
        return None
    cache_obj = json.loads(raw)
    data = cache_obj.get("data", {})
    if sid not in data:
        return None
    s = pd.Series(data[sid])
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def _load_fred_cache_date():
    if not os.path.exists(CACHE_FRED):
        return "unknown"
    with open(CACHE_FRED, "r") as f:
        raw = f.read().strip()
    if not raw:
        return "unknown"
    return json.loads(raw).get("date", "unknown")


# ── Vol Regime Classifier ─────────────────────────────────────────────────────

_VOL_REGIME_ORDER  = ["LOW", "NORMAL", "HIGH", "EXTREME"]
_VOL_REGIME_WEIGHT = {0: 1.0, 1: 0.5, 2: 0.1}

def compute_vol_zscore(close: pd.Series) -> pd.Series:
    log_ret  = np.log(close / close.shift(1))
    vol_30d  = log_ret.rolling(30).std() * np.sqrt(365)
    roll_mean = vol_30d.rolling(730).mean()
    roll_std  = vol_30d.rolling(730).std()
    return ((vol_30d - roll_mean) / roll_std).rename("vol_zscore")

def _get_vol_regime(z_value: float) -> str:
    if np.isnan(z_value): return "NORMAL"
    if z_value < -0.5:    return "LOW"
    elif z_value < 0.5:   return "NORMAL"
    elif z_value < 1.5:   return "HIGH"
    else:                 return "EXTREME"

def _vol_regime_weights(vol_zscore_tr: pd.Series, current_regime: str) -> pd.Series:
    try: cur_idx = _VOL_REGIME_ORDER.index(current_regime)
    except ValueError: cur_idx = 1
    def _w(z):
        reg = _get_vol_regime(z)
        try: dist = abs(_VOL_REGIME_ORDER.index(reg) - cur_idx)
        except ValueError: dist = 2
        return _VOL_REGIME_WEIGHT.get(min(dist, 2), 0.1)
    return vol_zscore_tr.apply(_w)


# ── Holdout pair selection ────────────────────────────────────────────────────

def select_pairs_holdout(pairs, disc_tr, fwd_tr, rd, weights):
    n = len(disc_tr)
    split = int(n * HELD_OUT_SPLIT)
    dt_tr = disc_tr.iloc[:split]; ft_tr = fwd_tr.iloc[:split]
    dt_vl = disc_tr.iloc[split:]; ft_vl = fwd_tr.iloc[split:]
    active = list(set(s for s1, s2 in pairs for s in [s1, s2]))
    active = [s for s in active if s in dt_tr.columns and (dt_tr[s] != 0).mean() > ACTIVITY_THRESHOLD]
    tr_pairs = [(s1, s2) for s1, s2 in pairs if s1 in active and s2 in active]
    if len(tr_pairs) < MIN_PAIRS:
        meta = {p: _mod.pair_power(disc_tr, fwd_tr, p[0], p[1], rd,
                weights=weights, primary_horizon=PRIMARY_HORIZON) for p in pairs}
        ranked = sorted(meta.items(), key=lambda x: -x[1])
        return [p for p, _ in ranked[:MIN_PAIRS]]
    meta = {p: _mod.pair_power(dt_tr, ft_tr, p[0], p[1], rd,
            weights=weights, primary_horizon=PRIMARY_HORIZON) for p in tr_pairs}
    ranked = sorted(meta.items(), key=lambda x: -x[1])
    powers = np.array([s for _, s in ranked])
    floor  = np.mean(powers) + SIG_FLOOR_SIGMA * np.std(powers)
    top_n  = max(math.ceil(len(tr_pairs) * TOP_N_PCT), MIN_PAIRS)
    cands  = []
    for p, sc in ranked:
        if sc < floor: break
        cands.append(p)
        if len(cands) >= top_n: break
    if len(cands) < MIN_PAIRS:
        cands = [p for p, _ in ranked[:MIN_PAIRS]]
    validated = []
    for s1, s2 in cands:
        if s1 in dt_vl.columns and s2 in dt_vl.columns:
            vp = _mod.pair_power(dt_vl, ft_vl, s1, s2, rd,
                                 weights=weights, primary_horizon=PRIMARY_HORIZON)
            if vp > 0: validated.append((s1, s2))
    if len(validated) < MIN_PAIRS: validated = cands[:MIN_PAIRS]
    return validated


def find_gate_holm(combo_trail, close_trail, horizon=PRIMARY_HORIZON, alpha=0.05):
    cn = combo_trail[combo_trail != 0].dropna()
    if len(cn) < 60: return 0.0
    fwd_r = close_trail.pct_change(horizon).shift(-horizon)
    com   = cn.index.intersection(fwd_r.dropna().index)
    if len(com) < 30: return 0.0
    c = cn.loc[com]; f = fwd_r.loc[com]
    hit = ((c < 0) & (f > 0)) | ((c > 0) & (f < 0))
    for step, pct in enumerate([0, 10, 20, 30, 40, 50, 60, 70, 80, 90], 1):
        thr  = 0.0 if pct == 0 else np.percentile(c.abs(), pct)
        mask = c.abs() >= thr if pct > 0 else pd.Series(True, index=c.index)
        n    = mask.sum()
        if n < 20: continue
        k = int(hit[mask].sum())
        if binomtest(k, n, 0.5, alternative='greater').pvalue < alpha / step: return thr
    return float(np.percentile(c.abs(), 50))


def apply_cooldown(raw_exp, cd=COOLDOWN_DAYS):
    res = raw_exp.copy(); prev = raw_exp.iloc[0]; last_dir = 0; lcd = raw_exp.index[0]
    cooldown_events = []
    for i, (dt, tgt) in enumerate(raw_exp.items()):
        if i == 0: res[dt] = tgt; prev = tgt; continue
        d = tgt - prev
        if abs(d) < 0.001: res[dt] = prev; continue
        dirn = 1 if d > 0 else -1
        if last_dir != 0 and dirn != last_dir and (dt - lcd).days < cd:
            res[dt] = prev
            remaining = cd - (dt - lcd).days
            cooldown_events.append({"date": str(dt.date()), "blocked_move": f"{prev:.0%} → {tgt:.0%}",
                                     "reason": f"direction reversal within {cd}d cooldown",
                                     "remaining_days": remaining})
        else:
            res[dt] = tgt; prev = tgt; lcd = dt; last_dir = dirn
    return res, cooldown_events


def load_previous_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return None


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, default=str)


def main():
    today_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prev_state = load_previous_state()
    os.makedirs(DATA_DIR, exist_ok=True)

    print(f"\n{'='*65}")
    print(f"  CycleSignal Morning Report V2.2.2 — {today_str} UTC")
    print(f"  Data dir: {DATA_DIR}")
    print(f"{'='*65}")

    # ── 1. Fetch market data ──────────────────────────────────────────────────
    print("\n[1/6] Fetching Yahoo bundle & market data...")
    close = _yf_download_retry("BTC-USD")
    sp500, vix, dxy, gold, hy = _fetch_macro_all(close.index)

    btc_now      = float(close.iloc[-1])
    btc_prev     = float(close.iloc[-2]) if len(close) > 1 else btc_now
    btc_chg_pct  = (btc_now / btc_prev - 1) * 100
    print(f"  BTC: ${btc_now:,.0f} ({btc_chg_pct:+.1f}%)")

    # ── 2. Compute signals ────────────────────────────────────────────────────
    print("\n[2/6] Computing signals...")
    cq     = _fetch_cquant_retry(CQ_KEY, start=TRAIN_START)
    prx    = _mod.compute_proxy_signals(close, sp500, vix, dxy, gold, hy)
    raw_df = pd.DataFrame({**cq, **prx}).reindex(close.index).ffill()
    ter    = _mod.compute_ternary_matrix(raw_df)
    tsr    = _mod.compute_technical_signals(close, sp500, _mod.build_technical_signal_registry())
    combined = pd.concat([ter, tsr], axis=1).reindex(close.index).fillna(0)
    vol_zscore_aligned = compute_vol_zscore(close).reindex(close.index, method="ffill")
    disc = _mod.discretize_signals(combined)
    fwd  = _mod.compute_forward_returns(close)

    # 6 macro signals via FRED
    ffr  = _fetch_fred_retry(FRED_KEY, "FEDFUNDS",  lag_days=7,  close_index=close.index)
    ppi  = _fetch_fred_retry(FRED_KEY, "PPIACO",    lag_days=60, close_index=close.index)
    cpi  = _fetch_fred_retry(FRED_KEY, "CPIAUCSL",  lag_days=45, close_index=close.index)
    sofr = _fetch_fred_retry(FRED_KEY, "SOFR",      close_index=close.index)
    iorb = _fetch_fred_retry(FRED_KEY, "IORB",      close_index=close.index)
    rrp  = _fetch_fred_retry(FRED_KEY, "RRPONTSYD", close_index=close.index)

    disc["FFR_vs_MA365"]          = np.sign(ffr - ffr.rolling(365).mean()).reindex(disc.index).fillna(0).clip(-1, 1).astype(int)
    disc["SOFR_IORB_Spread_Sign"] = np.sign(sofr - iorb).reindex(disc.index).fillna(0).clip(-1, 1).astype(int)
    disc["RRP_Trend_90d"]         = np.sign(rrp - rrp.rolling(90).mean()).reindex(disc.index).fillna(0).clip(-1, 1).astype(int)
    ppi_yoy = ppi.pct_change(365); cpi_yoy = cpi.pct_change(365)
    disc["PPI_vs_CPI"]            = np.sign(ppi_yoy - cpi_yoy).reindex(disc.index).fillna(0).clip(-1, 1).astype(int)

    sigs_all      = list(disc.columns)
    sig_today     = disc.iloc[-1]
    sig_yesterday = disc.iloc[-2] if len(disc) > 1 else sig_today

    bull_sigs = sig_today[sig_today == -1].index.tolist()
    bear_sigs = sig_today[sig_today ==  1].index.tolist()
    neut_sigs = sig_today[sig_today ==  0].index.tolist()

    flips = []
    for s in sigs_all:
        y = int(sig_yesterday.get(s, 0))
        t = int(sig_today.get(s, 0))
        if y != t:
            dir_map = {-1: "BULL", 0: "NEUTRAL", 1: "BEAR"}
            flips.append({"signal": s, "from": dir_map[y], "to": dir_map[t]})

    print(f"  Bull: {len(bull_sigs)} | Neutral: {len(neut_sigs)} | Bear: {len(bear_sigs)}")
    print(f"  Signal flips today: {len(flips)}")

    # ── 3. Pair selection & composite ────────────────────────────────────────
    print("\n[3/6] Pair selection & composite (Vol Regime weights)...")
    all_rebal  = pd.date_range(pd.Timestamp(EVAL_START), close.index[-1], freq="3MS")
    current_rd = all_rebal[all_rebal <= close.index[-1]][-1]

    all_pairs_info = {}
    combo_parts    = {}
    for ty in [2, 3]:
        train_start_dt = current_rd - pd.DateOffset(years=ty)
        in_train = (disc.index >= train_start_dt) & (disc.index < current_rd)
        disc_tr  = disc[in_train]; fwd_tr = fwd[in_train]
        vol_tr   = vol_zscore_aligned[in_train]
        act      = {s: (disc_tr[s] != 0).mean() for s in sigs_all}
        active_sigs = [s for s, a in act.items() if a > ACTIVITY_THRESHOLD]
        pairs    = list(combinations(active_sigs, 2))
        vz       = float(vol_zscore_aligned.asof(current_rd)) if not pd.isna(vol_zscore_aligned.asof(current_rd)) else np.nan
        regime   = _get_vol_regime(vz)
        n_same   = int((vol_tr.apply(lambda v: _get_vol_regime(v) == regime)).sum())
        weights  = _vol_regime_weights(vol_tr, regime) if n_same >= _mod.MIN_REGIME_TRAIN_DAYS else None
        top_pairs = select_pairs_holdout(pairs, disc_tr, fwd_tr, current_rd, weights)

        for p in top_pairs:
            pw  = _mod.pair_power(disc_tr, fwd_tr, p[0], p[1], current_rd,
                                  weights=weights, primary_horizon=PRIMARY_HORIZON)
            key = f"{p[0]}|{p[1]}"
            if key not in all_pairs_info:
                all_pairs_info[key] = {"pair": p, "windows": [], "power": 0}
            all_pairs_info[key]["windows"].append(f"{ty}Y")
            all_pairs_info[key]["power"] = max(all_pairs_info[key]["power"], pw)

        # Score 365 days back so cycle_history.json has enough history for the chart.
        # The current signal still uses only ens_window.iloc[-1] so no lookahead risk.
        hist_start   = current_rd - pd.DateOffset(days=365)
        window_dates = close.index[close.index >= hist_start]
        combo = pd.Series(np.nan, index=window_dates)
        for t in window_dates:
            combo.loc[t] = _mod.score_at_date(disc, fwd, top_pairs, t)
        combo_parts[ty] = (combo, top_pairs, active_sigs)

    combo_2y, pairs_2y, _ = combo_parts[2]
    combo_3y, pairs_3y, _ = combo_parts[3]
    ens_window = (combo_2y.fillna(0) + combo_3y.fillna(0)) / 2

    dominant_pairs = sorted(all_pairs_info.values(), key=lambda x: -x["power"])[:10]

    # ── 4. Exposure + cooldown ────────────────────────────────────────────────
    print("\n[4/6] Computing exposure & cooldown...")
    # Historical CSVs now live in data/ so they persist across GitHub Action runs
    hist_combo_path = os.path.join(DATA_DIR, "combo_v2_vol_regime.csv")
    hist_exp_path   = os.path.join(DATA_DIR, "exposure_v2_vol_regime.csv")

    hist_combo = pd.Series(dtype=float)
    hist_exp   = pd.Series(dtype=float)
    if os.path.exists(hist_combo_path):
        hist_combo = pd.read_csv(hist_combo_path, index_col=0, parse_dates=True).iloc[:, 0]
        hist_combo.index = pd.to_datetime(hist_combo.index).tz_localize(None)
    if os.path.exists(hist_exp_path):
        hist_exp = pd.read_csv(hist_exp_path, index_col=0, parse_dates=True).iloc[:, 0]
        hist_exp.index = pd.to_datetime(hist_exp.index).tz_localize(None)

    gate_lookback_start = close.index[-1] - pd.DateOffset(years=GATE_THRESHOLD_LOOKBACK)
    if len(hist_combo) > 0:
        combo_trail = hist_combo[hist_combo.index >= gate_lookback_start]
        close_trail = close[close.index >= gate_lookback_start]
        gate = find_gate_holm(combo_trail, close_trail)
    else:
        gate = 0.0

    hist_nz = hist_combo[hist_combo != 0].abs().dropna() if len(hist_combo) > 0 else pd.Series(dtype=float)
    if len(hist_nz) >= 30:
        thresholds = [np.percentile(hist_nz, 100 * i / (N_THRESHOLDS + 1)) for i in range(1, N_THRESHOLDS + 1)]
    else:
        thresholds = [(i + 1) / (N_THRESHOLDS + 1) for i in range(N_THRESHOLDS)]

    prev_exp_val  = float(hist_exp.iloc[-1]) if len(hist_exp) > 0 else 0.5
    current_combo = float(ens_window.iloc[-1]) if len(ens_window) > 0 else 0.0

    # Always compute full_exp from the complete ens_window series so that
    # cycle_history.json is backfilled with all available history on first run.
    seed = hist_exp.copy() if len(hist_exp) > 0 else pd.Series(dtype=float)
    prev_val = float(seed.iloc[-1]) if len(seed) > 0 else 0.5
    exp_vals = {}
    for t, v in ens_window.items():
        if np.isnan(v) or abs(v) < gate:
            val = prev_val
        else:
            n_ab = sum(abs(v) >= th for th in thresholds)
            val  = (min(0.5 + n_ab * DELTA, 1.0) if v < 0
                    else max(0.5 - n_ab * DELTA, 0.0))
        exp_vals[t] = val
        prev_val = val
    full_exp = pd.Series(exp_vals) if exp_vals else pd.Series(0.5, index=[close.index[-1]])

    full_exp, cooldown_events = apply_cooldown(full_exp)
    current_exp = float(full_exp.iloc[-1])

    if prev_state:
        prev_exposure = prev_state.get("exposure", current_exp)
        daily_delta   = current_exp - prev_exposure
    else:
        daily_delta = 0.0

    direction = "BULLISH" if current_combo < -gate else ("BEARISH" if current_combo > gate else "NEUTRAL")

    print(f"  Exposure: {current_exp:.0%} ({direction})")
    print(f"  Composite: {current_combo:+.4f} | Gate: {gate:.4f}")

    # ── 5. Generate chart ─────────────────────────────────────────────────────
    print("\n[5/6] Generating chart...")

    BG, GRID, WHITE, DIM = '#0e1117', '#1e2330', '#e8eaf0', '#8892a4'
    BULL_C, BEAR_C, NEUT_C = '#00b894', '#e17055', '#636e72'
    EXP_C  = '#6c5ce7'
    WARN_C = '#fdcb6e'

    now_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M HKT")
    chart_title = f'CycleSignal Morning Report V2.2.2 — {now_str}'
    if _CACHE_WARNINGS:
        chart_title  = f'{chart_title}\n{" | ".join(_CACHE_WARNINGS)}'

    fig = plt.figure(figsize=(18, 16), facecolor=BG)
    fig.suptitle(chart_title, color=WARN_C if _CACHE_WARNINGS else WHITE,
                 fontsize=14, fontweight='bold', y=0.99)

    gs = gridspec.GridSpec(4, 3, figure=fig, hspace=0.55, wspace=0.35,
                           left=0.06, right=0.97, top=0.95, bottom=0.04)

    ax_price = fig.add_subplot(gs[0, :2])
    close_plot = close.loc[EVAL_START:]
    ax_e = ax_price.twinx()
    ax_price.plot(close_plot.index, close_plot.values, color='#f7931a', linewidth=1.0, alpha=0.9)
    ax_price.set_yscale('log')
    exp_plot = full_exp.reindex(close_plot.index).ffill()
    if exp_plot is not None and len(exp_plot) > 0:
        ax_e.fill_between(exp_plot.index, exp_plot.values, 0.5, alpha=0.22,
                           color=BULL_C, where=(exp_plot.values >= 0.5))
        ax_e.fill_between(exp_plot.index, exp_plot.values, 0.5, alpha=0.22,
                           color=BEAR_C, where=(exp_plot.values < 0.5))
        ax_e.plot(exp_plot.index, exp_plot.values, color=EXP_C, linewidth=1.2, alpha=0.85)
    ax_e.set_ylim(0, 1); ax_e.tick_params(colors=DIM, labelsize=8)
    ax_e.set_ylabel('Exposure', color=EXP_C, fontsize=8)
    ax_price.set_facecolor(BG); ax_price.tick_params(colors=DIM, labelsize=8)
    for sp in ax_price.spines.values(): sp.set_color(GRID)
    ax_price.grid(True, color=GRID, linewidth=0.4, linestyle='--', alpha=0.7)
    ax_price.set_title('BTC Price (log) + Strategy Exposure', color=WHITE, fontsize=10, pad=5)
    ax_price.set_ylabel('BTC (USD)', color='#f7931a', fontsize=8)

    ax_stat = fig.add_subplot(gs[0, 2])
    ax_stat.set_facecolor(BG)
    for sp in ax_stat.spines.values(): sp.set_color(GRID)
    ax_stat.set_xticks([]); ax_stat.set_yticks([])
    ax_stat.set_title('Current Position', color=WHITE, fontsize=10, pad=5)

    exp_pct   = current_exp * 100
    exp_col   = BULL_C if current_exp >= 0.6 else (BEAR_C if current_exp <= 0.4 else WARN_C)
    dir_col   = BULL_C if direction == "BULLISH" else (BEAR_C if direction == "BEARISH" else WARN_C)
    delta_col = BULL_C if daily_delta > 0.001 else (BEAR_C if daily_delta < -0.001 else DIM)
    delta_arrow = "+" if daily_delta > 0.001 else ("-" if daily_delta < -0.001 else "=")

    sub_ax = ax_stat.inset_axes([0.15, 0.55, 0.70, 0.42])
    sub_ax.set_facecolor(BG)
    sub_ax.pie([current_exp, 1 - current_exp], colors=[exp_col, GRID],
               startangle=90, counterclock=False,
               wedgeprops=dict(width=0.45, edgecolor=BG, linewidth=2))
    sub_ax.text(0, 0, f"{exp_pct:.0f}%\nBTC", ha='center', va='center',
                color=exp_col, fontsize=11, fontweight='bold')

    lines = [
        (0.44, f"${btc_now:,.0f}  ({btc_chg_pct:+.1f}%)", WHITE, 13),
        (0.33, f"{direction}", dir_col, 16),
        (0.24, f"Combo: {current_combo:+.3f}  |  Gate: {gate:.3f}", DIM, 7.5),
        (0.15, f"Daily Delta: {delta_arrow} {abs(daily_delta):.0%}", delta_col, 11),
        (0.07, f"Cooldowns active: {len([c for c in cooldown_events if c.get('remaining_days', 0) > 0])}", DIM, 8),
    ]
    for y_pos, txt, col, sz in lines:
        ax_stat.text(0.5, y_pos, txt, ha='center', va='bottom',
                     transform=ax_stat.transAxes, color=col, fontsize=sz, fontweight='bold')

    ax_bar = fig.add_subplot(gs[1, 0])
    ax_bar.set_facecolor(BG)
    for sp in ax_bar.spines.values(): sp.set_color(GRID)
    counts = [len(bull_sigs), len(neut_sigs), len(bear_sigs)]
    labels = ['Bull\n(-1)', 'Neutral\n(0)', 'Bear\n(+1)']
    bars = ax_bar.bar(labels, counts, color=[BULL_C, NEUT_C, BEAR_C], width=0.5, alpha=0.85)
    for bar, cnt in zip(bars, counts):
        ax_bar.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                    str(cnt), ha='center', va='bottom', color=WHITE, fontsize=11, fontweight='bold')
    ax_bar.set_title(f'Signals ({len(sigs_all)} total)', color=WHITE, fontsize=10, pad=5)
    ax_bar.tick_params(colors=DIM, labelsize=9)
    ax_bar.grid(axis='y', color=GRID, linewidth=0.4, linestyle='--', alpha=0.7)

    ax_pairs = fig.add_subplot(gs[1, 1:])
    ax_pairs.set_facecolor(BG)
    for sp in ax_pairs.spines.values(): sp.set_color(GRID)
    ax_pairs.set_title('Dominant Signal Pairs (by power score)', color=WHITE, fontsize=10, pad=5)
    if dominant_pairs:
        dp_labels, dp_vals, dp_colors = [], [], []
        for pi in dominant_pairs[:12]:
            p = pi["pair"]
            s1_dir = int(sig_today.get(p[0], 0)); s2_dir = int(sig_today.get(p[1], 0))
            dir_sym = {-1: '^', 0: 'o', 1: 'v'}
            dp_labels.append(f"{dir_sym.get(s1_dir,'?')}{p[0][:14]} x {dir_sym.get(s2_dir,'?')}{p[1][:14]}")
            dp_vals.append(pi["power"])
            net = s1_dir + s2_dir
            dp_colors.append(BULL_C if net < 0 else (BEAR_C if net > 0 else NEUT_C))
        y_pos_arr = np.arange(len(dp_labels))
        ax_pairs.barh(y_pos_arr, dp_vals, color=dp_colors, alpha=0.8, height=0.65)
        ax_pairs.set_yticks(y_pos_arr)
        ax_pairs.set_yticklabels(dp_labels, fontsize=7, color=WHITE)
        ax_pairs.invert_yaxis()
        ax_pairs.set_xlabel('Pair power', color=DIM, fontsize=8)
    ax_pairs.tick_params(axis='x', colors=DIM, labelsize=8)
    ax_pairs.grid(axis='x', color=GRID, linewidth=0.4, linestyle='--', alpha=0.7)

    ax_exp90 = fig.add_subplot(gs[2, :2])
    ax_exp90.set_facecolor(BG)
    for sp in ax_exp90.spines.values(): sp.set_color(GRID)
    exp90 = full_exp.iloc[-90:]
    btc90 = close.reindex(exp90.index).ffill()
    ax_b2 = ax_exp90.twinx()
    ax_b2.plot(btc90.index, btc90.values, color='#f7931a', linewidth=1.2, alpha=0.5)
    ax_b2.set_ylabel('BTC', color='#f7931a', fontsize=8)
    ax_b2.tick_params(colors='#f7931a', labelsize=8)
    ax_exp90.step(exp90.index, exp90.values, color=EXP_C, linewidth=2.0, where='post')
    ax_exp90.fill_between(exp90.index, exp90.values, 0.5, step='post', alpha=0.25,
                          color=BULL_C, where=(exp90.values >= 0.5))
    ax_exp90.fill_between(exp90.index, exp90.values, 0.5, step='post', alpha=0.25,
                          color=BEAR_C, where=(exp90.values < 0.5))
    ax_exp90.axhline(0.5, color=DIM, linewidth=0.6, linestyle=':')
    ax_exp90.set_ylim(0, 1)
    ax_exp90.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax_exp90.set_yticklabels(['0%', '25%', '50%', '75%', '100%'], color=DIM, fontsize=8)
    ax_exp90.tick_params(axis='x', colors=DIM, labelsize=8)
    ax_exp90.set_title('Exposure — Last 90 Days', color=WHITE, fontsize=10, pad=5)
    ax_exp90.set_ylabel('BTC Exposure', color=EXP_C, fontsize=8)
    ax_exp90.grid(True, color=GRID, linewidth=0.4, linestyle='--', alpha=0.7)

    ax_detail = fig.add_subplot(gs[2, 2])
    ax_detail.set_facecolor(BG)
    for sp in ax_detail.spines.values(): sp.set_color(GRID)
    ax_detail.set_xticks([]); ax_detail.set_yticks([])
    ax_detail.set_title('Signal Flips & Cooldowns', color=WHITE, fontsize=10, pad=5)
    y = 0.95
    ax_detail.text(0.03, y, f"SIGNAL FLIPS TODAY ({len(flips)})", transform=ax_detail.transAxes,
                   color=WARN_C, fontsize=9, fontweight='bold', va='top')
    y -= 0.06
    for fl in flips[:10]:
        fc = BULL_C if fl["to"] == "BULL" else (BEAR_C if fl["to"] == "BEAR" else DIM)
        ax_detail.text(0.05, y, f"  {fl['signal'][:22]}: {fl['from']}->{fl['to']}",
                       transform=ax_detail.transAxes, color=fc, fontsize=7, va='top')
        y -= 0.05
    if len(flips) > 10:
        ax_detail.text(0.05, y, f"  +{len(flips) - 10} more...", transform=ax_detail.transAxes,
                       color=DIM, fontsize=7, va='top')
        y -= 0.05
    y -= 0.04
    recent_cd = [c for c in cooldown_events if c.get("remaining_days", 0) > 0]
    ax_detail.text(0.03, y, f"COOLDOWNS ({len(recent_cd)} active)", transform=ax_detail.transAxes,
                   color=WARN_C, fontsize=9, fontweight='bold', va='top')
    y -= 0.06
    if recent_cd:
        for cd in recent_cd[-5:]:
            ax_detail.text(0.05, y, f"  {cd['blocked_move']} ({cd['remaining_days']}d left)",
                           transform=ax_detail.transAxes, color=WARN_C, fontsize=7, va='top')
            y -= 0.05
    else:
        ax_detail.text(0.05, y, "No active cooldowns", transform=ax_detail.transAxes,
                       color=DIM, fontsize=7.5, va='top')

    ax_sigs = fig.add_subplot(gs[3, :2])
    ax_sigs.set_facecolor(BG)
    for sp in ax_sigs.spines.values(): sp.set_color(GRID)
    ax_sigs.set_xticks([]); ax_sigs.set_yticks([])
    ax_sigs.set_title('All Active Signals', color=WHITE, fontsize=10, pad=5)
    def shorten(s, n=24): return s[:n] + '...' if len(s) > n else s
    y = 0.95
    ax_sigs.text(0.02, y, f"BULLISH ({len(bull_sigs)})", transform=ax_sigs.transAxes,
                 color=BULL_C, fontsize=9, fontweight='bold', va='top')
    col_y = y - 0.06
    for i, s in enumerate(bull_sigs):
        col = 0.03 if i < 15 else 0.28
        ax_sigs.text(col, col_y - (i % 15) * 0.055, f"  {shorten(s)}",
                     transform=ax_sigs.transAxes, color=BULL_C, fontsize=6.5, va='top', alpha=0.9)
    ax_sigs.text(0.55, y, f"BEARISH ({len(bear_sigs)})", transform=ax_sigs.transAxes,
                 color=BEAR_C, fontsize=9, fontweight='bold', va='top')
    for i, s in enumerate(bear_sigs):
        ax_sigs.text(0.56, col_y - i * 0.055, f"  {shorten(s)}",
                     transform=ax_sigs.transAxes, color=BEAR_C, fontsize=6.5, va='top', alpha=0.9)
    ax_sigs.text(0.80, y, f"NEUTRAL ({len(neut_sigs)})", transform=ax_sigs.transAxes,
                 color=NEUT_C, fontsize=9, fontweight='bold', va='top')

    risk_factors = []
    if current_exp >= 0.8:        risk_factors.append("High exposure (>=80%)")
    if len(bear_sigs) >= 15:      risk_factors.append(f"Many bearish signals ({len(bear_sigs)})")
    if abs(daily_delta) >= 0.2:   risk_factors.append(f"Large daily shift ({daily_delta:+.0%})")
    if len(recent_cd) > 0:        risk_factors.append("Cooldowns blocking moves")
    if len(flips) >= 5:           risk_factors.append(f"High signal churn ({len(flips)} flips)")
    if _CACHE_WARNINGS:           risk_factors.append(f"Stale data: {len(_CACHE_WARNINGS)} source(s) from cache")
    risk_level = "LOW" if len(risk_factors) == 0 else ("MEDIUM" if len(risk_factors) <= 2 else "HIGH")
    risk_col   = BULL_C if risk_level == "LOW" else (WARN_C if risk_level == "MEDIUM" else BEAR_C)

    ax_risk = fig.add_subplot(gs[3, 2])
    ax_risk.set_facecolor(BG)
    for sp in ax_risk.spines.values(): sp.set_color(GRID)
    ax_risk.set_xticks([]); ax_risk.set_yticks([])
    ax_risk.set_title('Risk Summary', color=WHITE, fontsize=10, pad=5)
    y = 0.90
    ax_risk.text(0.5, y, f"Risk: {risk_level}", ha='center', transform=ax_risk.transAxes,
                 color=risk_col, fontsize=16, fontweight='bold', va='top')
    y -= 0.12
    if risk_factors:
        for rf in risk_factors:
            ax_risk.text(0.05, y, f"  {rf}", transform=ax_risk.transAxes, color=WARN_C, fontsize=7.5, va='top')
            y -= 0.07
    else:
        ax_risk.text(0.05, y, "No risk flags triggered", transform=ax_risk.transAxes, color=BULL_C, fontsize=8, va='top')

    plt.savefig(OUT_PNG, dpi=150, bbox_inches='tight', facecolor=BG, edgecolor='none')
    print(f"\n[6/6] Chart saved: {OUT_PNG}")

    # ── Save state + web app JSON data ────────────────────────────────────────
    vol_z_now  = float(vol_zscore_aligned.iloc[-1])
    vol_regime = _get_vol_regime(vol_z_now)

    state = {
        "date":          today_str,
        "btc_price":     btc_now,
        "exposure":      current_exp,
        "direction":     direction,
        "composite":     current_combo,
        "gate":          gate,
        "vol_z":         vol_z_now,
        "vol_regime":    vol_regime,
        "bull_count":    len(bull_sigs),
        "neut_count":    len(neut_sigs),
        "bear_count":    len(bear_sigs),
        "bull_signals":  bull_sigs,
        "bear_signals":  bear_sigs,
        "neut_signals":  neut_sigs,
        "flips":         flips,
        "dominant_pairs": [{"s1": p["pair"][0], "s2": p["pair"][1],
                             "power": p["power"], "windows": p["windows"]}
                            for p in dominant_pairs[:10]],
        "cooldown_events": cooldown_events[-5:] if cooldown_events else [],
        "risk_level":    risk_level,
        "risk_factors":  risk_factors,
        "cache_warnings": _CACHE_WARNINGS,
    }
    save_state(state)

    # cycle_state.json = same as state (save_state already writes here)
    print(f"  State      → {STATE_FILE}")

    # cycle_history.json – rebuilt from full computed series each run (self-healing backfill)
    web_hist_path = os.path.join(DATA_DIR, "cycle_history.json")
    web_history = []
    for t in full_exp.index:
        t_str = str(t.date())
        c_val = ens_window.loc[t] if t in ens_window.index else float("nan")
        web_history.append({
            "date":      t_str,
            "combo":     None if (np.isnan(c_val)) else round(float(c_val), 6),
            "exposure":  round(float(full_exp.loc[t]), 4),
            "btc_price": round(float(close.loc[t]), 2) if t in close.index else None,
        })
    with open(web_hist_path, "w") as f:
        json.dump(web_history, f)
    print(f"  History    → {web_hist_path} ({len(web_history)} entries)")

    # ── Append today's data to historical CSVs (for gate computation) ─────────
    today_dt = pd.Timestamp(today_str)
    for fpath, new_row in [
        (hist_combo_path, {"Date": [today_dt], "combo": [current_combo]}),
        (hist_exp_path,   {"Date": [today_dt], "0":    [current_exp]}),
    ]:
        if os.path.exists(fpath):
            df = pd.read_csv(fpath)
            df["Date"] = pd.to_datetime(df["Date"])
            if today_dt not in df["Date"].values:
                df = pd.concat([df, pd.DataFrame(new_row)], ignore_index=True)
                df.to_csv(fpath, index=False)
                print(f"  Appended {today_str} to {os.path.basename(fpath)}")
        else:
            pd.DataFrame(new_row).to_csv(fpath, index=False)
            print(f"  Created {os.path.basename(fpath)}")

    # ── Console summary ───────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  CYCLESIGNAL MORNING REPORT V2.2.2 — {today_str}")
    print(f"{'='*65}")
    print(f"  BTC:        ${btc_now:,.0f} ({btc_chg_pct:+.1f}%)")
    print(f"  Exposure:   {current_exp:.0%} ({direction})")
    print(f"  Daily Delta: {daily_delta:+.0%}")
    print(f"  Composite:  {current_combo:+.4f} (gate: {gate:.4f})")
    print(f"  Vol Regime: {vol_regime} (z={vol_z_now:.2f})")
    print(f"  Signals:    Bull={len(bull_sigs)} Neutral={len(neut_sigs)} Bear={len(bear_sigs)}")
    print(f"  Flips:      {len(flips)}")
    print(f"  Risk:       {risk_level}")
    if dominant_pairs:
        print(f"  Top pair:   {dominant_pairs[0]['pair'][0]} x {dominant_pairs[0]['pair'][1]} (power={dominant_pairs[0]['power']:.4f})")
    print(f"\n  DATA PROVENANCE")
    print(f"  {'-'*55}")
    for src_name, origin, date_info in _DATA_SOURCES:
        print(f"  {src_name:<20} {origin:<22} {date_info}")
    if _CACHE_WARNINGS:
        print(f"\n  *** WARNINGS ({len(_CACHE_WARNINGS)}) ***")
        for w in _CACHE_WARNINGS:
            print(f"  {w}")
    print(f"{'='*65}\n")

    return state


if __name__ == "__main__":
    main()
