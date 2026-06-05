# PortfolioPilot — Code-Review Prep Guide

> A study aid for walking a reviewer through the **current shipped code (V5)**. Internalize it — don't read from it. Everything below matches what's actually in the repo today; the guardrail loop and human-in-the-loop flow are **V6/planned**, so they're under *Roadmap*, not described as built.

---

## 0. The 30-second framing (say this first)

"PortfolioPilot is an AI wealth manager. You give it a stock portfolio and a risk profile; it fetches live prices, reads recent news per holding in parallel, checks the portfolio against risk thresholds, and produces one structured, grounded report — streamed live to the dashboard as the agents work. It's built as a **stateful multi-agent graph in LangGraph**, on a FastAPI backend with a Next.js frontend and PostgreSQL + pgvector. Over runs it builds a private semantic memory of the user's preferences and personalizes the reports."

If asked *"what is LangGraph?"*: "A library for building stateful, multi-agent LLM systems as graphs — nodes are functions that read and write a shared state, edges define control flow. Unlike a plain chain it supports parallel fan-out, cycles, durable persistence, and human-in-the-loop pauses. The runtime is a Pregel-style superstep model."

---

## 1. The end-to-end data flow (the core walk-through)

Trace one report from click to render. Know this cold — it's the spine of the review.

1. **Frontend** — user clicks *Generate report*. `useReportStream.ts` opens a browser `EventSource` to `GET /api/generate-report?user_id=idan_demo`. (GET, not POST, because native `EventSource` only supports GET.)

2. **Handler** (`api/generate.py` → `generate_report`) — looks up the `User` + `Portfolio` from Postgres **synchronously, at the boundary**, builds a plain `initial_state` dict `{user_id, portfolio, risk_profile}`, mints a `report_id = uuid4()`, and returns a `StreamingResponse` wrapping the async generator `_report_event_stream(graph, initial_state, report_id)`. The DB session is **not** held open across the stream.

3. **Graph drive** — the generator consumes `graph.astream_events(initial_state, version="v2")`. As nodes start/finish, it emits SSE `status` events (filtered to `_STATUS_NODES`).

4. **`memory_loader`** (entrypoint) — builds a natural-language query from the portfolio + risk profile, calls `store.search(("memories", user_id), query=..., limit=5)`, and loads the top-5 most relevant past insights into `state["long_term_memory"]`. Degrades to `[]` on failure.

5. **`data_ingestion`** — fetches price + 24h change per symbol via the yfinance wrapper (`tools/stock_data.py`), populating `state["market_data"]`. A failed ticker is skipped with a warning, not fatal.

6. **Fan-out** — a conditional edge (`fan_out_to_agents`) returns a **list of `Send` objects**: one `sentiment_agent` per holding + one `risk_agent`. LangGraph runs them **concurrently**.
   - **`sentiment_agent`** (one per symbol, gpt-4o-mini) — Tavily news search (`tools/news_search.py`) → classify Positive/Neutral/Negative with a grounded 1-2 sentence summary. Returns a single-item list into `sentiment_findings`.
   - **`risk_agent`** (single, **deterministic — no LLM**) — computes value-weighted composition %, checks `RISK_PROFILES` thresholds, flags violations (e.g. "AAPL 37.3% > balanced cap 35%"). Writes `risk_analysis`.

7. **Fan-in / barrier** — both branch types have a static edge to `synthesizer`, so it fires **only after every branch completes**. The `Annotated[List[dict], add]` reducer on `sentiment_findings` has merged all the parallel returns into one list.

8. **`synthesizer`** (gpt-4o, `.with_structured_output(FinalReport)`) — consumes portfolio + market_data + merged sentiment + risk_analysis + `long_term_memory`, and produces the structured `FinalReport`. Memory **personalizes framing** but never overrides a real risk violation (the reconciliation hierarchy).

9. **`memory_extractor`** (terminal node, gpt-4o-mini) — distills 0-3 durable, user-level insights from the report and **persists them** to the store (V5 auto-saves; V6 adds a human approval gate). Writes `new_memories`.

10. **Persist + finish** — back in the generator, the finished `FinalReport` (captured from the synthesizer's `on_chain_end`) is archived via `_persist_report()` using its **own short-lived `SessionLocal`** (best-effort), then the generator emits `report_complete` with the report JSON + `report_id`.

11. **Frontend** — `LiveStatusFeed` showed the pipeline live; `FinalReportView` renders the final report. `/history` and `/memory` read the new endpoints.

**Shipped V5 topology:** `START → memory_loader → data_ingestion → [Send: sentiment×N + risk] → synthesizer → memory_extractor → END`.

---

## 2. `PortfolioState` (know every field + who writes it)

`graph/state.py` — a `TypedDict(total=False)`. Each node returns a partial dict; LangGraph merges it in.

| Field | Type | Written by | Reducer? |
|---|---|---|---|
| `user_id` | `str` | handler (input) | — |
| `portfolio` | `Dict[str, float]` | handler (input) | — |
| `risk_profile` | `RiskProfile` | handler (input) | — |
| `long_term_memory` | `List[dict]` | `memory_loader` | no (single writer) |
| `market_data` | `Dict[str, dict]` | `data_ingestion` | no |
| `sentiment_findings` | `Annotated[List[dict], add]` | **N parallel `sentiment_agent`s** | **yes — `add`** |
| `symbol` | `str` | per-Send payload | no (per-branch) |
| `risk_analysis` | `Dict[str, Any]` | `risk_agent` | no (single writer) |
| `final_report` | `FinalReport` | `synthesizer` | no |
| `new_memories` | `List[dict]` | `memory_extractor` | no |

**Two things to be able to say:**
- **Why `TypedDict`, not Pydantic:** state mutates on every node return and every reducer merge — `TypedDict` is a zero-cost type hint over a dict, no validation/copy overhead. Pydantic is reserved for the *boundaries* (API contracts + LLM structured output). "Validate at the edges, stay lightweight in the hot path."
- **Why the `add` reducer on `sentiment_findings`:** parallel branches writing the same key would clobber each other (last-write-wins) — four of five sentiment results would vanish. `add` is list concatenation, so each branch returns a one-item list and they fold into one. **`risk_analysis` deliberately has no reducer** because exactly one node writes it — reducer presence/absence is a *readable signal* of multi- vs single-writer.

---

## 3. The graph (`builder.py`) — the LangGraph crown jewels

- `_build_graph(store=None)` constructs the `StateGraph`, adds nodes, wires edges, and returns `builder.compile(store=store)`. A module-level `graph = _build_graph(store=memory_store)` singleton is built once at import. The factory takes `store` (and V6 will add `checkpointer=`) so it's never reaching for a global inside `compile()`.
- **Fan-out** is `add_conditional_edges("data_ingestion", fan_out_to_agents, ["sentiment_agent", "risk_agent"])`. The router returns a **list of `Send`** → spawn-N parallel. (Same API returns a single string for if/else routing — that's how the V6 guardrail will route.)
- The `["sentiment_agent", "risk_agent"]` list is the **enumeration of all possible Send targets**, required for static graph validation.
- **Implicit barrier:** `sentiment_agent → synthesizer` and `risk_agent → synthesizer` edges mean synthesizer waits for all branches. No explicit `join()`.

**`Send()` — the impressive subtlety:** the number of parallel branches **isn't known at graph-definition time** — it's the size of the portfolio, decided at runtime. Static parallel edges can't do that. `Send()` is what makes the fan-out dynamic, and its payload dict *is* the state that branch sees (`{**state, "symbol": symbol}`).

**Superstep / Pregel:** LangGraph executes in supersteps (bulk-synchronous-parallel) — all nodes in a step run concurrently, updates merge through reducers at the boundary, then the next step begins. The academic lineage is Google's **Pregel** — drop that word if pushed on the execution model.

---

## 4. Two persistence layers (nail this — people conflate them)

- **The Store** (`PostgresStore`, `graph/persistence/store.py`) — *cross-thread, long-term, **semantic** memory.* pgvector-indexed, addressed by namespace `("memories", user_id)`, queried by `store.search(ns, query=...)` which embeds the query (OpenAI `text-embedding-3-small`, 1536-dim) and runs cosine similarity. It's the graph's **own cognition**, injected into nodes via `compile(store=...)`. Auto-provisions its tables (`store`, `store_vectors`, …) via `store.setup()` — *not* declared on SQLAlchemy's `Base`.
- **Report history** (`reports` table, plain SQLAlchemy) — written at the **API boundary**, not in a node, because history is a UI concern distinct from the graph's memory. `raw_result` JSONB holds the full report so `/api/reports/{id}` replays it verbatim with no graph re-run.
- *(V6)* **The Checkpointer** (`PostgresSaver`) — *per-thread, short-term state snapshots* keyed by `thread_id` (we reuse `report_id`), which is what will make pause/resume possible. Different job, different tables, different lifetime from the Store.

**The memory loop (your best live demo):** `memory_extractor` saves insights → next run's `memory_loader` recalls them → `synthesizer` weaves them in. Wipe memory, run twice, and the second report references what the first taught it.

---

## 5. Key design decisions (the *why* — teacher gold)

- **Graph purity / I/O at the boundary.** The graph's input is `{user_id, portfolio}`; it doesn't know Postgres exists. DB lookups live in the handler. Keeps the graph trivially testable (just a dict) and reusable by the planned daily-digest scheduler. **The one deliberate exception** is the memory nodes — they do I/O to the graph's *own* semantic memory, via an **injected** store (not the request DB session), so the principle holds.
- **Deterministic `risk_agent`.** Percentages are arithmetic; LLMs are unreliable at math. Pure Python is cheaper, faster, deterministic, and verifiable.
- **Structured output.** `.with_structured_output(FinalReport)` injects the Pydantic schema (with field descriptions) as the LLM's format spec, constraining output at sampling time. "The field descriptions aren't documentation — they're prompt engineering." (Demo: `print(FinalReport.model_json_schema())`.)
- **No token streaming.** The synthesizer emits one structured object, so streaming its tokens would give partial JSON — the streaming that carries the demo is the burst of `status` events.
- **`run_id` correlation in SSE.** `astream_events` is a firehose. A parallel branch's `start` carries its symbol in `data.input`; its `end` doesn't — so the handler stashes `run_id → symbol` on start and recovers it on end. This is what lets each "AAPL done" match the right branch.
- **Boundary persistence with a scoped session.** The archive write opens its own short-lived `SessionLocal` inside the DB-free generator, best-effort — a failed archive never denies the delivered report.
- **Thin tool wrappers + graceful degradation.** yfinance/Tavily each live in one file with one custom exception; a failed news fetch returns a degraded "data unavailable" insight rather than sinking the whole report.
- **Model tiering.** gpt-4o-mini for the N parallel agents (cheap fan-out); gpt-4o for the heavier synthesizer prompt.

---

## 6. File map (jump here when asked "show me where X happens")

```
backend/app/
├── main.py                       # FastAPI app, CORS, lifespan (provisions DB + store), routers
├── api/
│   ├── generate.py               # GET /api/generate-report (SSE); _report_event_stream, _persist_report, _STATUS_NODES
│   ├── portfolio.py              # portfolio CRUD
│   ├── reports.py                # GET /api/reports/history/{uid}, GET /api/reports/{id}     (V5)
│   └── memories.py               # GET + DELETE /api/memories/{uid}                            (V5)
├── core/config.py                # pydantic-settings, env
├── db/
│   ├── base.py                   # engine, SessionLocal, Base, get_db
│   └── models.py                 # User, Portfolio, Report
├── graph/
│   ├── builder.py                # _build_graph, fan_out_to_agents, graph singleton
│   ├── state.py                  # PortfolioState (TypedDict + reducers)
│   ├── risk_profiles.py          # RISK_PROFILES thresholds
│   ├── persistence/store.py      # PostgresStore singleton, open_store/close_store
│   └── nodes/
│       ├── memory_loader.py      # semantic recall  → long_term_memory
│       ├── data_ingestion.py     # yfinance         → market_data
│       ├── sentiment_agent.py    # Tavily + LLM     → sentiment_findings (per symbol)
│       ├── risk_agent.py         # deterministic    → risk_analysis
│       ├── synthesizer.py        # gpt-4o           → final_report
│       └── memory_extractor.py   # distill + save   → new_memories
├── schemas/
│   ├── portfolio.py              # PortfolioRequest/Response, RiskProfile
│   └── report.py                 # FinalReport + PortfolioValuation, MarketInsight, RebalancingRecommendation
└── tools/{stock_data.py, news_search.py}
frontend/src/
├── app/{page.tsx, portfolio/page.tsx, history/page.tsx, memory/page.tsx}
├── components/{LiveStatusFeed, FinalReportView, PortfolioOverview}.tsx
└── lib/{types.ts, api.ts, useReportStream.ts}
```

---

## 7. Likely questions + crisp answers

- **"Why LangGraph and not plain LangChain or `asyncio.gather`?"** — For the shipped fan-out alone, raw `asyncio.gather` would do. LangGraph earns it as one coherent model for the *whole* system: typed state with deterministic reducer merges, the streaming event taxonomy from `astream_events`, and — the real justifier — the V6 durable checkpointer + `interrupt()` for human-in-the-loop, which has no lighter equivalent. Admit the replaceable parts; that makes the rest credible.
- **"Threads or async for the parallelism?"** — `sentiment_agent` is sync `def`, so LangGraph dispatches the Send-target branches through the asyncio threadpool when the graph is awaited. Five symbols → five workers; wall-clock is bounded by the slowest branch. Would move to `async def` + async clients if latency demanded.
- **"What if one analyst fails mid-run?"** — Graceful degradation inside the branch: it returns a Neutral "data unavailable" insight instead of letting the exception propagate and 500 the report. The other four are unaffected.
- **"How do you stop hallucinated numbers?"** — Three layers: `.with_structured_output` constrains the shape; the risk math is deterministic Python passed *into* the prompt; the synthesizer is told to use the upstream sentiment verbatim, not re-derive. (V6 adds a guardrail loop as a fourth.)
- **"Why Postgres for memory, not Pinecone?"** — Cohesion: pgvector lives in the same Postgres I already run; `PostgresStore.setup()` provisions the vector tables automatically; a managed vector DB is operational overhead with no payoff at this scale. One DB, two connection pools.
- **"Why is `risk_agent` not an LLM?"** — It's arithmetic. Deterministic Python is cheaper, exact, and verifiable; an LLM would add cost and a hallucination surface for numbers it can't reliably produce.
- **"Walk me through the state during a run."** — Use the table in §2: handler seeds the three inputs; `memory_loader` adds `long_term_memory`; `data_ingestion` adds `market_data`; the parallel branches accumulate `sentiment_findings` (via the reducer) and `risk_analysis`; `synthesizer` writes `final_report`; `memory_extractor` writes `new_memories`.

---

## 8. Be honest about limits (frame as roadmap, not gaps)

- **Memory can over-infer** (e.g. assuming the user "accepted" a recommendation it merely made). V6's human-approval gate is the intended filter.
- **Guardrail loop + HITL are designed, not shipped** (V6). If asked directly whether they're live: *"the parallel analysis, streaming, dashboard, semantic memory loop, and report/memory endpoints are shipped; the self-correcting guardrail and human-approval flow are fully architected and landing next."* Precision beats a vague "yes."
- **Single user** (`idan_demo`) — real auth is V7 (NextAuth).
- **No crypto yet** (V6.5, CoinGecko) — the `Dict[str, float]` assets shape already supports it.
- **Value-weighted allocation pie** — deferred to a polish pass (the data comes from `risk_agent`'s composition, surfaced through `report_complete`).
- **No test suite / CI on this repo yet** — acknowledged; the per-version smoke tests stand in for now.

---

*Roadmap recap: V6 guardrail + HITL · V6.5 crypto · V7 auth · V8 Telegram digest + PWA + Israeli-market context.*
