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
