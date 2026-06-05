import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const { password } = (await request.json()) as { password?: string };

  const correct = process.env.PRIVATE_FUND_PASSWORD;
  const token = process.env.PRIVATE_FUND_TOKEN;

  if (!correct || !token) {
    return NextResponse.json({ error: "Auth not configured" }, { status: 500 });
  }

  if (!password || password !== correct) {
    return NextResponse.json({ error: "Invalid password" }, { status: 401 });
  }

  const res = NextResponse.json({ ok: true });
  res.cookies.set("pf_auth", token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    maxAge: 60 * 60 * 24 * 30, // 30 days
    path: "/",
  });
  return res;
}

export async function DELETE() {
  const res = NextResponse.json({ ok: true });
  res.cookies.delete("pf_auth");
  return res;
}
