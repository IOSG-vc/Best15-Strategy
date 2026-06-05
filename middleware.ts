import { NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow the login page and the auth API through without checking
  if (
    pathname.startsWith("/private-fund/login") ||
    pathname.startsWith("/api/auth")
  ) {
    return NextResponse.next();
  }

  const token = request.cookies.get("pf_auth")?.value;
  const expected = process.env.PRIVATE_FUND_TOKEN;

  if (!token || !expected || token !== expected) {
    const url = new URL("/private-fund/login", request.url);
    url.searchParams.set("from", pathname);
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/private-fund/:path*"],
};
