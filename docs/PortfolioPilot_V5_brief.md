# PortfolioPilot V5 — Implementation Brief

> Appendix to `PortfolioPilot_SRS_dev.md`. Captures what was built across V5 (V5a backend semantic memory, V5b report persistence + transparency endpoints, V5c history/memory frontend), what deviated from the SRS, and what was explicitly deferred — so any subsequent Claude conversation picks up with full context.

**Status:** Shipped Day 5. Tagged `v5` on `main`. Pushed to `github.com/IdanRodri17/PortfolioPilot`.

**Smoke tests passed:**
- `store.py` one-liner: pool opens, `store.setup()` provisions pgvector + the store tables, an OpenAI embedding write succeeds, and `store.search()` returns semantically ordered results (a "should I sell my bitcoin" query scored a crypto-volatility memory at 0.408 vs an unrelated ETF memory at 0.132).
- Lifespan: `uvicorn` boots to "Application startup complete" with no error; `\dx` shows `vector`, `\dt` shows `store` / `store_vectors` / `store_migrations` / `vector_migrations` alongside the SQL tables; `Ctrl+C` exits cleanly (pool closed).
- `memory_loader` standalone: returns seeded memories ordered by relevance to a tech portfolio (NVDA/tech-concentration insights above an energy/oil one).
- Synthesizer: with a seeded "reluctant to trim AAPL" memory, the report still recommends reducing AAPL (the 37.3% > 35% violation is not suppressed) but the rationale + narrative acknowledge the preference — the reconciliation hierarchy holds.
- `memory_extractor` standalone: proposes 1–3 durable, user-level insights and persists them; readback from the store matches.
- **Full memory loop (2-pass):** clear `idan_demo` → run 1 from empty (event order `memory_loader → data_ingestion → fan-out burst → synthesizer → memory_extractor → report_complete`; saves 3 insights) → run 2's narrative references "your preference for a balanced risk profile and openness to rebalancing" — text that only exists because `memory_loader` surfaced what `memory_extractor` wrote on run 1. The loop is closed.
- Report persistence: `report_complete` carries `report_id`; a row lands in `reports` with `confidence_flag` `high` and `raw_result->>'confidence'` = `0.8`.
- `GET /api/reports/history/{user_id}` lists summaries newest-first; `GET /api/reports/{report_id}` replays the full report; bad id → 404.
- `GET /api/memories/{user_id}` lists insights; `DELETE` returns `{"deleted": N}`; subsequent `GET` is empty.
- Frontend: `/history` lists past reports and clicking one renders it via `FinalReportView`; `/memory` lists insights with a working **Wipe memory** button; dashboard nav links (`Edit portfolio · History · Memory`) all route.

---

## What was built

### V5a — Backend semantic memory

```
backend/
├── requirements.txt              # + langgraph-checkpoint-postgres; psycopg[binary] → psycopg[binary,pool]
└── app/
    ├── main.py                   # REWORKED: create_all moved into a lifespan ctx mgr; + open_store/close_store; v0.5.0
    └── graph/
        ├── builder.py            # compile(store=store); START→memory_loader→…→memory_extractor→END; _build_graph(store=)
        ├── state.py              # + long_term_memory, + new_memories
        ├── persistence/
        │   ├── __init__.py       # NEW (package)
        │   └── store.py          # NEW: PostgresStore singleton (pool, index, open_store/close_store, conninfo xlate)
        └── nodes/
            ├── memory_loader.py   # NEW: semantic recall → long_term_memory (store injected)
            ├── memory_extractor.py# NEW: propose 0–3 durable insights + auto-save (store injected)
            └── synthesizer.py     # + long_term_memory consumption + reconciliation rules in the prompt
```

**Graph topology (V5):** `START → memory_loader → data_ingestion → [Send fan-out: sentiment_agent × N + risk_agent] → synthesizer → memory_extractor → END`. Compiled **with** the `PostgresStore` so LangGraph injects it into the two memory nodes.

**Memory model:** insights are stored in the `PostgresStore` under the namespace `("memories", user_id)`, each as `{"insight": str}`, with the `insight` field embedded (`text-embedding-3-small`, 1536-dim) for cosine search. `memory_loader` retrieves the top-5 most relevant; `memory_extractor` writes 0–3 new ones per run (auto-save in V5).

### V5b — Backend report persistence + transparency

```
backend/app/
├── db/models.py                  # + Report (uuid PK, user_id FK, generated_at, raw_result JSONB, confidence_flag)
├── api/
│   ├── generate.py               # + report_id (uuid4); _persist_report() via own SessionLocal; report_id in report_complete
│   ├── reports.py                # NEW: GET /api/reports/history/{user_id}, GET /api/reports/{report_id}
│   └── memories.py               # NEW: GET /api/memories/{user_id}, DELETE /api/memories/{user_id}
└── main.py                       # + mount reports_router, memories_router
```

Reports are archived **at the API boundary** (in the SSE generator, using a short-lived session — not the request session), keeping report history distinct from the graph's semantic memory. `raw_result` holds the full `FinalReport`, so `/api/reports/{id}` replays a report verbatim with no graph re-run.

### V5c — History + memory frontend

```
frontend/src/
├── app/
│   ├── page.tsx                  # + nav row (Edit portfolio · History · Memory)
│   ├── history/page.tsx          # NEW: past reports newest-first; click → FinalReportView
│   └── memory/page.tsx           # NEW: learned insights + Wipe memory button
└── lib/
    ├── types.ts                  # + Memory, ReportSummary, ReportDetail
    └── api.ts                    # + getMemories, deleteMemories, getReportsHistory, getReport
```

**Pages (4 now):** dashboard `/`, editor `/portfolio`, history `/history`, memory `/memory`. The history detail view reuses `FinalReportView`. Navigation is a small inline nav row on the dashboard (no shared `<Nav>` component — see deviations).

---

## Deviations from the SRS

| Area | SRS as written | V5 actually does | Why |
|---|---|---|---|
| `lifespan` context manager | Slated for V6 (checkpointer setup) | **Pulled into V5.** `create_all` moved out of `create_app()`; `open_store()`/`close_store()` driven by lifespan. | The store pool needs a *paired* open/close, and a module-level call can only open. Building a throwaway in V5 and replacing it in V6 is wasted work; V6's `PostgresSaver` slots into the same startup block. |
| `langgraph-checkpoint-postgres` | Listed under V6 (for `PostgresSaver`) | **Installed in V5.** | `PostgresStore` ships in the same package, so V5 needs it; V6's checkpointer import is then already covered. Also bumped `psycopg[binary]` → `psycopg[binary,pool]` for `ConnectionPool`. |
| Store module location | §9 tree placed it directly under `graph/` | `graph/persistence/store.py` | Matches the `db/base.py` docstring ("the persistence layer") and groups V6's `checkpointer.py` beside it. |
| Store construction | `PostgresStore.from_conn_string(...)` (context manager) | Explicit `ConnectionPool(open=False, autocommit=True)` + `PostgresStore(conn=pool, index=...)` | The CM form closes on exit; an explicit pool gives a long-lived singleton whose lifecycle the app controls. `open=False` keeps imports DB-free; `autocommit=True` is required for the store's DDL/writes. |
| DB URL for the store | `DATABASE_URL` reused as-is | `+psycopg` stripped (`postgresql+psycopg://` → `postgresql://`) | psycopg's `ConnectionPool` passes conninfo straight to libpq, which rejects SQLAlchemy's dialect marker. |
| Embedding config | `OpenAIEmbeddings(model=...)` object | `"embed": "openai:text-embedding-3-small"` string form | Resolved by langchain; one less import. Equivalent result. |
| `memory_extractor` persistence | §4.5 propose→approve→save (HITL) | **Propose + auto-save in V5** (per the SRS's own V5/V6 split). The `human_review` gate is V6. | V5 closes the loop without HITL; V6 inserts the approval step. |
| `new_memories` State field | Listed under V6 | Lands in V5 | `memory_extractor` returns it now (what was saved). The `proposed_memories`/`approved_memories` split stays V6. |
| Report write location | Not specified | At the API boundary (handler/generator), not a graph node | Pattern #7: report *history* is a UI concern; the store is the graph's cognition. The write uses its own scoped session inside the otherwise DB-free generator. |
| `report_id` in `report_complete` | Not specified | Flat extra field on the payload | Non-breaking — the existing dashboard ignores it; `/history` reads it. The fuller payload wrap was deferred with the pie. |
| Reports/memories response models | Portfolio routes used Pydantic `response_model` | Plain shaped `dict`/`list` returns | The JSONB `raw_result` and the store are the runtime source of truth; re-validating through Pydantic would be redundant for read endpoints. |
| Value-weighted Recharts pie | §2/§8 + V4 deferred-to-V5 | **Not built** — deferred (see below) | Cuttable per the V4 brief; skipped to ship V5 on schedule. |
| Shared `<Nav>` component | Implied by multi-page §8.1 | Inline nav row on the dashboard | Four pages still don't justify the abstraction (YAGNI); inline `<Link>`s suffice, consistent with V4. |

---

## Explicitly deferred (do NOT build in V5; build in noted version)

- **Value-weighted allocation Recharts pie** (the main carried-over V5 item) → **V6 or a later polish pass.** It needs the `risk_agent`'s value-weighted composition surfaced through the `report_complete` payload (a small wrap: `{report, composition}`) and a Recharts `PieChart` in `PortfolioOverview` (`recharts` is already installed). Deterministic numbers must come from `risk_agent`, not the LLM (pattern #20). Also a natural moment to formalize the `report_complete` payload shape rather than the current flat `report_id` extra field.
- **V6** — guardrail Reflexion loop (cyclic edge synthesizer↔guardrail, retry budget 2); `interrupt()` + `Command(resume=...)` + `PostgresSaver` checkpointer (reusing `report_id` as `thread_id`); the `memory_extractor → human_review → memory_saver` split for HITL memory approval; `human_input_required` SSE event (slot reserved); `POST /api/resume-graph`; `MemoryReviewModal` frontend flow.
- **V6.5** — crypto holdings via CoinGecko; activate the `max_crypto_pct` threshold in `risk_agent`.
- **V7** — NextAuth.js authentication (replaces the hardcoded `idan_demo`).
- **V8 stretch** — daily 08:00 Telegram digest (APScheduler), installable PWA, Bank of Israel prime-rate context, TASE tickers.
- **Memory quality / lifecycle** (no firm version) — `memory_extractor` can occasionally over-infer (e.g., assuming the user "is open to" a recommendation it merely made). V6's `human_review` gate is the intended filter. Append-only memory with prompt-level dedup is the V5 approach; merging/updating/expiring memories is future work.
- **Also not built (no version target):** frontend tests, loading skeletons beyond simple text states, optimistic UI on the wipe action, a shared `<Nav>` component, pagination on `/history` (currently returns all reports), `_ALLOWED_ORIGINS`/store config read from settings.

---

## Patterns established — load-bearing for V6+

31. **PostgresStore semantic memory layer**: a LangGraph-managed key-value store (pgvector-indexed), distinct from the SQLAlchemy layer — addressed by namespace tuples `("memories", user_id)`, retrieved by `store.search(namespace, query=...)` (semantic) or no-query (list mode). Its tables are provisioned by `store.setup()`, not declared on `Base.metadata`.
32. **Dedicated persistence pool**: a `psycopg ConnectionPool` separate from the SQLAlchemy engine's pool (the two hand out incompatible connection objects). Created `open=False` (imports stay DB-free) with `autocommit=True` (required for the store's DDL/writes); the SQLAlchemy `DATABASE_URL` is translated to a libpq conninfo by stripping `+psycopg`.
33. **Lifespan-managed provisioning**: `create_all` + `store.setup()` (and V6's checkpointer) run on startup and the pool closes on shutdown, in one place. Replaces the V2–V4 imperative `create_all` at construction; constructing the app no longer touches the DB.
34. **Compile-with-store + store injection**: `builder.compile(store=store)` so nodes with a keyword-only `store: BaseStore` parameter receive it from the runtime. Nodes never import the store global. This is the first deliberate exception to graph purity (#7) — memory nodes do I/O to the graph's *own* cognition via an injected store, so the V8 scheduler still reuses the same compiled graph.
35. **Reconciliation hierarchy in prompts**: when remembered preferences conflict with deterministic analysis, the data/risk analysis is authoritative; memory personalizes framing but never suppresses a genuine violation or invents facts, and stays silent when no memory is on record.
36. **Propose-and-persist with dedup**: `memory_extractor` proposes 0–3 durable, user-level insights (an empty proposal is valid), deduplicated against the run's loaded memory, and auto-saves them in V5. The propose→approve→save split is a V6 concern.
37. **Boundary persistence with a scoped session**: the report archive write opens its own short-lived `SessionLocal` inside the otherwise DB-free SSE generator — not the request session — within a single await-free window, and is best-effort (a failed archive never denies the user the delivered report).
38. **Shaped-dict read endpoints**: reports/memories read handlers return lightweight `dict`/`list` shapes derived from `raw_result` / store items rather than re-validating through Pydantic `response_model`s; the JSONB and the store are the runtime source of truth.
39. **Frontend continuity**: hand-kept TS mirrors for the new endpoints; the `/history` detail view reuses `FinalReportView`; per-container explicit dark theming (#29) continued; navigation is an inline row, not a shared component.

*(Patterns #1–#30 from V1–V4 remain in force.)*

---

## Environment notes for the next Claude

- **Store lifecycle**: the persistence pool is created `open=False` at import (so importing `builder.py` needs no live DB); `open_store()` (pool open + `store.setup()`) runs in `main.py`'s lifespan, `close_store()` on shutdown. `store.setup()` is idempotent — warm restarts and `--reload` are no-ops.
- **Two pools, one DB**: the SQLAlchemy engine pool (ORM) and the psycopg pool (store, + V6 checkpointer) are independent against the same Postgres. The store pool needs `autocommit=True`.
- **Memory namespace**: `("memories", user_id)`. `store.search(ns, query=...)` is semantic; `store.search(ns)` (no query) is list mode — the endpoints pass `limit=100` so listing/wiping covers everything for the demo.
- **`DELETE /api/memories/{user_id}` wipes** — repopulate by running a report (or the 2-pass loop). Reports are unaffected by a memory wipe (separate table).
- **`report_id` is the V6 `thread_id`** — minted in the generate handler (`uuid4`), persisted as the `Report` PK, and reused for the checkpointer in V6.
- **Benign warning**: `PydanticSerializationUnexpectedValue ... field_name='parsed'` fires once per `with_structured_output` call (langchain issue #35538, Pydantic 2.12 vs langchain's internal `parsed` annotation). Output is unaffected. An optional narrow suppression (`warnings.filterwarnings("ignore", message="Pydantic serializer warnings", category=UserWarning)`) can be added in `core/config.py`.
- **App INFO logs are hidden by default** (root logger sits at WARNING via Python's last-resort handler, so `logger.info` in nodes is dropped while `logger.warning` shows; the `warnings` module is a separate channel, which is why the Pydantic warning appears). An optional scoped snippet on the `app` logger in `main.py` surfaces them.
- **`memory_extractor` model**: gpt-4o-mini, temperature 0.2. It can over-infer preferences from the system's own recommendations; V6's `human_review` is the intended quality gate.
- **Two services up** for the app: `uvicorn` on :8000 (from `backend/`, venv active) **and** the Postgres container (`docker compose up -d` from repo root). A stopped Postgres makes startup fail (lifespan can't open the pool / run `setup()`).
- Commits follow conventional format; each V5 step landed as its own commit; the version concluded with `git tag -a v5`. (A few optional `chore(v5)`/`refine(v5)` commits — logging, warning suppression, extractor prompt hardening — may also be present depending on whether those optional tweaks were applied.)

---

## V5 git history

Each step landed as its own conventional commit on `main`:

```
feat(v5): add PostgresStore semantic memory singleton
feat(v5): provision db and store via FastAPI lifespan
feat(v5): add memory_loader node for semantic memory retrieval
feat(v5): wire memory_loader as graph entrypoint, compile with store
feat(v5): synthesizer consumes long_term_memory for personalization
feat(v5): add memory_extractor node (propose + auto-save insights)
feat(v5): wire memory_extractor as terminal node, close memory loop
feat(v5): add Report model for persisted report history
feat(v5): persist generated reports at the API boundary
feat(v5): add report history endpoints
feat(v5): add memory transparency endpoints
feat(v5): add memory and history pages with dashboard nav
docs(v5): add V5 implementation brief
(tag) v5
```

To reconstruct the V5 baseline at any point: `git checkout v5`.
