---
name: crypto-valuation
description: Build, audit, update, or publish crypto token valuation models and growth dashboards. Use when the user asks for token PV/P50 valuation, HYPE-style or Lighter-style model replication, DefiLlama revenue/volume/TVL checks, protocol take-rate analysis, supply unlock/buyback modeling, stablecoin-yield sensitivities, market-share based Monte Carlo models, valuation scenario tables, or adding/updating valuation dashboards in a repo.
---

# Crypto Valuation

## Core Rule

Treat valuation work as a reproducible model, not a narrative estimate. Preserve the existing dashboard/model unless explicitly asked to replace it. When adding a new token, first read the incumbent reporting standard, turn it into a checklist when needed, then make the new model match that standard.

## Workflow

1. **Clarify the asset and deliverable.**
   Determine whether the user wants analysis only, a local model, a dashboard update, a GitHub PR, or a deployed site. If the target repo or source data is ambiguous, ask before editing.

2. **Inventory the existing model.**
   Read local files first: model scripts, output JSON, dashboard components, valuation data, and prior checklists. Use `rg` and avoid touching unrelated dashboards or untracked work.

3. **Fetch and verify data.**
   Prefer DefiLlama MCP/tools when available; otherwise use authenticated/API endpoints the user provides. Verify metric semantics before modeling:
   - `dailyFees` can include user-paid or third-party builder fees.
   - `dailyRevenue` should represent protocol/treasury revenue.
   - `holdersRevenue` is the cash line available to token holders or buybacks when supported.
   - TVL/yield lines are separate from fees unless the source explicitly includes them.

4. **Choose the model family.**
   Use protocol-specific economics instead of a generic bear/base/bull DCF when real drivers exist. For perps exchanges, prefer a market-share model against an external denominator such as Binance Futures. For apps with scarce history, keep scenario language explicit and mark sensitivities.

5. **Model supply and value capture.**
   Always account for circulating supply, max/FDV, fixed unlocks, emissions, buybacks/burns, and whether buyback cash actually reaches token holders. Use Year-3 effective supply for PV-per-token.

6. **Run or update Monte Carlo outputs.**
   Prefer historical MC draws from 2022-present when the market data is healthy. Focus on Year-3 outputs. Use growth velocity when modeling forward growth, preferably a 70/30 ensemble of 30D/180D and 7D/30D velocity. Output P25/P50/P75/P90, EV, probability above spot, probability of spot increasing or decreasing 30% within the next 2 years from undiscounted MC paths, Year-3 revenue/GP, supply, buybacks, and distribution ladders. For every Year-3 product-line card or report row, include the current baseline and percentage change versus the matching current data point, such as Y3 GP vs current annualized GP, Y3 daily volume vs current daily volume, and Y3 effective supply vs current circulating/effective supply. If a source run only exports quartiles, say when any distribution/P90 is approximated.

   **Also compute and display the market-implied Y3 GP/revenue growth rate.** Invert the valuation formula using the current spot price to find the Y3 GP or revenue the market is pricing in. Compare this to the model's base P50 Y3 GP/revenue (expressed as a % premium/discount) and, where a current run-rate is available, express it as a 3-year implied CAGR. Store as `implied_y3_gp`, `implied_vs_model` (%), and `implied_cagr` in `current_gp`. Always show this metric on the dashboard alongside the model P50 so the model's assumptions and the market's embedded expectations are directly comparable. See `references/model-methodology.md` for the formula.

7. **Audit assumptions before publishing.**
   Load `references/valuation-template-checklist.md` and complete it mentally before publishing. Compare new token reporting to the incumbent template. Call out take rate, discount rate, multiple, growth-velocity construction, volume/market-share/TVL driver, current revenue/GP, yield optionality, buyback years, supply path, Year-3 sanity metrics, and caveats. If the primary model driver changes, re-run the audit from the primary scenario down: scenario flags, dashboard copy, top cards, output table, distribution, and historical backtest must all refer to the same selected model.

8. **Update dashboard artifacts.**
   Keep data and UI aligned. Add standalone result JSON if the repo uses per-token outputs, then update aggregate valuation JSON and the dashboard component/cards. The dashboard must expose take-rate assumptions and show the selected-model historical diagnostic/backtest when enough data exists. Do not overwrite existing HYPE/other token methodology unless requested.

9. **Verify and ship.**
   Run the app’s build/test command. Browser-smoke-test the changed dashboard tab when practical. If the user wants GitHub changes, commit on a `codex/` branch, push, and open a PR with data sources and verification.

## Reference Loading

Read only the reference needed for the task:

- `references/model-methodology.md` for HYPE/Lighter-style MC methodology, supply/buyback mechanics, stable-yield sensitivities, and when to avoid generic DCF.
- `references/data-validation.md` for DefiLlama/CoinGecko/Otter/Notion data checks and common revenue metric traps.
- `references/dashboard-standards.md` for valuation dashboard reporting standards, cards, charts, assumptions tables, and GitHub update workflow.
- `references/valuation-template-checklist.md` for the mandatory pre-publish checklist that prevents shortcut models and obvious reporting mistakes.

## Defaults From Prior Work

- Horizon: 36 months / 3 years unless the user asks otherwise.
- Multiple: 15x normal case for derivatives exchange GP/revenue unless the incumbent model has a stronger regime schedule.
- Discount rate: preserve incumbent model rate; if starting fresh, justify rate explicitly and consider higher rates for less proven protocols.
- Primary output: P50 present value per token, not bear/base/bull labels, when using MC.
- Optionality: apply explicit optionality premiums on top of the relevant base case, e.g. `PV + stablecoin yield` then `× 1.10`, not on the no-yield base.
- Growth velocity: prefer a 70/30 ensemble of 30D/180D and 7D/30D velocity. If healthy market data is unavailable, use bear/base/bull 20/40/40 with identical starting velocity and linear decay to zero by M6/M12/M24 respectively unless the user specifies a different terminal.
- Stablecoin yield: treat as a sensitivity unless currently proven protocol revenue.
- Buyback years: compute on the correct supply-adjusted market cap if unlocks materially increase supply.

## What To Avoid

- Do not use current crypto multiples as circular anchors without TradFi or protocol-economic justification.
- Do not treat gross fees as treasury revenue when adapters include builder/front-end fees.
- Do not hide supply dilution behind current circulating supply.
- Do not call a copied methodology “replicated” unless volume driver, market-share trend, take rate, discount rate, multiple, supply schedule, buyback mechanics, and dashboard reporting standard are all aligned or deviations are explicit.
