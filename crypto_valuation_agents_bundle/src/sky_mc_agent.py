#!/usr/bin/env python3
"""SKY 3Y GP / Net Profit MC valuation prototype.

Framework agreed with user:
- Gross income / fees - savings-rate cost = GP
- GP - OPEX = net profit / distributable profit
- DAI flat in base; USDS growth follows capped money-market/yield TVL path
- Show both 10x GP value and higher-multiple net-profit value, plus EV
"""
from __future__ import annotations

import json, math, os, random, statistics
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

OUTDIR = Path('/Users/momir_mini/.openclaw/workspace/altcoin_research')
EXTRA_PATH = OUTDIR / 'sky_research_extra.json'
DATA_PATH = OUTDIR / 'sky_data_collection.json'
JSON_OUT = OUTDIR / 'sky_mc_result.json'
MD_OUT = OUTDIR / 'sky_mc_result.md'

# User-confirmed / Sky info page inputs, 2026-05-08
SPOT = 0.08084
SKY_SUPPLY = 23.462665147e9  # near-FDV supply from CoinGecko
MCAP = 1.876588264e9
FDV = 1.896796712e9

USDS_SUPPLY = 6.426632076e9
DAI_SUPPLY = 4.165943911e9
SUSDS_SUPPLY = 5.218832683e9
SDAI_SUPPLY = 0.239828197e9
TOTAL_STABLE_SUPPLY = USDS_SUPPLY + DAI_SUPPLY

# Sky info financials: current exposure annualized
GROSS_INCOME = 425.2e6
SAVINGS_EXPENSE = 193.49e6
STUSDS_EXPENSE = 13.23e6
CURRENT_OPEX_SITE = 43.93e6
SITE_EARNINGS = 174.556743e6

# Derived current rates
GROSS_INCOME_YIELD = GROSS_INCOME / TOTAL_STABLE_SUPPLY
SAVINGS_RATE = 0.0365
USDS_SAVINGS_PENETRATION = SUSDS_SUPPLY / USDS_SUPPLY
DAI_SAVINGS_PENETRATION = SDAI_SUPPLY / DAI_SUPPLY
STUSDS_EXPENSE_RATE_ON_USDS = STUSDS_EXPENSE / USDS_SUPPLY

# Model assumptions
HORIZON_MONTHS = 36
DISCOUNT_RATE = 0.25
PATHS = 100_000
SEED = 42

# User-confirmed sensitivities
OPEX_SCENARIOS = {
    'bear_90m_opex': 90e6,
    'base_70m_opex': 70e6,
    'bull_50m_opex': 50e6,
}
GP_MULTIPLE = 10.0
NP_MULTIPLE_BASE = 15.0

# USDS growth path uses a capped monthly path because Sky has not proved it can
# scale like the broad money-market complex. There is intentionally no explicit
# 3Y USDS supply cap unless added later by the analyst.
MONTHLY_GROWTH_CAP_LOW = -0.08
MONTHLY_GROWTH_CAP_HIGH = 0.10
GROWTH_DAMPENER = 0.65


def fmt_usd(x: float) -> str:
    if abs(x) >= 1e9:
        return f'${x/1e9:.2f}B'
    if abs(x) >= 1e6:
        return f'${x/1e6:.1f}M'
    if abs(x) >= 1e3:
        return f'${x/1e3:.1f}K'
    return f'${x:.2f}'


def load_growth_distribution() -> np.ndarray:
    j = json.loads(EXTRA_PATH.read_text())
    rets = np.array(j['money_market_log_returns'], dtype=float)
    # dampen and cap broad-market TVL growth to avoid assuming Sky matches the fastest protocols
    rets = np.clip(rets * GROWTH_DAMPENER, MONTHLY_GROWTH_CAP_LOW, MONTHLY_GROWTH_CAP_HIGH)
    return rets


def simulate(opex: float, np_multiple: float) -> dict:
    rng = np.random.default_rng(SEED)
    monthly_log_returns = load_growth_distribution()
    sampled = rng.choice(monthly_log_returns, size=(PATHS, HORIZON_MONTHS), replace=True)
    usds = np.full(PATHS, USDS_SUPPLY, dtype=float)
    dai = np.full(PATHS, DAI_SUPPLY, dtype=float)  # flat base assumption
    annual_gp_series = []
    annual_np_series = []

    # Track each path monthly, then use final 12M trailing annual GP/NP as denominator.
    monthly_gp = np.zeros((PATHS, HORIZON_MONTHS), dtype=float)
    monthly_np = np.zeros((PATHS, HORIZON_MONTHS), dtype=float)
    for m in range(HORIZON_MONTHS):
        # USDS growth only; DAI flat in base.
        usds *= np.exp(sampled[:, m])
        total = usds + dai
        gross_income_m = total * GROSS_INCOME_YIELD / 12.0
        savings_cost_m = (usds * USDS_SAVINGS_PENETRATION + dai * DAI_SAVINGS_PENETRATION) * SAVINGS_RATE / 12.0
        stusds_cost_m = usds * STUSDS_EXPENSE_RATE_ON_USDS / 12.0
        gp_m = gross_income_m - savings_cost_m - stusds_cost_m
        np_m = gp_m - opex / 12.0
        monthly_gp[:, m] = gp_m
        monthly_np[:, m] = np_m

    y3_ttm_gp = monthly_gp[:, -12:].sum(axis=1)
    y3_ttm_np = monthly_np[:, -12:].sum(axis=1)
    y3_ttm_np_floor = np.maximum(y3_ttm_np, 0.0)
    accumulated_treasury_cash = np.maximum(monthly_np, 0.0).sum(axis=1)
    y3_usds = usds
    y3_total_supply = usds + dai

    undiscounted_gp_price = y3_ttm_gp * GP_MULTIPLE / SKY_SUPPLY
    undiscounted_np_price = y3_ttm_np_floor * np_multiple / SKY_SUPPLY
    # Entity value version: operating value plus net profit accumulated in treasury.
    undiscounted_gp_plus_cash_price = (y3_ttm_gp * GP_MULTIPLE + accumulated_treasury_cash) / SKY_SUPPLY
    undiscounted_np_plus_cash_price = (y3_ttm_np_floor * np_multiple + accumulated_treasury_cash) / SKY_SUPPLY
    disc = (1.0 + DISCOUNT_RATE) ** 3
    pv_gp = undiscounted_gp_price / disc
    pv_np = undiscounted_np_price / disc
    pv_gp_plus_cash = undiscounted_gp_plus_cash_price / disc
    pv_np_plus_cash = undiscounted_np_plus_cash_price / disc

    def pct(arr, q): return float(np.percentile(arr, q))
    def pack(arr):
        return {
            'p25': pct(arr, 25), 'p50': pct(arr, 50), 'p75': pct(arr, 75), 'p90': pct(arr, 90),
            'ev_mean': float(np.mean(arr)),
            'prob_spot_justified': float(np.mean(arr >= SPOT)),
            'prob_3x': float(np.mean(arr >= 3 * SPOT)),
        }
    return {
        'opex': opex,
        'np_multiple': np_multiple,
        'pv_gp_10x': pack(pv_gp),
        'pv_np': pack(pv_np),
        'pv_gp_10x_plus_cash': pack(pv_gp_plus_cash),
        'pv_np_plus_cash': pack(pv_np_plus_cash),
        'undiscounted_gp_10x': pack(undiscounted_gp_price),
        'undiscounted_np': pack(undiscounted_np_price),
        'undiscounted_gp_10x_plus_cash': pack(undiscounted_gp_plus_cash_price),
        'undiscounted_np_plus_cash': pack(undiscounted_np_plus_cash_price),
        'accumulated_treasury_cash': pack(accumulated_treasury_cash),
        'y3_ttm_gp': pack(y3_ttm_gp),
        'y3_ttm_net_profit': pack(y3_ttm_np),
        'y3_usds_supply': pack(y3_usds),
        'y3_total_stable_supply': pack(y3_total_supply),
    }


def main():
    growth = load_growth_distribution()
    scenarios = {}
    for name, opex in OPEX_SCENARIOS.items():
        scenarios[name + '_np15x'] = simulate(opex, NP_MULTIPLE_BASE)

    current_gp = GROSS_INCOME - SAVINGS_EXPENSE - STUSDS_EXPENSE
    current_np_base = current_gp - OPEX_SCENARIOS['base_70m_opex']
    result = {
        'as_of_utc': datetime.now(timezone.utc).isoformat(),
        'inputs': {
            'spot': SPOT, 'sky_supply': SKY_SUPPLY, 'mcap': MCAP, 'fdv': FDV,
            'usds_supply': USDS_SUPPLY, 'dai_supply': DAI_SUPPLY,
            'susds_supply': SUSDS_SUPPLY, 'sdai_supply': SDAI_SUPPLY,
            'usds_savings_penetration': USDS_SAVINGS_PENETRATION,
            'dai_savings_penetration': DAI_SAVINGS_PENETRATION,
            'gross_income': GROSS_INCOME, 'savings_expense': SAVINGS_EXPENSE,
            'stusds_expense': STUSDS_EXPENSE, 'current_site_opex': CURRENT_OPEX_SITE,
            'current_gp': current_gp, 'current_np_base_70m_opex': current_np_base,
            'gross_income_yield': GROSS_INCOME_YIELD, 'savings_rate': SAVINGS_RATE,
            'stusds_expense_rate_on_usds': STUSDS_EXPENSE_RATE_ON_USDS,
            'discount_rate': DISCOUNT_RATE,
            'gp_multiple': GP_MULTIPLE,
            'np_multiple_base': NP_MULTIPLE_BASE,
            'growth_cap_low': MONTHLY_GROWTH_CAP_LOW,
            'growth_cap_high': MONTHLY_GROWTH_CAP_HIGH,
            'growth_dampener': GROWTH_DAMPENER,
            'money_market_growth_monthly_log_mean_after_caps': float(np.mean(growth)),
            'money_market_growth_monthly_log_stdev_after_caps': float(np.std(growth, ddof=1)),
        },
        'current_multiples': {
            'mcap_current_gp': MCAP / current_gp,
            'fdv_current_gp': FDV / current_gp,
            'mcap_current_np_base': MCAP / current_np_base,
            'fdv_current_np_base': FDV / current_np_base,
        },
        'scenarios': scenarios,
    }
    JSON_OUT.write_text(json.dumps(result, indent=2))

    lines = []
    lines.append('# SKY MC valuation prototype')
    lines.append(f"As of: {result['as_of_utc']}")
    lines.append('')
    lines.append('## Key assumptions')
    lines.append('```text')
    lines.append(f"Spot                              ${SPOT:.5f}")
    lines.append(f"SKY supply                         {SKY_SUPPLY/1e9:.2f}B")
    lines.append(f"USDS / DAI supply                  {USDS_SUPPLY/1e9:.2f}B / {DAI_SUPPLY/1e9:.2f}B")
    lines.append(f"sUSDS / sDAI                       {SUSDS_SUPPLY/1e9:.2f}B / {SDAI_SUPPLY/1e9:.2f}B")
    lines.append(f"USDS savings penetration           {USDS_SAVINGS_PENETRATION*100:.1f}%")
    lines.append(f"DAI savings penetration            {DAI_SAVINGS_PENETRATION*100:.1f}%")
    lines.append(f"Savings rate                       {SAVINGS_RATE*100:.2f}%")
    lines.append(f"Gross income yield                 {GROSS_INCOME_YIELD*100:.2f}%")
    lines.append(f"Current GP                         {fmt_usd(current_gp)}")
    lines.append(f"Base OPEX                          {fmt_usd(OPEX_SCENARIOS['base_70m_opex'])}")
    lines.append(f"Current net profit @ base OPEX      {fmt_usd(current_np_base)}")
    lines.append(f"Discount rate                      {DISCOUNT_RATE*100:.0f}%")
    lines.append(f"USDS growth path                   money-market TVL returns × {GROWTH_DAMPENER:.2f}, capped {MONTHLY_GROWTH_CAP_LOW*100:.0f}%/{MONTHLY_GROWTH_CAP_HIGH*100:.0f}% monthly; no explicit 3Y supply cap")
    lines.append("Treasury treatment                 monthly positive NP accumulates as cash; no buyback/supply reduction assumed")
    lines.append('```')
    lines.append('')
    lines.append('## KPIs to track for stale-assumption checks')
    lines.append('```text')
    lines.append(f"SSR / savings rate                 {SAVINGS_RATE*100:.2f}%")
    lines.append(f"USDS savings penetration           {USDS_SAVINGS_PENETRATION*100:.1f}%")
    lines.append(f"USDS supply                        {fmt_usd(USDS_SUPPLY)}")
    lines.append(f"DAI supply                         {fmt_usd(DAI_SUPPLY)}")
    lines.append(f"Annualized GP                      {fmt_usd(current_gp)}")
    lines.append(f"Operational expenses assumption    {fmt_usd(OPEX_SCENARIOS['base_70m_opex'])}")
    lines.append('```')
    lines.append('')
    lines.append('## Current multiples')
    lines.append('```text')
    lines.append(f"MCap / current GP                  {MCAP/current_gp:.1f}x")
    lines.append(f"FDV  / current GP                  {FDV/current_gp:.1f}x")
    lines.append(f"MCap / current net profit          {MCAP/current_np_base:.1f}x")
    lines.append(f"FDV  / current net profit          {FDV/current_np_base:.1f}x")
    lines.append('```')
    lines.append('')
    lines.append('## Model results: discounted PV')
    lines.append('```text')
    lines.append('Scenario              Value basis        P25     P50     EV      P75     P90     P(spot)')
    lines.append('--------------------  ---------------  ------  ------  ------  ------  ------  -------')
    for name in ['bear_90m_opex_np15x','base_70m_opex_np15x','bull_50m_opex_np15x']:
        s = scenarios[name]
        label = name.replace('_opex_', ' ').replace('_', ' ')
        for basis, key in [('10x GP', 'pv_gp_10x'), (f"{s['np_multiple']:.1f}x NP", 'pv_np'), ('10x GP + cash', 'pv_gp_10x_plus_cash'), (f"{s['np_multiple']:.1f}x NP + cash", 'pv_np_plus_cash')]:
            r = s[key]
            lines.append(f"{label[:20]:20s}  {basis:15s}  ${r['p25']:.3f}  ${r['p50']:.3f}  ${r['ev_mean']:.3f}  ${r['p75']:.3f}  ${r['p90']:.3f}  {r['prob_spot_justified']*100:6.1f}%")
    lines.append('```')
    lines.append('')
    lines.append('## Base case operating outputs')
    lines.append('```text')
    b = scenarios['base_70m_opex_np15x']
    lines.append(f"Y3 USDS supply P50                 {fmt_usd(b['y3_usds_supply']['p50'])}")
    lines.append(f"Y3 stablecoin supply P50           {fmt_usd(b['y3_total_stable_supply']['p50'])}")
    lines.append(f"Y3 TTM GP P50                      {fmt_usd(b['y3_ttm_gp']['p50'])}")
    lines.append(f"Y3 TTM net profit P50              {fmt_usd(b['y3_ttm_net_profit']['p50'])}")
    lines.append(f"Accumulated treasury cash P50      {fmt_usd(b['accumulated_treasury_cash']['p50'])}")
    lines.append(f"Base 15x NP PV P50                 ${b['pv_np']['p50']:.3f}")
    lines.append(f"Base 15x NP + cash PV P50          ${b['pv_np_plus_cash']['p50']:.3f}")
    lines.append('```')
    MD_OUT.write_text('\n'.join(lines) + '\n')
    print(JSON_OUT)
    print(MD_OUT)
    print('\n'.join(lines))

if __name__ == '__main__':
    main()
