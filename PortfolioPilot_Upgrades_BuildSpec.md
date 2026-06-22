# PortfolioPilot — Upgrade Build Spec (V10 → V16)

> Forward-looking appendix to `PortfolioPilot_SRS_dev.md` and the V2–V8 briefs.
> Specifies the next wave of features: deeper analysis, a more alive UX, and a
> publishable surface. Written to be handed to Claude Code one increment at a
> time, paired with `PortfolioPilot_Upgrades_ClaudeCode_Prompts.md`.

**Author's framing.** The codebase is in better shape than the README admits —
the guardrail loop, HITL `interrupt()`, `PostgresSaver` checkpointer, scheduled
Telegram/email delivery, and Auth.js v5 are all shipped, but the README
build-status table still reads V5-in-progress. Two themes drive this wave:
(1) **make the AI visibly smarter** — surface analysis you already compute and
add genuinely new intelligence; (2) **make it publishable** — a demo path and
shareable reports, because this project is also your strongest career signal and
your best content engine. Every version below is a clean one-to-two-file
increment that ends in a smoke test and a `feat(vN):` tag.

---

## Standing conventions (unchanged from V1–V8)

- **One version at a time**, each concluded with a conventional-commit history,
  a Git tag, and a smoke test that proves the increment end to end.
- **Commits:** `feat(vN): …` / `fix(vN): …` with a multi-line body. Run `git`
  from the **repo root**, never a subdirectory.
- **Migrations:** no Alembic. Schema changes are **surgical `ALTER TABLE`**
  applied by hand (heredoc via psql on Git Bash to avoid `$`-escaping mishaps).
- **Backend boundary rule (load-bearing):** the graph is a pure
  `portfolio_dict → FinalReport` pipeline and must not learn that Postgres
  exists. DB lookups and report archiving stay in the FastAPI handlers. The one
  sanctioned exception is the memory nodes' injected `BaseStore`.
- **Deterministic numbers do not pass through the LLM** (risk_agent docstring;
  `PortfolioOverview` comment). Percentages, deltas, and price moves are
  computed in Python and attached to the report — never re-emitted by the model.
- **Frontend:** Next.js **16.2.6** + React **19** — this is *not* the Next.js in
  training data. Read the relevant guide under `node_modules/next/dist/docs/`
  before writing components (see `frontend/AGENTS.md`). Tailwind **v4**.
  **Recharts 3.8.1 is already installed** (no new dep for charts). Hooks are the
  **first lines in the component body**. Dark slate theme; colour language is
  shared (emerald = good/positive, rose = bad/reduce, slate = neutral, amber
  reserved for in-flight).
- **Per-feature briefs:** when a version ships, append a retrospective brief to
  `docs/` matching the V8 brief format (status, headline, what was built, file
  trees, deviations table, deferred items).

**Prerequisite note.** **V9 (backend JWT verification)** is your already-planned
next item: today a raw `curl …?user_id=anything` bypasses auth because the
backend trusts the `user_id`. Several features below (demo mode, shareable
reports) deliberately open *unauthenticated* routes, so they are easiest to
reason about **after V9 exists** — V9 defines the default-closed baseline that
demo/share routes then explicitly opt out of. Recommended order: ship V9, then
this wave.

---

## Sequencing at a glance

| Ver | Feature | Type | Why it's here |
|----|---------|------|---------------|
| **Prelude** | README + roadmap refresh | Docs | Near-free; stops underselling 3 versions of work |
| **V10a** | Surface value-weighted allocation (donut) | FE + tiny BE | Data already computed; instantly looks finished |
| **V10b** | Ticker entry that validates | FE + small BE | The line between "demo" and "product" |
| **V11** | Concentration / correlation agent | Graph (BE) | Standout intelligence; your best thread |
| **V12a** | Portfolio value trend chart | FE + tiny BE | History that means something |
| **V12b** | "Since your last report" diff | BE + FE | Reports feel alive and continuous |
| **V13** | AI grades its own past advice | BE + FE | Most distinctive; credibility + content |
| **V14** | Chat with your report | BE + FE | One-shot briefing → interactive agent |
| **V15a** | Guest / demo mode | FE + BE | Zero-signup trial = top-of-funnel |
| **V15b** | Shareable report + PDF | FE + BE | A shared report is free distribution |
| **V16** | Stretch: alerts, crypto/TASE, token-stream | Mixed | Roadmap continuation |

> **If you only do three:** V10a (looks finished), V11 (cleanest "smart" win),
> and V13 (the self-grading differentiator). Those three change how the app
> *demos* more than anything else on the list.

---

## Prelude — README & roadmap refresh (housekeeping, do first)

**Goal.** Make the README reflect reality. The build-status table should show
V1–V8 shipped (V9 in progress), the highlight legend should flip the guardrail
loop, HITL, delivery, and auth from 🚧/📋 to ✅, and the roadmap should be
re-anchored to this spec's V10+.

**Files:** `README.md` only. No code.

**Smoke test:** a stranger reading the README can tell, in 30 seconds, that the
app has real auth, a self-correcting guardrail, HITL memory approval, and
scheduled multi-channel delivery — all shipped.

---

## V10a — Surface the allocation you already compute (donut chart)

**Goal.** `risk_agent` already returns `composition_pct` (value-weighted
percentage per asset) and `total_value_usd`, but neither reaches the report or
the UI — `PortfolioOverview` still shows raw quantities and even carries a
comment admitting the value-weighted pie is owed. Put the composition into the
report payload and render a Recharts donut on the dashboard.

**Why it matters.** Highest visual-payoff-per-hour change in the project. A
real allocation chart is the difference between "student project" and "product"
in a screenshot — and screenshots are your content.

**Files touched.**
```
backend/app/
├── schemas/report.py     # + AssetAllocation model; + portfolio_composition on the report
└── graph/nodes/synthesizer.py   # attach composition deterministically (NOT via the LLM)

frontend/src/
├── lib/types.ts          # mirror AssetAllocation + portfolio_composition
└── components/
    ├── AllocationDonut.tsx   # NEW: Recharts donut, value-weighted
    └── FinalReportView.tsx   # render the donut in the valuation section
```

**Design & decisions.**
- **Deterministic, not LLM-emitted.** Honor the project rule: do not route exact
  percentages through `with_structured_output`. Keep the LLM-bound schema free of
  composition, then have the `synthesizer` node attach
  `risk_analysis["composition_pct"]` to the returned report after the LLM call.
  Concretely: split the current `FinalReport` so the model fills a `ReportBody`
  (valuation, insights, recommendations, narrative, confidence), and the node
  assembles `FinalReport(**body, portfolio_composition=<from risk_analysis>)`.
  `portfolio_composition` is a list of `{asset, pct, value_usd}`.
- **Archive gets it for free.** Because it lives on the report payload, the
  `reports.raw_result` archive, `/history`, and shareable reports (V15) all
  inherit the chart with no extra work.
- **Empty/edge state.** If `composition_pct` is empty (no priced assets), emit
  an empty list and have the donut render an honest "no priced holdings" state.

**Smoke test.** Generate a report for `idan_demo`; the dashboard shows a donut
whose slices match the risk_agent percentages (AAPL the largest), slice labels
read `SYMBOL pct%`, and the centre shows total USD. `report_complete` payload
contains `portfolio_composition`. `npx tsc --noEmit` clean.

**Gotchas.** Recharts 3.x labels/legend props differ from 2.x examples — verify
against the installed version. Keep slice colours within the slate/emerald
palette; don't introduce a rainbow.

---

## V10b — Ticker entry that validates

**Goal.** In the portfolio editor, validate each symbol as it's entered and show
the company name + live price inline, so a user can't save a typo'd ticker that
silently fails at ingestion time.

**Files touched.**
```
backend/app/
├── tools/stock_data.py   # + lookup_symbol(symbol) -> {name, price} | None (reuse yfinance)
└── api/portfolio.py      # + GET /api/ticker/validate?symbol=...  (thin, cached)

frontend/src/
├── lib/api.ts            # validateTicker(symbol)
└── app/portfolio/page.tsx  # inline validation: name + price + invalid guard
```

**Design & decisions.**
- **Reuse the existing thin wrapper.** `stock_data.py` already owns the only
  yfinance touch-point; add `lookup_symbol` there, normalized to the same custom
  exception, so nodes/endpoints never import the SDK directly.
- **Debounce + cache.** Validate on a short debounce (e.g. 400 ms after typing
  stops); cache results per symbol in-memory on the backend (yfinance `.info` is
  slow). Unknown symbol → `null` → inline "couldn't find that ticker" and a
  disabled save for that row.
- **Don't block save on a flaky network.** If validation errors (not "not
  found", but a fetch failure), allow save with a soft warning — degrade
  gracefully, consistent with the project's per-asset error tolerance.

**Smoke test.** Typing `AAPL` shows "Apple Inc. · $—"; typing `ZZZZ` shows a
not-found state and blocks that row; saving a valid portfolio still works; the
network tab shows one validate call per settled symbol, not per keystroke.

---

## V11 — Concentration & correlation agent (`macro_context_agent`)

**Goal.** Add a new parallel agent that looks at the portfolio *as a whole* and
flags correlated concentration the per-asset sentiment agents can't see:
*"78% of your value is AAPL / MSFT / NVDA / GOOGL — that's not diversified,
it's one bet on tech."*

**Why it matters.** Architecturally clean — your `builder.py` literally leaves a
comment anticipating a `macro_context_agent` as a new `Send` target. It's
genuinely insightful, and it writes your single best build-in-public thread.

**Files touched.**
```
backend/app/
├── graph/
│   ├── state.py          # + macro_analysis: Dict[str, Any]  (single writer, no reducer)
│   ├── nodes/macro_context_agent.py   # NEW: sector buckets + concentration metric
│   └── builder.py        # add node; add to fan_out_to_agents Sends + conditional-edge list;
│                         #   add edge macro_context_agent -> synthesizer
│   tools/stock_data.py   # + get_sector(symbol) (yfinance .info['sector'], cached)
├── schemas/report.py     # + SectorBreakdown / ConcentrationInsight on report (deterministic)
├── graph/nodes/synthesizer.py   # + macro block in the prompt; weave into narrative/recs
└── api/generate.py       # add "macro_context_agent" to _STATUS_NODES

frontend/src/
├── lib/types.ts          # mirror the concentration fields
└── components/FinalReportView.tsx   # render a sector breakdown bar + a concentration callout
```

**Design & decisions.**
- **Mirror `risk_agent`, not `sentiment_agent`.** It runs **once** over the whole
  portfolio (single-writer `macro_analysis`, no reducer), reading
  `portfolio` + `market_data`. It is fanned out alongside risk_agent/sentiment
  via the same `fan_out_to_agents` edge; remember to append
  `"macro_context_agent"` to the conditional-edge target list (static graph
  validation requires the full enumeration) and add the
  `macro_context_agent -> synthesizer` edge so the implicit barrier still holds.
- **Sector source + caching.** `yfinance.Ticker(sym).info["sector"]` is the
  pragmatic source, but `.info` is slow and rate-limit-prone — cache per symbol
  in `stock_data.py` (module-level dict or `functools.lru_cache`). Missing
  sector → `"Uncategorized"` (graceful degradation, same as a failed news
  fetch).
- **Concentration metric (deterministic).** Compute value-weighted sector shares
  from `composition_pct` (already available) + each symbol's sector, then a
  simple concentration signal: flag any sector over a threshold (e.g. > 60% of
  value), and surface a Herfindahl-style index (sum of squared sector shares) as
  a single "diversification score" 0–1. All Python; the LLM only narrates it.
- **Correlation (optional V11 stretch).** A truer "these move together" signal is
  a 30-day return correlation via `yfinance` history. It's heavier (one history
  call per symbol) — default V11 to sector bucketing; gate real correlation
  behind a follow-up if the sector heuristic proves too coarse.
- **Synthesizer integration.** Pass the macro block in verbatim like the risk
  block; instruct the model to (a) reference the dominant sector in the
  narrative, and (b) factor concentration into rebalancing rationale — without
  inventing numbers. The deterministic sector breakdown is attached to the
  report post-LLM (same pattern as V10a composition).

**Smoke test.** A tech-heavy `idan_demo` report shows a sector breakdown
(Technology ~majority), a "concentration: high" callout naming the dominant
sector, and a diversification score; the narrative explicitly mentions the
sector concentration; SSE status feed shows `macro_context_agent` lighting up
in parallel with the sentiment agents. With a manually diversified portfolio the
callout flips to "balanced".

**Gotchas.** `.info` can raise or return partial dicts for some tickers — wrap
every access. Don't let a single sector lookup failure fail the branch; default
to `"Uncategorized"` and continue.

---

## V12a — Portfolio value trend chart

**Goal.** On `/history`, plot total portfolio value over time from the reports
you already archive.

**Files touched.**
```
backend/app/api/reports.py   # + GET /api/reports/series/{user_id}
                             #   -> [{generated_at, total_usd, change_24h_percent}]
frontend/src/
├── lib/api.ts               # getReportSeries(userId)
├── lib/types.ts             # ReportSeriesPoint
└── app/history/page.tsx     # Recharts line chart above the report list
```

**Design & decisions.**
- **Derive, don't recompute.** Each `reports.raw_result` already holds
  `portfolio_valuation.total_usd` and `generated_at`. The series endpoint selects
  those two fields ordered by time — no graph re-run, no LLM cost.
- **Boundary, not graph.** This is pure read-side history (pattern #7) — lives in
  `reports.py`, not a node.

**Smoke test.** After generating several reports across a session, `/history`
shows a value line that matches the archived totals in chronological order; an
empty-history user shows an honest "no reports yet" state.

---

## V12b — "Since your last report" diff

**Goal.** On each new run, compare against the user's previous report and surface
deltas at the top: valuation change, per-asset sentiment flips, and risk
violations newly created or resolved.

**Files touched.**
```
backend/app/
├── api/generate.py       # before streaming: load previous report; compute diff;
│                         #   emit new SSE event `report_diff` after report_complete
└── schemas/report.py     # ReportDiff model (deltas) — for typing/serialization

frontend/src/
├── lib/types.ts          # ReportDiff
├── lib/useReportStream.ts  # handle the report_diff event
└── components/SinceLastReport.tsx  # NEW: a compact "what changed" strip
    components/FinalReportView.tsx   # mount the strip at the top
```

**Design & decisions.**
- **Computed at the boundary, deterministically.** In the generate handler, fetch
  the most-recent prior `reports` row for this user *before* the new run starts
  (you have the `user_id`); after the new report is produced, diff the two JSON
  payloads in Python (sentiment per asset: `prev → curr`; valuation delta;
  set-difference on violation strings). Emit as a `report_diff` SSE event. No LLM.
- **First-run safe.** No prior report → emit `report_diff` with a `first_report:
  true` flag; the strip renders "First report — nothing to compare yet."
- **Taxonomy update.** Add `report_diff` to the SSE event taxonomy in the README
  and the client hook's switch.

**Smoke test.** Generate report A, change a holding or wait for a sentiment
shift, generate report B; the strip shows e.g. "NVDA sentiment Neutral →
Positive", "Value +1.8% since last report", "Resolved: AAPL concentration". The
very first report for a fresh user shows the first-run state.

---

## V13 — The AI grades its own past advice

**Goal.** When a new report runs, look back at the *previous* report's
`rebalancing_recommendations` and show how those assets actually moved since —
a "report card" on the AI's own calls. "Last report said *reduce TSLA* — down
6% since; the call aged well."

**Why it matters.** The most distinctive thing on this list. Almost nobody ships
self-grading AI. It's a credibility flex and an endless content series ("my AI
graded its own homework this week").

**Files touched.**
```
backend/app/
├── tools/stock_data.py   # + price_on(symbol, date) via yfinance history (nearest trading day)
├── api/generate.py       # load prior recs + their report date; score each; emit `advice_review`
└── schemas/report.py     # AdviceReview / GradedCall models

frontend/src/
├── lib/types.ts          # AdviceReview
├── lib/useReportStream.ts  # handle advice_review
└── components/AdviceReportCard.tsx  # NEW: graded calls, win/lose colour-coded
    components/FinalReportView.tsx    # mount under the recommendations section
```

**Design & decisions.**
- **Scoring is deterministic.** For each prior recommendation, fetch the asset's
  close on the prior report's date and its current price; compute % move; grade:
  `reduce` + price down = good call, `increase` + price up = good call, `hold`
  graded on small absolute move. All Python; the model isn't involved.
- **Historical price lookup.** `yfinance.Ticker(sym).history(start=date,
  end=date+1d)` — but markets close on weekends/holidays, so fall back to the
  nearest *prior* trading day's close. Cache lookups; degrade gracefully (a call
  with no retrievable history is shown as "not enough data to grade", not an
  error).
- **Scope the window honestly.** Grade only against the immediately previous
  report (clear, cheap). A full equity curve of "if you'd followed every
  rebalance" is a tempting V13.5 but needs careful assumptions — keep V13 to the
  one-step look-back.
- **Reuse the V12b prior-report fetch.** If V12b shipped, you already load the
  previous report in the handler; extend that path rather than fetching twice.

**Smoke test.** Generate report A (with at least one non-`hold` recommendation),
let time/price move (or seed a back-dated report), generate report B; the report
card lists each prior call with its asset's move and a win/lose badge, and a call
on an asset with no retrievable history shows the "not enough data" state.

**Gotchas.** Time zones and the "nearest trading day" fallback are the fiddly
part — write a tiny helper and test it against a known weekend date. Be explicit
in the UI that this is a backward-looking, single-step grade, not a performance
guarantee (and keep the standing not-financial-advice disclaimer visible).

---

## V14 — Chat with your report

**Goal.** After a report renders, let the user ask follow-ups — "why reduce
AAPL?", "what's my biggest risk?" — answered strictly from that report's
contents, streamed token by token.

**Why it matters.** Turns a one-shot briefing into an interactive agent for very
little new infrastructure, and it's your first chance to show real
token-streaming (the structured report can't stream; free-form answers can).

**Files touched.**
```
backend/app/
├── api/reports.py        # + POST /api/reports/{report_id}/ask  (SSE token stream)
└── schemas/report.py     # AskRequest (question: str)

frontend/src/
├── lib/api.ts            # askReport(reportId, question) — EventSource/fetch stream
└── components/ReportChat.tsx  # NEW: Q&A panel under the report
    components/FinalReportView.tsx   # mount the chat panel
```

**Design & decisions.**
- **No graph re-run.** Load the archived `reports.raw_result`, build a grounded
  prompt — "You are answering questions about THIS report only. If the answer
  isn't in it, say so. Do not invent prices, news, or recommendations." — and
  stream the model's reply. It's a stateless, single-call endpoint, cheap and
  safe, and it reuses the report you already persist.
- **Streaming.** Use the LLM's token stream → SSE `token` events → append in the
  UI. This is the deliberate counter-case to the report endpoint's "no token
  events" note (which holds *because* structured output emits one JSON object;
  free prose does not).
- **Grounding guardrail.** The system prompt forbids going beyond the report;
  keep `temperature` low. This keeps the feature inside the
  educational-not-advice framing.

**Smoke test.** After a report, asking "why reduce AAPL?" streams an answer that
cites the report's own AAPL concentration/sentiment; asking "what's the weather"
gets "that's outside this report." Answers stream progressively, not all at once.

---

## V15a — Guest / demo mode

**Goal.** A zero-signup `/demo` route that loads a fixed read-only `idan_demo`
portfolio and lets a visitor generate a real report — but not edit holdings or
wipe memory.

**Why it matters.** The single biggest top-of-funnel lever for publishing:
nobody signs up for an unknown app, but plenty will click "see a live demo."

**Files touched.**
```
frontend/src/
├── middleware.ts         # allowlist /demo (and its data calls) past the auth gate
├── app/demo/page.tsx     # NEW: read-only dashboard bound to idan_demo
└── components/*           # reuse dashboard components in a read-only mode flag

backend/app/
└── (V9 interaction) allow the demo user through the JWT guard for read + generate only
```

**Design & decisions.**
- **Default-closed, explicitly opened.** With V9 in place the backend is
  default-closed; demo carves out exactly: `GET /api/portfolio/idan_demo`,
  `GET /api/generate-report?user_id=idan_demo`, and read-only report fetches.
  Editing, memory wipe, settings, and delivery stay closed.
- **Reuse, don't fork, the UI.** Pass a `readOnly` flag into the existing
  dashboard components: hide "Edit portfolio", disable the memory modal's persist
  (or auto-decline), show a banner "Demo — sign up to save your own portfolio".
- **Seed and freeze `idan_demo`.** Keep its holdings curated so the demo always
  tells a good story (the tech-concentration narrative from V11 demos well).

**Smoke test.** An incognito visit to `/demo` (no login) loads holdings, runs a
full streaming report including the live pipeline, but shows no edit affordances
and cannot wipe memory; a `curl` of a write endpoint as `idan_demo` is still
rejected.

---

## V15b — Shareable report + PDF

**Goal.** A public, read-only link to a single archived report
(`/r/{report_id}`) that renders without auth, plus a "Share" button and a PDF
export.

**Why it matters.** A shared report is free distribution — every link is a tiny
ad for the app, and a clean PDF is something people forward.

**Files touched.**
```
frontend/src/
├── middleware.ts         # allowlist /r/* and the single-report GET
├── app/r/[reportId]/page.tsx   # NEW: read-only report render (reuse FinalReportView)
├── app/globals.css       # print stylesheet for clean PDF via the browser
└── components/FinalReportView.tsx   # + a "Share" button (copy link) + "Export PDF"

backend/app/
└── api/reports.py        # GET /api/reports/{report_id} already exists — confirm it
                          #   serves the read-only payload without leaking owner PII
```

**Design & decisions.**
- **Reuse the existing endpoint.** `GET /api/reports/{report_id}` already replays
  an archived report from `raw_result` with no LLM cost; the public page just
  renders it. Confirm the payload doesn't carry the owner's email or other PII —
  if it does, strip to report fields only.
- **PDF for free first.** Start with a `@media print` stylesheet and the
  browser's "Save as PDF" (zero deps, looks clean). Only reach for a client lib
  (e.g. a print-to-canvas) if you need pixel-exact branded exports.
- **Unguessable IDs.** Report IDs are uuid4 — fine as capability URLs. If you
  want stricter privacy later, add a per-report `share_token` and gate on that
  instead of the raw id.

**Smoke test.** Copy a report's share link, open it in a private window (logged
out) — it renders the full report read-only; "Export PDF" produces a clean,
single-document PDF; the page exposes no owner email or edit controls.

---

## V16 — Stretch shelf (brief specs)

Pick up as appetite allows; each is a clean increment.

- **Threshold alerts.** Extend `DeliveryPreference` with alert rules (e.g.
  "notify if any holding's sentiment flips Negative or moves > X% in 24h") and
  have the dispatcher evaluate them on its existing cron, reusing the Telegram/
  email channels. Natural extension of the V7 delivery system — same idempotent
  `last_sent_at` discipline per alert.
- **Crypto (CoinGecko) + Israeli-market context.** Your existing roadmap (V6.5 /
  V8): CoinGecko for crypto holdings (activate the dormant `max_crypto_pct`
  threshold in `risk_agent`), TASE tickers, and a Bank-of-Israel-rate macro line.
  A strong personal differentiator given your market.
- **Token-stream the narrative.** If you want the *report's* prose to stream too,
  split the synthesizer: structured fields via `with_structured_output`, then a
  second streamed call for `summary_narrative` only. Adds latency and complexity
  — V14's chat already gives you the streaming "wow", so weigh whether this earns
  its keep.

---

## Cross-cutting reminders for every increment

1. **Smoke test before the commit.** No tag without a passing end-to-end check.
2. **Keep the graph pure.** New read-side history (diffs, grading, series) lives
   in handlers; only genuinely in-graph analysis (the macro agent) touches nodes.
3. **Deterministic numbers in Python.** Composition, sector shares, deltas, and
   price moves are computed and attached — never invented by the model.
4. **Schema is additive.** New `FinalReport`/payload fields are optional with
   safe defaults so older archived reports still deserialize and render.
5. **Disclaimer stays visible.** Every new analysis surface (concentration,
   advice grading, chat) keeps the educational-not-financial-advice framing.
6. **Append a brief when you ship.** One retrospective doc per version in `docs/`,
   V8-brief format, so the next Claude session has full context.
