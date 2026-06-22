# PortfolioPilot — Claude Code Prompt Playbook (V10 → V16)

> Companion to `PortfolioPilot_Upgrades_BuildSpec.md`. Each prompt below is
> copy-paste-ready for Claude Code, scoped to your one-to-two-files-per-session
> cadence, and ends with the smoke test and the exact commit. Run them in order.
> Attach the build spec to the Claude Code session so it has the full rationale.

---

## How to use this file

- **One prompt = one session = one or two files = one commit.** Don't batch.
- **Paste the "Standing rules" block once** at the start of each session (or keep
  it in `CLAUDE.md`), then paste the numbered prompt.
- **Run `git` from the repo root.** Activate the venv for backend work
  (`source backend/.venv/Scripts/activate` on Git Bash).
- **Do the smoke test yourself** before letting it commit. If it fails, fix
  forward in the same session; don't tag a broken increment.

### Standing rules (prepend to every session)

```
You are working on PortfolioPilot, an existing, shipped codebase. Follow these
rules without exception:

1. SCOPE: Touch only the files named in this prompt. Do not refactor, rename, or
   "improve" unrelated code. If something out of scope looks wrong, note it in
   your summary — do not change it.
2. NEXT.JS: This repo is Next.js 16.2.6 + React 19 — NOT the version in your
   training data. Before writing or editing any frontend file, read the relevant
   guide under node_modules/next/dist/docs/ and heed deprecations. Hooks are the
   FIRST lines in the component body. Tailwind is v4. Recharts 3.8.1 is ALREADY
   installed — do not add a charting dependency.
3. BACKEND BOUNDARY: The LangGraph graph is a pure portfolio_dict -> FinalReport
   pipeline and must not learn that Postgres exists. DB lookups and report
   archiving live in FastAPI handlers, never in graph nodes. The only sanctioned
   DB-in-graph exception is the memory nodes' injected BaseStore.
4. DETERMINISTIC NUMBERS NEVER PASS THROUGH THE LLM. Percentages, deltas, sector
   shares, and price moves are computed in Python and attached to the payload —
   never produced by with_structured_output.
5. MIGRATIONS: No Alembic. If you need a schema change, output the exact surgical
   ALTER TABLE statement for me to run by hand (heredoc-safe for Git Bash). Make
   new payload/schema fields optional with safe defaults so old archived reports
   still deserialize.
6. STYLE: Match the surrounding code and docstring voice. Dark slate theme;
   emerald = good/positive, rose = bad/reduce, slate = neutral, amber reserved
   for in-flight. Keep the not-financial-advice framing on any new analysis UI.
7. FINISH EVERY TASK with: (a) the smoke-test steps I should run, and (b) a
   conventional commit in the form feat(vN): <subject> with a multi-line body.
   Do NOT run the commit yourself — propose it and wait.
```

---

# Prelude

### Prompt 0 — README & roadmap refresh

```
Refactor README.md ONLY to reflect the real state of the codebase. Today the
build-status table says V5-in-progress with V6–V8 "planned", but the code
actually ships: the Reflexion guardrail loop, the HITL interrupt()/Command(resume)
flow, the PostgresSaver checkpointer, scheduled Telegram + email delivery
(APScheduler, timezone-aware DeliveryPreference), and Auth.js v5 credential auth.

Tasks:
- Flip the Highlights legend items for guardrail, HITL memory approval, semantic
  memory, and delivery from 🚧/📋 to ✅.
- Rewrite the Build-status table so V1–V8 read Shipped and V9 (backend JWT
  verification) reads In progress.
- Re-anchor the Roadmap section to the upcoming V10+ items from
  PortfolioPilot_Upgrades_BuildSpec.md (allocation chart, concentration agent,
  report diffs, advice grading, report chat, demo + sharing).
- Do not touch any code or other docs.

Smoke test: a first-time reader can tell within 30 seconds that the app has real
auth, a self-correcting guardrail, HITL memory approval, and scheduled
multi-channel delivery.

Commit: docs(readme): correct build status to reflect shipped V6–V8 features
```

---

# V10a — Allocation donut

### Prompt 1 — Backend: surface composition deterministically

```
Goal: put the value-weighted allocation that risk_agent already computes onto
the report payload WITHOUT routing the percentages through the LLM.

Files: backend/app/schemas/report.py and backend/app/graph/nodes/synthesizer.py

In schemas/report.py:
- Add an AssetAllocation model: { asset: str, pct: float, value_usd: float }.
- Add portfolio_composition: List[AssetAllocation] = [] to the report contract.
- IMPORTANT: keep the LLM-bound schema free of portfolio_composition. The cleanest
  way: have the model fill a ReportBody (the existing fields — valuation,
  market_insights, rebalancing_recommendations, summary_narrative, confidence) and
  define FinalReport = ReportBody + portfolio_composition. Use ReportBody for
  with_structured_output; assemble FinalReport in the node.

In synthesizer.py:
- Call .with_structured_output(ReportBody) (not the full report).
- After the LLM returns, build portfolio_composition deterministically from
  state["risk_analysis"]["composition_pct"] and ["total_value_usd"]
  (value_usd = pct/100 * total_value_usd), and return
  {"final_report": FinalReport(**body.model_dump(), portfolio_composition=...)}.
- If composition_pct is empty, portfolio_composition is [].

Smoke test (curl): POST a portfolio for idan_demo, then
curl -N ".../api/generate-report?user_id=idan_demo" and confirm the
report_complete payload contains portfolio_composition with pcts matching
risk_agent (AAPL largest), and that total value_usd sums correctly.

Commit: feat(v10a): surface value-weighted composition on the report payload
```

### Prompt 2 — Frontend: the donut

```
Goal: render the new portfolio_composition as a Recharts donut on the dashboard.

Files: frontend/src/lib/types.ts, frontend/src/components/AllocationDonut.tsx (NEW),
and frontend/src/components/FinalReportView.tsx.

- Mirror AssetAllocation and add portfolio_composition to the FinalReport type.
- AllocationDonut.tsx: a Recharts donut (PieChart + Pie with innerRadius). Slice
  label "SYMBOL pct%"; centre label shows total USD. Use slate/emerald palette
  shades only — no rainbow. Recharts is v3.8.1 (already installed); verify
  label/legend props against the installed version, not v2 examples.
- In FinalReportView.tsx, render <AllocationDonut/> inside the valuation section.
  If portfolio_composition is empty, render an honest "no priced holdings" state.

Smoke test: generate a report on the dashboard; a donut appears with slices
matching the risk_agent percentages and a USD total in the centre.
npx tsc --noEmit is clean.

Commit: feat(v10a): render value-weighted allocation donut on the dashboard
```

---

# V10b — Ticker validation

### Prompt 3 — Backend: symbol lookup endpoint

```
Goal: a thin, cached endpoint to validate a ticker and return its name + price.

Files: backend/app/tools/stock_data.py and backend/app/api/portfolio.py.

- In stock_data.py add lookup_symbol(symbol) -> {"name": str, "price": float} | None,
  reusing the existing yfinance touch-point and the module's custom exception type.
  Cache results per symbol in-memory (yfinance .info is slow). Return None for an
  unknown ticker; raise the custom exception only on a real fetch failure.
- In portfolio.py add GET /api/ticker/validate?symbol=... that returns the lookup
  result, or 404-style {found: false} for unknown symbols.

Smoke test: curl ".../api/ticker/validate?symbol=AAPL" returns Apple + a price;
symbol=ZZZZ returns the not-found shape; a repeated call is served from cache.

Commit: feat(v10b): add cached ticker validation endpoint
```

### Prompt 4 — Frontend: inline validation in the editor

```
Goal: validate symbols as the user types in the portfolio editor.

Files: frontend/src/lib/api.ts and frontend/src/app/portfolio/page.tsx.

- api.ts: add validateTicker(symbol).
- portfolio/page.tsx: on a ~400ms debounce after a symbol field settles, call
  validateTicker; show "Apple Inc. · $XXX" on success, an inline "couldn't find
  that ticker" + disabled save for that row on not-found. On a fetch error (not
  not-found), allow save with a soft warning — degrade gracefully. Do NOT fire a
  request per keystroke.

Smoke test: typing AAPL shows the company + price; ZZZZ blocks that row; the
network tab shows one validate call per settled symbol; saving a valid portfolio
still works.

Commit: feat(v10b): inline ticker validation in the portfolio editor
```

---

# V11 — Concentration / correlation agent

### Prompt 5 — Backend: the agent node + state + sector lookup

```
Goal: add a single-instance macro_context_agent that analyzes the whole
portfolio for sector concentration. Mirror risk_agent's shape, NOT
sentiment_agent's.

Files: backend/app/graph/nodes/macro_context_agent.py (NEW),
backend/app/graph/state.py, and backend/app/tools/stock_data.py.

- stock_data.py: add get_sector(symbol) -> str using yfinance .info["sector"],
  cached per symbol (module dict or lru_cache). Missing/failed -> "Uncategorized".
  Wrap every .info access; never raise out of this helper.
- state.py: add macro_analysis: Dict[str, Any] (single writer, NO reducer — add a
  comment saying so, like risk_analysis).
- macro_context_agent.py: runs ONCE over the whole portfolio. Read portfolio +
  market_data + risk_analysis["composition_pct"]. Compute value-weighted sector
  shares, flag any sector > 60% of value, and compute a Herfindahl-style
  diversification score (1 - sum of squared sector shares), 0–1. Return
  {"macro_analysis": {sector_breakdown: {sector: pct}, dominant_sector,
  concentration: "high"|"moderate"|"low", diversification_score, note}}.
  All deterministic Python; no LLM.

Smoke test (pytest or a scratch invoke): feeding a tech-heavy portfolio yields
Technology as dominant_sector with concentration "high"; a mixed portfolio yields
"low"/"moderate". An unknown ticker is bucketed "Uncategorized" without error.

Commit: feat(v11): add deterministic macro_context_agent (sector concentration)
```

### Prompt 6 — Backend: wire the agent into the graph

```
Goal: fan macro_context_agent out alongside risk_agent and join at synthesizer.

Files: backend/app/graph/builder.py and backend/app/api/generate.py.

In builder.py:
- builder.add_node("macro_context_agent", macro_context_agent).
- In fan_out_to_agents, append Send("macro_context_agent", state).
- Add "macro_context_agent" to the conditional-edge target list on
  add_conditional_edges (static validation needs the full enumeration).
- Add builder.add_edge("macro_context_agent", "synthesizer") so the implicit
  barrier still waits for it.

In generate.py: add "macro_context_agent" to _STATUS_NODES so it surfaces in the
live SSE status feed.

Smoke test: generate a report and watch the SSE status feed — macro_context_agent
lights up in parallel with the sentiment agents; the report still completes.

Commit: feat(v11): fan macro_context_agent into the graph and status feed
```

### Prompt 7 — Backend: synthesizer + report schema integration

```
Goal: let the narrative reference concentration, and attach the deterministic
sector breakdown to the report.

Files: backend/app/graph/nodes/synthesizer.py and backend/app/schemas/report.py.

- report.py: add a SectorBreakdown / concentration block to FinalReport (outside
  the LLM-bound ReportBody — attached post-LLM like portfolio_composition).
- synthesizer.py: add a macro block to the human prompt (formatted like the risk
  block, passed verbatim) instructing the model to (a) mention the dominant sector
  in summary_narrative and (b) factor concentration into rebalancing rationale,
  WITHOUT inventing numbers. After the LLM call, attach state["macro_analysis"]'s
  sector breakdown + concentration to the returned FinalReport.

Smoke test: a tech-heavy report's narrative explicitly names the tech
concentration, and the report payload carries the sector breakdown + a
concentration label and diversification score.

Commit: feat(v11): weave concentration into synthesis and attach to the report
```

### Prompt 8 — Frontend: concentration UI

```
Goal: render the sector breakdown + concentration callout.

Files: frontend/src/lib/types.ts and frontend/src/components/FinalReportView.tsx.

- types.ts: mirror the sector breakdown + concentration fields.
- FinalReportView.tsx: add a "Concentration" section — a horizontal sector
  breakdown bar (Recharts or simple flex bars) + a callout naming the dominant
  sector and the concentration level (rose tint for "high", emerald for "low"),
  plus the diversification score. Keep the not-financial-advice tone.

Smoke test: a tech-heavy report shows Technology as the dominant slice and a
"concentration: high" callout; a diversified portfolio flips it to balanced.
npx tsc --noEmit clean.

Commit: feat(v11): render sector concentration breakdown in the report
```

---

# V12a — Value trend chart

### Prompt 9 — Backend: time-series endpoint

```
Goal: serve portfolio value over time from already-archived reports.

File: backend/app/api/reports.py.

- Add GET /api/reports/series/{user_id} returning
  [{generated_at, total_usd, change_24h_percent}] ordered by generated_at,
  read from reports.raw_result.portfolio_valuation. No graph run, no LLM.

Smoke test: after several reports exist, curl the endpoint and confirm the points
match the archived totals in chronological order; an unknown user returns [].

Commit: feat(v12a): add report value time-series endpoint
```

### Prompt 10 — Frontend: trend line on /history

```
Goal: plot the value series on the history page.

Files: frontend/src/lib/api.ts, frontend/src/lib/types.ts,
frontend/src/app/history/page.tsx.

- api.ts: getReportSeries(userId). types.ts: ReportSeriesPoint.
- history/page.tsx: a Recharts line chart of total_usd over generated_at above the
  existing report list. Empty series -> "No reports yet" state.

Smoke test: /history shows a value line matching archived totals; empty-history
user shows the empty state. npx tsc --noEmit clean.

Commit: feat(v12a): portfolio value trend chart on the history page
```

---

# V12b — "Since your last report" diff

### Prompt 11 — Backend: compute + emit the diff

```
Goal: diff each new report against the user's previous one and stream it.

Files: backend/app/api/generate.py and backend/app/schemas/report.py.

- report.py: a ReportDiff model (valuation_delta_pct, sentiment_flips:
  [{asset, from, to}], violations_resolved: [str], violations_new: [str],
  first_report: bool).
- generate.py: BEFORE the run, fetch this user's most recent prior reports row.
  AFTER report_complete, diff the two raw_result payloads in Python and emit a new
  SSE event `report_diff`. No prior report -> emit with first_report: true. No LLM.
- Add report_diff to the SSE taxonomy comment/README.

Smoke test: generate A, change a holding or wait for a sentiment shift, generate
B; the report_diff event carries the sentiment flips, valuation delta, and
resolved/new violations. First report for a fresh user sets first_report true.

Commit: feat(v12b): compute and stream the since-last-report diff
```

### Prompt 12 — Frontend: the "what changed" strip

```
Goal: render the diff at the top of the report.

Files: frontend/src/lib/types.ts, frontend/src/lib/useReportStream.ts,
frontend/src/components/SinceLastReport.tsx (NEW),
frontend/src/components/FinalReportView.tsx.

- types.ts: ReportDiff. useReportStream.ts: handle the report_diff event into state.
- SinceLastReport.tsx: a compact strip — "Value +1.8% since last report",
  "NVDA Neutral -> Positive", "Resolved: AAPL concentration" — colour-coded.
  first_report -> "First report — nothing to compare yet."
- Mount it at the top of FinalReportView.

Smoke test: second report shows the strip with real deltas; first report shows the
first-run message. npx tsc --noEmit clean.

Commit: feat(v12b): render the since-last-report change strip
```

---

# V13 — AI grades its own advice

### Prompt 13 — Backend: historical price helper + grading

```
Goal: grade the previous report's recommendations against actual price moves.

Files: backend/app/tools/stock_data.py, backend/app/api/generate.py,
backend/app/schemas/report.py.

- stock_data.py: add price_on(symbol, date) using yfinance history(start=date,
  end=date+1d); if that day has no data (weekend/holiday), fall back to the
  nearest PRIOR trading day's close. Cache; return None if nothing retrievable.
- report.py: GradedCall { asset, action, recommended_at, pct_move_since,
  grade: "good"|"poor"|"neutral"|"insufficient_data" } and AdviceReview
  (list + summary).
- generate.py: load the prior report's rebalancing_recommendations + its
  generated_at (reuse the V12b prior-report fetch if present). For each rec,
  price_on(report_date) vs current price -> pct move -> grade (reduce+down=good,
  increase+up=good, hold graded on small move; None history -> insufficient_data).
  Emit a new SSE event `advice_review`. All deterministic.

Smoke test: with a back-dated report containing a non-hold rec, the advice_review
event lists each call with its move and grade; a rec on an asset with no history
is "insufficient_data", not an error.

Commit: feat(v13): grade prior recommendations against actual price moves
```

### Prompt 14 — Frontend: the report card

```
Goal: render the advice grades.

Files: frontend/src/lib/types.ts, frontend/src/lib/useReportStream.ts,
frontend/src/components/AdviceReportCard.tsx (NEW),
frontend/src/components/FinalReportView.tsx.

- types.ts: AdviceReview/GradedCall. useReportStream.ts: handle advice_review.
- AdviceReportCard.tsx: a "How last report's calls aged" card — each call with its
  asset, the action taken, the % move since, and a win/lose/neutral badge
  (emerald/rose/slate); insufficient_data shown plainly. Include a one-line note
  that this is a backward-looking, single-step grade, not a guarantee.
- Mount under the recommendations section.

Smoke test: the card lists prior calls with moves and badges; an ungradeable call
shows the insufficient-data state. npx tsc --noEmit clean.

Commit: feat(v13): render the advice report card
```

---

# V14 — Chat with your report

### Prompt 15 — Backend: grounded streaming Q&A endpoint

```
Goal: answer follow-up questions grounded strictly in one archived report,
streamed token by token. No graph re-run.

Files: backend/app/api/reports.py and backend/app/schemas/report.py.

- report.py: AskRequest { question: str }.
- reports.py: POST /api/reports/{report_id}/ask. Load reports.raw_result; build a
  grounded prompt: "Answer ONLY from THIS report. If it isn't in the report, say
  so. Never invent prices, news, or recommendations." Stream the LLM token output
  as SSE `token` events, then a `done` event. Low temperature. This is the
  deliberate counter-case to generate.py's no-token rule (which holds because
  structured output emits one JSON object; free prose streams fine).

Smoke test: curl -N the endpoint with {"question":"why reduce AAPL?"} and watch
tokens stream an answer grounded in that report; "what's the weather" returns an
out-of-scope answer.

Commit: feat(v14): grounded streaming Q&A endpoint over an archived report
```

### Prompt 16 — Frontend: chat panel

```
Goal: a chat box under the report.

Files: frontend/src/lib/api.ts and frontend/src/components/ReportChat.tsx (NEW),
mounted in FinalReportView.tsx.

- api.ts: askReport(reportId, question) consuming the SSE token stream.
- ReportChat.tsx: a Q&A list + input; append streamed tokens to the latest answer
  as they arrive. Keep it visually secondary to the report (slate, compact).
- Mount under the report; it needs the report_id from report_complete.

Smoke test: after a report, asking a question streams a grounded answer
progressively (not all at once). npx tsc --noEmit clean.

Commit: feat(v14): report chat panel with streamed answers
```

---

# V15a — Guest / demo mode

### Prompt 17 — Demo route (read-only)

```
Goal: a zero-signup /demo dashboard bound to idan_demo, read-only.

Files: frontend/src/middleware.ts, frontend/src/app/demo/page.tsx (NEW), and the
dashboard components (add a readOnly flag — reuse, do not fork).
Backend (with V9 in place): allow idan_demo through the JWT guard for
GET portfolio, GET generate-report, and read-only report fetches ONLY.

- middleware.ts: allowlist /demo and its read/generate data calls past the auth gate.
- demo/page.tsx: render the dashboard for a fixed idan_demo session in readOnly
  mode — hide "Edit portfolio", auto-decline/hide the memory persist modal, show a
  banner "Demo — sign up to save your own portfolio".
- Keep idan_demo's holdings curated so the demo tells a good story (the tech-
  concentration narrative demos well).

Smoke test: incognito /demo loads holdings and runs a full streaming report
(including the live pipeline) with no edit affordances; a write endpoint called as
idan_demo is still rejected.

Commit: feat(v15a): read-only guest demo dashboard
```

---

# V15b — Shareable report + PDF

### Prompt 18 — Public report page + share/export

```
Goal: a public read-only report link plus PDF export.

Files: frontend/src/middleware.ts, frontend/src/app/r/[reportId]/page.tsx (NEW),
frontend/src/app/globals.css (print styles),
frontend/src/components/FinalReportView.tsx (Share + Export buttons).
Backend: confirm GET /api/reports/{report_id} serves the read-only payload with
NO owner PII (strip email etc. if present).

- r/[reportId]/page.tsx: fetch the archived report and render FinalReportView
  read-only (no chat, no edit). middleware.ts: allowlist /r/* and the single GET.
- globals.css: a @media print stylesheet for a clean browser "Save as PDF".
- FinalReportView.tsx: a "Share" button (copies the /r/{id} link) and "Export PDF"
  (window.print). Only reach for a client PDF lib later if pixel-exact branding
  is needed.

Smoke test: open a copied share link in a logged-out private window — it renders
the full report read-only with no owner email or edit controls; Export PDF
produces a clean single-document PDF.

Commit: feat(v15b): public shareable report page with PDF export
```

---

# V16 — Stretch shelf

These are intentionally terse — expand into full prompts when you pick them up,
following the same one-or-two-file discipline.

```
Prompt 19 (alerts): Extend DeliveryPreference with alert rules (sentiment-flip /
%-move thresholds) and have the existing dispatcher cron evaluate them, reusing
the Telegram/email channels and the idempotent last_sent_at discipline.
Commit: feat(v16): threshold alerts on the delivery scheduler

Prompt 20 (crypto + TASE): Add CoinGecko crypto pricing (activate the dormant
max_crypto_pct threshold in risk_agent) and Israeli-market context (TASE tickers,
Bank of Israel rate line).
Commit: feat(v16): crypto holdings and Israeli-market context

Prompt 21 (token-stream narrative): Split the synthesizer so summary_narrative
streams in a second call while the structured fields stay on
with_structured_output. Weigh the added latency — V14 already provides the
streaming wow.
Commit: feat(v16): stream the report narrative
```

---

## After each version ships

Append a retrospective brief to `docs/` in the V8-brief format: status + tag +
push, a one-line headline, "What was built" with file trees, a deviations table,
and explicitly-deferred items. That doc is what lets the next Claude session pick
up with full context — it's the single most valuable habit in this whole
workflow.
```
```
