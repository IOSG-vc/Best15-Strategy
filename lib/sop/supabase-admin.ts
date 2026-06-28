import { createClient, type SupabaseClient } from "@supabase/supabase-js";

let _client: SupabaseClient | null = null;

export function sopSupabaseAdmin(): SupabaseClient {
  if (_client) return _client;
  const url = process.env.NEXT_PUBLIC_SOP_SUPABASE_URL;
  const serviceKey = process.env.SOP_SUPABASE_SERVICE_ROLE_KEY;
  if (!url) throw new Error("NEXT_PUBLIC_SOP_SUPABASE_URL not set");
  if (!serviceKey) throw new Error("SOP_SUPABASE_SERVICE_ROLE_KEY not set");
  _client = createClient(url, serviceKey, { auth: { persistSession: false } });
  return _client;
}
