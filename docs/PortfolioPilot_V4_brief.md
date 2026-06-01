# PortfolioPilot V4 — Implementation Brief

> Appendix to `PortfolioPilot_SRS_dev.md`. Captures what was built across V4 (V4a backend SSE + V4b two-page frontend), what deviated from the SRS, and what was explicitly deferred — so any subsequent Claude conversation picks up with full context.

**Status:** Shipped Day 4. Tagged `v4` on `main`. Pushed to `github.com/IdanRodri17/PortfolioPilot`.
**Smoke tests passed:**
- `curl -N "http://localhost:8000/api/generate-report?user_id=idan_demo"` streams `text/event-stream`: `status` start/end events for all four nodes (sentiment_agent starts *and* ends carry their symbol), then a single `report_complete` carrying the full `FinalReport`. No `content-length`, confirming a true stream rather than a buffered JSON body.
- Browser dashboard (`localhost:3000`): clicking **Generate report** animates the live pipeline — `data_ingestion`, then the five `sentiment_agent` branches + `risk_agent` pulsing concurrently (the `Send()` burst), then `synthesizer` — and renders the `FinalReport` as cards. The EventSource fires exactly once and does not re-run after completion.
- Portfolio editor (`localhost:3000/portfolio`): loads the 5-asset balanced portfolio, edits assets + risk profile, saves via `POST /api/portfolio` (with CORS preflight), and the change is reflected on the dashboard's Holdings panel and in a subsequent report run.
- Navigation works both directions between dashboard and editor.

---

## What was built

### V4a — Backend SSE

```
backend/app/
├── main.py                    # + CORSMiddleware; version bumped 0.2.0 → 0.4.0
└── api/generate.py            # REWRITTEN: StreamingResponse + astream_events generator
```

`GET /api/generate-report` no longer returns a `FinalReport` JSON body. It now returns a `StreamingResponse(media_type="text/event-stream")` whose body is produced by `_report_event_stream`, an async generator that consumes `graph.astream_events(initial_state, version="v2")` and maps the raw event firehose down to the SSE taxonomy:

- `on_chain_start` / `on_chain_end` for the four nodes in `_STATUS_NODES` → `status` events `{node, phase, metadata}`.
- `sentiment_agent` start pulls `symbol` from `data.input`; the matching end recovers the same `symbol` via a `run_id → symbol` map (start and end of one runnable invocation share a `run_id`). This makes every status end self-describing so the frontend can pair an end with the start branch it closes.
- The `FinalReport` is captured off whichever `on_chain_end` carries `final_report` in its output, then emitted as `report_complete`.
- Any exception, or a finish with no report, → `error` event.

The DB lookup stays synchronous at the handler boundary; the user's assets + risk_profile are read into a plain `initial_state` dict **before** returning, so the streaming generator holds no ORM objects and the `get_db` session lifetime is irrelevant to it (pattern #7 applied to SSE).

### V4b — Two-page Next.js frontend

```
frontend/
├── .env.local                       # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 (gitignored)
└── src/
    ├── app/
    │   ├── page.tsx                  # Dashboard: holdings + live pipeline + report, two-column
    │   └── portfolio/page.tsx        # Editor: load/edit/save portfolio
    ├── components/
    │   ├── LiveStatusFeed.tsx        # status stream → live pipeline rows
    │   ├── FinalReportView.tsx       # FinalReport → structured cards
    │   └── PortfolioOverview.tsx     # holdings panel (self-fetches portfolio)
    └── lib/
        ├── types.ts                  # TS mirrors of backend contracts + SSE union
        ├── api.ts                    # typed fetch wrappers for portfolio GET/POST
        └── useReportStream.ts        # EventSource hook → typed React state
```

Scaffolded with `create-next-app` (Next 16.2.6, Turbopack): TypeScript, ESLint, Tailwind v4, App Router, `src/` dir, `@/*` alias. `recharts` installed (reserved for the V5 allocation pie — see deferred).

**Pages (2, as scoped):** dashboard `/` and editor `/portfolio`. History and memory pages are V5 (their backends don't exist yet).

**Theme:** dark fintech, applied per-container with explicit Tailwind classes (every component sets its own bg/text) rather than via `globals.css` theme tokens. This deliberately sidesteps the `create-next-app` OS-dark-mode default that caused an early white-on-white bug. Shared colour language across components: emerald = positive/good, rose = negative/reduce, slate = neutral, amber = in-flight (feed only), mono badges for tickers.

---

## Deviations from the SRS

| Area | SRS as written | V4 actually does | Why |
|---|---|---|---|
| `token` event / "token-by-token report draft" | §3 V4 row promises a streaming report draft | **Not emitted.** `token` stays reserved in the taxonomy but unused. | The synthesizer uses `.with_structured_output(FinalReport)`, so the model emits one JSON/tool-call object — streaming its tokens yields partial JSON, not prose. Splitting the synthesizer into a second plain-text call would be scope creep and would complicate the V6 guardrail. The demo's visible streaming is the `status` burst instead. A typewriter effect, if wanted, is a pure frontend reveal (deferred). |
| Frontend page count | §8.1 implies four pages (`/`, `/portfolio`, `/history`, `/memory`) | **Two pages** (`/`, `/portfolio`). | `/history` needs the `Report` model + `/api/reports/history` (V5); `/memory` needs `PostgresStore` + `/api/memories` (V5). Building them now means shells against mocked data, rewired in V5. Pages grow per version, matching the per-version growth of `PortfolioState` and `requirements.txt`. |
| `PortfolioOverview` pie | §2 / §8: "Recharts portfolio pie" | **Holdings list by quantity**, not a value-weighted pie. | A true allocation pie needs per-asset *value* (qty × price). The frontend has quantities (via `getPortfolio`) but not prices; `risk_agent` computes the value-weighted composition server-side but it is deliberately not routed through the LLM's `FinalReport`. Surfacing that composition is a clean V5 change rather than a rushed one at V4's close. `recharts` is installed and ready. |
| HTTP method on streaming endpoint | Not specified | `GET` (kept) | The browser's native `EventSource` only supports `GET`; the portfolio is resolved server-side from `user_id`. |
| `response_model` on `/api/generate-report` | V1-V3 had `response_model=FinalReport` | **Removed** | A streaming body has no single fixed schema. |
| CORS | Not specified | `CORSMiddleware` for `localhost:3000` / `127.0.0.1:3000` | The Next.js dev server (:3000) is a different origin from the API (:8000); its EventSource and POST are cross-origin and the browser blocks them without it. `curl` sends no Origin, which is why the V4a SSE smoke test passed before CORS existed. |
| Frontend data fetching | Not specified | Native `fetch` + `EventSource`, plain React hooks | No React Query / Redux / Zustand for two pages (YAGNI). No client-side response validator (zod): the backend `response_model` is the runtime source of truth; TS types are erase-at-runtime usage hints only. |
| Env var for API base | Not specified | `NEXT_PUBLIC_API_BASE_URL` in `.env.local` | The `NEXT_PUBLIC_` prefix is required for browser-read vars; consumed by `api.ts` and `useReportStream.ts`. |

---

## Explicitly deferred (do NOT build in V4; build in noted version)

- **V5** — value-weighted allocation **Recharts pie** in `PortfolioOverview` (requires surfacing the `risk_agent` composition; `recharts` already installed). `/history` page (needs `Report` model + `/api/reports/history`). `/memory` page (needs `PostgresStore` + `/api/memories`). Read-only memory view or curl is acceptable until then.
- **V6** — `human_input_required` SSE event (the taxonomy slot is reserved now); the `MemoryReviewModal` frontend flow (close SSE on `human_input_required`, reopen against `/api/resume-graph`) — structurally V6 work because `interrupt()` does not exist until then.
- **Polish (no firm version; demo-polish day or V6.5)** — responsive/layout refinement beyond the current centered two-column grid; optional typewriter reveal animation on `summary_narrative`; reading `_ALLOWED_ORIGINS` from settings instead of hardcoding.

**Also not built (no version target yet):** loading skeletons beyond simple text states, optimistic UI on save, a shared `<Nav>` component (two inline `<Link>`s suffice for two pages), tests for the frontend, error boundaries.

---

## Patterns established — load-bearing for V5-V6

24. **SSE event mapping at the API boundary**: the graph stays pure and emits nothing about transport; `_report_event_stream` translates the `astream_events` firehose into the SSE taxonomy in the handler layer. New nodes (V5 `memory_loader`, V6 `guardrail`/`human_review`/`memory_saver`) become visible in the feed by adding their names to `_STATUS_NODES`.
26. **`run_id` pairing for fan-out branches**: when a parallel branch's start and end events need to be correlated (e.g. recovering a `Send` branch's `symbol` on its end event), key off the `run_id` that astream_events shares across one runnable invocation, not off output shape.
27. **Typed boundary mirror (frontend)**: `lib/types.ts` hand-mirrors the Pydantic contracts; the SSE taxonomy is a discriminated union (`ReportStreamEvent`) keyed on a `type` discriminant so a `switch` narrows the payload. Events absent from the backend (`token`, `human_input_required`) are absent from the union until their code lands — the TS analogue of per-version State growth.
28. **EventSource discipline**: one `addEventListener` per *named* event (bare `onmessage` only fires for unnamed events); explicit `close()` on terminal events (`report_complete`, `error`) and transport errors to defeat the default auto-reconnect, which would otherwise re-run the whole graph; distinguish the backend's application-level `error` event (JSON body) from a transport `onerror` (no data) via `e.data`.
29. **Per-container explicit theming (frontend)**: components set their own bg/text classes rather than inheriting a global theme, sidestepping framework defaults (the `create-next-app` OS-dark-mode flip) and keeping the dark fintech palette consistent. Shared colour semantics: emerald/rose/slate/amber + mono ticker badges.
30. **Editable-rows model**: edit a `{symbol: quantity}` map as an array of `{id, symbol, quantity}` rows (stable ids), converting to the map only at the persistence boundary with the backend's own validation mirrored client-side. Avoids key-mutation and collision problems mid-edit.

*(Patterns #1-#23 established in V1-V3 remain in force: singleton-with-DI, node contract, LCEL structured output, thin tool wrappers, Pydantic-for-boundaries/TypedDict-for-State, graph purity with DB I/O at the API boundary, per-asset error tolerance, deterministic risk math, etc.)*

---

## Environment notes for the next Claude

- **Two services must be up** for the dashboard to work: uvicorn on :8000 (from `backend/`, venv active) **and** the Postgres container (`docker compose up -d` from repo root). A stopped Postgres makes `/api/generate-report` 500 (DB lookup) before any event streams; the browser then reports the SSE failure as a generic connection error. Health (`/api/health`) does not touch the DB, so it can pass while a report fails.
- **Frontend env** lives in `frontend/.env.local` (gitignored, `NEXT_PUBLIC_API_BASE_URL`). Env changes require a dev-server restart; `.ts`/`.tsx` changes hot-reload.
- **CORS** is hardcoded to localhost:3000/:8000 in `main.py`. Any new frontend origin (deploy) must be added there.
- **astream_events is version-sensitive.** Node names came through clean on the installed LangGraph version (no drift); if a future upgrade empties the status feed, re-check the `name` field on `on_chain_start` against `_STATUS_NODES`.
- **Git hygiene reminder (learned in V4):** `git restore <file>` discards uncommitted working-tree changes — it reverted the streaming `generate.py` to an older committed state mid-V4 and served stale JSON until re-saved + uvicorn restarted. Always `git status` + `git diff` before restoring. Diagnosis trail: browser console "MIME type application/json is not text/event-stream" → `curl -i` showed `content-type: application/json` + a `content-length` (a buffered body, i.e. the old handler) → restore mishap identified.
- Commits follow conventional format; each V4 step landed as its own commit, version concluded with `git tag -a v4`.

---

## V4 git history

Each step landed as its own conventional commit on `main`:

```
feat(v4): stream generate-report via SSE with astream_events
chore(v4): enable CORS for the frontend dev server
feat(v4): scaffold Next.js frontend with browser health check
feat(v4): add typed API boundary for the frontend
feat(v4): add useReportStream EventSource hook
fix(v4): carry symbol on sentiment_agent end events via run_id
feat(v4): add LiveStatusFeed dashboard component
feat(v4): add FinalReportView report component
feat(v4): assemble two-column dashboard, retire build harness
feat(v4): add portfolio editor page
feat(v4): add dashboard-to-editor navigation link
(tag) v4
```

To reconstruct the V4 baseline at any point: `git checkout v4`.
