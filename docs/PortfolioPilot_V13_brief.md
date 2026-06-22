# PortfolioPilot V13 — Implementation Brief

> Appendix to `PortfolioPilot_SRS_dev.md` and `PortfolioPilot_Upgrades_BuildSpec.md`.
> Captures V13: the AI grades its own past advice — the previous report's
> recommendations scored against how those assets actually moved since.

**Status:** Shipped. Tagged `v13` on `main`. The live smoke test confirmed the
"How last report's calls aged" card; it also surfaced a same-day grading edge
case (a flat 0.00% move graded "poor"), fixed live with a directional dead-zone
(a sub-0.5% move → neutral, never a miss).

**Headline:** the most distinctive feature on the roadmap — self-grading AI.
When a new report runs, the previous report's `rebalancing_recommendations` are
scored against each asset's actual price move since: *"Last report said reduce
TSLA — down 6% since; the call aged well."* Deterministic, one-step look-back,
no LLM.

**Smoke tests — verified in the build session (offline):**

- **Grade rules:** reduce + price fell → `good`; reduce + rose → `poor`;
  increase + rose → `good`; increase + fell → `poor`; hold + small move →
  `good`; hold + large move → `neutral`. A directional move under ~0.5% (incl.
  same-day grading, where prior and current share a close) → `neutral` — too
  close to call, never a miss.
- **`_compute_advice_review`:** no prior report → "No prior recommendations to
  grade yet."; a prior report with calls grades each one (right `pct_move_since`
  and grade), tallies a clean summary ("3 good"), and marks an asset with no
  retrievable history `insufficient_data` (move `None`) rather than erroring.
- **Frontend:** `npx tsc --noEmit` clean (one pre-existing unused-`loading`
  warning in `page.tsx`, untouched).

**Smoke tests — confirmed live (via the Docker stack):**

- Generate a report (idan_demo has prior reports): a **"How last report's calls
  aged"** card appears under the recommendations — each prior call with its
  action, the asset's % move since, and a win/lose/neutral badge, plus the
  summary tally and the "backward-looking, single-step grade" note. A call on an
  asset with no retrievable history shows the "No data" state.

---

## What was built

### Prompt 13 — historical price helper + grading (backend)

```
backend/app/
├── tools/stock_data.py   # + price_on(symbol, date) (nearest prior trading day)
├── schemas/report.py     # + GradedCall, AdviceReview
└── api/generate.py       # _grade_call + _compute_advice_review; emit advice_review
```

`price_on` uses `yfinance.Ticker(sym).history(start, end)` over a ~6-day
look-back window and returns the last close on/before the target date — the
nearest prior trading day, covering weekends/holidays. Cached per (symbol,
date); never raises (None if unretrievable). `_compute_advice_review` reuses the
V12b prior-report fetch (now also its `generated_at`): for each prior rec it
compares `price_on(asset, prior_date)` with `price_on(asset, today)`, computes
the % move, and grades it. Emitted as an `advice_review` SSE event after
`report_diff`.

### Prompt 14 — the report card (frontend)

```
frontend/src/
├── lib/types.ts                    # mirror GradedCall + AdviceReview; union += advice_review
├── lib/useReportStream.ts          # handle advice_review -> adviceReview state
├── components/AdviceReportCard.tsx # NEW graded-calls card
├── components/FinalReportView.tsx  # optional adviceReview prop; mount under recs
└── app/page.tsx                    # pass the hook's adviceReview through
```

The card colour-codes each call (emerald = aged well, rose = aged poorly, slate
= neutral / no data) and keeps the not-a-guarantee disclaimer visible. Hidden
when there's nothing to grade (first report, or no prior recommendations).

---

## Deviations from the upgrade spec

| Area | Spec | V13 actually does | Why |
|---|---|---|---|
| Current price source | "vs current price" | `price_on(asset, today)` (nearest trading day) for both legs | One never-raising helper for the historical AND current close — uniform, cached, and graceful on weekends/holidays. |
| Hold grading | "hold graded on small absolute move" | `good` if \|move\| < 5%, else `neutral` (never `poor`) | A hold is a non-directional call; a big subsequent move isn't a "wrong" call, so it's neutral, not poor. |
| Scope | one-step look-back | one-step look-back only | A full "if you'd followed every rebalance" equity curve (V13.5) needs careful assumptions; deferred per the spec. |
| `v13` tag | tag on ship | Deferred until the live e2e smoke test passes | "No tag without a passing end-to-end check." |

---

## Explicitly deferred (build in noted version)

- **Push the `v13` tag.** Created locally after the live smoke test passed;
  `git push origin v13` to publish it.
- **Multi-step equity curve (V13.5).** Grade against every prior report, or
  model "if you'd followed every rebalance" — needs assumptions about sizing and
  cash; out of scope for the one-step grade.
- **Timezone precision.** `price_on` keys on the UTC date of the prior report;
  fine for daily grading, but intraday precision would need market-time handling.

---

## Patterns established — load-bearing for later versions

67. **Nearest-prior-trading-day price lookup.** `price_on` walks back a few
    days and takes the last close on/before the target — the reliable way to
    price "as of date D" given weekends/holidays. Cached, never raises;
    unretrievable → the caller degrades (here, `insufficient_data`).

68. **Chained deterministic post-report SSE events.** stream 1 now emits, in
    order: status… → report_complete → report_diff → advice_review. Each is
    deterministic and LLM-free; adding one = compute after report_complete,
    `_format_sse`, and a matching EventSource listener + union entry on the
    client. The resume leg (stream 2) is untouched.

69. **Honest framing for backward-looking AI claims.** Self-grading keeps a
    visible "single-step, not a guarantee" disclaimer and an explicit
    "insufficient_data" state — credibility over flattery.

*(Patterns #1–#66 from V1–V12 remain in force. V9 will continue the counter
when it ships.)*

---

## Environment notes for the next Claude

- **`advice_review` is stream-1-only**, after `report_diff`;
  `useReportStream` stores it as `adviceReview`. The resume leg doesn't carry it.
- **Grading reuses the V12b prior-report fetch** — the handler now also reads
  `prev.generated_at` and passes it into the generator. No second DB query.
- **`price_on` adds yfinance `.history` calls per recommended asset** (cached).
  Combined with V11's `get_sector`, a first report makes several extra yfinance
  calls; all are cached for the session.

---

## V13 git history

```
feat(v13): grade prior recommendations against actual price moves
feat(v13): render the advice report card
docs(v13): add V13 implementation brief
fix(v13): grade a too-small (or same-day) move as neutral, not poor
(tag) v13
```

To reconstruct the V13 baseline at any point: `git checkout v13`.
