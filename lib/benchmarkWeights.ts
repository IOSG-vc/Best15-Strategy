// ── MCAP Universe ────────────────────────────────────────────────────────────
// Original 15-asset universe (stellar, no sui/aave/avalanche-2/hyperliquid).
// 12 assets available in performance data; missing ~3.84% renormalized away.

const MCAP_UNIV_TOTAL = 96.16;
export const MCAP_UNIV_MCAP_WEIGHTS: Record<string, number> = {
  bitcoin:        73.60 / MCAP_UNIV_TOTAL,
  ethereum:        9.17 / MCAP_UNIV_TOTAL,
  binancecoin:     3.97 / MCAP_UNIV_TOTAL,
  solana:          3.95 / MCAP_UNIV_TOTAL,
  ripple:          2.38 / MCAP_UNIV_TOTAL,
  cardano:         1.42 / MCAP_UNIV_TOTAL,
  chainlink:       0.57 / MCAP_UNIV_TOTAL,
  stellar:         0.31 / MCAP_UNIV_TOTAL,
  uniswap:         0.22 / MCAP_UNIV_TOTAL,
  litecoin:        0.22 / MCAP_UNIV_TOTAL,
  zcash:           0.18 / MCAP_UNIV_TOTAL,
  "bitcoin-cash":  0.17 / MCAP_UNIV_TOTAL,
};

const MCAP_UNIV_N = 12;
export const MCAP_UNIV_1N_WEIGHTS: Record<string, number> = Object.fromEntries(
  Object.keys(MCAP_UNIV_MCAP_WEIGHTS).map((a) => [a, 1 / MCAP_UNIV_N]),
);

// ── Liquidity Universe ────────────────────────────────────────────────────────
// New 15-asset universe (hyperliquid, uniswap, aave, sui, avalanche-2).
// Missing: sui, aave, avalanche-2. Weights below renormalized to available assets.

// MCAP-weighted — missing 0.43% (sui+aave+avalanche-2)
const LIQ_MCAP_TOTAL = 99.57;
export const MCAP_WEIGHTS: Record<string, number> = {
  bitcoin:        73.80 / LIQ_MCAP_TOTAL,
  ethereum:       13.15 / LIQ_MCAP_TOTAL,
  ripple:          4.07 / LIQ_MCAP_TOTAL,
  binancecoin:     4.00 / LIQ_MCAP_TOTAL,
  solana:          2.31 / LIQ_MCAP_TOTAL,
  hyperliquid:     0.46 / LIQ_MCAP_TOTAL,
  cardano:         0.44 / LIQ_MCAP_TOTAL,
  "bitcoin-cash":  0.43 / LIQ_MCAP_TOTAL,
  chainlink:       0.32 / LIQ_MCAP_TOTAL,
  zcash:           0.28 / LIQ_MCAP_TOTAL,
  litecoin:        0.21 / LIQ_MCAP_TOTAL,
  uniswap:         0.10 / LIQ_MCAP_TOTAL,
};

// Volume/liquidity-weighted — missing 1.36% (sui+aave+avalanche-2)
const LIQ_VOL_TOTAL = 98.65;
export const VOLUME_WEIGHTS: Record<string, number> = {
  bitcoin:        59.55 / LIQ_VOL_TOTAL,
  ethereum:       26.32 / LIQ_VOL_TOTAL,
  solana:          5.18 / LIQ_VOL_TOTAL,
  ripple:          3.33 / LIQ_VOL_TOTAL,
  binancecoin:     1.36 / LIQ_VOL_TOTAL,
  cardano:         0.62 / LIQ_VOL_TOTAL,
  zcash:           0.47 / LIQ_VOL_TOTAL,
  chainlink:       0.45 / LIQ_VOL_TOTAL,
  litecoin:        0.43 / LIQ_VOL_TOTAL,
  hyperliquid:     0.38 / LIQ_VOL_TOTAL,
  "bitcoin-cash":  0.31 / LIQ_VOL_TOTAL,
  uniswap:         0.25 / LIQ_VOL_TOTAL,
};

// 1/N equal-weight — 12 of 15 available
const LIQ_N = 12;
export const LIQUIDITY_WEIGHTS: Record<string, number> = Object.fromEntries(
  Object.keys(VOLUME_WEIGHTS).map((a) => [a, 1 / LIQ_N]),
);

// ETF (Min-Var) — liquidity universe — missing sui(1%) + aave(1.24%) → 97.76% available
const LIQ_ETF_TOTAL = 97.76;
export const LIQ_ETF_WEIGHTS: Record<string, number> = {
  bitcoin:        44.71 / LIQ_ETF_TOTAL,
  mstr:           15.00 / LIQ_ETF_TOTAL,
  coin:            8.01 / LIQ_ETF_TOTAL,
  hood:            6.99 / LIQ_ETF_TOTAL,
  binancecoin:     7.22 / LIQ_ETF_TOTAL,
  litecoin:        3.13 / LIQ_ETF_TOTAL,
  ripple:          2.85 / LIQ_ETF_TOTAL,
  ethereum:        2.44 / LIQ_ETF_TOTAL,
  hyperliquid:     1.78 / LIQ_ETF_TOTAL,
  solana:          1.50 / LIQ_ETF_TOTAL,
  chainlink:       1.40 / LIQ_ETF_TOTAL,
  cardano:         1.45 / LIQ_ETF_TOTAL,
  zcash:           1.28 / LIQ_ETF_TOTAL,
};

// Quality Factor — liquidity universe — missing sky(1.14%) → 98.86% available
const LIQ_QUALITY_TOTAL = 98.86;
export const LIQ_QUALITY_WEIGHTS: Record<string, number> = {
  bitcoin:        32.57 / LIQ_QUALITY_TOTAL,
  ethereum:       15.57 / LIQ_QUALITY_TOTAL,
  hood:            8.26 / LIQ_QUALITY_TOTAL,
  mstr:            7.36 / LIQ_QUALITY_TOTAL,
  coin:            7.25 / LIQ_QUALITY_TOTAL,
  solana:          6.22 / LIQ_QUALITY_TOTAL,
  crcl:            5.38 / LIQ_QUALITY_TOTAL,
  binancecoin:     5.36 / LIQ_QUALITY_TOTAL,
  hyperliquid:     3.01 / LIQ_QUALITY_TOTAL,
  chainlink:       2.25 / LIQ_QUALITY_TOTAL,
  zcash:           2.15 / LIQ_QUALITY_TOTAL,
  uniswap:         1.48 / LIQ_QUALITY_TOTAL,
  "ether-fi":      1.00 / LIQ_QUALITY_TOTAL,
  morpho:          1.00 / LIQ_QUALITY_TOTAL,
};

// Risk Factor — liquidity universe — missing sui(1%) + aave(1%) → 98.02% available
const LIQ_RISK_TOTAL = 98.02;
export const LIQ_RISK_WEIGHTS: Record<string, number> = {
  mstr:           17.64 / LIQ_RISK_TOTAL,
  coin:           15.07 / LIQ_RISK_TOTAL,
  hood:           14.55 / LIQ_RISK_TOTAL,
  bitcoin:        12.29 / LIQ_RISK_TOTAL,
  binancecoin:    12.00 / LIQ_RISK_TOTAL,
  litecoin:        6.47 / LIQ_RISK_TOTAL,
  ripple:          6.29 / LIQ_RISK_TOTAL,
  ethereum:        5.10 / LIQ_RISK_TOTAL,
  solana:          3.86 / LIQ_RISK_TOTAL,
  hyperliquid:     1.68 / LIQ_RISK_TOTAL,
  cardano:         1.07 / LIQ_RISK_TOTAL,
  zcash:           1.00 / LIQ_RISK_TOTAL,
  chainlink:       1.00 / LIQ_RISK_TOTAL,
};
