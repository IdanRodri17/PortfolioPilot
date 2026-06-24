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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-[4px] border border-line bg-paper p-5 text-ink shadow-2xl sm:p-6">
        <h2 className="font-serif text-lg font-medium tracking-tight text-ink">
          Review what PortfolioPilot learned
        </h2>
        <p className="mt-1 text-sm text-muted">
          These insights were distilled from this report. Choose which to keep in
          long-term memory — only the ones you approve are saved.
        </p>

        <ul className="mt-5 space-y-2">
          {proposedMemories.map((m, i) => (
            <li key={i}>
              <label
                className={`flex cursor-pointer items-start gap-3 rounded-[3px] border p-3 transition-colors ${
                  checked[i]
                    ? "border-forest/40 bg-wash-pos"
                    : "border-line bg-card"
                }`}
              >
                <input
                  type="checkbox"
                  checked={checked[i]}
                  onChange={() => toggle(i)}
                  disabled={saving}
                  className="mt-0.5 h-4 w-4 flex-shrink-0 accent-[#2f5d45]"
                />
                <span className="text-sm leading-relaxed text-ink">
                  {m.insight}
                </span>
              </label>
            </li>
          ))}
        </ul>

        <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <button
            onClick={() => onApprove([])}
            disabled={saving}
            className="min-h-[40px] text-sm text-label transition-colors hover:text-terracotta disabled:opacity-50"
          >
            Reject all
          </button>
          <div className="flex items-center gap-2">
            <button
              onClick={() => onApprove(allIndices)}
              disabled={saving}
              className="min-h-[40px] rounded-[2px] border border-field px-3 py-2 text-sm text-muted transition-colors hover:bg-inset disabled:opacity-50"
            >
              Approve all
            </button>
            <button
              onClick={() => onApprove(selectedIndices)}
              disabled={saving || selectedIndices.length === 0}
              className="min-h-[40px] rounded-[2px] bg-forest px-4 py-2 text-sm font-medium text-paper transition-colors hover:bg-forest-deep disabled:opacity-50"
            >
              {saving ? "Saving…" : `Approve selected (${selectedIndices.length})`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
