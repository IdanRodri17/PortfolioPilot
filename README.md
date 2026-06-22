# PortfolioPilot

**A personal AI wealth manager built on a multi-agent LangGraph system.**

PortfolioPilot analyzes a user's stock holdings, reads real-time market news, checks the portfolio against the user's risk profile, and produces a personalized, structured investment briefing — streamed live to a dashboard as a team of AI agents works in parallel. Over time it builds a private semantic memory of the user's preferences and personalizes its guidance.

![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-multi--agent-1C3C3C)
![Next.js](https://img.shields.io/badge/Next.js-App_Router-000000?logo=nextdotjs&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?logo=postgresql&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o-412991?logo=openai&logoColor=white)
![Status](https://img.shields.io/badge/status-active_development-brightgreen)

> **Disclaimer.** PortfolioPilot is an educational project. It is **not** licensed financial advice, not a brokerage integration, and does not execute trades. Users enter holdings manually, and every report includes a disclaimer. Do not make real investment decisions based on its output.

---

## Table of contents

- [Highlights](#highlights)
- [Architecture](#architecture)
- [Build status](#build-status)
- [Tech stack](#tech-stack)
- [How it works](#how-it-works)
- [Project structure](#project-structure)
- [Getting started](#getting-started)
- [API reference](#api-reference)
- [Engineering decisions](#engineering-decisions)
- [Roadmap](#roadmap)
- [Author](#author)
- [License](#license)

---

## Highlights

- **Parallel multi-agent analysis** ✅ — One sentiment agent per holding plus a risk agent, fanned out concurrently via LangGraph's `Send()` API. A full five-stock report runs in ~6 seconds instead of ~30 sequential.
- **Live streaming dashboard** ✅ — The backend streams agent progress over Server-Sent Events using `astream_events`; the Next.js frontend renders a live pipeline as each agent starts and finishes.
- **Structured, validated LLM output** ✅ — The report is a Pydantic schema enforced at sampling time via `.with_structured_output()`, so parsing never fails and field descriptions double as the model's format instructions.
- **Risk-profile awareness** ✅ — A deterministic (non-LLM) risk agent computes value-weighted composition and flags concentration against per-profile thresholds.
- **Semantic long-term memory** ✅ — A `PostgresStore` with pgvector recalls the user's most relevant past insights by semantic similarity and feeds them into each new report.
- **Self-correcting guardrail loop** ✅ — A Reflexion-style cycle validates each report for hallucinated numbers and risk-profile violations, rewriting on failure (retry budget of 3).
- **Human-in-the-loop memory approval** ✅ — The graph pauses via `interrupt()`, surfaces proposed memories for the user to approve, and resumes from the checkpoint with only the approved insights persisted.
- **Scheduled multi-channel delivery** ✅ — A timezone-aware APScheduler dispatcher delivers the daily briefing to Telegram and email on each user's chosen cadence, with idempotent `last_sent_at` dedupe so a report is never sent twice.
- **Real authentication** ✅ — Auth.js (NextAuth v5) credential auth with a login page, session-derived `user_id`, and middleware route protection. The backend JWT guard that closes the trusted-`user_id` gap is landing in V9.

*Status legend: ✅ shipped · 🚧 in active development · 📋 designed / planned. See [Build status](#build-status).*

---

## Architecture

PortfolioPilot is a stateful LangGraph graph. Nodes are functions that read from and return updates to a shared `PortfolioState`; edges define control flow. Unlike a linear chain, the graph fans out in parallel, loops for self-correction, and pauses for human input.

```mermaid
flowchart TD
    START([START]) --> ML["memory_loader<br/><i>semantic recall</i>"]
    ML --> DI["data_ingestion<br/><i>prices + 24h change</i>"]
    DI -->|Send fan-out| SA["sentiment_agent<br/><i>one per holding · Tavily + LLM</i>"]
    DI -->|Send fan-out| RA["risk_agent<br/><i>deterministic composition</i>"]
    SA --> SY["synthesizer<br/><i>GPT-4o → FinalReport</i>"]
    RA --> SY
    SY --> GR{"guardrail<br/><i>validate</i>"}
    GR -->|fail · retry &lt; 3| SY
    GR -->|pass| ME["memory_extractor<br/><i>propose insights</i>"]
    ME --> HR["human_review<br/><i>interrupt → approve</i>"]
    HR --> MS["memory_saver<br/><i>persist approved</i>"]
    MS --> END([END])
```

The diagram shows the **shipped architecture** — every node above is implemented and runs end to end: parallel `Send()` fan-out, the semantic `memory_loader`, the Reflexion `guardrail` retry loop, and the `memory_extractor → human_review → memory_saver` human-in-the-loop chain backed by the `PostgresSaver` checkpointer. See [Build status](#build-status).

**Two persistence layers (an important distinction):**

- **Store** (`PostgresStore`) — *cross-thread, long-term, semantic.* Holds the user's distilled insights, addressed by namespace `("memories", user_id)`, retrieved by pgvector cosine similarity on an embedded field.
- **Checkpointer** (`PostgresSaver`, V6) — *per-thread, short-term state snapshots.* Persists the graph's state at every super-step keyed by `thread_id`, which is what makes pause-and-resume (HITL) possible.

---

## Build status

The project is built **one version at a time**, each concluded with a Git tag, a conventional-commit history, and a smoke test that proves the increment end to end.

| Version | Focus | Key deliverable | Status |
|--------|-------|-----------------|--------|
| **V1** | Skeleton + linear graph | FastAPI app, `data_ingestion → synthesizer`, yfinance, `FinalReport` schema | ✅ Shipped |
| **V2** | Database + portfolio CRUD | Postgres (Docker), SQLAlchemy `User`/`Portfolio`, JSONB assets, multi-asset ingestion | ✅ Shipped |
| **V3** | Parallel agents | `Send()` fan-out, `Annotated[List, add]` reducer, per-symbol `sentiment_agent`, deterministic `risk_agent`, Tavily | ✅ Shipped |
| **V4** | SSE streaming + frontend | `astream_events`, `StreamingResponse`, SSE taxonomy, two-page Next.js dashboard + editor | ✅ Shipped |
| **V5** | Semantic long-term memory | `PostgresStore` + pgvector, `memory_loader`, `memory_extractor`, report history + memory endpoints, `/history` + `/memory` pages | ✅ Shipped |
| **V6** | Guardrail + HITL | Reflexion guardrail cycle, `interrupt()` / `Command(resume=...)`, `PostgresSaver` checkpointer | ✅ Shipped |
| **V6.5** | Crypto (deferred) | CoinGecko crypto holdings + the dormant `max_crypto_pct` threshold — deferred, not yet shipped | 📋 Planned |
| **V7** | Multi-channel delivery | Scheduled Telegram + email digests, APScheduler dispatcher, timezone-aware `DeliveryPreference`, idempotent `last_sent_at` dedupe | ✅ Shipped |
| **V8** | Authentication | Auth.js (NextAuth v5) credential auth, login page, session-derived `user_id`, middleware route protection | ✅ Shipped |
| **V9** | Backend JWT verification | FastAPI dependency that verifies the Auth.js session token and derives `user_id` server-side — closes the trusted-query-param gap | 🚧 In progress |

---

## Tech stack

| Layer | Choice | Why |
|------|--------|-----|
| AI orchestration | **LangGraph** | Parallel `Send()` fan-out, state reducers, cycles, and native `PostgresStore` memory — a coherent execution model for the whole system |
| LLM | **OpenAI** — GPT-4o-mini (parallel agents), GPT-4o (synthesizer) | Cheap model fans out to N symbols; heavier model handles the grounded synthesis |
| Embeddings | **OpenAI `text-embedding-3-small`** (1536-dim) | Powers pgvector semantic search over stored memories |
| Backend | **FastAPI** (async) | Native `StreamingResponse` + async generators integrate seamlessly with `astream_events` |
| Database | **PostgreSQL + pgvector** via **SQLAlchemy** | JSONB for flexible asset maps; pgvector for semantic memory in the same database |
| Stocks | **yfinance** | Free, no API key, sufficient for prices and 24h changes |
| News | **Tavily** | Returns recent, LLM-friendly news snippets for grounded sentiment |
| Frontend | **Next.js (App Router) + TypeScript + Tailwind** | Streaming components, typed boundary mirrors, fast iteration |
| Charts | **Recharts** | Portfolio composition visualization |
| Infra | **Docker Compose** | Single-command Postgres with pgvector pre-installed |

---

## How it works

**Parallel fan-out.** After market data is fetched, a conditional edge returns a *list* of `Send` objects — one `sentiment_agent` invocation per holding plus one `risk_agent`. LangGraph runs them concurrently. The number of branches isn't known at graph-definition time; it's the size of the portfolio, decided at runtime. The parallel results merge safely because `sentiment_findings` is declared `Annotated[List[dict], add]` — without that reducer, concurrent writes would clobber each other.

**Live streaming.** The report endpoint consumes `graph.astream_events(version="v2")` and maps its event firehose down to a small SSE taxonomy (`status`, `report_complete`, `error`). Each parallel branch's start and end events are correlated by their shared `run_id`, so every status update names the asset it belongs to. The frontend's `EventSource` hook renders this as a live pipeline — the moment of parallel fan-out is visible on screen.

**Structured output.** The synthesizer uses `prompt | llm.with_structured_output(FinalReport)`. The Pydantic model's JSON schema — including every field's description — is injected as the LLM's format specification, constraining the output at sampling time. The field descriptions are effectively prompt engineering, not documentation.

**Semantic memory.** `memory_loader` builds a natural-language query from the current portfolio and risk profile, and `store.search()` embeds it and returns the most relevant past insights by cosine similarity — surfacing *relevant* memories for the situation rather than dumping the full history into the prompt. Memory writes go through a propose-then-persist flow with human-in-the-loop approval.

---

## Project structure

```
PortfolioPilot/
├── docker-compose.yml              # Postgres + pgvector
├── backend/
│   ├── requirements.txt
│   ├── .env.example
│   └── app/
│       ├── main.py                 # FastAPI app, CORS, lifespan (db + store provisioning)
│       ├── api/
│       │   ├── generate.py         # GET /api/generate-report  (SSE)
│       │   └── portfolio.py        # portfolio CRUD
│       ├── core/
│       │   └── config.py           # pydantic-settings, env loading
│       ├── db/
│       │   ├── base.py             # engine, SessionLocal, Base, get_db
│       │   └── models.py           # User, Portfolio  (Report in V5)
│       ├── graph/
│       │   ├── builder.py          # graph compile, Send fan-out, conditional edges
│       │   ├── state.py            # PortfolioState (TypedDict + reducers)
│       │   ├── risk_profiles.py    # RISK_PROFILES thresholds
│       │   ├── persistence/
│       │   │   └── store.py        # PostgresStore singleton  (V5)
│       │   └── nodes/
│       │       ├── memory_loader.py    # semantic recall      (V5)
│       │       ├── data_ingestion.py   # yfinance fetch
│       │       ├── sentiment_agent.py  # Tavily + LLM, per symbol
│       │       ├── risk_agent.py       # deterministic composition
│       │       └── synthesizer.py      # GPT-4o → FinalReport
│       ├── schemas/
│       │   ├── portfolio.py        # PortfolioRequest / Response
│       │   └── report.py           # FinalReport + nested models
│       └── tools/
│           ├── stock_data.py       # yfinance wrapper
│           └── news_search.py      # Tavily wrapper
└── frontend/
    ├── .env.local
    └── src/
        ├── app/
        │   ├── page.tsx            # Dashboard (live pipeline + report)
        │   └── portfolio/page.tsx  # Portfolio editor
        ├── components/
        │   ├── LiveStatusFeed.tsx
        │   ├── FinalReportView.tsx
        │   └── PortfolioOverview.tsx
        └── lib/
            ├── types.ts            # TS mirrors of backend contracts
            ├── api.ts              # typed fetch wrappers
            └── useReportStream.ts  # EventSource hook
```

---

## Getting started

### Prerequisites

- **Python 3.12+**
- **Node.js 18+**
- **Docker** (runs the whole stack, or just Postgres for host dev)
- An **OpenAI API key** and a **Tavily API key** (free tier)

### 1. Clone

```bash
git clone https://github.com/IdanRodri17/PortfolioPilot.git
cd PortfolioPilot
```

### Run with Docker (all services)

The whole stack — Postgres, backend, and frontend — runs with one command. You
need Docker and the two env files (`backend/.env` and `frontend/.env.local` —
variables shown in steps 3 and 4 below).

```bash
docker compose up            # first run builds the images; Ctrl-C to stop
# docker compose up -d       # …or detached
```

- Frontend → http://localhost:3000 · Backend → http://localhost:8000 · Postgres → `:5432`
- Source is bind-mounted, so code edits hot-reload. After changing
  `requirements.txt` or `package.json`, rebuild: `docker compose up -d --build`.
- `docker compose down` stops everything; the `portfoliopilot_pg` volume keeps your data.

Inside the compose network the backend reaches Postgres at the `postgres` host
(`DATABASE_URL` is overridden) and the frontend's server-side auth call reaches
the backend at `http://backend:8000` (`INTERNAL_API_BASE_URL`); the browser
still uses `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`.

> **Hot reload note.** The frontend dev server (Turbopack) can miss file changes
> over a Docker-on-Windows bind mount — if an edit doesn't appear, run
> `docker compose restart frontend`, or use the host dev server (below) for
> frontend-heavy work.

---

To run the services **directly on your host** instead (snappier for frontend
dev), start only the database and run the apps yourself:

### 2. Start Postgres

From the repo root:

```bash
docker compose up -d postgres
```

This brings up PostgreSQL with the pgvector extension pre-installed.

### 3. Backend

```bash
cd backend
cp .env.example .env          # then fill in your keys (see below)

python -m venv .venv
source .venv/Scripts/activate # Git Bash on Windows
# source .venv/bin/activate   # macOS / Linux

pip install -r requirements.txt
uvicorn app.main:app --reload # serves on http://localhost:8000
```

`backend/.env`:

```dotenv
OPENAI_API_KEY=sk-...
OPENAI_MODEL_SYNTHESIZER=gpt-4o
DATABASE_URL=postgresql+psycopg://portfoliopilot:portfoliopilot@localhost:5432/portfoliopilot
TAVILY_API_KEY=tvly-...
```

### 4. Frontend

```bash
cd frontend
npm install
npm run dev                   # serves on http://localhost:3000
```

`frontend/.env.local`:

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

### 5. Try it

Seed a portfolio, then generate a report:

```bash
# Create a demo portfolio
curl -X POST http://localhost:8000/api/portfolio \
  -H "Content-Type: application/json" \
  -d '{"user_id":"idan_demo","assets":{"AAPL":10,"MSFT":5,"NVDA":3,"GOOGL":2,"TSLA":4},"risk_profile":"balanced"}'

# Stream a live report (-N keeps the connection open for SSE)
curl -N "http://localhost:8000/api/generate-report?user_id=idan_demo"
```

Or open the dashboard at **http://localhost:3000** and click **Generate report** to watch the agents work in real time.

---

## API reference

| Method | Route | Purpose | Streaming | Status |
|--------|-------|---------|-----------|--------|
| `GET` | `/api/health` | Liveness check | — | ✅ |
| `POST` | `/api/portfolio` | Create or replace a user's portfolio + risk profile | — | ✅ |
| `GET` | `/api/portfolio/{user_id}` | Fetch the current portfolio | — | ✅ |
| `GET` | `/api/generate-report?user_id=...` | Run the graph, stream agent progress + final report | **SSE** | ✅ |
| `GET` | `/api/reports/history/{user_id}` | List past reports | — | ✅ |
| `GET` | `/api/reports/{report_id}` | Fetch one historical report | — | ✅ |
| `GET` | `/api/memories/{user_id}` | View extracted insights (transparency) | — | ✅ |
| `DELETE` | `/api/memories/{user_id}` | Wipe memory (demo reset) | — | ✅ |
| `POST` | `/api/resume-graph?thread_id=...` | Resume an interrupted graph with user decisions | **SSE** | ✅ |
| `POST` | `/api/auth/verify` | Verify an Auth.js session token (V8) | — | ✅ |
| `GET` | `/api/delivery-preferences/{user_id}` | Read a user's delivery schedule + channels | — | ✅ |
| `PUT` | `/api/delivery-preferences/{user_id}` | Set a user's delivery schedule + channels | — | ✅ |
| `POST` | `/api/telegram/connect/{user_id}` | Bind a Telegram chat via `getUpdates` | — | ✅ |
| `POST` | `/api/deliveries/run-now/{user_id}` | Generate + deliver a briefing immediately | — | ✅ |
| `POST` | `/api/run-due-deliveries` | Dispatch every delivery currently due | — | ✅ |

`/api/generate-report` is `GET` because the browser's native `EventSource` only supports GET; the portfolio is resolved server-side from `user_id`.

### SSE event taxonomy

```
event: status
data: {"node": "sentiment_agent", "phase": "start", "metadata": {"symbol": "AAPL"}}

event: report_complete
data: { ...full FinalReport JSON..., "report_id": "..." }

event: report_diff
data: {"first_report": false, "valuation_delta_pct": 1.8, "sentiment_flips": [...], "recommendations_new": [...], "recommendations_resolved": [...]}

event: error
data: {"code": "GRAPH_ERROR", "message": "..."}
```

---

## Engineering decisions

A few deliberate choices that shape the codebase:

- **Graph purity — I/O at the boundary.** The graph's input contract is `{user_id, portfolio}` and it does not know Postgres exists; portfolio lookups happen in the FastAPI handler. This keeps the graph trivially testable (just a dict) and reusable by the planned daily-digest scheduler. The one exception, `memory_loader`, does I/O to the graph's *own* semantic memory via an **injected** store — not the application's request-scoped DB session — so the principle holds.
- **Reducers signal intent.** `sentiment_findings` carries an `add` reducer because multiple parallel branches write it; `risk_analysis` has none because exactly one node does. Reducer presence/absence is a readable signal of multi- vs single-writer fields.
- **TypedDict for state, Pydantic for boundaries.** State mutates on every node return and reducer merge, so it's a zero-cost `TypedDict`. Pydantic is reserved for the edges: API contracts and LLM structured output.
- **Pure-compute where the LLM is the wrong tool.** The risk agent is deterministic Python — percentages are arithmetic, LLMs are unreliable at math, and deterministic numbers are something the guardrail can later verify.
- **Thin tool wrappers.** yfinance and Tavily are each touched in exactly one module, normalized to a single custom exception type, so a provider swap stays contained and nodes never import an SDK directly.
- **Graceful degradation inside parallel branches.** A failed news fetch returns a degraded "data unavailable" insight rather than propagating and failing the whole report.
- **Lifespan-managed persistence.** Database tables and the `PostgresStore` are provisioned in a FastAPI `lifespan` context manager — one place for startup setup and clean shutdown, ready to host the V6 checkpointer alongside.

---

## Roadmap

The next wave makes the AI **visibly smarter** and the app **publishable** — full spec in `PortfolioPilot_Upgrades_BuildSpec.md`.

- **V9** 🚧 — Backend JWT verification: a FastAPI dependency that verifies the Auth.js session token and derives `user_id` server-side, closing the trusted-query-param gap (the default-closed baseline the demo/share routes later opt out of).
- **V10** 📋 — Value-weighted allocation donut (Recharts) on the dashboard, plus inline ticker validation (company name + live price) in the portfolio editor.
- **V11** 📋 — A `macro_context_agent` that analyzes the portfolio as a whole for sector concentration and surfaces a diversification score.
- **V12** 📋 — Portfolio value trend chart over time, and a "since your last report" diff strip (valuation delta, sentiment flips, resolved/new risk violations).
- **V13** 📋 — The AI grades its own past advice: each prior recommendation scored against how that asset actually moved since.
- **V14** 📋 — Chat with your report: grounded, token-streamed follow-up Q&A over a single archived report.
- **V15** 📋 — Zero-signup guest/demo mode and public shareable report links with PDF export.
- **V16** 📋 — Stretch shelf: threshold alerts on the delivery scheduler, crypto (CoinGecko) + Israeli-market context, and a streamed report narrative.

---

## Author

Built by **Idan** ([@IdanRodri17](https://github.com/IdanRodri17)) as the capstone project for the **CyberPro AI Developer Bootcamp** at ELAD Software.

It is part of a two-project LangChain/LangGraph portfolio: **JobFit** covers controlled retrieval and action selection; **PortfolioPilot** covers agentic parallel orchestration with long-term memory.

---

## License

Released under the MIT License — see [`LICENSE`](LICENSE).
