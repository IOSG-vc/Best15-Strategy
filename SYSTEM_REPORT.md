# IOSG Best15-Strategy — System Report

**What this is:** A crypto quantitative investment platform combining a live Next.js dashboard (deployed on Vercel), automated Python data pipelines run via GitHub Actions, and three auxiliary standalone tools. All data flows through JSON files committed to the repo and served statically at build time.

---

## App 1 — Best15 Strategy Dashboard (Primary)

**Type:** Next.js 14 (App Router) · TypeScript · Tailwind · Recharts · Deployed on Vercel

**URL:** Vercel-hosted (protected)

### Pages / Routes

| Route | Component | What it shows |
|---|---|---|
| `/` | redirects → | → `/private-fund` |
| `/private-fund` | `PrivateFundDashboard` | Strategy performance, NAV, monthly heatmap, drawdown, asset comparison, positions — **password-protected** |
| `/valuation` | `ValuationDashboard` | Token-by-token valuations (UNI, ETHFI, JUP, HYPE, SKY, etc.) with MC models, scenarios, P25–P90 distribution, historical backtest signals |
| `/cycle-signals` | `CycleSignalDashboard` | BTC cycle exposure model — daily K3 rank, composite score, overlay delta, 90-day history chart |
| `/crypto-tech` | `CryptoTechDashboard` | Live crypto + stock prices fetched from `/api/prices` at runtime |
| `/private-fund/login` | `LoginForm` | Cookie-based auth gateway |

### Architecture Diagram — App 1

```
External APIs (runtime)
  CoinGecko Pro ──────────────────┐
  Yahoo Finance ───────────────────┤──► /api/prices  (Next.js API route, force-dynamic)
                                   │         │
                                   │         ▼
                          CryptoTechDashboard (client polling)

GitHub Repo  ← git push ← GitHub Actions (cron)
       │
       │  data/performance.json       ◄─── scripts/update_performance.py
       │  data/cycle_state.json       ◄─── scripts/production_v4.py
       │  data/cycle_history.json     ◄─── scripts/production_v4.py
       │  data/valuations.json        ◄─── scripts/update_valuations.py
       │  data/private_fund_positions.json  (manual / static)
       │
       ▼
  Vercel Build (force-static)
       │
       ├─► lib/loadData.ts        → data/performance.json
       ├─► lib/loadCycleData.ts   → data/cycle_state.json + cycle_history.json
       ├─► lib/loadValuations.ts  → data/valuations.json
       └─► lib/loadPositions.ts   → data/private_fund_positions.json
               │
               ▼
    Next.js Pages (SSG — baked at build time)
       /private-fund   →  PrivateFundDashboard
       /valuation      →  ValuationDashboard
       /cycle-signals  →  CycleSignalDashboard

Auth layer: Next.js middleware checks `pf_auth` cookie on /private-fund/*
             POST /api/auth sets cookie, DELETE /api/auth clears it
```

---

## Data Pipeline — GitHub Actions Cron Jobs

| Workflow | Schedule (UTC) | Script | Inputs | Output |
|---|---|---|---|---|
| `update-performance.yml` | Daily 08:00 | `scripts/update_performance.py` | CoinGecko API + yfinance + CSV weights in `Weights History Top15 BTC 50% Cap/` | `data/performance.json` |
| `update-cycle-signals.yml` | Daily 09:00 | `scripts/production_v4.py` | CryptoQuant API + FRED API (via V3 backend) | `data/cycle_state.json`, `data/cycle_history.json` |
| `update_valuations.yml` | Daily 10:00 | `scripts/update_valuations.py` | CoinGecko + FRED + DefiLlama APIs, pulls from `crypto_valuation_agents_bundle/webapp/agents/` | `data/valuations.json` |
| `weekly-fund-report.yml` | Mondays (after perf update) | `scripts/weekly_fund_report.py` | `data/performance.json` + live prices | Slack webhook message |

```
Data Flow — Pipeline Layer

  CoinGecko API ─────────────────────────────────────────────┐
  yfinance (Yahoo Finance) ──────────────────────────────────┤
  Weights CSVs (repo static) ────────────────────────────────┤──► update_performance.py ──► data/performance.json
                                                              │
  CryptoQuant API ────────────────────────────────────────────┤
  FRED API ───────────────────────────────────────────────────┤──► production_v4.py ──────► data/cycle_state.json
  Yahoo Finance (BTC) ────────────────────────────────────────┤                             data/cycle_history.json
                                                              │     cache/base_parts/
                                                              │     cache/k3_mined_candidates.csv
  CoinGecko API ─────────────────────────────────────────────┐
  FRED API ───────────────────────────────────────────────────┤──► update_valuations.py ──► data/valuations.json
  DefiLlama API ──────────────────────────────────────────────┘     (calls 10 per-token agents)

  data/performance.json ─────────────────────────────────────► weekly_fund_report.py ──► Slack

  GitHub Actions commits → pushes updated JSON → triggers Vercel redeploy
```

---

## App 2 — Crypto Tech Dashboard (Standalone, Local)

**Type:** FastAPI (Python 3.12) + vanilla JS SPA · Local CSV store · Docker-portable
**Location:** `crypto-tech-dashboard-2nd-try-v2.0/crypto-tech-dashboard/`
**Run:** `./run.sh` → `http://localhost:8080`

### What it does
Pulls CoinGecko Top-200 daily OHLCV through a **Binance → OKX → Bybit → Gate.io → CoinGecko** exchange waterfall, computes 12 technical indicator families, ranks tokens by blended trend/reversal score + 2y/3y time-series percentiles.

### Architecture Diagram — App 2

```
┌─────────────────────────────────────────────────────────────────┐
│                   Crypto Tech Dashboard                         │
│                                                                 │
│  Exchanges (data ingestion)                                     │
│  Binance ──┐                                                    │
│  OKX ──────┤── Exchange Waterfall ──► OHLCV CSV per token      │
│  Bybit ────┤                         local_data/ohlcv/          │
│  Gate.io ──┘         (fallback) ──► local_data/market_cap/     │
│  CoinGecko (close-only fallback)    local_data/metadata/        │
│                                              │                  │
│                          APScheduler ────────┘                  │
│                          08:30 Asia/Shanghai daily              │
│                                                                 │
│  Backend (FastAPI)                                              │
│  ├─ indicators/    12 families (RSI, MACD, BB, etc.)           │
│  ├─ scoring/       trend_score + reversal_score + CS/TS %ile   │
│  ├─ backtest/      golden_cross equity curve                    │
│  ├─ services/      data_service singleton cache                 │
│  └─ api/routes_*   REST endpoints                              │
│                          │                                      │
│  Frontend (Static SPA)   │                                      │
│  ├─ Lightweight Charts   │                                      │
│  ├─ Candle + 6 indicator panels                                 │
│  ├─ Trend/Reversal gauges│                                      │
│  └─ Sidebar Top-20 feed  │                                      │
│                          │                                      │
│  Browser ──────────────► REST API (FastAPI) ──► CSV data store │
└─────────────────────────────────────────────────────────────────┘
```

---

## App 3 — Crypto Valuation Agents Bundle

**Type:** Python agent library · Hermes cron (Mon/Fri 09:00) + GitHub Actions daily
**Location:** `crypto_valuation_agents_bundle/webapp/agents/`

### Tokens covered
`UNI · ETHFI · JUP · HYPE · SKY · Lighter · VVV · BP · CARDS · COIN (Coinbase)`

### Architecture Diagram — App 3

```
External Data
  CoinGecko Pro ─────────────────────┐
  FRED API ──────────────────────────┤
  DefiLlama API ─────────────────────┤
                                     ▼
  Per-token agent (Python)        update_valuations.py
  agents/uni.py                        │
  agents/ethfi.py    ─────────────────►│
  agents/jup.py          Monte Carlo   │  GP-capture model,
  agents/hype.py         GP-capture,   │  DCF / MC scenarios,
  agents/sky.py          DCF model     │  P25/P50/P75/P90
  agents/bp.py                         │
  agents/cards.py                      │
  agents/coinbase.py  (stock model)    │
  ...                                  │
                                       ▼
                              data/valuations.json
                                       │
                                       ▼
                          /valuation page (Next.js)
                          ValuationDashboard component
```

---

## App 4 — CycleSignal V4 (Standalone Research Repo)

**Type:** Python 3 · Separate git repo inside workspace
**Location:** `cyclesignal-v4/`

### What it does
Production runner for the locked V4 strategy: `K10/sqrtN base + K3 cbrtM overlay`. Incremental daily updates with caching of quarterly rebalance segments.

### Architecture Diagram — App 4

```
APIs
  CryptoQuant ──► BTC on-chain signals (138 signal matrix)
  FRED API ──────► macro regime indicators
  Yahoo Finance ──► BTC daily close

        ▼
  production_v4.py
  ├─ Phase 1: Base (K10/sqrtN)
  │   cache/base_parts/ ──► reuse completed quarters
  │   open quarter ──────► recompute daily
  │
  ├─ Phase 2: K3 mining (incremental)
  │   cache/k3_mined_candidates.csv ──► yearly anchors (pre-seeded 2016–2026)
  │   new year start ──────────────────► mine + append
  │
  ├─ Phase 3: cbrtM motif scoring → K3 evidence rank
  │
  └─ Phase 4: One-step overlay (+20% / -20%)

        ▼
  data/cycle_state.json   ◄── latest exposure snapshot
  data/cycle_history.json ◄── one row per day (appended)
  data/daily.csv          ◄── full series

  (feeds into Best15 main app /cycle-signals page via GitHub Actions sync)

  Future: Crash Gate layer (combined_exposure = v4_exposure × crash_gate)
```

---

## App 5 — HYPE Valuation Agent (Static Report)

**Type:** Python Monte Carlo → static HTML → Vercel
**Location:** `hype_valuation_agent_20260612_192434/`
**Deployed:** `https://vercel-html-illustrations.vercel.app/hype-dashboard/`

### Architecture Diagram — App 5

```
  DefiLlama (HL/Binance derivatives volume)
  Market share assumptions (locked model)
  Monte Carlo (3Y GP-capture)
         │
         ▼
  altcoin_research/hype_gp_capture_12m_start_run.py
         │
         ▼
  dashboard/build_hype_dashboard_v2.py
         │
         ▼
  dashboard/hype-dashboard-index.html  (static, self-contained)
         │
         ▼
  Vercel deploy → public URL
```

---

## Summary — System-Wide Data Flow

```
                     ┌─────────────────────────────────────┐
                     │         External Data Sources        │
                     │  CoinGecko · CryptoQuant · FRED      │
                     │  DefiLlama · yfinance · Exchanges    │
                     └──────────────┬──────────────────────┘
                                    │
                         ┌──────────▼──────────┐
                         │   GitHub Actions     │
                         │   (cron: daily)      │
                         │  08:00 → performance │
                         │  09:00 → cycle V4    │
                         │  10:00 → valuations  │
                         │  Mon   → Slack report│
                         └──────────┬──────────┘
                                    │ git commit + push
                                    │ (JSON files in /data)
                         ┌──────────▼──────────┐
                         │   GitHub Repo        │
                         │  data/*.json  ◄──────┼── private_fund_positions.json
                         │  (source of truth)   │   (manual update)
                         └──────────┬──────────┘
                                    │ Vercel rebuild trigger
                         ┌──────────▼──────────┐
                         │   Vercel (Next.js)   │
                         │  SSG pages baked     │
                         │  from JSON at build  │
                         │                      │
                         │  /private-fund ───── │──► PrivateFundDashboard
                         │  /valuation ──────── │──► ValuationDashboard
                         │  /cycle-signals ──── │──► CycleSignalDashboard
                         │  /crypto-tech ─────  │──► live prices (runtime API)
                         └─────────────────────┘

Standalone (not in Vercel):
  Crypto Tech Dashboard ─── local FastAPI + CSV + browser SPA
  HYPE Dashboard ─────────── static HTML on separate Vercel project
```

---

## Key Data Maintenance Notes

| Data file | Updated by | Frequency |
|---|---|---|
| `data/performance.json` | GitHub Actions (auto) | Daily 08:00 UTC |
| `data/cycle_state.json` | GitHub Actions (auto) | Daily 09:00 UTC |
| `data/cycle_history.json` | GitHub Actions (auto) | Daily 09:00 UTC |
| `data/valuations.json` | GitHub Actions (auto) | Daily 10:00 UTC |
| `data/private_fund_positions.json` | **Manual** | On rebalance |

- Vercel rebuilds automatically on every git push (triggered by the Actions commits).
- The crypto-tech-dashboard has its own **local** data store (`local_data/`) — fully independent of the main repo and not synced anywhere automatically.
- API secrets stored as GitHub repo secrets: `COINGECKO_API_KEY`, `CRYPTOQUANT_KEY`, `FRED_API_KEY`, `DEFILLAMA_API_KEY`, `SLACK_WEBHOOK_URL`, `PRIVATE_FUND_PASSWORD`, `PRIVATE_FUND_TOKEN`.
