# PortfolioPilot V19 — Implementation Brief

> Appendix to `PortfolioPilot_SRS_dev.md`. Streamed report narrative: the
> summary "types" out word-by-word instead of appearing all at once.

**Status:** Shipped (verified live end-to-end; hardened by an adversarial review
pass). The `v19` tag is **pending the live browser check** (generate a report and
watch the summary type in). Code on `main`.

**Headline:** the report's prose summary now streams in word-by-word — the same
"alive" feel as the V14 chat — instead of popping in as a finished block. The
deterministic numbers, donut, recommendations and confidence still appear
instantly; only the closing narrative animates.

---

## The key design decision: replay, not a second LLM call

The map surfaced two candidate designs. The deciding constraint is the
**guardrail** (V6/V13), which validates the narrative for banned phrases and
hallucinated tickers (`guardrail.py`):

- ❌ **Second streamed LLM call** for the narrative (outside the graph): bypasses
  the guardrail entirely, doubles cost/latency, and risks the prose diverging
  from the structured recommendations.
- ❌ **Stream inside the synthesizer node**: the guardrail can regenerate the
  report up to 2×, so the narrative would stream 2–3 times (duplicate tokens),
  and `with_structured_output` can't stream prose anyway (it emits one JSON blob).
- ✅ **Replay the guardrail-validated narrative at the API boundary** (chosen):
  the graph runs and the guardrail validates the report exactly as before; then
  the SSE layer re-emits the *final* `summary_narrative` word-by-word. One source
  of truth, guardrail intact, zero extra LLM cost, no divergence.

This works cleanly because `report_complete` is already **non-terminal** —
`report_diff`, `advice_review`, and `human_input_required` already follow it on
the same stream, so appending narrative events fits the existing pattern.

---

## What was built

```
backend/app/api/generate.py
  - _stream_narrative(narrative): replay the text as paced `narrative_token`
    SSE events, ending with `narrative_done`.
  - emitted in _report_event_stream after advice_review, before the human_review
    interrupt detection.

frontend/src/
  ├── lib/types.ts            # NarrativeTokenData
  ├── lib/useReportStream.ts  # streamedNarrative + narrativeStreaming; listeners;
  │                           #   reset/clear on (re)start, done, error, pause, close
  ├── components/FinalReportView.tsx  # render streamed text + typing cursor while
  │                           #   typing, else report.summary_narrative
  └── app/page.tsx, app/demo/page.tsx # pass the streaming props through
```

**Chunking is lossless.** `re.findall(r"\s*\S+\s*", narrative)` groups each word
with its surrounding whitespace, so concatenation reconstructs the original byte
-for-byte (leading whitespace + `\n\n` paragraph breaks included) — the client's
fallback to the full `summary_narrative` is therefore identical to what streamed.
Pacing adapts to length (~3s total).

**Fallback everywhere.** While `narrativeStreaming` is true the report view shows
the streamed text (with a cursor); once it's false (done / error / dropped stream
/ history / share page) it renders the authoritative `report.summary_narrative`.
So `/history`, `/r/{id}`, and the PDF export are unaffected.

---

## Hardening (adversarial review)

A multi-agent review found and **fixed** before commit:

| Severity | Finding | Fix |
|---|---|---|
| **Critical** | whitespace-only narrative → `ZeroDivisionError` (empty chunk list) | guard `not narrative.strip()` → emit `narrative_done` only |
| **High** | `\S+\s*` dropped leading whitespace (broke the lossless contract) | switched to `\s*\S+\s*` |
| **High** | demo page (`/demo`) never passed the streaming props | wired them through |
| **Medium** | typing cursor/placeholder could print into a PDF | added `no-print` |
| **Medium** | stale `narrative_token` from a superseded stream (re-Generate mid-typing) | guard `esRef.current === es` |

(One low finding — a sub-frame "Writing summary" flash — was kept as intended UX.)

---

## Smoke test

- **Verified (live):** a real generate run emits **201 `narrative_token` events**
  that reconstruct the narrative **byte-for-byte** (1427/1427 chars), in order
  `report_complete → report_diff → advice_review → narrative…→ narrative_done →
  human_input_required`; empty / whitespace-only / leading-whitespace inputs all
  handled without crashing; tsc + eslint clean.
- **Pending (browser):** click **Generate report** (dashboard *and* `/demo`) →
  the numbers/donut/recommendations appear immediately and the **Summary** types
  out word-by-word with a blinking caret; opening a report from `/history` or a
  shared `/r/{id}` link shows the full summary instantly (no animation); a printed
  PDF has no caret.

---

## Deviations / decisions

| Area | Choice | Why |
|---|---|---|
| Streaming mechanism | replay validated text | preserves the guardrail; no extra LLM cost/divergence |
| Event placement | after `advice_review` | `report_complete` is non-terminal; deterministic cards land first |
| Schema | unchanged | `summary_narrative` stays one field; report_complete is the fallback |
| `v19` tag | deferred | pending the live browser check |

---

## Patterns established

88. **Replay-stream validated text instead of a second model call.** When a
    feature wants token-by-token UX over content that a pipeline already produced
    and validated, re-emit the finished text as paced SSE tokens at the API
    boundary. Keeps every upstream guarantee (here: the guardrail), costs nothing
    extra, and the final payload stays the single source of truth + fallback.

*(Patterns #1–#87 from V1–V18 remain in force.)*

---

## V19 git history

```
feat(v19): stream the report narrative — the summary types out word-by-word
docs(v19): add V19 implementation brief
(tag) v19  — pending live browser check
```

To reconstruct the V19 baseline at any point once tagged: `git checkout v19`.
