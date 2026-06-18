# Data Validation Reference

## Source Priority

1. Local model outputs and scripts already in the repo.
2. DefiLlama MCP/tools for protocol revenue, fees, holders revenue, TVL, derivatives volume, stablecoins, yields, and prices.
3. Official protocol docs/APIs or verified public dashboards.
4. CoinGecko/CoinMarketCap for token price, market cap, FDV, and supply.
5. Otter/Notion/Drive only when the user asks to incorporate meeting notes or internal estimates.

Use web/API browsing for current market data because these facts change.

## DefiLlama Metric Semantics

Check definitions before modeling:

- `dailyFees`: user-paid fees; may include third-party builder/front-end code fees in some adapters.
- `dailyRevenue`: protocol/treasury revenue; usually better for token valuation than total fees.
- `dailyHoldersRevenue` or `holdersRevenue`: amount routed to token holders or buybacks.
- `dailyVolume` / derivatives volume: GMV/paid volume; verify venue and denominator.
- TVL: stock, not flow. Do not annualize TVL.
- Revenue/fees: flow. 30D annualized = trailing 30D × 12.

Known trap from HYPE work: if adapter fees include builder code fees, clean treasury revenue should use base protocol revenue, not total fees. A 0.034% fee model can be valid for gross fees while clean treasury revenue may be closer to a lower bps rate.

## Growth And Traction Work

When analyzing company traction such as Fun.xyz:

- Treat founder-updated revenue/ARR as a new primary data point if the meeting transcript confirms it.
- Preserve historical authority from the original model where the user says it is authoritative.
- Separate GMV growth from revenue growth when product mix/take rate changes.
- Build both level charts and growth-velocity charts:
  - Monthly volume or revenue where monthly data exists.
  - Annualized MoM growth where monthly data exists.
  - Period-to-period annualized growth where monthly granularity is missing.
  - QoQ growth velocity to show acceleration/deceleration.
- Update valuation scenarios using current growth rate haircuts only when the user specifies the haircut.

## Internal Meeting Checks

For Otter:

- Call `get_user_info` first.
- Infer dates from user language, e.g. “about 10 days ago” relative to current date.
- Search meeting metadata first, then fetch transcript only for the likely meeting.
- Quote meeting content sparingly; summarize revenue/ARR/product-mix claims and note uncertainty.

For Notion:

- Search/fetch target pages by URL or title.
- If editing, inspect the page first and preserve existing structure.
- If translating content, keep facts and names literal; do not invent missing details.

## Sanity Checks

Before publishing numbers:

- Reconcile 30D revenue annualized with ARR claims.
- Compare net take rate = revenue / volume.
- Check whether there is enough 2022-present history for MC draws; if not, disclose the shorter window and use the fallback scenario framework.
- Verify the growth velocity source window: 30D/180D and 7D/30D components should use the same metric definition and denominator.
- Compare market cap / revenue and market cap / GP.
- Check current supply vs FDV/max supply.
- Verify whether buybacks are funded by total revenue, holder revenue, or a subset.
- If there is no burn, confirm net profit is modeled as treasury cash rather than supply reduction.
- Explain any mismatch between historical estimates and latest founder/data updates.
