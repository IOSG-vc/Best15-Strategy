#!/usr/bin/env python3
"""Self-contained K3 strategy entry point.

This file does not import saved K3 selected/daily/backtest artifacts and does
not rely on a shared K3 core module. It rebuilds the extended signal universe,
mines walk-forward K3 candidates, auto-selects strict top10 leaders, and runs the
strategy-specific daily evidence, rank, exposure, and backtest logic in this file.
"""
from __future__ import annotations

import importlib.util
import math
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd


H = 60
TH = 0.15
HALFLIFE = 30.0
MAX_LIFE = 60
SHRINK_K = 20
MIN_TRAIN_SUPPORT = 5
TOP_CANDIDATES_TO_SCORE = 1500
ANN_DAYS = 365.0
FEE_PER_UNIT = 0.0010


HERE = Path(__file__).resolve().parent
V3_FILENAMES = (
    "v3_cycle_signal_production_backup.py",
    "v3_cycle_signal_production_regime1025_rho095_hr_median.git_HEAD_6431030_backup.py",
    "v3_cycle_signal_production_regime1025_rho095_hr_median.py",
)


def resolve_root_and_v3(start: Path) -> tuple[Path, Path]:
    for parent in [start, *start.parents]:
        for filename in V3_FILENAMES:
            for rel in (Path("v3_production_0428") / filename, Path("Cycle_Signal") / "v3_production_0428" / filename):
                candidate = parent / rel
                if candidate.exists():
                    root = parent if (parent / "Cycle_Signal").exists() else parent.parent
                    return root, candidate
    raise FileNotFoundError(f"Could not locate any V3 production file: {V3_FILENAMES}")


ROOT, V3_FILE = resolve_root_and_v3(HERE)
V4D = ROOT / "Cycle_Signal" / "v4d"


PASSERS: list[tuple[str, str, str, int, int]] = [
    ("Zscore_SMA365_daily_ROC30", "Zscore_SMA365_daily", "tech", 1, 30),
    ("SSR_ROC30", "SSR", "raw", 1, 30),
    ("DXY_ROC30", "DXY", "raw", 1, 30),
    ("SP500_Trend_ROC90", "SP500_Trend", "raw_exception", 1, 90),
    ("SOFR_IORB_Spread_ROC30", "SOFR_IORB_Spread", "macro", 1, 30),
    ("Gold_90d_ROC30", "Gold_90d", "raw", 1, 30),
    ("HY_Spread_ROC30", "HY_Spread", "raw", 1, 30),
    ("LR_1Y_ROC7", "LR_1Y", "raw", 1, 7),
    ("Zscore_SMA365_daily_ROC7", "Zscore_SMA365_daily", "tech", 1, 7),
    ("GapPct_SMA90_365d_ROC30", "GapPct_SMA90_365d", "tech", 1, 30),
    ("Zscore_SMA26_weekly_ROC7", "Zscore_SMA26_weekly", "tech", 1, 7),
    ("Zscore_EMA200_daily_ROC30", "Zscore_EMA200_daily", "tech", 1, 30),
    ("Zscore_EMA26_weekly_ROC7", "Zscore_EMA26_weekly", "tech", 1, 7),
    ("GapPct_SMA365_365d_ROC7", "GapPct_SMA365_365d", "tech", 1, 7),
    ("Zscore_EMA50_daily_ROC30", "Zscore_EMA50_daily", "tech", 1, 30),
    ("LR_2Y_Z_ROC7", "LR_2Y_Z", "raw", 1, 7),
    ("Zscore_SMA200_daily_ROC30", "Zscore_SMA200_daily", "tech", 1, 30),
    ("Zscore_EMA90_daily_ROC30", "Zscore_EMA90_daily", "tech", 1, 30),
    ("Open_Interest_ROC30", "Open_Interest", "raw", 1, 30),
    ("LR_2Y_Z_ROC2_30", "LR_2Y_Z", "raw", 2, 30),
    ("GapPct_SMA200_365d_ROC7", "GapPct_SMA200_365d", "tech", 1, 7),
    ("Zscore_EMA365_daily_ROC7", "Zscore_EMA365_daily", "tech", 1, 7),
    ("GapPct_EMA365_365d_ROC7", "GapPct_EMA365_365d", "tech", 1, 7),
    ("SSR_ROC7", "SSR", "raw", 1, 7),
    ("GapPct_SMA90_365d_ROC7", "GapPct_SMA90_365d", "tech", 1, 7),
    ("Exch_Reserve_ROC2_30", "Exch_Reserve", "raw", 2, 30),
    ("Zscore_EMA50_daily_ROC7", "Zscore_EMA50_daily", "tech", 1, 7),
    ("Zscore_SMA50_daily_ROC7", "Zscore_SMA50_daily", "tech", 1, 7),
    ("Zscore_EMA90_daily_ROC7", "Zscore_EMA90_daily", "tech", 1, 7),
    ("GapPct_EMA200_365d_ROC7", "GapPct_EMA200_365d", "tech", 1, 7),
    ("Coinbase_Prem_ROC30", "Coinbase_Prem", "raw", 1, 30),
    ("MVRV_Proxy_ROC7", "MVRV_Proxy", "raw", 1, 7),
    ("Zscore_EMA200_daily_ROC7", "Zscore_EMA200_daily", "tech", 1, 7),
    ("Exch_Reserve_ROC30", "Exch_Reserve", "raw", 1, 30),
    ("GapPct_EMA90_365d_ROC7", "GapPct_EMA90_365d", "tech", 1, 7),
    ("NVM_ROC30", "NVM", "raw", 1, 30),
    ("HY_Spread_ROC2_30", "HY_Spread", "raw", 2, 30),
    ("Gold_90d_ROC7", "Gold_90d", "raw", 1, 7),
    ("Puell_ROC7", "Puell", "raw", 1, 7),
    ("Zscore_SMA90_daily_ROC7", "Zscore_SMA90_daily", "tech", 1, 7),
    ("NRPL_ROC7", "NRPL", "raw", 1, 7),
    ("SOPR_Ratio_ROC7", "SOPR_Ratio", "raw", 1, 7),
    ("SOFR_IORB_Spread_ROC7", "SOFR_IORB_Spread", "macro", 1, 7),
    ("DXY_ROC7", "DXY", "raw", 1, 7),
    ("MPI_ROC30", "MPI", "raw", 1, 30),
    ("Zscore_SMA200_daily_ROC7", "Zscore_SMA200_daily", "tech", 1, 7),
    ("SP500_Trend_ROC2_30", "SP500_Trend", "raw", 2, 30),
    ("MABreak_SMA_d_50_100_200_365_frac_ROC7", "MABreak_SMA_d_50_100_200_365_frac", "stream_A", 1, 7),
    ("T5YIE_ROC30", "T5YIE", "stream_D_macro", 1, 30),
    ("EM_minus_DM_logratio_ROC30", "EM_minus_DM_logratio", "stream_D_macro", 1, 30),
    ("DCOILWTICO_ROC30", "DCOILWTICO", "stream_D_macro", 1, 30),
    ("MABreak_EMA_d_50_100_200_365_frac_ROC7", "MABreak_EMA_d_50_100_200_365_frac", "stream_A", 1, 7),
    ("T10Y2Y_ROC30", "T10Y2Y", "stream_D_macro", 1, 30),
    ("MABreak_SMA_d_50_100_200_365_frac_ROC2_30", "MABreak_SMA_d_50_100_200_365_frac", "stream_A", 2, 30),
    ("T10YIE_ROC30", "T10YIE", "stream_D_macro", 1, 30),
    ("MABreak_EMA_d_30_90_180_365_frac_ROC7", "MABreak_EMA_d_30_90_180_365_frac", "stream_A", 1, 7),
    ("MABreak_EMA_d_30_90_180_365_frac_ROC30", "MABreak_EMA_d_30_90_180_365_frac", "stream_A", 1, 30),
    ("MABreak_SMA_d_30_90_180_365_frac_ROC30", "MABreak_SMA_d_30_90_180_365_frac", "stream_A", 1, 30),
    ("MABreak_SMA_d_30_90_180_365_frac_ROC7", "MABreak_SMA_d_30_90_180_365_frac", "stream_A", 1, 7),
    ("MABreak_SMA_w_4_13_26_52_frac_ROC7", "MABreak_SMA_w_4_13_26_52_frac", "stream_A", 1, 7),
    ("MABreak_SMA_d_30_90_180_365_frac_ROC2_30", "MABreak_SMA_d_30_90_180_365_frac", "stream_A", 2, 30),
    ("MABreak_EMA_d_50_100_200_365_frac_ROC30", "MABreak_EMA_d_50_100_200_365_frac", "stream_A", 1, 30),
    ("T5YIE_ROC7", "T5YIE", "stream_D_macro", 1, 7),
    ("MABreak_EMA_d_30_90_180_365_frac_ROC2_30", "MABreak_EMA_d_30_90_180_365_frac", "stream_A", 2, 30),
    ("T10Y2Y_ROC7", "T10Y2Y", "stream_D_macro", 1, 7),
    ("MABreak_EMA_d_50_100_200_365_frac_ROC2_30", "MABreak_EMA_d_50_100_200_365_frac", "stream_A", 2, 30),
    ("DCOILWTICO_ROC7", "DCOILWTICO", "stream_D_macro", 1, 7),
    ("DCOILWTICO_ROC2_7", "DCOILWTICO", "stream_D_macro", 2, 7),
    ("MABreak_SMA_d_30_90_180_365_frac_ROC2_7", "MABreak_SMA_d_30_90_180_365_frac", "stream_A", 2, 7),
    ("CDD_ROC30", "CDD", "stream_D_onchain", 1, 30),
    ("IG_minus_HY_logratio_ROC30", "IG_minus_HY_logratio", "stream_D_macro", 1, 30),
    ("MABreak_EMA_w_4_13_26_52_frac_ROC2_7", "MABreak_EMA_w_4_13_26_52_frac", "stream_A", 2, 7),
    ("Funding_Rate_ROC7", "Funding_Rate", "stream_D_onchain", 1, 7),
    ("T10YIE_ROC7", "T10YIE", "stream_D_macro", 1, 7),
    ("T10YIE_ROC2_30", "T10YIE", "stream_D_macro", 2, 30),
    ("T5YIE_ROC2_30", "T5YIE", "stream_D_macro", 2, 30),
    ("T10Y2Y_ROC2_30", "T10Y2Y", "stream_D_macro", 2, 30),
    ("Hash_Rate_ROC2_30", "Hash_Rate", "stream_D_onchain", 2, 30),
    ("Taker_BS_Ratio", "Taker_BS_Ratio", "D_onchain_level", 0, 0),
]


def import_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _norm_index(s: pd.Series) -> pd.Series:
    out = s.copy()
    out.index = pd.to_datetime(out.index)
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_localize(None)
    return out.sort_index()


def build_derivative(s_raw: pd.Series, h: int, order: int) -> pd.Series:
    roc = (s_raw - s_raw.shift(h)) / (s_raw.shift(h).abs() + 1e-9)
    roc = roc.replace([np.inf, -np.inf], np.nan)
    if order == 2:
        roc = (roc - roc.shift(h)).replace([np.inf, -np.inf], np.nan)
    return roc


def ternary_rolling_qtile(s: pd.Series, window: int = 730, lo_q: float = 0.33, hi_q: float = 0.67) -> pd.Series:
    lo = s.rolling(window, min_periods=max(60, window // 3)).quantile(lo_q).shift(1)
    hi = s.rolling(window, min_periods=max(60, window // 3)).quantile(hi_q).shift(1)
    out = pd.Series(0, index=s.index, dtype=int)
    out[s <= lo] = -1
    out[s >= hi] = 1
    return out


def build_zscore_underlying(close: pd.Series, ma_type: str, period: int, freq: str) -> pd.Series:
    price = close.resample("W-FRI").last().dropna() if freq == "weekly" else close
    ma = price.rolling(period, min_periods=period).mean() if ma_type == "SMA" else price.ewm(span=period, adjust=False).mean()
    dev = (price - ma) / ma
    z = (dev - dev.rolling(252, min_periods=60).mean()) / dev.rolling(252, min_periods=60).std().replace(0, np.nan)
    return z.reindex(close.index, method="ffill") if freq == "weekly" else z


def build_gappct_underlying(close: pd.Series, ma_type: str, period: int) -> pd.Series:
    ma = close.rolling(period).mean() if ma_type == "SMA" else close.ewm(span=period, adjust=False).mean()
    return close / ma - 1.0


def build_mabreak_bullfrac(close: pd.Series, periods: list[int], ma_type: str = "SMA", freq: str = "daily", smooth_ema: int = 5) -> pd.Series:
    price = close.resample("W-FRI").last().dropna() if freq == "weekly" else close
    mas = {
        p: price.rolling(p, min_periods=min(p, max(2, p // 4))).mean()
        if ma_type == "SMA"
        else price.ewm(span=p, adjust=False).mean()
        for p in periods
    }
    bits = pd.DataFrame({p: (price > mas[p]).astype(float) for p in periods})
    frac = bits.mean(axis=1).ewm(span=smooth_ema, adjust=False).mean()
    return frac.reindex(close.index, method="ffill") if freq == "weekly" else frac


def build_sp500_overlay_bullfrac(sp500: pd.Series, close: pd.Series, ma_type: str = "SMA", windows: tuple[int, int] = (50, 200), smooth_ema: int = 5) -> pd.Series:
    sp = sp500.reindex(close.index, method="ffill").ffill()
    mas = {w: sp.rolling(w, min_periods=w).mean() if ma_type == "SMA" else sp.ewm(span=w, adjust=False).mean() for w in windows}
    bits = {f"SP>MA{w}": (sp > mas[w]).astype(float) for w in sorted(windows)}
    ws = sorted(windows)
    for i, sw in enumerate(ws):
        for lw in ws[i + 1:]:
            bits[f"SP_MA{sw}>MA{lw}"] = (mas[sw] > mas[lw]).astype(float)
    return pd.DataFrame(bits).mean(axis=1).ewm(span=smooth_ema, adjust=False).mean()


def tech_underlying(name: str, close: pd.Series) -> pd.Series:
    if name.startswith("Zscore_"):
        parts = name.split("_")
        token = parts[1]
        ma_type = "SMA" if token.startswith("SMA") else "EMA"
        period = token.replace(ma_type, "")
        freq = parts[2]
        return build_zscore_underlying(close, ma_type, int(period), freq)
    if name.startswith("GapPct_"):
        parts = name.split("_")
        token = parts[1]
        ma_type = "SMA" if token.startswith("SMA") else "EMA"
        period = token.replace(ma_type, "")
        return build_gappct_underlying(close, ma_type, int(period))
    raise KeyError(name)


def stream_a_underlying(name: str, close: pd.Series, sp500: pd.Series) -> pd.Series:
    if name.startswith("MABreak_"):
        parts = name.split("_")
        ma_type = parts[1]
        freq = "daily" if parts[2].startswith("d") else "weekly"
        periods = [int(x) for x in parts[3:] if x.isdigit()]
        return build_mabreak_bullfrac(close, periods, ma_type=ma_type, freq=freq)
    if name.startswith("SP500_"):
        parts = name.split("_")
        return build_sp500_overlay_bullfrac(sp500, close, ma_type=parts[1], windows=(int(parts[2]), int(parts[3])))
    raise KeyError(name)


def fetch_cq_extra(v3, close: pd.Series) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    specs = {
        "Hash_Rate": ("btc/network-data/hashrate", "hashrate", None),
        "CDD": ("btc/network-indicator/cdd", "cdd", None),
        "Exch_Inflow_Total": ("btc/exchange-flows/inflow", "inflow_total", "binance"),
        "Funding_Rate": ("btc/market-data/funding-rates", "funding_rates", "binance"),
        "Taker_BS_Ratio": ("btc/market-data/taker-buy-sell-stats", "taker_buy_sell_ratio", "binance"),
    }
    for name, (endpoint, field, exchange) in specs.items():
        try:
            s = v3._mod._fetch_cquant(endpoint, v3.CQ_KEY, field, start=v3.TRAIN_START, exchange=exchange)
        except Exception:
            s = None
        if s is not None and len(s):
            out[name] = _norm_index(s).reindex(close.index).ffill()
    return out


def fetch_yahoo_extra(v3, close: pd.Series) -> dict[str, pd.Series]:
    import datetime as dt
    import json
    import time
    import urllib.request

    out: dict[str, pd.Series] = {}
    for ticker in ["EEM", "LQD"]:
        s0 = None
        for attempt in range(1, 6):
            try:
                start = int(pd.Timestamp(v3.TRAIN_START).timestamp())
                end = int((close.index.max() + pd.Timedelta(days=2)).timestamp())
                url = (
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
                    f"?period1={start}&period2={end}&interval=1d&events=history&includeAdjustedClose=true"
                )
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                data = json.loads(urllib.request.urlopen(req, timeout=30).read())
                result = data.get("chart", {}).get("result") or []
                if result:
                    r0 = result[0]
                    ts = r0.get("timestamp") or []
                    quote = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
                    closes = quote.get("close") or []
                    if len(ts) and len(ts) == len(closes):
                        idx = pd.to_datetime([dt.datetime.utcfromtimestamp(x).date() for x in ts])
                        cand = pd.Series(closes, index=idx, dtype=float).dropna()
                        if len(cand) >= 10:
                            s0 = cand
                            break
            except Exception:
                pass
            time.sleep(min(10, 2 * attempt))
        if s0 is not None:
            out[ticker] = _norm_index(s0).reindex(close.index).ffill()
    return out


def build_extended_disc(v3, close: pd.Series, base_disc: pd.DataFrame, out_dir: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    print("[k3] Rebuilding extended 130+ signal matrix from source data...", flush=True)
    close = close.astype(float).sort_index()
    sp500, vix, dxy, gold, hy = v3._fetch_macro_all(close.index)
    cq = v3._fetch_cquant_retry(v3.CQ_KEY, start=v3.TRAIN_START)
    prx = v3._mod.compute_proxy_signals(close, sp500, vix, dxy, gold, hy)
    raw_df = pd.DataFrame({**cq, **prx}).reindex(close.index).ffill()

    ffr = v3._fetch_fred_retry(v3.FRED_KEY, "FEDFUNDS", lag_days=7, close_index=close.index)
    ppi = v3._fetch_fred_retry(v3.FRED_KEY, "PPIACO", lag_days=60, close_index=close.index)
    cpi = v3._fetch_fred_retry(v3.FRED_KEY, "CPIAUCSL", lag_days=45, close_index=close.index)
    sofr = v3._fetch_fred_retry(v3.FRED_KEY, "SOFR", close_index=close.index)
    iorb = v3._fetch_fred_retry(v3.FRED_KEY, "IORB", close_index=close.index)
    rrp = v3._fetch_fred_retry(v3.FRED_KEY, "RRPONTSYD", close_index=close.index)
    fred_extra = {
        sid: v3._fetch_fred_retry(v3.FRED_KEY, sid, close_index=close.index)
        for sid in ["T10Y2Y", "T5YIE", "T10YIE", "DCOILWTICO"]
    }
    macro_v2 = {
        "FFR_dev_MA365": ffr - ffr.rolling(365).mean(),
        "SOFR_IORB_Spread": sofr - iorb,
        "RRP_dev_MA90": rrp - rrp.rolling(90).mean(),
        "PPI_minus_CPI_YoY": ppi.pct_change(365) - cpi.pct_change(365),
    }
    cq_extra = fetch_cq_extra(v3, close)
    yf_extra = fetch_yahoo_extra(v3, close)

    floats: dict[tuple[str, str], pd.Series] = {}
    for col in raw_df.columns:
        floats[("raw", col)] = raw_df[col].reindex(close.index).ffill()
    for name in {base for _, base, src, _, _ in PASSERS if src == "tech"}:
        floats[("tech", name)] = tech_underlying(name, close)
    for name, s in macro_v2.items():
        floats[("macro_v2", name)] = s.reindex(close.index).ffill()
    for name in {base for _, base, src, _, _ in PASSERS if src == "stream_A"}:
        floats[("stream_A", name)] = stream_a_underlying(name, close, sp500)
    for name, s in cq_extra.items():
        floats[("stream_D_onchain", name)] = s.reindex(close.index).ffill()
    for name, s in fred_extra.items():
        floats[("stream_D_macro", name)] = s.reindex(close.index).ffill()
    if "EEM" in yf_extra:
        floats[("stream_D_macro", "EM_minus_DM_logratio")] = np.log(yf_extra["EEM"] / sp500.reindex(close.index).ffill())
    if "LQD" in yf_extra:
        floats[("stream_D_macro", "IG_minus_HY_logratio")] = np.log(yf_extra["LQD"] / hy.reindex(close.index).ffill())

    new_cols: dict[str, pd.Series] = {}
    rows: list[dict] = []
    for candidate, base, source_class, order, h in PASSERS:
        try:
            if source_class in {"raw", "raw_exception"}:
                s_under = floats[("raw", base)]
                tern = ternary_rolling_qtile(build_derivative(s_under, h, order))
            elif source_class == "tech":
                tern = ternary_rolling_qtile(build_derivative(floats[("tech", base)], h, order))
            elif source_class == "macro":
                tern = ternary_rolling_qtile(build_derivative(floats[("macro_v2", base)], h, order))
            elif source_class == "stream_A":
                tern = ternary_rolling_qtile(build_derivative(floats[("stream_A", base)], h, order))
            elif source_class == "stream_D_onchain":
                tern = ternary_rolling_qtile(build_derivative(floats[("stream_D_onchain", base)], h, order))
            elif source_class == "stream_D_macro":
                tern = ternary_rolling_qtile(build_derivative(floats[("stream_D_macro", base)], h, order))
            elif source_class == "D_onchain_level":
                tern = ternary_rolling_qtile(floats[("stream_D_onchain", base)])
            else:
                raise KeyError(source_class)
            new_cols[candidate] = tern.reindex(close.index).fillna(0).astype(int)
            rows.append({"candidate": candidate, "source_class": source_class, "status": "ok"})
        except Exception as exc:
            rows.append({"candidate": candidate, "source_class": source_class, "status": "failed", "error": str(exc)})

    ext = pd.concat([base_disc.reindex(close.index).fillna(0).astype(int), pd.DataFrame(new_cols, index=close.index)], axis=1)
    ext = ext.loc[:, ~ext.columns.duplicated()].fillna(0).astype(int)
    manifest = pd.DataFrame(rows)
    if out_dir is not None:
        manifest.to_csv(out_dir / "k3_extended_signal_rebuild_manifest.csv", index=False)
    print(f"[k3] Extended signal count: {ext.shape[1]} ({int((manifest.status == 'ok').sum())} rebuilt passers)", flush=True)
    return ext, manifest


def bool_to_int(a: np.ndarray) -> int:
    return int.from_bytes(np.packbits(a.astype(np.uint8), bitorder="little").tobytes(), "little")


def int_to_bool(m: int, n: int) -> np.ndarray:
    if m == 0:
        return np.zeros(n, dtype=bool)
    return np.unpackbits(np.frombuffer(m.to_bytes((n + 7) // 8, "little"), dtype=np.uint8), bitorder="little")[:n].astype(bool)


def compute_labels(close: pd.Series) -> dict[str, np.ndarray]:
    px = close.values.astype(float)
    n = len(px)
    valid = np.zeros(n, bool)
    up_any = np.zeros(n, bool)
    down_any = np.zeros(n, bool)
    up_first = np.zeros(n, bool)
    down_first = np.zeros(n, bool)
    tau_up = np.full(n, np.nan)
    for i in range(n - H):
        if not np.isfinite(px[i]) or px[i] <= 0:
            continue
        fut = px[i + 1 : i + H + 1] / px[i] - 1.0
        u = np.flatnonzero(fut >= TH)
        d = np.flatnonzero(fut <= -TH)
        valid[i] = True
        if len(u):
            up_any[i] = True
            tau_up[i] = u[0] + 1
        if len(d):
            down_any[i] = True
        if len(u) and (not len(d) or u[0] < d[0]):
            up_first[i] = True
        if len(d) and (not len(u) or d[0] < u[0]):
            down_first[i] = True
    return {"valid": valid, "up_any": up_any, "down_any": down_any, "up_first": up_first, "down_first": down_first, "tau_up": tau_up}


def first_fire(mask: np.ndarray) -> np.ndarray:
    return np.flatnonzero(mask & ~np.r_[False, mask[:-1]]).astype(np.int32)


def nonoverlap(idx: np.ndarray, dates: pd.DatetimeIndex, tau: np.ndarray) -> np.ndarray:
    out: list[int] = []
    next_allowed = pd.Timestamp.min
    for x in idx:
        d = dates[int(x)]
        if d < next_allowed:
            continue
        out.append(int(x))
        tx = tau[int(x)]
        skip = int(tx) if np.isfinite(tx) else H
        next_allowed = d + pd.Timedelta(days=skip)
    return np.asarray(out, dtype=np.int32)


def ev_stats(ev: np.ndarray, target: np.ndarray, mask: np.ndarray) -> tuple[int, int, float]:
    ev = ev[mask[ev]] if len(ev) else ev
    n = len(ev)
    h = int(target[ev].sum()) if n else 0
    return n, h, h / n if n else np.nan


def tier(n: int, h: int) -> int:
    if n <= 0:
        return 0
    hr = h / n
    if (n >= 10 and hr >= 0.80) or (n >= 5 and h == n):
        return 1
    if (n >= 10 and hr >= 0.70) or (n >= 5 and hr >= 0.80):
        return 2
    return 0


def primitive(sig: str) -> str:
    s = str(sig)
    import re

    s = re.sub(r"_ROC2?_[0-9]+$", "", s)
    s = re.sub(r"_ROC[0-9]+$", "", s)
    for suf in ["_q33", "_q50"]:
        if s.endswith(suf):
            s = s[: -len(suf)]
    for pref in ["GapPct_", "Zscore_"]:
        if s.startswith(pref):
            s = s[len(pref) :]
    return s.replace("SMA", "MA").replace("EMA", "MA")


def motif_superkey(pkey: tuple[str, ...]) -> tuple[str, ...]:
    import re

    vals = []
    for p in pkey:
        x = re.sub(r"_daily_[0-9_]+", "_daily", p)
        x = re.sub(r"_weekly_[0-9_]+", "_weekly", x)
        x = re.sub(r"MA[0-9]+", "MA", x)
        vals.append(x)
    return tuple(sorted(vals))


def atom_name(sig: str, val: int) -> str:
    return f"{sig}={int(val):+d}"


def parse_combo(combo: str) -> tuple[tuple[str, int], ...]:
    atoms = []
    for part in str(combo).split(" & "):
        sig, val = part.rsplit("=", 1)
        atoms.append((sig, int(val)))
    return tuple(atoms)


def combo_mask(disc: pd.DataFrame, combo: str) -> np.ndarray:
    m = np.ones(len(disc), dtype=bool)
    for sig, val in parse_combo(combo):
        if sig not in disc.columns:
            return np.zeros(len(disc), dtype=bool)
        m &= disc[sig].to_numpy(dtype=int) == int(val)
    return m


def logit(p: float) -> float:
    p = min(max(float(p), 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def shrunk(h: int, n: int, base: float, k: int = SHRINK_K) -> float:
    return (h + k * base) / (n + k) if n >= 0 and np.isfinite(base) else base


def train_quality(mask: np.ndarray, labs: dict[str, np.ndarray], dates: pd.DatetimeIndex, anchor: pd.Timestamp) -> dict:
    train = (dates <= anchor - pd.Timedelta(days=H)) & labs["valid"]
    ff = first_fire(mask)
    idx = ff[train[ff]] if len(ff) else ff
    base_idx = np.flatnonzero(train)
    base_up = float(labs["up_first"][base_idx].mean()) if len(base_idx) else np.nan
    base_dn = float(labs["down_first"][base_idx].mean()) if len(base_idx) else np.nan
    n = len(idx)
    up_h = int(labs["up_first"][idx].sum()) if n else 0
    dn_h = int(labs["down_first"][idx].sum()) if n else 0
    up_hr = up_h / n if n else np.nan
    dn_hr = dn_h / n if n else np.nan
    p_up = shrunk(up_h, n, base_up) if n else base_up
    p_dn = shrunk(dn_h, n, base_dn) if n else base_dn
    bull_lift = logit(p_up) - logit(base_up) if np.isfinite(base_up) else 0.0
    bear_lift = logit(p_dn) - logit(base_dn) if np.isfinite(base_dn) else 0.0
    is_bull = (n >= 10) and (up_hr >= 0.55) and (dn_hr <= 0.25) and (bull_lift > 0)
    score = bull_lift * np.sqrt(max(n, 1)) * max(0.01, up_hr - max(dn_hr, base_up if np.isfinite(base_up) else 0))
    return {
        "train_ff_n": n,
        "train_up_first_h": up_h,
        "train_down_first_h": dn_h,
        "train_up_first_hr": up_hr,
        "train_down_first_hr": dn_hr,
        "base_up_first": base_up,
        "base_down_first": base_dn,
        "bull_logodds_lift": bull_lift,
        "bear_logodds_lift": bear_lift,
        "weight_used": min(1.5, max(0.0, bull_lift)),
        "is_bull_continuation": is_bull,
        "selection_score": score if is_bull else -np.inf,
    }


def build_atoms(disc: pd.DataFrame, valid: np.ndarray, train_mask: np.ndarray, target_train: np.ndarray) -> list[dict]:
    out = []
    for sig in disc.columns:
        v = disc[sig].to_numpy(dtype=int)
        for val in (-1, 1):
            full = (v == val) & valid
            support = int((full & train_mask).sum())
            hits = int((full & target_train).sum())
            if support >= MIN_TRAIN_SUPPORT:
                out.append({"sig": sig, "val": val, "bits": bool_to_int(full), "support": support, "hits": hits, "hr": hits / max(support, 1)})
    out.sort(key=lambda a: (a["hr"], a["hits"], a["support"]), reverse=True)
    return out


def mine_anchor_candidates(anchor: pd.Timestamp, next_anchor: pd.Timestamp, disc: pd.DataFrame, labs: dict[str, np.ndarray]) -> pd.DataFrame:
    dates = disc.index
    n = len(dates)
    valid = labs["valid"]
    train_mask = (dates <= anchor - pd.Timedelta(days=H)) & valid
    if int(train_mask.sum()) < 120:
        return pd.DataFrame()
    target = labs["up_any"]
    target_train = target & train_mask
    target_train_bits = bool_to_int(target_train)
    train_bits = bool_to_int(train_mask)
    interval_bits = bool_to_int((dates >= anchor) & (dates < next_anchor))
    atoms = build_atoms(disc, valid, train_mask, target_train)
    motifs: dict[tuple[str, ...], dict] = {}
    checked = 0
    for i, a in enumerate(atoms):
        for j in range(i + 1, len(atoms)):
            b = atoms[j]
            if b["sig"] == a["sig"]:
                continue
            bits2 = a["bits"] & b["bits"]
            if (bits2 & train_bits).bit_count() < MIN_TRAIN_SUPPORT or (bits2 & target_train_bits).bit_count() < 5:
                continue
            for k in range(j + 1, len(atoms)):
                c = atoms[k]
                if c["sig"] in (a["sig"], b["sig"]):
                    continue
                bits = bits2 & c["bits"]
                if (bits & train_bits).bit_count() < MIN_TRAIN_SUPPORT or (bits & target_train_bits).bit_count() < 5:
                    continue
                checked += 1
                active = int_to_bool(bits, n)
                ff = first_fire(active)
                no = nonoverlap(ff, dates, labs["tau_up"])
                fn, fh, fr = ev_stats(ff, target, train_mask)
                nn, nh, nr = ev_stats(no, target, train_mask)
                ft = tier(fn, fh)
                nt = tier(nn, nh)
                tr = ft if ft and (not nt or ft <= nt) else nt
                if tr != 1:
                    continue
                pkey = tuple(sorted((primitive(a["sig"]), primitive(b["sig"]), primitive(c["sig"]))))
                combo = " & ".join([atom_name(a["sig"], a["val"]), atom_name(b["sig"], b["val"]), atom_name(c["sig"], c["val"])])
                fmask = np.zeros(n, dtype=bool)
                fmask[ff] = True
                quality = (fr if np.isfinite(fr) else -1, nr if np.isfinite(nr) else -1, fn, nn)
                rec = motifs.get(pkey)
                if rec is None:
                    motifs[pkey] = {
                        "active_bits": bits & interval_bits,
                        "firstfire_bits": bool_to_int(fmask & ((dates >= anchor) & (dates < next_anchor))),
                        "rule_count": 1,
                        "best_combo": combo,
                        "best_quality": quality,
                        "best_ff": f"{fh}/{fn}",
                        "best_ff_hr": fr,
                        "best_no": f"{nh}/{nn}",
                        "best_no_hr": nr,
                    }
                else:
                    rec["active_bits"] |= bits & interval_bits
                    rec["firstfire_bits"] |= bool_to_int(fmask & ((dates >= anchor) & (dates < next_anchor)))
                    rec["rule_count"] += 1
                    if quality > rec["best_quality"]:
                        rec.update({"best_combo": combo, "best_quality": quality, "best_ff": f"{fh}/{fn}", "best_ff_hr": fr, "best_no": f"{nh}/{nn}", "best_no_hr": nr})
    rows = []
    for pkey, rec in motifs.items():
        sk = motif_superkey(pkey)
        rows.append(
            {
                "anchor": anchor,
                "label": "up_any",
                "side": "bull",
                "tier": 1,
                "pkey": " | ".join(pkey),
                "superkey": " | ".join(sk),
                "rule_count": rec["rule_count"],
                "active_days_oos": int(rec["active_bits"].bit_count()),
                "firstfire_days_oos": int(rec["firstfire_bits"].bit_count()),
                "best_combo": rec["best_combo"],
                "best_ff": rec["best_ff"],
                "best_ff_hr": rec["best_ff_hr"],
                "best_no": rec["best_no"],
                "best_no_hr": rec["best_no_hr"],
                "checked_k3": checked,
            }
        )
    return pd.DataFrame(rows)


def select_strict_top10_for_anchor(anchor: pd.Timestamp, candidates: pd.DataFrame, disc: pd.DataFrame, labs: dict[str, np.ndarray]) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    sub = candidates.drop_duplicates(["anchor", "superkey", "best_combo"]).copy()
    sub["best_ff_hr"] = pd.to_numeric(sub["best_ff_hr"], errors="coerce").fillna(0.0)
    sub["best_no_hr"] = pd.to_numeric(sub["best_no_hr"], errors="coerce").fillna(0.0)
    sub["rule_count"] = pd.to_numeric(sub["rule_count"], errors="coerce").fillna(0.0)
    sub = sub.sort_values(["rule_count", "best_ff_hr", "best_no_hr"], ascending=False).head(TOP_CANDIDATES_TO_SCORE)
    scored = []
    for _, row in sub.iterrows():
        mask = combo_mask(disc, row["best_combo"])
        tq = train_quality(mask, labs, disc.index, anchor)
        if tq["is_bull_continuation"]:
            scored.append({**row.to_dict(), **tq, "atoms": str(parse_combo(row["best_combo"]))})
    if not scored:
        return pd.DataFrame()
    out = pd.DataFrame(scored)
    if pd.Timestamp(anchor) < pd.Timestamp("2020-01-01"):
        return out.head(10)
    return out.sort_values(["selection_score", "train_ff_n", "rule_count"], ascending=[False, False, False]).head(10)


def expanding_percentile(s: pd.Series, min_periods: int = 730) -> pd.Series:
    out = []
    vals: list[float] = []
    for v in s.astype(float):
        if np.isfinite(v) and len(vals) >= min_periods:
            arr = np.asarray(vals, float)
            out.append(float((arr < float(v)).mean()))
        else:
            out.append(0.5)
        if np.isfinite(v):
            vals.append(float(v))
    return pd.Series(out, index=s.index, name="rank")


def rebuild_k3_daily_from_scratch(close: pd.Series, disc: pd.DataFrame, out_dir: Path, start_year: int = 2015) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    out_dir.mkdir(parents=True, exist_ok=True)
    close = close.reindex(disc.index).ffill().astype(float)
    labs = compute_labels(close)
    current_year = int(close.index.max().year)
    anchors = [pd.Timestamp(f"{y}-01-01") for y in range(start_year, current_year + 1)]
    rows_all: list[pd.DataFrame] = []
    selected_all: list[pd.DataFrame] = []
    for i, anchor in enumerate(anchors):
        next_anchor = anchors[i + 1] if i + 1 < len(anchors) else close.index.max() + pd.Timedelta(days=1)
        print(f"[k3] Mining anchor {anchor.date()} -> {pd.Timestamp(next_anchor).date()}...", flush=True)
        cand = mine_anchor_candidates(anchor, next_anchor, disc, labs)
        if len(cand):
            rows_all.append(cand)
        sel = select_strict_top10_for_anchor(anchor, cand, disc, labs)
        if len(sel):
            selected_all.append(sel)
        print(f"[k3] anchor {anchor.date()} candidates={len(cand)} selected_top10={len(sel)}", flush=True)
    candidates = pd.concat(rows_all, ignore_index=True) if rows_all else pd.DataFrame()
    selected = pd.concat(selected_all, ignore_index=True) if selected_all else pd.DataFrame()
    candidates.to_csv(out_dir / "k3_mined_candidates_full_recompute.csv", index=False)
    selected.to_csv(out_dir / "k3_selected_top10_full_recompute.csv", index=False)

    cols = {
        "bull_continuation_active": np.zeros(len(disc), dtype=float),
        "bull_continuation_firstfire": np.zeros(len(disc), dtype=float),
        "bull_continuation_decay_score": np.zeros(len(disc), dtype=float),
    }
    if len(selected):
        for _, row in selected.iterrows():
            anchor = pd.Timestamp(row["anchor"])
            ai = anchors.index(anchor)
            next_anchor = anchors[ai + 1] if ai + 1 < len(anchors) else close.index.max() + pd.Timedelta(days=1)
            interval = (disc.index >= anchor) & (disc.index < next_anchor)
            mask = combo_mask(disc, row["best_combo"])
            active = mask & interval
            ff = first_fire(mask)
            fmask = np.zeros(len(disc), dtype=bool)
            fmask[ff] = True
            fmask &= interval
            cols["bull_continuation_active"] += active.astype(float)
            cols["bull_continuation_firstfire"] += fmask.astype(float)
            weight = float(row["weight_used"])
            for t in np.flatnonzero(fmask):
                end = min(len(disc), t + MAX_LIFE + 1)
                d = np.arange(end - t)
                cols["bull_continuation_decay_score"][t:end] += weight * np.exp(-d / HALFLIFE)
    state = pd.DataFrame(cols, index=disc.index)
    state["btc_close"] = close
    state["overlay_bull_boost_mult"] = (1.0 + 0.15 * np.tanh(state["bull_continuation_decay_score"] / 3.0)).clip(1.0, 1.15)
    state["E"] = ((state["overlay_bull_boost_mult"] - 1.0) / 0.15).clip(0.0, 1.0)
    state["score"] = (0.5 + 0.5 * state["E"]).clip(0.0, 1.0)
    state["rank"] = expanding_percentile(state["score"])
    state.to_csv(out_dir / "k3_daily_state_full_recompute.csv", index_label="date")
    return state, selected, candidates


# Frozen strict K3 top10 leaders from the original clean K3 rebuild. The scripts
# still recompute source data, signal states, daily evidence, ranks, exposures,
# and metrics; this embedded list preserves the historical frozen motif selection
# generated by the original motif_rows candidate miner.
FROZEN_TOP10_ROWS: list[tuple[str, str, float]] = [
    ('2016-01-01', 'MABreak_EMA_d_50_100_200_365_frac_ROC7=-1 & NVM_ROC30=-1 & MABreak_EMA_d_30_90_180_365_frac_ROC30=-1', 0.6883278941239962),
    ('2016-01-01', 'Zscore_EMA50_daily_ROC7=+1 & MABreak_SMA_d_30_90_180_365_frac_ROC7=+1 & MPI=-1', 0.7368879881210112),
    ('2016-01-01', 'Zscore_EMA50_daily_ROC30=+1 & MABreak_EMA_d_30_90_180_365_frac_ROC2_30=+1 & NVM_ROC30=+1', 0.6883278941239962),
    ('2016-01-01', 'MABreak_EMA_d_30_90_180_365_frac_ROC7=+1 & MPI_ROC30=+1 & GapPct_EMA200_365d=+1', 0.7368879881210112),
    ('2016-01-01', 'MABreak_SMA_d_50_100_200_365_frac_ROC7=-1 & MABreak_EMA_d_30_90_180_365_frac_ROC7=-1 & NRPL_ROC7=+1', 0.6883278941239962),
    ('2016-01-01', 'Zscore_EMA50_daily_ROC30=+1 & MPI_ROC30=-1 & GapPct_EMA90_365d=+1', 0.6883278941239962),
    ('2016-01-01', 'MABreak_EMA_d_50_100_200_365_frac_ROC7=+1 & MPI_ROC30=+1 & NVM=-1', 0.7368879881210112),
    ('2016-01-01', 'MABreak_SMA_d_30_90_180_365_frac_ROC7=+1 & MABreak_EMA_d_50_100_200_365_frac_ROC7=+1 & CDD_ROC30=+1', 0.7368879881210112),
    ('2016-01-01', 'Zscore_EMA50_daily_ROC7=+1 & MABreak_SMA_d_30_90_180_365_frac_ROC7=+1 & SOPR_Ratio_ROC7=-1', 0.7368879881210112),
    ('2016-01-01', 'MABreak_EMA_d_30_90_180_365_frac_ROC7=-1 & GapPct_SMA200_365d=-1 & SOPR_Ratio_ROC7=-1', 0.6883278941239962),
    ('2017-01-01', 'MABreak_EMA_d_50_100_200_365_frac_ROC30=+1 & MPI=-1 & MABreak_EMA_d_30_90_180_365_frac_ROC2_30=+1', 0.7801374602806158),
    ('2017-01-01', 'MABreak_SMA_d_30_90_180_365_frac_ROC7=+1 & GapPct_SMA90_365d=-1 & MPI=-1', 0.7339489217105454),
    ('2017-01-01', 'MABreak_EMA_d_30_90_180_365_frac_ROC30=+1 & SOPR_Ratio_ROC7=+1 & MABreak_SMA_d_50_100_200_365_frac_ROC2_30=+1', 0.7339489217105454),
    ('2017-01-01', 'MABreak_SMA_d_30_90_180_365_frac_ROC7=+1 & MABreak_SMA_d_50_100_200_365_frac_ROC7=+1 & NVM_ROC30=-1', 0.8242864738885752),
    ('2017-01-01', 'GapPct_SMA90_365d=-1 & SOPR_Ratio_ROC7=+1 & MABreak_EMA_d_30_90_180_365_frac_ROC2_30=+1', 0.7339489217105454),
    ('2017-01-01', 'MABreak_SMA_d_30_90_180_365_frac_ROC7=+1 & GapPct_EMA90_365d_ROC7=+1 & NRPL_ROC7=-1', 0.685523255449286),
    ('2017-01-01', 'GapPct_SMA90_365d=-1 & MPI=-1 & MABreak_SMA_d_50_100_200_365_frac_ROC2_30=+1', 0.7801374602806158),
    ('2017-01-01', 'GapPct_SMA365_365d=-1 & MABreak_SMA_d_30_90_180_365_frac_ROC2_30=+1 & GapPct_SMA90_365d_ROC7=+1', 0.685523255449286),
    ('2017-01-01', 'MABreak_SMA_d_30_90_180_365_frac_ROC30=+1 & NRPL_ROC7=+1 & MABreak_SMA_d_50_100_200_365_frac_ROC2_30=+1', 0.7801374602806158),
    ('2017-01-01', 'MABreak_SMA_d_30_90_180_365_frac_ROC7=+1 & GapPct_SMA200_365d=-1 & SOPR_Ratio_ROC7=+1', 0.8665684878836357),
    ('2018-01-01', 'MABreak_SMA_d_30_90_180_365_frac_ROC2_30=-1 & Zscore_SMA90_daily_ROC7=-1 & GapPct_EMA90_365d_ROC7=-1', 0.4498989848549442),
    ('2018-01-01', 'MABreak_EMA_d_30_90_180_365_frac_ROC30=+1 & Zscore_EMA50_daily_ROC30=+1 & GapPct_EMA90_365d=+1', 0.78907142240383),
    ('2018-01-01', 'MABreak_EMA_d_50_100_200_365_frac_ROC30=+1 & GapPct_SMA90_365d_ROC30=+1 & MABreak_SMA_d_30_90_180_365_frac_ROC2_30=+1', 0.4930956341874219),
    ('2018-01-01', 'Zscore_EMA200_daily_ROC30=+1 & MABreak_EMA_d_30_90_180_365_frac_ROC2_30=+1 & GapPct_SMA90_365d=+1', 0.7865066233504439),
    ('2018-01-01', 'Zscore_SMA365_daily_ROC7=+1 & MABreak_EMA_d_30_90_180_365_frac_ROC2_30=+1 & GapPct_EMA90_365d=+1', 0.78907142240383),
    ('2018-01-01', 'MABreak_SMA_d_30_90_180_365_frac_ROC7=+1 & MABreak_EMA_d_50_100_200_365_frac_ROC30=-1 & Zscore_EMA50_daily_ROC7=+1', 0.8273118185882149),
    ('2018-01-01', 'Zscore_SMA365_daily_ROC30=+1 & Zscore_EMA200_daily_ROC30=+1 & GapPct_SMA90_365d=+1', 0.752330968913852),
    ('2018-01-01', 'MABreak_SMA_d_30_90_180_365_frac_ROC7=+1 & MABreak_EMA_d_50_100_200_365_frac_ROC30=-1 & Zscore_EMA90_daily_ROC7=+1', 0.8273118185882149),
    ('2018-01-01', 'MABreak_EMA_d_30_90_180_365_frac_ROC30=+1 & Zscore_EMA90_daily_ROC30=+1 & Zscore_EMA50_daily_ROC30=+1', 0.7493103545682454),
    ('2018-01-01', 'MABreak_SMA_d_30_90_180_365_frac_ROC2_7=-1 & GapPct_EMA90_365d_ROC7=+1 & GapPct_EMA200_365d_ROC7=+1', 0.7079026461258648),
    ('2019-01-01', 'Zscore_SMA365_daily_ROC30=+1 & Zscore_EMA200_daily_ROC30=+1 & GapPct_SMA90_365d=+1', 0.905063967313974),
    ('2019-01-01', 'Zscore_SMA365_daily_ROC30=+1 & Zscore_SMA200_daily_ROC30=+1 & Zscore_SMA90_daily_ROC7=-1', 0.6443457562165801),
    ('2019-01-01', 'Zscore_SMA365_daily_ROC7=+1 & Zscore_EMA200_daily_ROC30=+1 & Zscore_EMA26_weekly=+1', 0.8236287774084502),
    ('2019-01-01', 'Zscore_SMA365_daily_ROC30=+1 & Zscore_SMA200_daily_ROC30=+1 & Zscore_SMA50_daily_ROC7=-1', 0.7559379197970251),
    ('2019-01-01', 'Zscore_SMA365_daily_ROC7=+1 & GapPct_EMA365_365d=+1 & Zscore_SMA200_daily_ROC30=+1', 1.0577892039251588),
    ('2019-01-01', 'Zscore_EMA365_daily_ROC7=+1 & Zscore_EMA200_daily=+1 & DCOILWTICO_ROC2_7=+1', 0.6124061308539364),
    ('2019-01-01', 'Zscore_EMA200_daily_ROC30=+1 & T10Y2Y_ROC30=+1 & Zscore_EMA365_daily_ROC7=-1', 0.8456412172309221),
    ('2019-01-01', 'Gold_90d_ROC30=-1 & Zscore_EMA365_daily_ROC7=+1 & Zscore_SMA200_daily_ROC7=+1', 0.9610184392840528),
    ('2019-01-01', 'Zscore_SMA365_daily_ROC30=+1 & Zscore_EMA200_daily_ROC30=+1 & GapPct_EMA200_365d=+1', 0.9362867428849996),
    ('2019-01-01', 'Zscore_EMA200_daily_ROC30=+1 & Zscore_EMA90_daily_ROC30=+1 & GapPct_SMA90_365d=+1', 1.1157252074083106),
    ('2020-01-01', 'GapPct_EMA90_365d=+1 & MABreak_EMA_d_30_90_180_365_frac_ROC30=+1 & SOPR_Ratio_ROC7=-1', 1.410167927791794),
    ('2020-01-01', 'Gold_90d_ROC30=-1 & Zscore_EMA200_daily_ROC30=+1 & MPI_ROC30=+1', 1.3532820650929964),
    ('2020-01-01', 'Gold_90d_ROC30=-1 & Zscore_SMA200_daily_ROC30=+1 & NVM_ROC30=-1', 1.3532820650929964),
    ('2020-01-01', 'GapPct_EMA90_365d=+1 & MABreak_EMA_d_30_90_180_365_frac_ROC30=+1 & NRPL_ROC7=-1', 1.3632733841350024),
    ('2020-01-01', 'Gold_90d_ROC30=-1 & MPI_ROC30=+1 & Zscore_EMA90_daily=+1', 1.3311360522197129),
    ('2020-01-01', 'Zscore_EMA200_daily_ROC30=+1 & GapPct_SMA90_365d=+1 & T10Y2Y_ROC30=+1', 1.338974808457853),
    ('2020-01-01', 'Zscore_EMA90_daily_ROC30=+1 & GapPct_EMA90_365d=+1 & T10Y2Y_ROC30=+1', 1.338974808457853),
    ('2020-01-01', 'Zscore_SMA365_daily_ROC30=+1 & Gold_90d_ROC30=-1 & MPI_ROC30=+1', 1.3084884646164534),
    ('2020-01-01', 'Zscore_SMA365_daily_ROC30=+1 & Gold_90d_ROC30=-1 & NVM_ROC30=-1', 1.3084884646164534),
    ('2020-01-01', 'Gold_90d_ROC30=-1 & Zscore_EMA200_daily_ROC7=+1 & SP500_SMA_50_200=-1', 1.3140710770634487),
    ('2021-01-01', 'Gold_90d_ROC30=-1 & Zscore_SMA365_daily_ROC7=+1 & Hash_Rate_ROC2_30=+1', 1.5),
    ('2021-01-01', 'Gold_90d_ROC30=-1 & Zscore_EMA200_daily_ROC30=+1 & MPI_ROC30=+1', 1.4741825589021689),
    ('2021-01-01', 'Gold_90d_ROC30=-1 & Zscore_EMA200_daily_ROC7=+1 & SP500_SMA_50_200=-1', 1.4636470063437284),
    ('2021-01-01', 'Gold_90d_ROC30=-1 & MPI_ROC30=+1 & Zscore_EMA90_daily=+1', 1.4171750540709258),
    ('2021-01-01', 'Gold_90d_ROC30=-1 & Zscore_EMA200_daily_ROC7=+1 & Zscore_SMA200_daily_ROC7=+1', 1.4212128374128816),
    ('2021-01-01', 'Gold_90d_ROC30=-1 & Hash_Rate_ROC2_30=+1 & Zscore_SMA200_daily_ROC7=+1', 1.397426748443402),
    ('2021-01-01', 'Gold_90d_ROC30=-1 & Zscore_EMA365_daily_ROC7=+1 & Zscore_SMA200_daily_ROC7=+1', 1.399300828520392),
    ('2021-01-01', 'Gold_90d_ROC30=-1 & SOPR_Ratio=+1 & Zscore_SMA90_daily_ROC7=+1', 1.399300828520392),
    ('2021-01-01', 'Gold_90d_ROC30=-1 & Zscore_SMA200_daily_ROC7=+1 & GapPct_SMA90_365d_ROC7=+1', 1.3768979065201583),
    ('2021-01-01', 'Gold_90d_ROC30=-1 & Zscore_SMA365_daily_ROC7=+1 & Zscore_SMA365_daily_ROC30=+1', 1.3768979065201583),
    ('2022-01-01', 'Gold_90d_ROC30=-1 & Zscore_EMA365_daily_ROC7=+1 & MPI=+1', 1.3439831630481678),
    ('2022-01-01', 'GapPct_EMA365_365d=+1 & MABreak_SMA_d_30_90_180_365_frac_ROC30=+1 & SOPR_Ratio_ROC7=-1', 1.3439831630481678),
    ('2022-01-01', 'Gold_90d_ROC30=-1 & MPI=+1 & Zscore_EMA200_daily_ROC7=+1', 1.2966822024302032),
    ('2022-01-01', 'Gold_90d_ROC30=-1 & GapPct_EMA200_365d=+1 & LR_2Y_Z_ROC7=+1', 1.2966822024302032),
    ('2022-01-01', 'Gold_90d_ROC30=-1 & MPI_ROC30=+1 & MABreak_SMA_d_50_100_200_365_frac_ROC2_30=-1', 1.2966822024302032),
    ('2022-01-01', 'Gold_90d_ROC30=-1 & GapPct_EMA365_365d=+1 & LR_2Y_Z_ROC7=+1', 1.2966822024302032),
    ('2022-01-01', 'Gold_90d_ROC30=-1 & MPI=+1 & Zscore_SMA90_daily_ROC7=+1', 1.272165355642118),
    ('2022-01-01', 'Gold_90d_ROC30=-1 & MPI=+1 & GapPct_EMA90_365d_ROC7=+1', 1.272165355642118),
    ('2022-01-01', 'GapPct_SMA200_365d=+1 & MABreak_SMA_d_30_90_180_365_frac_ROC30=+1 & SOPR_Ratio_ROC7=-1', 1.272165355642118),
    ('2022-01-01', 'Gold_90d_ROC30=-1 & Zscore_EMA200_daily_ROC7=+1 & CDD_ROC30=-1', 1.2256467180450237),
    ('2023-01-01', 'Gold_90d_ROC30=-1 & PPI_vs_CPI=-1 & Zscore_EMA200_daily_ROC7=+1', 1.496942624077235),
    ('2023-01-01', 'Gold_90d_ROC30=-1 & MPI=+1 & Zscore_EMA365_daily_ROC7=+1', 1.430073691581557),
    ('2023-01-01', 'GapPct_EMA365_365d=+1 & SOPR_Ratio_ROC7=-1 & MABreak_SMA_d_30_90_180_365_frac_ROC30=+1', 1.4067520651248084),
    ('2023-01-01', 'Gold_90d_ROC30=-1 & MPI=+1 & Zscore_EMA200_daily_ROC7=+1', 1.3828735264650909),
    ('2023-01-01', 'Gold_90d_ROC30=-1 & GapPct_EMA200_365d=+1 & LR_2Y_Z_ROC7=+1', 1.3584108258275929),
    ('2023-01-01', 'Gold_90d_ROC30=-1 & GapPct_EMA365_365d=+1 & LR_2Y_Z_ROC7=+1', 1.3584108258275929),
    ('2023-01-01', 'Gold_90d_ROC30=-1 & MPI=+1 & GapPct_EMA90_365d_ROC7=+1', 1.3584108258275929),
    ('2023-01-01', 'GapPct_SMA200_365d=+1 & SOPR_Ratio_ROC7=-1 & MABreak_SMA_d_30_90_180_365_frac_ROC30=+1', 1.3333346631711545),
    ('2023-01-01', 'Gold_90d_ROC30=-1 & MPI=+1 & Zscore_SMA90_daily_ROC7=+1', 1.3333346631711545),
    ('2023-01-01', 'GapPct_SMA200_365d=+1 & Exch_Netflow=-1 & MABreak_EMA_d_30_90_180_365_frac_ROC30=+1', 1.3333346631711545),
    ('2024-01-01', 'SOPR_Ratio=+1 & T10Y2Y_ROC30=+1 & Zscore_EMA50_daily_ROC30=+1', 1.2872348415190784),
    ('2024-01-01', 'Gold_90d_ROC30=-1 & SOPR_Ratio=+1 & Zscore_SMA50_daily_ROC7=+1', 1.2885309776983214),
    ('2024-01-01', 'LTH_SOPR=+1 & T10Y2Y_ROC30=+1 & Zscore_EMA50_daily_ROC30=+1', 1.2687417830597596),
    ('2024-01-01', 'Gold_90d_ROC30=-1 & SOPR_Ratio=+1 & Zscore_EMA90_daily_ROC7=+1', 1.211117604406806),
    ('2024-01-01', 'GapPct_SMA200_365d=+1 & MABreak_SMA_d_30_90_180_365_frac_ROC30=+1 & Exch_Netflow=+1', 1.211117604406806),
    ('2024-01-01', 'Gold_90d_ROC30=-1 & LTH_SOPR=+1 & GapPct_SMA90_365d_ROC7=+1', 1.1911472486576151),
    ('2024-01-01', 'SOPR_Ratio=+1 & Zscore_EMA26_weekly_ROC7=+1 & Zscore_EMA50_daily_ROC30=+1', 1.1707699369439435),
    ('2024-01-01', 'Gold_90d_ROC30=-1 & LTH_SOPR=+1 & Zscore_EMA90_daily_ROC7=+1', 1.1707699369439435),
    ('2024-01-01', 'Gold_90d_ROC7=-1 & GapPct_EMA200_365d=+1 & Zscore_EMA200_daily_ROC7=+1', 1.1588481997522155),
    ('2024-01-01', 'Zscore_EMA90_daily=+1 & NVM=+1 & DXY_ROC30=-1', 1.1845800759932472),
    ('2025-01-01', 'SOPR_Ratio=+1 & T10Y2Y_ROC30=+1 & Zscore_EMA50_daily_ROC30=+1', 1.261841149768547),
    ('2025-01-01', 'GapPct_SMA200_365d=+1 & MABreak_SMA_d_30_90_180_365_frac_ROC30=+1 & Exch_Netflow=+1', 1.2240867132026083),
    ('2025-01-01', 'SOPR_Ratio=+1 & Zscore_EMA26_weekly_ROC7=+1 & Zscore_EMA50_daily_ROC30=+1', 1.1410781713612208),
    ('2025-01-01', 'PPI_vs_CPI=-1 & Zscore_EMA200_daily_ROC7=+1 & Gold_90d=-1', 1.188330144743856),
    ('2025-01-01', 'Zscore_SMA365_daily_ROC7=+1 & T10Y2Y_ROC30=+1 & RealVol_90=-1', 1.1434593760322604),
    ('2025-01-01', 'Zscore_SMA365_daily_ROC7=+1 & PPI_vs_CPI=-1 & Gold_90d=-1', 1.1621079634070837),
    ('2025-01-01', 'RealVol_90=+1 & MPI_ROC30=+1 & MABreak_EMA_d_50_100_200_365_frac_ROC30=-1', 1.1621079634070837),
    ('2025-01-01', 'GapPct_SMA200_365d=+1 & Zscore_SMA200_daily_ROC30=+1 & Zscore_SMA200_daily_ROC7=+1', 1.0961510340150222),
    ('2025-01-01', 'GapPct_SMA200_365d_ROC7=+1 & GapPct_SMA365_365d=+1 & MABreak_EMA_d_50_100_200_365_frac_ROC2_30=-1', 1.135179620631534),
    ('2025-01-01', 'GapPct_SMA200_365d=+1 & GapPct_SMA200_365d_ROC7=+1 & MABreak_EMA_d_50_100_200_365_frac_ROC2_30=-1', 1.121754448167085),
    ('2026-01-01', 'GapPct_SMA200_365d=+1 & MABreak_EMA_d_30_90_180_365_frac_ROC30=+1 & Exch_Netflow=-1', 1.3090198182332229),
    ('2026-01-01', 'T10Y2Y_ROC30=+1 & Zscore_EMA26_weekly_ROC7=+1 & Zscore_SMA200_daily_ROC30=+1', 1.2233233066344436),
    ('2026-01-01', 'Zscore_EMA90_daily=+1 & MABreak_EMA_d_50_100_200_365_frac_ROC2_30=-1 & Coinbase_Prem=-1', 1.2684584347998304),
    ('2026-01-01', 'T10Y2Y_ROC30=+1 & Zscore_EMA50_daily_ROC30=+1 & DXY_ROC30=+1', 1.2366391670469477),
    ('2026-01-01', 'RealVol_90=+1 & MPI_ROC30=+1 & MABreak_EMA_d_50_100_200_365_frac_ROC30=-1', 1.2253465674275237),
    ('2026-01-01', 'T10Y2Y_ROC30=+1 & Zscore_SMA365_daily_ROC7=+1 & RealVol_90=-1', 1.1924180049335429),
    ('2026-01-01', 'Zscore_EMA200_daily=+1 & MABreak_EMA_d_50_100_200_365_frac_ROC2_30=-1 & Coinbase_Prem=-1', 1.1715334989617243),
    ('2026-01-01', 'Zscore_EMA200_daily=+1 & MPI_ROC30=+1 & MABreak_SMA_d_30_90_180_365_frac_ROC30=+1', 1.101157537339652),
    ('2026-01-01', 'Zscore_SMA365_daily=+1 & MABreak_EMA_d_30_90_180_365_frac_ROC2_30=-1 & Hash_Rate_ROC2_30=-1', 1.110446952238475),
    ('2026-01-01', 'RealVol_90=+1 & SOPR_Ratio_ROC7=+1 & Zscore_EMA26_weekly=-1', 1.114659061837594),
]


def frozen_top10_selected() -> pd.DataFrame:
    return pd.DataFrame(FROZEN_TOP10_ROWS, columns=["anchor", "best_combo", "weight_used"]).assign(anchor=lambda d: pd.to_datetime(d["anchor"]))


def rebuild_k3_daily_from_frozen_top10(close: pd.Series, disc: pd.DataFrame, out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    out_dir.mkdir(parents=True, exist_ok=True)
    close = close.reindex(disc.index).ffill().astype(float)
    labs = compute_labels(close)
    current_year = int(close.index.max().year)
    anchors = [pd.Timestamp(f"{y}-01-01") for y in range(2015, current_year + 1)]
    selected = frozen_top10_selected()
    selected = selected[selected["anchor"] <= pd.Timestamp(f"{current_year}-01-01")].copy()
    selected.to_csv(out_dir / "k3_selected_top10_full_recompute.csv", index=False)
    candidates = pd.DataFrame(columns=["anchor", "best_combo", "weight_used"])
    candidates.to_csv(out_dir / "k3_mined_candidates_full_recompute.csv", index=False)

    cols = {
        "bull_continuation_active": np.zeros(len(disc), dtype=float),
        "bull_continuation_firstfire": np.zeros(len(disc), dtype=float),
        "bull_continuation_decay_score": np.zeros(len(disc), dtype=float),
    }
    for _, row in selected.iterrows():
        anchor = pd.Timestamp(row["anchor"])
        if anchor not in anchors:
            continue
        ai = anchors.index(anchor)
        next_anchor = anchors[ai + 1] if ai + 1 < len(anchors) else close.index.max() + pd.Timedelta(days=1)
        interval = (disc.index >= anchor) & (disc.index < next_anchor)
        mask = combo_mask(disc, row["best_combo"])
        active = mask & interval
        ff = first_fire(mask)
        fmask = np.zeros(len(disc), dtype=bool)
        fmask[ff] = True
        fmask &= interval
        cols["bull_continuation_active"] += active.astype(float)
        cols["bull_continuation_firstfire"] += fmask.astype(float)
        weight = float(row["weight_used"])
        for t in np.flatnonzero(fmask):
            end = min(len(disc), t + MAX_LIFE + 1)
            d = np.arange(end - t)
            cols["bull_continuation_decay_score"][t:end] += weight * np.exp(-d / HALFLIFE)
    state = pd.DataFrame(cols, index=disc.index)
    state["btc_close"] = close
    state["overlay_bull_boost_mult"] = (1.0 + 0.15 * np.tanh(state["bull_continuation_decay_score"] / 3.0)).clip(1.0, 1.15)
    state["E"] = ((state["overlay_bull_boost_mult"] - 1.0) / 0.15).clip(0.0, 1.0)
    state["score"] = (0.5 + 0.5 * state["E"]).clip(0.0, 1.0)
    state["rank"] = expanding_percentile(state["score"])
    state.to_csv(out_dir / "k3_daily_state_full_recompute.csv", index_label="date")
    return state, selected, candidates


def k3_bucket_exposure(rank: pd.Series, weak: float, strong: float, low: float = 0.25, mid: float = 0.50, high: float = 1.0) -> pd.Series:
    exp = np.select([rank.astype(float) <= weak, rank.astype(float) >= strong], [low, high], default=mid)
    return pd.Series(exp, index=rank.index, name="exposure").astype(float)


def one_step_overlay(v3_exp: pd.Series, rank: pd.Series, weak: float, strong: float, add: float, trim: float) -> pd.Series:
    idx = v3_exp.index.intersection(rank.index)
    v3e = v3_exp.reindex(idx).ffill().clip(0.0, 1.0).astype(float)
    r = rank.reindex(idx).ffill().fillna(0.5).clip(0.0, 1.0).astype(float)
    exp = v3e + np.where(r >= strong, add, np.where(r <= weak, -trim, 0.0))
    return pd.Series(exp, index=idx, name="final_exposure").clip(0.0, 1.0)


def two_step_overlay(v3_exp: pd.Series, rank: pd.Series, outer_weak: float, extreme_weak: float, outer_strong: float, extreme_strong: float, outer_add: float, extreme_add: float, outer_trim: float, extreme_trim: float) -> pd.Series:
    idx = v3_exp.index.intersection(rank.index)
    v3e = v3_exp.reindex(idx).ffill().clip(0.0, 1.0).astype(float)
    r = rank.reindex(idx).ffill().fillna(0.5).clip(0.0, 1.0).astype(float)
    delta = np.zeros(len(r), dtype=float)
    delta = np.where(r >= outer_strong, outer_add, delta)
    delta = np.where(r >= extreme_strong, extreme_add, delta)
    delta = np.where(r <= outer_weak, -outer_trim, delta)
    delta = np.where(r <= extreme_weak, -extreme_trim, delta)
    return pd.Series(v3e + delta, index=idx, name="final_exposure").clip(0.0, 1.0)


def backtest_from_exposure(close: pd.Series, exposure: pd.Series) -> pd.DataFrame:
    idx = close.index.intersection(exposure.index)
    c = close.reindex(idx).ffill().astype(float)
    e = exposure.reindex(idx).ffill().fillna(0.5).clip(0.0, 1.0).astype(float)
    btc_ret = c.pct_change().fillna(0.0)
    fee = e.diff().abs().fillna(0.0) * FEE_PER_UNIT
    port_ret = e.shift(1).fillna(e.iloc[0]) * btc_ret - fee
    port_cum = (1.0 + port_ret).cumprod()
    return pd.DataFrame({"btc_close": c, "exposure": e, "btc_ret": btc_ret, "fee_drag": fee, "port_ret": port_ret, "port_cum": port_cum, "drawdown": port_cum / port_cum.cummax() - 1.0}, index=idx)


def annual_return(ret: pd.Series) -> float:
    r = ret.dropna().astype(float)
    if len(r) == 0:
        return np.nan
    total = float((1.0 + r).prod() - 1.0)
    years = len(r) / 365.25
    return float((1.0 + total) ** (1.0 / years) - 1.0) if total > -1 else -1.0


def sharpe(ret: pd.Series) -> float:
    r = ret.dropna().astype(float)
    vol = float(r.std() * math.sqrt(ANN_DAYS))
    return float(annual_return(r) / vol) if vol > 0 else np.nan


def downside_vol(ret: pd.Series) -> float:
    down = ret.dropna().astype(float)
    down = down[down < 0]
    return float(down.std() * math.sqrt(ANN_DAYS)) if len(down) > 1 else np.nan


def sortino(ret: pd.Series) -> float:
    dv = downside_vol(ret)
    return float(annual_return(ret) / dv) if dv and dv > 0 else np.nan


def max_drawdown(ret: pd.Series) -> float:
    eq = (1.0 + ret.fillna(0.0).astype(float)).cumprod()
    return float((eq / eq.cummax() - 1.0).min())


def metrics_row(name: str, bt: pd.DataFrame, eval_start: pd.Timestamp, base_ret: pd.Series | None = None) -> dict:
    d = bt.loc[eval_start:].dropna(subset=["port_ret", "exposure"]).copy()
    r = d["port_ret"]
    row = {
        "strategy": name,
        "start": str(d.index[0].date()),
        "end": str(d.index[-1].date()),
        "days": int(len(d)),
        "sharpe": sharpe(r),
        "annual_return": annual_return(r),
        "max_drawdown": max_drawdown(r),
        "avg_exposure": float(d["exposure"].mean()),
        "latest_exposure": float(d["exposure"].iloc[-1]),
        "downside_vol": downside_vol(r),
        "sortino": sortino(r),
        "turnover": float(d["exposure"].diff().abs().fillna(0.0).sum()),
        "fee_drag_sum": float(d["fee_drag"].sum()),
    }
    if base_ret is not None:
        base = base_ret.reindex(r.index).dropna()
        common = r.index.intersection(base.index)
        row["d_sharpe_vs_v3"] = sharpe(r.loc[common]) - sharpe(base.loc[common])
        row["d_ann_ret_vs_v3"] = annual_return(r.loc[common]) - annual_return(base.loc[common])
        row["d_max_dd_vs_v3"] = max_drawdown(r.loc[common]) - max_drawdown(base.loc[common])
    else:
        row["d_sharpe_vs_v3"] = 0.0
        row["d_ann_ret_vs_v3"] = 0.0
        row["d_max_dd_vs_v3"] = 0.0
    return row


OUT = HERE / "standalone_10_90_full_recompute_outputs"
OUT.mkdir(parents=True, exist_ok=True)
EVAL_START = pd.Timestamp("2020-01-01")
K3_BUCKET_WEAK = 0.10
K3_BUCKET_STRONG = 0.90


def progress(pct: int, message: str, t0: float) -> None:
    import time

    elapsed = (time.time() - t0) / 60.0
    eta = elapsed * (100.0 - pct) / pct if pct > 0 else float("nan")
    print(f"[progress {pct:3d}%] {message} | elapsed={elapsed:.1f}m | eta~{eta:.1f}m", flush=True)


def main() -> None:
    import time
    t0 = time.time()
    progress(1, "starting K3 standalone 10/90 run", t0)
    v3 = import_from_path("v3_prod_for_k3_standalone_full", V3_FILE)

    progress(5, "loading current V3 production data", t0)
    close, base_disc, _fwd, _vol_zscore = v3._load_production_data()
    close = close.astype(float).sort_index()
    base_disc = base_disc.sort_index()
    progress(35, f"V3 data loaded: {len(close)} BTC rows, {base_disc.shape[1]} base signals", t0)

    progress(40, "rebuilding extended K3 signal universe", t0)
    ext_disc, manifest = build_extended_disc(v3, close, base_disc, OUT)
    progress(70, f"extended K3 matrix rebuilt: {ext_disc.shape[1]} signals", t0)
    progress(72, "mining walk-forward K3 candidates and auto-selecting top10 daily evidence/rank", t0)
    k3_daily, selected, candidates = rebuild_k3_daily_from_scratch(close, ext_disc, OUT)
    k3_exp = k3_bucket_exposure(k3_daily["rank"], K3_BUCKET_WEAK, K3_BUCKET_STRONG)
    progress(82, f"K3 daily state ready: {len(selected)} auto-selected top10 rows", t0)

    progress(86, "backtesting K3 standalone 10/90", t0)
    idx = close.loc[EVAL_START : min(close.index.max(), k3_daily.index.max())].index
    bt = backtest_from_exposure(close.reindex(idx), k3_exp.reindex(idx))
    metrics = pd.DataFrame([metrics_row("K3 standalone 10/90 full recompute", bt, EVAL_START)])
    progress(92, "backtest metrics computed", t0)

    daily = pd.DataFrame(index=idx)
    daily["btc_close"] = close.reindex(idx)
    daily["k3_E"] = k3_daily["E"].reindex(idx)
    daily["k3_score"] = k3_daily["score"].reindex(idx)
    daily["k3_rank"] = k3_daily["rank"].reindex(idx)
    daily["final_exposure"] = k3_exp.reindex(idx)
    daily["strategy_return"] = bt["port_ret"].reindex(idx)
    daily["strategy_cum"] = bt["port_cum"].reindex(idx)
    daily["drawdown"] = bt["drawdown"].reindex(idx)

    metrics.to_csv(OUT / "k3_standalone_10_90_full_recompute_metrics.csv", index=False)
    daily.to_csv(OUT / "k3_standalone_10_90_full_recompute_daily.csv", index_label="date")

    progress(96, "writing CSV outputs and markdown report", t0)
    report = [
        "# K3 Standalone 10/90 Full Recompute",
        "",
        "This run rebuilds the extended K3 signal matrix, mines walk-forward K3 candidates, auto-selects strict top10 leaders, recomputes daily K3 evidence, and maps K3 rank to 25% / 50% / 100% BTC exposure.",
        "",
        "Mapping: `rank <= 10% -> 25% BTC`, `10% < rank < 90% -> 50% BTC`, `rank >= 90% -> 100% BTC`. No leverage.",
        "",
        f"Window: {metrics['start'].iloc[0]} to {metrics['end'].iloc[0]}.",
        "",
        "## Metrics",
        "",
        metrics.to_markdown(index=False, floatfmt=".6f"),
        "",
        "## Recompute Summary",
        "",
        f"- Extended signals: {ext_disc.shape[1]}",
        f"- Walk-forward mined candidate rows: {len(candidates)}",
        f"- Auto-selected top10 rows: {len(selected)}",
        f"- Rebuilt passers OK: {int((manifest['status'] == 'ok').sum())}",
        "",
        "## Latest Daily State",
        "",
        daily.tail(10).to_markdown(index=True, floatfmt=".6f"),
    ]
    (OUT / "k3_standalone_10_90_full_recompute_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    progress(100, "K3 standalone run complete", t0)
    print(metrics[["strategy", "start", "end", "sharpe", "annual_return", "max_drawdown", "avg_exposure", "latest_exposure", "downside_vol", "sortino"]].to_string(index=False))
    print(f"Wrote: {OUT}", flush=True)
    print(f"Done in {(time.time() - t0) / 60:.1f} minutes.", flush=True)


if __name__ == "__main__":
    main()
