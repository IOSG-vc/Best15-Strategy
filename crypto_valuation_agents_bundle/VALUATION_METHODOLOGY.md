# Crypto Valuation Agents — Methodology

**Tokens covered:** Morpho (MORPHO), Spark (SPK), Aave (AAVE)
**Framework:** 3-Year GP-Capture Monte Carlo · **As of:** 2026-06-30 · **Owner:** IOSG Research

---

## 0. TL;DR — what these agents do

Each agent answers one question: *what is a token worth on a 3-year horizon if you value it on the
gross profit (GP) the protocol can plausibly capture, grown stochastically, and discounted back?*

It is **not** a perpetual DCF / terminal-value model. It is a 3-year, investment-horizon, distribution-based
fair value. Every run fetches **live** protocol + market data, runs a **100,000-path Monte Carlo**, and emits a
fair-value **distribution** (P25 / P50 / P75 / P90) plus probabilities (P(>spot), 2Y ±30%) for a dashboard card.

The three new agents reuse the existing house engine (built for SKY / UNI / HYPE) and differ only in **how GP is
earned**, which is exactly where the three businesses differ.

---

## 1. The core formula

```
                 Y3 trailing-12M GP  (P50 of 100k paths)   ×   15×  GP multiple
PV per token  =  ───────────────────────────────────────────────────────────────
                              token supply   ×   (1 + discount rate)³
```

- **GP** = the gross profit the *token/DAO* captures (definition differs per protocol — §4).
- **15× multiple** on Year-3 GP (house standard, matches UNI/SKY; no perpetual terminal value).
- **Supply** = the relevant token supply 3 years out (circulating + modeled unlocks — §6).
- **Discount rate** = liquid-token rate, `rf + ERP × (token vol / S&P vol)` (§5).

The full P25–P90 distribution and EV come from the Monte Carlo, not a point estimate.

---

## 2. The shared engine (4 steps)

All three agents (and SKY) run the same machinery. Only **Step 3** changes between tokens.

### Step 1 — Denominator: the addressable market
A **lending/yield TVL "basket"** — the monthly sum of TVL across the 20 largest lending / CDP / yield protocols
(Aave V3, Morpho Blue, SparkLend, Compound, Euler, Fluid, Maple, Kamino, Pendle, Sky Lending, …). This is the
"total addressable market" the protocol competes in. The basket is a **53-month series (2022-01 → 2026-05)** with
its monthly log-returns; it is **locked** in `<token>_research_extra.json` (reused from the validated SKY model —
all three new protocols are *members* of this basket).

In the Monte Carlo, each of the 100k paths:
- draws a **starting** basket TVL uniformly from the historical monthly denominators, and
- applies **36 monthly shocks** sampled from the historical log-returns (dampened ×0.65, capped −8%/+10% per month).

### Step 2 — Market share path
The protocol's **share of the basket** = (protocol TVL ÷ basket TVL), computed as rolling **MS7 / MS30 / MS90 / MS180**
from the protocol's *live daily TVL* mapped onto the basket's monthly denominator.

- **Seed** the share at **MS90** (the 90-day average — robust to noise).
- **Grow** it with a **velocity ensemble**: 70% weight on medium-term momentum (MS30/MS180) + 30% on short-term
  (MS7/MS30), converted to a monthly log-velocity that **decays to zero over 12 months** (share growth doesn't
  compound forever).
- **Cap** the terminal share (Morpho 35%, Spark 35%, Aave 45%) so no protocol is modeled to eat the whole market.

`Protocol TVL path = basket TVL path × share path` for all 36 months.

### Step 3 — GP derivation (the protocol-specific part — see §4)
Convert TVL into the GP the token captures:
```
GP = protocol TVL × yield-on-TVL × take
```
where *yield-on-TVL* and *take* are defined per protocol from live data.

### Step 4 — Valuation
For each path: Y3 trailing-12M GP → × 15× → ÷ supply → ÷ (1+DR)³ = discounted PV per token. Then read off the
P25/P50/P75/P90, the EV, P(PV ≥ spot), P(PV ≥ 3× spot), and 2-year undiscounted ±30% probabilities.

---

## 3. Reference mapping — which existing agent each one is built on

| New token | Built on (reference) | Why | What's different |
|---|---|---|---|
| **Morpho** | **SKY** (denominator/share) + **UNI** (fee-switch) | Lending is a *stock* business like SKY; value accrual is a *fee-switch activation* story like UNI | Protocol fee is **OFF** today (token revenue ≈ $0); GP is hypothetical "if the switch is turned on" |
| **Spark** | **SKY** | Spark is a *Sky subDAO / capital allocator* — same money-market spread economics as Sky itself | GP = retained **net interest margin** on managed capital; tiny float (30% of 10B) |
| **Aave** | **SKY** + **UNI**, with **real revenue** | Lending stock business + GP-capture framing | Aave already earns **real reserve-factor revenue today** → current-state is the *primary* case, not an activation story |

**Why a stock (TVL) model, not a flow (volume) model:** UNI/HYPE value a *flow* (DEX/perp volume × fee). Lending is
a *stock* business — TVL/borrows earn interest continuously — so these three use SKY's TVL-denominator structure, not
UNI's volume structure. (Morpho borrows UNI's *fee-switch* idea but applies it to the lending stock.)

---

## 4. Per-token GP definition

### 4.1 Morpho (MORPHO) — *lending fee-switch GP-capture*
- **Reference:** SKY (engine) + UNI (fee-switch framing).
- **Key fact:** Morpho Blue's protocol fee switch is **OFF by default** — DefiLlama shows ~$0 "revenue". Borrowers
  pay interest ("fees", ~$200M/yr) but it all goes to suppliers today. On-chain max protocol fee is **25% of interest**.
- **GP** = Morpho TVL × **fee-yield-on-TVL** (trailing interest ÷ TVL, ~3.2%) × **fee-switch take**.
- **Scenarios (the take axis):** Conservative **10%** · **Base 15% (primary)** · Full **25%** (on-chain max) ·
  + a circulating-supply sensitivity.
- **Read:** a fee-*activation* valuation. Spot already prices in activation **plus** growth.

### 4.2 Spark (SPK) — *Sky-ecosystem capital-allocator GP-capture*
- **Reference:** SKY.
- **Key fact:** Spark borrows USDS from Sky at the Sky Savings Rate and deploys it across **SparkLend** (lending) +
  **Spark Liquidity Layer** (DeFi/CeFi/RWA deployment) + **Spark Savings** (sUSDS — a *cost* line). Gross income
  (SparkLend interest + SLL yield) ≈ $139M/yr.
- **GP** = combined Spark TVL × **gross-income-yield** (gross income ÷ TVL, ~2.0%) × **net margin** retained after
  Sky's cost-of-capital and savings payouts.
- **Scenarios (the take axis):** Conservative **20%** · **Base 30% (primary)** · Bull **40%** · + max-supply (FDV).
- **Supply caveat:** only **~30%** of the 10B SPK supply circulates → the 3Y model uses **near-fully-diluted** supply.

### 4.3 Aave (AAVE) — *lending GP-capture on real revenue*
- **Reference:** SKY + UNI, but with **real current cashflow** (unlike Morpho).
- **Key fact:** Aave already earns **real protocol revenue** today — the reserve-factor cut of borrower interest
  (~$60M/yr, live from DefiLlama `dailyRevenue`), ≈ a 0.5% net yield on TVL. Plus GHO.
- **GP** = Aave TVL × **net revenue yield on TVL** (already net of the reserve factor — no extra "take").
- **Scenarios (the yield/margin axis):** Conservative **0.40%** · **Current ~0.50% (primary)** · Expansion **0.70%**
  (GHO scaling + reserve-factor hikes) · + max-supply (FDV).
- **Note:** the Aavenomics buyback (~$1M/wk) is reported as *supporting context*, not added to GP (avoids
  double-counting protocol revenue).

---

## 5. Discount rate (liquid-token framework)

```
DR = risk-free rate + 3% ERP × (token daily-return stdev ÷ S&P-500 daily-return stdev)
```
- **rf** = US 10Y yield (live from Yahoo `^TNX`, falls back to FRED `DGS10`, then 4.5%).
- **token vol / S&P vol** = ratio of 365-day daily-return standard deviations (token from CoinGecko, S&P from Yahoo `^GSPC`).
- This produces a token-specific liquid discount (e.g. ~24% Morpho, ~21% Aave, ~35% Spark — Spark is the most volatile).
- Locked fallback in each `<token>_research_extra.json` if the live fetch fails.

---

## 6. Supply / dilution treatment

- Effective supply follows each token's **real published vesting/emission schedule**, stored as a **monthly
  outstanding-supply curve** (`supply_schedule` in `<token>_research_extra.json`). The PV divides Y3 GP by the
  **month-36** supply and the Y2 price by the **month-24** supply.
- Primary scenarios use a **float basis** (contractual + scheduled supply); the **FDV (max-supply) row** is the
  explicit full-dilution downside.
- **Morpho:** ~320M float today → **~525M by Y3** (contractual tranches: Founders to 2028, Strategic to 2027,
  Early Contributors to 2029). The 47.5% DAO/TBD reserve (no fixed schedule) is the FDV (1B) row. *(Note: CoinGecko
  over-reports Morpho "circulating" at ~650M by counting the DAO reserve — the model uses the 320M float instead.)*
- **Spark:** ~3.04B today → **~6.5B (Y2) → ~7.9B (Y3)** from declining Sky-Farming (1.625B/yr → …) + team
  (12-mo cliff, 3-yr vest) + ecosystem; FDV = 10B. Heavy farming emission is a real sell-pressure overhang.
- **Aave:** ~95% circulating of 16M → ~15.5M by Y3 (only the small Ecosystem Reserve trickles); FDV ≈ base.
- *(Prior versions inferred the unlock rate by extrapolating trailing circulating-supply growth — that over-stated
  dilution for Morpho/Spark and is now replaced by the explicit schedule.)*

---

## 7. Data sources

| Input | Source | Live / locked |
|---|---|---|
| Spot, market cap, FDV, supply | CoinGecko (`/coins/<id>`) | **Live** |
| Token price/mcap history (vol + supply growth) | CoinGecko (`/market_chart`) | **Live** |
| Protocol TVL (daily) | DefiLlama (`/protocol/<slug>`) | **Live** |
| Protocol fees / revenue (daily) | DefiLlama (`/summary/fees/<slug>?dataType=dailyFees|dailyRevenue`) | **Live** |
| Lending/yield TVL basket (denominator) | DefiLlama (20-protocol monthly series) | **Locked** (`<token>_research_extra.json`, 2022-01→2026-05) |
| Risk-free rate | Yahoo `^TNX` → FRED `DGS10` | **Live** (fallback 4.5%) |
| S&P 500 volatility | Yahoo `^GSPC` | **Live** |

Each agent degrades to **locked fallbacks** (a 2026-06-30 snapshot) if any live source is unavailable, so `run()`
never crashes the dashboard.

---

## 8. Outputs (what the dashboard shows)

Per token card: spot / mcap / FDV; model type, discount rate, multiple, paths; current-GP cards; and a **scenario
table** — for each scenario: P25 / P50 / P75 / P90 fair value, P(>spot), 2Y +30% / −30% probabilities, with a
mini range bar against spot. Plus model note and caveats. Each agent also emits `ms_history` and `hist_charts`
(Mcap/GP secondary chart, a model backtest with GOOD/NEUTRAL/BAD signals, and EOY3 market-share history).

---

## 9. Results snapshot (2026-06-30, live)

> Filled in after the verification pass — see §10.

| Token | Spot | Primary scenario | P50 fair value | P(>spot) | One-line read |
|---|---|---|---|---|---|
| **MORPHO** | $1.88 | Base activation (15%), 525M float | ~$0.47 (FDV row ~$0.25) | ~1% | Still rich — prices in fee activation **+** large growth |
| **SPK** | $0.017 | Base (30% net margin), 7.9B Y3 | ~$0.035 (FDV row ~$0.028) | ~85% | Looks cheap on GP basis (thin float, Sky-backed revenue unpriced) |
| **AAVE** | $90 | Current-state revenue, 15.5M | ~$38 | ~11% | Rich on conservative current-revenue GP-capture (real cashflow) |

*(Supply now from real vesting schedules — §6. The Morpho/SPK P50s rose vs the earlier full-dilution numbers; FDV rows bracket the downside.)*

*All three valuations are intentionally conservative (15× GP, current/locked yields, capped share). They are a
GP-capture floor, not a target price; narrative/multiple re-rating is upside not captured here.*

---

## 10. How to run / extend

- Run one agent: `cd webapp && python3 -m agents.<token>` (writes `results/<token>_result.json`).
- Serve the dashboard: `python3 webapp/app.py` → http://localhost:5050 → click "Run Valuation".
- **Add a new token:** (1) write `webapp/agents/<token>.py` (copy the closest sibling); (2) register in `app.py`
  `AGENTS`; (3) add to `index.html` `TOKENS` + `COLORS`. Reuse the basket denominator from any `*_research_extra.json`.

---

## 11. Key assumptions & honest caveats

- **The basket return distribution is locked** at 2022-01→2026-05; current denominator and all protocol data are live.
- **Morpho:** entirely a fee-*activation* story — token captures ~$0 today; the take (10/15/25%) is the dominant lever.
- **Spark:** the **net margin** (20/30/40%) is *modeled*, not directly observable; gross income includes SLL yield
  which Spark must share with Sky (the margin haircuts for this). Combined component TVL has some internal double-count.
- **Aave:** current revenue yield is **post-April-2026-crash and cyclical**; reserve factors vary by asset; GHO upside
  sits in the expansion scenario.
- **All:** 15× GP multiple and capped market share are deliberate conservatism. No OPEX line (GP-capture framing).
