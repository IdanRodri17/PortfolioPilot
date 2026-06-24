"use client";

/**
 * SinceLastReport — a compact "what changed" strip shown atop a fresh report.
 *
 * Fed by the report_diff SSE event (V12b), computed deterministically on the
 * backend by diffing the new report against the user's previous one. Renders a
 * first-run message when there's nothing to compare, else color-coded chips:
 * valuation delta, per-asset sentiment flips, and new/resolved recommendations.
 */

import type { ReactNode } from "react";
import type { ReportDiff } from "@/lib/types";

export function SinceLastReport({ diff }: { diff: ReportDiff }) {
  if (diff.first_report) {
    return (
      <div className="rounded-[4px] border border-line bg-card px-4 py-2.5 text-sm text-faint">
        First report — nothing to compare yet.
      </div>
    );
  }

  const chips: ReactNode[] = [];

  const delta = diff.valuation_delta_pct;
  if (delta != null && Math.abs(delta) >= 0.01) {
    const up = delta >= 0;
    chips.push(
      <span
        key="val"
        className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
          up
            ? "bg-wash-pos text-forest"
            : "bg-wash-neg text-terracotta"
        }`}
      >
        Value {up ? "+" : ""}
        {delta.toFixed(2)}%
      </span>,
    );
  }

  for (const f of diff.sentiment_flips) {
    chips.push(
      <span
        key={`s-${f.asset}`}
        className="rounded-full bg-chip px-2.5 py-0.5 text-xs text-muted"
      >
        <span className="font-mono text-ink">{f.asset}</span> {f.previous} →{" "}
        {f.current}
      </span>,
    );
  }

  for (const rec of diff.recommendations_new) {
    chips.push(
      <span
        key={`n-${rec}`}
        className="rounded-full bg-ochre/10 px-2.5 py-0.5 text-xs text-ochre"
      >
        New: {rec}
      </span>,
    );
  }

  for (const rec of diff.recommendations_resolved) {
    chips.push(
      <span
        key={`r-${rec}`}
        className="rounded-full bg-wash-pos px-2.5 py-0.5 text-xs text-forest"
      >
        Resolved: {rec}
      </span>,
    );
  }

  return (
    <div className="rounded-[4px] border border-line bg-card px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-[0.12em] text-faint">
          Since last report
        </span>
        {chips.length > 0 ? (
          chips
        ) : (
          <span className="text-sm text-faint">No material changes.</span>
        )}
      </div>
    </div>
  );
}
