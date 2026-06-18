# JUP / Jupiter Locked Valuation Model

Locked: 2026-05-09. Corrected: 2026-05-15 for supply schedule and optional product tracking. Updated: 2026-06-17 for the stricter crypto-valuation skill architecture: Binance-denominator perps and spot market-share modeling, full percentile ladders, and 2Y ±30% probabilities.

## Core framing

JUP is modeled as a 3Y product-line GP capture model, but the growth engine is now external market share rather than raw Jupiter GP extrapolation.

```text
PV/JUP =
  Year-3 TTM entity GP
  × 15x GP multiple
  × premium multiplier
  ÷ Year-3 effective supply
  ÷ (1 + 24.4%)^3
```

- Multiple: 15x Y3 TTM entity GP.
- Discount rate: 24.4%.
- Primary case: `+10% Opt + Jupnet`, a 20% value premium over core.
- Buybacks: 50% of modeled entity GP buys JUP at current spot and reduces effective supply.
- Scheduled unlocks: 0 JUP/month until Jupiter announces a public cold-storage/community reserve distribution plan.

## Modeled product lines

| Product line | Current treatment |
|---|---|
| Jupiter Perps | Core MC line. Binance Futures monthly denominator × JUP/Binance perps share × clean GP take-rate. |
| Spot aggregator / Ultra + Jupiterz | Core MC line. Binance spot monthly denominator × JUP/Binance spot share × observed rake. |
| Lend, jupSOL, DCA, Limit Orders, Studio, Prediction, Ape-Jupiter, JupUSD | Tracked as live optional revenue where available, but represented in the +10% optionality premium until individually material. |
| Jupnet | Separate +10% value premium until live adoption/revenue can be modeled directly. |
| Litterbox Trust | Supply/buyback mechanic, not a product line. |

## Denominator-share methodology

Perps now match the HYPE/Lighter-style architecture:

```text
JUP perps GP =
  sampled Binance Futures monthly volume
  × JUP/Binance Futures perps share path
  × clean perps GP take-rate
```

Spot now matches the UNI-style external denominator architecture:

```text
JUP spot GP =
  sampled Binance spot monthly volume
  × JUP/Binance spot share path
  × observed spot rake
```

The Binance denominators use BTCUSDT quote-volume histories scaled to Blockworks annual exchange totals. Monthly denominator paths sample historical Binance monthly log returns and are capped at 2x historical peak monthly denominator volume to avoid unrealistic far-tail exchange-size outcomes.

Market-share path:

```text
share velocity =
  70% × MS30/MS180 monthly-equivalent velocity
  + 30% × MS7/MS30 monthly-equivalent velocity
```

The velocity is capped/floored through the shared UNI helper, decayed over 12 months, compounded into a 36-month share path, and capped at 10% absolute share for both JUP/Binance Futures and JUP/Binance spot.

## Data caveats

- The public DefiLlama summary endpoint returned no accessible direct Jupiter derivatives dailyVolume in this environment. Perps numerator therefore falls back to clean-GP-implied volume using a 1.50bps clean take-rate unless a direct dailyVolume series is available.
- Jupiter aggregator dailyVolume may not be exposed by the public DEX summary slug. When unavailable, aggregator volume falls back to fee-implied volume using the observed rake. Jupiterz volume remains directly fetched from DefiLlama DEX volume.
- Smaller products are not yet separate MC drivers because they are small relative to perps/spot and/or lack clean recurring economics.

## Latest output, 2026-06-18

```text
Spot / MCap / FDV       $0.1856 / $616.2M / $1.27B
Perps MS30 / MS90       1.04% / 1.07% vs Binance Futures
Spot MS30 / MS90        0.51% / 0.58% vs Binance spot
Perps clean take-rate   1.50 bps
Spot rake               12.95 bps
```

| Case | P25 | P50 | P75 | P90 | EV | P>spot | 2Y +30% | 2Y -30% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Core GP | $0.164 | $0.382 | $0.699 | $0.992 | $0.475 | 72.1% | 77.3% | 9.3% |
| +10% Optionality | $0.180 | $0.421 | $0.769 | $1.091 | $0.522 | 74.3% | 79.9% | 7.8% |
| +10% Opt + Jupnet | $0.197 | $0.459 | $0.839 | $1.190 | $0.570 | 76.2% | 82.1% | 6.6% |

P50 product state in the primary case:

```text
Y3 TTM entity GP P50          ~$121.3M (+112.0% vs current annualized GP)
  Perps GP P50                ~$29.6M (+4.0% vs current)
  Spot/Agg+Jupiterz GP P50    ~$66.3M (+130.5% vs current)
Y3 perps daily volume P50     ~$540.5M/day (+2.6% vs current)
Y3 spot daily volume P50      ~$140.4M/day (+127.4% vs current)
Y3 effective supply P50       ~2.49B JUP (-25.1% vs current)
P50 buyback accumulation      ~832M JUP
```

## Report format

Use three short Discord-friendly sections:

1. Key assumptions and current market-share/take-rate seeds.
2. Model results: P25/P50/P75/P90/EV, probability above spot, 2Y ±30% probabilities.
3. KPI/watchlist: perps volume/share/take-rate, spot volume/share/rake, monthly buybacks, reserve-distribution announcements, and Jupnet revenue design.
