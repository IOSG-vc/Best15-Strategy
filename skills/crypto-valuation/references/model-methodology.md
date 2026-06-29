# Model Methodology Reference

## Preferred Model Families

Use protocol-specific cash-flow drivers first.

| Protocol shape | Preferred driver | Value capture |
| --- | --- | --- |
| Perps exchange | External market volume proxy × protocol market share × net take rate | Protocol revenue, holder revenue, buybacks |
| Spot DEX | Total DEX volume × market share × protocol fee share | Fee-switch GP, front-end revenue if owned |
| Stablecoin/CDP | Stablecoin supply or collateral × net spread/yield − incentives/opex | Gross profit or surplus |
| Liquid staking/restaking | TVL × staking/restaking yield × protocol take | Net GP after costs |
| Wallet/payment/on-ramp | GMV × take rate; segment by new product line when take rate shifts | Revenue/GP; watch mix shift |

Use generic TAM → market share → take rate → Year-3 exit value only as a fallback when protocol-level data is missing.

## Growth Velocity Standard

Every project should use a growth velocity input unless the model is explicitly static. Prefer a stabilized ensemble:

```text
velocity_30_180 = monthly_equivalent_growth(avg_30d_metric, avg_180d_metric, midpoint_gap_days≈75)
velocity_7_30   = monthly_equivalent_growth(avg_7d_metric, avg_30d_metric, midpoint_gap_days≈11.5)
starting_velocity = 70% × capped(velocity_30_180) + 30% × capped(velocity_7_30)
```

Metric choice depends on the protocol:

- Perps/DEX/payment/on-ramp: volume, GMV, or market-share velocity.
- Stablecoin/CDP/lending/staking: TVL, supply, deposits, or market-share velocity.
- Multi-product protocols: compute velocity for the key alpha line, then show mature lines separately.

Use caps to prevent a short data window from dominating the model. A common default is `-5%` to `+12%` monthly unless the incumbent model justifies a different range. Preserve raw 30D MoM and raw 7D/30D values for auditability.

When healthy market data is not available, use a 20/40/40 bear/base/bull fallback:

```text
Bear weight 20%: starting_velocity linearly decays to 0% by end of M6.
Base weight 40%: starting_velocity linearly decays to 0% by end of M12.
Bull weight 40%: starting_velocity linearly decays to 0% by end of M24.
```

All three fallback scenarios must start from the same starting velocity. Decay must be linear. Do not make bull start higher unless the user explicitly asks.

## Historical MC Draws

When possible, draw MC paths from the historical period 2022-present:

- Use protocol-specific daily/monthly observations or a defensible external denominator.
- Focus the report on End-of-Year-3 values, not only PV.
- Base-to-compound-on can be randomly drawn from the same historical distribution when it is more robust than anchoring only to today.
- Use today’s data as the live snapshot, but do not overfit the valuation to a single noisy current base.
- If 2022-present data is structurally missing or regime-broken, disclose the shorter window and why.

## HYPE-Style Perps MC

Core structure:

```text
monthly_volume = external_denominator_volume × protocol_market_share
monthly_revenue_or_gp = monthly_volume × clean_take_rate
year_3_value = year_3_ttm_gp_or_revenue × exit_multiple
pv_per_token = year_3_value / effective_y3_supply / (1 + discount_rate)^3
```

Required assumptions:

- External denominator: Binance Futures proxy or other defensible market denominator.
- Starting share: usually MS90, not a hand-picked latest spike.
- Momentum: MS30/MS90 or MS30/MS180; decay momentum rather than extrapolating indefinitely.
- Absolute share cap: explicit cap when protocol share can otherwise explode.
- Take rate: use clean protocol/treasury revenue, not gross fees if adapter includes third-party fees.
- Multiple regime: e.g. 20x trough / 15x normal / 10x peak by volume path percentile.
- Supply path: fixed unlock/emission schedule per path.
- Buybacks: apply only the cash line actually available for token buybacks or burns.

## Lighter Replication Checklist

When replicating HYPE to Lighter or another perps venue, align these before calling it a replica:

- Perps volume driver: denominator-volume × protocol market share, not raw protocol volume alone.
- Starting input: MS90 or equivalent denominator share, not only 30D protocol volume.
- Market-share trend: MS30/MS90/MS180 with the same momentum/decay logic or a clearly stated deviation.
- Take rate: observed net protocol/holder revenue divided by paid volume.
- Holder capture: model `holdersRevenue` separately if buybacks are funded from holder revenue.
- Supply: include fixed unlock schedule and apply buybacks against Year-3 supply.
- Stable-yield sensitivity: separate optional case, not current revenue unless proven.

## Stablecoin Yield Sensitivity

Use only when defensible:

```text
yield_run_rate = TVL_or_stable_float × net_yield × protocol_capture
```

Default inherited sensitivity from prior HYPE/Lighter work:

- SOFR or equivalent base yield
- Haircut for operating/friction cost
- 90% capture if no better source exists
- TVL-to-volume elasticity only when the model has evidence or incumbent precedent

Always label this as sensitivity/optional future business unless the protocol already earns it.

## Supply And Buyback Years

Use the correct denominator:

```text
supply_adjusted_market_cap = spot × effective_y3_supply
buyback_years_fee_only = supply_adjusted_market_cap / annual_holder_revenue
buyback_years_with_yield = supply_adjusted_market_cap / (annual_holder_revenue + annual_yield_cash)
```

If unlocks materially increase supply, do not compute buyback years on current market cap only.

## Market-Implied Growth Rate

After computing the forward model, always invert the valuation formula to quantify what Y3 GP or revenue the current market price implies, and how far that sits from the model's own projection.

### Formula

```text
implied_y3_gp = spot × y3_supply_p50 × (1 + DR)^3 / base_multiple
```

- `spot`: current market price per token or per share.
- `y3_supply_p50`: Year-3 diluted token supply or share count from the base (primary) scenario.
- `DR`: CAPM or model discount rate.
- `base_multiple`: exit GP multiple for crypto GP models (`model.multiple`); exit P/S center for stock-like P/S models (primary scenario `ps_center`).

### Derived fields

| Field | Definition |
| --- | --- |
| `implied_y3_gp` | Dollar Y3 GP/revenue the current spot implies at `base_multiple` and `DR`. |
| `implied_vs_model` | `(implied_y3_gp / model_y3_gp_p50 − 1) × 100`. Positive = market prices in more growth than model P50; negative = market is below model fair value. |
| `implied_cagr` | `(implied_y3_gp / current_ann_gp)^(1/3) − 1`. Requires `current_ann_gp` from `current_gp` (try `total_revenue_ann`, `gross_profit_ann`, `revenue_ann`, `defillama_30d_ann` in that order). Omit if no current run-rate is available; do not synthesize a baseline. |
| `implied_multiple` | The `base_multiple` value used, for auditability. |

### Interpretation

- `implied_vs_model` tells how much more (or less) growth the market embeds versus the model's base case.
- `implied_cagr` converts this into an annualized revenue/GP growth rate, making it comparable to analyst consensus or management guidance.
- When `implied_vs_model` is large and positive (e.g. >100%), state explicitly that the current price requires growth well beyond the base scenario — this is a stretched-multiple or high-conviction growth bet, not a mispricing.
- When `implied_vs_model` is negative, the model fair value exceeds spot; the market is pricing in lower growth than the base case projects.

### Storage

Store all four fields under `current_gp` in the agent result JSON and in the aggregate `data/valuations.json`. Compute them in `scripts/update_valuations.py` as a post-processing step so the values are available for any downstream use (APIs, reports, alternative frontends) without re-running the full MC.

### Display

- Dashboard: show `implied_y3_gp` with `implied_vs_model` and `implied_cagr` as a MetricCard for every token.
- For detailed model sections (stock-like or high-multiple tokens), add a dedicated amber "Market-Implied Growth Rate" panel with a 4-box breakdown: implied Y3 GP/revenue, model base P50, implied vs model %, and implied CAGR.
- Color the card accent: green when `implied_vs_model ≤ 0` (market below model), yellow when `0 < implied_vs_model ≤ 50%`, red when `implied_vs_model > 50%` (market pricing in aggressive growth).

## Output Schema

For each scenario, prefer:

- `pv.p25`, `pv.p50`, `pv.p75`, `pv.p90`
- `ev`
- `prob_above_spot`
- `prob_spot_up_30_2y` from undiscounted 2-year MC path values
- `prob_spot_down_30_2y` from undiscounted 2-year MC path values
- `prob_3x` when meaningful; label as right-tail probability in UI when P50 is close to spot or EV is fat-tail driven
- `distribution` P5 through P95 when available
- `y3_price_p50`
- `y3_mcap_p50`
- `y3_supply_p50`
- `y3_gp_p50` or `y3_revenue_p50`
- `y3_gp_by_product_line_p50`, e.g. card, staking, vault, perps, stable-yield
- `y3_daily_mean_volume_p50` or `y3_daily_mean_tvl_p50`, whichever best matches the protocol driver
- `current_baselines`, e.g. annualized GP/revenue, daily volume, TVL/supply, and current effective supply used for Y3 comparison
- `y3_delta_vs_current`, e.g. percentage changes for Y3 GP/revenue, product-line GP/revenue, daily volume/TVL, and effective supply
- `burn_3y_est` / buyback tokens

When the MC run only exports quartiles, either rerun to export the full distribution or explicitly mark derived percentiles as approximated.

Compute delta fields in the model artifact when practical. If the dashboard derives a delta, it must use the same current baseline exported in `current_baselines`; do not silently mix current 30D values with trailing-12M values or current circulating supply with modeled effective supply.

## Primary Scenario Consistency

When a model pivots from one driver to another, for example from protocol-native volume share to a CEX-denominator share model, update every downstream artifact to the new primary scenario:

- Scenario `is_primary` flag.
- Model note and methodology copy.
- Top-line dashboard cards.
- Model output table fields and labels.
- PV distribution and spot line.
- Historical diagnostic/backtest.
- Static or deployed HTML if the repo publishes a separate artifact.

Do not reuse a historical backtest from the old driver as the selected-model diagnostic. If only an old-driver backtest is available, label it as a sensitivity/proxy and add a caveat before publishing.
