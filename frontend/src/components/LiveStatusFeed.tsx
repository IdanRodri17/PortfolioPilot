"use client";

/**
 * LiveStatusFeed — renders the SSE status stream as a live analysis pipeline.
 *
 * Turns the flat StatusEventData[] from useReportStream into ordered rows,
 * one per graph node (and one per sentiment_agent branch, keyed by symbol),
 * each showing whether it is currently running or finished. This is where
 * aha-moment #2 lives: when the Send() fan-out fires, the five sentiment
 * rows plus risk_agent appear and pulse at the same time — the parallelism
 * made visible, not a spinner hiding a black box.
 *
 * Folding logic: each node emits a start then (later) an end event. We key
 * by node name, except sentiment_agent which runs N times — there we key by
 * node + symbol so the five branches are distinct rows. First appearance
 * fixes the row's position; the end event flips it from running to done.
 */

import type { StatusEventData } from "@/lib/types";
import type { StreamPhase } from "@/lib/useReportStream";

interface LiveStatusFeedProps {
  statuses: StatusEventData[];
  phase: StreamPhase;
}

interface Row {
  key: string;
  label: string;
  symbol?: string;
  running: boolean;
  done: boolean;
}

function labelFor(node: string): string {
  switch (node) {
    case "data_ingestion":
      return "Fetching market data";
    case "sentiment_agent":
      return "Sentiment";
    case "risk_agent":
      return "Risk analysis";
    case "macro_context_agent":
      return "Sector concentration";
    case "synthesizer":
      return "Synthesizing report";
    case "memory_loader":
      return "Recalling memory";
    case "guardrail":
      return "Validating report";
    case "memory_extractor":
      return "Extracting insights";
    case "memory_saver":
      return "Saving approved insights";
    default:
      return node;
  }
}

function buildRows(statuses: StatusEventData[]): Row[] {
  const order: string[] = [];
  const byKey = new Map<string, Row>();

  for (const s of statuses) {
    const symbol = s.metadata?.symbol;
    const key = symbol ? `${s.node}:${symbol}` : s.node;

    if (!byKey.has(key)) {
      order.push(key);
      byKey.set(key, {
        key,
        label: labelFor(s.node),
        symbol,
        running: false,
        done: false,
      });
    }

    const row = byKey.get(key)!;
    if (s.phase === "start") row.running = true;
    if (s.phase === "end") {
      row.running = false;
      row.done = true;
    }
  }

  return order.map((k) => byKey.get(k)!);
}

function RunningDot() {
  // Classic ping-ring dot: the outer ring animates outward while the solid
  // core stays put. Several of these pulsing at once IS the burst.
  return (
    <span className="relative flex h-2.5 w-2.5">
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-ochre opacity-75" />
      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-ochre" />
    </span>
  );
}

function DoneCheck() {
  return (
    <svg
      className="h-4 w-4 text-forest"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M5 10.5l3.5 3.5L15 6" />
    </svg>
  );
}

export function LiveStatusFeed({ statuses, phase }: LiveStatusFeedProps) {
  const rows = buildRows(statuses);

  const phaseLabel =
    phase === "streaming"
      ? "Running"
      : phase === "done"
        ? "Complete"
        : phase === "error"
          ? "Failed"
          : "Idle";

  return (
    <section className="rounded-[4px] border border-line bg-card p-5">
      <header className="mb-4 flex items-center justify-between">
        <h2 className="font-serif text-lg font-medium text-ink">
          Analysis pipeline
        </h2>
        <span className="text-xs font-semibold uppercase tracking-[0.12em] text-faint">
          {phaseLabel}
        </span>
      </header>

      {rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-faint">
          Run a report to watch the agents work.
        </p>
      ) : (
        <ul className="space-y-1">
          {rows.map((row) => (
            <li
              key={row.key}
              className={`flex items-center gap-3 rounded-[2px] px-3 py-2 transition-colors ${
                row.running ? "bg-inset" : ""
              }`}
            >
              <span className="flex w-4 justify-center">
                {row.done ? <DoneCheck /> : <RunningDot />}
              </span>
              <span className="text-sm text-ink">{row.label}</span>
              {row.symbol && (
                <span className="rounded-[2px] bg-chip px-1.5 py-0.5 font-mono text-xs text-muted">
                  {row.symbol}
                </span>
              )}
              <span className="ml-auto text-xs text-faint">
                {row.done ? "done" : "running"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
