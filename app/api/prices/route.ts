import { NextResponse } from "next/server";

const COINGECKO_IDS = [
  "bitcoin",
  "ethereum",
  "solana",
  "binancecoin",
  "hyperliquid",
  "chainlink",
  "zcash",
  "uniswap",
  "ether-fi",
  "ethena",
  "morpho",
];

const STOCK_TICKERS: Record<string, string> = {
  mstr: "MSTR",
  coin: "COIN",
  hood: "HOOD",
  crcl: "CRCL",
};

export const dynamic = "force-dynamic";

const CG_API_KEY = process.env.COINGECKO_API_KEY ?? "";
const CG_BASE = CG_API_KEY
  ? "https://pro-api.coingecko.com/api/v3"
  : "https://api.coingecko.com/api/v3";

export async function GET() {
  const prices: Record<string, number> = {};

  // Crypto — CoinGecko (Pro API when key is set, free otherwise)
  try {
    const res = await fetch(
      `${CG_BASE}/simple/price?ids=${COINGECKO_IDS.join(",")}&vs_currencies=usd`,
      {
        signal: AbortSignal.timeout(8000),
        headers: CG_API_KEY ? { "x-cg-pro-api-key": CG_API_KEY } : {},
      },
    );
    if (res.ok) {
      const data = (await res.json()) as Record<string, { usd: number }>;
      for (const [id, val] of Object.entries(data)) {
        prices[id] = val.usd;
      }
    }
  } catch {
    // CoinGecko unavailable — prices stay empty, client falls back to stale data
  }

  // Stocks — Yahoo Finance unofficial chart endpoint
  await Promise.all(
    Object.entries(STOCK_TICKERS).map(async ([id, ticker]) => {
      try {
        const res = await fetch(
          `https://query1.finance.yahoo.com/v8/finance/chart/${ticker}?interval=1d&range=1d`,
          {
            headers: { "User-Agent": "Mozilla/5.0" },
            signal: AbortSignal.timeout(8000),
          },
        );
        if (res.ok) {
          const data = (await res.json()) as {
            chart?: { result?: { meta?: { regularMarketPrice?: number } }[] };
          };
          const price = data?.chart?.result?.[0]?.meta?.regularMarketPrice;
          if (price) prices[id] = price;
        }
      } catch {
        // skip this ticker
      }
    }),
  );

  return NextResponse.json({ prices, timestamp: new Date().toISOString() });
}
