# HYPE Valuation Agent Bundle

Updated HYPE valuation model + Vercel dashboard builder.

## Contents

- `altcoin_research/hype_gp_capture_12m_start_run.py` — main 3Y GP-capture Monte Carlo model.
- `altcoin_research/hype_gp_capture_mc.py` — supporting data/model utilities.
- `dashboard/build_hype_dashboard_v2.py` — static dashboard generator.
- `dashboard/hype-dashboard-index.html` — latest generated dashboard HTML snapshot.
- `docs/STANDARD_VERCEL_REPORT_TEMPLATE.md` — generalized reporting template.

## Locked assumptions in this bundle

- HL/Binance market share uses DefiLlama MCP derivatives-volume aggregates for headline MS30/MS90/MS180.
- Binance denominator uses the BTCUSDT-scaled Binance futures proxy.
- MS30/MS180 is interpreted as a 6M forward share-growth amplifier.
- Growth velocity decays fully within 12 months; gained share is retained.
- Absolute HL/Binance share cap: 35%.
- Take rate: 0.034%.
- USDC yield is modeled separately from DefiLlama revenue.
- Dashboard reports one selected model, not token-overhang scenarios.

## Run

From the workspace root:

```bash
python3 altcoin_research/hype_gp_capture_12m_start_run.py
python3 dashboard/build_hype_dashboard_v2.py
```

The dashboard is currently deployed at:
https://vercel-html-illustrations.vercel.app/hype-dashboard/
