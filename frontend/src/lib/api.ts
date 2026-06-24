/**
 * Typed fetch wrappers for the REST endpoints.
 *
 * Auth (V9): user-scoped calls attach an `Authorization: Bearer` token minted
 * by the same-origin Next /api/token route (signed from the session). The
 * backend verifies it and derives the user_id from the token, not the request.
 * getReport (a uuid4 capability URL, reused by V15 public sharing) and
 * validateTicker (public market data) stay unauthenticated.
 *
 * On type safety: res.json() is typed `any`, and the Promise<T> return
 * annotation is an unchecked assertion — the backend's Pydantic response_model
 * is the runtime guarantee.
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
  DeliveryPreferenceInput,
} from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL;

// ─── API auth token (V9) ───
// A short-lived HS256 token minted from the session by the Next /api/token
// route. Cached and refreshed a minute before its 5-minute expiry so most calls
// reuse it. The EventSource SSE (which can't set headers) reads it via
// getApiToken and passes it as a query param; everything else uses authHeaders.
let _tokenCache: { token: string; fetchedAt: number } | null = null;
const _TOKEN_TTL_MS = 4 * 60 * 1000;

export async function getApiToken(): Promise<string> {
  const now = Date.now();
  if (_tokenCache && now - _tokenCache.fetchedAt < _TOKEN_TTL_MS) {
    return _tokenCache.token;
  }
  const res = await fetch("/api/token"); // same-origin Next route
  if (!res.ok) throw new Error(`Could not get API token: HTTP ${res.status}`);
  const { token } = (await res.json()) as { token: string };
  _tokenCache = { token, fetchedAt: now };
  return token;
}

export async function authHeaders(): Promise<Record<string, string>> {
  // Returns {} when there's no session (e.g. the guest demo). The backend opens
  // the demo user's read endpoints; any other user without a token then 401s.
  try {
    return { Authorization: `Bearer ${await getApiToken()}` };
  } catch {
    return {};
  }
}

export async function getPortfolio(userId: string): Promise<PortfolioResponse> {
  const res = await fetch(`${API_BASE}/api/portfolio/${userId}`, {
    headers: await authHeaders(),
  });
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
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
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
  const res = await fetch(`${API_BASE}/api/memories/${userId}`, {
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error(`getMemories failed: HTTP ${res.status}`);
  return res.json();
}

export async function deleteMemories(
  userId: string,
): Promise<{ user_id: string; deleted: number }> {
  const res = await fetch(`${API_BASE}/api/memories/${userId}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error(`deleteMemories failed: HTTP ${res.status}`);
  return res.json();
}

export async function getReportsHistory(userId: string): Promise<ReportSummary[]> {
  const res = await fetch(`${API_BASE}/api/reports/history/${userId}`, {
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error(`getReportsHistory failed: HTTP ${res.status}`);
  return res.json();
}

// Public capability URL (uuid4) — no auth, reused by V15 public report sharing.
export async function getReport(reportId: string): Promise<ReportDetail> {
  const res = await fetch(`${API_BASE}/api/reports/${reportId}`);
  if (!res.ok) throw new Error(`getReport failed: HTTP ${res.status}`);
  return res.json();
}

export async function getReportSeries(
  userId: string,
): Promise<ReportSeriesPoint[]> {
  const res = await fetch(`${API_BASE}/api/reports/series/${userId}`, {
    headers: await authHeaders(),
  });
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
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
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

export async function getDeliveryPreferences(
  userId: string,
): Promise<DeliveryPreferencesView> {
  const res = await fetch(`${API_BASE}/api/delivery-preferences/${userId}`, {
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to load delivery preferences (${res.status})`);
  return res.json();
}

export async function putDeliveryPreferences(
  userId: string,
  input: DeliveryPreferenceInput,
): Promise<DeliveryPreference> {
  const res = await fetch(`${API_BASE}/api/delivery-preferences/${userId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    // The backend's address-gate returns 422 with a useful detail message.
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `Failed to save preferences (${res.status})`);
  }
  return res.json();
}

// Mirrors GET /api/ticker/validate (api/portfolio.py). Public market data — no
// auth. `found:false` is a normal 200 (unknown ticker); a thrown error means a
// real fetch failure (e.g. 502), which callers treat as "couldn't verify".
export interface TickerValidation {
  found: boolean;
  symbol: string;
  name?: string;
  price?: number;
  currency?: string; // "USD" or "ILS" (TASE)
}

// Public: USD->ILS rate for the base-currency display toggle (V17). No auth.
export async function getFxRate(): Promise<{ ils_per_usd: number }> {
  const res = await fetch(`${API_BASE}/api/fx/usd-ils`);
  if (!res.ok) throw new Error(`getFxRate failed: HTTP ${res.status}`);
  return res.json();
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
    headers: await authHeaders(),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    // 409 = "message the bot first, then connect"
    throw new Error(detail?.detail ?? `Failed to connect Telegram (${res.status})`);
  }
  return res.json();
}
