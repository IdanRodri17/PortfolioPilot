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
