#!/usr/bin/env python3
"""
ETF 80:20 Methodology — 2026 OOS Attribution Analysis
======================================================
Compares the ETF strategy vs BTC for the 2026 OOS period and decomposes
the performance delta into:
  1. Size / liquidity factor  (em_b → em_lq)
  2. Risk constraints         (em_b → em_mv, minimum-variance overlay)
  3. Technical signals        (em_mv → em_tc)

Counts weekly and monthly return/Sharpe wins vs BTC.

Data coverage: live tracking starts 2026-05-01.
For Jan–Apr 2026, run the production backtest engine and append results
to performance.json before running this script.

Usage:
    python scripts/etf_2026_oos_analysis.py

Output:
    Prints attribution table and win-rate scorecards to stdout.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

# ── Config ──────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent
PERF_FILE = REPO_ROOT / "data" / "performance.json"

OOS_START = pd.Timestamp("2026-01-01")

ANN_DAYS = 365.0

# ETF factor chain: each step adds one methodology feature
# em_b  → MCAP-weighted altcoin basket (no frills)
# em_lq → + liquidity / small-cap filter (size factor)
# em_mv → + minimum-variance optimization (risk constraints)
# em_tc → + BTC technical cycle signals (tech signals)
# etf   → final production ETF (same as em_tc + BTC cap)
FACTOR_CHAIN = [
    ("em_b",  "ETF Base (MCAP)"),
    ("em_lq", "ETF + Liq/Size Filter"),
    ("em_mv", "ETF + Min-Var (risk)"),
    ("em_tc", "ETF + Tech Signals"),
    ("etf",   "ETF Final (production)"),
]

BTC_ASSET_KEY = "bitcoin"

# ── Helpers ─────────────────────────────────────────────────────────────────


def load_series(perf: dict, key: str, source: str = "strategies") -> pd.Series | None:
    """Return a daily-return pd.Series from performance.json."""
    try:
        dd = perf[source][key]["dailyData"]
    except KeyError:
        return None
    if not dd:
        return None
    s = pd.Series(
        {pd.Timestamp(r["date"]): r["return"] for r in dd},
        name=key,
        dtype=float,
    )
    return s[s.index >= OOS_START].sort_index()


def load_btc_series(perf: dict) -> pd.Series | None:
    """BTC asset is stored as cumReturn, derive daily returns."""
    try:
        dd = perf["assets"][BTC_ASSET_KEY]["dailyData"]
    except KeyError:
        return None
    cum = pd.Series(
        {pd.Timestamp(r["date"]): r["cumReturn"] for r in dd},
        dtype=float,
    ).sort_index()
    cum = cum[cum.index >= OOS_START]
    ret = cum.pct_change().dropna()
    ret.name = "bitcoin"
    return ret


def metrics(ret: pd.Series) -> dict:
    if len(ret) < 3:
        return {}
    total = (1 + ret).prod() - 1
    n_days = max((ret.index[-1] - ret.index[0]).days, 1)
    ann_factor = ANN_DAYS / n_days
    ann_ret = (1 + total) ** ann_factor - 1
    vol = ret.std() * np.sqrt(ANN_DAYS)
    down = ret[ret < 0].std() * np.sqrt(ANN_DAYS)
    cum = (1 + ret).cumprod()
    max_dd = (cum / cum.cummax() - 1).min()
    sharpe = ann_ret / vol if vol > 0 else np.nan
    sortino = ann_ret / down if down > 0 else np.nan
    return {
        "total_ret_pct": round(total * 100, 2),
        "ann_ret_pct":   round(ann_ret * 100, 2),
        "vol_pct":       round(vol * 100, 2),
        "sharpe":        round(sharpe, 3),
        "sortino":       round(sortino, 3),
        "max_dd_pct":    round(max_dd * 100, 2),
        "n_days":        len(ret),
    }


def weekly_wins(strat: pd.Series, bench: pd.Series) -> tuple[int, int, int, int]:
    """Return (return_wins, return_total, sharpe_wins, sharpe_total)."""
    aligned = pd.DataFrame({"strat": strat, "bench": bench}).dropna()
    weekly = aligned.resample("W-FRI")

    ret_wins, ret_total = 0, 0
    sharpe_wins, sharpe_total = 0, 0

    for _, wk in weekly:
        if len(wk) < 3:
            continue
        s_ret = (1 + wk["strat"]).prod() - 1
        b_ret = (1 + wk["bench"]).prod() - 1
        ret_total += 1
        if s_ret > b_ret:
            ret_wins += 1

        s_vol = wk["strat"].std() * np.sqrt(ANN_DAYS / 7)
        b_vol = wk["bench"].std() * np.sqrt(ANN_DAYS / 7)
        s_sr = s_ret / s_vol if s_vol > 0 else np.nan
        b_sr = b_ret / b_vol if b_vol > 0 else np.nan
        if not (np.isnan(s_sr) or np.isnan(b_sr)):
            sharpe_total += 1
            if s_sr > b_sr:
                sharpe_wins += 1

    return ret_wins, ret_total, sharpe_wins, sharpe_total


def monthly_wins(strat: pd.Series, bench: pd.Series) -> tuple[int, int, int, int]:
    """Return (return_wins, return_total, sharpe_wins, sharpe_total)."""
    aligned = pd.DataFrame({"strat": strat, "bench": bench}).dropna()
    monthly = aligned.resample("ME")

    ret_wins, ret_total = 0, 0
    sharpe_wins, sharpe_total = 0, 0

    for period, mo in monthly:
        if len(mo) < 5:
            continue
        s_ret = (1 + mo["strat"]).prod() - 1
        b_ret = (1 + mo["bench"]).prod() - 1
        ret_total += 1
        if s_ret > b_ret:
            ret_wins += 1

        s_vol = mo["strat"].std() * np.sqrt(ANN_DAYS)
        b_vol = mo["bench"].std() * np.sqrt(ANN_DAYS)
        s_sr = s_ret / s_vol if s_vol > 0 else np.nan
        b_sr = b_ret / b_vol if b_vol > 0 else np.nan
        if not (np.isnan(s_sr) or np.isnan(b_sr)):
            sharpe_total += 1
            if s_sr > b_sr:
                sharpe_wins += 1

    return ret_wins, ret_total, sharpe_wins, sharpe_total


def incremental_contribution(chain_series: list[tuple[str, pd.Series]]) -> list[dict]:
    """Compute marginal return contribution of each factor step."""
    results = []
    for i, (label, s) in enumerate(chain_series):
        tot = (1 + s).prod() - 1
        if i == 0:
            incr = tot
        else:
            prev_tot = (1 + chain_series[i - 1][1]).prod() - 1
            incr = tot - prev_tot
        results.append({
            "step": label,
            "total_ret_pct": round(tot * 100, 2),
            "incremental_pp": round(incr * 100, 2),
        })
    return results


def sep(char="─", width=72) -> str:
    return char * width


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    with PERF_FILE.open() as f:
        perf = json.load(f)

    # ── Load series ──────────────────────────────────────────────────────────
    btc = load_btc_series(perf)
    if btc is None or len(btc) == 0:
        print("ERROR: BTC data not found in performance.json")
        return

    chain_series: list[tuple[str, pd.Series]] = []
    for key, label in FACTOR_CHAIN:
        s = load_series(perf, key)
        if s is None:
            print(f"  ! {key} not found — skipping")
            continue
        chain_series.append((label, s))

    data_start = btc.index[0].date()
    data_end   = btc.index[-1].date()

    print()
    print(sep("═"))
    print(f"  ETF 2026 OOS Attribution Analysis")
    print(f"  Data period: {data_start}  →  {data_end}  ({len(btc)} BTC trading days)")
    print(f"  NOTE: Live tracking started 2026-05-01. For full Jan–Apr coverage,")
    print(f"        re-run the production strategy engine and refresh performance.json.")
    print(sep("═"))

    # ── Section 1: Overall metrics ────────────────────────────────────────────
    print()
    print("1. OVERALL PERIOD METRICS (2026 OOS)")
    print(sep())
    print(f"  {'Strategy':<35} {'Total%':>8} {'AnnRet%':>9} {'Vol%':>7} {'Sharpe':>8} {'MaxDD%':>8} {'Days':>5}")
    print(f"  {'-'*35} {'-------':>8} {'-------':>9} {'-----':>7} {'------':>8} {'------':>8} {'----':>5}")

    # BTC line
    bm = metrics(btc)
    print(f"  {'BTC (benchmark)':<35} {bm['total_ret_pct']:>8.2f} {bm['ann_ret_pct']:>9.2f} {bm['vol_pct']:>7.2f} {bm['sharpe']:>8.3f} {bm['max_dd_pct']:>8.2f} {bm['n_days']:>5}")

    for label, s in chain_series:
        # Align to same date range as BTC
        common = s.reindex(btc.index).dropna()
        m = metrics(common)
        if not m:
            continue
        vs_btc = m["total_ret_pct"] - bm["total_ret_pct"]
        flag = " ✓" if vs_btc > 0 else " ✗"
        print(f"  {label:<35} {m['total_ret_pct']:>8.2f} {m['ann_ret_pct']:>9.2f} {m['vol_pct']:>7.2f} {m['sharpe']:>8.3f} {m['max_dd_pct']:>8.2f} {m['n_days']:>5}  ({vs_btc:+.2f}pp){flag}")

    # ── Section 2: Factor attribution ─────────────────────────────────────────
    print()
    print("2. FACTOR ATTRIBUTION — INCREMENTAL RETURN CONTRIBUTION")
    print(sep())
    print("   Each row shows how much return was ADDED (or lost) by adding that feature.")
    print()
    print(f"  {'Step':<35} {'Total%':>8} {'Incremental pp':>16}")
    print(f"  {'-'*35} {'-------':>8} {'---------------':>16}")

    aligned_chain = []
    for label, s in chain_series:
        aligned_chain.append((label, s.reindex(btc.index).dropna()))
    contribs = incremental_contribution(aligned_chain)

    for row in contribs:
        sign = "+" if row["incremental_pp"] >= 0 else ""
        arrow = "▲" if row["incremental_pp"] > 0 else "▼"
        print(f"  {row['step']:<35} {row['total_ret_pct']:>8.2f} {sign}{row['incremental_pp']:>14.2f} pp  {arrow}")

    # Summary
    print()
    print("   Attribution breakdown (vs ETF Base):")
    if len(contribs) >= 4:
        base = contribs[0]["total_ret_pct"]
        for row in contribs[1:]:
            delta = row["total_ret_pct"] - base
            print(f"   • {row['step']:<33}: {delta:+.2f} pp vs Base")

    # ── Section 3: Weekly win/loss scorecard ──────────────────────────────────
    etf_prod = None
    for label, s in chain_series:
        if "Final" in label or "production" in label.lower():
            etf_prod = s
            break
    if etf_prod is None and chain_series:
        etf_prod = chain_series[-1][1]

    etf_aligned = etf_prod.reindex(btc.index).dropna()

    print()
    print("3. WEEKLY WIN RATE vs BTC (ETF Final vs BTC)")
    print(sep())
    r_w, r_n, sh_w, sh_n = weekly_wins(etf_aligned, btc)
    print(f"   Return wins:  {r_w}/{r_n} weeks  ({100*r_w/r_n:.0f}% win rate)" if r_n > 0 else "   Not enough weeks")
    print(f"   Sharpe wins:  {sh_w}/{sh_n} weeks  ({100*sh_w/sh_n:.0f}% win rate)" if sh_n > 0 else "   Not enough weeks")

    # By-week detail
    aligned = pd.DataFrame({"etf": etf_aligned, "btc": btc}).dropna()
    print()
    print(f"   {'Week ending':<14} {'ETF%':>8} {'BTC%':>8} {'Delta pp':>10} {'Winner':>8}")
    print(f"   {'----------':<14} {'----':>8} {'----':>8} {'---------':>10} {'------':>8}")
    for period, wk in aligned.resample("W-FRI"):
        if len(wk) < 3:
            continue
        s_ret = (1 + wk["etf"]).prod() - 1
        b_ret = (1 + wk["btc"]).prod() - 1
        delta = (s_ret - b_ret) * 100
        winner = "ETF ✓" if s_ret > b_ret else "BTC  ✗"
        print(f"   {str(period.date()):<14} {s_ret*100:>8.2f} {b_ret*100:>8.2f} {delta:>+10.2f} {winner:>8}")

    # ── Section 4: Monthly win/loss scorecard ─────────────────────────────────
    print()
    print("4. MONTHLY WIN RATE vs BTC (ETF Final vs BTC)")
    print(sep())
    r_w, r_n, sh_w, sh_n = monthly_wins(etf_aligned, btc)
    print(f"   Return wins:  {r_w}/{r_n} months  ({100*r_w/r_n:.0f}% win rate)" if r_n > 0 else "   Not enough months")
    print(f"   Sharpe wins:  {sh_w}/{sh_n} months  ({100*sh_w/sh_n:.0f}% win rate)" if sh_n > 0 else "   Not enough months")

    print()
    print(f"   {'Month':<14} {'ETF%':>8} {'BTC%':>8} {'Delta pp':>10} {'Winner':>8}")
    print(f"   {'-----':<14} {'----':>8} {'----':>8} {'---------':>10} {'------':>8}")
    for period, mo in aligned.resample("ME"):
        if len(mo) < 5:
            continue
        s_ret = (1 + mo["etf"]).prod() - 1
        b_ret = (1 + mo["btc"]).prod() - 1
        delta = (s_ret - b_ret) * 100
        winner = "ETF ✓" if s_ret > b_ret else "BTC  ✗"
        label_str = period.strftime("%Y-%m")
        print(f"   {label_str:<14} {s_ret*100:>8.2f} {b_ret*100:>8.2f} {delta:>+10.2f} {winner:>8}")

    # ── Section 5: Factor attribution by month ────────────────────────────────
    print()
    print("5. FACTOR ATTRIBUTION BY MONTH")
    print(sep())
    header = f"  {'Month':<12}"
    for label, _ in aligned_chain:
        short = label.split("(")[0].strip()[:13]
        header += f"  {short:>13}"
    header += f"  {'BTC':>8}"
    print(header)
    print(f"  {'-'*12}" + "  " + "  ".join([f"{'-----':>13}"] * len(aligned_chain)) + f"  {'---':>8}")

    monthly_btc = btc.resample("ME").apply(lambda x: (1 + x).prod() - 1) * 100

    for period, _ in btc.resample("ME"):
        row_str = f"  {period.strftime('%Y-%m'):<12}"
        for label, s in aligned_chain:
            month_s = s[(s.index >= period.replace(day=1)) & (s.index <= period)]
            if len(month_s) >= 5:
                ret = (1 + month_s).prod() - 1
                row_str += f"  {ret*100:>13.2f}"
            else:
                row_str += f"  {'  n/a':>13}"
        btc_mo = monthly_btc.get(period, np.nan)
        row_str += f"  {btc_mo:>8.2f}" if not np.isnan(btc_mo) else f"  {'n/a':>8}"
        print(row_str)

    # ── Section 6: Key findings ────────────────────────────────────────────────
    print()
    print("6. KEY FINDINGS")
    print(sep())
    if len(contribs) >= 4:
        base_tot = contribs[0]["total_ret_pct"]
        final_tot = contribs[-1]["total_ret_pct"]
        btc_tot = bm["total_ret_pct"]
        delta_vs_btc = final_tot - btc_tot

        size_liq_delta = contribs[1]["total_ret_pct"] - contribs[0]["total_ret_pct"] if len(contribs) > 1 else 0
        minvar_delta   = contribs[2]["total_ret_pct"] - contribs[0]["total_ret_pct"] if len(contribs) > 2 else 0
        tech_delta     = contribs[3]["total_ret_pct"] - contribs[2]["total_ret_pct"] if len(contribs) > 3 else 0

        print(f"   ETF Final vs BTC:    {delta_vs_btc:+.2f} pp  ({'outperformed' if delta_vs_btc > 0 else 'underperformed'})")
        print(f"   Base (MCAP) vs BTC:  {base_tot - btc_tot:+.2f} pp")
        print()
        print(f"   Performance delta decomposition (ETF Final vs Base):")
        print(f"     Size / Liq filter:   {size_liq_delta:+.2f} pp")
        print(f"     Risk constraints (MinVar): {minvar_delta:+.2f} pp  (vs Base)")
        print(f"     Technical signals:   {tech_delta:+.2f} pp  (vs MinVar)")
        print()
        print(f"   Note: positive = feature ADDED return; negative = feature COST return")

    print()
    print(sep("═"))
    print("  END OF REPORT")
    print(sep("═"))
    print()
    print("  To extend to full 2026 (Jan–Apr), run the production backtest engine:")
    print("    python scripts/Production_v3_k3_one_step_10_90_add20_138.py")
    print("  then refresh performance.json with update_performance.py.")
    print()


if __name__ == "__main__":
    main()
