**JUP locked valuation refresh — 2026-06-18**

```text
KEY ASSUMPTIONS / LIVE SEEDS
Spot / MCap / FDV       $0.1856 / $616.2M / $1.27B
Circ supply             3.32B JUP
Discount / multiple     24.4% / 15x Y3 TTM entity GP
Perps model             Binance Futures volume x JUP/Binance share x clean take-rate
Spot model              Binance spot volume x JUP/Binance share x observed rake
Perps MS30 / MS90       1.04% / 1.07%
Spot MS30 / MS90        0.51% / 0.58%
Perps clean take-rate   1.50 bps
Spot rake               12.95 bps
Buybacks                50% modeled entity GP at current spot
Scheduled unlocks       0 JUP/mo until a public reserve distribution plan
```

```text
RESULTS — discounted PV / JUP
Case              P25    P50    P75    P90    EV     P>spot 2Y+30 2Y-30
Core GP          $0.164 $0.382 $0.699 $0.992 $0.475  72.1%  77.3%   9.3%
+10% Optionality $0.180 $0.421 $0.769 $1.091 $0.522  74.3%  79.9%   7.8%
+10% Opt + Jupne $0.197 $0.459 $0.839 $1.190 $0.570  76.2%  82.1%   6.6%
```

```text
P50 MODEL STATE / PRODUCT SPLIT
Primary case                 +10% Opt + Jupnet
Primary P50 / EV             $0.459 / $0.570
Y3 TTM entity GP P50         $121.3M
  vs current annualized GP   +112.0%
  Perps GP P50               $29.6M (+4.0% vs current)
  Spot/Agg+Jupiterz GP P50   $66.3M (+130.5% vs current)
Y3 perps daily volume P50    $540.5M/day (+2.6% vs current)
Y3 spot daily volume P50     $140.4M/day (+127.4% vs current)
Y3 effective supply P50      2.49B JUP (-25.1% vs current)
P50 buyback accumulation     832M JUP
```

Caveats:
- JUP Perps direct DefiLlama derivatives volume is not available from the public summary endpoint in this environment; perps numerator falls back to clean-GP-implied volume unless a live dailyVolume series is returned.
- Jupiter aggregator volume falls back to fee-implied volume if the public DEX summary endpoint does not expose dailyVolume for the aggregator slug.
