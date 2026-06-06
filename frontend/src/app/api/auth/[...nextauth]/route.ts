/**
 * NextAuth v5 catch-all route — handles all /api/auth/* requests
 * (signin, signout, session, csrf, callback).
 *
 * In v5 this file is deliberately tiny: the real config lives in lib/auth.ts,
 * which exports `handlers` (an object with GET and POST). We destructure those
 * two methods out and re-export them — this is what the App Router needs a
 * route file to expose. It replaces v4's pages/api/auth/[...nextauth].ts.
 *
 * Note: this is the FRONTEND's /api/auth/* namespace (NextAuth's own routes).
 * It does NOT collide with the BACKEND's POST /api/auth/verify — that lives on
 * the FastAPI server (:8000), a different origin. authorize() in lib/auth.ts
 * calls the backend one; the browser hits these.
 *
 * Versioning:
 *   V8a: this file.
 */

import { handlers } from "@/lib/auth";

export const { GET, POST } = handlers;
