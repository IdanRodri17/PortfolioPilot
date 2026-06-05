# PortfolioPilot V6 — Implementation Brief

> Appendix to `PortfolioPilot_SRS_dev.md`. Captures what was built across V6 (V6a guardrail Reflexion loop, V6b checkpointer + HITL memory split + resume endpoint, V6c memory-review frontend), what deviated from the SRS, and what was explicitly deferred — so any subsequent Claude conversation picks up with full context.

**Status:** Shipped Day 6. Tagged `v6` on `main`. Pushed to `github.com/IdanRodri17/PortfolioPilot`.

**Smoke tests passed:**
- **Guardrail clean pass:** a report runs `synthesizer → guardrail → memory_extractor` with a single guardrail evaluation; the report is grounded (AAPL flagged at 41.7% over the balanced 35% cap, one `reduce AAPL -15%` recommendation, confidence 0.8).
- **Guardrail retry (Reflexion):** with the `GUARDRAIL_FORCE_FAIL=1` demo toggle, the feed shows `synthesizer → guardrail (fail) → synthesizer → guardrail (pass) → memory_extractor` — the regeneration is the second synthesizer pair; server logs `guardrail: FORCED FAIL` then `guardrail: PASS attempt=2`.
- **Clean startup:** `uvicorn` boots to "Application startup complete" with no event-loop error; `\dt` shows the `checkpoints` / `checkpoint_blobs` / `checkpoint_writes` / `checkpoint_migrations` tables alongside the store and SQL tables.
- **Pause (HITL):** a report streams `report_complete` (carrying `report_id`) **then** `human_input_required` (carrying `thread_id` == `report_id` and 1–3 `proposed_memories`); the stream closes; `GET /api/memories/idan_demo` returns `[]` — nothing persisted, the saver is genuinely gated.
- **Resume:** `POST /api/resume-graph?thread_id=…` with `{"approved_indices": [0]}` streams `memory_saver` start/end then `memory_saved {"count": 1}`; the approved insight appears in the store with a timestamp.
- **Guard / idempotency:** resuming an unknown or already-finished `thread_id` returns `error NO_PAUSED_RUN` (no fresh run, no `KeyError`); resuming a thread already at END returns `NO_PAUSED_RUN` (can't double-save).
- **Reject / select:** `{"approved_indices": []}` → `memory_saved {"count": 0}`, store unchanged; a checked subset persists exactly that subset.
- **Frontend:** clicking **Generate report** animates the pipeline and renders the report; the **MemoryReviewModal** opens over it with the proposals pre-checked; **Approve selected** flips to "Saving…", a "Saving approved insights" row appears, the modal closes, and `/memory` lists exactly the approved subset. Reject-all and approve-all behave correctly.

---

## What was built

### V6a — Guardrail Reflexion loop (no checkpointer, no HITL)

```
backend/app/graph/
├── state.py                 # + guardrail_passed, guardrail_feedback, retry_count
├── builder.py               # synthesizer → guardrail; conditional route_after_guardrail
└── nodes/
    ├── guardrail.py         # NEW: rule checks + gpt-4o LLM-as-judge → {passed, feedback}
    └── synthesizer.py       # + guardrail_feedback injected on retry (Reflexion preamble)
backend/app/api/generate.py  # + "guardrail" in _STATUS_NODES
```

`guardrail` validates the synthesizer's `final_report` in two layers. **Layer 1 (deterministic, free):** every ticker mentioned in `market_insights` / `rebalancing_recommendations` must be in the portfolio; `total_usd >= 0`; no overpromising language ("guaranteed returns", "risk-free", "can't lose", …). Rule failures **fail-fast** — skip the paid judge and feed the reasons back. **Layer 2 (gpt-4o LLM-as-judge):** only if the rules pass; judges grounding + risk-profile adherence, returns structured `{passed, feedback}`. A judge exception degrades to pass-through (the report already exists — never trap the user in retries). The node increments `retry_count` on every entry.

`route_after_guardrail`: `passed → memory_extractor`; `retry_count >= 3 → memory_extractor` (give up, ship best-effort); else `→ synthesizer`. Budget = **2 regenerations** (3 synthesizer attempts). On retry the synthesizer prepends a Reflexion preamble (`_format_guardrail_feedback_block`) listing the failure reasons.

This sub-version is fully functional on the existing store-only compile — **cycles do not need a checkpointer** (only `interrupt()` does).

### V6b — Checkpointer + HITL memory split + resume endpoint

```
backend/app/
├── graph/
│   ├── state.py                       # + proposed_memories, approved_memories
│   ├── builder.py                     # store-only graph at import + set_checkpointer() rebind;
│   │                                  #   memory_extractor → human_review → memory_saver → END
│   ├── persistence/
│   │   └── checkpointer.py            # NEW: AsyncPostgresSaver on its own async pool (lifespan-built)
│   └── nodes/
│       ├── memory_extractor.py        # narrowed to propose-only (no store write, no store injection)
│       ├── human_review.py            # NEW: interrupt() pause; skips interrupt if no proposals
│       └── memory_saver.py            # NEW: persists only approved_memories → new_memories
├── api/generate.py                    # thread_id config; interrupt detection; POST /api/resume-graph
└── main.py                            # lifespan builds checkpointer + set_checkpointer; v0.6.0
```

**Checkpointer.** An `AsyncPostgresSaver` (async, *not* the sync `PostgresSaver` the SRS sketched — the async `astream_events` runtime calls the checkpointer's async methods, which the sync saver leaves unimplemented). It runs on its **own** `AsyncConnectionPool`, separate from the store's sync pool (an async saver needs an async pool). Critically, it is **constructed inside the lifespan** (`open_checkpointer()`), not at import — `AsyncPostgresSaver.__init__` binds to the running event loop, so constructing it at module scope raises `RuntimeError: no running event loop`.

**Deferred compile.** Because the checkpointer can't exist at import, `builder.graph` is compiled **store-only** at import; the lifespan then calls `set_checkpointer(cp)` to recompile it with both store and checkpointer. `get_graph()` reads `builder.graph` *dynamically* (not a value bound at import) so it returns the upgraded graph.

**HITL three-node split.** V5's `memory_extractor` (propose + auto-save) becomes three nodes: `memory_extractor` proposes → `proposed_memories`; `human_review` calls `interrupt()` to pause and surface them; `memory_saver` persists only `approved_memories`. The `store.put` lives in `memory_saver`, *after* the gate — `human_review` re-executes from the top on resume (everything above `interrupt()` runs twice), so the write must not sit before the gate or it would double-fire. `human_review` skips the interrupt entirely when there are no proposals.

**Interrupt surfacing + resume.** The generate handler passes `config={"configurable": {"thread_id": report_id}}` (every checkpointer run needs a thread_id; we reuse `report_id`). After the run, it reads `graph.aget_state(config)` — `snapshot.next` containing `"human_review"` means a pause — and emits `human_input_required`. **`report_complete` ships first**, so the report is never gated on memory approval. `POST /api/resume-graph?thread_id=…` resumes via **`ainvoke(Command(resume=...))`** (run-to-completion — the resumed `astream_events` firehose emitted nothing in this LangGraph version), synthesizes the `memory_saver` status events, and ends with `memory_saved {count}`. A guard rejects unknown / already-finished thread_ids with `NO_PAUSED_RUN`.

### V6c — Memory-review HITL frontend

```
frontend/src/
├── components/
│   ├── MemoryReviewModal.tsx   # NEW: checkboxes + approve selected / approve all / reject all
│   └── LiveStatusFeed.tsx      # + labels for memory_loader / guardrail / memory_extractor / memory_saver
├── lib/
│   ├── types.ts                # + human_input_required, memory_saved in the SSE union
│   └── useReportStream.ts      # pause/resume state machine + fetch-based resume reader
└── app/page.tsx                # renders the modal; Generate disabled through review/saving
```

The hook walks `streaming → done → awaiting_review → saving → done`. **`report_complete` is no longer terminal** (a `human_input_required` may follow it in the same stream), so the EventSource stays open after the report; a `terminalRef` tells the transport `onerror` that a later close is the clean end (defeating the auto-reconnect that would otherwise re-run the graph). `human_input_required` opens the modal and closes stream 1. **Resume is a second transport:** the approved indices ride in a POST body, which `EventSource` (GET-only) can't carry, so `resume()` uses `fetch()` + `response.body.getReader()` + a small SSE block parser, feeding `memory_saver` status into the same feed.

**Graph topology (V6):**
```
START → memory_loader → data_ingestion → [Send fan-out: sentiment_agent × N + risk_agent]
        → synthesizer ⇄ guardrail → memory_extractor → human_review (interrupt)
        → memory_saver → END
```
Compiled **with both** the `PostgresStore` (sync, node-injected) and the `AsyncPostgresSaver` checkpointer (async, runtime-managed), the latter wired in by the lifespan.

---

## Deviations from the SRS

| Area | SRS as written | V6 actually does | Why |
|---|---|---|---|
| Checkpointer flavor | sync `PostgresSaver` (§4.7) | **`AsyncPostgresSaver`** | The graph runs via async `astream_events`; the runtime calls async checkpointer methods, which the sync saver leaves unimplemented (`NotImplementedError`). |
| Persistence pool | one pool for store + checkpointer (pattern #32 intent) | **separate async pool** for the checkpointer | The async saver needs an `AsyncConnectionPool`; the store's pool is the sync `ConnectionPool`. Two pools, one DB. |
| Checkpointer construction | module-level / `from_conn_string` (§4.7) | **built in the lifespan loop** | `AsyncPostgresSaver.__init__` binds to the running loop; constructing at import raises `RuntimeError: no running event loop`. Graph is compiled store-only at import, then recompiled via `set_checkpointer`. |
| `draft_report` field | separate `draft_report` then `final_report` (§4.1) | **kept single `final_report`** | The synthesizer already writes it and the SSE capture keys on it; a separate draft field would churn both for no gain. |
| Retry budget | give up at `retry_count >= 2` (§4.6) — 1 regeneration | `>= 3` — **2 regenerations** (3 attempts) | "Retry budget 2" read as two regenerations; one-line knob (`_RETRY_BUDGET`). |
| `report_complete` timing | end of the *resumed* stream (§5.2) | **stream 1, before `human_input_required`** | The report is the deliverable; it must not be held hostage to memory approval. |
| Resume execution | `astream_events(Command(resume=...))` (§4.7) | **`ainvoke(Command(resume=...))`** + synthesized status | The resumed `astream_events` firehose produced an empty 200 in this version; run-to-completion is reliable and can't fail silently. |
| Memory value shape | `{"insight", "context"}` (§4.5) | **`{"insight"}` only** | Preserves V5's store shape so `memory_loader` and the `/api/memories` endpoint keep working unchanged. `context` deferred. |
| `human_review` in status feed | (implied surfacing) | **not surfaced** | On the first pass it emits a `start` then interrupts with no `end` — it would hang as a "running" row. The modal is its UI; `memory_saver` is surfaced instead. |
| `confidence_flag` source | "from guardrail" (§6.1) | **budget-exhausted → low**, else confidence-based | `_persist_report` flags `low` when `guardrail_passed is False`; otherwise the V5 confidence threshold. |
| Resume guard | (not specified) | **`NO_PAUSED_RUN`** for unknown/finished threads | Without it, `Command(resume=...)` on a checkpoint-less thread starts a fresh run with empty state → `KeyError 'user_id'`. Also makes resume idempotent. |
| Resume client | (POST, §5.1 notes EventSource can't send a body) | **`fetch()` + `ReadableStream`** + SSE parser | As the SRS anticipated; the native `EventSource` is GET-only. |

---

## Explicitly deferred (do NOT build in V6; build in the noted version)

- **Value-weighted allocation Recharts pie** (the long-carried item, deferred since V4) → next polish pass. Needs `risk_agent`'s value-weighted composition surfaced through a `report_complete` wrap (`{report, composition}`); deterministic numbers must come from `risk_agent`, not the LLM (pattern #20). `recharts` is already installed.
- **`GUARDRAIL_FORCE_FAIL` demo toggle** in `guardrail.py` — a deliberate dev aid to make the retry observable. Safe to leave (env-gated) or delete in a `chore` commit; if it's ever exported in the uvicorn shell, every report burns a forced regeneration.
- **msgpack deserialization warning** — `Deserializing unregistered type app.schemas.report.FinalReport from checkpoint`. Benign now (works, warns about a future block) because we keep a `FinalReport` Pydantic instance in graph state and the checkpointer msgpacks it. Tidy later by registering the type (`allowed_msgpack_modules`) or storing `final_report` as a dict — the latter touches `synthesizer`/`guardrail`/`memory_extractor` attribute access, so it's not free.
- **V6.5** — crypto holdings via CoinGecko; activate the `max_crypto_pct` threshold in `risk_agent` (defined since V3, still inert).
- **V7** — NextAuth.js (replaces the hardcoded `idan_demo`); `report_id`/`thread_id` and the user-keyed store/namespaces are already auth-ready.
- **V8 stretch** — daily 08:00 Telegram digest (APScheduler, separate lighter graph), PWA, BOI prime-rate context, TASE tickers, a **second HITL interrupt** for rebalancing-intention tracking (the `human_review`/resume machinery now exists to reuse).
- **Memory lifecycle** — `context` on stored memories; merge/update/expire instead of append-only with prompt-level dedup. The `human_review` gate is the intended quality filter for the over-inference the extractor occasionally shows.
- **Also not built** — frontend tests; loading skeletons; optimistic UI; a shared `<Nav>`; pagination on `/history`; reading `_ALLOWED_ORIGINS` / store config from settings.

---

## Patterns established — load-bearing for V6.5+

40. **Reflexion guardrail cycle**: a conditional edge re-enters an *upstream* node (`synthesizer`) with feedback carried in State, bounded by a single `retry_count` int. Reducer fields (`sentiment_findings`) do **not** re-fire on the cycle because only `synthesizer`/`guardrail` run on it — the fan-out ran once, upstream.
41. **Layered validation, fail-fast**: cheap deterministic rule checks before the paid LLM-as-judge; a rule miss short-circuits the judge; a judge exception degrades to pass-through (the report already exists, so never trap the user in retries — an extension of pattern #22).
42. **Async checkpointer on its own async pool**: `AsyncPostgresSaver` (async methods, for the `astream_events` runtime) needs an `AsyncConnectionPool`, separate from the store's sync pool; `open=False` + `autocommit=True`, opened/closed in the lifespan.
43. **Loop-bound construction, deferred compile**: objects that bind to the event loop in `__init__` (the async saver) are built inside the lifespan, not at import. The graph singleton is compiled store-only at import and recompiled with the checkpointer via `set_checkpointer`; `get_graph()` reads the module's `graph` dynamically so it picks up the rebind.
44. **HITL three-node split**: `memory_extractor` (propose) → `human_review` (`interrupt()` gate) → `memory_saver` (persist approved only). The node holding `interrupt()` re-executes from the top on resume, so all pre-interrupt work is side-effect-free and the durable write lives strictly after the gate.
45. **Interrupt surfaced at the API boundary**: after the run, `graph.aget_state(config).next` containing the interrupt node reveals the pause; `report_complete` ships first, then `human_input_required` carries the proposals + `thread_id`. The report is never gated on approval.
46. **Resume by run-to-completion**: resume via `ainvoke(Command(resume=...))` (reliable, surfaces errors) rather than mapping a fragile resumed event firehose; synthesize the node status events around it; a `NO_PAUSED_RUN` guard rejects unknown/finished thread_ids for clean failures and idempotency.
47. **Two-transport SSE on the frontend**: `EventSource` for the GET generate stream; `fetch()` + `ReadableStream` + an SSE block parser for the POST resume stream (the body can't go through `EventSource`). `report_complete` is made non-terminal via a `terminalRef` so the stream survives to the pause and the auto-reconnect is defeated.

*(Patterns #1–#39 from V1–V5 remain in force.)*

---

## Environment notes for the next Claude

- **The checkpointer must be built in the running loop.** `AsyncPostgresSaver(conn=pool)` at module import raises `RuntimeError: no running event loop`. It is constructed in `open_checkpointer()` (awaited in the lifespan); `builder.set_checkpointer()` then recompiles the graph. Do not move it back to import scope.
- **Three pools, one Postgres**: SQLAlchemy engine (ORM), sync psycopg `ConnectionPool` (store), async psycopg `AsyncConnectionPool` (checkpointer). All against the same DB. The async one needs `autocommit=True` for `setup()`.
- **Every graph run now needs a `thread_id`** — `config={"configurable": {"thread_id": report_id}}`. The store-less/checkpointer-less compile is only for tests; the served graph (post-lifespan) is checkpointer-bound. `report_id == thread_id`, and checkpoints persist in Postgres across uvicorn restarts.
- **Resume uses `ainvoke`, not `astream_events`.** The resumed `astream_events(Command(resume=...))` stream emitted an empty 200 here. If you ever revisit streaming the resume, verify it emits node events on a resumed run in the installed version first.
- **Interrupt detection** keys on `aget_state(config).next` containing `"human_review"` (with a fallback to `snapshot.interrupts` / `tasks[*].interrupts`). The same check guards the resume endpoint.
- **`GUARDRAIL_FORCE_FAIL=1`** forces one guardrail failure on the first evaluation — handy to demo the retry, but if it's exported in the uvicorn shell every report regenerates. Launch plain `uvicorn app.main:app --reload`.
- **Two services up** for the app: `uvicorn` on :8000 (from `backend/`, venv active) **and** Postgres (`docker compose up -d` from repo root). Frontend `npm run dev` on :3000; CORS allows :3000 (the resume POST triggers a preflight that the wildcard `allow_methods`/`allow_headers` answer).
- **Dev gotcha (Git Bash):** multi-line `curl` with `\` continuation breaks if blank lines separate the lines (the first command runs with no body → 422; `-H`/`-d` become "command not found"). Use single-line `curl`s when testing the SSE/resume endpoints.
- **Benign warning:** `Deserializing unregistered type … FinalReport from checkpoint` fires on `aget_state` (we keep a Pydantic `FinalReport` in State). Output unaffected; see deferred.
- Commits follow conventional format; each V6 step landed as its own commit; the version concluded with `git tag -a v6`.

---

## V6 git history

Each step landed as its own conventional commit on `main`:

```
feat(v6): add guardrail node with rule checks and LLM-as-judge
feat(v6): wire the guardrail Reflexion loop into the graph
feat(v6): add async PostgresSaver checkpointer wired into lifespan
feat(v6): split memory persistence behind a human_review interrupt
feat(v6): surface the memory-review interrupt and add resume endpoint
feat(v6): add memory-review HITL flow to the frontend
docs(v6): add V6 implementation brief
(tag) v6
```

To reconstruct the V6 baseline at any point: `git checkout v6`.
