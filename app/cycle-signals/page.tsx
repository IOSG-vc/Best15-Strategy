import { loadCycleData } from "@/lib/loadCycleData";
import { loadCrashClusterData } from "@/lib/loadCrashClusterData";
import CycleSignalDashboard from "@/components/CycleSignalDashboard";

export const dynamic = "force-static";

export default function CycleSignalsPage() {
  const data = loadCycleData();
  const crashData = loadCrashClusterData();
  return <CycleSignalDashboard data={data} crashClusterData={crashData} />;
}
