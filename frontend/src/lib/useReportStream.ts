"use client";

/**
 * useReportStream — drives the full HITL report flow (V6).
 *
 * Two transports, because the two legs need different HTTP shapes:
 *   - Stream 1 (generate): GET SSE via the browser's native EventSource.
 *   - Stream 2 (resume):   POST SSE — the approved indices ride in the body,
 *                          which EventSource (GET-only) can't do, so we read
 *                          it with fetch() + response.body.getReader() and a
 *                          small SSE parser.
 *
 * State machine: idle -> streaming -> done, OR
 *                idle -> streaming -> done -> awaiting_review -> saving -> done.
 *
 * report_complete is NOT terminal anymore: a human_input_required may follow it
 * in the same stream. So we keep the connection open after the report and only
 * treat a close as clean once we've seen a report/review/error (terminalRef) —
 * otherwise EventSource's auto-reconnect would re-run the whole graph.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  FinalReport,
  ReportDiff,
  AdviceReview,
  StatusEventData,
  ErrorEventData,
  ProposedMemory,
  HumanInputRequiredData,
  MemorySavedData,
  NarrativeTokenData,
} from "@/lib/types";
import { getApiToken, authHeaders } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL;

export type StreamPhase =
  | "idle"
  | "streaming"
  | "done"
  | "awaiting_review"
  | "saving"
  | "error";

export interface ReviewState {
  threadId: string;
  proposedMemories: ProposedMemory[];
}

export interface UseReportStream {
  phase: StreamPhase;
  statuses: StatusEventData[];
  report: FinalReport | null;
  reportId: string | null;
  diff: ReportDiff | null;
  adviceReview: AdviceReview | null;
  error: ErrorEventData | null;
  review: ReviewState | null;
  savedCount: number | null;
  // V19: the summary as it types in, and whether it's still typing. While
  // narrativeStreaming is true the report view shows streamedNarrative; once
  // false it falls back to the authoritative report.summary_narrative.
  streamedNarrative: string;
  narrativeStreaming: boolean;
  start: (userId: string) => void;
  resume: (threadId: string, approvedIndices: number[]) => Promise<void>;
}

/** Parse one SSE block ("event: X\ndata: Y") into {event, data}. */
function parseSseBlock(block: string): { event: string; data: unknown } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
}

export function useReportStream(): UseReportStream {
  const [phase, setPhase] = useState<StreamPhase>("idle");
  const [statuses, setStatuses] = useState<StatusEventData[]>([]);
  const [report, setReport] = useState<FinalReport | null>(null);
  const [reportId, setReportId] = useState<string | null>(null);
  const [diff, setDiff] = useState<ReportDiff | null>(null);
  const [adviceReview, setAdviceReview] = useState<AdviceReview | null>(null);
  const [error, setError] = useState<ErrorEventData | null>(null);
  const [review, setReview] = useState<ReviewState | null>(null);
  const [savedCount, setSavedCount] = useState<number | null>(null);
  const [streamedNarrative, setStreamedNarrative] = useState("");
  const [narrativeStreaming, setNarrativeStreaming] = useState(false);

  const esRef = useRef<EventSource | null>(null);
  // True once a report/review/error has been seen — tells the transport
  // onerror that a subsequent connection close is the expected end, not a fault.
  const terminalRef = useRef(false);

  const close = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
  }, []);

  const start = useCallback(
    async (userId: string) => {
      close();
      setStatuses([]);
      setReport(null);
      setReportId(null);
      setDiff(null);
      setAdviceReview(null);
      setError(null);
      setReview(null);
      setSavedCount(null);
      setStreamedNarrative("");
      setNarrativeStreaming(false);
      setPhase("streaming");
      terminalRef.current = false;

      // EventSource can't set headers, so (V9, option A) the short-lived API
      // token rides as a query param. Authenticated users get one; the guest
      // demo (V15a) has none, so we omit it and let the backend's demo carve-out
      // decide (any non-demo user without a token gets 401).
      let token = "";
      try {
        token = await getApiToken();
      } catch {
        token = "";
      }

      const url =
        `${API_BASE}/api/generate-report?user_id=${encodeURIComponent(userId)}` +
        (token ? `&token=${encodeURIComponent(token)}` : "");
      const es = new EventSource(url);
      esRef.current = es;

      es.addEventListener("status", (e: MessageEvent) => {
        setStatuses((prev) => [...prev, JSON.parse(e.data) as StatusEventData]);
      });

      // Report arrives — render it, but DON'T close: a human_input_required may
      // still follow in this same stream. Mark terminal so a later close reads
      // as clean.
      es.addEventListener("report_complete", (e: MessageEvent) => {
        const data = JSON.parse(e.data) as FinalReport & { report_id?: string };
        setReport(data);
        setReportId(data.report_id ?? null); // carried for the report chat (V14)
        setPhase("done");
        terminalRef.current = true;
        // V19: the narrative replay (narrative_token events) follows; show the
        // typing indicator until narrative_done. The full text is already in
        // `data.summary_narrative` as the fallback once streaming stops.
        setStreamedNarrative("");
        setNarrativeStreaming(true);
      });

      // V19: the summary types in word-by-word after report_complete. Guard
      // against a stale event from a superseded stream (re-Generate mid-typing)
      // appending into the new run's accumulator.
      es.addEventListener("narrative_token", (e: MessageEvent) => {
        if (esRef.current !== es) return;
        const data = JSON.parse(e.data) as NarrativeTokenData;
        setStreamedNarrative((prev) => prev + data.text);
      });
      es.addEventListener("narrative_done", () => {
        setNarrativeStreaming(false);
      });

      // The since-last-report diff follows report_complete on the same stream.
      es.addEventListener("report_diff", (e: MessageEvent) => {
        setDiff(JSON.parse(e.data) as ReportDiff);
      });

      // The advice report card (V13) also follows on the same stream.
      es.addEventListener("advice_review", (e: MessageEvent) => {
        setAdviceReview(JSON.parse(e.data) as AdviceReview);
      });

      // The pause: open the modal and close THIS stream. Resume is a new stream.
      es.addEventListener("human_input_required", (e: MessageEvent) => {
        const data = JSON.parse(e.data) as HumanInputRequiredData;
        setReview({
          threadId: data.thread_id,
          proposedMemories: data.payload.proposed_memories,
        });
        setPhase("awaiting_review");
        terminalRef.current = true;
        setNarrativeStreaming(false);
        close();
      });

      es.addEventListener("error", (e: MessageEvent) => {
        if (e.data) {
          setError(JSON.parse(e.data) as ErrorEventData);
        } else {
          setError({ code: "STREAM_ERROR", message: "Connection failed." });
        }
        setPhase("error");
        terminalRef.current = true;
        setNarrativeStreaming(false);
        close();
      });

      es.onerror = () => {
        if (esRef.current === null) return; // already closed cleanly
        if (terminalRef.current) {
          // Report (or review/error) already handled — this is the stream
          // closing normally (e.g. the no-proposals path ends at report_complete).
          // If it closed mid-narrative, stop typing and fall back to the full text.
          setNarrativeStreaming(false);
          close();
          return;
        }
        setError({
          code: "STREAM_ERROR",
          message: "Connection to the report stream failed.",
        });
        setPhase("error");
        close();
      };
    },
    [close],
  );

  // Resume leg: POST the approvals, read the SSE response with a stream reader.
  const resume = useCallback(
    async (threadId: string, approvedIndices: number[]) => {
      setPhase("saving");
      try {
        const res = await fetch(
          `${API_BASE}/api/resume-graph?thread_id=${encodeURIComponent(threadId)}`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(await authHeaders()),
            },
            body: JSON.stringify({ approved_indices: approvedIndices }),
          },
        );
        if (!res.ok || !res.body) {
          setError({ code: "RESUME_HTTP", message: `Resume failed: HTTP ${res.status}` });
          setPhase("error");
          setReview(null);
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let sep: number;
          while ((sep = buffer.indexOf("\n\n")) !== -1) {
            const block = buffer.slice(0, sep);
            buffer = buffer.slice(sep + 2);
            const ev = parseSseBlock(block);
            if (!ev) continue;
            if (ev.event === "status") {
              setStatuses((prev) => [...prev, ev.data as StatusEventData]);
            } else if (ev.event === "memory_saved") {
              setSavedCount((ev.data as MemorySavedData).count);
              setPhase("done");
              setReview(null); // closes the modal
            } else if (ev.event === "error") {
              setError(ev.data as ErrorEventData);
              setPhase("error");
              setReview(null);
            }
          }
        }
      } catch (e) {
        setError({ code: "RESUME_ERROR", message: String(e) });
        setPhase("error");
        setReview(null);
      }
    },
    [],
  );

  useEffect(() => close, [close]);

  return {
    phase,
    statuses,
    report,
    reportId,
    diff,
    adviceReview,
    error,
    review,
    savedCount,
    streamedNarrative,
    narrativeStreaming,
    start,
    resume,
  };
}