import { loadValuations } from "@/lib/loadValuations";
import ValuationDashboard from "@/components/ValuationDashboard";

export const dynamic = "force-static";

export default function ValuationPage() {
  const data = loadValuations();
  return <ValuationDashboard data={data} />;
}
