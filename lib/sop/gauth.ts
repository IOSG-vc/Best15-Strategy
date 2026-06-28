// Minimal Google service-account JWT → OAuth access token, no extra deps.
// Uses Node's built-in crypto.createSign('RSA-SHA256') so we don't pull in googleapis (~50MB).
//
// Env vars (set in Vercel):
//   GOOGLE_SERVICE_ACCOUNT_JSON — full SA key JSON, either raw or base64.
//
// Token cached in-module for ~50min so multiple route invocations within a
// warm lambda instance don't re-mint.

import { createSign } from "node:crypto";

interface ServiceAccountKey {
  client_email: string;
  private_key: string;
  token_uri: string;
}

interface CachedToken {
  access_token: string;
  expires_at: number; // unix seconds
}

let cached: CachedToken | null = null;
let parsedKey: ServiceAccountKey | null = null;

function parseSAKey(): ServiceAccountKey {
  if (parsedKey) return parsedKey;
  const raw = process.env.SOP_GOOGLE_SERVICE_ACCOUNT_JSON;
  if (!raw) throw new Error("SOP_GOOGLE_SERVICE_ACCOUNT_JSON not set");
  // Accept either raw JSON or base64-encoded JSON (Vercel UI sometimes munges newlines)
  let txt = raw.trim();
  if (!txt.startsWith("{")) {
    try { txt = Buffer.from(txt, "base64").toString("utf8"); }
    catch { throw new Error("GOOGLE_SERVICE_ACCOUNT_JSON is neither JSON nor base64"); }
  }
  const obj = JSON.parse(txt) as ServiceAccountKey;
  // Vercel env vars escape \n — un-escape if present
  if (obj.private_key.includes("\\n")) {
    obj.private_key = obj.private_key.replace(/\\n/g, "\n");
  }
  parsedKey = obj;
  return obj;
}

function b64url(input: Buffer | string): string {
  const buf = typeof input === "string" ? Buffer.from(input) : input;
  return buf.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function mintAccessToken(scopes: string[]): Promise<CachedToken> {
  const key = parseSAKey();
  const now = Math.floor(Date.now() / 1000);
  const exp = now + 3600;
  const header = b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const claim = b64url(JSON.stringify({
    iss: key.client_email,
    scope: scopes.join(" "),
    aud: key.token_uri || "https://oauth2.googleapis.com/token",
    iat: now,
    exp,
  }));
  const signing = `${header}.${claim}`;
  const signer = createSign("RSA-SHA256");
  signer.update(signing);
  const sig = b64url(signer.sign(key.private_key));
  const jwt = `${signing}.${sig}`;

  const res = await fetch(key.token_uri || "https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion: jwt,
    }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`google token mint failed: ${res.status} ${body}`);
  }
  const json = (await res.json()) as { access_token: string; expires_in: number };
  return { access_token: json.access_token, expires_at: now + json.expires_in - 60 };
}

export async function getSheetsAccessToken(): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  if (cached && cached.expires_at > now) return cached.access_token;
  cached = await mintAccessToken(["https://www.googleapis.com/auth/spreadsheets"]);
  return cached.access_token;
}
