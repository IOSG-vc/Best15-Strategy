import { loadPerformanceData } from "@/lib/loadData";
import { loadPositionsData } from "@/lib/loadPositions";
import PrivateFundDashboard from "@/components/PrivateFundDashboard";

export const dynamic = "force-static";

export default function PrivateFundPage() {
  const perfData = loadPerformanceData();
  const positions = loadPositionsData();

  return (
    <PrivateFundDashboard
      privateData={perfData.strategies.private}
      btcData={perfData.assets.bitcoin}
      allAssets={perfData.assets}
      etfData={perfData.strategies.etf}
      qualityData={perfData.strategies.quality}
      riskData={perfData.strategies.risk}
      positions={positions}
      lastUpdated={perfData.lastUpdated}
      latestRebalanceDate={perfData.latestRebalanceDate}
    />
  );
}
