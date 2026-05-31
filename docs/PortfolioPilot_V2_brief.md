# PortfolioPilot V2 — Implementation Brief

> Appendix to `PortfolioPilot_SRS_dev.md` and `PortfolioPilot_V1_brief.md`. Captures what was built on Day 2 (V2), what deviated from the SRS, and what was explicitly deferred — so any subsequent Claude conversation picks up with full context.

**Status:** Shipped Day 2. Tagged `v2` on `main`. Pushed to `github.com/IdanRodri17/PortfolioPilot`.

**Smoke test passed:**
- `docker compose up -d` brings up Postgres with pgvector pre-installed; healthcheck green.
- `POST /api/portfolio` creates a user + portfolio in one transaction; resubmitting full-replaces both.
- `GET /api/portfolio/{user_id}` returns denormalized response (assets + risk_profile + updated_at); 404 on missing.
- `GET /api/generate-report?user_id=idan_demo` reads portfolio from DB and runs the (topologically unchanged) graph against it.
- Multi-asset portfolios produce one `MarketInsight` per priced symbol; bogus tickers are skipped with a `logger.warning` and flagged in the synthesizer prompt (no fabricated prices).
- TASE ticker `TEVA.TA` verified working via yfinance — NVDA + TEVA.TA 2-asset report returned a `portfolio_valuation.total_usd` of $26,480 with sensible per-asset insights.
- Pydantic 422 rejection for negative quantities (custom `field_validator`) and invalid risk_profile values (Literal mismatch).

Demo portfolio at end of V2: `idan_demo` with `{AAPL: 10, MSFT: 5, NVDA: 3, GOOGL: 2, TSLA: 4}`, balanced — staged for V3's 5-symbol parallel `Send()` demo.

---

## What was built

```
PortfolioPilot/
├── docker-compose.yml                     # NEW at repo root — postgres only (backend container deferred)
└── backend/
    ├── .env / .env.example                # + DATABASE_URL
    ├── requirements.txt                   # + sqlalchemy, psycopg[binary]
    └── app/
        ├── main.py                        # + create_all, + portfolio router, + side-effect import of models
        ├── core/config.py                 # + database_url field
        ├── api/
        │   ├── generate.py                # rewrite: DB lookup replaces V1 hardcode
        │   └── portfolio.py               # NEW — POST upsert, GET fetch
        ├── schemas/
        │   └── portfolio.py               # NEW — PortfolioRequest, PortfolioResponse, RiskProfile alias
        ├── db/                            # NEW directory
        │   ├── __init__.py
        │   ├── base.py                    # engine, SessionLocal, Base, get_db
        │   └── models.py                  # User, Portfolio (JSONB assets)
        └── graph/nodes/
            ├── data_ingestion.py          # + per-symbol try/except, logger.warning, skip-on-fail
            └── synthesizer.py             # + markdown table formatters, + missing_assets_block
```

**Graph topology:** unchanged from V1 (`START → data_ingestion → synthesizer → END`). The V2 architectural change is at the boundary, not inside the graph.

**Endpoints live:**
- `GET /api/health` (unchanged)
- `POST /api/portfolio` (NEW V2 — upsert)
- `GET /api/portfolio/{user_id}` (NEW V2 — fetch or 404)
- `GET /api/generate-report?user_id=…` (rewired to DB lookup; V1 hardcode removed)

**V2 `requirements.txt` adds:** `sqlalchemy`, `psycopg[binary]` (psycopg v3, matches the `postgresql+psycopg://` URL scheme — *not* `psycopg2-binary`).

---

## Deviations from the SRS

| Area | SRS as written | V2 actually does | Why |
|---|---|---|---|
| Postgres image | "PostgreSQL + pgvector" (§2, image unspecified) | `pgvector/pgvector:pg16` from step 1 | pgvector pre-installed in the image avoids a `CREATE EXTENSION` dance or volume wipe when V5's `PostgresStore.setup()` lands. Same Postgres, just with the extension primed. |
| Timestamps | `datetime.utcnow` Python-side default (§6.1) | `server_default=func.now()` with `DateTime(timezone=True)` | Avoids Python 3.12's `datetime.utcnow()` `DeprecationWarning`; timestamps come from Postgres (single clock) regardless of which app server inserts the row; `TIMESTAMPTZ` is the correct Postgres default. |
| `Portfolio.user_id` constraints | `ForeignKey("users.id")` only (§6.1) | + `unique=True`, `index=True`, `ondelete="CASCADE"` | `unique=True` enforces 1-to-1 with users at the DB level (which the `uselist=False` relationship on the User side merely *implies*); makes a future `ON CONFLICT (user_id) DO UPDATE` upsert valid. `ondelete=CASCADE` + `cascade="all, delete-orphan"` on the relationship gives clean deletion semantics. |
| `User.telegram_chat_id` | Present in SRS (V8 stretch column, §6.1) | Not declared in V2 | Pure V8 stretch; non-breaking ALTER when (if) V8 ships. |
| `Report` model | Present in SRS (§6.1) | Not declared in V2 | V5 owns it (historical report persistence) per the version plan. |
| Pool config | Not specified | `pool_pre_ping=True`, `expire_on_commit=False` | `pool_pre_ping` catches Postgres-dropped idle connections (common after Docker pauses overnight). `expire_on_commit=False` keeps ORM objects usable after `db.commit()` — the standard FastAPI pattern that avoids `DetachedInstanceError` when serializing back to the client. |
| `risk_profile` propagation into State | SRS state schema lists it as an input (§4.1) | Read from DB in the handler, NOT yet threaded into `PortfolioState` | V2 graph has no node that uses it (V3's `risk_agent` is the first consumer). Adding an unused State field now would be deferred churn. V3 step 1 will add it. |
| `data_errors` in State | Not in SRS | Not added in V2 either — synthesizer derives missing set from `set(portfolio.keys()) - set(market_data.keys())` | Simpler than threading an error map through State. If `data_ingestion` quietly drops a symbol, `synthesizer` notices automatically — no coordination point. V3 may add explicit error tracking if richer context (rate-limited vs delisted) earns its keep. |
| `PortfolioResponse` shape | SRS only declares `PortfolioRequest` (§5.3) | Designed `PortfolioResponse` to denormalize `User.risk_profile` + `Portfolio.assets` + `Portfolio.updated_at` | Client needs both pieces to render a portfolio view; denormalizing at the response boundary saves a round-trip. ORM models stay normalized. |
| Asset quantity validation | Not specified | `field_validator` rejects `qty <= 0` | A "zero AAPL" holding is just a missing key. Defensive boundary check prevents nonsense downstream. |
| `RiskProfile = Literal[...]` | Used inline in SRS (§5.3) | Extracted as a named alias in `schemas/portfolio.py` | Reused in both PortfolioRequest and PortfolioResponse. V3 will import the same alias for State typing. |
| Migrations | Not specified | `Base.metadata.create_all(bind=engine)` at app startup; no Alembic | `CREATE TABLE IF NOT EXISTS` is idempotent; safe for forward-additive schema (V2-V6). Schema changes during dev: `docker compose down -v` + restart. Alembic earns its keep post-MVP. |
| Upsert pattern on `POST /api/portfolio` | Not specified | Read-then-write inside one transaction (race window flagged in docstring) | Clearer for the bootcamp's teaching goals than `INSERT ... ON CONFLICT`; demo is single-user-at-a-time so the race window is theoretical. Production hardening: row-level lock or true Postgres upsert. |
| Per-asset error handling in `data_ingestion` | V1 brief noted "not yet built" | **Built in V2 step 6** | Skipped symbols log a `WARNING` and are omitted from `market_data`; synthesizer prompt flags the gap to prevent price hallucination. |
| Synthesizer prompt format | V1 brief noted "consider markdown formatter in V2/V3" | **Built in V2 step 6** | Three private helpers in `synthesizer.py` render portfolio + market_data as markdown tables and conditionally render a missing-assets note. Will be extracted to a shared module if V3's `sentiment_agent` or `risk_agent` reuse the same shape. |
| `import app.db.models` side-effect | Not specified | Explicit in `main.py` with `# noqa: F401` | Required for SQLAlchemy: model classes must be *imported* into the process before `Base.metadata.create_all()` runs, or metadata is empty and the call is a silent no-op. The `noqa` comment makes intent legible to linters. |
| Sync `def` vs `async def` for handlers | Not specified | Portfolio CRUD: sync `def` (blocking SQLAlchemy → FastAPI threadpool). `/api/generate-report`: stays `async def` (awaits `graph.ainvoke`) | Sync `def` with sync DB is correct for FastAPI — the framework runs sync handlers in a threadpool, event loop stays free. Async `def` with sync DB calls would block the loop. Mixed pattern documented in handler docstrings. |
| POST status code | Not specified | `200 OK` on `POST /api/portfolio`, not `201 Created` | Upsert semantics: the route is "create or replace", not exclusively create. 200 better matches the unified write semantics. |

---

## Explicitly deferred (do NOT build in V2; build in noted version)

- **V3** — `Send()` fan-out, `Annotated[List, add]` reducer on `sentiment_findings`, `risk_agent` and `sentiment_agent` nodes, `risk_profile` field added to `PortfolioState` and threaded from the handler, Tavily wrapper at `app/tools/news_search.py`, `RISK_PROFILES` config at `app/config/risk_profiles.py`, synthesizer prompt rewrite to consume `sentiment_findings` + `risk_analysis`, `core/llm_provider.py` abstraction (likely V3 when sentiment + risk + synthesizer all need configured LLM access), gpt-4o for synthesizer, `asyncio.to_thread` for non-blocking yfinance.
- **V4** — `astream_events`, `StreamingResponse`, SSE event taxonomy, frontend `EventSource`.
- **V5** — `Report` SQLAlchemy model, `PostgresStore` with pgvector (`store.setup()` runs `CREATE EXTENSION vector`), semantic memory, `memory_loader` / `memory_extractor` nodes, `/api/memories` endpoints.
- **V6** — Guardrail Reflexion loop, `interrupt()` + `Command(resume=...)` + `PostgresSaver` checkpointer, split memory persistence (`memory_extractor` proposes → `human_review` interrupts → `memory_saver` persists), likely refactor of `create_all` into a FastAPI `lifespan` for cleaner checkpointer setup/teardown.
- **V6.5** — Crypto via CoinGecko (`app/tools/crypto_data.py`); the open `Dict[str, float]` `assets` shape needs no schema change.
- **V8 stretch** — `User.telegram_chat_id` column add (ALTER), Telegram digest, PWA, BOI prime rate, separate `daily_digest` graph reusing portfolio dicts via the V2 boundary.

**Hardening still deferred (no version target yet, raised by V2's design):**
- CORS middleware, global exception handlers, FastAPI `lifespan` context manager, tests, frontend.
- **Upsert race window** on `POST /api/portfolio` — production fix is ON CONFLICT or row-level lock.
- **Async DB session** — the sync session held open during `await graph.ainvoke()` is fine for single-user demo. V8 multi-user digest may want to release the session before invoke (extract assets dict, close, then invoke) or move to async SQLAlchemy.
- **Mutable JSONB tracking** — V2 always replaces the full assets dict (POST = full-replace). If any future version wants partial updates, will need `MutableDict.as_mutable(JSONB)` on the column.
- **Alembic migrations** — only needed when schema changes become non-additive.
- **Logging configuration** — `logger.warning` from app code reaches uvicorn's default stdout handler in practice; add `logging.basicConfig` in `main.py` or `create_app()` if stricter control is wanted later.

---

## Patterns established — load-bearing for V3-V6

Continuing from V1 (singleton-with-DI, node contract, LCEL with structured output, thin tool wrappers, Pydantic for boundaries + TypedDict for State). V2 adds:

7. **API as I/O boundary, graph as pure pipeline.** DB lookups happen in `app/api/`, never inside `app/graph/nodes/`. The graph's input contract is `{user_id, portfolio: dict}` and it does not know Postgres exists. This makes the same compiled graph reusable by the V8 daily-digest scheduler against a different data driver — same nodes, same compiled `Pregel`, different caller assembling the dict.

8. **Yield-generator DI for request-scoped resources.** `get_db()` is a generator function — FastAPI advances it past `yield` to inject the session, then drives it to completion through the `finally:` clause to guarantee `db.close()`. Distinct shape from V1's `@lru_cache` singleton DI (Settings, graph). Use the singleton shape for stateless, process-wide objects; use the yield shape for per-request lifecycles. V6's `PostgresSaver` is currently expected to be a singleton (it's thread-safe) but if any V5+ resource turns out to be request-scoped, this is the pattern.

9. **Side-effect imports for SQLAlchemy registration.** `import app.db.models  # noqa: F401` in `main.py` makes the User and Portfolio classes known to `Base.metadata` before `create_all()` runs. Add V5's `Report` to that import (or rotate to a `db/__init__.py`-based registry if the model count grows).

10. **Sync `def` for blocking I/O, `async def` only when awaitables exist.** Portfolio CRUD handlers are sync — FastAPI's threadpool handles them. Generate-report stays async because of `graph.ainvoke`. Mixed sync DB inside async handler is fine at MVP scale; flagged for V8 if it becomes pool pressure.

11. **Server-side timestamps via `func.now()` with `TIMESTAMPTZ`.** No Python-side `datetime.utcnow` defaults — Postgres is the single clock. Pattern applies to every future `created_at`/`updated_at` column, including V5's `Report.generated_at`.

12. **Prompt formatters as private helpers in the LLM-calling node.** Markdown table renderers live next to the chain they feed. Extract to a shared module (`app/graph/prompt_formatters.py`) only when a second node reuses them — V3's `sentiment_agent` or `risk_agent` are the candidates.

13. **Per-asset error tolerance via silent omission + downstream prompt-side flag.** `data_ingestion` skips on `StockDataError`; `synthesizer` computes the missing set and includes it in the prompt with a "do not invent prices" instruction. State stays clean; the architectural cost of richer error tracking is deferred until it earns its keep.

---

## Environment notes for the next Claude

- `DATABASE_URL` in `backend/.env`: `postgresql+psycopg://portfoliopilot:portfoliopilot@localhost:5432/portfoliopilot`. Credentials match the Compose file; both literally `portfoliopilot`.
- Postgres runs via `docker compose up -d` from repo root. Container name: `portfoliopilot-postgres`. Volume name: `portfoliopilot_pg` — data persists across `docker compose down`, wiped only on `docker compose down -v`.
- The pgvector extension is **available** (`pg_available_extensions` shows it) but **not yet installed** (`pg_extension` will not list it). V5's `store.setup()` will run `CREATE EXTENSION vector` when needed.
- Tables created at app startup via `Base.metadata.create_all` — idempotent CREATE IF NOT EXISTS. Verify with `docker compose exec postgres psql -U portfoliopilot -d portfoliopilot -c "\dt"`. Expected: `users`, `portfolios`.
- Demo user: `idan_demo`. Currently holds `{AAPL: 10, MSFT: 5, NVDA: 3, GOOGL: 2, TSLA: 4}`, balanced — staged for V3's 5-symbol parallel `Send()` demo.
- Connection pool config: `pool_pre_ping=True` (catches dropped idle connections), `expire_on_commit=False` (objects usable after commit).
- `uvicorn` exposes `logger.warning` calls from app code in its default stdout handler. No explicit `logging.basicConfig` needed for now; add to `main.py` if more control is wanted later.
- Idan does NOT use Alembic. Schema changes during dev: `docker compose down -v` + restart. Schema is forward-additive through V6, so this is acceptable.
- `psycopg[binary]` (psycopg v3) — NOT `psycopg2-binary`. URL scheme is `postgresql+psycopg://`, not `postgresql+psycopg2://`.
- All Pydantic models are v2-style: `ConfigDict(...)` (not `class Config:`), `@field_validator` (not `@validator`), `model_validate` (not `parse_obj`).
- Idan still runs Git Bash on Windows. HTTPS remote on `IdanRodri17/PortfolioPilot`. Conventional commits with multi-line bodies via `-m … -m … -m …`. Each V2 step landed as its own commit; the version concluded with `git tag -a v2`.

---

## V2 git history

Each step landed as its own conventional commit on `main`, then tagged:

```
chore(v2): add postgres via docker-compose
feat(v2): add db base, session, and User/Portfolio models
feat(v2): create tables on app startup
feat(v2): add portfolio CRUD endpoints
feat(v2): generate-report reads portfolio from DB
feat(v2): cleaner multi-asset prompt and per-asset error tolerance
(tag) v2
```

To reconstruct the V2 baseline at any point: `git checkout v2`. To reconstruct V1: `git checkout v1`.
