#!/usr/bin/env python3
"""CycleSignal V4 production runner — daily incremental.

V4 = K10/sqrtN base + K3 cbrtM overlay (one-step 10/high-dynamic, +20% / -20%).
This is the production-shaped sibling of the research script
``reproduce_fresh_130_sqrtn_k3_cbrtM_20260610_rerun.py``. Differences that make
it safe to run every day:

  * Base (K10/sqrtN) caches *completed* quarterly rebalance segments under
    ``cache/base_parts``; the current (still-open) quarter is recomputed every
    run so new days are always appended.
  * K3 candidate mining is incremental: each yearly anchor is mined once and
    appended to ``cache/k3_mined_candidates.csv``. Already-mined anchors (the
    seed ships 2016-2026) are reused. Most days mine nothing.
  * Only the locked cbrtM mode is computed (sqrtM is dropped).
  * Outputs ``data/cycle_state.json`` (latest snapshot), appends
    ``data/cycle_history.json``, and writes ``data/daily.csv``.

Run:
    CRYPTOQUANT_API_KEY=... FRED_API_KEY=... python3 scripts/production_v4.py

Requires the same API inputs as V3 (BTC / CryptoQuant / FRED / Yahoo). No keys
are stored in source; they are read from the environment by the V3 backend.
"""
from __future__ import annotations

import json
import math
import sys
import time
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
CACHE = REPO / "cache"
BASE_PARTS = CACHE / "base_parts"
K3_CANDIDATES = CACHE / "k3_mined_candidates.csv"
DATA = REPO / "data"
for d in (BASE_PARTS, DATA):
    d.mkdir(parents=True, exist_ok=True)

EVAL_START = pd.Timestamp("2020-01-01")
RHO_MAX = 0.95
K_REF = 10
N_UNIVERSE = 138
K3_LOW = 0.10
K3_HIGH = 1.0 - 1.0 / math.sqrt(N_UNIVERSE)
K3_MODE = "cbrtM"
ADD = 0.20
TRIM = 0.20


def imp(name: str, path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


eng = imp("k3_local_strategy_engine", ROOT / "01_scripts" / "k3_local_strategy_engine.py")
v3 = imp("v3_cycle_signal_production_backup", ROOT / "v3_production_0428" / "v3_cycle_signal_production_backup.py")


def progress(pct: int, msg: str, t0: float) -> None:
    elapsed = (time.time() - t0) / 60.0
    eta = elapsed * (100 - pct) / pct if pct > 0 else 0.0
    print(f"[progress {pct:3d}%] {msg} | elapsed={elapsed:.1f}m | eta~{eta:.1f}m", flush=True)


# --------------------------------------------------------------------------- base

def base_target_k(regime: str, ranked_pair_count: int) -> int:
    """K10 schedule: LOW/NORMAL fixed 10; HIGH/EXTREME ceil(sqrt(active ranked pairs))."""
    if regime in {"HIGH", "EXTREME"}:
        return max(v3.MIN_PAIRS, int(math.ceil(math.sqrt(max(ranked_pair_count, 1)))))
    return K_REF


def _part_paths(rd: pd.Timestamp):
    tag = rd.strftime("%Y-%m-%d")
    return BASE_PARTS / f"combo_{tag}.csv", BASE_PARTS / f"corr_{tag}.csv"


def run_base(close, disc, fwd, vol_zscore, t0):
    """K10/sqrtN base. Completed quarters are cached; the final open quarter is
    always recomputed so the latest day is incorporated."""
    patched = v3.make_score_at_date_variant(v3.score_m0)
    v3._mod.MABreakSignal._eval_events = v3.make_eval_events_variant(v3.score_m0)
    sigs = list(disc.columns)
    rebal = pd.date_range(EVAL_START, close.index[-1], freq="3MS")
    last_idx = len(rebal) - 1
    combo = pd.Series(0.0, index=close.index)
    rows = []
    print(f"[base] signals={len(sigs)} K: LOW/NORMAL=10 HIGH/EXTREME=ceil(sqrt(ranked)) rho={RHO_MAX}", flush=True)
    for i, rd in enumerate(rebal):
        combo_p, corr_p = _part_paths(rd)
        nxt = rebal[i + 1] if i + 1 < len(rebal) else close.index[-1] + pd.Timedelta(days=1)
        oos = close.index[(close.index >= rd) & (close.index < nxt)]
        is_open_segment = i == last_idx  # current quarter keeps growing -> never trust cache
        if not is_open_segment and combo_p.exists() and corr_p.exists():
            seg = pd.read_csv(combo_p, parse_dates=["date"]).set_index("date")["combo"]
            combo.loc[seg.index] = seg
            rows.extend(pd.read_csv(corr_p, parse_dates=["rebalance_date"]).to_dict("records"))
            continue
        rd_rows = []
        seg_combo = pd.Series(0.0, index=oos)
        for ty in [2, 3]:
            train_start = rd - pd.DateOffset(years=ty)
            in_train = (disc.index >= train_start) & (disc.index < rd)
            disc_tr = disc[in_train]
            fwd_tr = fwd[in_train]
            vol_tr = vol_zscore[in_train]
            active = [s for s in sigs if (disc_tr[s] != 0).mean() > v3.ACTIVITY_THRESHOLD]
            pairs = list(combinations(active, 2))
            vz = float(vol_zscore.asof(rd)) if not pd.isna(vol_zscore.asof(rd)) else np.nan
            regime = v3._get_vol_regime(vz)
            ranked, dt_vl, ft_vl, fallback = v3.rank_pairs_cached(pairs, disc_tr, fwd_tr, rd, None)
            ranked_pair_count = len(ranked)
            k = base_target_k(regime, ranked_pair_count)
            top, dbg = v3.select_from_ranked(
                ranked, dt_vl, ft_vl, rd, None, fallback, k=k, use_corr_filter=True, disc_tr=disc_tr, rho_max=RHO_MAX
            )
            cstats = v3._selected_pair_corr_stats(top, disc_tr)
            rd_rows.append({
                "rebalance_date": rd, "train_years": ty, "regime": regime, "n_active": len(active),
                "ranked_pair_count": ranked_pair_count, "target_k": k, "selected_pairs": len(top), **dbg, **cstats,
            })
            for tdt in oos:
                seg_combo.loc[tdt] += patched(disc, fwd, top, tdt)
        seg_combo /= 2
        combo.loc[oos] = seg_combo
        if not is_open_segment:  # only freeze completed quarters
            pd.DataFrame({"date": seg_combo.index, "combo": seg_combo.values}).to_csv(combo_p, index=False)
            pd.DataFrame(rd_rows).to_csv(corr_p, index=False)
        rows.extend(rd_rows)
        tag = "open" if is_open_segment else "done"
        print(f"[base] {rd.date()} {tag} target_k={rd_rows[0]['target_k']}/{rd_rows[1]['target_k']}", flush=True)
    exp = v3.run_d10_backtest(combo, close)
    return combo, exp, pd.DataFrame(rows)


# ----------------------------------------------------------------------------- K3

def mine_or_load_k3_candidates(close, disc, t0):
    """Incremental K3 candidate mining. Each yearly anchor is mined once and
    appended to the cache; already-mined anchors are reused unchanged."""
    anchors = [pd.Timestamp(f"{y}-01-01") for y in range(2015, int(close.index.max().year) + 1)]
    existing = pd.read_csv(K3_CANDIDATES) if K3_CANDIDATES.exists() else pd.DataFrame()
    done = set(pd.to_datetime(existing["anchor"]).dt.normalize()) if len(existing) else set()
    missing = [a for a in anchors if a.normalize() not in done]
    if not missing:
        print(f"[k3-mine] all {len(anchors)} anchors cached; nothing to mine", flush=True)
        return existing
    print(f"[k3-mine] mining {len(missing)} new anchor(s): {[a.date().isoformat() for a in missing]}", flush=True)
    labs = eng.compute_labels(close.reindex(disc.index).ffill().astype(float))
    new_rows = []
    for a in missing:
        i = anchors.index(a)
        nxt = anchors[i + 1] if i + 1 < len(anchors) else close.index.max() + pd.Timedelta(days=1)
        progress(40, f"mining anchor {a.date()}", t0)
        cand = eng.mine_anchor_candidates(a, nxt, disc, labs)
        if len(cand):
            new_rows.append(cand)
    if new_rows:
        existing = pd.concat([existing, *new_rows], ignore_index=True)
        existing.to_csv(K3_CANDIDATES, index=False)
    return existing


def k3_target_k(regime: str, scored_valid_count: int) -> int:
    if regime in {"HIGH", "EXTREME"}:
        return max(1, int(math.ceil(max(scored_valid_count, 1) ** (1.0 / 3.0))))  # cbrtM
    return K_REF


def _bit_corr(a, b) -> float:
    a = a.astype(float)
    b = b.astype(float)
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def select_k3_state(close, disc, candidates, vol_zscore, t0):
    """Score + select cbrtM motifs per anchor and build the daily K3 evidence
    state (E / score / expanding-rank). Fast: no mining here."""
    labs = eng.compute_labels(close.reindex(disc.index).ffill().astype(float))
    anchors = [pd.Timestamp(f"{y}-01-01") for y in range(2015, int(close.index.max().year) + 1)]
    sels = []
    for anchor in anchors:
        cand = candidates[candidates.anchor.eq(anchor.strftime("%Y-%m-%d")) | candidates.anchor.eq(anchor)]
        sub = cand.drop_duplicates(["anchor", "best_combo"]).copy()
        if sub.empty:
            continue
        for col in ["best_ff_hr", "best_no_hr", "rule_count"]:
            sub[col] = pd.to_numeric(sub[col], errors="coerce").fillna(0.0)
        sub = sub.sort_values(["rule_count", "best_ff_hr", "best_no_hr"], ascending=False).head(eng.TOP_CANDIDATES_TO_SCORE)
        train = (disc.index <= anchor - pd.Timedelta(days=eng.H)) & labs["valid"]
        scored = []
        for _, row in sub.iterrows():
            mask = eng.combo_mask(disc, row.best_combo)
            tq = eng.train_quality(mask, labs, disc.index, anchor)
            if not tq["is_bull_continuation"]:
                continue
            vec = mask & train
            if int(vec.sum()) < 2:
                continue
            scored.append({**row.to_dict(), **tq, "corr_vec": vec})
        vz = float(vol_zscore.asof(anchor)) if not pd.isna(vol_zscore.asof(anchor)) else np.nan
        regime = v3._get_vol_regime(vz)
        scored_valid_count = len(scored)
        top_k = k3_target_k(regime, scored_valid_count)
        chosen = []
        for r in sorted(scored, key=lambda r: (r["selection_score"], r["train_ff_n"], r["rule_count"]), reverse=True):
            if all(abs(_bit_corr(r["corr_vec"], c["corr_vec"])) <= RHO_MAX for c in chosen):
                chosen.append(r)
            if len(chosen) >= top_k:
                break
        for r in chosen:
            r.pop("corr_vec", None)
            r["regime"] = regime
            r["scored_valid_count"] = scored_valid_count
            r["target_k"] = top_k
            r["k3_mode"] = K3_MODE
        if chosen:
            sels.append(pd.DataFrame(chosen))
        print(f"[k3-select] {anchor.date()} regime={regime} M={scored_valid_count} selected={len(chosen)} target={top_k}", flush=True)
    selected = pd.concat(sels, ignore_index=True) if sels else pd.DataFrame()
    cols = {
        "bull_continuation_active": np.zeros(len(disc)),
        "bull_continuation_firstfire": np.zeros(len(disc)),
        "bull_continuation_decay_score": np.zeros(len(disc)),
    }
    for _, row in selected.iterrows():
        anchor = pd.Timestamp(row.anchor)
        if anchor not in anchors:
            continue
        ai = anchors.index(anchor)
        nxt = anchors[ai + 1] if ai + 1 < len(anchors) else close.index.max() + pd.Timedelta(days=1)
        interval = (disc.index >= anchor) & (disc.index < nxt)
        mask = eng.combo_mask(disc, row.best_combo)
        ff = eng.first_fire(mask)
        fmask = np.zeros(len(disc), dtype=bool)
        fmask[ff] = True
        fmask &= interval
        cols["bull_continuation_active"] += (mask & interval).astype(float)
        cols["bull_continuation_firstfire"] += fmask.astype(float)
        w = float(row.weight_used)
        for tt in np.flatnonzero(fmask):
            end = min(len(disc), tt + eng.MAX_LIFE + 1)
            d = np.arange(end - tt)
            cols["bull_continuation_decay_score"][tt:end] += w * np.exp(-d / eng.HALFLIFE)
    st = pd.DataFrame(cols, index=disc.index)
    st["btc_close"] = close.reindex(disc.index).ffill()
    st["E"] = np.tanh(st["bull_continuation_decay_score"] / 3.0).clip(0, 1)
    st["score"] = (0.5 + 0.5 * st["E"]).clip(0, 1)
    st["rank"] = eng.expanding_percentile(st["score"])
    return st, selected


# -------------------------------------------------------------------------- output

def _direction(final_exp: float, base_exp: float) -> str:
    if final_exp > base_exp + 1e-9:
        return "UP"
    if final_exp < base_exp - 1e-9:
        return "DOWN"
    return "NEUTRAL"


def main():
    t0 = time.time()
    progress(2, "loading production data (BTC / CryptoQuant / FRED / Yahoo)", t0)
    close, base_disc, fwd, vol = v3._load_production_data()
    close = close.astype(float).sort_index()
    base_disc = base_disc.sort_index()

    progress(10, "rebuilding extended 138-signal matrix", t0)
    ext_disc, manifest = eng.build_extended_disc(v3, close, base_disc, None)
    fwd_ext = v3._mod.compute_forward_returns(close).reindex(ext_disc.index)
    vol_ext = vol.reindex(ext_disc.index).ffill()

    progress(15, "computing K10/sqrtN base exposure", t0)
    combo, base_exp, corr = run_base(close, ext_disc, fwd_ext, vol_ext, t0)

    candidates = mine_or_load_k3_candidates(close, ext_disc, t0)

    progress(70, "selecting cbrtM motifs + building K3 daily state", t0)
    st, selected = select_k3_state(close, ext_disc, candidates, vol_ext, t0)

    progress(85, "applying one-step 10/high-dynamic +20/-20 overlay", t0)
    overlay = eng.one_step_overlay(base_exp, st["rank"], K3_LOW, K3_HIGH, ADD, TRIM)

    base_bt = eng.backtest_from_exposure(close, base_exp)
    full_bt = eng.backtest_from_exposure(close, overlay)
    base_m = eng.metrics_row("base K10/sqrtN", base_bt, EVAL_START)
    full_m = eng.metrics_row("V4 base + K3 cbrtM", full_bt, EVAL_START, base_bt["port_ret"])

    latest = overlay.index.max()
    st_latest = st.reindex([latest]).iloc[0]
    base_latest = float(base_exp.reindex([latest]).ffill().iloc[0])
    final_latest = float(overlay.loc[latest])

    state = {
        "date": str(latest.date()),
        "btc_price": float(close.reindex([latest]).ffill().iloc[0]),
        "base_exposure": round(base_latest, 6),
        "exposure": round(final_latest, 6),
        "overlay_delta": round(final_latest - base_latest, 6),
        "direction": _direction(final_latest, base_latest),
        "k3_E": float(st_latest["E"]),
        "k3_score": float(st_latest["score"]),
        "k3_rank": float(st_latest["rank"]),
        "base_sharpe": float(base_m["sharpe"]),
        "strategy_sharpe": float(full_m["sharpe"]),
        "sharpe_delta": float(full_m["d_sharpe_vs_v3"]),
        "annual_return": float(full_m["annual_return"]),
        "max_drawdown": float(full_m["max_drawdown"]),
        "avg_exposure": float(full_m["avg_exposure"]),
        "k3_mode": K3_MODE,
        "k3_low": K3_LOW,
        "k3_high": round(K3_HIGH, 6),
        "n_universe": N_UNIVERSE,
        "selected_motifs": int(len(selected)),
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
    }

    (DATA / "cycle_state.json").write_text(json.dumps(state, indent=2) + "\n")

    # append-or-replace today's row in history
    hist_p = DATA / "cycle_history.json"
    hist = json.loads(hist_p.read_text()) if hist_p.exists() else []
    hist = [h for h in hist if h.get("date") != state["date"]]
    hist.append(state)
    hist.sort(key=lambda h: h["date"])
    hist_p.write_text(json.dumps(hist, indent=2) + "\n")

    daily = pd.DataFrame(index=close.index)
    daily["btc_close"] = close
    daily["base138_exposure"] = base_exp.reindex(close.index)
    daily["k3_rank_cbrtM"] = st["rank"].reindex(close.index)
    daily["overlay_exposure_cbrtM"] = overlay.reindex(close.index)
    daily.to_csv(DATA / "daily.csv", index_label="date")

    print("\n=== V4 cycle_state ===", flush=True)
    print(json.dumps(state, indent=2), flush=True)
    print(f"\nWrote {DATA}  elapsed_min={round((time.time() - t0) / 60, 2)}", flush=True)


if __name__ == "__main__":
    main()
