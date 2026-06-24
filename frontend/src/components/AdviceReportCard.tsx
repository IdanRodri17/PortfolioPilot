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
    chip: "bg-wash-pos text-forest",
  },
  poor: {
    label: "Aged poorly",
    chip: "bg-wash-neg text-terracotta",
  },
  neutral: {
    label: "Neutral",
    chip: "bg-ochre/10 text-ochre",
  },
  insufficient_data: {
    label: "No data",
    chip: "bg-inset text-faint",
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
    <section className="rounded-[4px] border border-line bg-card p-5">
      <div className="mb-1 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
        <h2 className="font-serif text-lg font-medium text-ink">
          How last report&apos;s calls aged
        </h2>
        <span className="text-xs text-faint">{review.summary}</span>
      </div>
      <p className="mb-3 text-xs text-label">
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
              className="flex items-center gap-3 rounded-[4px] border border-line bg-card p-3"
            >
              <span className="rounded-[2px] bg-chip px-1.5 py-0.5 font-mono text-sm text-ink">{call.asset}</span>
              <span className="text-sm text-muted">
                {ACTION_LABEL[call.action]}
              </span>
              <span className="ml-auto font-mono text-xs">
                {move == null ? (
                  <span className="text-faint">—</span>
                ) : (
                  <span className={up ? "text-forest" : "text-terracotta"}>
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
