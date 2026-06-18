#!/usr/bin/env python3
"""Compatibility runner for the canonical SKY valuation agent.

The maintained SKY model lives in ``webapp/agents/sky.py`` because the webapp
and aggregate valuation pipeline consume that standardized result shape.  This
entrypoint preserves the older ``src/sky_mc_agent.py`` command while avoiding a
second, stale implementation with locked supply inputs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


BUNDLE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = Path(__file__).resolve().parent
RESULT_JSON = SRC_DIR / "sky_mc_result.json"
RESULT_MD = SRC_DIR / "sky_mc_result.md"

sys.path.insert(0, str(BUNDLE_ROOT / "webapp" / "agents"))

import sky  # noqa: E402


def _fmt_usd(x: float) -> str:
    if abs(x) >= 1e9:
        return f"${x / 1e9:.2f}B"
    if abs(x) >= 1e6:
        return f"${x / 1e6:.1f}M"
    return f"${x:.2f}"


def _primary_scenario(result: dict) -> dict:
    scenarios = result.get("scenarios", [])
    return next((s for s in scenarios if s.get("is_primary")), scenarios[0])


def main() -> None:
    result = sky.run()
    primary = _primary_scenario(result)
    current_gp = result["current_gp"]

    RESULT_JSON.write_text(json.dumps(result, indent=2) + "\n")

    lines = [
        "# SKY MC valuation",
        "",
        f"As of: {result['as_of_utc']}",
        "",
        "## Primary scenario",
        "",
        "```text",
        f"Scenario                           {primary['label']}",
        f"P50 PV                             ${primary['pv']['p50']:.4f}",
        f"P25 / P75 / P90                    ${primary['pv']['p25']:.4f} / ${primary['pv']['p75']:.4f} / ${primary['pv']['p90']:.4f}",
        f"EV                                 ${primary['ev']:.4f}",
        f"P(above spot)                      {primary['prob_above_spot'] * 100:.1f}%",
        f"2Y +30% / -30%                     {primary['prob_spot_up_30_2y'] * 100:.1f}% / {primary['prob_spot_down_30_2y'] * 100:.1f}%",
        f"Y3 GP P50                          {_fmt_usd(primary['y3_gp_p50'])}",
        f"Y3 total Sky stable supply P50      {_fmt_usd(primary['y3_total_stable_supply_p50'])}",
        "```",
        "",
        "## Current assumptions",
        "",
        "```text",
        f"Official USDS supply                {_fmt_usd(current_gp['usds_supply'])}",
        f"Official DAI supply                 {_fmt_usd(current_gp['dai_supply'])}",
        f"Gross income take-rate              {current_gp['gross_income_take_rate_bps']:.1f} bps",
        f"Savings cost rate                   {current_gp['savings_cost_rate_bps']:.1f} bps",
        f"stUSDS cost rate                    {current_gp['stusds_cost_rate_bps']:.1f} bps",
        f"Net GP take-rate                    {current_gp['net_gp_take_rate_bps']:.1f} bps",
        f"Velocity ensemble                   {current_gp.get('velocity_ensemble_monthly', 0) * 100:.2f}%/mo",
        f"Discount / multiple                 {result['model']['discount_rate'] * 100:.0f}% / {result['model']['multiple']:.0f}x",
        "```",
        "",
        "## Caveats",
        "",
    ]
    lines.extend(f"- {caveat}" for caveat in result.get("caveats", []))
    RESULT_MD.write_text("\n".join(lines) + "\n")

    print(RESULT_JSON)
    print(RESULT_MD)
    print(
        f"SKY P50 PV ${primary['pv']['p50']:.4f}; "
        f"2Y +30% {primary['prob_spot_up_30_2y'] * 100:.1f}%; "
        f"2Y -30% {primary['prob_spot_down_30_2y'] * 100:.1f}%"
    )


if __name__ == "__main__":
    main()
