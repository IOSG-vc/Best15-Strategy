#!/usr/bin/env python3
"""
Generate daily equity/exposure/gate/event JSON for the crash-gate overlay charts.
Input:  cyclesignal-v4/data/daily.csv  (has date, btc_close, overlay_exposure_cbrtM)
Output: data/crash_cluster_daily.json
"""
import math, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
INP  = ROOT / "cyclesignal-v4/data/daily.csv"
OUT  = ROOT / "data/crash_cluster_daily.json"

ANN  = 365.25
COST = 0.001

VARIANTS = {
    "A_locked_SH": dict(vol_window=180, z_threshold=1.5, half_life=126, jump=0.20, floor=0.15, midpoint=2.0, slope=5.0),
    "B_floor35":   dict(vol_window=180, z_threshold=1.5, half_life=126, jump=0.20, floor=0.35, midpoint=2.0, slope=5.0),
    "C_strong":    dict(vol_window=365, z_threshold=1.5, half_life=91,  jump=0.35, floor=0.15, midpoint=2.0, slope=5.0),
}

def load_base():
    df = pd.read_csv(INP, parse_dates=["date"]).set_index("date").sort_index()
    df = df.loc["2020-01-01":"2026-06-10"].copy()
    df.index = df.index.tz_localize(None).normalize()
    df["btc_return"] = df["btc_close"].pct_change().fillna(0.0)
    df["baseline_exposure"] = df["overlay_exposure_cbrtM"].astype(float)
    return df

def intensity_gate(r, p):
    minp = min(p["vol_window"], max(30, p["vol_window"] // 4))
    vol = r.rolling(p["vol_window"], min_periods=minp).std().replace(0, np.nan)
    z = r / vol
    event = (z <= -p["z_threshold"]).astype(float).fillna(0.0)
    decay = math.exp(-math.log(2) / p["half_life"])
    vals, inten = [], 0.0
    for ev in event.shift(1).fillna(0.0).values:
        inten = decay * inten + p["jump"] * float(ev)
        vals.append(float(inten))
    intensity = pd.Series(vals, index=r.index)
    gate = (p["floor"] + (1 - p["floor"]) / (1 + np.exp(p["slope"] * (intensity - p["midpoint"])))).clip(p["floor"], 1.0)
    return event, intensity, gate

def build(df):
    r        = df["btc_return"]
    base_exp = df["baseline_exposure"]

    base_to  = base_exp.diff().abs().fillna(0.0)
    base_ret = base_exp.shift(1).fillna(base_exp.iloc[0]) * r - base_to * COST
    base_eq  = (1 + base_ret).cumprod()

    rows = []
    var_data = {}

    for name, p in VARIANTS.items():
        event, inten, gate = intensity_gate(r, p)
        exp    = base_exp * gate
        to     = exp.diff().abs().fillna(0.0)
        ret    = exp.shift(1).fillna(exp.iloc[0]) * r - to * COST
        eq     = (1 + ret).cumprod()
        var_data[name] = {"eq": eq, "exp": exp, "gate": gate, "event": event}

    for date in df.index:
        ds = date.strftime("%Y-%m-%d")
        row = {
            "date": ds,
            "btc_close": round(float(df.loc[date, "btc_close"]), 2),
            "equity_baseline": round(float(base_eq.loc[date]), 4),
            "exposure_baseline": round(float(base_exp.loc[date]), 4),
            "crash_event": 0,
        }
        for name, d in var_data.items():
            row[f"equity_{name}"]   = round(float(d["eq"].loc[date]), 4)
            row[f"exposure_{name}"] = round(float(d["exp"].loc[date]), 4)
            row[f"gate_{name}"]     = round(float(d["gate"].loc[date]), 4)
            if d["event"].loc[date] == 1.0:
                row["crash_event"] = 1
        rows.append(row)

    return rows

def main():
    df   = load_base()
    rows = build(df)
    crash_dates = [r["date"] for r in rows if r["crash_event"] == 1]
    out = {
        "generatedAt": "2026-06-28",
        "crashEvents": crash_dates,
        "daily": rows,
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(f"Wrote {len(rows)} rows, {len(crash_dates)} crash events → {OUT}")

if __name__ == "__main__":
    main()
