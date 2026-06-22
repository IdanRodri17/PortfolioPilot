"use client";

/**
 * AdviceReportCard — "how last report's calls aged" (V13).
 *
 * Fed by the advice_review SSE event: each prior recommendation graded
 * deterministically on the backend against the asset's actual price move since.
 * Win/lose/neutral colour-coded; ungradeable calls shown plainly. Explicitly a
 * backward-looking, single-step grade — not a performance guarantee.
 */

import type { AdviceReview, GradedCall } from "@/lib/types";

const GRADE_META: Record<GradedCall["grade"], { label: string; chip: string }> = {
  good: {
    label: "Aged well",
    chip: "bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/20",
  },
  poor: {
    label: "Aged poorly",
    chip: "bg-rose-500/10 text-rose-300 ring-1 ring-rose-500/20",
  },
  neutral: {
    label: "Neutral",
    chip: "bg-slate-500/10 text-slate-300 ring-1 ring-slate-500/20",
  },
  insufficient_data: {
    label: "No data",
    chip: "bg-slate-500/10 text-slate-400 ring-1 ring-slate-500/20",
  },
};

const ACTION_LABEL: Record<GradedCall["action"], string> = {
  reduce: "Reduce",
  increase: "Increase",
  hold: "Hold",
};

export function AdviceReportCard({ review }: { review: AdviceReview }) {
  // Nothing to grade (first report, or the prior report made no calls).
  if (review.calls.length === 0) return null;

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-1 flex items-center justify-between gap-3">
        <h2 className="text-sm font-medium tracking-wide text-slate-300">
          How last report&apos;s calls aged
        </h2>
        <span className="text-xs text-slate-500">{review.summary}</span>
      </div>
      <p className="mb-3 text-xs text-slate-600">
        Backward-looking, single-step grade since {review.recommended_at} — not a
        performance guarantee.
      </p>
      <div className="space-y-2">
        {review.calls.map((call) => {
          const meta = GRADE_META[call.grade];
          const move = call.pct_move_since;
          const up = (move ?? 0) >= 0;
          return (
            <div
              key={`${call.asset}-${call.action}`}
              className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/40 p-3"
            >
              <span className="font-mono text-sm text-slate-200">{call.asset}</span>
              <span className="text-sm text-slate-400">
                {ACTION_LABEL[call.action]}
              </span>
              <span className="ml-auto font-mono text-xs">
                {move == null ? (
                  <span className="text-slate-500">—</span>
                ) : (
                  <span className={up ? "text-emerald-400" : "text-rose-400"}>
                    {up ? "▲" : "▼"} {Math.abs(move).toFixed(2)}%
                  </span>
                )}
              </span>
              <span
                className={`rounded-full px-2 py-0.5 text-xs font-medium ${meta.chip}`}
              >
                {meta.label}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
