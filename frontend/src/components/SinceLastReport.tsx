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
      <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-2.5 text-sm text-slate-500">
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
        className={`rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${
          up
            ? "bg-emerald-500/10 text-emerald-300 ring-emerald-500/20"
            : "bg-rose-500/10 text-rose-300 ring-rose-500/20"
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
        className="rounded-full bg-slate-800 px-2.5 py-0.5 text-xs text-slate-300"
      >
        <span className="font-mono text-slate-200">{f.asset}</span> {f.previous} →{" "}
        {f.current}
      </span>,
    );
  }

  for (const rec of diff.recommendations_new) {
    chips.push(
      <span
        key={`n-${rec}`}
        className="rounded-full bg-amber-500/10 px-2.5 py-0.5 text-xs text-amber-300 ring-1 ring-amber-500/20"
      >
        New: {rec}
      </span>,
    );
  }

  for (const rec of diff.recommendations_resolved) {
    chips.push(
      <span
        key={`r-${rec}`}
        className="rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-xs text-emerald-300 ring-1 ring-emerald-500/20"
      >
        Resolved: {rec}
      </span>,
    );
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs uppercase tracking-wider text-slate-500">
          Since last report
        </span>
        {chips.length > 0 ? (
          chips
        ) : (
          <span className="text-sm text-slate-500">No material changes.</span>
        )}
      </div>
    </div>
  );
}
