#!/usr/bin/env python3.12
"""
CycleSignal Production D10 Strategy
===================================

Main production recommendation:

    Regime 10/25 + 0.95 correlation threshold
    + original Hit Rate / Median Return scoring.

This file is deliberately self-contained except for the shared
`btc_combined_backtest_lib.py` library. It does not import the research runner.

Production rules:
    1. K policy:
       LOW volatility     -> 10 pairs
       NORMAL volatility  -> 10 pairs
       HIGH volatility    -> 25 pairs
       EXTREME volatility -> 25 pairs

    2. Pair correlation filter:
       Candidate pair is skipped if the absolute Spearman correlation between
       its pair-product state series and any selected pair is greater than 0.95.

    3. Daily scoring:
       Original/M0 Hit Rate + Median Return:
           hr >= 0.75 and median >  0.02 -> -1.0  (bullish)
           hr >= 0.60 and median >  0.00 -> -0.5  (mild bullish)
           hr <= 0.25 and median < -0.02 -> +1.0  (bearish)
           hr <= 0.40 and median <  0.00 -> +0.5  (mild bearish)
           otherwise                         0.0

Run:
    python cs_production_regime1025_rho095_hr_median.py

Outputs:
    cs_production_regime1025_rho095_hr_median.json
    cs_production_regime1025_rho095_hr_median.png
    cs_production_regime1025_rho095_hr_median_pair_corr.csv
"""
import sys, os, json, math, warnings, importlib.util, time, shutil, subprocess, random, copy, types, argparse
import numpy as np, pandas as pd
import requests
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from datetime import datetime, timezone, timedelta
from scipy.stats import binomtest, spearmanr
from itertools import combinations

warnings.filterwarnings('ignore')

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
QUANT_DIR  = SCRIPT_DIR  # cycle-signal root
V3_DIR     = os.path.join(QUANT_DIR, "v3_experiment_v2")
OUT_DIR    = SCRIPT_DIR
OUT_PNG    = os.path.join(OUT_DIR, "cs_production_regime1025_rho095_hr_median.png")
OUT_JSON   = os.path.join(OUT_DIR, "cs_production_regime1025_rho095_hr_median.json")
OUT_PAIR_CORR = os.path.join(OUT_DIR, "cs_production_regime1025_rho095_hr_median_pair_corr.csv")

# ── Load backtest lib ────────────────────────────────────────────────────────
LIB_PATH = os.path.join(QUANT_DIR, "btc_combined_backtest_lib.py")
spec = importlib.util.spec_from_file_location("bbt", LIB_PATH)
_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_mod)
_mod.HORIZON_WEIGHTS.clear()
_mod.HORIZON_WEIGHTS.update({3: 1/6, 7: 1/6, 14: 1/6, 30: 1/6, 90: 1/6, 180: 1/6})

# Patch MABreak._find_events (same as all production files)
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

# ── Config (identical to production) ────────────────────────────────────────
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
HELD_OUT_SPLIT       = 0.70
HORIZON_LIST         = [3, 7, 14, 30, 90, 180]
HORIZON_WEIGHTS      = {3: 1/6, 7: 1/6, 14: 1/6, 30: 1/6, 90: 1/6, 180: 1/6}
TX_COST_BPS          = 10
GATE_THRESHOLD_LOOKBACK = 3

CQ_KEY               = os.environ.get("CRYPTOQUANT_API_KEY") or os.environ.get("CQ_KEY")
FRED_KEY             = os.environ.get("FRED_API_KEY") or os.environ.get("FRED_KEY")
RETRY_MAX            = 300
RETRY_WAIT           = 3
RETRY_WAIT_JITTER    = 2
YF_BUNDLE_TICKERS    = ["BTC-USD", "^GSPC", "^VIX", "DX-Y.NYB", "GC=F", "HYG"]
YF_HELPER_FILE       = os.path.join(V3_DIR, "cs_morning_report_v2_2_2_yf_helper.py")

# Cache (reuse v3_experiment_v2 cache)
CACHE_DIR    = os.path.join(V3_DIR, "cache")
CACHE_BTC    = os.path.join(CACHE_DIR, "cache_btc.json")
CACHE_MACRO  = os.path.join(CACHE_DIR, "cache_macro.json")
CACHE_CQUANT = os.path.join(CACHE_DIR, "cache_cquant.json")
CACHE_FRED   = os.path.join(CACHE_DIR, "cache_fred.json")

_CACHE_WARNINGS = []
_DATA_SOURCES   = []
_YF_BUNDLE_DATA  = None
_YF_BUNDLE_ERROR = None
NO_CACHE_READ = os.environ.get("CS_NO_CACHE_READ", "").lower() in {"1", "true", "yes"}

# Correlation filter thresholds
CORR_THRESHOLD = 0.5
RHO_VALUES = [0.95]

CONFIG_NAME = "Production_Regime10_25_rho0.95_HR_Median"
REGIME_K_MAP = {
    "LOW": 10,
    "NORMAL": 10,
    "HIGH": 25,
    "EXTREME": 25,
}
RHO_MAX = 0.95

# The old grid-runner variables are kept only because helper functions below
# reference them; the production main at the bottom runs one config only.
K_VALUES = []
REGIME_K_MAPS = {}


def _fmt_k_value(k_val):
    return str(k_val)


def _fmt_rho_value(rho_max):
    if rho_max is None:
        return "None"
    return f"{float(rho_max):.4g}"


def _config_name(k_val, rho_max):
    return f"K={_fmt_k_value(k_val)}_rho{_fmt_rho_value(rho_max)}"


def _config_display_name(k_val, rho_max):
    return f"K={_fmt_k_value(k_val)} | rho={_fmt_rho_value(rho_max)}"


def _regime_config_name(label, rho_max):
    return f"{label}_rho{_fmt_rho_value(rho_max)}"


def _regime_config_display_name(label, rho_max):
    return f"{label} | rho={_fmt_rho_value(rho_max)}"


def _selected_pair_corr_stats(selected_pairs, disc_tr):
    if disc_tr is None or len(selected_pairs) < 2:
        return {
            "avg_abs_corr": 0.0,
            "max_abs_corr": 0.0,
            "corr_pairs_evaluated": 0,
        }
    pair_signals = {}
    for s1, s2 in selected_pairs:
        if s1 in disc_tr.columns and s2 in disc_tr.columns:
            pair_signals[(s1, s2)] = (disc_tr[s1] * disc_tr[s2]).values
    corr_vals = []
    sel_list = list(pair_signals.items())
    for i, (_, sig_i) in enumerate(sel_list):
        for _, sig_j in sel_list[i + 1:]:
            mask = (sig_i != 0) | (sig_j != 0)
            if mask.sum() < 30:
                continue
            rho, _ = spearmanr(sig_i[mask], sig_j[mask])
            if np.isnan(rho):
                continue
            corr_vals.append(abs(float(rho)))
    if not corr_vals:
        return {
            "avg_abs_corr": 0.0,
            "max_abs_corr": 0.0,
            "corr_pairs_evaluated": 0,
        }
    return {
        "avg_abs_corr": round(float(np.mean(corr_vals)), 4),
        "max_abs_corr": round(float(np.max(corr_vals)), 4),
        "corr_pairs_evaluated": int(len(corr_vals)),
    }

# Vol regime
_VOL_REGIME_ORDER  = ["LOW", "NORMAL", "HIGH", "EXTREME"]
_VOL_REGIME_WEIGHT = {0: 1.0, 1: 0.5, 2: 0.1}

def _get_vol_regime(z):
    if np.isnan(z): return "NORMAL"
    if z < -0.5: return "LOW"
    elif z < 0.5: return "NORMAL"
    elif z < 1.5: return "HIGH"
    else: return "EXTREME"

def _vol_regime_weights(vol_z_series, current_regime):
    try: cur_idx = _VOL_REGIME_ORDER.index(current_regime)
    except ValueError: cur_idx = 1
    def _w(z):
        reg = _get_vol_regime(z)
        try: dist = abs(_VOL_REGIME_ORDER.index(reg) - cur_idx)
        except ValueError: dist = 2
        return _VOL_REGIME_WEIGHT.get(min(dist, 2), 0.1)
    return vol_z_series.apply(_w)

def compute_vol_zscore(close):
    log_ret   = np.log(close / close.shift(1))
    vol_30d   = log_ret.rolling(30).std() * np.sqrt(365)
    roll_mean = vol_30d.rolling(730).mean()
    roll_std  = vol_30d.rolling(730).std()
    return ((vol_30d - roll_mean) / roll_std).rename("vol_zscore")


# ═══════════════════════════════════════════════════════════════════════════
# Data loading (from production pipeline)
# ═══════════════════════════════════════════════════════════════════════════

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
        print(f"  [cache] Saved {label}")

def _load_series_cache(cache_path):
    if NO_CACHE_READ:
        return None, None
    if not os.path.exists(cache_path): return None, None
    with open(cache_path, "r") as f:
        raw = f.read().strip()
    if not raw: return None, None
    cache_obj = json.loads(raw)
    cache_date = cache_obj.get("date", "unknown")
    data_dict  = cache_obj.get("data", {})
    if not data_dict: return cache_date, None
    first_val = next(iter(data_dict.values()))
    if isinstance(first_val, dict):
        df = pd.DataFrame(data_dict)
        df.index = pd.to_datetime(df.index)
        return cache_date, df
    else:
        s = pd.Series(data_dict)
        s.index = pd.to_datetime(s.index)
        return cache_date, s.sort_index()

def _load_df_cache(cache_path):
    cache_date, obj = _load_series_cache(cache_path)
    if obj is None: return cache_date, None
    if isinstance(obj, pd.DataFrame): return cache_date, obj
    return cache_date, obj.to_frame()

def _next_yf_retry_wait():
    return random.uniform(max(0.0, RETRY_WAIT - RETRY_WAIT_JITTER), RETRY_WAIT + RETRY_WAIT_JITTER)

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
        return None, f"invalid JSON ({e})"
    if not payload.get("ok"):
        return None, payload.get("error") or "helper not ok"
    close_map = payload.get("close_map", {})
    out = {}
    for ticker in YF_BUNDLE_TICKERS:
        s_map = close_map.get(ticker, {})
        if not s_map: continue
        s = pd.Series(s_map, dtype=float)
        s.index = pd.to_datetime(s.index)
        out[ticker] = s.sort_index()
    return out, None

def _get_yf_bundle(start=TRAIN_START):
    global _YF_BUNDLE_DATA, _YF_BUNDLE_ERROR
    if _YF_BUNDLE_DATA is not None: return _YF_BUNDLE_DATA
    if _YF_BUNDLE_ERROR is not None: return None
    for attempt in range(1, RETRY_MAX + 1):
        bundle, err = _run_yf_bundle_helper(start)
        if bundle is not None:
            missing = [t for t in YF_BUNDLE_TICKERS if t not in bundle or len(bundle[t]) < 10]
            if not missing:
                _YF_BUNDLE_DATA = bundle
                return _YF_BUNDLE_DATA
            err = f"missing: {missing}"
        wait_s = _next_yf_retry_wait()
        print(f"  [Yahoo bundle] attempt {attempt}/{RETRY_MAX} failed: {err} -- retry {wait_s:.1f}s...")
        time.sleep(wait_s)
    _YF_BUNDLE_ERROR = err or "bundle unavailable"
    return None

def _fetch_binance_daily_close(start_date, end_date):
    try:
        start_ms = int(pd.Timestamp(start_date).tz_localize("UTC").timestamp() * 1000)
        end_ms   = int((pd.Timestamp(end_date) + pd.Timedelta(days=1)).tz_localize("UTC").timestamp() * 1000)
        url = f"https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1d&startTime={start_ms}&endTime={end_ms}&limit=1000"
        r = requests.get(url, timeout=10); r.raise_for_status()
        data = {pd.Timestamp(k[0], unit="ms").normalize(): float(k[4]) for k in r.json()}
        return pd.Series(data).sort_index()
    except Exception:
        return pd.Series(dtype=float)

def _patch_btc_gaps(close):
    if close is None or len(close) < 2: return close
    full_idx = pd.date_range(close.index.min().normalize(), close.index.max().normalize(), freq="D")
    have = pd.DatetimeIndex([d.normalize() for d in close.index])
    missing = full_idx.difference(have)
    if len(missing) == 0: return close
    patch_start = missing.min() - pd.Timedelta(days=2)
    patch_end = missing.max() + pd.Timedelta(days=1)
    binance_s = _fetch_binance_daily_close(patch_start, patch_end)
    if binance_s.empty: return close
    patch = binance_s.reindex(missing).dropna()
    if patch.empty: return close
    out = pd.concat([close, patch]).sort_index()
    out = out[~out.index.duplicated(keep="first")]
    print(f"  [gap-fill] Patched {len(patch)} missing BTC day(s) from Binance")
    return out

def _yf_download_retry(ticker, start=TRAIN_START):
    bundle = _get_yf_bundle(start)
    if bundle is not None and ticker in bundle and len(bundle[ticker]) >= 10:
        s = bundle[ticker].copy()
        s = _patch_btc_gaps(s)
        _save_series_cache(CACHE_BTC, s, label="BTC-USD")
        return s
    cache_date, cached_s = _load_series_cache(CACHE_BTC)
    if cached_s is None:
        print("FATAL: BTC cache missing."); sys.exit(1)
    today_dt = pd.Timestamp(datetime.now(timezone.utc).date())
    if today_dt not in cached_s.index:
        cached_s.loc[today_dt] = cached_s.iloc[-1]
        cached_s = cached_s.sort_index()
    return cached_s.ffill()

def _fetch_macro_all(ref_index):
    bundle = _get_yf_bundle(TRAIN_START)
    if bundle is None:
        print("FATAL: Yahoo bundle unavailable."); sys.exit(1)
    sp500 = bundle["^GSPC"].reindex(ref_index, method="ffill")
    vix   = bundle["^VIX"].reindex(ref_index, method="ffill")
    dxy   = bundle["DX-Y.NYB"].reindex(ref_index, method="ffill")
    gold  = bundle["GC=F"].reindex(ref_index, method="ffill")
    hy    = bundle["HYG"].reindex(ref_index, method="ffill")
    return sp500, vix, dxy, gold, hy

def _fetch_cquant_retry(cq_key, start):
    last_error = None
    if not cq_key:
        print("  [CryptoQuant] API key missing; trying cache fallback")
    for attempt in range(1, RETRY_MAX + 1) if cq_key else range(0):
        _mod._session = requests.Session()
        result = _mod.fetch_cquant_signals(cq_key, start=start)
        if result is not None and len(result) > 0:
            cq_df = pd.DataFrame(result)
            cq_df.index = pd.to_datetime(cq_df.index)
            _save_series_cache(CACHE_CQUANT, cq_df, label="CryptoQuant")
            return result
        last_error = "empty"
        print(f"  [CryptoQuant] attempt {attempt}/{RETRY_MAX} failed -- retry {RETRY_WAIT}s...")
        time.sleep(RETRY_WAIT)
    cache_date, cached_obj = _load_df_cache(CACHE_CQUANT)
    if cached_obj is None:
        print("FATAL: CryptoQuant cache missing."); sys.exit(1)
    today_dt = pd.Timestamp(datetime.now(timezone.utc).date())
    if isinstance(cached_obj, pd.DataFrame):
        cached_obj.index = pd.to_datetime(cached_obj.index)
        if today_dt not in cached_obj.index:
            cached_obj = pd.concat([cached_obj, cached_obj.iloc[[-1]].set_index(pd.DatetimeIndex([today_dt]))])
        cached_obj = cached_obj.ffill()
        return {col: cached_obj[col] for col in cached_obj.columns}
    return {}

def _fetch_fred_retry(fred_api_key, sid, lag_days=0, close_index=None):
    if not fred_api_key:
        print(f"  [FRED {sid}] API key missing; trying cache fallback")
    else:
        from fredapi import Fred
    for attempt in range(1, RETRY_MAX + 1) if fred_api_key else range(0):
        try:
            s = Fred(api_key=fred_api_key).get_series(sid, observation_start=TRAIN_START)
        except Exception:
            s = None
        if s is not None:
            s = s.dropna()
            if len(s) > 0:
                if lag_days: s.index = s.index + pd.Timedelta(days=lag_days)
                if close_index is not None: return s.reindex(close_index, method="ffill")
                return s
        print(f"  [FRED {sid}] attempt {attempt}/{RETRY_MAX} -- retry {RETRY_WAIT}s...")
        time.sleep(RETRY_WAIT)
    if not NO_CACHE_READ and os.path.exists(CACHE_FRED):
        with open(CACHE_FRED) as f: raw = f.read().strip()
        if raw:
            data = json.loads(raw).get("data", {})
            if sid in data:
                s = pd.Series(data[sid]); s.index = pd.to_datetime(s.index); s = s.sort_index()
                if lag_days: s.index = s.index + pd.Timedelta(days=lag_days)
                if close_index is not None: return s.reindex(close_index, method="ffill")
                return s
    print(f"FATAL: FRED {sid} unavailable."); sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════
# Pair selection — baseline (no filter) and with correlation filter
# ═══════════════════════════════════════════════════════════════════════════

def rank_pairs_cached(pairs, disc_tr, fwd_tr, rd, weights):
    """
    Score and rank all pairs descending by pair_power.
    Returns (ranked, dt_vl, ft_vl, fallback) where ranked = [(pair, score), ...].
    This is called ONCE per rebalance window and cached.
    """
    n = len(disc_tr); split = int(n * HELD_OUT_SPLIT)
    dt_tr = disc_tr.iloc[:split]; ft_tr = fwd_tr.iloc[:split]
    dt_vl = disc_tr.iloc[split:]; ft_vl = fwd_tr.iloc[split:]

    active = list(set(s for s1, s2 in pairs for s in [s1, s2]))
    active = [s for s in active if s in dt_tr.columns and (dt_tr[s] != 0).mean() > ACTIVITY_THRESHOLD]
    tr_pairs = [(s1, s2) for s1, s2 in pairs if s1 in active and s2 in active]

    if len(tr_pairs) < MIN_PAIRS:
        meta = {p: _mod.pair_power(disc_tr, fwd_tr, p[0], p[1], rd,
                weights=weights, primary_horizon=PRIMARY_HORIZON) for p in pairs}
        ranked = sorted(meta.items(), key=lambda x: -x[1])
        return ranked, dt_vl, ft_vl, True

    meta = {p: _mod.pair_power(dt_tr, ft_tr, p[0], p[1], rd,
            weights=weights, primary_horizon=PRIMARY_HORIZON) for p in tr_pairs}
    ranked = sorted(meta.items(), key=lambda x: -x[1])
    return ranked, dt_vl, ft_vl, False


def select_from_ranked(ranked, dt_vl, ft_vl, rd, weights, fallback,
                       k=None, use_corr_filter=False, disc_tr=None, rho_max=CORR_THRESHOLD):
    """
    Given pre-computed ranked pairs, select top-K with optional correlation filter.
    """
    if fallback:
        selected = [p for p, _ in ranked[:max(k or MIN_PAIRS, MIN_PAIRS)]]
        return selected, {
            "target_k": max(k or MIN_PAIRS, MIN_PAIRS),
            "candidate_count": len(selected),
            "filtered_due_corr": 0,
            "fill_count": 0,
            "used_fallback": True,
        }

    if k is None:
        target_k = max(math.ceil(len(ranked) * TOP_N_PCT), MIN_PAIRS)
    else:
        target_k = max(k, MIN_PAIRS)

    if not use_corr_filter:
        # Baseline: take top K with floor check (only for top1% mode)
        powers = np.array([s for _, s in ranked])
        floor = np.mean(powers) + SIG_FLOOR_SIGMA * np.std(powers)
        cands = []
        for p, sc in ranked:
            if k is None and sc < floor:
                break
            cands.append(p)
            if len(cands) >= target_k:
                break
        if len(cands) < MIN_PAIRS:
            cands = [p for p, _ in ranked[:MIN_PAIRS]]
    else:
        # Correlation filter: greedy selection
        max_candidates = max(target_k * 10, len(ranked) // 5, 100)

        # Pre-compute product signals
        pair_signals = {}
        for p, _ in ranked[:max_candidates]:
            s1, s2 = p
            if disc_tr is not None and s1 in disc_tr.columns and s2 in disc_tr.columns:
                pair_signals[p] = (disc_tr[s1] * disc_tr[s2]).values
            else:
                pair_signals[p] = np.zeros(len(disc_tr) if disc_tr is not None else 0)

        cands = []
        cand_sigs = []
        filtered_due_corr = 0
        for p, sc in ranked[:max_candidates]:
            if len(cands) >= target_k:
                break
            sig = pair_signals.get(p)
            if sig is None:
                continue

            # Check correlation with already-selected pairs
            too_correlated = False
            for sel_sig in cand_sigs:
                mask = (sig != 0) | (sel_sig != 0)
                if mask.sum() < 30:
                    continue
                rho, _ = spearmanr(sig[mask], sel_sig[mask])
                if rho_max is not None and abs(rho) > rho_max:
                    too_correlated = True
                    break
            if too_correlated:
                filtered_due_corr += 1
                continue
            cands.append(p)
            cand_sigs.append(sig)

        # Fill if not enough
        fill_count = 0
        if len(cands) < MIN_PAIRS:
            for p, _ in ranked:
                if p not in cands:
                    cands.append(p)
                    fill_count += 1
                if len(cands) >= max(target_k, MIN_PAIRS):
                    break
    if not use_corr_filter:
        filtered_due_corr = 0
        fill_count = 0

    # Holdout validation
    validated = []
    for s1, s2 in cands:
        if s1 in dt_vl.columns and s2 in dt_vl.columns:
            vp = _mod.pair_power(dt_vl, ft_vl, s1, s2, rd,
                                 weights=weights, primary_horizon=PRIMARY_HORIZON)
            if vp > 0:
                validated.append((s1, s2))

    if len(validated) < MIN_PAIRS:
        validated = cands[:max(target_k, MIN_PAIRS)]

    return validated, {
        "target_k": target_k,
        "candidate_count": len(cands),
        "filtered_due_corr": filtered_due_corr,
        "fill_count": fill_count,
        "used_fallback": False,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Exposure mapping (verbatim from production)
# ═══════════════════════════════════════════════════════════════════════════

def apply_cooldown(raw_exp, cd=COOLDOWN_DAYS):
    res = raw_exp.copy(); prev = raw_exp.iloc[0]; last_dir = 0; lcd = raw_exp.index[0]
    for i, (dt, tgt) in enumerate(raw_exp.items()):
        if i == 0: res[dt] = tgt; prev = tgt; continue
        d = tgt - prev
        if abs(d) < 0.001: res[dt] = prev; continue
        dirn = 1 if d > 0 else -1
        if last_dir != 0 and dirn != last_dir and (dt - lcd).days < cd: res[dt] = prev
        else: res[dt] = tgt; prev = tgt; lcd = dt; last_dir = dirn
    return res


def find_gate_holm(combo_trail, close_trail, horizon=PRIMARY_HORIZON, alpha=0.05):
    cn = combo_trail[combo_trail != 0].dropna()
    if len(cn) < 60: return 0.0
    fwd_r = close_trail.pct_change(horizon).shift(-horizon)
    com = cn.index.intersection(fwd_r.dropna().index)
    if len(com) < 30: return 0.0
    c = cn.loc[com]; f = fwd_r.loc[com]
    hit = ((c < 0) & (f > 0)) | ((c > 0) & (f < 0))
    for step, pct in enumerate([0, 10, 20, 30, 40, 50, 60, 70, 80, 90], 1):
        thr = 0.0 if pct == 0 else np.percentile(c.abs(), pct)
        mask = c.abs() >= thr if pct > 0 else pd.Series(True, index=c.index)
        n = mask.sum()
        if n < 20: continue
        k = int(hit[mask].sum())
        if binomtest(k, n, 0.5, alternative='greater').pvalue < alpha / step: return thr
    return float(np.percentile(c.abs(), 50))


def run_d10_backtest(combo, close):
    rebal_dates = pd.date_range(pd.Timestamp(EVAL_START), close.index[-1], freq="3MS")
    ty = GATE_THRESHOLD_LOOKBACK
    gates = {}
    for rd in rebal_dates:
        ct = combo[(combo.index >= rd - pd.DateOffset(years=ty)) & (combo.index < rd)]
        cl = close[(close.index >= rd - pd.DateOffset(years=ty)) & (close.index < rd)]
        gates[rd] = find_gate_holm(ct, cl)
    exposure = pd.Series(0.5, index=combo.index); prev = 0.5
    for qi, rd in enumerate(rebal_dates):
        next_rd = rebal_dates[qi + 1] if qi + 1 < len(rebal_dates) else close.index[-1] + pd.Timedelta(days=1)
        hist_nz = combo[(combo.index >= rd - pd.DateOffset(years=ty)) & (combo.index < rd)]
        hist_nz = hist_nz[hist_nz != 0].abs().dropna()
        if len(hist_nz) >= 30:
            thresholds = [np.percentile(hist_nz, 100 * i / (N_THRESHOLDS + 1)) for i in range(1, N_THRESHOLDS + 1)]
        else:
            thresholds = [(i + 1) / (N_THRESHOLDS + 1) for i in range(N_THRESHOLDS)]
        gate = gates.get(rd, 0.0)
        for t in combo.index[(combo.index >= rd) & (combo.index < next_rd)]:
            c = combo.loc[t]
            if np.isnan(c) or abs(c) < gate: exposure.loc[t] = prev; continue
            n_above = sum(abs(c) >= th for th in thresholds)
            if c < 0: prev = min(0.5 + n_above * DELTA, 1.0)
            else: prev = max(0.5 - n_above * DELTA, 0.0)
            exposure.loc[t] = prev
    return apply_cooldown(exposure)


def compute_full_metrics(close_eval, exposure, label=""):
    exp = exposure.reindex(close_eval.index).ffill()
    bt = _mod.backtest_from_exposure(close_eval, exp, label)
    r = bt['port_ret']
    tr = (1 + r).prod() - 1; ny = len(r) / 365.25
    ar = (1 + tr) ** (1 / ny) - 1 if ny > 0 else 0
    av = r.std() * np.sqrt(365)
    sharpe = ar / av if av > 0 else 0
    cum = (1 + r).cumprod(); mdd = float((cum / cum.cummax() - 1).min())

    # Holdout Sharpe (2024-2026)
    ho_r = r[r.index.year.isin([2024, 2025, 2026])]
    if len(ho_r) > 30:
        ho_tr = (1 + ho_r).prod() - 1; ho_ny = len(ho_r) / 365.25
        ho_ar = (1 + ho_tr) ** (1 / ho_ny) - 1 if ho_ny > 0 else 0
        ho_av = ho_r.std() * np.sqrt(365)
        ho_sharpe = ho_ar / ho_av if ho_av > 0 else 0
    else:
        ho_sharpe = 0

    # Sortino
    downside = r[r < 0]
    down_std = downside.std() if len(downside) > 0 else 1e-10
    sortino = (r.mean() / down_std * np.sqrt(365)) if down_std > 0 else 0

    # Calmar
    calmar = ar / abs(mdd) if mdd != 0 else 0

    # Yearly breakdown
    yearly = {yr: float((1 + r[r.index.year == yr]).prod() - 1)
              for yr in sorted(r.index.year.unique())}

    return {
        "label": label,
        "sharpe": round(float(sharpe), 4),
        "ho_sharpe": round(float(ho_sharpe), 4),
        "sortino": round(float(sortino), 4),
        "annual_return": round(float(ar), 4),
        "max_dd": round(float(mdd), 4),
        "avg_exposure": round(float(exp.mean()), 4),
        "calmar": round(float(calmar), 3),
        "yearly": yearly,
        "cum_returns": (1 + r).cumprod(),
        "daily_returns": r,
        "drawdown": (cum / cum.cummax() - 1),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Production scoring (M0 baseline — 4-bucket)
# ═══════════════════════════════════════════════════════════════════════════

def score_m0(hr, med):
    if   hr >= 0.75 and med >  0.02: return -1.0
    elif hr >= 0.60 and med >  0:    return -0.5
    elif hr <= 0.25 and med < -0.02: return  1.0
    elif hr <= 0.40 and med <  0:    return  0.5
    else:                             return  0.0

def make_score_at_date_variant(variant_fn):
    def patched_score_at_date(disc, fwd, top_pairs, t, conviction_gamma=None):
        scores = []
        for s1, s2 in top_pairs:
            st1, st2 = disc.loc[t, s1], disc.loc[t, s2]
            res = _mod.evaluate_joint_state(disc, fwd, s1, s2, (st1, st2), t)
            if res is None:
                continue
            ws, tw = 0.0, 0.0
            for h, stats in res.items():
                w    = _mod.HORIZON_WEIGHTS.get(h, 0.1)
                hr   = stats["hit_rate"]
                med  = stats["median"]
                sv   = variant_fn(hr, med)
                ws += w * sv
                tw += w
            if tw > 0:
                scores.append(np.clip(ws / tw, -1, 1))
        return float(np.mean(scores)) if scores else 0.0
    return patched_score_at_date

def make_eval_events_variant(variant_fn):
    def patched_eval_events(self, evts):
        scores = []
        for h in _mod.FWD_HORIZONS:
            rc = f"fwd_{h}d"
            if rc not in evts.columns:
                continue
            v = evts[rc].dropna()
            if len(v) < _mod.MIN_EVENTS:
                continue
            hr, med = (v > 0).mean(), v.median()
            s = variant_fn(hr, med)
            scores.append((h, s))
        if not scores:
            return 0.0
        tw = sum(_mod.HORIZON_WEIGHTS.get(h, 0.1) for h, _ in scores)
        return sum(_mod.HORIZON_WEIGHTS.get(h, 0.1) * s for h, s in scores) / tw if tw > 0 else 0.0
    return patched_eval_events


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def experiment_grid_main():
    global K_VALUES, RHO_VALUES, REGIME_K_MAPS, OUT_PNG, OUT_JSON, OUT_PAIR_CORR
    parser = argparse.ArgumentParser(description="CycleSignal K/correlation filter experiment")
    parser.add_argument("--k-values", default=None, help="Comma-separated K values, e.g. 10,15,20,25")
    parser.add_argument("--rho-values", default=None, help="Comma-separated rho values; use None for no filter")
    parser.add_argument("--output-suffix", default="", help="Suffix before output extensions, e.g. _rho095")
    parser.add_argument("--skip-fixed-k", action="store_true", help="Only run explicitly requested regime maps")
    parser.add_argument("--regime-1025", action="store_true", help="Run LOW/NORMAL vs HIGH/EXTREME 10/25 regime maps")
    args = parser.parse_args()
    if args.k_values:
        K_VALUES = [int(x.strip()) for x in args.k_values.split(",") if x.strip()]
    if args.rho_values:
        parsed_rhos = []
        for raw in args.rho_values.split(","):
            raw = raw.strip()
            if not raw:
                continue
            parsed_rhos.append(None if raw.lower() == "none" else float(raw))
        RHO_VALUES = parsed_rhos
    if args.output_suffix:
        suffix = args.output_suffix
        OUT_JSON = os.path.join(OUT_DIR, f"corr_filter_results{suffix}.json")
        OUT_PNG = os.path.join(OUT_DIR, f"corr_filter_comparison{suffix}.png")
        OUT_PAIR_CORR = os.path.join(QUANT_DIR, f"pair_corr_timeseries{suffix}.csv")
    if args.regime_1025:
        REGIME_K_MAPS = {
            "RegimeK_LOW25_NORMAL25_HIGH10_EXTREME10": {
                "LOW": 25,
                "NORMAL": 25,
                "HIGH": 10,
                "EXTREME": 10,
            },
            "RegimeK_LOW10_NORMAL10_HIGH25_EXTREME25": {
                "LOW": 10,
                "NORMAL": 10,
                "HIGH": 25,
                "EXTREME": 25,
            },
        }

    t0 = time.time()
    print(f"\n{'='*70}")
    print(f"  K-OPTIMIZATION WITH CORRELATION FILTER")
    print(f"  Eval period: {EVAL_START} to today")
    print(f"  K values: {K_VALUES}")
    if REGIME_K_MAPS:
        print(f"  Regime K maps: {list(REGIME_K_MAPS)}")
    print(f"  Correlation threshold: {CORR_THRESHOLD}")
    print(f"{'='*70}")

    # ── 1. Load all data ─────────────────────────────────────────────────
    print("\n[1/4] Loading data...")
    close = _yf_download_retry("BTC-USD")
    sp500, vix, dxy, gold, hy = _fetch_macro_all(close.index)
    print(f"  BTC: {len(close)} days, {close.index[0].date()} to {close.index[-1].date()}")

    # ── 2. Compute signals ───────────────────────────────────────────────
    print("\n[2/4] Computing signals...")
    cq  = _fetch_cquant_retry(CQ_KEY, start=TRAIN_START)
    prx = _mod.compute_proxy_signals(close, sp500, vix, dxy, gold, hy)
    raw_df = pd.DataFrame({**cq, **prx}).reindex(close.index).ffill()
    ter = _mod.compute_ternary_matrix(raw_df)
    tsr = _mod.compute_technical_signals(close, sp500, _mod.build_technical_signal_registry())
    combined = pd.concat([ter, tsr], axis=1).reindex(close.index).fillna(0)
    vol_zscore = compute_vol_zscore(close).reindex(close.index, method="ffill")
    disc = _mod.discretize_signals(combined)
    fwd  = _mod.compute_forward_returns(close)

    # FRED signals
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

    sigs_all = list(disc.columns)
    n_signals = len(sigs_all)
    print(f"  {n_signals} signals computed")

    # Use M0 scoring (production baseline)
    patched_score = make_score_at_date_variant(score_m0)
    patched_eval = make_eval_events_variant(score_m0)
    _mod.MABreakSignal._eval_events = patched_eval

    # ── 3. Walk-forward for each configuration ───────────────────────────
    print("\n[3/4] Walk-forward backtest...")
    rebal_dates = pd.date_range(pd.Timestamp(EVAL_START), close.index[-1], freq="3MS")

    # Pre-compute pair rankings at each rebalance window (expensive, do ONCE)
    print("\n  Pre-computing pair rankings at each rebalance window...")
    ranking_cache = {}  # (i_rd, ty) -> (ranked, dt_vl, ft_vl, fallback, weights, disc_tr)
    for i_rd, rd in enumerate(rebal_dates):
        for ty in [2, 3]:
            train_start = rd - pd.DateOffset(years=ty)
            in_train = (disc.index >= train_start) & (disc.index < rd)
            disc_tr = disc[in_train]; fwd_tr = fwd[in_train]
            vol_tr = vol_zscore[in_train]

            act = {s: (disc_tr[s] != 0).mean() for s in sigs_all}
            active_sigs = [s for s, a in act.items() if a > ACTIVITY_THRESHOLD]
            pairs = list(combinations(active_sigs, 2))

            vz = float(vol_zscore.asof(rd)) if not pd.isna(vol_zscore.asof(rd)) else np.nan
            regime = _get_vol_regime(vz)
            n_same = int((vol_tr.apply(lambda v: _get_vol_regime(v) == regime)).sum())
            weights = _vol_regime_weights(vol_tr, regime) if n_same >= _mod.MIN_REGIME_TRAIN_DAYS else None

            ranked, dt_vl, ft_vl, fallback = rank_pairs_cached(pairs, disc_tr, fwd_tr, rd, weights)
            ranking_cache[(i_rd, ty)] = (ranked, dt_vl, ft_vl, fallback, weights, disc_tr, regime)
            print(f"    [{rd.date()} {ty}Y] {len(ranked)} pairs ranked", flush=True)

    # Build configurations: no-filter baseline + rho grid
    configs = []
    fixed_k_values_for_configs = [] if args.skip_fixed_k else list(K_VALUES)
    for k_val in fixed_k_values_for_configs:
        for rho_max in RHO_VALUES:
            configs.append({
                "name": _config_name(k_val, rho_max),
                "display": _config_display_name(k_val, rho_max),
                "k_val": k_val,
                "regime_k_map": None,
                "rho_max": rho_max,
                "use_corr_filter": rho_max is not None,
            })
    for regime_label, regime_k_map in REGIME_K_MAPS.items():
        for rho_max in RHO_VALUES:
            configs.append({
                "name": _regime_config_name(regime_label, rho_max),
                "display": _regime_config_display_name(regime_label, rho_max),
                "k_val": regime_label,
                "regime_k_map": regime_k_map,
                "rho_max": rho_max,
                "use_corr_filter": rho_max is not None,
            })

    results = {}
    corr_timeseries_rows = []
    structure_summary = {}

    for cfg in configs:
        cfg_label = cfg["name"]
        print(f"\n  === {cfg_label} ===", flush=True)

        k_val = cfg["k_val"]
        regime_k_map = cfg.get("regime_k_map")
        rho_val = cfg["rho_max"]
        use_corr = cfg["use_corr_filter"]
        k_numeric_static = None if k_val == "top1%" else (None if regime_k_map else int(k_val))

        combo = pd.Series(0.0, index=close.index)

        for i_rd, rd in enumerate(rebal_dates):
            next_rd = rebal_dates[i_rd + 1] if i_rd + 1 < len(rebal_dates) else close.index[-1] + pd.Timedelta(days=1)
            oos_dates = close.index[(close.index >= rd) & (close.index < next_rd)]
            if len(oos_dates) == 0:
                continue

            for ty in [2, 3]:
                ranked, dt_vl, ft_vl, fallback, weights, disc_tr_cached, regime = ranking_cache[(i_rd, ty)]
                k_numeric = int(regime_k_map.get(regime, MIN_PAIRS)) if regime_k_map else k_numeric_static
                top_pairs, selection_debug = select_from_ranked(
                    ranked, dt_vl, ft_vl, rd, weights, fallback,
                    k=k_numeric, use_corr_filter=use_corr,
                    disc_tr=disc_tr_cached, rho_max=rho_val)
                corr_stats = _selected_pair_corr_stats(top_pairs, disc_tr_cached)
                filtered_ratio = (
                    selection_debug["filtered_due_corr"] /
                    max(selection_debug["candidate_count"] + selection_debug["filtered_due_corr"], 1)
                )
                corr_timeseries_rows.append({
                    "config": cfg_label,
                    "display": cfg["display"],
                    "k_value": _fmt_k_value(k_val),
                    "regime": regime,
                    "regime_k": k_numeric,
                    "rho_max": _fmt_rho_value(rho_val),
                    "rebalance_date": rd.strftime("%Y-%m-%d"),
                    "train_years": ty,
                    "selected_pairs": len(top_pairs),
                    "target_k": selection_debug["target_k"],
                    "candidate_count": selection_debug["candidate_count"],
                    "filtered_due_corr": selection_debug["filtered_due_corr"],
                    "filtered_ratio": round(float(filtered_ratio), 4),
                    "fill_count": selection_debug["fill_count"],
                    "avg_abs_corr": corr_stats["avg_abs_corr"],
                    "max_abs_corr": corr_stats["max_abs_corr"],
                    "corr_pairs_evaluated": corr_stats["corr_pairs_evaluated"],
                })

                for t in oos_dates:
                    combo.loc[t] += patched_score(disc, fwd, top_pairs, t)

            combo.loc[oos_dates] /= 2

        exposure = run_d10_backtest(combo, close)
        close_eval = close.loc[EVAL_START:]
        metrics = compute_full_metrics(close_eval, exposure.loc[EVAL_START:], label=cfg_label)
        results[cfg_label] = metrics
        cfg_rows = [r for r in corr_timeseries_rows if r["config"] == cfg_label]
        if cfg_rows:
            structure_summary[cfg_label] = {
                "avg_abs_corr": round(float(np.mean([r["avg_abs_corr"] for r in cfg_rows])), 4),
                "max_abs_corr": round(float(np.max([r["max_abs_corr"] for r in cfg_rows])), 4),
                "avg_filtered_ratio": round(float(np.mean([r["filtered_ratio"] for r in cfg_rows])), 4),
                "avg_selected_pairs": round(float(np.mean([r["selected_pairs"] for r in cfg_rows])), 2),
            }
            metrics.update(structure_summary[cfg_label])

        print(f"    Sharpe={metrics['sharpe']:+.4f}  HO_Sharpe={metrics['ho_sharpe']:+.4f}  "
              f"Sortino={metrics['sortino']:+.4f}  AnnRet={metrics['annual_return']:.1%}  "
              f"MaxDD={metrics['max_dd']:.1%}  Calmar={metrics['calmar']:.3f}", flush=True)
        for yr, ret in sorted(metrics['yearly'].items()):
            print(f"      {yr}: {ret:+.1%}")

    # Buy & Hold reference
    close_eval = close.loc[EVAL_START:]
    bh_ret = close_eval.pct_change().dropna()
    bh_cum = (1 + bh_ret).cumprod()
    bh_ny = len(bh_ret) / 365.25
    bh_ar = (1 + (bh_cum.iloc[-1] - 1)) ** (1 / bh_ny) - 1 if bh_ny > 0 else 0
    bh_mdd = float((bh_cum / bh_cum.cummax() - 1).min())
    bh_sharpe = (bh_ret.mean() / bh_ret.std() * np.sqrt(365)) if bh_ret.std() > 0 else 0
    bh_downside = bh_ret[bh_ret < 0]
    bh_sortino = (bh_ret.mean() / bh_downside.std() * np.sqrt(365)) if len(bh_downside) > 0 else 0
    bh_calmar = bh_ar / abs(bh_mdd) if bh_mdd != 0 else 0
    bh_yearly = {yr: float((1 + bh_ret[bh_ret.index.year == yr]).prod() - 1)
                 for yr in sorted(bh_ret.index.year.unique())}
    results["Buy_Hold"] = {
        "label": "Buy_Hold", "sharpe": round(float(bh_sharpe), 4),
        "ho_sharpe": 0, "sortino": round(float(bh_sortino), 4),
        "annual_return": round(float(bh_ar), 4),
        "max_dd": round(float(bh_mdd), 4), "avg_exposure": 1.0,
        "calmar": round(float(bh_calmar), 3),
        "yearly": bh_yearly,
        "cum_returns": bh_cum, "daily_returns": bh_ret,
        "drawdown": bh_cum / bh_cum.cummax() - 1,
    }

    # ── 4. Output ────────────────────────────────────────────────────────
    print(f"\n[4/4] Generating outputs...")

    # Summary table
    all_labels = [cfg["name"] for cfg in configs] + ["Buy_Hold"]
    print(f"\n{'='*110}")
    print(f"  {'Config':<24} {'Sharpe':>8} {'HO_Shr':>8} {'Sortino':>8} {'AnnRet':>8} {'MaxDD':>8} {'Calmar':>8} {'AvgExp':>8}")
    print(f"  {'-'*24} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    for name in all_labels:
        m = results[name]
        print(f"  {name:<24} {m['sharpe']:>+8.4f} {m.get('ho_sharpe', 0):>+8.4f} {m['sortino']:>+8.4f} "
              f"{m['annual_return']:>7.1%} {m['max_dd']:>7.1%} {m['calmar']:>8.3f} {m['avg_exposure']:>7.2f}")
    print(f"{'='*110}")

    print(f"\n  Correlation Filter Delta Analysis (vs rho=None):")
    print(f"  {'K':<12} {'rho_max':<10} {'dSharpe':>10} {'dHO_Shr':>10} {'dSortino':>10} {'dAnnRet':>10} {'dMaxDD':>10}")
    print(f"  {'-'*12} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")
    for k_val in fixed_k_values_for_configs:
        base = results[_config_name(k_val, None)]
        for rho_max in RHO_VALUES[1:]:
            name = _config_name(k_val, rho_max)
            m = results[name]
            ds = m['sharpe'] - base['sharpe']
            dh = m['ho_sharpe'] - base['ho_sharpe']
            dso = m['sortino'] - base['sortino']
            da = m['annual_return'] - base['annual_return']
            dm = m['max_dd'] - base['max_dd']
            print(f"  {_fmt_k_value(k_val):<12} {_fmt_rho_value(rho_max):<10} {ds:>+10.4f} {dh:>+10.4f} {dso:>+10.4f} {da:>+10.1%} {dm:>+10.1%}")
    for regime_label in REGIME_K_MAPS:
        base = results[_regime_config_name(regime_label, None)]
        for rho_max in RHO_VALUES[1:]:
            name = _regime_config_name(regime_label, rho_max)
            m = results[name]
            ds = m['sharpe'] - base['sharpe']
            dh = m['ho_sharpe'] - base['ho_sharpe']
            dso = m['sortino'] - base['sortino']
            da = m['annual_return'] - base['annual_return']
            dm = m['max_dd'] - base['max_dd']
            print(f"  {regime_label:<12} {_fmt_rho_value(rho_max):<10} {ds:>+10.4f} {dh:>+10.4f} {dso:>+10.4f} {da:>+10.1%} {dm:>+10.1%}")
    print(f"{'='*110}")

    # Yearly table
    all_years = sorted(set(yr for name in results for yr in results[name].get("yearly", {}).keys()))
    print(f"\n  {'Config':<24}", end="")
    for yr in all_years:
        print(f" {yr:>8}", end="")
    print()
    print(f"  {'-'*24}", end="")
    for _ in all_years:
        print(f" {'-'*8}", end="")
    print()
    for name in all_labels:
        print(f"  {name:<24}", end="")
        for yr in all_years:
            ret = results[name].get("yearly", {}).get(yr, 0)
            print(f" {ret:>+7.1%}", end="")
        print()

    # Save JSON
    json_results = {
        "metadata": {
            "eval_start": EVAL_START,
            "signal_count": n_signals,
            "k_values": fixed_k_values_for_configs,
            "regime_k_maps": REGIME_K_MAPS,
            "rho_values": [None if x is None else float(x) for x in RHO_VALUES],
            "run_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
        "configs": {},
        "delta_analysis": {},
        "structure_analysis": structure_summary,
    }
    for name, m in results.items():
        json_results["configs"][name] = {k: v for k, v in m.items()
                                         if k not in ("cum_returns", "daily_returns", "drawdown")}
    for k_val in fixed_k_values_for_configs:
        base_name = _config_name(k_val, None)
        base = results[base_name]
        json_results["delta_analysis"][base_name] = {}
        for rho_max in RHO_VALUES[1:]:
            name = _config_name(k_val, rho_max)
            m = results[name]
            json_results["delta_analysis"][base_name][name] = {
                "d_sharpe": round(float(m["sharpe"] - base["sharpe"]), 4),
                "d_ho_sharpe": round(float(m["ho_sharpe"] - base["ho_sharpe"]), 4),
                "d_sortino": round(float(m["sortino"] - base["sortino"]), 4),
                "d_annual_return": round(float(m["annual_return"] - base["annual_return"]), 4),
                "d_max_dd": round(float(m["max_dd"] - base["max_dd"]), 4),
            }
    for regime_label in REGIME_K_MAPS:
        base_name = _regime_config_name(regime_label, None)
        base = results[base_name]
        json_results["delta_analysis"][base_name] = {}
        for rho_max in RHO_VALUES[1:]:
            name = _regime_config_name(regime_label, rho_max)
            m = results[name]
            json_results["delta_analysis"][base_name][name] = {
                "d_sharpe": round(float(m["sharpe"] - base["sharpe"]), 4),
                "d_ho_sharpe": round(float(m["ho_sharpe"] - base["ho_sharpe"]), 4),
                "d_sortino": round(float(m["sortino"] - base["sortino"]), 4),
                "d_annual_return": round(float(m["annual_return"] - base["annual_return"]), 4),
                "d_max_dd": round(float(m["max_dd"] - base["max_dd"]), 4),
            }
    with open(OUT_JSON, "w") as f:
        json.dump(json_results, f, indent=2, default=str)
    print(f"\n  Saved: {OUT_JSON}")
    pd.DataFrame(corr_timeseries_rows).to_csv(OUT_PAIR_CORR, index=False)
    print(f"  Saved: {OUT_PAIR_CORR}")

    # ── Generate chart ───────────────────────────────────────────────────
    BG, GRID, WHITE, DIM = '#0e1117', '#1e2330', '#e8eaf0', '#8892a4'
    rho_colors = {
        None: "#e17055",
        0.9: "#00b894",
        0.8: "#6c5ce7",
        0.7: "#fdcb6e",
        0.6: "#00cec9",
        0.5: "#fd79a8",
    }

    fig = plt.figure(figsize=(22, 18), facecolor=BG)
    fig.suptitle(f'CycleSignal K Optimization with Correlation Filter ({TX_COST_BPS}bps TX cost)\n'
                 f'{EVAL_START} to {datetime.now().strftime("%Y-%m-%d")}\n'
                 f'rho_max values: {", ".join(_fmt_rho_value(x) for x in RHO_VALUES)}',
                 color=WHITE, fontsize=14, fontweight='bold', y=0.99)

    gs = gridspec.GridSpec(3, 2, figure=fig, hspace=0.4, wspace=0.3,
                           left=0.06, right=0.97, top=0.90, bottom=0.06)

    if fixed_k_values_for_configs:
        plot_labels = [_fmt_k_value(k) for k in fixed_k_values_for_configs]
        x = np.arange(len(fixed_k_values_for_configs))

        def _series(metric_name, rho_max):
            return [results[_config_name(k, rho_max)][metric_name] for k in fixed_k_values_for_configs]
    else:
        plot_labels = [cfg["name"].replace("RegimeK_", "") for cfg in configs]
        x = np.arange(len(configs))

    metric_panels = [
        (gs[0, 0], "sharpe", "Sharpe Ratio"),
        (gs[0, 1], "ho_sharpe", "Holdout Sharpe"),
        (gs[1, 0], "annual_return", "Annual Return"),
        (gs[1, 1], "sortino", "Sortino Ratio"),
        (gs[2, 0], "max_dd", "Max Drawdown"),
    ]
    for spec, metric_name, title in metric_panels:
        ax = fig.add_subplot(spec)
        ax.set_facecolor(BG)
        for sp in ax.spines.values():
            sp.set_color(GRID)
        ax.tick_params(colors=DIM)
        ax.grid(color=GRID, alpha=0.3)
        if fixed_k_values_for_configs:
            for rho_max in RHO_VALUES:
                ax.plot(x, _series(metric_name, rho_max), marker='o', linewidth=1.8, markersize=4,
                        color=rho_colors.get(rho_max, "#ffffff"), label=f"rho={_fmt_rho_value(rho_max)}")
        else:
            vals = [results[cfg["name"]][metric_name] for cfg in configs]
            colors = [rho_colors.get(cfg["rho_max"], "#ffffff") for cfg in configs]
            ax.bar(x, vals, color=colors)
        ax.set_xticks(x)
        ax.set_xticklabels(plot_labels, fontsize=6, color=DIM, rotation=45, ha="right")
        ax.set_title(title, color=WHITE, fontsize=11)
        ax.set_xlabel("Config", color=DIM)
        if fixed_k_values_for_configs:
            ax.legend(loc='best', fontsize=7, facecolor=BG, edgecolor=GRID, labelcolor=WHITE)

    ax_tbl = fig.add_subplot(gs[2, 1])
    ax_tbl.set_facecolor(BG)
    ax_tbl.axis('off')
    cell_text = []
    col_labels = ["Sharpe", "HO Shr", "Sortino", "AnnRet", "MaxDD", "Calmar", "AvgExp"]
    row_labels = []
    for name in all_labels:
        m = results[name]
        cell_text.append([
            f"{m['sharpe']:+.3f}",
            f"{m.get('ho_sharpe', 0):+.3f}",
            f"{m['sortino']:+.3f}",
            f"{m['annual_return']:.1%}",
            f"{m['max_dd']:.1%}",
            f"{m['calmar']:.2f}",
            f"{m['avg_exposure']:.2f}",
        ])
        row_labels.append(name)
    table = ax_tbl.table(cellText=cell_text, rowLabels=row_labels, colLabels=col_labels,
                         loc='center', cellLoc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(6)
    for key, cell in table.get_celld().items():
        cell.set_facecolor(BG)
        cell.set_edgecolor(GRID)
        cell.set_text_props(color=WHITE)
        cell.set_height(0.055)

    plt.savefig(OUT_PNG, dpi=150, facecolor=BG, bbox_inches='tight')
    print(f"  Saved: {OUT_PNG}")
    plt.close()

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed/60:.1f} minutes.")


def _json_default(obj):
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    return str(obj)


def _latest_position_advice(exposure_value: float) -> str:
    if exposure_value > 0.55:
        return "Long / Overweight BTC"
    if exposure_value < 0.45:
        return "Underweight BTC"
    return "Neutral BTC"


def _load_production_data():
    print("\n[1/4] Loading data...")
    close = _yf_download_retry("BTC-USD")
    sp500, vix, dxy, gold, hy = _fetch_macro_all(close.index)
    print(f"  BTC: {len(close)} days, {close.index[0].date()} to {close.index[-1].date()}")

    print("\n[2/4] Computing signals...")
    cq = _fetch_cquant_retry(CQ_KEY, start=TRAIN_START)
    prx = _mod.compute_proxy_signals(close, sp500, vix, dxy, gold, hy)
    raw_df = pd.DataFrame({**cq, **prx}).reindex(close.index).ffill()
    ter = _mod.compute_ternary_matrix(raw_df)
    tsr = _mod.compute_technical_signals(close, sp500, _mod.build_technical_signal_registry())
    combined = pd.concat([ter, tsr], axis=1).reindex(close.index).fillna(0)
    vol_zscore = compute_vol_zscore(close).reindex(close.index, method="ffill")
    disc = _mod.discretize_signals(combined)
    fwd = _mod.compute_forward_returns(close)

    # FRED-derived macro signals.
    ffr = _fetch_fred_retry(FRED_KEY, "FEDFUNDS", lag_days=7, close_index=close.index)
    ppi = _fetch_fred_retry(FRED_KEY, "PPIACO", lag_days=60, close_index=close.index)
    cpi = _fetch_fred_retry(FRED_KEY, "CPIAUCSL", lag_days=45, close_index=close.index)
    sofr = _fetch_fred_retry(FRED_KEY, "SOFR", close_index=close.index)
    iorb = _fetch_fred_retry(FRED_KEY, "IORB", close_index=close.index)
    rrp = _fetch_fred_retry(FRED_KEY, "RRPONTSYD", close_index=close.index)

    disc["FFR_vs_MA365"] = np.sign(ffr - ffr.rolling(365).mean()).reindex(disc.index).fillna(0).clip(-1, 1).astype(int)
    disc["SOFR_IORB_Spread_Sign"] = np.sign(sofr - iorb).reindex(disc.index).fillna(0).clip(-1, 1).astype(int)
    disc["RRP_Trend_90d"] = np.sign(rrp - rrp.rolling(90).mean()).reindex(disc.index).fillna(0).clip(-1, 1).astype(int)
    ppi_yoy = ppi.pct_change(365)
    cpi_yoy = cpi.pct_change(365)
    disc["PPI_vs_CPI"] = np.sign(ppi_yoy - cpi_yoy).reindex(disc.index).fillna(0).clip(-1, 1).astype(int)

    print(f"  Signals: {len(disc.columns)}")
    return close, disc, fwd, vol_zscore


def _run_production_strategy(close, disc, fwd, vol_zscore):
    print("\n[3/4] Running production walk-forward backtest...")
    patched_score = make_score_at_date_variant(score_m0)
    _mod.MABreakSignal._eval_events = make_eval_events_variant(score_m0)

    sigs_all = list(disc.columns)
    rebal_dates = pd.date_range(pd.Timestamp(EVAL_START), close.index[-1], freq="3MS")
    combo = pd.Series(0.0, index=close.index)
    corr_rows = []

    for i_rd, rd in enumerate(rebal_dates):
        next_rd = rebal_dates[i_rd + 1] if i_rd + 1 < len(rebal_dates) else close.index[-1] + pd.Timedelta(days=1)
        oos_dates = close.index[(close.index >= rd) & (close.index < next_rd)]
        if len(oos_dates) == 0:
            continue

        for ty in [2, 3]:
            train_start = rd - pd.DateOffset(years=ty)
            in_train = (disc.index >= train_start) & (disc.index < rd)
            disc_tr = disc[in_train]
            fwd_tr = fwd[in_train]
            vol_tr = vol_zscore[in_train]

            active_sigs = [s for s in sigs_all if (disc_tr[s] != 0).mean() > ACTIVITY_THRESHOLD]
            pairs = list(combinations(active_sigs, 2))

            vz = float(vol_zscore.asof(rd)) if not pd.isna(vol_zscore.asof(rd)) else np.nan
            regime = _get_vol_regime(vz)
            n_same = int((vol_tr.apply(lambda v: _get_vol_regime(v) == regime)).sum())
            weights = _vol_regime_weights(vol_tr, regime) if n_same >= _mod.MIN_REGIME_TRAIN_DAYS else None

            ranked, dt_vl, ft_vl, fallback = rank_pairs_cached(pairs, disc_tr, fwd_tr, rd, weights)
            target_k = int(REGIME_K_MAP.get(regime, MIN_PAIRS))
            top_pairs, selection_debug = select_from_ranked(
                ranked,
                dt_vl,
                ft_vl,
                rd,
                weights,
                fallback,
                k=target_k,
                use_corr_filter=True,
                disc_tr=disc_tr,
                rho_max=RHO_MAX,
            )

            corr_stats = _selected_pair_corr_stats(top_pairs, disc_tr)
            filtered_ratio = (
                selection_debug["filtered_due_corr"] /
                max(selection_debug["candidate_count"] + selection_debug["filtered_due_corr"], 1)
            )
            corr_rows.append({
                "config": CONFIG_NAME,
                "rebalance_date": rd.strftime("%Y-%m-%d"),
                "train_years": ty,
                "regime": regime,
                "target_k": target_k,
                "selected_pairs": len(top_pairs),
                "candidate_count": selection_debug["candidate_count"],
                "filtered_due_corr": selection_debug["filtered_due_corr"],
                "filtered_ratio": round(float(filtered_ratio), 4),
                "fill_count": selection_debug["fill_count"],
                "avg_abs_corr": corr_stats["avg_abs_corr"],
                "max_abs_corr": corr_stats["max_abs_corr"],
                "corr_pairs_evaluated": corr_stats["corr_pairs_evaluated"],
            })

            for t in oos_dates:
                combo.loc[t] += patched_score(disc, fwd, top_pairs, t)

        combo.loc[oos_dates] /= 2
        print(f"  {rd.date()} done")

    exposure = run_d10_backtest(combo, close)
    close_eval = close.loc[EVAL_START:]
    metrics = compute_full_metrics(close_eval, exposure.loc[EVAL_START:], label=CONFIG_NAME)
    return combo, exposure, metrics, corr_rows


def _write_production_outputs(close, combo, exposure, metrics, corr_rows):
    print("\n[4/4] Writing production outputs...")
    corr_df = pd.DataFrame(corr_rows)
    corr_df.to_csv(OUT_PAIR_CORR, index=False)

    close_eval = close.loc[EVAL_START:]
    exp_eval = exposure.reindex(close_eval.index).ffill()
    latest_date = combo.dropna().index[-1]
    latest_exposure = float(exposure.reindex([latest_date]).ffill().iloc[-1])
    latest_composite = float(combo.loc[latest_date])

    structure = {
        "avg_selected_pairs": round(float(corr_df["selected_pairs"].mean()), 2),
        "avg_abs_corr": round(float(corr_df["avg_abs_corr"].mean()), 4),
        "max_abs_corr": round(float(corr_df["max_abs_corr"].max()), 4),
        "avg_filtered_ratio": round(float(corr_df["filtered_ratio"].mean()), 4),
        "avg_filtered_due_corr": round(float(corr_df["filtered_due_corr"].mean()), 2),
    }
    current_signal = {
        "latest_date": latest_date.strftime("%Y-%m-%d"),
        "latest_btc_price": round(float(close.loc[latest_date]), 2),
        "latest_composite": round(latest_composite, 6),
        "latest_exposure": round(latest_exposure, 4),
        "btc_position_pct": round(latest_exposure * 100, 2),
        "advice": _latest_position_advice(latest_exposure),
    }

    payload = {
        "metadata": {
            "run_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "config": CONFIG_NAME,
            "k_policy": REGIME_K_MAP,
            "rho_max": RHO_MAX,
            "daily_scoring": "Original/M0 Hit Rate + Median Return",
            "implementation_note": "Self-contained production runner; imports only btc_combined_backtest_lib.py.",
        },
        "current_signal": current_signal,
        "metrics": {
            k: v for k, v in metrics.items()
            if k not in ("cum_returns", "daily_returns", "drawdown")
        },
        "structure": structure,
    }
    with open(OUT_JSON, "w") as f:
        json.dump(payload, f, indent=2, default=_json_default)

    fig = plt.figure(figsize=(14, 9))
    gs = gridspec.GridSpec(3, 1, height_ratios=[2, 1, 1], hspace=0.25)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax3 = fig.add_subplot(gs[2], sharex=ax1)

    ax1.plot(metrics["cum_returns"].index, metrics["cum_returns"].values, linewidth=1.8)
    ax1.set_title(
        f"{CONFIG_NAME}: Sharpe {metrics['sharpe']:.4f}, "
        f"HO {metrics['ho_sharpe']:.4f}, Annual {metrics['annual_return']:.2%}"
    )
    ax1.set_yscale("log")
    ax1.grid(True, alpha=0.25)

    ax2.plot(metrics["drawdown"].index, metrics["drawdown"].values, color="#d62728", linewidth=1.2)
    ax2.set_title(f"Drawdown (MaxDD {metrics['max_dd']:.2%})")
    ax2.grid(True, alpha=0.25)

    ax3.plot(exp_eval.index, exp_eval.values * 100, color="#2ca02c", linewidth=1.2)
    ax3.set_title(
        f"BTC Exposure, latest {current_signal['btc_position_pct']:.1f}% "
        f"({current_signal['advice']})"
    )
    ax3.set_ylabel("Exposure %")
    ax3.grid(True, alpha=0.25)

    plt.savefig(OUT_PNG, dpi=150, bbox_inches="tight")
    plt.close()

    print(f"  Saved JSON: {OUT_JSON}")
    print(f"  Saved chart: {OUT_PNG}")
    print(f"  Saved pair correlation: {OUT_PAIR_CORR}")
    print("\nProduction summary:")
    print(f"  Sharpe:        {metrics['sharpe']:.4f}")
    print(f"  HO Sharpe:     {metrics['ho_sharpe']:.4f}")
    print(f"  Annual Return: {metrics['annual_return']:.2%}")
    print(f"  Max Drawdown:  {metrics['max_dd']:.2%}")
    print(f"  Latest BTC:    {current_signal['btc_position_pct']:.1f}% ({current_signal['advice']})")


def main():
    t0 = time.time()
    print(f"\n{'='*78}")
    print("  CycleSignal Production: Regime 10/25 + rho0.95 + HR/Median")
    print(f"  Eval period: {EVAL_START} to latest available BTC close")
    print(f"  K policy: {REGIME_K_MAP}")
    print(f"  rho_max: {RHO_MAX}")
    print(f"{'='*78}")
    close, disc, fwd, vol_zscore = _load_production_data()
    combo, exposure, metrics, corr_rows = _run_production_strategy(close, disc, fwd, vol_zscore)
    _write_production_outputs(close, combo, exposure, metrics, corr_rows)
    print(f"\nDone in {(time.time() - t0) / 60:.1f} minutes.")


if __name__ == "__main__":
    main()
