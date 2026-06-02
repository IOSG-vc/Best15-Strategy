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
      allStrategies={perfData.strategies}
      positions={positions}
      lastUpdated={perfData.lastUpdated}
      latestRebalanceDate={perfData.latestRebalanceDate}
    />
  );
}
