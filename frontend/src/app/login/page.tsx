"use client";

/**
 * /login — credential sign-in page (V8a).
 *
 * Calls NextAuth v5's client signIn("credentials", ...) with redirect:false so
 * we can show an inline error on failure instead of bouncing to the default
 * error page. On success we push to the dashboard (or to the ?callbackUrl the
 * middleware set when it bounced an unauthenticated user here).
 *
 * authorize() in lib/auth.ts returns null for any bad-credential case, which
 * surfaces here as result.error (a generic CredentialsSignin) — we never learn
 * (or reveal) whether it was the email or the password that was wrong.
 *
 * Theme matches the rest of the app: slate-950 canvas, emerald accent, rose for
 * errors, per-container explicit classes (pattern #29).
 *
 * Versioning:
 *   V8a: this file.
 */

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { signIn } from "next-auth/react";

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const callbackUrl = searchParams.get("callbackUrl") || "/";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    setError(null);
    setSubmitting(true);
    try {
      const result = await signIn("credentials", {
        email,
        password,
        redirect: false,
      });

      if (result?.error) {
        setError("Invalid email or password.");
        return;
      }

      // Success — go where the user was headed (or the dashboard).
      router.push(callbackUrl);
      router.refresh(); // re-fetch server state now that a session exists
    } catch {
      setError("Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  // Enter-to-submit without an HTML <form> (avoids the form-tag caveat and
  // keeps this a plain controlled component).
  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !submitting) handleSubmit();
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center px-6">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">
            Portfolio<span className="text-emerald-400">Pilot</span>
          </h1>
          <p className="mt-1 text-sm text-slate-500">Sign in to your account</p>
        </div>

        <div className="space-y-4 rounded-xl border border-slate-800 bg-slate-900/60 p-6">
          <div>
            <label
              htmlFor="email"
              className="block text-xs text-slate-500 mb-1.5"
            >
              Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={onKeyDown}
              autoComplete="email"
              className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-emerald-600 focus:outline-none"
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label
              htmlFor="password"
              className="block text-xs text-slate-500 mb-1.5"
            >
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={onKeyDown}
              autoComplete="current-password"
              className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-emerald-600 focus:outline-none"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <p className="rounded-lg bg-rose-500/10 px-3 py-2 text-sm text-rose-300 ring-1 ring-rose-500/20">
              {error}
            </p>
          )}

          <button
            onClick={handleSubmit}
            disabled={submitting || !email || !password}
            className="w-full rounded-lg bg-emerald-600 px-4 py-2 font-medium text-white transition-colors hover:bg-emerald-500 disabled:opacity-50"
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </div>
      </div>
    </main>
  );
}
