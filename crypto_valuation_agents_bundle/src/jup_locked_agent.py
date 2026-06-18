#!/usr/bin/env python3
"""Standalone JUP locked valuation runner.

The canonical JUP model lives in webapp/agents/jup.py so the dashboard and
locked report cannot drift. This wrapper runs that model, then writes the
src/ artifacts expected by the bundle.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
WEBAPP_ROOT = BUNDLE_ROOT / "webapp"
for p in (BUNDLE_ROOT, WEBAPP_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from agents import jup

OUTDIR = Path(__file__).resolve().parent


def fmt_money(x: float) -> str:
    ax = abs(float(x))
    if ax >= 1e9:
        return f"${x / 1e9:.2f}B"
    if ax >= 1e6:
        return f"${x / 1e6:.1f}M"
    if ax >= 1e3:
        return f"${x / 1e3:.1f}K"
    return f"${x:.3f}"


def fmt_pct(x) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:+.1f}%"


def write_report(res: dict) -> str:
    market = res["market"]
    gp = res["current_gp"]
    delta = gp.get("y3_vs_current_pct", {})
    scenarios = res["scenarios"]
    primary = next((s for s in scenarios if s.get("is_primary")), scenarios[-1])
    lines = [
        f"**JUP locked valuation refresh — {res['as_of_utc'][:10]}**",
        "",
        "```text",
        "KEY ASSUMPTIONS / LIVE SEEDS",
        f"Spot / MCap / FDV       ${market['spot']:.4f} / {fmt_money(market['market_cap'])} / {fmt_money(market['fdv'])}",
        f"Circ supply             {market['circulating_supply'] / 1e9:.2f}B JUP",
        f"Discount / multiple     {res['model']['discount_rate'] * 100:.1f}% / {res['model']['multiple']:.0f}x Y3 TTM entity GP",
        "Perps model             Binance Futures volume x JUP/Binance share x clean take-rate",
        "Spot model              Binance spot volume x JUP/Binance share x observed rake",
        f"Perps MS30 / MS90       {gp.get('perps_ms30_vs_binance_futures', 0) * 100:.2f}% / {gp.get('perps_ms90_vs_binance_futures', 0) * 100:.2f}%",
        f"Spot MS30 / MS90        {gp.get('spot_ms30_vs_binance_spot', 0) * 100:.2f}% / {gp.get('spot_ms90_vs_binance_spot', 0) * 100:.2f}%",
        f"Perps clean take-rate   {gp.get('perps_clean_take_rate_bps', 0):.2f} bps",
        f"Spot rake               {gp.get('spot_take_rate_bps', 0):.2f} bps",
        f"Buybacks                50% modeled entity GP at current spot",
        "Scheduled unlocks       0 JUP/mo until a public reserve distribution plan",
        "```",
        "",
        "```text",
        "RESULTS — discounted PV / JUP",
        "Case              P25    P50    P75    P90    EV     P>spot 2Y+30 2Y-30",
    ]
    for s in scenarios:
        pv = s["pv"]
        lines.append(
            f"{s['label'][:16]:<16} "
            f"${pv['p25']:.3f} ${pv['p50']:.3f} ${pv['p75']:.3f} ${pv['p90']:.3f} "
            f"${s['ev']:.3f} {s['prob_above_spot'] * 100:5.1f}% "
            f"{s['prob_spot_up_30_2y'] * 100:5.1f}% {s['prob_spot_down_30_2y'] * 100:5.1f}%"
        )
    lines.extend([
        "```",
        "",
        "```text",
        "P50 MODEL STATE / PRODUCT SPLIT",
        f"Primary case                 {primary['label']}",
        f"Primary P50 / EV             ${primary['pv']['p50']:.3f} / ${primary['ev']:.3f}",
        f"Y3 TTM entity GP P50         {fmt_money(gp['y3_gp_p50'])}",
        f"  vs current annualized GP   {fmt_pct(delta.get('entity_gp_pct'))}",
        f"  Perps GP P50               {fmt_money(gp['y3_perps_gp_p50'])} ({fmt_pct(delta.get('perps_gp_pct'))} vs current)",
        f"  Spot/Agg+Jupiterz GP P50   {fmt_money(gp['y3_spot_gp_p50'])} ({fmt_pct(delta.get('spot_gp_pct'))} vs current)",
        f"Y3 perps daily volume P50    {fmt_money(gp['y3_perps_daily_mean_volume_p50'])}/day ({fmt_pct(delta.get('perps_daily_volume_pct'))} vs current)",
        f"Y3 spot daily volume P50     {fmt_money(gp['y3_spot_daily_mean_volume_p50'])}/day ({fmt_pct(delta.get('spot_daily_volume_pct'))} vs current)",
        f"Y3 effective supply P50      {gp['y3_supply_p50'] / 1e9:.2f}B JUP ({fmt_pct(delta.get('effective_supply_pct'))} vs current)",
        f"P50 buyback accumulation     {gp['buyback_tokens_p50'] / 1e6:.0f}M JUP",
        "```",
    ])
    if res.get("caveats"):
        lines.extend(["", "Caveats:"])
        lines.extend(f"- {c}" for c in res["caveats"])
    return "\n".join(lines)


def main() -> dict:
    res = jup.run()
    json_path = OUTDIR / "jup_locked_result.json"
    md_path = OUTDIR / "jup_locked_report.md"
    out = {
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "canonical_model": "crypto_valuation_agents_bundle/webapp/agents/jup.py",
        "result": res,
    }
    with open(json_path, "w") as f:
        json.dump(out, f, indent=2)
    report = write_report(res)
    with open(md_path, "w") as f:
        f.write(report + "\n")
    print(report)
    print(f"\nSaved: {json_path}")
    print(f"Saved: {md_path}")
    return out


if __name__ == "__main__":
    main()
