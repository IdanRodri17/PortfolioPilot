"use client";

/**
 * MemoryReviewModal — the HITL gate (V6).
 *
 * Target path: frontend/src/components/MemoryReviewModal.tsx
 *
 * Triggered when the generate stream ends with `human_input_required`. Renders
 * the extractor's proposed memories as checkboxes; the indices the user keeps
 * are sent back via onApprove, which the dashboard forwards to the hook's
 * resume() (POST /api/resume-graph). Only approved insights get persisted.
 *
 * Defaults every proposal checked — for an approval gate the lighter touch is
 * "review and uncheck what you don't want", not "opt in from nothing".
 *
 * Theme matches the rest of the app (per-container dark fintech, pattern #29):
 * emerald = keep/good, rose = reject, slate = neutral.
 */

import { useState } from "react";
import type { ProposedMemory } from "@/lib/types";

interface MemoryReviewModalProps {
  proposedMemories: ProposedMemory[];
  saving: boolean;
  onApprove: (approvedIndices: number[]) => void;
}

export function MemoryReviewModal({
  proposedMemories,
  saving,
  onApprove,
}: MemoryReviewModalProps) {
  const [checked, setChecked] = useState<boolean[]>(() =>
    proposedMemories.map(() => true),
  );

  function toggle(i: number) {
    setChecked((prev) => prev.map((c, j) => (j === i ? !c : c)));
  }

  const selectedIndices = checked.flatMap((c, i) => (c ? [i] : []));
  const allIndices = proposedMemories.map((_, i) => i);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-xl border border-slate-800 bg-slate-900 p-6 shadow-2xl">
        <h2 className="text-lg font-semibold tracking-tight text-slate-100">
          Review what PortfolioPilot learned
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          These insights were distilled from this report. Choose which to keep in
          long-term memory — only the ones you approve are saved.
        </p>

        <ul className="mt-5 space-y-2">
          {proposedMemories.map((m, i) => (
            <li key={i}>
              <label
                className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
                  checked[i]
                    ? "border-emerald-600/40 bg-emerald-500/5"
                    : "border-slate-800 bg-slate-900/40"
                }`}
              >
                <input
                  type="checkbox"
                  checked={checked[i]}
                  onChange={() => toggle(i)}
                  disabled={saving}
                  className="mt-0.5 h-4 w-4 flex-shrink-0 accent-emerald-600"
                />
                <span className="text-sm leading-relaxed text-slate-200">
                  {m.insight}
                </span>
              </label>
            </li>
          ))}
        </ul>

        <div className="mt-6 flex items-center justify-between gap-3">
          <button
            onClick={() => onApprove([])}
            disabled={saving}
            className="text-sm text-slate-500 transition-colors hover:text-rose-400 disabled:opacity-50"
          >
            Reject all
          </button>
          <div className="flex items-center gap-2">
            <button
              onClick={() => onApprove(allIndices)}
              disabled={saving}
              className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 transition-colors hover:bg-slate-800 disabled:opacity-50"
            >
              Approve all
            </button>
            <button
              onClick={() => onApprove(selectedIndices)}
              disabled={saving || selectedIndices.length === 0}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-500 disabled:opacity-50"
            >
              {saving ? "Saving…" : `Approve selected (${selectedIndices.length})`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
