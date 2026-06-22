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

export interface AssetAllocation {
  asset: string;
  pct: number; // share of total portfolio value, 0..100
  value_usd: number; // this asset's value in USD
}

export interface FinalReport {
  portfolio_valuation: PortfolioValuation;
  market_insights: MarketInsight[];
  rebalancing_recommendations: RebalancingRecommendation[];
  summary_narrative: string;
  confidence: number; // 0..1
  // Value-weighted allocation (V10a). Optional so reports archived before
  // V10a (which lack the field) still type-check when replayed from history.
  portfolio_composition?: AssetAllocation[];
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
  | { type: "human_input_required"; data: HumanInputRequiredData }
  | { type: "memory_saved"; data: MemorySavedData }
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

export interface ProposedMemory {
  insight: string;
  context?: string;
}

export interface HumanInputRequiredData {
  thread_id: string;
  type: string; // "memory_review"
  payload: { proposed_memories: ProposedMemory[] };
}

export interface MemorySavedData {
  count: number;
}

export type Cadence = "daily" | "every_n_days" | "weekly";

// The stored preference, as returned inside the GET view and by PUT.
export interface DeliveryPreference {
  user_id: string;
  deliver_telegram: boolean;
  deliver_email: boolean;
  cadence: Cadence;
  interval_days: number | null; // set when cadence === "every_n_days"
  weekday: number | null;       // 0=Mon … 6=Sun, set when cadence === "weekly"
  send_time_local: string;      // "HH:MM:SS" wall-clock in `timezone`
  timezone: string;             // IANA name, e.g. "Asia/Jerusalem"
  enabled: boolean;
  last_sent_at: string | null;  // ISO UTC, or null if never sent
  updated_at: string;           // ISO UTC
}

// What GET /api/delivery-preferences/{user_id} returns: the preference plus
// the two "is this channel even usable" flags the page needs to gate the
// checkboxes (you can't enable email with no address on file, etc.).
export interface DeliveryPreferencesView {
  user_id: string;
  email_set: boolean;
  telegram_connected: boolean;
  preference: DeliveryPreference | null; // null until first saved
}

// The PUT body — note interval_days/weekday are conditionally required by the
// backend validators depending on cadence, hence optional here.
export interface DeliveryPreferenceInput {
  deliver_telegram: boolean;
  deliver_email: boolean;
  cadence: Cadence;
  interval_days?: number | null;
  weekday?: number | null;
  send_time_local: string; // "HH:MM" from an <input type="time"> is fine
  timezone: string;
  enabled: boolean;
}
