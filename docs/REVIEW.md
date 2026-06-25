# PortfolioPilot — Review & Build Backlog

> Source: a 7-agent deep review (architecture, API/data, frontend, security, financial
> correctness, DevOps/testing, product). This file is the **working spec** — each item has
> enough context to build it well. Priorities: 🔴 must-fix, 🟠 should-fix, 🟢 nice. Effort: S/M/L.

## Verdict (the honest version)

Top-decile engineering for a solo project — LangGraph multi-agent fan-out, Reflexion guardrail,
HITL memory with checkpointer pause/resume, pgvector recall, deterministic-numbers-in-Python,
live SSE, real Israeli-market/₪ support, 20 tagged versions with briefs. **But it's currently an
engineering showcase, not yet a sticky product:** zero tests, the daily digest re-runs the *same*
full report (noise, not signal), and there's no onboarding / growth / monetization. The path to a
real product: make it **proactive** (signal-not-repetition) and **discoverable**, and pick a sharp
position (Israeli+global AI digest with memory).

### Two review findings we intentionally OVERRIDE (don't "fix" these)
- **TASE P/L FX is NOT a bug.** `_compute_pnl` converts *both* buy and current price at the
  *current* rate, so FX cancels and the **% is the stock's native return** (FX-neutral); the $ is
  today's USD value of that gain. Switching to purchase-date FX would *add* currency P&L — a product
  choice, not a defect. If we ever want "total return incl. FX", store the buy-date rate then.
- **Composition % is already deterministic** — `synthesizer._build_composition` uses
  `risk_analysis.total_value_usd`, not the LLM. Only the *headline* valuation is LLM-authored (see
  V21). Composition needs no fix.

---

## Roadmap (versioned)

| Ver | Item | Track | Effort |
|---|---|---|---|
| **V21** | Deterministic headline valuation + starter test suite | correctness/foundation | M |
| **V22** | Trending/popular stocks card (+ optional add-to-portfolio) | feature | M |
| **V23** | "What changed since last report" lightweight digest mode | feature (keystone) | L |
| **V24** | Benchmark vs S&P 500 / Nasdaq (report + history overlay) | feature | M |
| **V25** | Watchlist (track tickers without owning) | feature | M |
| **V26** | Portfolio import (CSV + natural-language paste) | feature/onboarding | M |
| **V27** | Onboarding flow (new user → import → risk → first report) | feature | M |
| **V28** | Alert depth: sentiment-flip + price-target alerts | feature | M |
| **V29** | Earnings/dividend calendar woven into the narrative | feature | M |
| **V30** | Crypto as its own sector (stop "Uncategorized") | correctness | S |
| **—** | Infra/security track (below) — interleave as needed | hardening | varies |
| **Later** | Freemium paywall + analytics + growth loop | product/business | M–L |

---

## V21 — Deterministic headline valuation + test suite 🔴 (in progress)

**Problem.** `synthesizer.py` prompt (~line 89-90) tells the LLM to "compute `total_usd` and the
weighted `change_24h_percent`." So the *one number users trust most* (the hero `Portfolio value` and
the 24h move) is LLM-authored and can drift / mis-add, while everything else is deterministic. It can
also disagree with the donut total (which IS deterministic).

**Fix.**
- `backend/app/graph/nodes/risk_agent.py`: also compute the **value-weighted 24h change** from
  `market_data` (`sum(value_i * change_i) / total`) and return `total_change_24h_percent` in
  `risk_analysis` (and `0.0` in the no-data path). `total_value_usd` already exists.
- `backend/app/graph/nodes/synthesizer.py`: after building `report`, OVERRIDE
  `report.portfolio_valuation.total_usd = risk_analysis["total_value_usd"]` and
  `.change_24h_percent = risk_analysis["total_change_24h_percent"]` (same pattern as the V20 P/L
  totals + composition). The LLM may still draft them for context, but the deterministic values win.
- Guardrail runs after synthesizer, so it now validates the deterministic numbers. ✓

**Acceptance.** A generated report's `portfolio_valuation.total_usd` exactly equals the sum of
`portfolio_composition[].value_usd` (donut total); 24h change is the value-weighted mean. Verified
live + unit-tested.

**Test suite (the #1 "industry-standard" gap).** Add `pytest` and `backend/tests/` covering the
pure deterministic cores (no network/LLM/DB calls needed):
- `test_risk_agent.py` — `_compute_composition` (empty / single / multi / missing-price),
  `_compute_pnl` (no cost basis, US holding, **TASE ₪→USD**, NaN/zero-price guard, zero cost),
  `_check_violations` (single-asset cap, min-assets, crypto cap), and the new weighted-change.
- `test_alerts.py` — `_evaluate_rules` (price move, portfolio move, concentration) + `_on_cooldown`.
- `test_stock_data.py` — `is_tase`, `is_crypto` (and `_normalize_money` if present).
- (follow-up) `test_guardrail.py`, `test_delivery.py` (`_is_due`).
Run: `docker compose exec backend python -m pytest backend/tests -q` (add `pytest` to
`requirements.txt`; install in the container to run now). Target ≥70% on `graph/nodes/*` + `delivery/*`.

---

## V22 — Trending / popular stocks ⭐ (the user's idea)

**Why.** Converts a portfolio-*analysis* tool into a portfolio-*discovery* tool → a daily reason to
return. We already fan out `sentiment_agent` per symbol, so we can point it at trending tickers.

**Build.**
- Data source for "hot" tickers: Finnhub `/stock/news` or `/calendar`, Polygon trending, or a curated
  static list as a fallback (ship value even without a new API key). Add `TRENDING_*` to
  `core/config.py`; degrade gracefully if no key.
- `GET /api/trending?limit=10` (public, cached ~15 min) → `[{symbol, name, price, change_24h_percent,
  sentiment?}]`. Reuse `stock_data` for price/change; optionally run `sentiment_agent` on the top 3.
- Frontend: a **"Trending today"** card in the dashboard right band (Editorial styling: bg-card,
  forest/terracotta change, sentiment pill). Each row gets an optional **"+ Add to portfolio"** that
  prefills the editor (reduces friction).
- Exclude tickers already in the user's portfolio.

**Effort M.** Acceptance: card renders 5–10 trending names with live price/change; add-to-portfolio works.

---

## V23 — "What changed since last report" digest mode ⭐ (keystone)

**Why.** Today the scheduled daily send re-runs the full synthesizer → 7 near-identical emails/week =
noise. The product promise ("busy people get a digest") needs *deltas*, not repetition.

**Build.**
- A lightweight path that does NOT run the full graph: fetch current `market_data` + the user's
  *previous* archived report, then deterministically diff (you already have `_compute_report_diff` in
  `generate.py` for V12b — reuse/extend it): price moves, **sentiment flips**, concentration drift
  (>2%), newly-relevant recalled memories, P/L change.
- New renderer (`delivery/renderers.py`): a compact "what changed" Telegram/email body (headline +
  bullet deltas + link to the full report). Add a `digest_mode` to `DeliveryPreference`
  (`full` | `changes_only`, default `changes_only` for daily, `full` for weekly).
- `dispatcher.deliver_for_user` branches on `digest_mode`: `changes_only` skips the graph (cheap,
  fast, no LLM or one tiny LLM call for a one-line summary).
- Wire the memory system to *initiate*: "You flagged TSLA as overconcentrated — it's now 45% (+3%)."

**Effort L.** Acceptance: a daily `changes_only` digest sends only when something changed (or a "quiet
day" one-liner), costs ≪ a full report, and reads as signal.

---

## V24 — Benchmark vs S&P 500 / Nasdaq

**Why.** Answers "am I beating the market?" — the #1 user question; today the portfolio is analyzed in
a vacuum.
**Build.** Fetch SPY/QQQ via `stock_data` (period for the same window). Add benchmark return to the
report (deterministic, in `risk_agent` or at the API boundary) and a benchmark line overlay on the
`/history` value-trend chart (Recharts supports multiple `<Line>`s). Optional: sector weight vs the
index. **Effort M.**

## V25 — Watchlist
**Why.** Track/due-diligence tickers without owning them (table-stakes).
**Build.** `User.watchlist` JSONB `{symbols: [...]}` (light-migration). CRUD `GET/PUT
/api/watchlist/{user_id}`. Dashboard "Watching" card (sentiment + 24h change). Optional daily
sentiment run on watchlist symbols; later, watchlist alerts. **Effort M.**

## V26 — Portfolio import (CSV + natural-language)
**Why.** Manual row-by-row entry is the single highest-friction step for a real signup.
**Build.** (a) CSV: `POST /api/portfolio/import-csv` (symbol, qty, optional buy_price); parse + validate
+ preview. (b) NL paste: a field → one LLM call extracting `{symbol, qty}` from "10 Apple, 0.5 BTC,
1000₪ TEVA" → user reviews → save. Reuse ticker validation (V10). **Effort M.**

## V27 — Onboarding flow
**Why.** New users land on a blank dashboard with a non-working Generate button.
**Build.** Detect no-portfolio → `/onboarding`: import (V26) → risk profile → delivery prefs → auto first
report. Optional welcome email + a dashboard tutorial card. **Effort M.**

## V28 — Alert depth (sentiment-flip + price-target)
**Build.** (a) Sentiment-flip: compare this report's `market_insights[symbol].sentiment` to the prior
report; fire on flip. (b) Price-target: `price_targets` JSONB on `DeliveryPreference`
(`{symbol: {type: sell_at|buy_at, price}}`) + `/settings` UI; evaluate on the alert tick (reuse V18
cooldown). Prioritize sentiment-flip (no new UI). **Effort M.**

## V29 — Earnings/dividend calendar
**Build.** Finnhub `/calendar/earnings` + dividend data (yfinance `info`); add
`state["market_calendar"]`; synthesizer weaves "NVDA reports in 3 days" into the narrative; optional
dashboard "Calendar" card. **Effort M.**

## V30 — Crypto as its own sector
**Build.** `stock_data.get_sector`: if `is_crypto(symbol)` return `"Cryptocurrency"`; `macro_context_agent`
then treats it as a normal sector (weight, diversification, concentration). **Effort S.**

---

## Infra / security / hardening track (interleave)

### 🔴 Must-fix
- **`/api/run-due-deliveries` is unauthenticated** (`api/deliveries.py`) → anyone can trigger bulk
  sends + LLM spend. Gate with a shared-secret header (`X-Scheduler-Token` vs an env var) or remove
  the public endpoint and keep only the in-process call.
- **No rate limiting** → add `slowapi`: `/api/auth/*` (brute-force), `/api/generate-report` (cost),
  `/api/deliveries/run-now`.
- **No tests** → V21 starts the suite; expand each version.

### 🟠 Should-fix
- **CI/CD:** `.github/workflows/ci.yml` — `ruff` + `pytest` (backend), `tsc --noEmit` + `eslint`
  (frontend), docker build smoke. Merge-blocking.
- **Migrations → Alembic.** `light_migrations.py` can't do renames/type-changes/rollback. Adopt
  Alembic (move existing ALTERs into `0001_initial`), keep `create_all` for fresh DBs.
- **Scheduler multi-worker bug.** In-process `APScheduler` double-fires under `gunicorn -w N`
  (N schedulers). Move to an authed `/run-due` endpoint hit by an external cron, or Celery/RQ.
- **Observability:** structured JSON logs (`python-json-logger`) + request-id middleware + **Sentry**
  (`sentry-sdk`, ~5 lines) + basic Prometheus metrics (graph time, API latency, delivery success).
- **Pin deps:** pin `requirements.txt` (only `apscheduler<4` is pinned) and the OpenAI model id
  (`gpt-4o-2024-08-06`, not `gpt-4o`); commit `package-lock.json` and gate it in CI.
- **LLM cost tracking + per-user budget** before scaling the scheduler (a 100-symbol portfolio fans
  out 100 sentiment calls). Log `{model, tokens_in, tokens_out, cost}`; soft/hard monthly caps.
- **SQL-native upsert** (`ON CONFLICT`) for portfolio + delivery prefs (removes the read-then-write
  race acknowledged in `api/portfolio.py`).
- **Frontend:** add `app/error.tsx` boundary (a Recharts crash currently blanks the page); consider
  TanStack Query so editor↔dashboard share/invalidate portfolio data; extract one shared SSE parser
  (duplicated in `useReportStream.resume` + `api.askReport`); add `sessionStorage` token (per-tab).
- **Telegram link trust:** audit the connect flow — ensure a forged `chat_id` can't hijack linking
  (sign/verify or confirm via a one-time code).

### 🟢 Nice
- Production Dockerfiles (non-root, no `--reload`, healthcheck, `npm run build`), graceful shutdown
  (`scheduler.shutdown(wait=True)`), DB pool tuning, backups doc, a `_migrations_run` audit table,
  input max-lengths, JSONB CHECK constraints, model version pinning + `seed`, structured error
  taxonomy, accessibility pass (labels, modal ARIA, focus trap), analytics (Plausible/Mixpanel).

---

## Data-correctness notes (carry into every feature)
- **Headline valuation** → deterministic (V21).
- **Single data source (yfinance):** no fallback / staleness / rate-limit detection. Add (a) 429/403
  detection + backoff (`tenacity`), (b) staleness check (warn if price > 1h old), (c) a cached
  prior-close fallback, (d) a second provider for top holdings. We already `dropna` NaN closes (V20.1).
- **CoinGecko** rate-limit: add backoff + batch multi-coin queries.
- **FX fallback (3.7)** is hardcoded — make it an env var / refresh source; log when used.
- **Sector strings** from yfinance aren't normalized (could get "tech"/"Tech"/"Technology") — add a
  normalizer (pairs with V30).
- **Frontend money guards:** `formatMoney`/`displayMoney` should return `"—"` for non-finite input.
