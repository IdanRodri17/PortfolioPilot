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
import { signOut, useSession } from "next-auth/react";

import { useUserId } from "@/lib/useUserId";

export default function DashboardPage() {
  const { userId } = useUserId();
  const { data: session } = useSession();
  const {
    phase,
    statuses,
    report,
    reportId,
    diff,
    adviceReview,
    streamedNarrative,
    narrativeStreaming,
    error,
    review,
    resume,
    start,
  } = useReportStream();

  const busy =
    phase === "streaming" || phase === "awaiting_review" || phase === "saving";

  return (
    <main className="min-h-screen bg-backdrop text-ink">
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-10">
        <header className="no-print mb-8 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="font-serif text-2xl font-medium tracking-[-0.01em]">
              PortfolioPilot
            </h1>
            <p className="mt-1 text-sm text-muted">AI portfolio analysis</p>
            <nav className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm">
              <Link href="/portfolio" className="text-forest transition-colors hover:text-forest-deep">
                Edit portfolio
              </Link>
              <Link href="/history" className="text-label transition-colors hover:text-ink">
                History
              </Link>
              <Link href="/memory" className="text-label transition-colors hover:text-ink">
                Memory
              </Link>
              <Link href="/settings" className="text-label transition-colors hover:text-ink">
                Settings
              </Link>
              {session?.user?.email && <span className="text-faint">·</span>}
              {session?.user?.email && (
                <span className="text-faint">{session.user.email}</span>
              )}
              <button
                onClick={() => signOut({ callbackUrl: "/login" })}
                className="text-label transition-colors hover:text-terracotta"
              >
                Sign out
              </button>
            </nav>
          </div>
          <button
            onClick={() => userId && start(userId)}
            disabled={busy}
            className="min-h-[40px] shrink-0 rounded-[2px] bg-forest px-5 py-2 font-semibold text-paper transition-colors hover:bg-forest-deep disabled:opacity-50">
            {busy ? "Analyzing…" : "Generate report"}
          </button>
        </header>

        <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
          {/* Left: what you hold */}
          <aside className="no-print">
            {userId ? (
              <PortfolioOverview userId={userId} />
            ) : (
              <p className="rounded-[4px] border border-line bg-card p-5 text-sm text-faint">
                Loading…
              </p>
            )}
          </aside>

          {/* Right: the analysis flow */}
          <div className="space-y-6">
            <div className="no-print">
              <LiveStatusFeed statuses={statuses} phase={phase} />
            </div>

            {error && (
              <p className="rounded-[4px] border border-neg-line bg-wash-neg px-4 py-3 text-sm text-terracotta">
                {error.message}
              </p>
            )}

            {report ? (
              <FinalReportView
                report={report}
                diff={diff}
                adviceReview={adviceReview}
                reportId={reportId}
                streamingNarrative={streamedNarrative}
                narrativeStreaming={narrativeStreaming}
              />
            ) : (
              phase !== "streaming" && (
                <p className="rounded-[4px] border border-dashed border-line px-4 py-10 text-center text-sm text-faint">
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
