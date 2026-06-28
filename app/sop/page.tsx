import { redirect } from "next/navigation";
import { sopSupabase } from "@/lib/sop/supabase";

export const dynamic = "force-dynamic";

export default async function SopIndexPage() {
  const { data, error } = await sopSupabase()
    .from("digests")
    .select("date")
    .order("date", { ascending: false })
    .limit(1);

  if (error || !data || data.length === 0) {
    redirect("/sop/empty");
  }
  redirect(`/sop/${data[0].date}`);
}
