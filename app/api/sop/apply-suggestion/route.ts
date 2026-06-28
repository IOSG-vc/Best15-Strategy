import { NextRequest, NextResponse } from "next/server";
import { sopSupabaseAdmin } from "@/lib/sop/supabase-admin";
import { readRange, writeCell, ensureTab, appendRow, listTabs, pinkHighlight } from "@/lib/sop/sheets";
import { mappingFor, colLetterToIndex, TOKEN_LOOKUP_COLUMN, DATA_FIRST_ROW } from "@/lib/sop/subdim-mapping";
import type { SubDim, Suggestion } from "@/lib/sop/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const START_UNIVERSE_ID  = process.env.SOP_START_UNIVERSE_SHEET_ID!;
const CHANGE_LOG_ID      = process.env.SOP_CHANGE_LOG_SHEET_ID!;
const START_UNIVERSE_TAB = process.env.SOP_START_UNIVERSE_TAB || "start_universe";

const VALID_SUBDIMS: SubDim[] = [
  "alignment", "cogs", "distribution", "blockworks_transparency",
  "liquidity", "tam_pure", "catalyst", "market_leadership", "moat", "leadership",
];

interface ReqBody {
  date: string; token_id: string; sub_dim: SubDim;
  new_subdim_value: number; reason?: string; applied_by?: string;
}

function todayDateStr() { return new Date().toISOString().slice(0, 10); }
function bad(status: number, msg: string, extra?: Record<string, unknown>): NextResponse {
  return NextResponse.json({ ok: false, error: msg, ...extra }, { status });
}

export async function POST(req: NextRequest): Promise<NextResponse> {
  for (const v of ["SOP_START_UNIVERSE_SHEET_ID", "SOP_CHANGE_LOG_SHEET_ID", "SOP_GOOGLE_SERVICE_ACCOUNT_JSON", "SOP_SUPABASE_SERVICE_ROLE_KEY"]) {
    if (!process.env[v]) return bad(500, `env ${v} not set`);
  }

  let body: ReqBody;
  try { body = (await req.json()) as ReqBody; }
  catch { return bad(400, "invalid json"); }

  const { date, token_id, sub_dim, new_subdim_value } = body;
  if (!date || !token_id || !sub_dim || typeof new_subdim_value !== "number") {
    return bad(400, "missing required fields");
  }
  if (!VALID_SUBDIMS.includes(sub_dim)) return bad(400, `invalid sub_dim: ${sub_dim}`);
  if (new_subdim_value < -1 || new_subdim_value > 5) return bad(400, "new_subdim_value out of [-1, 5]");

  const m = mappingFor(sub_dim);

  const sugRes = await sopSupabaseAdmin()
    .from("suggestions").select("*")
    .eq("date", date).eq("token_id", token_id).eq("sub_dim", sub_dim).maybeSingle();
  if (sugRes.error) return bad(500, `suggestion lookup failed: ${sugRes.error.message}`);
  if (!sugRes.data)  return bad(404, "suggestion not found");
  const suggestion = sugRes.data as Suggestion;

  let absoluteRowNum: number;
  let oldValue: number | null;
  try {
    const colD = await readRange(
      START_UNIVERSE_ID,
      `${START_UNIVERSE_TAB}!${TOKEN_LOOKUP_COLUMN}${DATA_FIRST_ROW}:${TOKEN_LOOKUP_COLUMN}500`,
    );
    const rows = colD.values || [];
    const offset = rows.findIndex(r => (r[0] || "").trim().toLowerCase() === token_id.toLowerCase());
    if (offset < 0) return bad(404, `token_id "${token_id}" not in Start Universe`);
    absoluteRowNum = DATA_FIRST_ROW + offset;
    const curRead = await readRange(START_UNIVERSE_ID, `${START_UNIVERSE_TAB}!${m.column}${absoluteRowNum}`);
    const raw = curRead.values?.[0]?.[0];
    oldValue = raw === undefined || raw === "" ? null : parseFloat(String(raw));
    if (oldValue !== null && Number.isNaN(oldValue)) return bad(500, `cell not numeric: "${raw}"`);
  } catch (e) { return bad(502, `Start Universe read failed: ${(e as Error).message}`); }

  const delta = oldValue === null ? null : +(new_subdim_value - oldValue).toFixed(2);
  const targetCell = `${START_UNIVERSE_TAB}!${m.column}${absoluteRowNum}`;

  try { await writeCell(START_UNIVERSE_ID, targetCell, new_subdim_value); }
  catch (e) { return bad(502, `Start Universe write failed: ${(e as Error).message}`); }

  let fillError: string | null = null;
  try {
    const tabs = await listTabs(START_UNIVERSE_ID);
    const tab = tabs.find(t => t.title === START_UNIVERSE_TAB);
    if (tab) await pinkHighlight(START_UNIVERSE_ID, tab.id, absoluteRowNum - 1, colLetterToIndex(m.column));
  } catch (e) { fillError = (e as Error).message; }

  const todayTab = todayDateStr();
  const reasonText = (body.reason || suggestion.summary || "applied via website").trim();
  let sheetSyncStatus: "ok" | "failed" | "partial" = "ok";
  let sheetSyncError: string | null = null;
  try {
    await ensureTab(CHANGE_LOG_ID, todayTab, ["Timestamp", "Token", "Field Modified", "Old Value", "New Value", "Delta", "Reason"]);
    const ts = new Date().toISOString().replace("T", " ").slice(0, 16);
    await appendRow(CHANGE_LOG_ID, `${todayTab}!A1`, [
      ts, token_id, m.label, oldValue === null ? "" : oldValue, new_subdim_value, delta === null ? "" : delta, reasonText,
    ]);
  } catch (e) { sheetSyncStatus = "partial"; sheetSyncError = (e as Error).message; }
  if (fillError && sheetSyncStatus === "ok") { sheetSyncStatus = "partial"; sheetSyncError = `fill: ${fillError}`; }

  const changelogIns = await sopSupabaseAdmin().from("changelog").insert({
    date, token_id, sub_dim, old_value: oldValue, new_value: new_subdim_value, delta,
    reason: reasonText, suggestion_ref: suggestion,
    applied_by: body.applied_by || "web-apply-button",
    sheet_sync_status: sheetSyncStatus, sheet_sync_error: sheetSyncError,
  });
  if (changelogIns.error) return bad(500, `changelog insert failed: ${changelogIns.error.message}`, { sheet_write_status: "ok" });

  const statusUpdate = await sopSupabaseAdmin()
    .from("suggestions").update({ status: "applied", applied_at: new Date().toISOString() })
    .eq("date", date).eq("token_id", token_id).eq("sub_dim", sub_dim);
  if (statusUpdate.error) {
    return NextResponse.json({
      ok: true, warning: `status flip failed: ${statusUpdate.error.message}`,
      cell: targetCell, label: m.label, old_value: oldValue, new_value: new_subdim_value, delta,
      sheet_sync_status: sheetSyncStatus, sheet_sync_error: sheetSyncError,
    });
  }

  return NextResponse.json({
    ok: true, cell: targetCell, label: m.label, sub_dim,
    old_value: oldValue, new_value: new_subdim_value, delta,
    sheet_sync_status: sheetSyncStatus, sheet_sync_error: sheetSyncError,
  });
}
