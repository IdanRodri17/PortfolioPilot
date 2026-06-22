/**
 * GET /api/token — mint a short-lived API token for the FastAPI backend (V9).
 *
 * Server-side route: reads the Auth.js session, and if the user is
 * authenticated, signs a small HS256 JWT { sub: user_id } with the shared
 * AUTH_SECRET. The browser sends this to the backend as a Bearer token (or, for
 * the EventSource SSE, as a query param); the backend verifies it with the same
 * secret and trusts the `sub` as the user_id.
 *
 * We sign with Node's built-in crypto (no new dependency). This is a SEPARATE
 * plain token, distinct from Auth.js's encrypted session cookie — the backend
 * never has to decrypt the session.
 */

import crypto from "crypto";
import { NextResponse } from "next/server";
import { auth } from "@/lib/auth";

export const runtime = "nodejs"; // needs node:crypto, not the edge runtime

const TOKEN_TTL_SECONDS = 300; // short-lived: refreshed by the client near expiry

function base64url(input: string): string {
  return Buffer.from(input).toString("base64url");
}

function signJwt(payload: Record<string, unknown>, secret: string): string {
  const header = base64url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const body = base64url(JSON.stringify(payload));
  const data = `${header}.${body}`;
  const signature = crypto
    .createHmac("sha256", secret)
    .update(data)
    .digest("base64url");
  return `${data}.${signature}`;
}

export async function GET() {
  const session = await auth();
  const userId = session?.user?.id;
  if (!userId) {
    return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  }

  const secret = process.env.AUTH_SECRET;
  if (!secret) {
    return NextResponse.json(
      { error: "Server auth is not configured" },
      { status: 500 },
    );
  }

  const now = Math.floor(Date.now() / 1000);
  const token = signJwt(
    { sub: userId, iat: now, exp: now + TOKEN_TTL_SECONDS },
    secret,
  );
  return NextResponse.json({ token });
}
