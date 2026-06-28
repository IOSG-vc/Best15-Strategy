// Thin Google Sheets REST helpers used by /api/apply-suggestion.
// Direct fetch + JSON — no googleapis dependency. See lib/gauth.ts for token.

import { getSheetsAccessToken } from "./gauth";

const BASE = "https://sheets.googleapis.com/v4/spreadsheets";

async function sheetsFetch(path: string, init?: RequestInit): Promise<unknown> {
  const token = await getSheetsAccessToken();
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.headers || {}),
      authorization: `Bearer ${token}`,
      "content-type": "application/json",
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Sheets API ${res.status} ${init?.method || "GET"} ${path}: ${body}`);
  }
  return res.json();
}

export interface ReadRangeResp {
  range: string;
  majorDimension: string;
  values?: string[][];
}

export async function readRange(spreadsheetId: string, a1: string): Promise<ReadRangeResp> {
  return (await sheetsFetch(`/${spreadsheetId}/values/${encodeURIComponent(a1)}`)) as ReadRangeResp;
}

export async function writeCell(spreadsheetId: string, a1: string, value: string | number): Promise<void> {
  await sheetsFetch(
    `/${spreadsheetId}/values/${encodeURIComponent(a1)}?valueInputOption=USER_ENTERED`,
    {
      method: "PUT",
      body: JSON.stringify({ range: a1, majorDimension: "ROWS", values: [[String(value)]] }),
    }
  );
}

export async function appendRow(spreadsheetId: string, tabAndRange: string, row: (string | number)[]): Promise<void> {
  await sheetsFetch(
    `/${spreadsheetId}/values/${encodeURIComponent(tabAndRange)}:append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS`,
    {
      method: "POST",
      body: JSON.stringify({ range: tabAndRange, majorDimension: "ROWS", values: [row.map(String)] }),
    }
  );
}

interface SheetMeta { properties: { sheetId: number; title: string } }
interface SpreadsheetMeta { sheets: SheetMeta[] }

export async function listTabs(spreadsheetId: string): Promise<Array<{ id: number; title: string }>> {
  const meta = (await sheetsFetch(`/${spreadsheetId}?fields=sheets.properties`)) as SpreadsheetMeta;
  return meta.sheets.map((s) => ({ id: s.properties.sheetId, title: s.properties.title }));
}

export async function ensureTab(spreadsheetId: string, title: string, header?: string[]): Promise<number> {
  const tabs = await listTabs(spreadsheetId);
  const existing = tabs.find((t) => t.title === title);
  if (existing) return existing.id;
  const resp = (await sheetsFetch(`/${spreadsheetId}:batchUpdate`, {
    method: "POST",
    body: JSON.stringify({
      requests: [{ addSheet: { properties: { title } } }],
    }),
  })) as { replies: Array<{ addSheet: { properties: { sheetId: number } } }> };
  const sheetId = resp.replies[0].addSheet.properties.sheetId;
  if (header && header.length) {
    await appendRow(spreadsheetId, `${title}!A1`, header);
  }
  return sheetId;
}

// Apply a pink (#FFB6C1) background fill on a single cell. `row`/`col` are 0-indexed.
export async function pinkHighlight(
  spreadsheetId: string,
  sheetId: number,
  rowIdx: number,
  colIdx: number,
): Promise<void> {
  await sheetsFetch(`/${spreadsheetId}:batchUpdate`, {
    method: "POST",
    body: JSON.stringify({
      requests: [{
        repeatCell: {
          range: {
            sheetId,
            startRowIndex: rowIdx,
            endRowIndex: rowIdx + 1,
            startColumnIndex: colIdx,
            endColumnIndex: colIdx + 1,
          },
          cell: { userEnteredFormat: { backgroundColor: { red: 1.0, green: 0.7137, blue: 0.7569 } } },
          fields: "userEnteredFormat.backgroundColor",
        },
      }],
    }),
  });
}
