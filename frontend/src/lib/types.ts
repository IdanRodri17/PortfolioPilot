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
  cost_basis?: Record<string, number>; // symbol -> buy price (native currency), optional (V20)
  risk_profile: RiskProfile;
}

export interface PortfolioResponse {
  user_id: string;
  assets: Record<string, number>;
  cost_basis?: Record<string, number>; // symbol -> buy price (V20); may be absent on old rows
  risk_profile: RiskProfile;
  updated_at: string; // ISO-8601 timestamp from the server
}

// Watchlist (V25): tickers the user tracks but doesn't own.
export interface WatchlistItem {
  symbol: string;
  price: number | null;
  change_24h_percent: number | null;
}
export interface WatchlistView {
  symbols: string[];
  items: WatchlistItem[];
}

// Trending / popular stocks for the discovery card (V22). Public market data.
export interface TrendingStock {
  symbol: string;
  name: string;
  price: number;
  change_24h_percent: number;
}

// ─── Report domain (mirrors schemas/report.py) ───

export type Sentiment = "Positive" | "Neutral" | "Negative";
export type RecommendationAction = "reduce" | "increase" | "hold";

export interface BenchmarkChange {
  name: string;
  symbol: string;
  change_24h_percent: number;
}

export interface PortfolioValuation {
  total_usd: number;
  change_24h_percent: number;
  // Cost-basis P/L (V20) — null/absent when no buy prices are set.
  total_cost_basis_usd?: number | null;
  total_gain_loss_usd?: number | null;
  total_gain_loss_pct?: number | null;
  // Market benchmarks' 24h change (V24); absent for pre-V24 reports.
  benchmark_24h?: BenchmarkChange[];
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
  value_usd: number; // this asset's value in its own currency
  currency?: string; // "USD" or "ILS" (TASE); optional for pre-V16 reports
  // Cost-basis P/L (V20) — null/absent unless a buy price is set for this holding.
  cost_basis_usd?: number | null;
  gain_loss_usd?: number | null;
  gain_loss_pct?: number | null;
}

export interface SectorAllocation {
  sector: string;
  pct: number; // sector share of total portfolio value, 0..100
}

export interface SectorConcentration {
  sectors: SectorAllocation[]; // largest first
  dominant_sector: string | null;
  concentration: "high" | "moderate" | "low" | "unknown";
  diversification_score: number; // 0..1, higher = more diversified
  note: string;
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
  // Value-weighted sector concentration (V11). Optional/null for pre-V11 reports.
  sector_concentration?: SectorConcentration | null;
}

// SSE narrative streaming (V19): after report_complete, the backend replays the
// summary word-by-word — each narrative_token carries one chunk; narrative_done
// (no payload) signals the typing is finished.
export interface NarrativeTokenData {
  text: string;
}

// Since-last-report diff (mirrors ReportDiff in schemas/report.py; V12b).
export interface SentimentFlip {
  asset: string;
  previous: Sentiment;
  current: Sentiment;
}

export interface ReportDiff {
  first_report: boolean;
  valuation_delta_pct: number | null;
  sentiment_flips: SentimentFlip[];
  recommendations_new: string[];
  recommendations_resolved: string[];
}

// AI self-grading of the prior report's calls (mirrors AdviceReview; V13).
export interface GradedCall {
  asset: string;
  action: RecommendationAction; // "reduce" | "increase" | "hold"
  recommended_at: string; // ISO date of the prior report
  pct_move_since: number | null;
  grade: "good" | "poor" | "neutral" | "insufficient_data";
}

export interface AdviceReview {
  recommended_at: string | null;
  calls: GradedCall[];
  summary: string;
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
  | { type: "report_diff"; data: ReportDiff }
  | { type: "advice_review"; data: AdviceReview }
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

// One point of the value trend (mirrors GET /api/reports/series/{user_id}).
export interface ReportSeriesPoint {
  generated_at: string; // ISO-8601, oldest first (one point per calendar day)
  total_usd: number;
  change_24h_percent: number | null;
  // V24: rebased benchmark overlays (null where unavailable).
  sp500_usd?: number | null;
  nasdaq_usd?: number | null;
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
// V23: what a scheduled send contains.
export type DigestMode = "full" | "changes_only";

// V23: the lightweight what-changed digest (deltas vs the last report).
export interface DigestMover {
  symbol: string;
  change_24h_percent: number;
  value_usd: number;
}
export interface ChangeDigest {
  prev_date: string | null;
  total_usd: number;
  value_delta_usd: number | null;
  value_delta_pct: number | null;
  movers: DigestMover[];
  top_now: { symbol: string; pct: number } | null;
  top_prev: { symbol: string; pct: number } | null;
  notable: boolean;
}
export interface DigestPreview {
  available: boolean;
  reason?: string;
  digest?: ChangeDigest;
}

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
  digest_mode: DigestMode;      // V23: full report vs what-changed digest
  // Threshold alerts (V18). A null threshold = that rule is off.
  alerts_enabled: boolean;
  alert_price_move_pct: number | null;
  alert_portfolio_move_pct: number | null;
  alert_concentration_pct: number | null;
  alert_cooldown_hours: number;
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
  digest_mode: DigestMode; // V23
  // Threshold alerts (V18). null = the rule is off.
  alerts_enabled: boolean;
  alert_price_move_pct?: number | null;
  alert_portfolio_move_pct?: number | null;
  alert_concentration_pct?: number | null;
  alert_cooldown_hours: number;
}

// What GET /api/alerts/preview/{user_id} returns: the alert lines that would
// fire right now (ignoring the master switch + cooldown), for the Preview button.
export interface AlertPreview {
  alerts: string[];
  evaluated_symbols?: string[];
  alerts_enabled?: boolean;
  skipped?: string;
}
