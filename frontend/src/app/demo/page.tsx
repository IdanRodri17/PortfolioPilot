"use client";

/**
 * /demo — zero-signup guest mode (V15a).
 *
 * A public, read-only dashboard bound to the curated `idan_demo` portfolio: a
 * visitor can generate a real streamed report (with the donut, concentration,
 * since-last-report diff, and advice card) but cannot edit holdings, chat, wipe
 * memory, or change settings. The backend opens exactly the demo user's read +
 * generate endpoints; everything else stays default-closed (V9).
 *
 * Reuses the dashboard components rather than forking them — it simply omits the
 * authenticated-only affordances (edit, chat, memory modal, nav, sign-out).
 */

import Link from "next/link";
import { useReportStream } from "@/lib/useReportStream";
import { LiveStatusFeed } from "@/components/LiveStatusFeed";
import { FinalReportView } from "@/components/FinalReportView";
import { PortfolioOverview } from "@/components/PortfolioOverview";

const DEMO_USER = "idan_demo";

export default function DemoPage() {
  const { phase, statuses, report, diff, adviceReview, error, start } =
    useReportStream();

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-5xl px-6 py-10">
        {/* Demo banner */}
        <div className="no-print mb-6 rounded-lg border border-emerald-600/30 bg-emerald-500/5 px-4 py-3 text-sm text-emerald-300/90">
          Live demo on a sample portfolio — a real AI report, nothing saved.{" "}
          <Link href="/login" className="font-medium underline hover:text-emerald-200">
            Sign up
          </Link>{" "}
          to track your own holdings.
        </div>

        <header className="no-print mb-8 flex items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">PortfolioPilot</h1>
            <p className="mt-1 text-sm text-slate-500">AI portfolio analysis · demo</p>
          </div>
          <button
            onClick={() => start(DEMO_USER)}
            disabled={phase === "streaming"}
            className="rounded-lg bg-emerald-600 px-4 py-2 font-medium text-white transition-colors hover:bg-emerald-500 disabled:opacity-50"
          >
            {phase === "streaming" ? "Analyzing…" : "Generate report"}
          </button>
        </header>

        <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
          {/* Left: the curated holdings (read-only) */}
          <aside className="no-print">
            <PortfolioOverview userId={DEMO_USER} />
          </aside>

          {/* Right: the analysis flow */}
          <div className="space-y-6">
            <div className="no-print">
              <LiveStatusFeed statuses={statuses} phase={phase} />
            </div>

            {error && (
              <p className="rounded-lg bg-rose-500/10 px-4 py-3 text-sm text-rose-300 ring-1 ring-rose-500/20">
                {error.message}
              </p>
            )}

            {report ? (
              // No reportId passed -> the report chat stays hidden in the demo.
              <FinalReportView report={report} diff={diff} adviceReview={adviceReview} />
            ) : (
              phase !== "streaming" && (
                <p className="rounded-xl border border-dashed border-slate-800 px-4 py-10 text-center text-sm text-slate-600">
                  Generate a report to see the analysis here.
                </p>
              )
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
