import { type NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "paritylens_session";

/**
 * Runs before a page is rendered. Sends visitors without a session cookie
 * to the login page, so they do not see a page skeleton first.
 *
 * This is a convenience, not the access check. A cookie being present
 * says nothing about it being valid; the backend verifies it on every
 * request, and the app layout redirects if that fails.
 */
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const signedIn = request.cookies.has(SESSION_COOKIE);

  if (pathname === "/") {
    return NextResponse.redirect(new URL(signedIn ? "/projects" : "/login", request.url));
  }
  if (!signedIn && pathname !== "/login") {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  // Everything except the API (forwarded to the backend) and static files.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
