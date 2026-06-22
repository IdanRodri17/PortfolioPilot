/**
 * Typed fetch wrappers for the REST portfolio endpoints.
 *
 * Only the two CRUD calls live here. The generate-report endpoint is an
 * SSE stream, not a fetch-and-parse call — it is consumed via EventSource
 * in the step-3 useReportStream hook, not from this module.
 *
 * On type safety: res.json() is typed `any`, and the Promise<T> return
 * annotation is an unchecked assertion — TypeScript trusts the body
 * matches T but does not verify it at runtime. The backend's Pydantic
 * response_model is what guarantees the shape on the wire, so a runtime
 * validator (e.g. zod) here would be belt-and-braces the backend already
 * provides. If the contract ever drifted, that's where one would go.
 */

import type {
  PortfolioRequest,
  PortfolioResponse,
  Memory,
  ReportSummary,
  ReportSeriesPoint,
  ReportDetail,
  DeliveryPreferencesView,
  DeliveryPreference, 
  DeliveryPreferenceInput
} from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL;

export async function getPortfolio(
  userId: string,
): Promise<PortfolioResponse> {
  const res = await fetch(`${API_BASE}/api/portfolio/${userId}`);
  if (!res.ok) {
    throw new Error(
      `getPortfolio(${userId}) failed: HTTP ${res.status} ${res.statusText}`,
    );
  }
  return res.json();
}

export async function upsertPortfolio(
  payload: PortfolioRequest,
): Promise<PortfolioResponse> {
  const res = await fetch(`${API_BASE}/api/portfolio`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(
      `upsertPortfolio failed: HTTP ${res.status} ${res.statusText}`,
    );
  }
  return res.json();
}

export async function getMemories(userId: string): Promise<Memory[]> {
  const res = await fetch(`${API_BASE}/api/memories/${userId}`);
  if (!res.ok) throw new Error(`getMemories failed: HTTP ${res.status}`);
  return res.json();
}

export async function deleteMemories(
  userId: string,
): Promise<{ user_id: string; deleted: number }> {
  const res = await fetch(`${API_BASE}/api/memories/${userId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`deleteMemories failed: HTTP ${res.status}`);
  return res.json();
}

export async function getReportsHistory(userId: string): Promise<ReportSummary[]> {
  const res = await fetch(`${API_BASE}/api/reports/history/${userId}`);
  if (!res.ok) throw new Error(`getReportsHistory failed: HTTP ${res.status}`);
  return res.json();
}

export async function getReport(reportId: string): Promise<ReportDetail> {
  const res = await fetch(`${API_BASE}/api/reports/${reportId}`);
  if (!res.ok) throw new Error(`getReport failed: HTTP ${res.status}`);
  return res.json();
}

export async function getReportSeries(
  userId: string,
): Promise<ReportSeriesPoint[]> {
  const res = await fetch(`${API_BASE}/api/reports/series/${userId}`);
  if (!res.ok) throw new Error(`getReportSeries failed: HTTP ${res.status}`);
  return res.json();
}

/**
 * Ask a grounded question about one report; stream the answer token-by-token.
 * POST carries the question in the body, so we read the SSE response with a
 * stream reader (EventSource is GET-only). onToken fires per token; resolves on
 * the `done` event, throws on `error` or transport failure.
 */
export async function askReport(
  reportId: string,
  question: string,
  onToken: (text: string) => void,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/reports/${reportId}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok || !res.body) {
    throw new Error(`askReport failed: HTTP ${res.status}`);
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
      let event = "message";
      const dataLines: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length === 0) continue;
      let data: unknown;
      try {
        data = JSON.parse(dataLines.join("\n"));
      } catch {
        continue;
      }
      if (event === "token") {
        onToken((data as { text: string }).text);
      } else if (event === "done") {
        return;
      } else if (event === "error") {
        throw new Error((data as { message?: string }).message ?? "ask failed");
      }
    }
  }
}

// (uses the same API_BASE constant your other helpers use)

export async function getDeliveryPreferences(
  userId: string,
): Promise<DeliveryPreferencesView> {
  const res = await fetch(`${API_BASE}/api/delivery-preferences/${userId}`);
  if (!res.ok) throw new Error(`Failed to load delivery preferences (${res.status})`);
  return res.json();
}

export async function putDeliveryPreferences(
  userId: string,
  input: DeliveryPreferenceInput,
): Promise<DeliveryPreference> {
  const res = await fetch(`${API_BASE}/api/delivery-preferences/${userId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    // The backend's address-gate returns 422 with a useful detail message.
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `Failed to save preferences (${res.status})`);
  }
  return res.json();
}

// Mirrors GET /api/ticker/validate (api/portfolio.py). `found:false` is a
// normal 200 response (unknown ticker); a thrown error means a real fetch
// failure (e.g. 502), which callers treat as "couldn't verify", not "invalid".
export interface TickerValidation {
  found: boolean;
  symbol: string;
  name?: string;
  price?: number;
}

export async function validateTicker(symbol: string): Promise<TickerValidation> {
  const res = await fetch(
    `${API_BASE}/api/ticker/validate?symbol=${encodeURIComponent(symbol)}`,
  );
  if (!res.ok) {
    throw new Error(`validateTicker(${symbol}) failed: HTTP ${res.status}`);
  }
  return res.json();
}

export async function connectTelegram(
  userId: string,
): Promise<{ telegram_connected: boolean; chat_id: string }> {
  const res = await fetch(`${API_BASE}/api/telegram/connect/${userId}`, {
    method: "POST",
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    // 409 = "message the bot first, then connect"
    throw new Error(detail?.detail ?? `Failed to connect Telegram (${res.status})`);
  }
  return res.json();
}
