# SKY MC valuation

As of: 2026-06-18T06:53:22.954510+00:00

## Primary scenario

```text
Scenario                           Base OPEX ($70M), 15× NP
P50 PV                             $0.0442
P25 / P75 / P90                    $0.0323 / $0.0633 / $0.0859
EV                                 $0.0516
P(above spot)                      32.4%
2Y +30% / -30%                     56.3% / 0.0%
Y3 GP P50                          $203.9M
Y3 total Sky stable supply P50      $10.99B
```

## Current assumptions

```text
Official USDS supply                $6.36B
Official DAI supply                 $3.90B
Gross income take-rate              401.4 bps
Savings cost rate                   182.7 bps
stUSDS cost rate                    12.5 bps
Net GP take-rate                    206.3 bps
Velocity ensemble                   1.35%/mo
Discount / multiple                 25% / 15x
```

## Caveats

- USDS/DAI supply is sourced from Sky's official supply page API; financial rates and savings/stUSDS assumptions remain locked at the prior run.
- USDS path now follows broad money-market/yield-vault TVL denominator × Sky share, not DefiLlama stablecoin market share.
- No buybacks or SKY supply reduction modeled; treasury accumulates cash only.
- Take-rate assumptions are stablecoin economics rates on modeled Sky supply: gross income yield, savings cost, stUSDS cost, and net GP spread.
- Savings rate (3.65%) and USDS savings penetration (81.2%) are point-in-time inputs.
