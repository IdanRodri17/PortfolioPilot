/**
 * TypeScript mirrors of the backend contracts.
 *
 * Hand-kept in sync with the FastAPI Pydantic schemas
 * (backend/app/schemas/report.py and portfolio.py) and the SSE event
 * taxonomy (backend/app/api/generate.py). TypeScript types are erased at
 * runtime — nothing here validates a payload; they only describe the
 * shape we expect so the compiler and editor can check our usage. The
 * backend's Pydantic response_model is the actual runtime guarantee.
 *
 * Pydantic -> TS mapping used throughout:
 *   str                -> string
 *   float / int        -> number
 *   bool               -> boolean
 *   Literal["a","b"]   -> "a" | "b"            (string-literal union)
 *   List[X]            -> X[]
 *   Dict[str, float]   -> Record<string, number>
 *   datetime           -> string               (no JSON date type; it's
 *                                                an ISO-8601 string on the wire)
 */

// ─── Portfolio domain (mirrors schemas/portfolio.py) ───

export type RiskProfile = "conservative" | "balanced" | "aggressive";

export interface PortfolioRequest {
  user_id: string;
  assets: Record<string, number>; // symbol -> quantity
  risk_profile: RiskProfile;
}

export interface PortfolioResponse {
  user_id: string;
  assets: Record<string, number>;
  risk_profile: RiskProfile;
  updated_at: string; // ISO-8601 timestamp from the server
}

// ─── Report domain (mirrors schemas/report.py) ───

export type Sentiment = "Positive" | "Neutral" | "Negative";
export type RecommendationAction = "reduce" | "increase" | "hold";

export interface PortfolioValuation {
  total_usd: number;
  change_24h_percent: number;
}

export interface MarketInsight {
  asset: string;
  sentiment: Sentiment;
  summary: string;
}

export interface RebalancingRecommendation {
  action: RecommendationAction;
  asset: string;
  target_change_pct: number;
  rationale: string;
}

export interface FinalReport {
  portfolio_valuation: PortfolioValuation;
  market_insights: MarketInsight[];
  rebalancing_recommendations: RebalancingRecommendation[];
  summary_narrative: string;
  confidence: number; // 0..1
}

// ─── SSE event taxonomy (mirrors api/generate.py _format_sse calls) ───
//
// The backend sends each event as `event: <name>` + `data: <json>`. We
// model the data payload per event name, then tie them together in a
// discriminated union keyed by `type`. The `type` field is the
// discriminant: a switch on it narrows `data` to the right shape, which
// is exactly how the step-3 EventSource hook consumes the stream.
//
// `token` and `human_input_required` exist in the SRS taxonomy but are
// NOT emitted in V4 (token: the synthesizer uses structured output;
// human_input_required: arrives with V6's interrupt()). They are left out
// here deliberately and join when their backend code lands — the same
// per-version growth discipline as PortfolioState and requirements.txt.

export type StatusPhase = "start" | "end";

export interface StatusEventData {
  node: string;
  phase: StatusPhase;
  metadata: { symbol?: string }; // symbol present only on sentiment_agent branches
}

export interface ErrorEventData {
  code: string;
  message: string;
}

export type ReportStreamEvent =
  | { type: "status"; data: StatusEventData }
  | { type: "report_complete"; data: FinalReport }
  | { type: "error"; data: ErrorEventData };

// ─── Memory + report history (mirrors api/memories.py, api/reports.py) ───

export interface Memory {
  key: string;
  insight: string;
  created_at: string | null;
}

export interface ReportSummary {
  report_id: string;
  generated_at: string;
  confidence_flag: string | null; // "high" | "low" | null
  total_usd: number | null;
  change_24h_percent: number | null;
}

export interface ReportDetail {
  report_id: string;
  user_id: string;
  generated_at: string;
  confidence_flag: string | null;
  report: FinalReport;
}
