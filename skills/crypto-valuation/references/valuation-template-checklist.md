# Valuation Template Checklist

Use this checklist before publishing any valuation model, dashboard update, or GitHub PR. Do not skip it for “quick” updates.

## 1. Data And Definitions

- Identify the protocol’s economic product lines.
- Choose the correct primary driver per line: volume, GMV, TVL, supply, float, market share, or take rate.
- Verify source semantics before modeling:
  - Fees vs protocol revenue vs holders revenue.
  - Gross revenue vs gross profit vs net profit.
  - TVL/supply as stock, not flow.
  - Builder/front-end fees, incentives, and pass-through costs.
- Reconcile current price, market cap, FDV, circulating supply, and relevant token supply schedule.

## 2. Growth Velocity

- Build a growth velocity input for the key growth line whenever possible.
- Prefer:

```text
starting_velocity = 70% × 30D/180D monthly-equivalent velocity
                  + 30% × 7D/30D monthly-equivalent velocity
```

- Show both component velocities and caps.
- Preserve raw 30D MoM and short-window data for auditability.
- If historical market data is not healthy, use 20/40/40 fallback scenarios:
  - Bear: same starting velocity, linear decay to 0% by M6.
  - Base: same starting velocity, linear decay to 0% by M12.
  - Bull: same starting velocity, linear decay to 0% by M24.
- Do not give bull a higher starting velocity unless the user explicitly asks.

## 3. Monte Carlo Method

- Prefer MC draws from 2022-present where enough data exists.
- Use protocol-specific historical observations or a defensible market denominator.
- Focus on End-of-Year-3 outcomes.
- Randomly draw the compounding base as well when anchoring only to today would overfit a noisy current level.
- If MC data is too thin or regime-broken, disclose it and use the fallback scenario method.
- If the selected primary driver changes, rebuild the historical diagnostic/backtest from that same selected driver. Do not leave an old backtest from a prior driver or sensitivity in the dashboard.

## 4. Value Capture And Supply

- Model only the cash line that reaches token holders, treasury, buybacks, burns, or verified token value capture.
- If no burn exists, add net profit as treasury cash rather than reducing supply.
- Model fixed unlocks/emissions per path when known.
- Use effective Year-3 supply for PV/token and buyback-year calculations.
- Explain when max supply is only a sensitivity rather than a primary denominator.

## 5. Required Outputs

Each model should produce:

- P25/P50/P75/P90 PV per token and EV.
- Probability above current spot.
- Probability of undiscounted token price being at least 30% higher after 2 years.
- Probability of undiscounted token price being at least 30% lower after 2 years.
- Probability of 3x only when meaningful; label it as a right-tail metric when P50 is near spot or when EV is driven by a fat-tailed distribution.
- End-of-Year-3 aggregate revenue or gross profit.
- End-of-Year-3 revenue or gross profit by product line.
- End-of-Year-3 effective token supply.
- End-of-Year-3 daily mean volume or daily mean TVL/supply, depending on the core driver.
- Current baseline values that match every displayed Year-3 metric, plus percent change vs current. Use current annualized GP/revenue for Y3 annual GP/revenue, current daily volume for Y3 daily volume, current TVL/supply for Y3 TVL/supply, and current circulating/effective supply for Y3 effective supply.
- Current annualized revenue/GP, take rate, P/S and P/GP where relevant.

## 6. Dashboard Requirements

- Highlight P50 PV distinctly.
- Show discount rate, multiple, take rate, supply, and velocity assumptions near the top. If take rate has multiple components, show each component and the combined take rate.
- Show stable-yield or new-business optionality as separate lines unless already proven current revenue.
- If optionality is requested as part of displayed price estimates, apply it consistently to every scenario price and label it.
- In every price distribution chart, draw and label a horizontal line at current spot price.
- Include a Y3 sanity block with aggregate GP/revenue, product-line split, supply, and daily mean volume/TVL.
- Include a historical diagnostic/backtest for the selected primary model when enough historical data exists. Name it explicitly if it is only a proxy, and do not show a sensitivity backtest as if it were the selected model.
- Keep incumbent dashboard standards intact; do not degrade existing HYPE or other tabs while adding a new model.

## 7. Pre-Publish Audit

- Compare the model against the incumbent template token by token.
- Check for circular valuation anchors, gross-fee/revenue confusion, missing supply dilution, and missing token-capture logic.
- Ensure the JSON artifact, aggregate valuation file, dashboard UI, static/deployed page, and historical backtest use the same primary scenario convention.
- Confirm the displayed 3x/upside metrics cannot be mistaken for the base case when P50 is close to spot.
- Run the build/test command and browser-smoke-test the changed tab when practical.
- In the final response or PR, list data sources, key assumptions, verification commands, and caveats.
