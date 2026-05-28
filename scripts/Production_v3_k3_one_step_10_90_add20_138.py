#!/usr/bin/env python3
"""V3 + K3 one-step 10/90 +20/-20 handoff runner, universe 138.

Run from this folder:
    python3 run_strategy.py

The folder is self-contained for normal runs: it includes local V3 code,
Yahoo helper, V3 data cache fallback, and K3 selected-top10 cache. Daily BTC,
V3 exposure, and K3 signal inputs are recomputed every run so the latest date is
included.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd


VARIANT_KEY = "one_step"
VARIANT_NAME = "V3 + K3 one-step 10/90 +20% / -20%"
UNIVERSE = 138
EVAL_START = pd.Timestamp("2020-01-01")

ROOT = Path(__file__).resolve().parent
ENGINE_FILE = ROOT / "01_scripts" / "k3_local_strategy_engine.py"
CACHE_ROOT = ROOT / "cache"
SHARED_CACHE = CACHE_ROOT / "shared"
UNIVERSE_CACHE = CACHE_ROOT / "u138"
OUTPUT_DIR = ROOT / "outputs"
APP_DATA_DIR = ROOT.parent / "data"
for d in (SHARED_CACHE, UNIVERSE_CACHE, OUTPUT_DIR, APP_DATA_DIR):
    d.mkdir(parents=True, exist_ok=True)

RUN_SOURCE = {
    "shared_inputs": "UNKNOWN",
    "shared_close_end": None,
    "v3_stdout": "",
    "k3_stdout": "",
}


class TeeCapture(contextlib.AbstractContextManager):
    def __init__(self):
        self.buffer = io.StringIO()
        self._stdout = None

    def write(self, text: str) -> int:
        self.buffer.write(text)
        return self._stdout.write(text)

    def flush(self) -> None:
        self.buffer.flush()
        self._stdout.flush()

    def __enter__(self):
        self._stdout = sys.stdout
        sys.stdout = self
        return self

    def __exit__(self, exc_type, exc, tb):
        sys.stdout = self._stdout
        return False


def progress(pct: int, msg: str, t0: float) -> None:
    elapsed = (time.time() - t0) / 60.0
    eta = elapsed * (100 - pct) / pct if pct > 0 else 0.0
    print(f"[progress {pct:3d}%] {msg} | elapsed={elapsed:.1f}m | eta~{eta:.1f}m", flush=True)


def load_engine():
    spec = importlib.util.spec_from_file_location("k3_local_strategy_engine", ENGINE_FILE)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["k3_local_strategy_engine"] = mod
    spec.loader.exec_module(mod)
    return mod


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def columns_hash(cols: list[str]) -> str:
    return hashlib.sha256("\n".join(map(str, cols)).encode("utf-8")).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def read_csv_dates(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "anchor" in df.columns:
        df["anchor"] = pd.to_datetime(df["anchor"])
    return df


def markdown_table(df: pd.DataFrame) -> str:
    """Small markdown table writer without pandas' optional tabulate dependency."""
    text_df = df.copy()
    for col in text_df.columns:
        if pd.api.types.is_float_dtype(text_df[col]):
            text_df[col] = text_df[col].map(lambda x: "" if pd.isna(x) else f"{x:.6f}")
        else:
            text_df[col] = text_df[col].map(lambda x: "" if pd.isna(x) else str(x))
    headers = list(text_df.columns)
    rows = text_df.values.tolist()
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines.extend("| " + " | ".join(map(str, row)) + " |" for row in rows)
    return "\n".join(lines)


def build_or_load_shared(engine, refresh_shared: bool, allow_stale_shared: bool, t0: float):
    """Recompute live daily inputs every run.

    The only production cache we rely on for speed is the annual K3 selected
    motif cache. BTC close, V3 exposure, and the 138-signal K3 matrix are
    recomputed on every run so the latest day is incorporated.
    """
    progress(5, "loading local V3 production data", t0)
    v3 = engine.import_from_path("v3_prod_local_for_k3", engine.V3_FILE)
    with TeeCapture() as cap:
        close, base_disc, fwd, vol_zscore = v3._load_production_data()
    RUN_SOURCE["v3_stdout"] += cap.buffer.getvalue()
    close = close.astype(float).sort_index()
    base_disc = base_disc.sort_index()

    progress(12, "recomputing V3 original exposure", t0)
    _combo, v3_exp, _m, _corr = v3._run_production_strategy(close, base_disc, fwd, vol_zscore)
    v3_exp = v3_exp.reindex(close.index).ffill().clip(0.0, 1.0)

    progress(20, "rebuilding K3 extended signal matrix", t0)
    with TeeCapture() as cap:
        ext_full, manifest = engine.build_extended_disc(v3, close, base_disc, SHARED_CACHE)
    RUN_SOURCE["k3_stdout"] += cap.buffer.getvalue()
    manifest.to_csv(SHARED_CACHE / "k3_extended_signal_rebuild_manifest.csv", index=False)
    write_json(
        SHARED_CACHE / "manifest.json",
        {
            "created_at": pd.Timestamp.now("UTC").isoformat(),
            "universe": UNIVERSE,
            "v3_file": str(engine.V3_FILE),
            "v3_file_sha256": file_sha256(engine.V3_FILE),
            "close_end": str(close.index.max().date()),
            "ext_signal_count": int(ext_full.shape[1]),
            "ext_columns_hash": columns_hash(list(ext_full.columns)),
        },
    )
    RUN_SOURCE["shared_inputs"] = "RECOMPUTED THIS RUN (V3 API/cache fallback)"
    RUN_SOURCE["shared_close_end"] = str(close.index.max().date())
    return close, v3_exp, ext_full


def apply_selected_no_label_mask(engine, close: pd.Series, disc: pd.DataFrame, selected: pd.DataFrame) -> pd.DataFrame:
    close = close.reindex(disc.index).ffill().astype(float)
    current_year = int(close.index.max().year)
    anchors = [pd.Timestamp(f"{y}-01-01") for y in range(2015, current_year + 1)]
    selected = selected.copy()
    if len(selected):
        selected["anchor"] = pd.to_datetime(selected["anchor"])

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
        mask = engine.combo_mask(disc, row["best_combo"])
        active = mask & interval
        ff = engine.first_fire(mask)
        fmask = np.zeros(len(disc), dtype=bool)
        fmask[ff] = True
        fmask &= interval
        cols["bull_continuation_active"] += active.astype(float)
        cols["bull_continuation_firstfire"] += fmask.astype(float)
        weight = float(row["weight_used"])
        for t in np.flatnonzero(fmask):
            end = min(len(disc), t + engine.MAX_LIFE + 1)
            d = np.arange(end - t)
            cols["bull_continuation_decay_score"][t:end] += weight * np.exp(-d / engine.HALFLIFE)

    state = pd.DataFrame(cols, index=disc.index)
    state["btc_close"] = close
    state["overlay_bull_boost_mult"] = (1.0 + 0.15 * np.tanh(state["bull_continuation_decay_score"] / 3.0)).clip(1.0, 1.15)
    state["E"] = ((state["overlay_bull_boost_mult"] - 1.0) / 0.15).clip(0.0, 1.0)
    state["score"] = (0.5 + 0.5 * state["E"]).clip(0.0, 1.0)
    state["rank"] = engine.expanding_percentile(state["score"])
    return state


def load_or_build_k3_state(engine, close: pd.Series, disc: pd.DataFrame, force_remine: bool, t0: float):
    selected_p = UNIVERSE_CACHE / "selected_top10.csv"
    candidates_p = UNIVERSE_CACHE / "mined_candidates.csv"
    daily_p = UNIVERSE_CACHE / "k3_daily_state.csv"
    anchors_done_p = UNIVERSE_CACHE / "anchors_done.json"

    if force_remine or not selected_p.exists():
        progress(35, "selected-top10 cache missing: full adaptive remine", t0)
        daily, selected, candidates = engine.rebuild_k3_daily_from_scratch(close, disc, UNIVERSE_CACHE / "full_remine_tmp")
        selected["anchor"] = pd.to_datetime(selected["anchor"])
        current_year = int(close.index.max().year)
        anchors_done = [f"{y}-01-01" for y in range(2015, current_year + 1)]
    else:
        progress(35, "loading local K3 selected-top10 cache", t0)
        selected = read_csv_dates(selected_p)
        candidates = read_csv_dates(candidates_p) if candidates_p.exists() else pd.DataFrame()
        anchors_done = read_json(anchors_done_p, {}).get("anchors_done", [])

    current_year = int(close.index.max().year)
    all_anchors = [pd.Timestamp(f"{y}-01-01") for y in range(2015, current_year + 1)]
    done = set(pd.to_datetime(anchors_done).normalize()) if anchors_done else set(pd.to_datetime(selected["anchor"]).dt.normalize())
    labs = None
    for i, anchor in enumerate(all_anchors):
        if anchor in done:
            continue
        if labs is None:
            labs = engine.compute_labels(close.reindex(disc.index).ffill().astype(float))
        next_anchor = all_anchors[i + 1] if i + 1 < len(all_anchors) else close.index.max() + pd.Timedelta(days=1)
        progress(45, f"mining missing yearly anchor {anchor.date()}", t0)
        cand = engine.mine_anchor_candidates(anchor, next_anchor, disc, labs)
        sel = engine.select_strict_top10_for_anchor(anchor, cand, disc, labs)
        if len(cand):
            candidates = pd.concat([candidates, cand], ignore_index=True)
        if len(sel):
            selected = pd.concat([selected, sel], ignore_index=True)
        done.add(anchor)

    progress(70, "applying selected motifs to latest dates without label mask", t0)
    daily = apply_selected_no_label_mask(engine, close, disc, selected)
    selected.to_csv(selected_p, index=False)
    candidates.to_csv(candidates_p, index=False)
    daily.to_csv(daily_p, index_label="date")
    write_json(anchors_done_p, {"anchors_done": sorted(pd.to_datetime(list(done)).strftime("%Y-%m-%d").tolist())})
    write_json(
        UNIVERSE_CACHE / "manifest.json",
        {
            "updated_at": pd.Timestamp.now("UTC").isoformat(),
            "universe": UNIVERSE,
            "signal_count": int(disc.shape[1]),
            "close_end": str(close.index.max().date()),
            "selected_rows": int(len(selected)),
            "oos_apply_uses_label_valid_mask": False,
        },
    )
    return daily, selected


def variant_exposure(engine, v3_exp: pd.Series, rank: pd.Series) -> pd.Series:
    return engine.one_step_overlay(v3_exp, rank, 0.10, 0.90, 0.20, 0.20)


def _json_cache_info(path: Path) -> dict:
    if not path.exists():
        return {"status": "MISSING", "cache_date": "N/A", "data_end": "N/A", "items": 0}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        data = obj.get("data", {})
        dates = []
        if isinstance(data, dict):
            for key, val in data.items():
                if isinstance(val, dict):
                    dates.extend(val.keys())
                else:
                    dates.append(key)
        parsed = pd.to_datetime(pd.Series(dates), errors="coerce").dropna() if dates else pd.Series(dtype="datetime64[ns]")
        data_end = str(parsed.max().date()) if len(parsed) else "N/A"
        return {
            "status": "LOCAL JSON CACHE",
            "cache_date": obj.get("date", "unknown"),
            "data_end": data_end,
            "items": len(data) if isinstance(data, dict) else 0,
        }
    except Exception as exc:
        return {"status": f"READ ERROR: {exc}", "cache_date": "N/A", "data_end": "N/A", "items": 0}


def _fmt_money(x: float) -> str:
    return f"${x:,.0f}"


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _direction(strategy_exp: float, v3_exp: float) -> str:
    if strategy_exp > v3_exp + 1e-9:
        return "BULLISH / ADD BTC"
    if strategy_exp < v3_exp - 1e-9:
        return "BEARISH / CUT BTC"
    return "NEUTRAL"


def _data_provenance_lines(close: pd.Series, v3_exp: pd.Series, k3_daily: pd.DataFrame, selected: pd.DataFrame) -> list[str]:
    v3_cache = ROOT / "v3_production_0428" / "v3_experiment_v2" / "cache"
    cache_rows = [
        ("V3 cache BTC-USD", _json_cache_info(v3_cache / "cache_btc.json")),
        ("V3 cache CryptoQuant", _json_cache_info(v3_cache / "cache_cquant.json")),
        ("V3 cache FRED", _json_cache_info(v3_cache / "cache_fred.json")),
        ("V3 cache Macro", _json_cache_info(v3_cache / "cache_macro.json")),
    ]
    selected_anchors = pd.to_datetime(selected["anchor"]).dt.strftime("%Y-%m-%d").unique().tolist() if len(selected) else []
    v3_log = RUN_SOURCE.get("v3_stdout", "")
    k3_log = RUN_SOURCE.get("k3_stdout", "")
    btc_source = "LIVE THIS RUN (Yahoo helper)"
    if "FATAL: BTC cache missing" in v3_log:
        btc_source = "FAILED"
    elif "[cache] Saved BTC-USD" not in v3_log:
        btc_source = "CACHE FALLBACK USED"
    cq_source = "LIVE THIS RUN (CryptoQuant API)"
    if "FATAL: CryptoQuant cache missing" in v3_log:
        cq_source = "FAILED"
    elif "[cache] Saved CryptoQuant" not in v3_log:
        cq_source = "CACHE FALLBACK USED"
    fred_source = "LIVE THIS RUN (FRED API)"
    if "FATAL: FRED" in v3_log:
        fred_source = "FAILED"
    elif "[FRED " in v3_log:
        fred_source = "CACHE FALLBACK USED"
    macro_source = "LIVE THIS RUN (Yahoo helper)"
    if "FATAL: Yahoo bundle unavailable" in v3_log:
        macro_source = "FAILED"
    k3_matrix_source = "RECOMPUTED THIS RUN"
    if "[k3] Extended signal count" not in k3_log:
        k3_matrix_source = "UNKNOWN"
    lines = [
        f"  BTC close            {btc_source:<42} {close.index.min().date()} to {close.index.max().date()}",
        f"  V3 exposure          RECOMPUTED THIS RUN                     to {v3_exp.index.max().date()}",
        f"  K3 signal matrix     {k3_matrix_source:<42} {UNIVERSE} signals",
        f"  K3 selected top10    LOCAL K3 LONG-RUN CACHE / AUTO-MINE {len(selected)} rows, {len(selected_anchors)} anchors",
        f"  K3 daily state       RECOMPUTED NO-LABEL-MASK      to {k3_daily.index.max().date()}",
        f"  CryptoQuant          {cq_source}",
        f"  FRED                 {fred_source}",
        f"  Macro/Yahoo          {macro_source}",
    ]
    for name, info in cache_rows:
        lines.append(f"  {name:<20} {info['status']:<28} cache_date={info['cache_date']} data_end={info['data_end']} items={info['items']}")
    return lines


def _build_morning_report(close: pd.Series, v3_exp: pd.Series, k3_daily: pd.DataFrame, selected: pd.DataFrame, metrics: pd.DataFrame, daily: pd.DataFrame) -> str:
    latest_date = daily.index[-1]
    btc_now = float(close.loc[latest_date])
    btc_prev = float(close.loc[:latest_date].iloc[-2]) if len(close.loc[:latest_date]) >= 2 else btc_now
    btc_chg = btc_now / btc_prev - 1.0 if btc_prev else 0.0
    v3_latest = float(daily["v3_exposure"].iloc[-1])
    strategy_latest = float(daily["strategy_exposure"].iloc[-1])
    rank_latest = float(daily["k3_rank"].iloc[-1])
    k3_e = float(daily["k3_E"].iloc[-1])
    k3_score = float(daily["k3_score"].iloc[-1])
    m = metrics.set_index("strategy")
    strategy_row = m.loc[VARIANT_NAME]
    v3_row = m.loc["V3 original"]
    width = 72
    lines = [
        f"CYCLESIGNAL K3 138 HANDOFF REPORT — {latest_date.date()}",
        "=" * width,
        f"  Strategy:   {VARIANT_NAME}",
        f"  BTC:        {_fmt_money(btc_now)} ({btc_chg:+.1%})",
        f"  V3 Exposure:       {v3_latest:.0%}",
        f"  Strategy Exposure: {strategy_latest:.0%}",
        f"  Overlay Delta:     {(strategy_latest - v3_latest):+.0%}",
        f"  Direction:  {_direction(strategy_latest, v3_latest)}",
        f"  K3 Rank:    {rank_latest:.4f}",
        f"  K3 E/Score: {k3_e:.4f} / {k3_score:.4f}",
        "",
        "  BACKTEST METRICS",
        "  -------------------------------------------------------",
        f"  Strategy Sharpe: {strategy_row['sharpe']:.4f}",
        f"  V3 Sharpe:       {v3_row['sharpe']:.4f}",
        f"  Sharpe Delta:    {strategy_row['d_sharpe_vs_v3']:+.4f}",
        f"  Annual Return:   {_fmt_pct(strategy_row['annual_return'])}",
        f"  Max Drawdown:    {_fmt_pct(strategy_row['max_drawdown'])}",
        f"  Avg Exposure:    {strategy_row['avg_exposure']:.1%}",
        f"  Turnover:        {strategy_row['turnover']:.1f}",
        f"  Fee Drag Sum:    {strategy_row['fee_drag_sum']:.4f}",
        "",
        "  DATA PROVENANCE",
        "  -------------------------------------------------------",
        *_data_provenance_lines(close, v3_exp, k3_daily, selected),
        "=" * width,
        f"  Saved metrics CSV: {OUTPUT_DIR / 'strategy_metrics.csv'}",
        f"  Saved daily CSV:   {OUTPUT_DIR / 'strategy_daily.csv'}",
        f"  Saved report MD:   {OUTPUT_DIR / 'strategy_report.md'}",
        f"  Saved morning TXT: {OUTPUT_DIR / 'morning_report.txt'}",
    ]
    return "\n".join(lines)


def _build_cache_warnings() -> list[str]:
    warnings: list[str] = []
    v3_log = RUN_SOURCE.get("v3_stdout", "")
    k3_log = RUN_SOURCE.get("k3_stdout", "")
    if "FATAL: BTC cache missing" in v3_log:
        warnings.append("⚠️ FAILED: BTC data unavailable")
    elif "[cache] Saved BTC-USD" not in v3_log:
        warnings.append("⚠️ CACHED: BTC price using cached data")
    if "FATAL: CryptoQuant cache missing" in v3_log:
        warnings.append("⚠️ FAILED: CryptoQuant data unavailable")
    elif "[cache] Saved CryptoQuant" not in v3_log:
        warnings.append("⚠️ CACHED: CryptoQuant data from cache")
    if "FATAL: FRED" in v3_log:
        warnings.append("⚠️ FAILED: FRED data unavailable")
    elif "[FRED " in v3_log:
        warnings.append("⚠️ CACHED: FRED macro data from cache")
    if "FATAL: Yahoo bundle unavailable" in v3_log:
        warnings.append("⚠️ FAILED: Yahoo macro data unavailable")
    if "[k3] Extended signal count" not in k3_log:
        warnings.append("⚠️ K3 signal matrix status unknown")
    return warnings


def write_app_data(daily: pd.DataFrame, metrics: pd.DataFrame) -> None:
    latest = daily.iloc[-1]
    latest_date = daily.index[-1]

    m = metrics.set_index("strategy")
    strategy_row = m.loc[VARIANT_NAME]
    v3_row = m.loc["V3 original"]

    strategy_exp = float(latest["strategy_exposure"])
    v3_e = float(latest["v3_exposure"])
    overlay_delta = strategy_exp - v3_e
    if overlay_delta > 1e-9:
        direction = "BULLISH"
    elif overlay_delta < -1e-9:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    state = {
        "date": str(latest_date.date()),
        "btc_price": float(latest["btc_close"]),
        "exposure": strategy_exp,
        "v3_exposure": v3_e,
        "overlay_delta": round(overlay_delta, 6),
        "direction": direction,
        "k3_rank": float(latest["k3_rank"]),
        "k3_E": float(latest["k3_E"]),
        "k3_score": float(latest["k3_score"]),
        "strategy_sharpe": float(strategy_row["sharpe"]),
        "v3_sharpe": float(v3_row["sharpe"]),
        "sharpe_delta": float(strategy_row["d_sharpe_vs_v3"]),
        "annual_return": float(strategy_row["annual_return"]),
        "max_drawdown": float(strategy_row["max_drawdown"]),
        "avg_exposure": float(strategy_row["avg_exposure"]),
        "cache_warnings": _build_cache_warnings(),
    }
    write_json(APP_DATA_DIR / "cycle_state.json", state)
    print(f"  App state  → {APP_DATA_DIR / 'cycle_state.json'}", flush=True)

    history = []
    for date, row in daily.iterrows():
        history.append({
            "date": str(date.date()),
            "exposure": round(float(row["strategy_exposure"]), 4),
            "v3_exposure": round(float(row["v3_exposure"]), 4),
            "btc_price": round(float(row["btc_close"]), 2),
            "k3_rank": round(float(row["k3_rank"]), 6),
        })
    (APP_DATA_DIR / "cycle_history.json").write_text(
        json.dumps(history) + "\n", encoding="utf-8"
    )
    print(f"  App history→ {APP_DATA_DIR / 'cycle_history.json'} ({len(history)} entries)", flush=True)


def write_outputs(engine, close: pd.Series, v3_exp: pd.Series, k3_daily: pd.DataFrame, selected: pd.DataFrame):
    idx = close.loc[EVAL_START : min(close.index.max(), k3_daily.index.max())].index
    exp = variant_exposure(engine, v3_exp, k3_daily["rank"])
    bt_v3 = engine.backtest_from_exposure(close.reindex(idx), v3_exp.reindex(idx))
    bt = engine.backtest_from_exposure(close.reindex(idx), exp.reindex(idx))
    metrics = pd.DataFrame(
        [
            engine.metrics_row("V3 original", bt_v3, EVAL_START),
            engine.metrics_row(VARIANT_NAME, bt, EVAL_START, bt_v3["port_ret"]),
        ]
    )
    daily = pd.DataFrame(index=idx)
    daily["btc_close"] = close.reindex(idx)
    daily["v3_exposure"] = v3_exp.reindex(idx)
    daily["k3_E"] = k3_daily["E"].reindex(idx)
    daily["k3_score"] = k3_daily["score"].reindex(idx)
    daily["k3_rank"] = k3_daily["rank"].reindex(idx)
    daily["strategy_exposure"] = exp.reindex(idx)
    daily["v3_return"] = bt_v3["port_ret"].reindex(idx)
    daily["strategy_return"] = bt["port_ret"].reindex(idx)
    metrics.to_csv(OUTPUT_DIR / "strategy_metrics.csv", index=False)
    daily.to_csv(OUTPUT_DIR / "strategy_daily.csv", index_label="date")
    selected.to_csv(OUTPUT_DIR / "selected_top10_used.csv", index=False)
    report = [
        f"# {VARIANT_NAME}",
        "",
        f"- Universe: {UNIVERSE}",
        f"- Evaluation: {idx.min().date()} to {idx.max().date()}",
        f"- Latest exposure: {daily['strategy_exposure'].iloc[-1]:.2%}",
        f"- Latest K3 rank: {daily['k3_rank'].iloc[-1]:.6f}",
        "",
        markdown_table(metrics[["strategy", "start", "end", "sharpe", "annual_return", "max_drawdown", "avg_exposure", "latest_exposure", "d_sharpe_vs_v3"]]),
    ]
    (OUTPUT_DIR / "strategy_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    morning_report = _build_morning_report(close, v3_exp, k3_daily, selected, metrics, daily)
    (OUTPUT_DIR / "morning_report.txt").write_text(morning_report + "\n", encoding="utf-8")
    print("\n" + morning_report + "\n", flush=True)
    print(metrics[["strategy", "sharpe", "annual_return", "max_drawdown", "avg_exposure", "latest_exposure", "d_sharpe_vs_v3"]].to_string(index=False), flush=True)
    write_app_data(daily, metrics)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-shared", action="store_true", help="kept for compatibility; daily inputs are recomputed every run")
    ap.add_argument("--allow-stale-shared", action="store_true", help="kept for compatibility; daily inputs are recomputed every run")
    ap.add_argument("--force-remine", action="store_true", help="force full adaptive K3 top10 remine")
    args = ap.parse_args()
    t0 = time.time()
    progress(1, f"starting {VARIANT_NAME}", t0)
    engine = load_engine()
    close, v3_exp, ext_full = build_or_load_shared(engine, args.refresh_shared, args.allow_stale_shared, t0)
    disc = ext_full
    k3_daily, selected = load_or_build_k3_state(engine, close, disc, args.force_remine, t0)
    write_outputs(engine, close, v3_exp, k3_daily, selected)
    progress(100, "complete", t0)
    print(f"[done] outputs: {OUTPUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
