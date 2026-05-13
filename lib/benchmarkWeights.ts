// ── Liquidity Universe (15 assets) ──────────────────────────────────────────
// 3 assets not in performance data: sui, aave, avalanche-2
// All weight maps are renormalized to the 12 available assets.

// MCAP-weighted (liquidity universe) — missing 0.43% of total weight
const MCAP_TOTAL = 99.57;
export const MCAP_WEIGHTS: Record<string, number> = {
  bitcoin:        73.80 / MCAP_TOTAL,
  ethereum:       13.15 / MCAP_TOTAL,
  ripple:          4.07 / MCAP_TOTAL,
  binancecoin:     4.00 / MCAP_TOTAL,
  solana:          2.31 / MCAP_TOTAL,
  hyperliquid:     0.46 / MCAP_TOTAL,
  cardano:         0.44 / MCAP_TOTAL,
  "bitcoin-cash":  0.43 / MCAP_TOTAL,
  chainlink:       0.32 / MCAP_TOTAL,
  zcash:           0.28 / MCAP_TOTAL,
  litecoin:        0.21 / MCAP_TOTAL,
  uniswap:         0.10 / MCAP_TOTAL,
};

// Volume/liquidity-weighted — missing 1.36% of total weight (sui, aave, avalanche-2)
const VOL_TOTAL = 98.65;
export const VOLUME_WEIGHTS: Record<string, number> = {
  bitcoin:        59.55 / VOL_TOTAL,
  ethereum:       26.32 / VOL_TOTAL,
  solana:          5.18 / VOL_TOTAL,
  ripple:          3.33 / VOL_TOTAL,
  binancecoin:     1.36 / VOL_TOTAL,
  cardano:         0.62 / VOL_TOTAL,
  zcash:           0.47 / VOL_TOTAL,
  chainlink:       0.45 / VOL_TOTAL,
  litecoin:        0.43 / VOL_TOTAL,
  hyperliquid:     0.38 / VOL_TOTAL,
  "bitcoin-cash":  0.31 / VOL_TOTAL,
  uniswap:         0.25 / VOL_TOTAL,
};

// 1/N equal weight — 12 of 15 liquidity universe assets available
const N = 12;
export const LIQUIDITY_WEIGHTS: Record<string, number> = {
  bitcoin:        1 / N,
  ethereum:       1 / N,
  solana:         1 / N,
  ripple:         1 / N,
  binancecoin:    1 / N,
  cardano:        1 / N,
  zcash:          1 / N,
  chainlink:      1 / N,
  litecoin:       1 / N,
  hyperliquid:    1 / N,
  "bitcoin-cash": 1 / N,
  uniswap:        1 / N,
};
