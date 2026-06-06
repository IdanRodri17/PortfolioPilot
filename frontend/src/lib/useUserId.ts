"use client";

/**
 * useUserId — the session's user_id for client pages (V8b).
 *
 * Replaces the hardcoded `DEMO_USER = "idan_demo"` that every page carried
 * pre-auth. Middleware guarantees a session exists on any protected page, but
 * useSession() still resolves asynchronously on the client, so there is a brief
 * window where status === "loading" and we don't have the id yet. This hook
 * surfaces both so a page can hold its data fetch until the id is ready, rather
 * than firing a request with `undefined`.
 *
 * Returns:
 *   userId  — session.user.id once authenticated, else null (loading/unauth).
 *   loading — true while the session is still resolving.
 *
 * Pages should gate their effect on a non-null userId and show a light loading
 * state while `loading` is true.
 *
 * Versioning:
 *   V8b: this file.
 */

import { useSession } from "next-auth/react";

export function useUserId(): { userId: string | null; loading: boolean } {
  const { data: session, status } = useSession();
  return {
    userId: session?.user?.id ?? null,
    loading: status === "loading",
  };
}
