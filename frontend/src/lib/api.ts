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

import type { PortfolioRequest, PortfolioResponse } from "@/lib/types";

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
