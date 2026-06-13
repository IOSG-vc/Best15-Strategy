# Standard Vercel Reporting Template

Use this as the default structure for any model/research dashboard deployed as a static Vercel page.

## 1. Top-line summary

- Project / asset / strategy name
- One-sentence conclusion
- Current date / data timestamp
- Current market snapshot where relevant:
  - price
  - market cap / TVL / AUM
  - circulating supply / units outstanding
  - key live operating metric
- Main model output:
  - selected-model P50
  - probability-weighted EV / mean
  - current price vs model output

## 2. Data integrity block

- Primary data sources and timestamps
- Fallback data sources, if any
- Explicit source reconciliation when metrics can differ
- Clear distinction between:
  - observed data
  - model-implied data
  - forecast/simulated data
- API/credential note: never embed secrets, keys, tokens, or raw credentials

## 3. Model assumptions

Show concise formulas and locked assumptions.

Recommended structure:

```text
Revenue / cash-flow formula
Growth / share / adoption formula
Supply / dilution / unit-count formula
Discounting / multiple / valuation formula
```

Requirements:
- Keep assumptions auditable
- Avoid hidden scenario logic
- Use selected-model terminology unless explicit scenarios are requested
- Do not mix observed run-rate metrics with model-implied forecasts without labeling them

## 4. Current data table

Include only metrics that are directly useful for interpreting the model.

Preferred rows:
- key adoption/share metric
- short-window and long-window trend metric
- observed revenue/cash-flow metrics
- buyback/payback/horizon metrics where relevant
- supply/unit-count target used in those horizon metrics

Avoid:
- duplicate metrics that imply different definitions
- unlabeled modeled run-rates beside observed revenue
- theoretical FDV/full-supply metrics unless explicitly requested

## 5. Model outputs

Use a single selected-model output table by default.

Required columns:
- case / selected model
- P50 output
- P50 market/value equivalent
- discounted PV, if applicable
- probability-weighted EV / mean
- probability current price is justified, if applicable

Only add Bear/Base/Bull or scenario rows if explicitly requested.

## 6. Distribution visual

Prefer visual distribution over a raw wide table.

Recommended:
- percentile ladder: P5/P10/P20/P25/P30/P40/P50/P60/P70/P75/P80/P90/P95
- highlight P50 separately
- show EV/mean marker separately
- avoid visuals that confuse price magnitude with probability mass

## 7. Historical diagnostic / backtest

If including a historical visual:
- It must use the same model mechanics where historical inputs exist
- Label it clearly as diagnostic unless it is a full replay backtest
- Avoid detached run-rate charts unless clearly labeled
- Normalize model-shaped proxy lines so the latest point matches the locked current model output
- Show whether recent points are scored or unscored due to missing forward returns
- Include caveats on unavailable historical inputs

## 8. Sensitivities and risks

Default: keep the dashboard simple.

Include sensitivities only when they answer an active question.

Good sensitivities:
- one assumption changed at a time
- clearly labeled as sensitivity, not selected model
- removed once the selected model is locked, unless user wants them retained

## 9. Narrative notes

Every dashboard should include short notes answering:
- what changed?
- why does the model say this?
- what assumption matters most?
- what would make the model wrong?

Keep notes concise and conclusion-first.

## 10. Verification before deploy

Before reporting done:
- regenerate static page
- open locally in browser
- check browser console errors
- verify key strings/numbers in generated HTML
- deploy to Vercel production
- fetch production URL and verify updated strings

## 11. Recommended page order

1. Hero summary + top KPIs
2. Current data / source integrity
3. Model assumptions
4. Model outputs
5. Distribution visual
6. Historical diagnostic / backtest
7. Payback/buyback/horizon chart where relevant
8. Key risks / caveats
9. Source/deployment footer

## 12. Style rules

- Minimal black/white/blue visual language unless project requires otherwise
- Use cards for top KPIs
- Use tables only for compact exact numbers
- Use SVG charts for distributions and historical diagnostics
- Avoid cluttered sensitivity overlays after a model decision is locked
- Always label P50 vs EV/mean clearly
