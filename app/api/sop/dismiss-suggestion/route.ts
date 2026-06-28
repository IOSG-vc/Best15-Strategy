import { NextRequest, NextResponse } from "next/server";
import { sopSupabaseAdmin } from "@/lib/sop/supabase-admin";
import type { SubDim } from "@/lib/sop/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface ReqBody { date: string; token_id: string; sub_dim: SubDim }

export async function POST(req: NextRequest): Promise<NextResponse> {
  if (!process.env.SOP_SUPABASE_SERVICE_ROLE_KEY) {
    return NextResponse.json({ ok: false, error: "SOP_SUPABASE_SERVICE_ROLE_KEY not set" }, { status: 500 });
  }
  let body: ReqBody;
  try { body = (await req.json()) as ReqBody; }
  catch { return NextResponse.json({ ok: false, error: "invalid json" }, { status: 400 }); }

  const { date, token_id, sub_dim } = body;
  if (!date || !token_id || !sub_dim) {
    return NextResponse.json({ ok: false, error: "missing date / token_id / sub_dim" }, { status: 400 });
  }

  const upd = await sopSupabaseAdmin()
    .from("suggestions")
    .update({ status: "dismissed", applied_at: new Date().toISOString() })
    .eq("date", date).eq("token_id", token_id).eq("sub_dim", sub_dim);

  if (upd.error) {
    return NextResponse.json({ ok: false, error: upd.error.message }, { status: 500 });
  }
  return NextResponse.json({ ok: true });
}
