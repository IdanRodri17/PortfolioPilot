# PortfolioPilot V3 — Implementation Brief

> Appendix to `PortfolioPilot_SRS_dev.md`, `PortfolioPilot_V1_brief.md`, and `PortfolioPilot_V2_brief.md`. Captures what was built on Day 3 (V3), what deviated from the SRS, and what was explicitly deferred — so any subsequent Claude conversation picks up with full context.

**Status:** Shipped Day 3. Tagged `v3` on `main`. Pushed to `github.com/IdanRodri17/PortfolioPilot`.

**Smoke test passed:**
- `GET /api/generate-report?user_id=idan_demo` runs the full V3 graph end-to-end against the 5-asset demo portfolio.
- 5 `sentiment_agent` invocations + 1 `risk_agent` invocation dispatched concurrently via `Send()` fan-out after `data_ingestion`.
- The `Annotated[List[dict], add]` reducer on `sentiment_findings` correctly accumulates all 5 parallel returns into a single merged list — no clobbering.
- Synthesizer fires only after every parallel branch completes (implicit barrier sync via shared next-node), consumes the merged sentiment findings verbatim as `market_insights`, generates rebalancing recommendations grounded in concrete risk violations, and writes a narrative integrating both.
- Tavily news search returns recent finance headlines per symbol; resulting sentiment summaries are grounded in actual news content rather than LLM priors.
- `risk_agent` deterministic computation verified independently: balanced portfolio with AAPL=47.11%, MSFT=43.9%, NVDA=8.99% correctly produces 3 violations (two single-asset cap exceedances + diversification below recommended minimum of 4).
- Graceful degradation paths exercised: `_SentimentClassification` failure on a thinly-covered ticker produces a Neutral degraded insight rather than crashing the branch; per-asset yfinance failure (V2 carryover) still skips with a warning and is flagged by `_format_missing_assets_block` in the synthesizer prompt.

Demo portfolio at end of V3: `idan_demo` with `{AAPL: 10, MSFT: 5, NVDA: 3, GOOGL: 2, TSLA: 4}`, balanced — five symbols means five parallel `Send()` invocations, the visual aha-moment for V4's SSE streaming demo.

---

## What was built

```
backend/
├── .env / .env.example                    # + TAVILY_API_KEY, bumped OPENAI_MODEL_SYNTHESIZER=gpt-4o
├── requirements.txt                       # + tavily-python
└── app/
    ├── api/generate.py                    # + risk_profile threaded into initial_state
    ├── core/config.py                     # + tavily_api_key required field
    ├── graph/
    │   ├── builder.py                     # rewrite: Send fan-out + new nodes + barrier merge
    │   ├── state.py                       # + sentiment_findings (reducer), risk_analysis, risk_profile, symbol
    │   ├── risk_profiles.py               # NEW — RISK_PROFILES thresholds dict
    │   └── nodes/
    │       ├── sentiment_agent.py         # NEW — per-symbol Tavily + LLM classification
    │       ├── risk_agent.py              # NEW — pure-compute composition + violations
    │       └── synthesizer.py             # rewrite: consumes sentiment_findings + risk_analysis, gpt-4o
    └── tools/
        └── news_search.py                 # NEW — TavilyClient wrapper + NewsSearchError
```

**Graph topology** (rewritten this version):

```
START → data_ingestion → [fan_out_to_agents conditional edge]
   ├─→ sentiment_agent (× N) ─┐
   └─→ risk_agent ────────────┴─→ synthesizer → END
```

The conditional edge from `data_ingestion` returns a list of `Send` objects — `N` sentiment_agent branches (one per portfolio symbol) plus one risk_agent — all dispatched concurrently. Both target nodes have a static edge to `synthesizer`, which acts as the implicit barrier: it fires only after every parallel branch has completed and the reducer has merged `sentiment_findings`.

**Endpoints live:** unchanged from V2.
- `GET /api/health`
- `POST /api/portfolio`
- `GET /api/portfolio/{user_id}`
- `GET /api/generate-report?user_id=…` — internally now fan-out + reduce; externally still a single JSON return.

**V3 `requirements.txt` adds:** `tavily-python`.

**V3 model bump:** `OPENAI_MODEL_SYNTHESIZER` default goes from `gpt-4o-mini` (V1-V2) to `gpt-4o` because the synthesizer prompt grew substantially with sentiment_findings + risk_analysis context. Parallel agents (`sentiment_agent`) stay on `gpt-4o-mini` per SRS §2 — cheap enough to fan out to N symbols without burning credits.

---

## Deviations from the SRS

| Area | SRS as written | V3 actually does | Why |
|---|---|---|---|
| `RISK_PROFILES` location | `app/config/risk_profiles.py` (§9 file structure) | `app/graph/risk_profiles.py` (in graph/, no config/ folder) | The risk_profiles dict is consumed exclusively by `risk_agent` (a graph node). Co-locating with the sole consumer is simpler than creating a fresh `app/config/` directory for one file. **Per Idan's note: a `config/` folder may be reintroduced later as the project grows and more cross-cutting config emerges.** |
| `risk_agent` design | Pictured as "GPT-4o-mini" in §4.2 topology diagram | Pure compute — no LLM call | Percentages are arithmetic; LLMs are unreliable at math and the cost of an extra LLM round-trip per report buys nothing the synthesizer can't do from structured numbers. Pure compute is cheaper, faster, deterministic, and the V6 guardrail can spot-check the numbers without spinning a separate validator. |
| Synthesizer model | `GPT-4o` from SRS §2 | gpt-4o (now default), V1-V2 used gpt-4o-mini | SRS-aligned in V3; the V1-V2 deferral to gpt-4o-mini was a thin-prompt optimization. V3's prompt (sentiment + risk + portfolio + market_data) is heavy enough that gpt-4o-mini occasionally drops grounding. |
| `MarketInsight.asset` source | SRS §5.3 declares the field; doesn't say who fills it | Set **programmatically** in `sentiment_agent`, not LLM-derived | Asking the LLM to repeat the ticker risks "Apple Inc." or "Apple" instead of "AAPL". Pulling `asset=symbol` from State guarantees consistency. The LLM is constrained to `_SentimentClassification` (sentiment + summary only); the full `MarketInsight` is constructed in Python. |
| Tavily integration | "TavilySearchResults — LangChain-native tool" (§2) | Direct `TavilyClient` from `tavily-python`, no LangChain wrapper | `TavilySearchResults` exists to make Tavily callable from an LLM's tool-use loop. `sentiment_agent` calls Tavily from Python code, not via tool-use. Direct client is one less abstraction layer and avoids pulling `langchain-community` into the dep tree. |
| Tavily failure handling | Not specified | Try/except `NewsSearchError`, return degraded `MarketInsight` (Neutral with "news could not be retrieved" summary) | One branch's news failure shouldn't kill the whole graph. Without the catch, an unhandled `NewsSearchError` inside a Send branch propagates up to `graph.ainvoke()` and 500s the whole report. The Neutral degraded insight is honest about the missing data and lets the synthesizer adjust confidence accordingly. |
| `_SentimentClassification` internal schema | Not in SRS | Private Pydantic model inside `sentiment_agent.py` with just `sentiment` + `summary` fields | Smaller structured-output schema = more reliable LLM behavior. The full `MarketInsight` is assembled programmatically after the LLM call, so the LLM only sees the fields it actually synthesizes. |
| `RISK_PROFILES` schema | Not specified beyond "thresholds" (§4.3) | Each profile carries `description`, `max_single_asset_pct`, `max_crypto_pct`, `min_assets_recommended` | `description` gives the synthesizer prompt natural-language profile context for the narrative. `max_crypto_pct` is forward-defined for V6.5 (defined but not evaluated in V3 — no crypto symbol detector yet). `min_assets_recommended` is the diversification floor. |
| `Send` payload shape | `Send("sentiment_agent", {"symbol": symbol, **state})` (§4.4) | `Send("sentiment_agent", {**state, "symbol": symbol})` | Semantically equivalent (later keys overwrite earlier ones). The `**state, "symbol": symbol` ordering puts the per-branch override last, which reads as "everything from state, then add symbol" — minor stylistic preference. |
| `symbol` field on State | Not explicit in SRS state schema (§4.1) | Added to `PortfolioState` as `symbol: str` | Per-Send-branch input — populated only inside `Send` invocations, never in the handler's main `initial_state`. Declaring it explicitly gives the `sentiment_agent` signature a typed read of `state["symbol"]` rather than relying on TypedDict's tolerance for unknown keys. |
| `risk_analysis` typing | "dict" in §4.1 | `Dict[str, Any]` in TypedDict | SRS-aligned but consciously loose. Tightening to a Pydantic `RiskAnalysis` model adds rigor but also serialization friction for V4's astream_events and V6's checkpointer. Reconsider in V6 if the guardrail wants to validate the structure. |
| `sentiment_findings` payload shape | "MarketInsight dict appended via the add reducer" (§4.3) | List of dicts produced by `MarketInsight(...).model_dump()` per branch | Storing model instances directly would block JSON serialization needed for V4 streaming and V6 checkpointing. Dump-to-dict at the producer means downstream consumers (synthesizer prompt formatter, V6 guardrail rule checks) work on plain dicts. |
| `core/llm_provider.py` abstraction | "Multi-Source RAG Knowledge Hub pattern" (§2 LLM row) | NOT built — `sentiment_agent` and `synthesizer` each instantiate `ChatOpenAI` directly | V2 brief flagged this as likely-V3 work, but with only two LLM call sites in the graph the abstraction earns its keep less obviously than expected. Reconsider in V5 (when `memory_extractor` adds a third LLM caller) or V6 (when guardrail's LLM-as-judge adds a fourth). |
| `asyncio.to_thread` for yfinance | Mentioned as V3 work in V2 brief | NOT built — yfinance still called synchronously inside `data_ingestion` | Per-asset error tolerance (V2 step 6) already gives the visible robustness gain. True async would speed up the multi-asset pre-fan-out fetch, but V4's SSE streaming will surface the parallel sentiment_agents as the more impressive visible-parallelism win. Keep yfinance sync for V3 simplicity. |
| Fan-out coverage | "for symbol in state['portfolio'].keys()" (§4.4) | Identical, but with explicit doc note that we fan out over `portfolio.keys()` (not `market_data.keys()`) | A symbol that failed yfinance still gets a sentiment_agent branch — sentiment is grounded in Tavily news, not in price. The synthesizer still receives that insight; only `portfolio_valuation` excludes the unpriced asset. Worth being explicit since "obviously we'd only sentiment-analyze the priced ones" is an easy wrong intuition. |
| Synthesizer prompt: sentiment passthrough | SRS doesn't specify how synthesizer should treat upstream agent outputs (§4.3) | Prompt explicitly instructs **"include the upstream sentiment findings verbatim — do not rewrite, summarize, or re-classify them"** | Upstream sentiment_agents grounded their classifications in Tavily news. Asking the synthesizer to re-process that work would (a) waste tokens, (b) introduce a paraphrase layer where grounding could erode, (c) potentially flip sentiment on second-guess. Pass-through is the reliable pattern. |
| Confidence guidance | "0 to 1, low values indicate insufficient data" (FinalReport.confidence) | Synthesizer prompt now explicitly steers 0.6-0.85 for V3 (vs 0.4-0.6 for V1-V2) | V3 grounds sentiment in real Tavily news, so the model has actual evidence to base confidence on. The prompt lowers it back toward 0.4-0.5 when (a) market data was missing for some assets, (b) sentiment findings were mostly Neutral with thin rationale, or (c) the report relies on a degraded sentiment_agent (visible as "news could not be retrieved" in the summary). |

---

## Explicitly deferred (do NOT build in V3; build in noted version)

- **V4** — `astream_events`, `StreamingResponse`, SSE event taxonomy (`status`, `token`, `report_complete`, `error`, plus `human_input_required` in V6), frontend `EventSource`. The Send fan-out built in V3 step 5 is what makes V4's streaming dramatic: the status feed will show 5+ `sentiment_agent` starts within milliseconds of each other.
- **V5** — `Report` SQLAlchemy model, `PostgresStore` with pgvector (`store.setup()` runs `CREATE EXTENSION vector`), semantic memory, `memory_loader` / `memory_extractor` nodes, `/api/memories` endpoints, `/api/reports/history` and `/api/reports/{report_id}`.
- **V6** — Guardrail Reflexion loop, `interrupt()` + `Command(resume=...)` + `PostgresSaver` checkpointer, split memory persistence (`memory_extractor` proposes → `human_review` interrupts → `memory_saver` persists), likely refactor of `create_all` into a FastAPI `lifespan` for cleaner checkpointer setup/teardown.
- **V6.5** — Crypto via CoinGecko (`app/tools/crypto_data.py`); `max_crypto_pct` threshold in `RISK_PROFILES` becomes active once a crypto symbol detector lands in `risk_agent`.
- **V8 stretch** — `User.telegram_chat_id` column add (ALTER), Telegram digest, PWA, BOI prime rate, separate `daily_digest` graph reusing the V2 portfolio-dict boundary.

**V3-era deferrals (originally proposed in V2 brief or SRS for V3, slipped to later):**
- **`core/llm_provider.py` abstraction** — slipped to V5/V6 once there are 3-4 LLM call sites to justify the indirection.
- **`asyncio.to_thread` for yfinance** — sync stays for V3. The threadpool runs sync nodes fine, and visible parallelism wins land in V4 (SSE streaming) and V3 step 5 (Send fan-out itself).
- **Tighter typing on `risk_analysis`** — currently `Dict[str, Any]`. A Pydantic `RiskAnalysis` model would close that loophole; deferred to V6 if the guardrail wants to validate structure.

**Architectural choices flagged as reconsider-later:**
- **`app/config/` folder** — skipped in V3 because there was only one file (`risk_profiles.py`) and it had a single consumer. As project config grows (caching policy, scheduler cron expressions in V8, multi-provider LLM routing if `llm_provider.py` lands), introducing `app/config/` becomes worthwhile. Idan flagged this explicitly as a "maybe later" decision.
- **Tighter `sentiment_findings` element type** — currently `List[dict]`. Could be `List[MarketInsight]` to push validation upstream, but JSON-serializability constraints from V4 streaming and V6 checkpointing favor dicts at the State boundary.
- **`fan_out_to_agents` portfolio-keys vs market-data-keys** — current: fan out over portfolio (all symbols, even unpriced). If Tavily quota becomes the constraint, switch to market_data.keys() (skip unpriced symbols' sentiment branches). Quota is comfortable at MVP scale, so portfolio-keys for now.

**Hardening still deferred (no version target yet, carried forward from V2):**
- CORS middleware, global exception handlers, FastAPI `lifespan` context manager, tests, frontend.
- Upsert race window on `POST /api/portfolio`.
- Async DB session held open during `await graph.ainvoke()`.
- Mutable JSONB tracking.
- Alembic migrations.
- Logging configuration (currently relies on uvicorn's default stdout handler).

---

## Patterns established — load-bearing for V4-V6

Continuing the running list from V1 (1-6) and V2 (7-13). V3 adds:

14. **`Send()` for parallel fan-out, conditional edge for if/else routing.** Same `add_conditional_edges()` API surface, but the router's return type discriminates. Returning a single string name = pick-one routing. Returning a list of `Send` objects = spawn-N parallel invocations. The two patterns will coexist in V6 when the guardrail routes (single-string) cohabit with the sentiment fan-out (Send list).

15. **The reducer + `Send` pair is the entire map-reduce abstraction.** Without the reducer, parallel branches clobber each other on shared State fields. Without `Send`, you can't spawn N parallel invocations of one node. Neither is useful alone; together they're the whole pattern. Same shape will reappear in V5 if `memory_loader` ever fans out across multiple memory namespaces.

16. **Implicit barrier sync via shared next-node.** Pointing multiple parallel-target nodes' outgoing edges to the same downstream node tells LangGraph "wait for all of these, then proceed." No explicit `join()`. V6's guardrail loop will exploit this for the same reason: the conditional edge between synthesizer and {memory_extractor, synthesizer-retry} doesn't need a join because each path is single-threaded.

17. **Per-Send-branch State extension as optional TypedDict fields.** Inputs that exist only inside specific Send invocations (like `symbol`) live as `total=False` fields on the main State. The handler's `initial_state` doesn't include them; the Send call does. This avoids splitting State into multiple TypedDicts per branch type while keeping per-branch reads typed.

18. **Pure-compute nodes alongside LLM nodes.** `risk_agent` is deterministic Python — no LLM call. `sentiment_agent` is LLM-driven. They coexist in the same graph because the State envelope and node contract (`def node(state) -> dict`) are agnostic to what's inside the node. Use LLM nodes for narrative/classification/synthesis; use pure-compute nodes for arithmetic/validation/transformations. V6's guardrail rule-check stage will follow this same shape.

19. **Single-writer fields don't need reducers.** `risk_analysis` is written by exactly one node (`risk_agent`), so default last-write-wins is correct. Adding a reducer where it isn't needed is harmless but misleading — it implies parallel writes that don't exist. Reducer presence/absence is a readable signal of multi- vs single-writer.

20. **Programmatic vs LLM-derived fields in structured output.** When a field is known at call time (like `asset=symbol` or `user_id` or `timestamp`), set it programmatically and shrink the LLM's schema to the fields it genuinely synthesizes. Smaller schemas are more reliably populated. The `_SentimentClassification` (sentiment + summary) → `MarketInsight` (asset + sentiment + summary) split is the canonical case.

21. **Pass-through prompting when upstream is grounded.** When an upstream agent has produced grounded output, instruct the downstream consumer to include it verbatim, not re-process. Re-processing risks (a) wasted tokens, (b) paraphrase-erosion of grounding, (c) second-guess flips. The synthesizer's "include the sentiment findings verbatim as market_insights" instruction is the model for V6's guardrail prompt ("evaluate the report, don't rewrite it").

22. **Graceful degradation inside Send branches.** A Send branch that raises propagates the exception out of `graph.ainvoke()` and 500s the whole report. `sentiment_agent` wraps `fetch_news()` in a try/except and returns a degraded `MarketInsight` (Neutral + "data unavailable") instead of raising. V4's status stream will visibly differentiate "completed successfully" from "completed with degradation."

23. **Direct provider client over LangChain Tool wrapper for non-tool-use callers.** When you're calling a service from Python code rather than exposing it as an LLM-callable tool, use the bare provider SDK. LangChain's Tool wrappers exist to make functions callable by an agent's tool-use loop — using them outside that context just adds an indirection layer. Applies equally to V6.5's CoinGecko wrapper.

---

## Environment notes for the next Claude

Carrying forward from V2's environment notes, plus V3 additions:

- `TAVILY_API_KEY` is required in `backend/.env` (Tavily free tier: 1000 searches/month). Each V3 report uses ~1 Tavily credit per portfolio symbol, so a 5-asset report = 5 credits. Comfortable budget for a bootcamp demo.
- `OPENAI_MODEL_SYNTHESIZER` defaults to `gpt-4o` in V3 (was `gpt-4o-mini` in V1-V2). Override via env var if testing with the cheaper model — prompt is robust enough that mini usually works.
- Sentiment_agent uses `gpt-4o-mini` hardcoded (per SRS §2) — cheap parallel agent. If swapping later, change the literal in `sentiment_agent.py`.
- **Always activate the venv before running anything on Windows.** Idan hit this in V3 step 3-5: the system Python 3.14 has its own copies of packages, and running `pip install` outside the venv installs to the wrong location. Symptom: `ModuleNotFoundError: No module named 'tavily'` from inside the venv even though the dep "exists." Fix: `pip install -r requirements.txt` from inside the activated venv.
- All Send-target nodes (sentiment_agent, future V5 memory branches) receive their State via the dict passed to `Send`. Adding a new per-branch input means (a) adding the field to `PortfolioState` as optional, (b) including it in the `Send(...)` call inside `fan_out_to_agents`.
- The `_build_graph` factory signature is still parameterless. V6 will extend it to accept `checkpointer=...` for HITL support — the factory shape was set up that way deliberately in V1 to avoid a later refactor.
- Smoke testing individual Send-target nodes (sentiment_agent, risk_agent) standalone: call the function with a synthetic State dict that includes `symbol` (for sentiment_agent) or `portfolio + market_data + risk_profile` (for risk_agent). No need to invoke through `graph.ainvoke` for unit-style checks.
- The synthesizer's prompt formatters (`_format_portfolio_table`, `_format_market_data_table`, `_format_missing_assets_block`, `_format_sentiment_findings_block`, `_format_risk_analysis_block`) are still private helpers in `synthesizer.py`. If V5's `memory_loader` or V6's guardrail end up rendering the same shapes in their own prompts, extract to a shared `app/graph/prompt_formatters.py`. Not before.
- V3 wall-clock time for a 5-asset report: ~10-20 seconds. Bottleneck mix: sequential yfinance fetches in data_ingestion (~3-5s) + parallel Tavily+LLM in sentiment_agents (~5-8s) + the upgraded synthesizer prompt (~5-8s). V4's `astream_events` will surface this as a visible activity feed; until then it's a single curl that takes ~15s.

---

## V3 git history

Each step landed as its own conventional commit on `main`, plus one V2-recovery commit, then tagged:

```
feat(v3): extend state with reducer + risk fields; thread risk_profile from db
feat(v3): add tavily news search wrapper and risk_profiles config
chore: recover V2 portfolio CRUD files missed from earlier commit
feat(v3): add sentiment_agent node — per-symbol Tavily + LLM classification
feat(v3): add risk_agent node — deterministic composition + threshold checks
feat(v3): fan-out to parallel agents via Send + synthesizer rewrite
(tag) v3
```

The recovery commit landed mid-V3 because the V2 step 4 commit had been a phantom — its files (`api/portfolio.py`, `schemas/portfolio.py`, the `main.py` router mount edit) were never staged due to a `git add` path issue when run from inside `backend/`. Local disk was correct all along; the GitHub repo was missing the files. The recovery commit makes GitHub match reality.

To reconstruct the V3 baseline at any point: `git checkout v3`. To reconstruct V2: `git checkout v2` (or use `git checkout v2-recovery` if a moved tag is preferred — see V2 brief). To reconstruct V1: `git checkout v1`.
