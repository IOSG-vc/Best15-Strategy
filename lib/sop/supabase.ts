import { createClient, type SupabaseClient } from "@supabase/supabase-js";

let _client: SupabaseClient | null = null;

export function sopSupabase(): SupabaseClient {
  if (_client) return _client;
  const url = process.env.NEXT_PUBLIC_SOP_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SOP_SUPABASE_ANON_KEY;
  if (!url) throw new Error("NEXT_PUBLIC_SOP_SUPABASE_URL not set");
  if (!anonKey) throw new Error("NEXT_PUBLIC_SOP_SUPABASE_ANON_KEY not set");
  _client = createClient(url, anonKey, { auth: { persistSession: false } });
  return _client;
}
