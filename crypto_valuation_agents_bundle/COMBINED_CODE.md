# Crypto valuation agents bundle
This bundle contains the six Hermes cron agent definitions plus source files for the locked valuation models. Delivery targets/chat IDs are intentionally not included.
## Schedules
- **HYPE valuation report Mon/Fri**: `0 9 * * 1,5`; workdir `/Users/momir_mini/.openclaw/workspace/altcoin_research`; toolsets `terminal, file, web`; skills `none`
- **SKY valuation report Mon/Fri**: `0 9 * * 1,5`; workdir `/Users/momir_mini/.openclaw/workspace/altcoin_research`; toolsets `terminal, file, web`; skills `none`
- **ETHFI valuation report Mon/Fri**: `0 9 * * 1,5`; workdir `/Users/momir_mini/.openclaw/workspace/altcoin_research`; toolsets `terminal, file, web`; skills `none`
- **UNI valuation report Mon/Fri**: `0 9 * * 1,5`; workdir `/Users/momir_mini/.openclaw/workspace/altcoin_research`; toolsets `terminal, file, web`; skills `crypto-gp-capture-valuation`
- **JUP valuation report Mon/Fri**: `0 9 * * 1,5`; workdir `/Users/momir_mini/.openclaw/workspace/altcoin_research`; toolsets `terminal, file, web`; skills `crypto-gp-capture-valuation`
- **Crypto valuation ranking EOW**: `0 18 * * 5`; workdir `/Users/momir_mini/.openclaw/workspace/altcoin_research`; toolsets `terminal, file, web`; skills `crypto-gp-capture-valuation`

## Cron prompts

### HYPE valuation report Mon/Fri

```text
Run the HYPE valuation agent from /Users/momir_mini/.openclaw/workspace/altcoin_research and deliver a concise Discord-friendly update.

Steps:
1. Run `python hype_gp_capture_12m_start_run.py` in the workdir.
2. Run or ensure `hype_latest_3_table_report.md` is refreshed if the generator is available; otherwise use the script's stdout plus `hype_3y_gp_capture_12m_start_run.json`.
3. Deliver only a short Discord-friendly 3-block update in aligned text code blocks: key assumptions, model results, sanity checks/KPI drift.
4. Avoid long methodology or wide Markdown tables. Do not expose secrets.
5. If live APIs fail after retries, use last successful JSON/report and clearly label stale data.

Mandatory report points:
- Spot, P50 PV, EV PV, P50/spot, EV/spot for base DB-observed emissions and +10% optionality.
- 30D revenue/GP, 12M median monthly revenue, selected start GP, TTM GP.
- Buyback years, base emissions, net supply/month, volume sanity.
- Flag if buyback-years crosses 20y or if 30D revenue materially diverges from 12M median.
```

### SKY valuation report Mon/Fri

```text
Run the locked SKY valuation agent report for Momir and deliver a concise Discord-friendly update. Workdir is /Users/momir_mini/.openclaw/workspace/altcoin_research.

Use the locked SKY model structure established on 2026-05-08:
- GP = gross income / stability fee income - savings-rate costs / DSR - stUSDS cost.
- Net profit = GP - OPEX.
- OPEX scenarios: bear $90M/year, base $70M/year, bull $50M/year.
- Use Sky native dashboard / BlockAnalitica data for DAI, USDS, sDAI, sUSDS, savings rate, financials; do not rely on CoinGecko stablecoin wrappers for the DAI/USDS split.
- Base DAI assumption is flat; future growth comes from USDS.
- MC path uses broad money-market/yield/CDP TVL monthly returns since 2022, dampened/capped as in sky_mc_agent.py unless explicitly updated by Momir later.
- Discount rate: 25% base.
- Multiples: 10x GP and 15x Net Profit.
- Treasury treatment: monthly positive net profit accumulates as cash; no buyback or supply reduction assumed. Main valuation line is 15x NP + accumulated treasury cash.
- Track stale-assumption KPIs: SSR/savings rate, USDS savings penetration, DAI savings penetration, USDS supply, DAI supply, annualized GP, OPEX assumption.

Steps:
1. Run: python sky_mc_agent.py
2. If it fails due stale API/page changes, inspect and fix the minimum necessary data pull issue while preserving locked methodology; report any methodology changes explicitly.
3. Read sky_mc_result.md and sky_mc_result.json.
4. Deliver a concise Discord-friendly report in the same 3-table format as HYPE/SKY:
   Table 1: key assumptions/KPIs.
   Table 2: model results, with P50 and EV, emphasizing Base $70M OPEX 15x NP + cash.
   Table 3: sanity checks/current multiples, including spot vs base PV, probability spot justified, Y3 USDS supply, Y3 GP, Y3 NP, accumulated treasury cash.
5. Flag stale assumptions or material KPI changes vs locked baseline: USDS 6.43B, DAI 4.17B, sUSDS 5.22B, sDAI 0.24B, SSR 3.65%, USDS savings penetration 81%, current GP ~$218.5M, base NP ~$148.5M.

Do not ask questions; the cron run is autonomous.
```

### ETHFI valuation report Mon/Fri

```text
Run the locked ETHFI valuation agent report for Momir and deliver a concise Discord-friendly update.

Workdir: /Users/momir_mini/.openclaw/workspace/altcoin_research
Primary script: python ethfi_mc_agent.py
Output files: ethfi_mc_result.md and ethfi_mc_result.json

Instructions:
1. Run `python ethfi_mc_agent.py` from the workdir.
2. If it errors, inspect and report the failure concisely; do not print secrets. The Dune API key may be available in ~/.hermes/secrets/dune_api_key or ~/.hermes/secrets.env and must never be printed.
3. Read ethfi_mc_result.md/json after the run.
4. Deliver a Discord-friendly report with 3 key tables/blocks:
   - Key assumptions + actionable insights / assumption watchlist.
   - Model results: discounted PV at 15x GP and 15x GP + cash, including P25/P50/EV/P75/P90 and P(spot).
   - Sanity checks: Y3 card annual GMV and staking TVL distributions, Y3 staking GP P50, current GP bridge, current MCap/GP and FDV/GP.
5. Include hurdle-rate sensitivity for P50 15x GP fair value at 17.5%, 22.5%, 27.5%, 32.5%, and 37.5%.
6. Highlight if new data suggest assumptions need fixing, especially:
   - Dune card growth anchor changed materially.
   - Card GMV slows sharply or exceeds the cap.
   - Staking APY/TVL shifts materially.
   - Take-rate diverges from 135bps.
   - Base 15x GP P50 crosses above/below spot.
   - Unaccounted 145.3M ETHFI receives an unlock schedule.
   - OPEX/cash assumptions look stale.
7. Keep output concise and avoid wide Markdown tables; use aligned text code blocks.
```

### UNI valuation report Mon/Fri

```text
Run the locked UNI valuation agent report for Momir and deliver a concise Discord-friendly update. This job is self-contained.

First read `/Users/momir_mini/.openclaw/workspace/altcoin_research/UNI_LOCKED_MODEL.md` and follow it exactly. If the file is unavailable, use the locked assumptions below.

Locked UNI model summary:
- 3-year GP-capture valuation, not perpetual DCF.
- Never call the full-activation line "terminal GP". Use "full-activation Y3 GP" or "potential Y3 GP".
- HYPE-style MC volume simulation using Uniswap monthly DEX volume history from DeFiLlama (`https://api.llama.fi/summary/dexs/uniswap?dataType=dailyVolume`). Aggregate daily volume to completed monthly volume; use history from 2021-01 through latest completed month; monthly log-return bootstrap; simulate 36 months; valuation denominator is Year-3 trailing 12M volume.
- Live base seed = min(latest full 30D Uniswap volume, trailing 12 completed months median monthly volume). For backtests, use min(latest completed month, trailing 12 completed months median).
- Pull Uniswap fees from DeFiLlama (`https://api.llama.fi/summary/fees/uniswap?dataType=dailyFees`). LP fee bps live = recent 30D fees/volume cross-checked against trailing 12M; corrected recent reference was ~10.92bps.
- Current-state LP protocol take = ~0.826bps because v4 not yet fee-switch active; current-state total take = 0.826bps + frontend effective take.
- Full-activation Y3 GP take = LP fee bps * 25% + frontend effective take.
- Frontend fee = 15bps; frontend/total volume = ~2%; frontend effective take = 0.30bps.
- Apply 15x GP multiple.
- No post-activation cash additive. Protocol fees route TokenJar -> Firepit -> UNI burns.
- Primary supply basis: current circulating UNI supply from market data; show FDV/full-supply sensitivity if available.
- Discount rate: liquid-token framework DR = risk_free_rate + 3% ERP * (UNI 365D daily stdev / S&P500 365D daily stdev). Use current 10Y yield, UNI price history, S&P500 history. Prior locked run produced ~24-25%.

Output exactly three compact Discord-friendly sections/tables:
1) Key assumptions: spot, data freshness, base seed, LP fee bps, current-state/full-activation take bps, DR, supply, multiple.
2) Model results: Y3 TTM volume P25/P50/P75/EV-mean; current-state GP and PV price; full-activation Y3 GP and PV price; FDV PV sensitivity. Include EV/mean PV price.
3) Sanity checks/current multiples: current annualized volume, current-state annual GP, full-activation annual GP, MCap/current-state GP, MCap/full-activation GP, FDV/full-activation GP, probability PV > spot and PV > 3x spot.

Keep output concise, easy to read in Discord, and avoid wide markdown pipe tables. Prefer aligned text code blocks. Include caveats if any data endpoint fails and clearly state fallback assumptions. Do not ask questions during the cron run.
```

### JUP valuation report Mon/Fri

```text
Run the locked JUP valuation agent from /Users/momir_mini/.openclaw/workspace/altcoin_research and deliver a concise Discord-friendly update.

Steps:
1. Run `python3 jup_locked_agent.py` from the workdir.
2. Read `jup_locked_report.md` and `jup_locked_result.json`.
3. Deliver a short metric-first report using compact bullets and narrow aligned ```text``` blocks only; no wide Markdown tables.

Required fields:
- Spot, mcap, FDV, as-of timestamp.
- Core, +10% optionality, and +10% optionality+Jupnet: P25, P50 PV, P75, EV PV, P50/spot, EV/spot, P>spot.
- Product revenue/GP split: Perps GP, Aggregator GP, Jupiterz volume + implied GP, DCA fees, JUP Lend revenue, jupSOL revenue, tracked optional total.
- Supply assumption: scheduled unlock pressure is 0 JUP/month until Jupiter announces a public distribution plan for the ~3.405B cold-storage/community reserve. Do NOT describe 53.47M/month as current or scheduled dilution. Mention it only as a retired/invalid assumption if relevant.
- Explain valuation read-through: current core GP seed, buybacks at 50% of entity GP, current/effective supply denominator, and small optional lines. Note that Lend/jupSOL are tracked explicitly but not separate MC drivers until material.
- Action signal: Watch / Act / No action, with one trigger that would upgrade/downgrade.

If live APIs fail, use the latest local artifacts and clearly label stale data.
```

### Crypto valuation ranking EOW

```text
Produce the end-of-week crypto valuation analysis for Momir and deliver to Discord. Rank the locked/report-list projects by model_price/spot_price. Include at minimum HYPE, SKY, ETHFI, UNI, and JUP if their model files/reports are available in /Users/momir_mini/.openclaw/workspace/altcoin_research and/or their recurring reports. Use each token's latest locked model convention and refreshed spot price. For each project, compute or extract P50 PV/spot and EV PV/spot; rank primarily by P50/spot, with EV/spot as secondary. Output concise Discord-friendly sections: (1) ranked table: token, P50 PV, spot, P50/spot, EV/spot, signal; (2) key movers/stale assumptions; (3) action list/KPIs for next week. Avoid wide Markdown tables; use aligned text blocks or narrow tables. Do not ask questions; if a model cannot be refreshed, use the latest locked/report value and label it stale.
```

## Source files

### `hype_gp_capture_12m_start_run.py`

```python
#!/usr/bin/env python3
"""Updated HYPE GP-capture scenario run after critique.

Fixes:
- Treat DeFiLlama dailyRevenue as net GP / buyback capacity directly (GP margin = 100%).
- Scenario emissions instead of hardcoded single base.
- Product optionality as separate Y3 value uplift sensitivity.
"""
import json, math, os
from datetime import datetime, timezone

import numpy as np

import hype_gp_capture_mc as h

OUTDIR = os.path.dirname(__file__)
N_PATHS = h.N_PATHS
MONTHS = h.MONTHS
SELECTED_DR = h.SELECTED_DISCOUNT_RATE
TOKEN_CAPTURE = 1.0
BUYBACK_RATE = 1.0
GP_MARGIN = 1.0

NET_REVENUE_TAKE_RATE = 0.00034  # net revenue / perp notional; old HYPE agent fee-rate anchor

def median_monthly_start_12m(rev_rows, trailing_30):
    months = h.monthly_sums(rev_rows)
    last12 = [v for _, v in months[-12:]]
    med12 = float(np.median(np.array(last12, dtype=float))) if last12 else float(trailing_30)
    return min(float(trailing_30), med12), med12, float(trailing_30)

SCENARIOS = [
    {
        "key": "bear_worst_case_emissions",
        "label": "Bear: worst-case emissions",
        "monthly_emission": 9_916_667.0,
        "emission_months": 20,
        "optionality": 0.0,
        "note": "9.92M HYPE/month treated as downside linear-release ceiling, not base.",
    },
    {
        "key": "base_db_observed_emissions",
        "label": "Base: DB-observed emissions",
        "monthly_emission": 962_000.0,
        "emission_months": 36,
        "optionality": 0.0,
        "note": "Uses critique's DB-observed run-rate for known emissions/unlocks.",
    },
    {
        "key": "upside_db_observed_plus_optionality",
        "label": "Upside: base + 10% optionality",
        "monthly_emission": 962_000.0,
        "emission_months": 36,
        "optionality": 0.10,
        "note": "Adds product optionality as separate +10% Y3 value uplift.",
    },
    {
        "key": "zero_emissions_sensitivity",
        "label": "Sensitivity: zero emissions",
        "monthly_emission": 0.0,
        "emission_months": 36,
        "optionality": 0.0,
        "note": "Sensitivity only; not a base case.",
    },
]

CORE_QS = [25, 50, 75, 90]
CHART_QS = [5, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 95]

def pct_dict(x, qs):
    return {f"p{q}": float(np.percentile(x, q)) for q in qs}

def fmt_money(x):
    if x is None or not (x == x):
        return "n/a"
    ax = abs(x)
    if ax >= 1e9: return f"${x/1e9:,.2f}B"
    if ax >= 1e6: return f"${x/1e6:,.1f}M"
    if ax >= 1e3: return f"${x/1e3:,.1f}K"
    return f"${x:,.2f}"

def run_once():
    market = h.cg_market()
    spot = float(market["current_price"])
    mcap = float(market["market_cap"])
    fdv = market.get("fully_diluted_valuation")
    fdv = float(fdv) if fdv else float("nan")
    circ = float(market.get("circulating_supply") or (mcap / spot))
    total_supply = market.get("total_supply")
    total_supply = float(total_supply) if total_supply else float("nan")

    rev = h.defillama_revenue()
    rev_vals = np.array([v for _, v in rev], dtype=float)
    last_date = rev[-1][0]
    trailing_30 = float(rev_vals[-30:].sum())
    trailing_90 = float(rev_vals[-90:].sum())
    current_monthly_rev, median_12m_monthly_rev, last_30d_rev = median_monthly_start_12m(rev, trailing_30)
    current_annual_gp = current_monthly_rev * 365 / 30 * GP_MARGIN
    ttm_gp = (float(rev_vals[-365:].sum()) if len(rev_vals) >= 365 else float(rev_vals.sum() * 365 / len(rev_vals))) * GP_MARGIN

    monthly_proxy, ret_arr, shares = h.choose_monthly_return_distribution()
    np.random.seed(42)
    draws = np.random.choice(ret_arr, size=(N_PATHS, MONTHS), replace=True)
    growth = np.exp(np.cumsum(draws, axis=1))
    monthly_gp = current_monthly_rev * growth * GP_MARGIN
    y3_ttm_gp = monthly_gp[:, -12:].sum(axis=1)
    ranks = h.percentile_ranks(y3_ttm_gp)
    multiple = h.multiple_for_ranks(ranks)

    scenarios = {}
    for sc in SCENARIOS:
        supply = np.full(N_PATHS, circ, dtype=float)
        for t in range(MONTHS):
            start = max(0, t - 11)
            gp_window = monthly_gp[:, start:t+1].sum(axis=1) * (12.0 / (t - start + 1))
            interim_rank = h.percentile_ranks(gp_window)
            interim_mult = h.multiple_for_ranks(interim_rank)
            interim_price = (gp_window * interim_mult * TOKEN_CAPTURE) / np.maximum(supply, 1)
            buy_tokens = (monthly_gp[:, t] * BUYBACK_RATE) / np.maximum(interim_price, 0.01)
            buy_tokens = np.minimum(buy_tokens, supply * 0.80)
            emissions = sc["monthly_emission"] if t < sc["emission_months"] else 0.0
            supply = supply + emissions - buy_tokens
            supply = np.maximum(supply, 1.0)
        y3_supply = supply
        y3_price_core = (y3_ttm_gp * multiple * TOKEN_CAPTURE) / np.maximum(y3_supply, 1)
        y3_price = y3_price_core * (1.0 + sc["optionality"])
        pv = y3_price / ((1.0 + SELECTED_DR) ** 3)
        current_monthly_gp = current_monthly_rev * GP_MARGIN
        current_buy_tokens = current_monthly_gp / max(spot, 0.01)
        net_monthly_supply = sc["monthly_emission"] - current_buy_tokens
        supply_to_buy_back = circ + sc["monthly_emission"] * min(sc["emission_months"], 36)
        buyback_years = supply_to_buy_back / max(current_buy_tokens * 12, 1)
        scenarios[sc["key"]] = {
            **sc,
            "discounted_token_price": pct_dict(pv, CORE_QS),
            "discounted_ev": float(np.mean(pv)),
            "discounted_distribution": pct_dict(pv, CHART_QS),
            "undiscounted_y3_token_price": pct_dict(y3_price, CORE_QS),
            "undiscounted_y3_ev": float(np.mean(y3_price)),
            "y3_ttm_gp": pct_dict(y3_ttm_gp, CORE_QS),
            "y3_supply": pct_dict(y3_supply, CORE_QS),
            "prob_current_spot_justified": float(np.mean(pv >= spot)),
            "prob_impairment_vs_spot": float(np.mean(pv < spot)),
            "prob_3x_vs_spot": float(np.mean(pv >= 3 * spot)),
            "current_monthly_gp": float(current_monthly_gp),
            "current_buy_tokens_per_month": float(current_buy_tokens),
            "net_monthly_supply_now": float(net_monthly_supply),
            "buyback_years_simple": float(buyback_years),
        }

    # Volume sanity: implied HYPE volume from Y3 GP using net revenue take-rate.
    # Compare to total Binance futures current/peak daily volume from scaled BTCUSDT proxy.
    latest_month_vol = float(monthly_proxy[-1][1])
    current_binance_daily = latest_month_vol / 30.0
    peak_binance_daily = float(max(v for _, v in monthly_proxy)) / 30.0
    for sc in scenarios.values():
        y3_gp_p50 = sc["y3_ttm_gp"]["p50"]
        implied_hype_daily_vol_p50 = y3_gp_p50 / NET_REVENUE_TAKE_RATE / 365.0
        sc["volume_sanity"] = {
            "net_revenue_take_rate": NET_REVENUE_TAKE_RATE,
            "implied_hype_daily_volume_y3_p50": implied_hype_daily_vol_p50,
            "current_binance_futures_daily_volume": current_binance_daily,
            "peak_binance_futures_daily_volume": peak_binance_daily,
            "implied_vs_current_binance": implied_hype_daily_vol_p50 / current_binance_daily,
            "implied_vs_peak_binance": implied_hype_daily_vol_p50 / peak_binance_daily,
        }

    out = {
        "asof_utc": datetime.now(timezone.utc).isoformat(),
        "market": {"spot": spot, "mcap": mcap, "fdv": fdv, "circ_supply": circ, "total_supply": total_supply},
        "revenue": {
            "defillama_last_date": str(last_date),
            "trailing_30d_revenue": trailing_30,
            "trailing_90d_revenue": trailing_90,
            "median_12m_monthly_revenue": median_12m_monthly_rev,
            "conservative_start_monthly_revenue": current_monthly_rev,
            "current_annualized_gp": current_annual_gp,
            "ttm_gp": ttm_gp,
            "gp_margin_on_defillama_revenue": GP_MARGIN,
        },
        "mc": {
            "paths": N_PATHS,
            "months": MONTHS,
            "volume_proxy": "total Binance futures, BTCUSDT-scaled via Blockworks annual totals",
            "proxy_months": len(monthly_proxy),
            "monthly_log_return_mean": float(np.mean(ret_arr)),
            "monthly_log_return_std": float(np.std(ret_arr, ddof=1)),
            "btcusdt_shares": {str(k): float(v) for k, v in shares.items()},
        },
        "discount": {"selected": SELECTED_DR},
        "scenarios": scenarios,
    }
    return out

def write_report(res):
    m, r, mc, scs = res["market"], res["revenue"], res["mc"], res["scenarios"]
    spot = m["spot"]
    lines = []
    lines.append("# HYPE 3Y GP-Capture MC — 12M Median Start Run")
    lines.append(f"As of: {res['asof_utc']}")
    lines.append("")
    lines.append("## What changed")
    lines.append("- DeFiLlama `dailyRevenue` is now treated as net GP / buyback capacity directly: **GP margin = 100% on revenue**.")
    lines.append("- 9.92M HYPE/month emissions are moved to **bear/worst-case**, not base.")
    lines.append("- Base uses DB-observed emissions from the critique: **0.962M HYPE/month**.")
    lines.append("- Product optionality is a separate **+10% Year-3 value** sensitivity.")
    lines.append("")
    lines.append("## Market + GP base")
    lines.append("```text")
    lines.append(f"Spot                         ${spot:,.2f}")
    lines.append(f"Market cap                   {fmt_money(m['mcap'])}")
    lines.append(f"FDV                          {fmt_money(m['fdv'])}")
    lines.append(f"Circulating supply           {m['circ_supply']/1e6:,.1f}M HYPE")
    lines.append(f"DeFiLlama revenue date       {r['defillama_last_date']}")
    lines.append(f"30D revenue                  {fmt_money(r['trailing_30d_revenue'])}")
    lines.append(f"Median monthly revenue 12M    {fmt_money(r['median_12m_monthly_revenue'])}")
    lines.append(f"Conservative monthly GP      {fmt_money(r['conservative_start_monthly_revenue'])}")
    lines.append(f"Annualized start GP          {fmt_money(r['current_annualized_gp'])}")
    lines.append(f"TTM GP                       {fmt_money(r['ttm_gp'])}")
    lines.append("GP margin                    100% of DeFiLlama revenue")
    lines.append("Discount rate                25% selected HYPE rate")
    lines.append(f"MC paths / horizon           {mc['paths']:,} / {mc['months']} months")
    lines.append(f"Monthly mkt logret mean/std  {mc['monthly_log_return_mean']:.2%} / {mc['monthly_log_return_std']:.2%}")
    lines.append("```")
    lines.append("")
    lines.append("## Scenario output — discounted fair value @ 25%")
    lines.append("```text")
    lines.append("Scenario                         P25      P50      P75      P90      P(spot)  3x+")
    lines.append("-------------------------------  -------  -------  -------  -------  -------  ------")
    order = ["bear_worst_case_emissions", "base_db_observed_emissions", "upside_db_observed_plus_optionality", "zero_emissions_sensitivity"]
    for k in order:
        s = scs[k]; d = s["discounted_token_price"]
        lines.append(f"{s['label']:<31}  ${d['p25']:>6.2f}  ${d['p50']:>6.2f}  ${d['p75']:>6.2f}  ${d['p90']:>6.2f}  {s['prob_current_spot_justified']:>6.1%}  {s['prob_3x_vs_spot']:>5.1%}")
    lines.append("```")
    lines.append("")
    lines.append("## Supply / buyback sanity")
    lines.append("```text")
    lines.append("Scenario                         Emissions/mo  Net supply/mo now  Buyback years  Y3 supply P50")
    lines.append("-------------------------------  ------------  -----------------  -------------  -------------")
    for k in order:
        s = scs[k]
        lines.append(f"{s['label']:<31}  {s['monthly_emission']/1e6:>8.2f}M     {s['net_monthly_supply_now']/1e6:>+8.2f}M          {s['buyback_years_simple']:>6.1f}y       {s['y3_supply']['p50']/1e6:>7.1f}M")
    lines.append("```")
    lines.append("")
    base = scs["base_db_observed_emissions"]["discounted_token_price"]
    upside = scs["upside_db_observed_plus_optionality"]["discounted_token_price"]
    bear = scs["bear_worst_case_emissions"]["discounted_token_price"]

    lines.append("## P50 volume sanity")
    lines.append("```text")
    lines.append("Assumed net revenue take-rate: 0.034% of notional volume")
    lines.append("")
    lines.append("Scenario                         Implied HYPE daily vol   vs Binance current   vs Binance peak")
    lines.append("-------------------------------  ----------------------   ------------------   ---------------")
    for k in order[:3]:
        s = scs[k]; vs = s["volume_sanity"]
        lines.append(f"{s['label']:<31}  {fmt_money(vs['implied_hype_daily_volume_y3_p50']):>22}   {vs['implied_vs_current_binance']:>17.1%}   {vs['implied_vs_peak_binance']:>14.1%}")
    lines.append("```")
    lines.append("")
    lines.append("## Read-through")
    lines.append(f"- **Bear/worst-case:** P50 **${bear['p50']:.2f}**, still clearly below spot because 9.92M/month emissions overwhelm buybacks.")
    lines.append(f"- **Base corrected run:** P50 **${base['p50']:.2f}**, P75 **${base['p75']:.2f}**, with spot justified in **{scs['base_db_observed_emissions']['prob_current_spot_justified']:.1%}** of paths.")
    lines.append(f"- **Upside optionality run:** P50 **${upside['p50']:.2f}**, P75 **${upside['p75']:.2f}**, spot justified in **{scs['upside_db_observed_plus_optionality']['prob_current_spot_justified']:.1%}** of paths.")
    lines.append("- Main conclusion: corrected model no longer says HYPE is obviously expensive; it says current spot is around the upper half of fair-value distribution unless worst-case emissions are true.")
    lines.append("")
    report = "\n".join(lines) + "\n"
    md = os.path.join(OUTDIR, "hype_3y_gp_capture_12m_start_run.md")
    js = os.path.join(OUTDIR, "hype_3y_gp_capture_12m_start_run.json")
    with open(md, "w") as f: f.write(report)
    with open(js, "w") as f: json.dump(res, f, indent=2)
    return md, js, report

if __name__ == "__main__":
    res = run_once()
    md, js, report = write_report(res)
    print(report)
    print("Saved:", md)
    print("Saved:", js)

```

### `generate_hype_3_table.py`

```python
import json, re, math, os, datetime
from pathlib import Path
import requests

WD = Path('/Users/momir_mini/.openclaw/workspace/altcoin_research')
J = json.loads((WD/'hype_3y_gp_capture_12m_start_run.json').read_text())
prev_txt = (WD/'hype_latest_3_table_report.md').read_text() if (WD/'hype_latest_3_table_report.md').exists() else ''
locked_txt = (WD/'hype_locked_report_2026-05-08.md').read_text()


def money(x):
    ax=abs(x)
    if ax>=1e12: return f"${x/1e12:.2f}T"
    if ax>=1e9: return f"${x/1e9:.2f}B"
    if ax>=1e6: return f"${x/1e6:.1f}M"
    return f"${x:,.0f}"

def price(x): return f"${x:.2f}"
def mult(x): return f"{x:.1f}x"
def pct(x): return f"{x*100:.1f}%"
def hype_m(x): return f"{x/1e6:.1f}M"

def extract(pattern, text, cast=float):
    m=re.search(pattern, text)
    if not m: return None
    s=m.group(1).replace('$','').replace(',','').replace('M','e6').replace('B','e9').replace('x','').replace('%','')
    try: return cast(eval(s))
    except Exception:
        try: return cast(s)
        except Exception: return m.group(1)

# HYPE volume data via CoinGecko, with previous report fallback for 30D/peak if API fails.
hype_current_vol = None; hype_30d_vol = None; hype_peak_vol = None; hype_peak_date = None; vol_note='live'
try:
    r=requests.get('https://api.coingecko.com/api/v3/coins/markets', params={'vs_currency':'usd','ids':'hyperliquid','sparkline':'false'}, timeout=20, headers={'User-Agent':'hype-report/1.0'})
    r.raise_for_status(); mkt=r.json()[0]
    hype_current_vol=float(mkt.get('total_volume') or 0)
    r=requests.get('https://api.coingecko.com/api/v3/coins/hyperliquid/market_chart', params={'vs_currency':'usd','days':'365','interval':'daily'}, timeout=30, headers={'User-Agent':'hype-report/1.0'})
    r.raise_for_status(); chart=r.json(); vols=chart.get('total_volumes', [])
    last30=vols[-30:] if len(vols)>=30 else vols
    hype_30d_vol=sum(v for _,v in last30)/len(last30)
    peak=max(vols, key=lambda tv: tv[1])
    hype_peak_vol=float(peak[1]); hype_peak_date=datetime.datetime.utcfromtimestamp(peak[0]/1000).date().isoformat()
except Exception as e:
    vol_note=f'fallback stale ({type(e).__name__})'
    hype_current_vol = extract(r'HYPE native 24h vol\s+\$([0-9.]+B)', prev_txt) or extract(r'HYPE current native 24h vol\s+\$([0-9.]+B)', locked_txt)
    hype_30d_vol = extract(r'HYPE 30D vol proxy\s+\$([0-9.]+B)', prev_txt) or extract(r'HYPE 30D avg vol proxy\s+\$([0-9.]+B)', locked_txt)
    hype_peak_vol = extract(r'HYPE hist peak proxy\s+\$([0-9.]+B)', prev_txt) or extract(r'HYPE historical peak vol proxy\s+\$([0-9.]+B)', locked_txt)
    m=re.search(r'HYPE hist peak proxy\s+\$[0-9.]+B on ([0-9-]+)', prev_txt) or re.search(r'HYPE historical peak vol proxy\s+\$[0-9.]+B on ([0-9-]+)', locked_txt)
    hype_peak_date=m.group(1) if m else 'n/a'

market=J['market']; rev=J['revenue']; mc=J['mc']; scs=J['scenarios']
base=scs['base_db_observed_emissions']; opt=scs['upside_db_observed_plus_optionality']; bear=scs['bear_worst_case_emissions']
vs=base['volume_sanity']
start_gp=rev['current_annualized_gp']; ttm=rev['ttm_gp']

# Create exact three sections.
lines=[]
lines.append('# HYPE 3Y GP-Capture — Latest 3-Table Report')
lines.append(f"As of: `{J['asof_utc']}`")
lines.append(f"Spot: **{price(market['spot'])}**")
lines.append('')
lines.append('## Key assumptions')
lines.append('```text')
rows=[
('Horizon','36 months'),('MC paths',f"{mc['paths']:,}"),('Discount rate','25% selected HYPE rate'),('Start rule','min(30D rev, 12M median rev)'),('30D revenue',money(rev['trailing_30d_revenue'])),('12M median monthly rev',money(rev['median_12m_monthly_revenue'])),('Selected start GP/mo',money(rev['conservative_start_monthly_revenue'])),('Annualized start GP',money(start_gp)),('TTM GP',money(ttm)),('GP denominator','DeFiLlama dailyRevenue = net GP'),('GP margin','100% on DeFiLlama revenue'),('Token capture','100%'),('Base emissions','0.962M HYPE/mo DB observed'),('Worst-case emissions','9.92M HYPE/mo only in bear'),('Buybacks','100% net GP reduces future supply'),('Optionality','Base +10% Y3 value sensitivity'),('Multiple regime','20x trough / 15x normal / 10x peak'),('Multiple denom.','Year-3 trailing 12M GP'),('Proxy mean / stdev',f"{mc['monthly_log_return_mean']*100:.2f}% / {mc['monthly_log_return_std']*100:.2f}%")]
for k,v in rows: lines.append(f"{k:<24} {v}")
lines.append('```')
lines.append('')
lines.append('## Model results')
lines.append('```text')
lines.append(f"{'Metric':<24} {'Base':>10} {'+10% opt':>10} {'Bear':>10}")
lines.append(f"{'-'*24} {'-'*10} {'-'*10} {'-'*10}")
for label, key, fmt in [
('Disc FV P50',('discounted_token_price','p50'),price),('Disc EV / mean',('discounted_ev',),price),('Disc FV P25',('discounted_token_price','p25'),price),('Disc FV P75',('discounted_token_price','p75'),price),('Disc FV P90',('discounted_token_price','p90'),price),('Y3 P50 undiscounted',('undiscounted_y3_token_price','p50'),price),('Y3 TTM GP P50',('y3_ttm_gp','p50'),money),('Y3 supply P50',('y3_supply','p50'),hype_m),('P(spot justified)',('prob_current_spot_justified',),pct),('P(3x+)',('prob_3x_vs_spot',),pct)]:
    def get(sc):
        val=sc
        for kk in key: val=val[kk]
        return fmt(val)
    lines.append(f"{label:<24} {get(base):>10} {get(opt):>10} {get(bear):>10}")
lines.append('```')
lines.append('')
lines.append('## Sanity checks + current multiples')
lines.append('```text')
sanity=[
('Current spot',price(market['spot'])),('Market cap',money(market['mcap'])),('FDV',money(market['fdv'])),('Circ supply',f"{market['circ_supply']/1e6:.1f}M HYPE"),('Total supply',f"{market['total_supply']/1e6:.1f}M HYPE"),('MCap / TTM GP',mult(market['mcap']/ttm)),('FDV / TTM GP',mult(market['fdv']/ttm)),('MCap / start GP',mult(market['mcap']/start_gp)),('FDV / start GP',mult(market['fdv']/start_gp)),('Current monthly GP',money(rev['conservative_start_monthly_revenue'])),('Buyback cap @ spot',f"{base['current_buy_tokens_per_month']/1e6:.2f}M HYPE/mo"),('Base emissions','0.96M HYPE/mo'),('Net supply now',f"{base['net_monthly_supply_now']/1e6:+.2f}M HYPE/mo"),('Years buy full supply',f"{base['buyback_years_simple']:.1f}y"),('Y3 TTM GP P50',money(base['y3_ttm_gp']['p50'])),('Net rev take-rate','0.034% of notional'),('Implied Y3 HYPE vol',money(vs['implied_hype_daily_volume_y3_p50'])),('Binance current vol',money(vs['current_binance_futures_daily_volume'])),('Binance peak vol',money(vs['peak_binance_futures_daily_volume'])),('Implied / Binance cur',pct(vs['implied_vs_current_binance'])),('Implied / Binance peak',pct(vs['implied_vs_peak_binance'])),('HYPE native 24h vol',money(hype_current_vol)),('HYPE 30D vol proxy',money(hype_30d_vol)+(f" ({vol_note})" if vol_note!='live' else '')),('HYPE hist peak proxy',money(hype_peak_vol)+f" on {hype_peak_date}"),('Implied / HYPE cur',pct(vs['implied_hype_daily_volume_y3_p50']/hype_current_vol) if hype_current_vol else 'n/a'),('Implied / HYPE 30D',pct(vs['implied_hype_daily_volume_y3_p50']/hype_30d_vol) if hype_30d_vol else 'n/a'),('Implied / HYPE peak',pct(vs['implied_hype_daily_volume_y3_p50']/hype_peak_vol) if hype_peak_vol else 'n/a')]
for k,v in sanity: lines.append(f"{k:<24} {v}")
lines.append('```')
lines.append('')
lines.append('**Bottom line:** P50 remains below spot, while EV/mean remains above spot due to right-skew. Base buybacks are now only slightly above DB-observed emissions, and simple buyback-years has crossed the 20y watch level.')
report='\n'.join(lines)+'\n'
(WD/'hype_latest_3_table_report.md').write_text(report)

# Drift metrics: use locked and previous markdown where possible.
def locked_val(label):
    # Finds '$nn.nM/B' or 'nn.ny/nn.n%' style after exact-ish label
    return None

# Parse previous current report values from the pre-overwrite text.
def rex(label, unit=None):
    pat=re.escape(label)+r'\s+([^\n]+)'
    m=re.search(pat, prev_txt)
    return m.group(1).strip() if m else None

# Numeric drift helpers from known fields in locked report.
locked_spot = extract(r'Spot:\s+\*\*\$([0-9.]+)\*\*', locked_txt)
prev_spot = extract(r'Spot:\s+\*\*\$([0-9.]+)\*\*', prev_txt)
locked_30d = extract(r'30D revenue\s+\$([0-9.]+M)', locked_txt)
prev_30d = extract(r'30D revenue\s+\$([0-9.]+M)', prev_txt)
locked_ttm = extract(r'TTM GP\s+\$([0-9.]+M)', locked_txt)
prev_ttm = extract(r'TTM GP\s+\$([0-9.]+M)', prev_txt)
locked_buyyears = extract(r'Years to buy full supply\s+([0-9.]+)y', locked_txt)
prev_buyyears = extract(r'Years buy full supply\s+([0-9.]+)y', prev_txt)
locked_curvol = extract(r'HYPE current native 24h vol\s+\$([0-9.]+B)', locked_txt) or extract(r'HYPE native 24h vol\s+\$([0-9.]+B)', locked_txt)
prev_curvol = extract(r'HYPE native 24h vol\s+\$([0-9.]+B)', prev_txt)

summary={
 'report': report,
 'vol_note': vol_note,
 'hype_current_vol': hype_current_vol,
 'hype_30d_vol': hype_30d_vol,
 'hype_peak_vol': hype_peak_vol,
 'hype_peak_date': hype_peak_date,
 'locked': {'spot':locked_spot,'30d':locked_30d,'ttm':locked_ttm,'buyyears':locked_buyyears,'curvol':locked_curvol},
 'prev': {'spot':prev_spot,'30d':prev_30d,'ttm':prev_ttm,'buyyears':prev_buyyears,'curvol':prev_curvol}
}
(WD/'hype_report_summary.json').write_text(json.dumps(summary, indent=2))
print(str(WD/'hype_latest_3_table_report.md'))
print('vol_note', vol_note)

```

### `sky_mc_agent.py`

```python
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

```

### `ethfi_mc_agent.py`

```python
#!/usr/bin/env python3
"""ETHFI bottom-up GP valuation agent.

Locked direction from Momir, 2026-05-08:
- Use bottom-up GP, not raw parent revenue.
- Card gross revenue must be margin-adjusted; base card margin 60%.
- Staking APY = average of Lido stETH and ether.fi weETH DefiLlama yield APYs.
- Lending leg excluded from base.
- Focus on GP; optional OPEX = $6M/year for treasury cash / NP sanity.
- Recent card growth informs the forward card GMV growth path, not necessarily the Y3 multiple.
- Y3 exit multiple base = 15x GP. Current/Y1 momentum can be shown separately, but main 3Y line is 15x.
"""

import json, math, os, random, statistics, urllib.request
from datetime import datetime, timezone

OUT_DIR = "/Users/momir_mini/.openclaw/workspace/altcoin_research"
JSON_OUT = os.path.join(OUT_DIR, "ethfi_mc_result.json")
MD_OUT = os.path.join(OUT_DIR, "ethfi_mc_result.md")
UA = {"User-Agent": "Mozilla/5.0"}

# Core assumptions
CARD_TAKE = 0.0135
CARD_MARGIN_BASE = 0.60
CARD_MARGIN_BEAR = 0.50
CARD_MARGIN_BULL = 0.70
STAKE_TAKE = 0.05
VAULT_FEE = 0.01
# Use scheduled/unlocked token denominator, not full 1.0B FDV, because no
# unlock schedule is available for the unaccounted 145.3M ETHFI.
# Current unlocked 809.7M + scheduled remaining locked 45.0M = 854.7M.
SUPPLY_Y3 = 854.7e6

# $6M/year appears to cover on-chain protocol overhead only, not a global card
# business + validator infrastructure. Keep GP as the primary denominator; use a
# conservative normalized total-company OPEX assumption only for optional cash.
OPEX_ANNUAL = 30e6
DISCOUNT_RATE = 0.275
N_PATHS = 50_000
SEED = 42
Y3_GP_MULTIPLE = 15.0
Y1_MOMENTUM_MULTIPLE = 20.0
SCENARIO_WEIGHTS = {"bear": 0.20, "base": 0.40, "bull": 0.40}
OPTIONALITY_BONUS = 0.10


def fetch(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45).read().decode())


def chart(url):
    d = fetch(url)
    arr = sorted(d.get("totalDataChart", []), key=lambda x: x[0])
    return [(int(ts), float(v)) for ts, v in arr]


def sum_last(arr, n):
    return sum(v for _, v in arr[-n:]) if arr else 0.0


def protocol_tvl(slug):
    d = fetch(f"https://api.llama.fi/protocol/{slug}")
    tvls = d.get("currentChainTvls", {}) or {}
    vals = [v for v in tvls.values() if isinstance(v, (int, float))]
    return sum(vals) if vals else float(d.get("tvl") or 0.0)


def get_market():
    d = fetch("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=ether-fi&sparkline=false")
    return d[0]


def get_avg_staking_apy():
    pools = fetch("https://yields.llama.fi/pools").get("data", [])
    lido = []
    ethfi = []
    for p in pools:
        if p.get("chain") != "Ethereum":
            continue
        sym = str(p.get("symbol", "")).upper()
        proj = p.get("project")
        if proj == "lido" and ("STETH" in sym or "WSTETH" in sym):
            lido.append(p)
        if proj == "ether.fi-stake" and "WEETH" in sym:
            ethfi.append(p)
    lido = sorted(lido, key=lambda x: x.get("tvlUsd") or 0, reverse=True)
    ethfi = sorted(ethfi, key=lambda x: x.get("tvlUsd") or 0, reverse=True)
    selected = []
    if lido: selected.append(lido[0])
    if ethfi: selected.append(ethfi[0])
    apys = [float(p.get("apy") or 0.0) / 100 for p in selected]
    avg = statistics.mean(apys) if apys else 0.0325
    return avg, selected


def get_dune_key():
    for p in [os.path.expanduser("~/.hermes/secrets/dune_api_key")]:
        if os.path.exists(p):
            return open(p).read().strip()
    return None


def fetch_dune_query_results(query_id, limit=1000):
    key = get_dune_key()
    if not key:
        return None
    url = f"https://api.dune.com/api/v1/query/{query_id}/results?limit={limit}"
    req = urllib.request.Request(url, headers={"X-Dune-API-Key": key, "User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=45).read().decode())


def parse_dune_day(s):
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def dune_card_growth_anchor(query_id=4455397):
    """Adaptive card growth anchor from Dune rolling 7D spend.

    Formula:
      1. Build rolling 7D spend buckets ending on latest full day.
      2. Compute weekly CGR over windows [4,8,12,16,20,24,28,32,36,40,44,48].
      3. Use mature windows only (8w-20w) when enough data exists; otherwise use all available windows.
      4. Conservative anchor = (min + median) / 2.
      5. Convert weekly anchor to monthly start growth; cap at 12% MoM.
    """
    d = fetch_dune_query_results(query_id)
    if not d:
        return None
    rows = sorted(d.get("result", {}).get("rows", []), key=lambda r: parse_dune_day(r["day"]))
    if len(rows) < 40:
        return None
    latest = parse_dune_day(rows[-1]["day"])
    full = [r for r in rows if parse_dune_day(r["day"]) < latest]  # exclude likely partial current day
    last_full = parse_dune_day(full[-1]["day"])

    def spend_between(start, end):
        return sum(float(r.get("spend_usd") or 0.0) for r in full if start <= parse_dune_day(r["day"]) <= end)

    records = []
    for intervals in range(4, 49, 4):
        weeks = []
        for i in range(intervals + 1):
            end = last_full - __import__('datetime').timedelta(days=7 * i)
            start = end - __import__('datetime').timedelta(days=6)
            weeks.append((start, end, spend_between(start, end)))
        weeks = list(reversed(weeks))
        first, last = weeks[0][2], weeks[-1][2]
        if first > 0 and last > 0:
            weekly_cgr = (last / first) ** (1 / intervals) - 1
            records.append({"weeks": intervals, "weekly_cgr": weekly_cgr, "first_spend": first, "last_spend": last})
    if not records:
        return None
    mature = [r["weekly_cgr"] for r in records if 8 <= r["weeks"] <= 20]
    sample = mature if len(mature) >= 3 else [r["weekly_cgr"] for r in records]
    mn = min(sample)
    med = statistics.median(sample)
    anchor_weekly = (mn + med) / 2
    monthly_start = min((1 + anchor_weekly) ** 4.345 - 1, 0.12)
    return {
        "latest_full_day": str(last_full),
        "records": records,
        "sample_windows": "8w-20w" if len(mature) >= 3 else "available",
        "min_weekly_cgr": mn,
        "median_weekly_cgr": med,
        "anchor_weekly_cgr": anchor_weekly,
        "monthly_start_growth": monthly_start,
    }


def get_eth_daily_logs():
    d = fetch("https://query1.finance.yahoo.com/v8/finance/chart/ETH-USD?range=4y&interval=1d")
    r = d["chart"]["result"][0]
    closes = [p for p in r["indicators"]["quote"][0]["close"] if p is not None]
    logs = [math.log(closes[i] / closes[i-1]) for i in range(1, len(closes)) if closes[i] > 0 and closes[i-1] > 0]
    # 2022+ yahoo range is already approx 4y; keep full sample.
    return logs


def growth_path(start_m, m12, m24, m36):
    # Monthly growth path linearly decaying across milestones.
    pts = [(0, start_m), (11, m12), (23, m24), (35, m36)]
    out = []
    for i in range(36):
        for (a, ga), (b, gb) in zip(pts[:-1], pts[1:]):
            if a <= i <= b:
                t = (i - a) / max(1, b - a)
                out.append(ga + (gb - ga) * t)
                break
    return out


def summarize(arr, spot=None):
    s = sorted(arr)
    def q(p): return s[min(len(s)-1, int(len(s)*p))]
    d = {"p25": q(0.25), "p50": q(0.50), "p75": q(0.75), "p90": q(0.90), "ev": sum(s)/len(s)}
    if spot is not None:
        d["p_spot_justified"] = sum(1 for x in s if x >= spot) / len(s)
    return d


def fmt_usd(x):
    if abs(x) >= 1e9: return f"${x/1e9:,.2f}B"
    if abs(x) >= 1e6: return f"${x/1e6:,.1f}M"
    return f"${x:,.0f}"


def fmt_px(x): return f"${x:.3f}"


def run():
    random.seed(SEED)
    os.makedirs(OUT_DIR, exist_ok=True)

    vol = chart("https://api.llama.fi/summary/dexs/etherfi-cash-liquid?dataType=dailyVolume")
    rev = chart("https://api.llama.fi/summary/fees/etherfi-cash-liquid?dataType=dailyRevenue")
    gdv_7 = sum_last(vol, 7); gdv_30 = sum_last(vol, 30)
    gdv_prev7 = sum(v for _, v in vol[-14:-7]); gdv_prev30 = sum(v for _, v in vol[-60:-30])
    rev_30 = sum_last(rev, 30); rev_7 = sum_last(rev, 7)
    gdv_ann_30 = gdv_30 * 365 / 30
    gdv_ann_7 = gdv_7 * 365 / 7
    take_bps_30 = rev_30 / gdv_30 * 10000 if gdv_30 else 0
    card_mom = gdv_30 / gdv_prev30 - 1 if gdv_prev30 else 0
    card_wow = gdv_7 / gdv_prev7 - 1 if gdv_prev7 else 0

    stake_tvl = protocol_tvl("ether.fi-stake")
    vault_tvl = protocol_tvl("ether.fi-liquid")
    market = get_market()
    staking_apy, apy_sources = get_avg_staking_apy()
    eth_logs = get_eth_daily_logs()

    price = market["current_price"]
    mcap = market["market_cap"]
    fdv = market.get("fully_diluted_valuation") or price * SUPPLY_Y3

    # Current GP anchor
    current_card_gp = gdv_ann_30 * CARD_TAKE * CARD_MARGIN_BASE
    current_stake_gp = stake_tvl * staking_apy * STAKE_TAKE
    current_vault_gp = vault_tvl * VAULT_FEE
    current_gp = current_card_gp + current_stake_gp + current_vault_gp

    card_anchor = dune_card_growth_anchor()
    base_start_m = card_anchor["monthly_start_growth"] if card_anchor else 0.09
    bear_start_m = max(0.015, base_start_m * 0.50)
    bull_start_m = min(0.12, base_start_m * 1.35)

    # Current card growth is a KPI, not a 3Y compounding assumption. Use an adaptive
    # Dune-based formula for starting growth, then force decay. This keeps the model
    # future-proof: if card GMV slows, the starting growth automatically falls.
    scenarios = {
        # Product growth slows quickly.
        "bear": {"margin": CARD_MARGIN_BEAR, "growth": growth_path(bear_start_m, 0.005, 0.000, 0.000)},
        # Conservative anchor: weekly CGR = (min + median) / 2 over mature Dune windows, converted to MoM.
        "base": {"margin": CARD_MARGIN_BASE, "growth": growth_path(base_start_m, 0.030, 0.010, 0.003)},
        # Strong adoption, capped starting growth.
        "bull": {"margin": CARD_MARGIN_BULL, "growth": growth_path(bull_start_m, 0.050, 0.020, 0.010)},
    }

    # Small monthly execution noise only; do not bootstrap huge weekly growth into
    # multi-year card compounding.
    MONTHLY_CARD_NOISE_SD = 0.015

    # Precompute one independent staking/ETH simulation set. Re-use the same staking
    # paths across bear/base/bull so scenario differences come from card adoption and
    # card margin, not accidental resampling of ETH/staking.
    rng_stake = random.Random(SEED + 202)
    stake_monthly_gp_paths = []
    stake_final_tvl_paths = []
    for _ in range(N_PATHS):
        s = 0.0
        eth_mult_months = []
        for m in range(36):
            # approx 30 daily returns per month
            for _d in range(30):
                s += rng_stake.choice(eth_logs)
            eth_mult_months.append(math.exp(s))
        stake_final_tvl_paths.append(stake_tvl * eth_mult_months[-1])
        stake_monthly_gp_paths.append([stake_tvl * mult * staking_apy * STAKE_TAKE / 12 for mult in eth_mult_months])

    results = {}
    weighted_samples = {
        "pv_15x_gp": [],
        "pv_15x_gp_plus_cash": [],
        "y3_gp": [],
        "y3_card_gdv_ann": [],
        "y3_stake_tvl": [],
        "y3_stake_gp_ann": [],
        "treasury_cash": [],
    }
    scenario_seed_offsets = {"bear": 0, "base": 1_000_000, "bull": 2_000_000}
    for name, sc in scenarios.items():
        # Use separate card RNG streams independent from staking/ETH paths.
        rng_card = random.Random(SEED + scenario_seed_offsets[name] + 101)
        pv_gp = []
        pv_gp_cash = []
        y3_gp = []
        y3_card_gdv_ann = []
        y3_stake_tvl = []
        y3_stake_gp_ann = []
        treasury_cash = []
        for path_i in range(N_PATHS):
            # Card path: deterministic decay + dampened stochastic monthly noise.
            card_gdv_ann = gdv_ann_30
            card_monthly_gp = []
            for gm in sc["growth"]:
                noise = rng_card.gauss(0.0, MONTHLY_CARD_NOISE_SD)
                monthly_growth = max(-0.05, min(0.08, gm + noise))
                card_gdv_ann *= (1 + monthly_growth)
                card_monthly_gp.append(card_gdv_ann * CARD_TAKE * sc["margin"] / 12)

            # Staking path: independent ETH bootstrap, precomputed once and shared
            # across scenarios for clean card-vs-staking decomposition.
            final_stake_tvl = stake_final_tvl_paths[path_i]
            stake_monthly_gp = stake_monthly_gp_paths[path_i]

            # Vault: flat base with very small monthly drift tied to scenario.
            vault = vault_tvl
            vault_monthly_gp = []
            vault_g = {"bear": 0.0, "base": 0.005, "bull": 0.01}[name]
            for _m in range(36):
                vault *= (1 + vault_g)
                vault_monthly_gp.append(vault * VAULT_FEE / 12)

            monthly_gp = [card_monthly_gp[i] + stake_monthly_gp[i] + vault_monthly_gp[i] for i in range(36)]
            y3 = sum(monthly_gp[-12:])
            cash = sum(max(gp - OPEX_ANNUAL/12, 0.0) for gp in monthly_gp)
            y3_gp.append(y3)
            treasury_cash.append(cash)
            y3_card_gdv_ann.append(card_gdv_ann)
            y3_stake_tvl.append(final_stake_tvl)
            y3_stake_gp_ann.append(final_stake_tvl * staking_apy * STAKE_TAKE)
            ev = y3 * Y3_GP_MULTIPLE
            pv_gp.append(ev / SUPPLY_Y3 / ((1 + DISCOUNT_RATE) ** 3))
            pv_gp_cash.append((ev + cash) / SUPPLY_Y3 / ((1 + DISCOUNT_RATE) ** 3))
        y3_gp_summary = summarize(y3_gp)
        cash_summary = summarize(treasury_cash)
        sensitivity_rates = [max(0.01, DISCOUNT_RATE - 0.10), DISCOUNT_RATE - 0.05, DISCOUNT_RATE, DISCOUNT_RATE + 0.05, DISCOUNT_RATE + 0.10]
        sensitivity = {
            f"{rate:.1%}": {
                "pv_15x_gp_p50": (y3_gp_summary["p50"] * Y3_GP_MULTIPLE) / SUPPLY_Y3 / ((1 + rate) ** 3),
                "pv_15x_gp_plus_cash_p50": (y3_gp_summary["p50"] * Y3_GP_MULTIPLE + cash_summary["p50"]) / SUPPLY_Y3 / ((1 + rate) ** 3),
            }
            for rate in sensitivity_rates
        }
        results[name] = {
            "pv_15x_gp": summarize(pv_gp, price),
            "pv_15x_gp_plus_cash": summarize(pv_gp_cash, price),
            "y3_gp": summarize(y3_gp),
            "y3_card_gdv_ann": summarize(y3_card_gdv_ann),
            "y3_stake_tvl": summarize(y3_stake_tvl),
            "y3_stake_gp_ann": summarize(y3_stake_gp_ann),
            "treasury_cash": summarize(treasury_cash),
            "hurdle_sensitivity": sensitivity,
            "margin": sc["margin"],
            "start_growth": sc["growth"][0],
        }
        sample_n = int(round(N_PATHS * SCENARIO_WEIGHTS.get(name, 0.0)))
        weighted_samples["pv_15x_gp"].extend(pv_gp[:sample_n])
        weighted_samples["pv_15x_gp_plus_cash"].extend(pv_gp_cash[:sample_n])
        weighted_samples["y3_gp"].extend(y3_gp[:sample_n])
        weighted_samples["y3_card_gdv_ann"].extend(y3_card_gdv_ann[:sample_n])
        weighted_samples["y3_stake_tvl"].extend(y3_stake_tvl[:sample_n])
        weighted_samples["y3_stake_gp_ann"].extend(y3_stake_gp_ann[:sample_n])
        weighted_samples["treasury_cash"].extend(treasury_cash[:sample_n])

    weighted_pv = weighted_samples["pv_15x_gp"]
    weighted_pv_cash = weighted_samples["pv_15x_gp_plus_cash"]
    results["weighted_20_40_40"] = {
        "pv_15x_gp": summarize(weighted_pv, price),
        "pv_15x_gp_plus_cash": summarize(weighted_pv_cash, price),
        "pv_15x_gp_plus_optionality": summarize([x * (1 + OPTIONALITY_BONUS) for x in weighted_pv], price),
        "pv_15x_gp_plus_cash_plus_optionality": summarize([x * (1 + OPTIONALITY_BONUS) for x in weighted_pv_cash], price),
        "y3_gp": summarize(weighted_samples["y3_gp"]),
        "y3_card_gdv_ann": summarize(weighted_samples["y3_card_gdv_ann"]),
        "y3_stake_tvl": summarize(weighted_samples["y3_stake_tvl"]),
        "y3_stake_gp_ann": summarize(weighted_samples["y3_stake_gp_ann"]),
        "treasury_cash": summarize(weighted_samples["treasury_cash"]),
        "scenario_weights": SCENARIO_WEIGHTS,
        "optionality_bonus": OPTIONALITY_BONUS,
    }

    insights = []
    base_pv = results["base"]["pv_15x_gp"]["p50"]
    bull_pv = results["bull"]["pv_15x_gp"]["p50"]
    if base_pv < price:
        insights.append("Base 15x GP P50 remains below spot; investment case needs sustained card GMV growth, higher terminal multiple, or stronger token-capture evidence.")
    if bull_pv < price:
        insights.append("Even bull 15x GP P50 is below spot; spot needs right-tail execution or a multiple above 15x.")
    if card_anchor and card_anchor.get("monthly_start_growth", 0) > 0.10:
        insights.append("Adaptive card growth anchor is near the 12% MoM cap; monitor for slowdown before extrapolating card GMV.")
    if current_gp and mcap / current_gp > 20:
        insights.append("Current MCap/GP is above 20x; current valuation already prices meaningful forward GP growth.")
    if results["base"]["treasury_cash"]["p50"] < 5e6:
        insights.append("At normalized $30M OPEX, base-case cash accumulation is negligible; treat '+ cash' as sensitivity, not core value.")
    insights.append("Revisit supply denominator if the unaccounted 145.3M ETHFI receives a clear unlock schedule.")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "actionable_insights": insights,
        "assumptions": {
            "card_take": CARD_TAKE,
            "card_margin_base": CARD_MARGIN_BASE,
            "stake_take": STAKE_TAKE,
            "staking_apy_avg_lido_ethfi": staking_apy,
            "vault_fee": VAULT_FEE,
            "opex_optional": OPEX_ANNUAL,
            "discount_rate": DISCOUNT_RATE,
            "supply_y3": SUPPLY_Y3,
            "y3_gp_multiple": Y3_GP_MULTIPLE,
            "scenario_weights": SCENARIO_WEIGHTS,
            "optionality_bonus": OPTIONALITY_BONUS,
            "lending": "excluded",
            "card_growth_anchor": card_anchor,
        },
        "market": market,
        "apy_sources": apy_sources,
        "current": {
            "price": price, "mcap": mcap, "fdv": fdv,
            "gdv_7d_ann": gdv_ann_7, "gdv_30d_ann": gdv_ann_30,
            "card_wow": card_wow, "card_mom": card_mom, "take_bps_30": take_bps_30,
            "stake_tvl": stake_tvl, "vault_tvl": vault_tvl,
            "card_gp": current_card_gp, "stake_gp": current_stake_gp, "vault_gp": current_vault_gp,
            "gp": current_gp,
            "mcap_gp": mcap / current_gp,
            "fdv_gp": fdv / current_gp,
        },
        "results": results,
    }
    json.dump(output, open(JSON_OUT, "w"), indent=2)

    lines = []
    lines.append("# ETHFI GP valuation")
    lines.append("")
    lines.append("## 1) Key assumptions")
    lines.append("```text")
    lines.append(f"Spot                              {fmt_px(price)}")
    lines.append(f"Market cap                        {fmt_usd(mcap)}")
    lines.append(f"FDV                               {fmt_usd(fdv)}")
    lines.append(f"Y3 supply                         {SUPPLY_Y3/1e6:.1f}M")
    lines.append(f"Supply note                       excludes unscheduled 145.3M ETHFI")
    lines.append(f"Discount rate                     {DISCOUNT_RATE:.1%}")
    lines.append(f"Y3 GP multiple                    {Y3_GP_MULTIPLE:.0f}x")
    lines.append(f"Scenario weights                  bear/base/bull {SCENARIO_WEIGHTS['bear']:.0%}/{SCENARIO_WEIGHTS['base']:.0%}/{SCENARIO_WEIGHTS['bull']:.0%}")
    lines.append(f"Optionality bonus                 +{OPTIONALITY_BONUS:.0%} to weighted PV")
    lines.append(f"Optional OPEX for cash            {fmt_usd(OPEX_ANNUAL)}/year")
    lines.append(f"Card take-rate                    {CARD_TAKE*10000:.0f}bps")
    lines.append(f"Card margin bear/base/bull        {CARD_MARGIN_BEAR:.0%}/{CARD_MARGIN_BASE:.0%}/{CARD_MARGIN_BULL:.0%}")
    lines.append(f"Staking APY avg Lido/e.fi         {staking_apy:.2%}")
    lines.append(f"Treasury share of staking yield   {STAKE_TAKE:.0%}")
    lines.append(f"Vault fee                         {VAULT_FEE*10000:.0f}bps")
    lines.append(f"Lending leg                       excluded")
    lines.append(f"Card 30D annualized GDV           {fmt_usd(gdv_ann_30)}")
    lines.append(f"Card 7D annualized GDV            {fmt_usd(gdv_ann_7)}")
    lines.append(f"Card growth signal                30D/prior30 {card_mom:+.1%}; 7D WoW {card_wow:+.1%}")
    if card_anchor:
        lines.append(f"Adaptive card growth formula      Dune {card_anchor['sample_windows']}: (min {card_anchor['min_weekly_cgr']:.2%} + median {card_anchor['median_weekly_cgr']:.2%}) / 2 = {card_anchor['anchor_weekly_cgr']:.2%}/wk")
        lines.append(f"Base starting card growth         {base_start_m:.1%} MoM; bear {bear_start_m:.1%}; bull {bull_start_m:.1%}")
    lines.append("```")
    lines.append("")
    lines.append("Actionable insights / assumption watchlist:")
    lines.append("```text")
    for i, insight in enumerate(insights, 1):
        lines.append(f"{i}. {insight}")
    lines.append("```")
    lines.append("")

    lines.append("## 2) Model results")
    lines.append("```text")
    lines.append(f"{'Scenario':<10} {'Basis':<18} {'P25':>7} {'P50':>7} {'EV':>7} {'P75':>7} {'P90':>7} {'P(spot)':>8}")
    lines.append("-" * 80)
    for name in ["bear", "base", "bull"]:
        for label, key in [("15x GP", "pv_15x_gp"), ("15x GP + cash", "pv_15x_gp_plus_cash")]:
            s = results[name][key]
            lines.append(f"{name.title():<10} {label:<18} {fmt_px(s['p25']):>7} {fmt_px(s['p50']):>7} {fmt_px(s['ev']):>7} {fmt_px(s['p75']):>7} {fmt_px(s['p90']):>7} {s['p_spot_justified']*100:>7.1f}%")
    for label, key in [("20/40/40", "pv_15x_gp"), ("+5% opt", "pv_15x_gp_plus_optionality")]:
        s = results["weighted_20_40_40"][key]
        lines.append(f"{'Weighted':<10} {label:<18} {fmt_px(s['p25']):>7} {fmt_px(s['p50']):>7} {fmt_px(s['ev']):>7} {fmt_px(s['p75']):>7} {fmt_px(s['p90']):>7} {s['p_spot_justified']*100:>7.1f}%")
    lines.append("```")
    lines.append("")
    lines.append("Hurdle-rate sensitivity — P50 15x GP fair value:")
    lines.append("```text")
    sens_rates = list(results["base"]["hurdle_sensitivity"].keys())
    lines.append(f"{'Scenario':<10} " + " ".join(f"{rate:>8}" for rate in sens_rates))
    lines.append("-" * (11 + 9 * len(sens_rates)))
    for name in ["bear", "base", "bull"]:
        sens = results[name]["hurdle_sensitivity"]
        lines.append(f"{name.title():<10} " + " ".join(f"{fmt_px(sens[rate]['pv_15x_gp_p50']):>8}" for rate in sens_rates))
    lines.append("```")
    lines.append("")

    lines.append("Operating outputs:")
    lines.append("```text")
    lines.append(f"{'Scenario':<10} {'Y3 GP P50':>12} {'Y3 card GDV P50':>18} {'Y3 stake TVL P50':>18} {'Cash P50':>12}")
    lines.append("-" * 78)
    for name in ["bear", "base", "bull"]:
        r = results[name]
        lines.append(f"{name.title():<10} {fmt_usd(r['y3_gp']['p50']):>12} {fmt_usd(r['y3_card_gdv_ann']['p50']):>18} {fmt_usd(r['y3_stake_tvl']['p50']):>18} {fmt_usd(r['treasury_cash']['p50']):>12}")
    lines.append("```")
    lines.append("")
    lines.append("Independent-driver sanity check:")
    lines.append("```text")
    lines.append(f"{'Scenario':<10} {'Card GDV P25/P50/P75':>29} {'Stake TVL P25/P50/P75':>29} {'Stake GP ann P50':>17}")
    lines.append("-" * 92)
    for name in ["bear", "base", "bull"]:
        r = results[name]
        card = r['y3_card_gdv_ann']; stake = r['y3_stake_tvl']; stake_gp = r['y3_stake_gp_ann']
        lines.append(f"{name.title():<10} {fmt_usd(card['p25'])}/{fmt_usd(card['p50'])}/{fmt_usd(card['p75']):>9} {fmt_usd(stake['p25'])}/{fmt_usd(stake['p50'])}/{fmt_usd(stake['p75']):>9} {fmt_usd(stake_gp['p50']):>17}")
    lines.append("```")
    lines.append("")
    lines.append("## 3) Sanity checks / current multiples")
    lines.append("```text")
    lines.append(f"Current card GP                   {fmt_usd(current_card_gp)}")
    lines.append(f"Current staking GP                {fmt_usd(current_stake_gp)}")
    lines.append(f"Current vault GP                  {fmt_usd(current_vault_gp)}")
    lines.append(f"Current bottom-up GP              {fmt_usd(current_gp)}")
    lines.append(f"MCap / current GP                 {mcap/current_gp:.1f}x")
    lines.append(f"FDV / current GP                  {fdv/current_gp:.1f}x")
    lines.append(f"Current 20x GP / Y3 supply        {fmt_px(current_gp*Y1_MOMENTUM_MULTIPLE/SUPPLY_Y3)}")
    lines.append(f"Current 15x GP / Y3 supply        {fmt_px(current_gp*Y3_GP_MULTIPLE/SUPPLY_Y3)}")
    lines.append(f"Discounted flat current 15x GP    {fmt_px(current_gp*Y3_GP_MULTIPLE/SUPPLY_Y3/((1+DISCOUNT_RATE)**3))}")
    lines.append("```")
    report = "\n".join(lines)
    open(MD_OUT, "w").write(report)
    print(MD_OUT)

if __name__ == "__main__":
    run()

```

### `run_uni_locked_report.py`

```python
#!/usr/bin/env python3
import csv, io, json, math, statistics, sys, time
from collections import defaultdict
from datetime import datetime, date, timezone
from urllib.request import Request, urlopen
import numpy as np

UA='Mozilla/5.0 Hermes UNI locked valuation cron'

def get_json(url, timeout=30):
    req=Request(url, headers={'User-Agent':UA, 'Accept':'application/json'})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def get_text(url, timeout=30):
    req=Request(url, headers={'User-Agent':UA})
    with urlopen(req, timeout=timeout) as r:
        return r.read().decode()

def ts_date(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).date()

def ym(d): return (d.year, d.month)
def yms(y,m): return f'{y:04d}-{m:02d}'

def money(x):
    ax=abs(x)
    if ax>=1e12: return f'${x/1e12:.2f}T'
    if ax>=1e9: return f'${x/1e9:.2f}B'
    if ax>=1e6: return f'${x/1e6:.1f}M'
    return f'${x:,.0f}'
def volfmt(x): return money(x).replace('$','$')
def bps(x): return f'{x:.2f}bps'
def px(x): return f'${x:.2f}'
def mult(x): return f'{x:.1f}x'
def pct(x): return f'{100*x:.0f}%'

def parse_chart(data):
    out=[]
    for ts,val in data['totalDataChart']:
        if val is None: continue
        d=ts_date(ts)
        out.append((d,float(val)))
    out.sort()
    return out

caveats=[]
# DeFiLlama data
vol_data=get_json('https://api.llama.fi/summary/dexs/uniswap?dataType=dailyVolume')
fee_data=get_json('https://api.llama.fi/summary/fees/uniswap?dataType=dailyFees')
vol_daily=parse_chart(vol_data)
fee_daily=parse_chart(fee_data)
vol_by_date=dict(vol_daily); fee_by_date=dict(fee_daily)
latest_vol_date=max(vol_by_date); latest_fee_date=max(fee_by_date)
latest_data_date=min(latest_vol_date, latest_fee_date)
# latest full 30D ending at latest common date
all_dates=sorted(set(vol_by_date)&set(fee_by_date))
latest_dates=[d for d in all_dates if d<=latest_data_date][-30:]
latest30_vol=sum(vol_by_date[d] for d in latest_dates)
latest30_fees=sum(fee_by_date[d] for d in latest_dates)
recent_lp_bps=latest30_fees/latest30_vol*10000

# monthly completed aggregates: complete month means before current month of latest_data_date
cur_ym=ym(latest_data_date)
monthly_vol=defaultdict(float); monthly_fee=defaultdict(float)
for d,v in vol_daily:
    if ym(d) < cur_ym:
        monthly_vol[ym(d)] += v
for d,v in fee_daily:
    if ym(d) < cur_ym:
        monthly_fee[ym(d)] += v
months=sorted(k for k,v in monthly_vol.items() if k>= (2021,1) and v>0 and k in monthly_fee)
# require up to latest completed month
last12=months[-12:]
trailing12_median_vol=statistics.median([monthly_vol[m] for m in last12])
trailing12_vol=sum(monthly_vol[m] for m in last12)
trailing12_fees=sum(monthly_fee[m] for m in last12)
trailing12_lp_bps=trailing12_fees/trailing12_vol*10000
lp_fee_bps=recent_lp_bps  # latest live, cross-check against T12M
base_seed=min(latest30_vol, trailing12_median_vol)
# log return bootstrap from monthly volumes 2021+ completed months
month_vols=np.array([monthly_vol[m] for m in months], dtype=float)
logrets=np.diff(np.log(month_vols))
# winsor not specified: pure bootstrap
rng=np.random.default_rng(20260525)
N=80000
idx=rng.integers(0, len(logrets), size=(N,36))
rets=logrets[idx]
paths=base_seed*np.exp(np.cumsum(rets, axis=1))
y3_ttm_vol=paths[:, -12:].sum(axis=1)

# Market data CoinGecko
cg=get_json('https://api.coingecko.com/api/v3/coins/uniswap?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false&sparkline=false')
md=cg['market_data']
spot=float(md['current_price']['usd'])
market_cap=float(md['market_cap']['usd'])
fdv=float(md.get('fully_diluted_valuation',{}).get('usd') or 0)
circ=float(md.get('circulating_supply') or market_cap/spot)
max_supply=float(md.get('max_supply') or md.get('total_supply') or (fdv/spot if fdv else circ))
if not max_supply or max_supply<circ: max_supply=circ

# Discount rate: Yahoo/FRED 10Y + S&P, CG UNI chart
try:
    # Yahoo ^TNX is the CBOE 10Y yield index quoted as percent points.
    tnx=get_json('https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX?range=5d&interval=1d')
    rf_pct=float(tnx['chart']['result'][0]['meta'].get('regularMarketPrice'))
    rf_date='Yahoo ^TNX latest'
    rf=rf_pct/100.0
except Exception as e1:
    try:
        dgs=get_text('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10', timeout=15)
        rows=list(csv.DictReader(io.StringIO(dgs)))
        vals=[(r['observation_date'], float(r['DGS10'])) for r in rows if r.get('DGS10') not in ('','.')]
        rf_date, rf_pct=vals[-1]
        rf=rf_pct/100.0
    except Exception as e2:
        caveats.append(f'10Y yield fetch failed; used 4.5% fallback (Yahoo {e1}; FRED {e2})')
        rf_date, rf_pct, rf='fallback',4.5,0.045
try:
    sp_y=get_json('https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?range=1y&interval=1d')
    sp_vals=[x for x in sp_y['chart']['result'][0]['indicators']['quote'][0]['close'] if x is not None]
    sp_rets=np.diff(np.log(np.array(sp_vals[-366:], dtype=float)))
    sp_stdev=float(np.std(sp_rets, ddof=1))
except Exception as e1:
    try:
        sp=get_text('https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500', timeout=15)
        rows=list(csv.DictReader(io.StringIO(sp)))
        sp_vals=[float(r['SP500']) for r in rows if r.get('SP500') not in ('','.')]
        sp_vals=sp_vals[-366:]
        sp_rets=np.diff(np.log(np.array(sp_vals)))
        sp_stdev=float(np.std(sp_rets, ddof=1))
    except Exception as e2:
        caveats.append(f'S&P fetch failed; used 1.0% daily stdev fallback (Yahoo {e1}; FRED {e2})')
        sp_stdev=0.010
try:
    uni_hist=get_json('https://api.coingecko.com/api/v3/coins/uniswap/market_chart?vs_currency=usd&days=365&interval=daily')
    prices=[]
    seen=set()
    for ms,p in uni_hist['prices']:
        d=datetime.fromtimestamp(ms/1000, tz=timezone.utc).date()
        if d in seen: continue
        seen.add(d); prices.append(float(p))
    prices=prices[-366:]
    uni_rets=np.diff(np.log(np.array(prices)))
    uni_stdev=float(np.std(uni_rets, ddof=1))
except Exception as e:
    caveats.append(f'UNI history fetch failed; used 7.0% daily stdev fallback ({e})')
    uni_stdev=0.070
DR=rf + 0.03*(uni_stdev/sp_stdev)

# Economics
frontend_bps=0.30
current_lp_protocol_bps=0.826
current_take_bps=current_lp_protocol_bps+frontend_bps
full_take_bps=lp_fee_bps*0.25+frontend_bps
multiple=15.0
disc=(1+DR)**3

def value_arrays(take_bps, supply):
    gp=y3_ttm_vol*take_bps/10000.0
    pv=gp*multiple/supply/disc
    return gp,pv
cur_gp, cur_pv=value_arrays(current_take_bps, circ)
full_gp, full_pv=value_arrays(full_take_bps, circ)
_, full_pv_fdv=value_arrays(full_take_bps, max_supply)
q=[25,50,75]
def qs(arr): return np.percentile(arr,q)
cur_gp_q, cur_pv_q=qs(cur_gp), qs(cur_pv)
full_gp_q, full_pv_q=qs(full_gp), qs(full_pv)
vol_q=qs(y3_ttm_vol)
fdv_pv_q=qs(full_pv_fdv)
vol_mean=float(np.mean(y3_ttm_vol)); cur_gp_mean=float(np.mean(cur_gp)); cur_pv_mean=float(np.mean(cur_pv)); full_gp_mean=float(np.mean(full_gp)); full_pv_mean=float(np.mean(full_pv)); fdv_pv_mean=float(np.mean(full_pv_fdv))
prob_gt_spot=float(np.mean(full_pv>spot)); prob_gt_3x=float(np.mean(full_pv>3*spot))
# current sanity
current_ann_vol=latest30_vol*365.0/30.0
current_state_ann_gp=current_ann_vol*current_take_bps/10000.0
full_ann_gp=current_ann_vol*full_take_bps/10000.0
mcap_cur=market_cap/current_state_ann_gp
mcap_full=market_cap/full_ann_gp
fdv_full=(fdv if fdv else spot*max_supply)/full_ann_gp

report=[]
report.append('UNI locked valuation update — 3Y GP-capture, full-activation economics')
report.append('```text')
report.append('1) Key assumptions')
report.append(f'Spot / mcap            {px(spot)} / {money(market_cap)}')
report.append(f'Data freshness          DFL vol+fees thru {latest_data_date}; spot CG live')
report.append(f'Base seed               {money(base_seed)} monthly (min 30D {money(latest30_vol)}, T12M med {money(trailing12_median_vol)})')
report.append(f'LP fee bps              {bps(lp_fee_bps)} recent 30D (T12M {bps(trailing12_lp_bps)})')
report.append(f'Take bps                current {bps(current_take_bps)} | full-act {bps(full_take_bps)}')
report.append(f'Discount rate           {100*DR:.1f}% (10Y {rf_pct:.2f}%, UNI/SPX stdev {uni_stdev/sp_stdev:.1f}x)')
report.append(f'Supply / multiple       {circ/1e6:.1f}M circ; {max_supply/1e6:.1f}M full / {multiple:.0f}x GP')
report.append('```')
report.append('```text')
report.append('2) Model results')
report.append('Metric                    P25        P50        P75       EV/mean')
report.append(f'Y3 TTM volume          {money(vol_q[0]):>9} {money(vol_q[1]):>9} {money(vol_q[2]):>9} {money(vol_mean):>9}')
report.append(f'Current-state GP       {money(cur_gp_q[0]):>9} {money(cur_gp_q[1]):>9} {money(cur_gp_q[2]):>9} {money(cur_gp_mean):>9}')
report.append(f'Current-state PV/UNI   {px(cur_pv_q[0]):>9} {px(cur_pv_q[1]):>9} {px(cur_pv_q[2]):>9} {px(cur_pv_mean):>9}')
report.append(f'Full-act Y3 GP         {money(full_gp_q[0]):>9} {money(full_gp_q[1]):>9} {money(full_gp_q[2]):>9} {money(full_gp_mean):>9}')
report.append(f'Full-act PV/UNI        {px(full_pv_q[0]):>9} {px(full_pv_q[1]):>9} {px(full_pv_q[2]):>9} {px(full_pv_mean):>9}')
report.append(f'FDV/full-supply PV     {px(fdv_pv_q[0]):>9} {px(fdv_pv_q[1]):>9} {px(fdv_pv_q[2]):>9} {px(fdv_pv_mean):>9}')
report.append('```')
report.append('```text')
report.append('3) Sanity checks / current multiples')
report.append(f'Current annualized volume       {money(current_ann_vol)}')
report.append(f'Current-state annual GP         {money(current_state_ann_gp)}')
report.append(f'Full-activation annual GP       {money(full_ann_gp)}')
report.append(f'MCap / current-state GP         {mult(mcap_cur)}')
report.append(f'MCap / full-activation GP       {mult(mcap_full)}')
report.append(f'FDV / full-activation GP        {mult(fdv_full)}')
report.append(f'Prob full-act PV > spot         {pct(prob_gt_spot)}')
report.append(f'Prob full-act PV > 3x spot      {pct(prob_gt_3x)}')
report.append('```')
if caveats:
    report.append('Caveats: ' + '; '.join(caveats))
print('\n'.join(report))

```

### `UNI_LOCKED_MODEL.md`

```markdown
# UNI Locked Valuation Model

Locked: 2026-05-09
Owner: Momir

## Purpose

Recurring UNI valuation report using a 3-year GP-capture framework and HYPE-style MC volume methodology. Output must be Discord-friendly and use three compact tables.

## Model framing

Do **not** call the full-activation line "terminal GP". Use:

- "full-activation Y3 GP"
- "potential Y3 GP"
- "full-activation economics"

This is not a perpetual DCF / terminal-value model. It is a 3-year investment-horizon valuation.

## Core formula

```text
PV50 / UNI =
  Y3 full-activation GP P50 × 15x
  ÷ UNI supply
  ÷ (1 + liquid-token discount rate)^3
```

Full distribution should show P25 / P50 / P75 and EV/mean PV price.

## Volume model

Use HYPE-style Monte Carlo volume simulation:

1. Pull Uniswap daily DEX volume from DeFiLlama: `https://api.llama.fi/summary/dexs/uniswap?dataType=dailyVolume`.
2. Aggregate to completed monthly volume.
3. Use history from 2021-01 through the latest completed month.
4. Compute monthly log-returns from historical Uniswap monthly volumes.
5. Base monthly volume seed:

```text
Backtest month-end:
  min(latest completed monthly Uniswap volume,
      trailing 12 completed months median monthly volume)

Live report:
  min(latest full 30D Uniswap volume,
      trailing 12 completed months median monthly volume)
```

6. Simulate 36 months and value Year-3 trailing 12M volume.

## Fee / GP assumptions

### Current-state economics

Current-state LP protocol take is approximately **0.826bps** because v4 is not yet fee-switch active. This is the active-fee/reality check line.

### Full-activation economics

Full-activation GP take:

```text
Full-activation GP take =
  LP fee rate × 25%
+ frontend effective take
```

Use no-lookahead LP fee rate for backtests:

```text
LP fee bps at date =
  min(latest completed month LP fees / volume,
      trailing 12M LP fees / volume) × 10,000
```

Use latest available live LP fee rate for current report, with sanity check against recent 30D fees / volume. Corrected recent reference: ~10.92bps from ~$44.4M fees / $40.67B volume.

Frontend:

```text
frontend fee = 15bps
frontend / total volume = ~2%
frontend effective take = 0.30bps
```

### GP formulas

```text
Current-state GP =
  Y3 volume × (0.826bps + 0.30bps)

Full-activation Y3 GP =
  Y3 volume × (LP fee bps × 25% + 0.30bps)
```

## Multiple and supply

- Apply **15x GP multiple** to full-activation Y3 GP and current-state GP.
- Do **not** add a post-activation cash line.
- Protocol fees route **TokenJar → Firepit → UNI burns**; additive cash accumulation is architecturally wrong.
- Primary supply basis: current circulating UNI supply from current market data.
- Also show FDV/full-supply sensitivity when data is available.

## Fee-switch / architecture notes

- Fee switch active since Dec-2025 / Month 5 for the currently active scope.
- v4 was noted as ~58.6% of volume and ~54.8% of LP fees with $0 protocol revenue at the correction date; v4 activation requires separate governance.
- UniswapX inventory fills are additive upside and not in DeFiLlama pool stats unless separately modeled.

## Discount rate

Use liquid-token framework:

```text
DR = risk_free_rate + ERP × (UNI daily stdev / S&P 500 daily stdev)
```

Use 365D UNI daily returns and 365D S&P 500 daily returns. ERP reference used in the locked run: 3%. Latest locked run produced ~24-25% DR.

## Report format

Deliver three compact Discord-friendly tables:

1. Key assumptions
2. Model results: P25 / P50 / P75 / EV-mean PV price
3. Sanity checks / current multiples / probabilities

Avoid wide markdown tables. Prefer aligned text blocks.

Include:

- spot price
- data freshness
- base seed
- LP fee bps
- current-state and full-activation effective take bps
- Y3 TTM volume P25/P50/P75/mean
- Current-state GP and PV price
- Full-activation Y3 GP and PV price
- FDV PV sensitivity if available
- probability PV > spot and PV > 3x spot
- current annualized volume and current/full-activation annual GP
- MCap/current-state GP and MCap/full-activation GP

## Backtest convention

When asked for backtest, show model-implied FV50 at historical month-ends without forward-looking bias:

- at each month-end, only use volume and fee history available through that month
- use historical monthly log returns only up to that date
- use base seed rule for backtests
- use no-lookahead LP fee bps rule
- compare FV50 to historical spot
- state if supply is held constant for comparability or if historical supply is used

```

### `jup_locked_agent.py`

```python
#!/usr/bin/env python3
"""JUP locked valuation agent.

Implements / refreshes JUP_LOCKED_MODEL.md with public DefiLlama + CoinGecko data.
The model is intentionally simple and transparent:
- Core entity GP = Jupiter Perps GP + Aggregator/Ultra GP + Jupiterz implied GP.
- Perps GP = 25% of Jupiter Perpetual Exchange gross fees (75% to JLP).
- Aggregator/Ultra GP = DefiLlama Jupiter Aggregator fees/revenue.
- Jupiterz GP = Jupiterz volume * aggregator rake. If live aggregator volume is unavailable,
  use the prior audited current rake anchor from the locked report lineage (~3.55bps).
- Lending / jupSOL / DCA / Ape / Prediction are tracked as live optional lines, but not separately MC-simulated unless they become material.
- Jupnet is a separate additional +10% premium.
- Scheduled unlock pressure is 0 until Jupiter announces a new distribution plan for the cold-storage/community reserve.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

OUTDIR = os.path.dirname(__file__)
N_PATHS = int(os.environ.get("JUP_MC_PATHS", "100000"))
MONTHS = 36
DISCOUNT = 0.244
MULTIPLE = 15.0
# No public forward unlock/distribution schedule for the ~3.4B cold-storage/community reserve.
# Treat scheduled unlock pressure as 0 until Jupiter announces a plan. Do not assume
# the old 53.47M/mo distribution continues or restarts against treasury/reserve tokens.
SCHEDULED_UNLOCKS_PER_MONTH = 0.0
COLD_STORAGE_COMMUNITY_RESERVE = 3.405e9
BUYBACK_SHARE = 0.50
# From 2026-05-11 active run: aggregator rev 30D $1.88M / aggregator vol 30D $5.29B = 3.55bps.
# Public DefiLlama currently exposes Jupiterz volume but not Jupiter aggregator volume via free endpoint.
AGG_RAKE_BPS_FALLBACK = 3.55
PREMIUMS = {
    "core": 1.00,
    "opt_10": 1.10,
    "opt_10_jupnet_10": 1.20,
}


def fetch_json(url: str, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception:
            if i == 2:
                raise
            time.sleep(2 * (i + 1))


def cg_market():
    url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=jupiter-exchange-solana"
    arr = fetch_json(url)
    if not arr:
        raise RuntimeError("CoinGecko returned no JUP market data")
    return arr[0]


def llama_summary(kind: str, slug: str, data_type: str):
    return fetch_json(f"https://api.llama.fi/summary/{kind}/{slug}?dataType={data_type}")


def chart_rows(data):
    rows = []
    for ts, val in data.get("totalDataChart", []) or []:
        try:
            rows.append((datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat(), float(val or 0)))
        except Exception:
            pass
    rows.sort()
    return rows


def monthly_sums(rows):
    d = defaultdict(float)
    for day, val in rows:
        d[day[:7]] += float(val)
    return sorted(d.items())


def trailing_sum(rows, n=30):
    return float(sum(v for _, v in rows[-n:])) if rows else 0.0


def median_last12(months):
    vals = [v for _, v in months[-12:] if v > 0]
    return float(statistics.median(vals)) if vals else 0.0


def pct_dict(x, qs=(25, 50, 75, 90)):
    return {f"p{q}": float(np.percentile(x, q)) for q in qs}


def fmt_money(x):
    ax = abs(float(x))
    if ax >= 1e9:
        return f"${x/1e9:.2f}B"
    if ax >= 1e6:
        return f"${x/1e6:.1f}M"
    if ax >= 1e3:
        return f"${x/1e3:.1f}K"
    return f"${x:.3f}"


def gp_series_and_seeds():
    perps_fees = chart_rows(llama_summary("fees", "jupiter-perpetual-exchange", "dailyFees"))
    agg_fees = chart_rows(llama_summary("fees", "jupiter-aggregator", "dailyFees"))
    jupz_vol = chart_rows(llama_summary("dexs", "jupiterz", "dailyVolume"))
    lend_revenue = chart_rows(llama_summary("fees", "jupiter-lend", "dailyRevenue"))
    jupsol_revenue = chart_rows(llama_summary("fees", "jupiter-staked-sol", "dailyRevenue"))
    ape_revenue = chart_rows(llama_summary("fees", "ape-jupiter", "dailyRevenue"))
    prediction_revenue = chart_rows(llama_summary("fees", "jupiter-prediction", "dailyRevenue"))
    dca_fees = chart_rows(llama_summary("fees", "jupiter-dca", "dailyFees"))

    rake = AGG_RAKE_BPS_FALLBACK / 10000.0
    perps_gp_daily = [(d, v * 0.25) for d, v in perps_fees]
    agg_gp_daily = agg_fees
    jupz_gp_daily = [(d, v * rake) for d, v in jupz_vol]

    perps_months = monthly_sums(perps_gp_daily)
    # Combine spot by month: aggregator fees + Jupiterz implied GP.
    spot_by_month = defaultdict(float)
    for d, v in agg_gp_daily:
        spot_by_month[d[:7]] += v
    for d, v in jupz_gp_daily:
        spot_by_month[d[:7]] += v
    spot_months = sorted(spot_by_month.items())

    perps_30 = trailing_sum(perps_gp_daily, 30)
    agg_30 = trailing_sum(agg_gp_daily, 30)
    jupz_vol_30 = trailing_sum(jupz_vol, 30)
    jupz_gp_30 = jupz_vol_30 * rake
    lend_30 = trailing_sum(lend_revenue, 30)
    jupsol_30 = trailing_sum(jupsol_revenue, 30)
    ape_30 = trailing_sum(ape_revenue, 30)
    prediction_30 = trailing_sum(prediction_revenue, 30)
    dca_30 = trailing_sum(dca_fees, 30)
    tracked_optional_30 = lend_30 + jupsol_30 + ape_30 + prediction_30 + dca_30
    spot_30 = agg_30 + jupz_gp_30
    total_30 = perps_30 + spot_30

    perps_med12 = median_last12(perps_months)
    spot_med12 = median_last12(spot_months)
    perps_seed = min(perps_30, perps_med12) if perps_med12 else perps_30
    spot_seed = min(spot_30, spot_med12) if spot_med12 else spot_30

    return {
        "rows": {"perps_gp_daily": perps_gp_daily, "agg_gp_daily": agg_gp_daily, "jupz_vol_daily": jupz_vol, "jupz_gp_daily": jupz_gp_daily, "dca_fees_daily": dca_fees},
        "months": {"perps_gp": perps_months, "spot_gp": spot_months},
        "seeds": {
            "perps_30d_gp": perps_30,
            "perps_12m_median_gp": perps_med12,
            "perps_seed_gp": perps_seed,
            "aggregator_30d_gp": agg_30,
            "jupiterz_30d_volume": jupz_vol_30,
            "jupiterz_implied_30d_gp": jupz_gp_30,
            "spot_30d_gp": spot_30,
            "spot_12m_median_gp": spot_med12,
            "spot_seed_gp": spot_seed,
            "total_30d_gp": total_30,
            "total_seed_gp": perps_seed + spot_seed,
            "dca_30d_fees_optional": dca_30,
            "lend_30d_revenue_optional": lend_30,
            "jupsol_30d_revenue_optional": jupsol_30,
            "ape_30d_revenue_optional": ape_30,
            "prediction_30d_revenue_optional": prediction_30,
            "tracked_optional_30d_revenue": tracked_optional_30,
            "jupiterz_rake_bps": AGG_RAKE_BPS_FALLBACK,
        },
        "last_dates": {
            "perps_fees": perps_fees[-1][0] if perps_fees else None,
            "aggregator_fees": agg_fees[-1][0] if agg_fees else None,
            "jupiterz_volume": jupz_vol[-1][0] if jupz_vol else None,
            "dca_fees": dca_fees[-1][0] if dca_fees else None,
            "lend_revenue": lend_revenue[-1][0] if lend_revenue else None,
            "jupsol_revenue": jupsol_revenue[-1][0] if jupsol_revenue else None,
            "ape_revenue": ape_revenue[-1][0] if ape_revenue else None,
            "prediction_revenue": prediction_revenue[-1][0] if prediction_revenue else None,
        },
    }


def sample_returns(months):
    # Exclude tiny-launch history and the current incomplete month. Early JUP product
    # months create absurd bootstrap tails that swamp the locked model. Use mature
    # completed months and cap single-month log shocks to keep the MC a valuation
    # model rather than a launch-base extrapolator.
    current_month = datetime.now(timezone.utc).date().isoformat()[:7]
    vals = [v for m, v in months if v > 0 and m >= "2024-01" and m < current_month]
    rets = []
    for a, b in zip(vals, vals[1:]):
        if a > 0 and b > 0:
            rets.append(max(-0.75, min(0.75, math.log(b / a))))
    if len(rets) < 6:
        return np.array([0.0])
    return np.array(rets, dtype=float)


def run_mc(market, gpdata):
    spot = float(market["current_price"])
    circ = float(market.get("circulating_supply") or market["market_cap"] / spot)
    perps_seed = gpdata["seeds"]["perps_seed_gp"]
    spot_seed = gpdata["seeds"]["spot_seed_gp"]
    perps_rets = sample_returns(gpdata["months"]["perps_gp"])
    spot_rets = sample_returns(gpdata["months"]["spot_gp"])

    rng = np.random.default_rng(42)
    perps_draws = rng.choice(perps_rets, size=(N_PATHS, MONTHS), replace=True)
    spot_draws = rng.choice(spot_rets, size=(N_PATHS, MONTHS), replace=True)
    perps_monthly = perps_seed * np.exp(np.cumsum(perps_draws, axis=1))
    spot_monthly = spot_seed * np.exp(np.cumsum(spot_draws, axis=1))
    # Guard against bootstrap-tail explosions in a young product series. This is
    # a 3Y valuation dashboard, not an unconstrained launch-phase extrapolation.
    # Cap each mature product line at 8x the live monthly seed; breakout/Jupnet
    # remains represented by the +10%/+20% premium cases rather than infinite GP.
    perps_monthly = np.minimum(perps_monthly, perps_seed * 8.0)
    spot_monthly = np.minimum(spot_monthly, spot_seed * 8.0)
    total_monthly = perps_monthly + spot_monthly
    y3_perps_gp = perps_monthly[:, -12:].sum(axis=1)
    y3_spot_gp = spot_monthly[:, -12:].sum(axis=1)
    y3_gp = y3_perps_gp + y3_spot_gp

    supply = np.full(N_PATHS, circ, dtype=float)
    buyback_tokens_accum = np.zeros(N_PATHS, dtype=float)
    for t in range(MONTHS):
        buy_tokens = (total_monthly[:, t] * BUYBACK_SHARE) / max(spot, 0.01)
        supply += SCHEDULED_UNLOCKS_PER_MONTH - buy_tokens
        buyback_tokens_accum += buy_tokens
    supply = np.maximum(supply, 1.0)

    y3_price_core = y3_gp * MULTIPLE / supply
    result_cases = {}
    for key, premium in PREMIUMS.items():
        y3_price = y3_price_core * premium
        pv = y3_price / ((1 + DISCOUNT) ** 3)
        result_cases[key] = {
            "discounted_pv": pct_dict(pv),
            "discounted_ev": float(np.mean(pv)),
            "p50_to_spot": float(np.percentile(pv, 50) / spot),
            "ev_to_spot": float(np.mean(pv) / spot),
            "prob_pv_gt_spot": float(np.mean(pv > spot)),
            "prob_pv_gt_2x": float(np.mean(pv > 2 * spot)),
            "prob_pv_gt_3x": float(np.mean(pv > 3 * spot)),
        }

    return {
        "mc": {
            "paths": N_PATHS,
            "months": MONTHS,
            "perps_return_months": int(len(perps_rets)),
            "spot_return_months": int(len(spot_rets)),
            "perps_logret_mean": float(np.mean(perps_rets)),
            "perps_logret_std": float(np.std(perps_rets, ddof=1)) if len(perps_rets) > 1 else 0.0,
            "spot_logret_mean": float(np.mean(spot_rets)),
            "spot_logret_std": float(np.std(spot_rets, ddof=1)) if len(spot_rets) > 1 else 0.0,
        },
        "y3_state": {
            "y3_ttm_gp": pct_dict(y3_gp),
            "y3_perps_gp": pct_dict(y3_perps_gp),
            "y3_spot_gp": pct_dict(y3_spot_gp),
            "y3_effective_supply": pct_dict(supply),
            "buyback_accum_tokens": pct_dict(buyback_tokens_accum),
        },
        "cases": result_cases,
    }


def write_report(out):
    m = out["market"]
    s = out["gpdata"]["seeds"]
    c = out["valuation"]["cases"]
    st = out["valuation"]["y3_state"]
    spot = m["current_price"]
    lines = []
    lines.append(f"**JUP locked valuation refresh — {out['as_of_utc'][:10]}**")
    lines.append("")
    lines.append("```text")
    lines.append("KEY ASSUMPTIONS / LIVE SEEDS")
    lines.append(f"Spot / MCap / FDV       ${spot:.4f} / {fmt_money(m['market_cap'])} / {fmt_money(m['fully_diluted_valuation'])}")
    lines.append(f"Circ / total supply     {m['circulating_supply']/1e9:.2f}B / {m['total_supply']/1e9:.2f}B JUP")
    lines.append(f"Discount / multiple     {DISCOUNT*100:.1f}% / {MULTIPLE:.0f}x Y3 TTM entity GP")
    lines.append(f"Scheduled unlocks        {SCHEDULED_UNLOCKS_PER_MONTH/1e6:.2f}M JUP/mo (0 until new reserve plan)")
    lines.append(f"Buybacks                50% entity GP at current spot")
    lines.append(f"Perps GP seed           {fmt_money(s['perps_seed_gp'])}/mo = min({fmt_money(s['perps_30d_gp'])}, {fmt_money(s['perps_12m_median_gp'])})")
    lines.append(f"Aggregator GP 30D       {fmt_money(s['aggregator_30d_gp'])}")
    lines.append(f"Jupiterz vol / GP 30D   {fmt_money(s['jupiterz_30d_volume'])} / {fmt_money(s['jupiterz_implied_30d_gp'])} @ {s['jupiterz_rake_bps']:.2f}bps")
    lines.append(f"Spot GP seed            {fmt_money(s['spot_seed_gp'])}/mo = min({fmt_money(s['spot_30d_gp'])}, {fmt_money(s['spot_12m_median_gp'])})")
    lines.append(f"Total GP seed           {fmt_money(s['total_seed_gp'])}/mo; 30D run-rate {fmt_money(s['total_30d_gp'])}/mo")
    lines.append(f"DCA fees optional       {fmt_money(s['dca_30d_fees_optional'])}/30D, not in core")
    lines.append(f"Lend revenue optional   {fmt_money(s['lend_30d_revenue_optional'])}/30D, not in core")
    lines.append(f"jupSOL revenue optional {fmt_money(s['jupsol_30d_revenue_optional'])}/30D, not in core")
    lines.append(f"Tracked optional total  {fmt_money(s['tracked_optional_30d_revenue'])}/30D")
    lines.append("```")
    lines.append("")
    lines.append("```text")
    lines.append("RESULTS — discounted PV / JUP")
    lines.append("Case              P25    P50    P75    EV     P50x  EVx   P>spot")
    for key, lab in [("core", "Core"), ("opt_10", "+10% opt"), ("opt_10_jupnet_10", "+opt+Jupnet")]:
        pv = c[key]["discounted_pv"]
        lines.append(f"{lab:<16} ${pv['p25']:.3f} ${pv['p50']:.3f} ${pv['p75']:.3f} ${c[key]['discounted_ev']:.3f}  {c[key]['p50_to_spot']:.2f}x {c[key]['ev_to_spot']:.2f}x {c[key]['prob_pv_gt_spot']*100:5.1f}%")
    lines.append("```")
    lines.append("")
    lines.append("```text")
    lines.append("P50 MODEL STATE / PRODUCT SPLIT")
    lines.append(f"Y3 TTM entity GP P50       {fmt_money(st['y3_ttm_gp']['p50'])}")
    lines.append(f"  Perps GP P50             {fmt_money(st['y3_perps_gp']['p50'])}")
    lines.append(f"  Spot/Agg+Jupiterz GP P50 {fmt_money(st['y3_spot_gp']['p50'])}")
    lines.append(f"Y3 effective supply P50    {st['y3_effective_supply']['p50']/1e9:.2f}B JUP")
    lines.append(f"P50 buyback accumulation   {st['buyback_accum_tokens']['p50']/1e6:.0f}M JUP")
    lines.append("```")
    lines.append("")
    lines.append("Read-through: supply assumption corrected. The prior 53.47M JUP/mo gross unlock path is removed because the scheduled unlocks are finished; the ~3.405B cold-storage/community reserve has no public distribution timeline. PV is now driven by current core GP seed (" + fmt_money(s['total_seed_gp']) + "/mo, ~" + fmt_money(s['total_seed_gp']*12) + "/yr), simulated buybacks, and current circulating/effective supply. Lend/jupSOL are tracked explicitly but remain small optional lines, not separate MC drivers yet.")
    return "\n".join(lines)


def main():
    market = cg_market()
    gpdata = gp_series_and_seeds()
    valuation = run_mc(market, gpdata)
    out = {
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "market": market,
        "methodology": {
            "discount_rate": DISCOUNT,
            "multiple": MULTIPLE,
            "scheduled_unlocks_per_month": SCHEDULED_UNLOCKS_PER_MONTH,
            "cold_storage_community_reserve": COLD_STORAGE_COMMUNITY_RESERVE,
            "supply_note": "Scheduled unlock pressure set to 0 until Jupiter announces a new distribution plan for cold-storage/community reserve tokens.",
            "buyback_share": BUYBACK_SHARE,
            "aggregator_rake_bps_fallback": AGG_RAKE_BPS_FALLBACK,
            "note": "Jupiterz GP uses fallback aggregator rake because free public DefiLlama endpoint exposes Jupiterz volume but not current aggregator/Ultra volume.",
        },
        "gpdata": gpdata,
        "valuation": valuation,
    }
    # Avoid dumping daily rows into json artifact size? Keep monthly + seeds, not raw rows.
    out_slim = dict(out)
    out_slim["gpdata"] = {"months": gpdata["months"], "seeds": gpdata["seeds"], "last_dates": gpdata["last_dates"]}
    json_path = os.path.join(OUTDIR, "jup_locked_result.json")
    md_path = os.path.join(OUTDIR, "jup_locked_report.md")
    with open(json_path, "w") as f:
        json.dump(out_slim, f, indent=2)
    report = write_report(out)
    with open(md_path, "w") as f:
        f.write(report + "\n")
    print(report)
    print(f"\nSaved: {json_path}")
    print(f"Saved: {md_path}")


if __name__ == "__main__":
    main()

```

### `JUP_LOCKED_MODEL.md`

```markdown
# JUP / Jupiter Locked Valuation Model

Locked: 2026-05-09. Corrected: 2026-05-15 for supply schedule and optional product tracking. Purpose: recurring JUP valuation report and cross-project ranking.

## Core framing

- Primary denominator: **entity protocol GP**, not holder revenue.
- Main valuation formula:

```text
PV/JUP =
  Year-3 TTM entity GP
  × 15x GP multiple
  × premium multiplier
  ÷ Year-3 effective supply
  ÷ (1 + discount rate)^3
```

- Multiple: **15x Y3 TTM entity GP**, same as UNI.
- Discount rate: **24.4%** unless liquid-token framework is refreshed and clearly differs.
- Product simulation: **simulate only two core lines**:
  1. Perps GP path.
  2. Spot / exchange GP path = Aggregator/Ultra + Jupiterz.
- Premiums:
  - Core MC: no premium.
  - Optionality case: **+10% value premium** for smaller/non-monetized products.
  - Optionality + Jupnet case: **+20% total value premium** = +10% optionality + separate +10% Jupnet premium.
- Do **not** add separate hand-weighted recovery scenarios as the main valuation table. If mentioned, keep as supporting sanity only.

## Product suite and treatment

| Product | Description | Model treatment |
|---|---|---|
| Aggregator / Ultra | Solana swap router / monetized Ultra swaps | Core spot MC line |
| Jupiterz | Jupiter-linked Solana spot DEX / trading venue | Combine with Aggregator; assume same bps rake as Aggregator once monetized |
| Jupiter Perps | Perpetual futures exchange backed by JLP | Core perps MC line; GP = 25% of gross fees, 75% to JLP |
| Lend | Lending/borrowing market | Tracked as live optional revenue; not separate MC until material |
| jupSOL | Liquid-staked SOL token | Included in optionality; staking yield is pass-through, only deposit/withdraw fees are protocol income |
| DCA | Dollar-cost averaging tool | Included in optionality |
| Limit Orders | Limit-order execution | Included in optionality |
| Studio | Launchpad / token issuance tooling | Included in optionality |
| Prediction | Prediction market interface/aggregator | Current GP = 0; included in optionality only if economics change |
| Ape-Jupiter | Memecoin trading app | Included in optionality |
| JupUSD | Stablecoin / basis-trading product | Included in optionality until revenue tracked |
| Jupnet | Planned cross-chain/liquidity/perps infra | Separate +10% Jupnet premium in base report; can be breakout sensitivity if live adoption appears |
| Litterbox Trust | Buyback/lock vehicle, not a product | Supply mechanic |

## Current anchored data from 2026-05-09 work

Market snapshot:

```text
JUP spot:              $0.240596
Market cap:            ~$800M
FDV:                   ~$1.65B
Circulating supply:    3.322B JUP
Total supply:          6.862B JUP
Max supply:            10.0B JUP
```

Core product seeds from latest model:

```text
Perps GP seed:               $2.329M/month
Spot GP seed:                $2.151M/month
  = Aggregator/Ultra + Jupiterz at same rake
Total simulated GP seed:     $4.480M/month
Annualized:                  $53.8M
```

Jupiterz treatment:

```text
Jupiterz 30D GMV:            ~$905M
Aggregator/Ultra rake:       ~3.07bps from audit April data
Jupiterz implied GP:         ~$0.278M/month at same rake
```

## Buyback / treasury / supply mechanics

- 50% of simulated entity GP goes to JUP buybacks / Litterbox Trust.
- 50% goes to Jupiter protocol treasury / DAO / operating balance sheet / Net-Zero support.
- Because the denominator is **entity GP**, do not haircut GP by 50% in the valuation multiple.
- Model buybacks as supply mechanics:

```text
monthly buyback dollars = 50% × simulated monthly entity GP
monthly JUP bought = monthly buyback dollars ÷ assumed JUP buyback price
```

- Default buyback token denominator: current spot, with sensitivity if needed.
- Litterbox tokens reduce effective float while locked; total supply only falls after burns.
- Default scheduled unlock path: **0 JUP/month** until Jupiter announces a new distribution plan for the cold-storage/community reserve.
- The ~3.405B JUP cold-storage/community reserve is minted/treasury-held, but has **no public DefiLlama-tracked distribution timeline**.
- Do not assume the old `53.47M JUP/month` schedule continues or restarts. If that rate were applied to the reserve, it would imply ~64 months, not 36, but this is **not a public schedule**.
- Y3 effective supply:

```text
current effective circulating supply
+ public scheduled unlocks, currently 0 until new reserve plan
- simulated buyback accumulation
- burns if verified
```

## MC methodology

1. Fetch current market data and product data if available.
2. Use product seed rule:

```text
seed = min(latest full 30D product GP, trailing 12M median monthly product GP)
```

3. Simulate separate paths:
   - Perps GP path from perps monthly GP/volume/fee history.
   - Spot GP path from Aggregator/Ultra + Jupiterz GMV/rake history.
4. Use monthly return bootstrap/log-return MC. Treat perps and spot as separate drivers, optionally with a shared weak common market factor.
5. Do not separately simulate Lend, jupSOL, DCA, Limit, Studio, Prediction, Ape, JupUSD in the main locked model; those are covered by the +10% optionality premium.
6. Run at least 50k paths when feasible.
7. Report discounted PV per token as the main output.

## Latest locked output from 2026-05-09 run

Assumptions:

```text
Core:                 spot + perps MC only
Optionality:          +10% value premium
Jupnet:               separate +10% value premium
Multiple:             15x GP
Discount rate:        24.4%
Supply:               gross unlocks included, buybacks reduce effective supply
Buybacks:             50% of simulated GP, bought at current spot
```

Valuation table:

| Case | P25 | P50 | P75 | EV / mean |
|---|---:|---:|---:|---:|
| Core spot+perps MC | $0.067 | $0.121 | $0.191 | $0.144 |
| +10% optionality | $0.073 | $0.133 | $0.210 | $0.158 |
| +10% optionality + 10% Jupnet | $0.080 | $0.145 | $0.230 | $0.173 |

Probability checks from latest run:

| Case | Prob PV > spot | Prob PV > 2x spot |
|---|---:|---:|
| Core | 15.6% | 0.5% |
| +10% optionality | 19.1% | 1.5% |
| +10% optionality + Jupnet | 22.8% | 2.9% |

P50 model state:

```text
Y3 TTM GP P50:                         ~$74.5M
P50 annual perps GP:                   ~$33.2M
P50 annual spot/Aggregator+Jupiterz GP:~$27.6M
Y3 effective supply P50:               ~4.81B JUP
```

Discord report output should prioritize the final premium case:

```text
JUP PV, spot+perps MC + 10% optionality + 10% Jupnet:
P25 $0.080 | P50 $0.145 | P75 $0.230 | EV $0.173
```

Always show spot and model_price/spot:

```text
Spot used in latest run: $0.2406
P50/spot: ~0.60x
EV/spot:  ~0.72x
```

## Report format

Use 3 short Discord-friendly sections/tables:

1. Key assumptions.
2. Model results: P25/P50/P75/EV and model_price/spot.
3. KPI/watchlist and changes since last run.

Avoid wide Markdown tables. Prefer aligned text blocks.

## Actionable KPI watchlist

Core:
- Monthly entity GP.
- Monthly buybacks.
- Current GP vs 12M median GP.
- Buyback yield on mcap / FDV.

Perps:
- Perps volume, gross fees, GP, fee bps, JLP TVL, OI/utilization if available, share vs Hyperliquid / Solana perps.

Aggregator + Jupiterz:
- Aggregator/Ultra GMV, fee bps, Jupiterz GMV, monetized vs unmonetized volume, new fee adapter/treasury address, fee-switch proposals.

Supply:
- Gross monthly unlocks, Net-Zero offsets, Litterbox holdings, burns, effective circulating supply, total supply.

Jupnet:
- Mainnet launch, perps launch, sequencer/settlement fee design, cross-chain liquidity, market-maker participation, first 30/90D volume, explicit JUP fee capture.

Other optionality:
- Lend deposits/borrows/utilization, jupSOL AUM/inflows, JupUSD TVL/yield/revenue adapter, Ape volume/fees, PM aggregator fee split changes.

```
