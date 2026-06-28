import { NextResponse } from "next/server";
import { sopSupabase } from "@/lib/sop/supabase";

export const dynamic = "force-dynamic";

export async function GET() {
  const { data, error } = await sopSupabase()
    .from("digests")
    .select("date, item_count, high_count, notable_count")
    .order("date", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ dates: data || [] });
}
