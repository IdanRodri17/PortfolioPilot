"use client";

/**
 * Dashboard page — the real V4b dashboard.
 *
 * Layout: a centered max-width container splitting into two columns on large
 * screens — a fixed-width left column with the Holdings panel and a flexible
 * right column with the live pipeline and the report. Stacks on small screens.
 * The Generate control and the link to the editor live in the header.
 *
 * user_id is hardcoded to the demo user; there is no auth until V7, so no
 * user switcher.
 */

import Link from "next/link";
import { useReportStream } from "@/lib/useReportStream";
import { LiveStatusFeed } from "@/components/LiveStatusFeed";
import { FinalReportView } from "@/components/FinalReportView";
import { PortfolioOverview } from "@/components/PortfolioOverview";
import { MemoryReviewModal } from "@/components/MemoryReviewModal";

const DEMO_USER = "idan_demo";

export default function DashboardPage() {
  const { phase, statuses, report, error, review, resume, start } = useReportStream();

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-5xl px-6 py-10">
        <header className="mb-8 flex items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">PortfolioPilot</h1>
            <p className="mt-1 text-sm text-slate-500">AI portfolio analysis</p>
            <nav className="mt-2 flex gap-4 text-sm">
              <Link href="/portfolio" className="text-emerald-400 transition-colors hover:text-emerald-300">
                Edit portfolio
              </Link>
              <Link href="/history" className="text-slate-400 transition-colors hover:text-slate-200">
                History
              </Link>
              <Link href="/memory" className="text-slate-400 transition-colors hover:text-slate-200">
                Memory
              </Link>
            </nav>
          </div>
          <button
            onClick={() => start(DEMO_USER)}
            disabled={phase === "streaming" || phase === "awaiting_review" || phase === "saving"}
            className="rounded-lg bg-emerald-600 px-4 py-2 font-medium text-white transition-colors hover:bg-emerald-500 disabled:opacity-50">
            {phase === "streaming" || phase === "awaiting_review" || phase === "saving"
              ? "Analyzing…"
              : "Generate report"}
          </button>
        </header>

        <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
          {/* Left: what you hold */}
          <aside>
            <PortfolioOverview userId={DEMO_USER} />
          </aside>

          {/* Right: the analysis flow */}
          <div className="space-y-6">
            <LiveStatusFeed statuses={statuses} phase={phase} />

            {error && (
              <p className="rounded-lg bg-rose-500/10 px-4 py-3 text-sm text-rose-300 ring-1 ring-rose-500/20">
                {error.message}
              </p>
            )}

            {report ? (
              <FinalReportView report={report} />
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
      {(phase === "awaiting_review" || phase === "saving") && review && (
        <MemoryReviewModal
          proposedMemories={review.proposedMemories}
          saving={phase === "saving"}
          onApprove={(indices) => resume(review.threadId, indices)}
        />
      )}
    </main>
  );
}
