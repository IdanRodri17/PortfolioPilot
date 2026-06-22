/**
 * Route-protection middleware (V8a).
 *
 * In Auth.js v5 the `auth` export is also a middleware wrapper: it populates
 * req.auth with the session (or null) and lets us gate routes at the edge,
 * before the page renders. Unauthenticated requests to a protected route are
 * redirected to /login with a ?callbackUrl so the login page can send the user
 * back where they were headed.
 *
 * Why middleware over a per-page client guard: it runs before any page code, so
 * there's no flash of protected content and no duplicated guard in every page.
 * (A client-side guard remains the fallback if the edge runtime ever fights the
 * Credentials setup — but it doesn't here.)
 *
 * The matcher is the load-bearing part. It must NOT match:
 *   - /login            (the redirect target — matching it loops forever)
 *   - /api/auth/*        (NextAuth's own sign-in/session/callback routes)
 *   - Next internals + static files (_next, favicon, etc.)
 * Everything else requires a session.
 *
 * Versioning:
 *   V8a: this file.
 */

import { auth } from "@/lib/auth";

export default auth((req) => {
  const isLoggedIn = !!req.auth;
  const { pathname, search } = req.nextUrl;

  if (!isLoggedIn) {
    const loginUrl = new URL("/login", req.nextUrl.origin);
    loginUrl.searchParams.set("callbackUrl", pathname + search);
    return Response.redirect(loginUrl);
  }
  // Authenticated — let the request through.
});

export const config = {
  // Match everything EXCEPT the excluded paths. The negative lookahead keeps
  // /login, NextAuth's API routes, and static assets out of the guard so there
  // is no redirect loop and no auth check on public assets.
  matcher: [
    // V15a: /demo is a public guest route; /api/token self-guards (returns 401
    // without a session) so it's excluded too.
    // V15b: /r/* are public read-only shared reports.
    "/((?!api/auth|api/token|login|demo|r/|_next/static|_next/image|favicon.ico).*)",
  ],
};
