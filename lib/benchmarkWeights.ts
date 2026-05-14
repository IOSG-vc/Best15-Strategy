// ── 1/N Equal-Weight Benchmarks ──────────────────────────────────────────────

// MCAP Universe — 12 assets (stellar, no hyperliquid)
const MCAP_UNIV_ASSETS = [
  "bitcoin", "ethereum", "binancecoin", "solana", "ripple",
  "cardano", "chainlink", "stellar", "uniswap", "litecoin", "zcash", "bitcoin-cash",
] as const;
export const MCAP_1N_WEIGHTS: Record<string, number> = Object.fromEntries(
  MCAP_UNIV_ASSETS.map((a) => [a, 1 / MCAP_UNIV_ASSETS.length]),
);

// Liquidity Universe — 12 assets (hyperliquid instead of stellar)
const LIQ_UNIV_ASSETS = [
  "bitcoin", "ethereum", "solana", "ripple", "binancecoin",
  "cardano", "zcash", "chainlink", "litecoin", "hyperliquid", "bitcoin-cash", "uniswap",
] as const;
export const LIQ_1N_WEIGHTS: Record<string, number> = Object.fromEntries(
  LIQ_UNIV_ASSETS.map((a) => [a, 1 / LIQ_UNIV_ASSETS.length]),
);

// ── ETF Family — MCAP Universe ────────────────────────────────────────────────
// All 15 assets available in performance data (coin/hood/mstr/bnb/btc/bch/ada/link/eth/hype/ltc/xrp/sol/xlm/zec)

export const ETF_MCAP_BASE: Record<string, number> = {
  coin:           0.053888433455917616,
  hood:           0.063074819208773100,
  mstr:           0.063275537408127440,
  binancecoin:    0.075230757097908230,
  bitcoin:        0.322987801800353500,
  "bitcoin-cash": 0.024562486325924280,
  cardano:        0.024928063442610296,
  chainlink:      0.021259672153624957,
  ethereum:       0.136349473062585050,
  hyperliquid:    0.025413554821193365,
  litecoin:       0.017043021040248473,
  ripple:         0.075878232707398960,
  solana:         0.057138179059794215,
  stellar:        0.018982351545994054,
  zcash:          0.019987616869546528,
};

export const ETF_MCAP_MINVAR: Record<string, number> = {
  coin:           0.081865013533303650,
  hood:           0.068134986466696370,
  mstr:           0.15,
  binancecoin:    0.037871209807392380,
  bitcoin:        0.451065913563275360,
  "bitcoin-cash": 0.049962674921199754,
  cardano:        0.011377310836608768,
  chainlink:      0.012169623114603666,
  ethereum:       0.020977455787118075,
  hyperliquid:    0.026314617422729558,
  litecoin:       0.023640093676515550,
  ripple:         0.027956630649606573,
  solana:         0.011985125277182946,
  stellar:        0.016679344943767420,
  zcash:          0.01,
};

export const ETF_MCAP_PLUS_LIQ: Record<string, number> = {
  coin:           0.0816,
  hood:           0.0684,
  mstr:           0.15,
  binancecoin:    0.0526,
  bitcoin:        0.4511,
  "bitcoin-cash": 0.0358,
  cardano:        0.0123,
  chainlink:      0.0126,
  ethereum:       0.021,
  hyperliquid:    0.0218,
  litecoin:       0.0252,
  ripple:         0.0279,
  solana:         0.0132,
  stellar:        0.0163,
  zcash:          0.0101,
};

export const ETF_MCAP_PLUS_TECH: Record<string, number> = {
  coin:           0.0784,
  hood:           0.0641,
  mstr:           0.15,
  binancecoin:    0.0349,
  bitcoin:        0.456,
  "bitcoin-cash": 0.0814,
  cardano:        0.0105,
  chainlink:      0.0107,
  ethereum:       0.0212,
  hyperliquid:    0.014,
  litecoin:       0.0224,
  ripple:         0.0229,
  solana:         0.0109,
  stellar:        0.0118,
  zcash:          0.0108,
};

// ── ETF Family — Liquidity Universe ──────────────────────────────────────────
// Missing: aave, sui → computeWeightedSeries normalizes by available weight sum

export const ETF_LIQ_BASE: Record<string, number> = {
  coin:        0.054880845506078760,
  hood:        0.064236408192348370,
  mstr:        0.064440822827968360,
  aave:        0.009989367161618150, // not in performance data
  binancecoin: 0.076616210433600100,
  bitcoin:     0.328935961099211970,
  cardano:     0.025387139889281644,
  chainlink:   0.021651191325266717,
  ethereum:    0.138860491687966400,
  hyperliquid: 0.025881572101053886,
  litecoin:    0.017356886156875560,
  ripple:      0.077275609985871060,
  solana:      0.058190438585385940,
  sui:         0.015941345239178130, // not in performance data
  zcash:       0.020355709808295038,
};

export const ETF_LIQ_MINVAR: Record<string, number> = {
  coin:        0.080034232911397250,
  hood:        0.069965767088602750,
  mstr:        0.15,
  aave:        0.013780437129233016, // not in performance data
  binancecoin: 0.055389203666261480,
  bitcoin:     0.443846746901235930,
  cardano:     0.014064560658367947,
  chainlink:   0.015201951141485206,
  ethereum:    0.024155706673001456,
  hyperliquid: 0.032059829657265100,
  litecoin:    0.031690672892099480,
  ripple:      0.031997546425762580,
  solana:      0.015144717018582636,
  sui:         0.010603805326004318, // not in performance data
  zcash:       0.012064822510700965,
};

export const ETF_LIQ_PLUS_LIQ: Record<string, number> = {
  coin:        0.0802,
  hood:        0.0698,
  mstr:        0.15,
  aave:        0.0129, // not in performance data
  binancecoin: 0.0676,
  bitcoin:     0.4436,
  cardano:     0.0147,
  chainlink:   0.0148,
  ethereum:    0.0243,
  hyperliquid: 0.0223,
  litecoin:    0.0291,
  ripple:      0.0321,
  solana:      0.016,
  sui:         0.0106, // not in performance data
  zcash:       0.0119,
};

export const ETF_LIQ_PLUS_TECH: Record<string, number> = {
  coin:        0.0801,
  hood:        0.0699,
  mstr:        0.15,
  aave:        0.0124, // not in performance data
  binancecoin: 0.0722,
  bitcoin:     0.4471,
  cardano:     0.0145,
  chainlink:   0.014,
  ethereum:    0.0244,
  hyperliquid: 0.0178,
  litecoin:    0.0313,
  ripple:      0.0285,
  solana:      0.015,
  sui:         0.01,   // not in performance data
  zcash:       0.0128,
};

// ── PF Family — same weights for MCAP and Liquidity universes ─────────────────
// sky not in performance data — included so it shows as grayed-out row

export const PF_BASE: Record<string, number> = {
  coin:        0.08757268597546156,
  crcl:        0.059303186127860626,
  hood:        0.10185740032479675,
  mstr:        0.08822011453021987,
  bitcoin:     0.3000631959513975,
  chainlink:   0.020390060962174616,
  "ether-fi":  5.957417841171345e-05,
  ethereum:    0.1902274198341007,
  hyperliquid: 0.039440623093709826,
  morpho:      0.009252812391341122,
  sky:         0.012493262160665595, // not in performance data
  solana:      0.061612752488162954,
  uniswap:     0.017592722531619715,
  zcash:       0.01191418945007743,
};

export const PF_PLUS_SIZE: Record<string, number> = {
  coin:        0.08680987461534564,
  crcl:        0.03430907175848295,
  hood:        0.07888105362617134,
  mstr:        0.1,
  binancecoin: 0.1,
  bitcoin:     0.38270966421197555,
  chainlink:   0.015483205526759624,
  "ether-fi":  0.012192121864043465,
  ethereum:    0.017716582812277455,
  hyperliquid: 0.029777748336373675,
  morpho:      0.01793627675498861,
  sky:         0.08485709229527819,  // not in performance data
  solana:      0.015181037684936335,
  uniswap:     0.014080329352504053,
  zcash:       0.010065941160863068,
};

export const PF_PLUS_LIQ: Record<string, number> = {
  coin:        0.08852873995463839,
  crcl:        0.035497709878511016,
  hood:        0.07597355016685058,
  mstr:        0.1,
  binancecoin: 0.1,
  bitcoin:     0.43738160953774996,
  chainlink:   0.01527002993665845,
  "ether-fi":  0.011270247323173156,
  ethereum:    0.018077938604765982,
  hyperliquid: 0.025366462758376392,
  morpho:      0.01479724091008594,
  sky:         0.039155045993170136, // not in performance data
  solana:      0.015408688945664183,
  uniswap:     0.01327273599035586,
  zcash:       0.01,
};

export const PF_PLUS_TECH: Record<string, number> = {
  coin:        0.08797947665665058,
  crcl:        0.03570226385946558,
  hood:        0.0763182594838838,
  mstr:        0.1,
  binancecoin: 0.06601662199897564,
  bitcoin:     0.5,
  chainlink:   0.012433858891424267,
  "ether-fi":  0.010000000000000002,
  ethereum:    0.013175243770316016,
  hyperliquid: 0.01572945749417817,
  morpho:      0.016871691968353565,
  sky:         0.029616481890742147, // not in performance data
  solana:      0.012476985994446868,
  uniswap:     0.013639962838981555,
  zcash:       0.010039695152581735,
};

export const PF_PLUS_QUALITY: Record<string, number> = {
  coin:        0.07387577287449308,
  crcl:        0.046352086735463316,
  hood:        0.0688597984866872,
  mstr:        0.09453899979123273,
  binancecoin: 0.017016208373020272,
  bitcoin:     0.4726563648994512,
  chainlink:   0.015971929044250842,
  "ether-fi":  0.01,
  ethereum:    0.03674384446697792,
  hyperliquid: 0.06338722375216412,
  morpho:      0.01709448904988038,
  sky:         0.03479338442298111,  // not in performance data
  solana:      0.017767797222247445,
  uniswap:     0.020942100881150425,
  zcash:       0.01,
};
