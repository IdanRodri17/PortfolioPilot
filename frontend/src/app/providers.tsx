"use client";

/**
 * Client-side providers wrapper (V8a).
 *
 * SessionProvider must run on the client and wrap any component tree that calls
 * useSession(). The root layout is a server component, so it can't host the
 * provider directly — this thin "use client" boundary does, and the layout
 * renders <Providers>{children}</Providers> around the app.
 *
 * SessionProvider makes the session available app-wide and keeps it fresh
 * (revalidating on focus/reconnect by default), so the dashboard, settings, and
 * every other page read the same session without each refetching it.
 *
 * Versioning:
 *   V8a: this file.
 */

import { SessionProvider } from "next-auth/react";

export function Providers({ children }: { children: React.ReactNode }) {
  return <SessionProvider>{children}</SessionProvider>;
}
