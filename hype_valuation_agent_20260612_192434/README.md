# HYPE Valuation Agent Bundle — DEPRECATED STANDALONE COPY

> **This folder is a snapshot from 2026-06-12 and is no longer the active model.**
> Active model lives at:
> - `crypto_valuation_agents_bundle/hype_gp_capture_12m_start_run.py` (model engine)
> - `crypto_valuation_agents_bundle/webapp/agents/hype.py` (webapp agent)
>
> Key differences vs this snapshot:
> - Take-rate corrected: **0.026% net revenue** (not 0.034%)
> - Scenario axis changed to **velocity-decay** (Bear 6M / Base 12M / Bull 24M) instead of supply/emission scenarios
> - USDC elasticity replaced with **fixed DefiLlama Pro betas** (0.60 / 0.85 / 1.00)
> - Weighted P50 = 40% bull + 40% base + 20% bear

## Contents (archive)

- `altcoin_research/hype_gp_capture_12m_start_run.py` — OLD model with 0.034% take-rate (supply/emission scenarios).
- `altcoin_research/hype_gp_capture_mc.py` — supporting data/model utilities (still current).
- `dashboard/build_hype_dashboard_v2.py` — OLD static dashboard generator (reads deprecated JSON schema).
- `dashboard/hype-dashboard-index.html` — last generated HTML snapshot (take-rate copy updated to 0.026%).
- `docs/STANDARD_VERCEL_REPORT_TEMPLATE.md` — generalized reporting template.

## Run

From the workspace root:

```bash
python3 altcoin_research/hype_gp_capture_12m_start_run.py
python3 dashboard/build_hype_dashboard_v2.py
```

The dashboard is currently deployed at:
https://vercel-html-illustrations.vercel.app/hype-dashboard/
