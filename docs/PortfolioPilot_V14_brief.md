# PortfolioPilot V14 — Implementation Brief

> Appendix to `PortfolioPilot_SRS_dev.md` and `PortfolioPilot_Upgrades_BuildSpec.md`.
> Captures V14: chat with your report — grounded, token-streamed follow-up Q&A
> over a single archived report.

**Status:** Shipped (code complete; statically verified). The `v14` tag is
**pending the live end-to-end smoke test** (asking a question and watching the
answer stream token-by-token). The endpoint wiring (404 / 422) was verified
live; code is committed on `main`.

**Headline:** the app's first real **token streaming**. After a report renders,
a chat box answers follow-ups ("why reduce AAPL?", "what's my biggest risk?")
grounded strictly in that report's contents, streamed word-by-word — the
deliberate counter-case to the report endpoint's no-token rule. No graph re-run.

**Smoke tests — verified in the build session:**

- **Endpoint wiring (live, no LLM):** `POST /api/reports/<unknown>/ask` → 404;
  an empty `question` → 422 (min_length validation). Module imports cleanly
  (container hot-reloaded).
- **Frontend:** `npx tsc --noEmit` clean (one pre-existing unused-`loading`
  warning in `page.tsx`, untouched).

**Smoke tests — pending your live run:**

- After a report, ask "why reduce AAPL?" → the answer **streams progressively**
  (not all at once) and cites the report's own AAPL sentiment/recommendation.
- Ask "what's the weather?" → an out-of-scope answer ("that's not in this
  report"), not a hallucination.
- The same chat works on an archived report opened from **/history**.

---

## What was built

### Prompt 15 — grounded streaming Q&A endpoint (backend)

```
backend/app/
├── schemas/report.py     # + AskRequest { question }
└── api/reports.py        # + POST /api/reports/{report_id}/ask (SSE token stream)
```

The endpoint loads `raw_result`, builds a grounded prompt — *"answer ONLY from
this report; if it isn't here, say so; never invent prices/news/recommendations"*
— and streams the low-temperature model's reply via `_ask_llm.astream(...)` as
SSE `token` events, then `done` (or `error`). No graph re-run; it just reuses the
report already persisted. POST (the question rides in the body), so the client
reads it with `fetch()`+reader rather than EventSource.

### Prompt 16 — chat panel (frontend)

```
frontend/src/
├── lib/api.ts                     # + askReport(reportId, question, onToken)
├── lib/useReportStream.ts         # capture report_id from report_complete
├── components/ReportChat.tsx      # NEW Q&A panel, streams tokens into the answer
├── components/FinalReportView.tsx # optional reportId prop; mount the chat
├── app/page.tsx                   # pass the streamed reportId
└── app/history/page.tsx           # pass the archived report_id (chat on past reports)
```

`askReport` POSTs and consumes the SSE stream with a reader, firing `onToken`
per token; `ReportChat` appends those tokens to the latest answer live. The chat
is visually secondary (slate, compact) and keeps the not-financial-advice note.

---

## Deviations from the upgrade spec

| Area | Spec | V14 actually does | Why |
|---|---|---|---|
| Chat scope | "after a report renders" (dashboard) | Dashboard **and** /history archived reports | The endpoint is keyed by report_id, which history already has — one optional `reportId` prop on `FinalReportView` enables both for free. |
| Model | (unspecified) | reuses `openai_model_synthesizer` (gpt-4o), low temp | Simplicity; gpt-4o-mini is a one-line swap if cost matters for chat volume. |
| `v14` tag | tag on ship | Deferred until the live token-stream smoke test passes | "No tag without a passing end-to-end check"; the streaming needs a real LLM call in the browser. |

---

## Explicitly deferred (build in noted version)

- **Live e2e confirmation + `v14` tag.** Ask a question, watch it stream, then
  `git tag v14`.
- **Conversation memory.** Each ask is stateless (one question → one grounded
  answer); multi-turn context within a chat is a later enhancement.
- **Auth on the ask endpoint.** Like the other report reads, it's currently
  unguarded by report_id (uuid4 capability URL); V9 should gate it consistently.

---

## Patterns established — load-bearing for later versions

70. **Token streaming over POST-SSE.** Free-form prose streams via
    `llm.astream()` → SSE `token`/`done`/`error`; consumed with
    `fetch()`+reader (EventSource is GET-only). This finally uses the `token`
    event reserved since V4 — and stands alongside the structured report's
    no-token rule rather than contradicting it.

71. **Grounded single-call endpoint over an archived artifact.** No graph
    re-run: load `raw_result`, prompt the model to answer ONLY from it, stream
    the reply. Cheap, safe, and reuses what's already persisted — the template
    for any "ask about X" feature.

72. **Thread the id for post-report actions.** `report_id` is captured from
    `report_complete` in the hook (and read from `ReportDetail` on history) and
    passed into `FinalReportView` as an optional prop, so one component enables
    the chat in both the live and replay contexts.

*(Patterns #1–#69 from V1–V13 remain in force. V9 will continue the counter when
it ships.)*

---

## Environment notes for the next Claude

- **Three streaming shapes now coexist:** generate (GET EventSource: status →
  report_complete → report_diff → advice_review), resume (POST reader:
  status/memory_saved), and ask (POST reader: token/done). `_format_sse` is
  duplicated in `reports.py` (a tiny local copy) to keep it decoupled from
  `generate.py`.
- **The chat is grounded by prompt, not by retrieval** — the whole report JSON
  is in the prompt; fine at report size, revisit if reports grow large.
- **report_id is a uuid4 capability URL.** Anyone with it can read/ask; tighten
  in V9 alongside the other report endpoints.

---

## V14 git history

```
feat(v14): grounded streaming Q&A endpoint over an archived report
feat(v14): report chat panel with streamed answers
docs(v14): add V14 implementation brief
(tag) v14  — pending live e2e smoke test
```

To reconstruct the V14 baseline at any point once tagged: `git checkout v14`.
