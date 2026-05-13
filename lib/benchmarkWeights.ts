// MCAP weights renormalized to the 12 assets available in performance data
// (avalanche-2, sui, hedera-hashgraph excluded — ~0.54% missing)
const MCAP_TOTAL = 96.16;
export const MCAP_WEIGHTS: Record<string, number> = {
  bitcoin:        73.6  / MCAP_TOTAL,
  ethereum:        9.17 / MCAP_TOTAL,
  binancecoin:     3.97 / MCAP_TOTAL,
  solana:          3.95 / MCAP_TOTAL,
  ripple:          2.38 / MCAP_TOTAL,
  cardano:         1.42 / MCAP_TOTAL,
  chainlink:       0.57 / MCAP_TOTAL,
  stellar:         0.31 / MCAP_TOTAL,
  uniswap:         0.22 / MCAP_TOTAL,
  litecoin:        0.22 / MCAP_TOTAL,
  zcash:           0.18 / MCAP_TOTAL,
  "bitcoin-cash":  0.17 / MCAP_TOTAL,
};

// 1/N equal weight across 12 available assets of the universe
// (avalanche-2, sui, hedera-hashgraph not in performance data — weight renormalized)
const N = 12;
export const LIQUIDITY_WEIGHTS: Record<string, number> = {
  bitcoin:        1 / N,
  ethereum:       1 / N,
  binancecoin:    1 / N,
  solana:         1 / N,
  ripple:         1 / N,
  cardano:        1 / N,
  chainlink:      1 / N,
  stellar:        1 / N,
  litecoin:       1 / N,
  uniswap:        1 / N,
  zcash:          1 / N,
  "bitcoin-cash": 1 / N,
};
