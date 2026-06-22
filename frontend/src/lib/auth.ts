/**
 * Auth.js v5 (NextAuth beta) configuration — credential auth for V8a.
 *
 * Exports the four things v5 hands back from NextAuth({...}):
 *   - handlers : the GET/POST route handlers, re-exported by the [...nextauth] route
 *   - signIn   : programmatic sign-in (used by the /login form in V8a step 4)
 *   - signOut  : programmatic sign-out (used by the dashboard logout button in V8b)
 *   - auth     : the universal session getter (server components, middleware, route handlers)
 *
 * No database adapter. Unlike the typical v5 tutorial (Prisma/Drizzle adapter),
 * our "data access" is the FastAPI backend: authorize() POSTs the credentials to
 * POST /api/auth/verify, which does the bcrypt check in Python and returns the
 * user identity. The frontend never touches Postgres or sees the password hash.
 *
 * Session strategy is JWT (not "database") — required when there's no adapter,
 * and it's what lets every API call read user_id off the session without a
 * round-trip. The jwt callback stashes user_id into the token on sign-in; the
 * session callback copies it onto session.user.id for the client.
 *
 * Versioning:
 *   V8a: Credentials provider + JWT session carrying user_id.
 */

import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL;
// authorize() runs server-side. In Docker the backend is not reachable on
// localhost, so allow an internal base-URL override (compose sets this to
// http://backend:8000). On host dev it's unset and falls back to the public
// localhost base, so nothing changes outside containers.
const SERVER_API_BASE = process.env.INTERNAL_API_BASE_URL ?? API_BASE;

export const { handlers, signIn, signOut, auth } = NextAuth({
  session: { strategy: "jwt" },

  // Custom sign-in page (built in V8a step 4). Without this, v5 renders its
  // own default page; we want our dark-fintech /login instead.
  pages: {
    signIn: "/login",
  },

  providers: [
    Credentials({
      // The shape of the fields the default sign-in form would render. We use
      // our own /login page, but these still document the expected inputs.
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },

      /**
       * Verify credentials against the backend. Returning a user object signs
       * the user in; returning null fails the attempt (NextAuth surfaces a
       * generic CredentialsSignin error — it never reveals which field was wrong).
       */
      async authorize(credentials) {
        const email = credentials?.email as string | undefined;
        const password = credentials?.password as string | undefined;
        if (!email || !password) return null;

        try {
          const res = await fetch(`${SERVER_API_BASE}/api/auth/verify`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password }),
          });

          if (!res.ok) {
            // 401 from the backend = bad credentials. Any other non-2xx is a
            // backend/transport problem; either way the login fails cleanly.
            return null;
          }

          const data = (await res.json()) as {
            user_id: string;
            name: string;
            email: string;
          };

          // The returned object becomes the `user` arg in the jwt callback.
          // `id` is NextAuth's canonical user identifier — we set it to the
          // backend's user_id so it flows straight into the token.
          return {
            id: data.user_id,
            name: data.name,
            email: data.email,
          };
        } catch {
          // Network error reaching the backend — treat as a failed login.
          return null;
        }
      },
    }),
  ],

  callbacks: {
    /**
     * Runs whenever a JWT is created or updated. On sign-in `user` is present
     * (the object authorize() returned); we copy its id onto the token so it
     * persists across requests. On later calls `user` is undefined and the
     * token already carries the id.
     */
    async jwt({ token, user }) {
      if (user) {
        token.id = user.id;
      }
      return token;
    },

    /**
     * Shapes the session object the client sees. We surface token.id as
     * session.user.id — the single value every downstream API call keys on,
     * replacing the hardcoded "idan_demo".
     */
    async session({ session, token }) {
      if (session.user && token.id) {
        session.user.id = token.id as string;
      }
      return session;
    },
  },
});
