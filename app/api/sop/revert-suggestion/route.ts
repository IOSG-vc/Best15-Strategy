import { NextRequest, NextResponse } from "next/server";
import { sopSupabaseAdmin } from "@/lib/sop/supabase-admin";
import { readRange, writeCell, ensureTab, appendRow } from "@/lib/sop/sheets";
import { mappingFor, TOKEN_LOOKUP_COLUMN, DATA_FIRST_ROW } from "@/lib/sop/subdim-mapping";
import type { SubDim } from "@/lib/sop/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const START_UNIVERSE_ID  = process.env.SOP_START_UNIVERSE_SHEET_ID!;
const CHANGE_LOG_ID      = process.env.SOP_CHANGE_LOG_SHEET_ID!;
const START_UNIVERSE_TAB = process.env.SOP_START_UNIVERSE_TAB || "start_universe";

interface ReqBody { date: string; token_id: string; sub_dim: SubDim }

function bad(status: number, msg: string, extra?: Record<string, unknown>): NextResponse {
  return NextResponse.json({ ok: false, error: msg, ...extra }, { status });
}
function todayDateStr() { return new Date().toISOString().slice(0, 10); }

export async function POST(req: NextRequest): Promise<NextResponse> {
  let body: ReqBody;
  try { body = (await req.json()) as ReqBody; }
  catch { return bad(400, "invalid json"); }

  const { date, token_id, sub_dim } = body;
  if (!date || !token_id || !sub_dim) return bad(400, "missing date / token_id / sub_dim");

  const sugRes = await sopSupabaseAdmin()
    .from("suggestions").select("*")
    .eq("date", date).eq("token_id", token_id).eq("sub_dim", sub_dim).maybeSingle();
  if (sugRes.error) return bad(500, `suggestion lookup failed: ${sugRes.error.message}`);
  if (!sugRes.data) return bad(404, "suggestion not found");
  const suggestion = sugRes.data;

  if (suggestion.status === "open") return bad(409, "suggestion already open");

  if (suggestion.status === "dismissed") {
    const flip = await sopSupabaseAdmin()
      .from("suggestions").update({ status: "open", applied_at: null })
      .eq("date", date).eq("token_id", token_id).eq("sub_dim", sub_dim);
    if (flip.error) return bad(500, `unreject failed: ${flip.error.message}`);
    return NextResponse.json({ ok: true, reverted_from: "dismissed", sheet_touched: false });
  }

  if (!process.env.SOP_START_UNIVERSE_SHEET_ID || !process.env.SOP_GOOGLE_SERVICE_ACCOUNT_JSON) {
    return bad(500, "sheets env not configured");
  }

  const chRes = await sopSupabaseAdmin()
    .from("changelog").select("*")
    .eq("date", date).eq("token_id", token_id).eq("sub_dim", sub_dim)
    .order("applied_at", { ascending: false }).limit(1).maybeSingle();
  if (chRes.error) return bad(500, `changelog lookup failed: ${chRes.error.message}`);
  if (!chRes.data) return bad(404, "no changelog row found — cannot revert sheet");
  const prev = chRes.data;

  const oldValue = prev.old_value;
  const newValue = prev.new_value;
  if (oldValue === null || oldValue === undefined) return bad(409, "previous old_value was null");

  const m = mappingFor(sub_dim);
  let absoluteRowNum: number;
  try {
    const colLookup = await readRange(
      START_UNIVERSE_ID,
      `${START_UNIVERSE_TAB}!${TOKEN_LOOKUP_COLUMN}${DATA_FIRST_ROW}:${TOKEN_LOOKUP_COLUMN}500`,
    );
    const rows = colLookup.values || [];
    const offset = rows.findIndex(r => (r[0] || "").trim().toLowerCase() === token_id.toLowerCase());
    if (offset < 0) return bad(404, `token_id "${token_id}" not in Start Universe`);
    absoluteRowNum = DATA_FIRST_ROW + offset;
  } catch (e) { return bad(502, `Start Universe read failed: ${(e as Error).message}`); }

  const targetCell = `${START_UNIVERSE_TAB}!${m.column}${absoluteRowNum}`;
  try { await writeCell(START_UNIVERSE_ID, targetCell, oldValue); }
  catch (e) { return bad(502, `Start Universe revert write failed: ${(e as Error).message}`); }

  let sheetSyncError: string | null = null;
  try {
    const todayTab = todayDateStr();
    await ensureTab(CHANGE_LOG_ID, todayTab, ["Timestamp", "Token", "Field Modified", "Old Value", "New Value", "Delta", "Reason"]);
    const ts = new Date().toISOString().replace("T", " ").slice(0, 16);
    await appendRow(CHANGE_LOG_ID, `${todayTab}!A1`, [
      ts, token_id, m.label, newValue, oldValue, -(prev.delta ?? 0),
      `[REVERT] of ${prev.id} — restored ${sub_dim} to ${oldValue}`,
    ]);
  } catch (e) { sheetSyncError = (e as Error).message; }

  const ins = await sopSupabaseAdmin().from("changelog").insert({
    date, token_id, sub_dim, old_value: newValue, new_value: oldValue, delta: -(prev.delta ?? 0),
    reason: `[REVERT] of changelog row ${prev.id}`,
    suggestion_ref: { reverted_from_changelog_id: prev.id, reverted_at: new Date().toISOString() },
    applied_by: "web-revert-button",
    sheet_sync_status: sheetSyncError ? "partial" : "ok",
    sheet_sync_error: sheetSyncError,
  });
  if (ins.error) return bad(500, `revert changelog insert failed: ${ins.error.message}`);

  const flip = await sopSupabaseAdmin()
    .from("suggestions").update({ status: "open", applied_at: null })
    .eq("date", date).eq("token_id", token_id).eq("sub_dim", sub_dim);
  if (flip.error) {
    return NextResponse.json({
      ok: true, warning: `status flip failed but sheet reverted: ${flip.error.message}`,
      cell: targetCell, old: newValue, new: oldValue,
    });
  }

  return NextResponse.json({
    ok: true, reverted_from: "applied", sheet_touched: true,
    cell: targetCell, old: newValue, new: oldValue, sheet_sync_error: sheetSyncError,
  });
}
