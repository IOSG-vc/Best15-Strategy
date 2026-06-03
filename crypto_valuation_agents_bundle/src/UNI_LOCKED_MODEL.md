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
