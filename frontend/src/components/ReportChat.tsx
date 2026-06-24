"use client";

/**
 * ReportChat — grounded Q&A panel under a report (V14).
 *
 * Asks POST /api/reports/{id}/ask and appends the streamed tokens to the latest
 * answer as they arrive — the app's first real token streaming. Visually
 * secondary to the report (slate, compact). Answers are grounded strictly in the
 * report by the backend prompt.
 */

import { useState, type FormEvent } from "react";
import { askReport } from "@/lib/api";

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
}

export function ReportChat({ reportId }: { reportId: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || streaming) return;
    setInput("");
    // Push the question + an empty answer we'll stream tokens into.
    setMessages((m) => [
      ...m,
      { role: "user", text: question },
      { role: "assistant", text: "" },
    ]);
    setStreaming(true);
    try {
      await askReport(reportId, question, (token) => {
        setMessages((m) => {
          const next = [...m];
          const last = next[next.length - 1];
          next[next.length - 1] = { role: "assistant", text: last.text + token };
          return next;
        });
      });
    } catch {
      setMessages((m) => {
        const next = [...m];
        const last = next[next.length - 1];
        next[next.length - 1] = {
          role: "assistant",
          text: last.text || "Sorry — I couldn't answer that right now.",
        };
        return next;
      });
    } finally {
      setStreaming(false);
    }
  }

  return (
    <section className="rounded-[4px] border border-line bg-card p-5">
      <h2 className="mb-3 font-serif text-lg font-medium tracking-wide text-ink">
        Ask about this report
      </h2>

      {messages.length > 0 && (
        <div className="mb-3 space-y-3">
          {messages.map((m, i) => (
            <div
              key={i}
              className={
                m.role === "user"
                  ? "text-sm text-muted"
                  : "text-sm leading-relaxed text-muted"
              }
            >
              <span className="mr-2 text-xs uppercase tracking-wider text-faint">
                {m.role === "user" ? "You" : "Pilot"}
              </span>
              {m.text ||
                (streaming && i === messages.length - 1 ? "…" : "")}
            </div>
          ))}
        </div>
      )}

      <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Why reduce AAPL?"
          disabled={streaming}
          className="min-h-[40px] flex-1 rounded-[3px] border border-field bg-card px-3 py-2 text-sm text-ink placeholder:text-faint focus:border-forest focus:outline-none disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={streaming || input.trim() === ""}
          className="min-h-[40px] rounded-[2px] bg-forest px-4 py-2 text-sm font-medium text-paper transition-colors hover:bg-forest-deep disabled:opacity-50"
        >
          {streaming ? "…" : "Ask"}
        </button>
      </form>
      <p className="mt-2 text-xs text-faint">
        Answers come only from this report — not financial advice.
      </p>
    </section>
  );
}
