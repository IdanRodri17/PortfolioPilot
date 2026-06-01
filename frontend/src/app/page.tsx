"use client";

/**
 * Temporary scaffolding — now the step-3 smoke test: a button that fires
 * useReportStream and dumps phase, the accumulated status feed, and the
 * final report. This is the curl trace flowing into React state. Step 4
 * replaces this with the real dashboard components.
 */

import { useReportStream } from "@/lib/useReportStream";

export default function Home() {
  const { phase, statuses, report, error, start } = useReportStream();

  return (
    <main className="p-8 font-sans">
      <h1 className="text-xl font-semibold">PortfolioPilot — stream harness</h1>

      <button
        onClick={() => start("idan_demo")}
        disabled={phase === "streaming"}
        className="mt-4 rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50"
      >
        {phase === "streaming" ? "Streaming…" : "Generate report"}
      </button>

      <p className="mt-4 text-sm text-gray-400">phase: {phase}</p>

      <p className="mt-4 text-sm text-gray-400">
        status feed ({statuses.length}):
      </p>
      <pre className="mt-1 rounded bg-gray-900 p-3 text-sm text-gray-100">
        {statuses
          .map(
            (s) =>
              `${s.node} — ${s.phase}` +
              (s.metadata.symbol ? ` (${s.metadata.symbol})` : ""),
          )
          .join("\n") || "(none yet)"}
      </pre>

      {error && (
        <pre className="mt-4 rounded bg-red-900 p-3 text-sm text-red-100">
          {JSON.stringify(error, null, 2)}
        </pre>
      )}

      {report && (
        <>
          <p className="mt-4 text-sm text-gray-400">final report:</p>
          <pre className="mt-1 rounded bg-gray-900 p-3 text-sm text-gray-100">
            {JSON.stringify(report, null, 2)}
          </pre>
        </>
      )}
    </main>
  );
}
