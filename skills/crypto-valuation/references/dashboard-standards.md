# Dashboard Standards Reference

## Reporting Checklist

Every token tab should expose comparable assumptions:

- Spot, market cap, circulating supply, FDV/max supply.
- P50 PV highlighted clearly.
- Take rate assumption in a top-line or assumption card.
- Discount rate and multiple visible without digging.
- Core revenue driver and market-share/volume driver.
- Growth velocity construction, including 30D/180D and 7D/30D components when used.
- Current annualized revenue or GP.
- Stable-yield sensitivity if relevant.
- Optionality case if requested, applied on top of the correct base.
- Token supply path, unlocks, buybacks/burns, effective Year-3 supply.
- Buyback years, preferably supply-adjusted.
- P/S and P/GP when both revenue and GP are meaningful.
- Scenario table with P25/P50/P75/P90, EV, P(spot), P(3x) when available.
- Two-year path probabilities: undiscounted probability of spot increasing 30% and decreasing 30%.
- Year-3 sanity metrics: aggregate GP/revenue, GP/revenue by product line, token supply, and daily mean volume or daily mean TVL.
- Year-3 cards and report rows should include `% change vs current` in the subtitle or adjacent row. Match the denominator to the metric: Y3 annual GP/revenue vs current annualized GP/revenue, Y3 daily volume vs current daily volume, Y3 TVL/supply vs current TVL/supply, and Y3 effective token supply vs current circulating/effective supply. Use negative percentages for modeled supply reductions from buybacks/burns. Display the current baseline or make it available in the adjacent assumption/detail table.
- **Market-implied growth rate**: invert the valuation formula to show what Y3 GP/revenue the current spot price implies, how far that sits from the model's base P50, and (where a current run-rate exists) the required 3-year CAGR. Show as a MetricCard on every token. For high-multiple or stock-like tokens, also show a dedicated panel with implied Y3 GP, model P50, % premium/discount, and implied CAGR. See `model-methodology.md` for the formula.
- Historical diagnostic/backtest chart for the selected primary model when enough data exists.
- Caveats that distinguish observed data from sensitivities.

When a dashboard includes multiple model families or sensitivities, the primary scenario must be unambiguous. Top cards, methodology copy, model-output tables, distribution charts, backtests, and deployed/static pages must all point to the same primary scenario. If a chart is for a sensitivity or proxy, label it as such.

## HYPE Baseline Standard

When matching another token to HYPE reporting, include:

- Market share trend section.
- Current snapshot table.
- Core revenue drivers explanation.
- Model and assumptions accordion.
- Model outputs cards.
- Scenario comparison table.
- PV distribution chart.
- Historical charts when available.

For every price distribution chart, draw a visible horizontal line at current spot price. Label it with the spot price. This applies even when the current spot sits above most of the PV distribution.

If displaying `P(3x)` or another large upside probability while P50 is near spot, label it as a right-tail metric. Do not present tail probability cards as if they were the central case.

Do not degrade the HYPE dashboard while adding another token. If using HYPE as template, copy standards conceptually, not by replacing existing HYPE data or UI.

## Lighter-Specific Cards

Useful Lighter top-line cards:

- Holder revenue annualized.
- MS90 valuation seed.
- MS30 / MS180 trend and model momentum floor.
- P50 fair value.
- P(above spot).
- Revenue take-rate in bps.
- Supply-adjusted buyback years with and without yield.

Useful Year-3 cards:

- Y3 revenue P50.
- Y3 monthly or annual volume P50.
- Buyback tokens P50.
- Effective supply P50.
- `% change vs current` for each Y3 revenue, volume, TVL, and supply card.

## Year-3 Sanity Metrics

Every dashboard should include a compact sanity block with:

- End-of-Year-3 aggregate gross profit or revenue.
- End-of-Year-3 gross profit or revenue by product line.
- End-of-Year-3 token supply or effective supply.
- End-of-Year-3 daily mean volume for volume-driven protocols, or daily mean TVL / supply for balance-sheet-driven protocols.
- The percentage change of each Year-3 metric versus the matching current metric.
- Undiscounted probability of spot price being up at least 30% and down at least 30% over the next 2 years from MC paths.

Do not make users infer product-line contribution from only volume/TVL. If staking, card, perps, vaults, stablecoin yield, or front-end fees are modeled separately, show the P50 contribution separately.

Do not compute current-delta percentages from mismatched baselines. If the current baseline is unavailable or stale, show `n/a` and add a caveat rather than deriving a misleading delta.

## JSON Integration Pattern

Typical repo pattern:

```text
data/valuations.json
crypto_valuation_agents_bundle/webapp/results/<token>_result.json
components/ValuationDashboard.tsx
lib/loadValuations.ts
```

Keep aggregate `data/valuations.json` formatting focused. Avoid reserializing the whole file if it creates massive numeric-format churn. Insert only the new token block when possible.

## Frontend Verification

After edits:

1. Run the project build command, usually `npm run build`.
2. Start a local server if needed.
3. Open `/valuation`.
4. Select the changed token tab.
5. Confirm token-specific strings and cards render.
6. Confirm the primary scenario label, take-rate assumptions, and selected-model backtest are visible.
7. Check no obvious chart or table layout overflow.

## Git Workflow

Use a focused branch:

```text
codex/add-<token>-valuation-model
codex/update-valuation-skill
```

Commit only relevant files. Leave unrelated untracked dashboards and local artifacts alone. If opening a PR, include:

- Summary of model/data/UI changes.
- Important assumptions and data sources.
- Verification commands and browser smoke test result.
- Caveats, especially any sensitivity or approximated distribution.
