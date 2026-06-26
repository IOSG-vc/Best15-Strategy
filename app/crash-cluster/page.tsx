import { loadCrashClusterData } from "@/lib/loadCrashClusterData";
import CrashClusterDashboard from "@/components/CrashClusterDashboard";

export const dynamic = "force-static";

export default function CrashClusterPage() {
  const data = loadCrashClusterData();
  return <CrashClusterDashboard data={data} />;
}
