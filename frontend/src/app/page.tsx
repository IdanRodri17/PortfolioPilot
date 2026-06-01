"use client";

/**
 * Temporary harness — step 4b swaps the raw report <pre> for the
 * FinalReportView component. Button + LiveStatusFeed stay; 4c assembles
 * everything (plus the PortfolioOverview pie) into the real dashboard
 * page and retires this harness.
 */

import { useReportStream } from "@/lib/useReportStream";
import { LiveStatusFeed } from "@/components/LiveStatusFeed";
import { FinalReportView } from "@/components/FinalReportView";

export default function Home() {
  const { phase, statuses, report, error, start } = useReportStream();

  return (
    <main className="min-h-screen bg-slate-950 p-8 font-sans text-slate-100">
      <h1 className="text-xl font-semibold">PortfolioPilot — dashboard (building)</h1>

      <button
        onClick={() => start("idan_demo")}
        disabled={phase === "streaming"}
        className="mt-4 rounded-lg bg-emerald-600 px-4 py-2 font-medium text-white transition-colors hover:bg-emerald-500 disabled:opacity-50"
      >
        {phase === "streaming" ? "Analyzing…" : "Generate report"}
      </button>

      <div className="mt-6 max-w-2xl">
        <LiveStatusFeed statuses={statuses} phase={phase} />
      </div>

      {error && (
        <pre className="mt-4 max-w-2xl rounded bg-red-950 p-3 text-sm text-red-200">
          {JSON.stringify(error, null, 2)}
        </pre>
      )}

      {report && (
        <div className="mt-6 max-w-2xl">
          <FinalReportView report={report} />
        </div>
      )}
    </main>
  );
}
