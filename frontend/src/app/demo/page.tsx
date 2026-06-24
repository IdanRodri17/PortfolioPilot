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
  const {
    phase,
    statuses,
    report,
    diff,
    adviceReview,
    error,
    streamedNarrative,
    narrativeStreaming,
    start,
  } = useReportStream();

  return (
    <main className="min-h-screen bg-backdrop text-ink">
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-10">
        {/* Demo banner */}
        <div className="no-print mb-6 rounded-[4px] border border-pos-line bg-wash-pos px-4 py-3 text-sm text-forest">
          Live demo on a sample portfolio — a real AI report, nothing saved.{" "}
          <Link href="/login" className="font-semibold underline hover:text-forest-deep">
            Sign up
          </Link>{" "}
          to track your own holdings.
        </div>

        <header className="no-print mb-8 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="font-serif text-2xl font-medium tracking-[-0.01em]">PortfolioPilot</h1>
            <p className="mt-1 text-sm text-muted">AI portfolio analysis · demo</p>
          </div>
          <button
            onClick={() => start(DEMO_USER)}
            disabled={phase === "streaming"}
            className="min-h-[40px] shrink-0 rounded-[2px] bg-forest px-5 py-2 font-semibold text-paper transition-colors hover:bg-forest-deep disabled:opacity-50"
          >
            {phase === "streaming" ? "Analyzing…" : "Generate report"}
          </button>
        </header>

        <div className="space-y-6">
          {/* Top band: holdings + live pipeline side-by-side; report spans full width below */}
          <div className="grid items-stretch gap-6 lg:grid-cols-[18rem_1fr]">
            {/* Left: the curated holdings (read-only); fills the equal-height cell */}
            <aside className="no-print [&>*]:h-full">
              <PortfolioOverview userId={DEMO_USER} />
            </aside>

            <div className="no-print flex min-w-0 flex-col gap-4">
              {/* flex-1 + h-full: the pipeline stretches to match the holdings height */}
              <div className="flex-1 [&>*]:h-full">
                <LiveStatusFeed statuses={statuses} phase={phase} />
              </div>

              {error && (
                <p className="rounded-[4px] border border-neg-line bg-wash-neg px-4 py-3 text-sm text-terracotta">
                  {error.message}
                </p>
              )}

              {!report && phase !== "streaming" && (
                <p className="rounded-[4px] border border-dashed border-line px-4 py-10 text-center text-sm text-faint">
                  Generate a report to see the analysis here.
                </p>
              )}
            </div>
          </div>

          {/* Report — full width. No reportId passed -> report chat stays hidden in the demo. */}
          {report && (
            <FinalReportView
              report={report}
              diff={diff}
              adviceReview={adviceReview}
              streamingNarrative={streamedNarrative}
              narrativeStreaming={narrativeStreaming}
            />
          )}
        </div>
      </div>
    </main>
  );
}
