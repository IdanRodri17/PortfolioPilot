"use client";

/**
 * useReportStream — opens the report SSE stream and accumulates it into
 * typed React state the dashboard renders against.
 *
 * Why EventSource (not fetch): the backend GET /api/generate-report is a
 * long-lived text/event-stream, not a one-shot body. EventSource is the
 * browser's native client for it — it holds the connection open and
 * pushes each event as it arrives.
 *
 * Two EventSource footguns this hook handles:
 *   1. Named events. The browser's EventSource only fires `onmessage` for
 *      UNNAMED events. The backend names every event (event: status,
 *      event: report_complete, event: error), so we must addEventListener
 *      per name — a bare onmessage would receive nothing.
 *   2. Auto-reconnect. When the stream closes, EventSource assumes the
 *      connection dropped and reopens it — which would re-run the whole
 *      graph. So on terminal events (report_complete, error) and on a
 *      transport error we call es.close() explicitly to stop that.
 *
 * The status feed is the V4 showpiece: the burst of sentiment_agent
 * starts (each carrying its symbol) is the parallel Send() fan-out made
 * visible, exactly as seen in the curl trace.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  FinalReport,
  StatusEventData,
  ErrorEventData,
} from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL;

// idle -> streaming -> (done | error). The dashboard switches UI on this.
export type StreamPhase = "idle" | "streaming" | "done" | "error";

export interface UseReportStream {
  phase: StreamPhase;
  statuses: StatusEventData[]; // accumulated, in arrival order
  report: FinalReport | null;
  error: ErrorEventData | null;
  start: (userId: string) => void;
}

export function useReportStream(): UseReportStream {
  const [phase, setPhase] = useState<StreamPhase>("idle");
  const [statuses, setStatuses] = useState<StatusEventData[]>([]);
  const [report, setReport] = useState<FinalReport | null>(null);
  const [error, setError] = useState<ErrorEventData | null>(null);

  // Hold the live connection in a ref so re-renders don't lose it and we
  // can close it on a new run or on unmount.
  const esRef = useRef<EventSource | null>(null);

  const close = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
  }, []);

  const start = useCallback(
    (userId: string) => {
      // A fresh run: tear down any prior connection and reset state.
      close();
      setStatuses([]);
      setReport(null);
      setError(null);
      setPhase("streaming");

      const url = `${API_BASE}/api/generate-report?user_id=${encodeURIComponent(userId)}`;
      const es = new EventSource(url);
      esRef.current = es;

      // Footgun #1: one listener per NAMED event.
      es.addEventListener("status", (e: MessageEvent) => {
        const data = JSON.parse(e.data) as StatusEventData;
        setStatuses((prev) => [...prev, data]);
      });

      es.addEventListener("report_complete", (e: MessageEvent) => {
        const data = JSON.parse(e.data) as FinalReport;
        setReport(data);
        setPhase("done");
        close(); // Footgun #2: terminal event — stop the auto-reconnect.
      });

      es.addEventListener("error", (e: MessageEvent) => {
        // Application-level error event from the backend (has a JSON body).
        // Distinct from a transport error (handled in onerror below), which
        // carries no data. Guard on e.data to tell them apart.
        if (e.data) {
          const data = JSON.parse(e.data) as ErrorEventData;
          setError(data);
        } else {
          setError({ code: "STREAM_ERROR", message: "Connection failed." });
        }
        setPhase("error");
        close();
      });

      // Transport-level failure (server down, network drop, CORS). Fires
      // with no data. Without closing here, EventSource would keep retrying.
      es.onerror = () => {
        // If the stream already finished cleanly, esRef was nulled by
        // close() and this is just the post-close blip — ignore it.
        if (esRef.current === null) return;
        setError({ code: "STREAM_ERROR", message: "Connection to the report stream failed." });
        setPhase("error");
        close();
      };
    },
    [close],
  );

  // Close the connection if the component unmounts mid-stream.
  useEffect(() => close, [close]);

  return { phase, statuses, report, error, start };
}
