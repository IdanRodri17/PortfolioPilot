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
 * Theme matches the rest of the app: the Editorial light theme — warm paper
 * canvas, forest-green accent, terracotta for errors (pattern #29).
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
    <main className="min-h-screen bg-backdrop text-ink flex items-center justify-center px-6">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="font-serif text-2xl font-medium tracking-[-0.02em]">
            Portfolio<span className="text-forest">Pilot</span>
          </h1>
          <p className="mt-1 text-sm text-faint">Sign in to your account</p>
        </div>

        <div className="space-y-4 rounded-[4px] border border-line bg-card p-6">
          <div>
            <label
              htmlFor="email"
              className="block text-xs text-label mb-1.5"
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
              className="w-full min-h-[40px] rounded-[3px] border border-field bg-card px-3 py-2 text-sm text-ink placeholder:text-faint focus:border-forest focus:outline-none"
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label
              htmlFor="password"
              className="block text-xs text-label mb-1.5"
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
              className="w-full min-h-[40px] rounded-[3px] border border-field bg-card px-3 py-2 text-sm text-ink placeholder:text-faint focus:border-forest focus:outline-none"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <p className="rounded-[3px] bg-wash-neg px-3 py-2 text-sm text-terracotta">
              {error}
            </p>
          )}

          <button
            onClick={handleSubmit}
            disabled={submitting || !email || !password}
            className="w-full min-h-[40px] rounded-[2px] bg-forest px-4 py-2 font-medium text-paper transition-colors hover:bg-forest-deep disabled:opacity-50"
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </div>
      </div>
    </main>
  );
}
