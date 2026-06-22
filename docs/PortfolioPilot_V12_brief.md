# PortfolioPilot V12 — Implementation Brief

> Appendix to `PortfolioPilot_SRS_dev.md` and `PortfolioPilot_Upgrades_BuildSpec.md`.
> Captures V12 (V12a portfolio value trend chart, V12b since-last-report diff) —
> what was built, what deviated from the upgrade spec, and what was deferred.

**Status:** Shipped (code complete; statically verified). The `v12` tag is
**pending the live end-to-end smoke test** (the /history line chart rendering;
two consecutive reports showing the diff strip). The V12a series endpoint was
verified live against `idan_demo`'s 24 archived reports; the V12b diff logic was
verified offline. Code is committed on `main`.

**Headline:** the reports the app already archives now tell a story over time —
a value trend line on /history — and each new report opens with a "since your
last report" strip (valuation delta, sentiment flips, new/resolved
recommendations). Both are deterministic read-side features: no graph re-run, no
LLM cost.

**Smoke tests — verified in the build session:**

- **V12a series endpoint (live, no LLM):** `GET /api/reports/series/idan_demo`
  returned 24 points in ascending `generated_at` order, all with `total_usd`;
  an unknown user returned `[]`.
- **V12a frontend:** `npx tsc --noEmit` + `eslint` clean.
- **V12b diff (offline scratch):** first-report → `first_report:true`; a full
  diff gave the right `valuation_delta_pct` (1.8% on 10000→10180), the one
  sentiment flip, and the recommendation set-diff (`new=["reduce NVDA"]`,
  `resolved=["reduce AAPL"]`); identical reports → 0% and no changes; a zero
  prior total guarded `valuation_delta_pct` to `None` (no ZeroDivision).
- **V12b frontend:** `tsc` clean; `eslint` clean apart from a pre-existing
  unused-`loading` warning in `page.tsx` (a V8 artifact, untouched).

**Smoke tests — pending your live run:**

- `/history` shows a value line matching the archived totals (left-to-right
  oldest→newest); an empty/single-report history shows no chart (the existing
  empty state covers it).
- Generate two reports in a row: the second opens with the **Since last report**
  strip showing the value delta and any sentiment/recommendation changes; a
  brand-new user's first report shows "First report — nothing to compare yet."

---

## What was built

### V12a — Portfolio value trend chart

```
backend/app/api/reports.py        # + GET /api/reports/series/{user_id}
frontend/src/
├── lib/types.ts                  # + ReportSeriesPoint
├── lib/api.ts                    # + getReportSeries(userId)
└── app/history/page.tsx          # Recharts line chart above the report list
```

The series endpoint selects each archived report's `portfolio_valuation`
(`total_usd`, `change_24h_percent`) ordered oldest-first — pure read-side history
at the boundary (pattern #7), reusing the same extraction the history-list
endpoint already does. The history page fetches the series alongside the list in
one `Promise.all`; the chart (emerald line, dark axes/grid, compact-USD ticks,
dark tooltip) renders only with ≥2 points.

### V12b — Since-last-report diff

```
backend/app/
├── schemas/report.py             # + SentimentFlip, ReportDiff
└── api/generate.py               # fetch prior report; _compute_report_diff;
                                  #   emit report_diff after report_complete
frontend/src/
├── lib/types.ts                  # mirror ReportDiff; + report_diff in the union
├── lib/useReportStream.ts        # handle report_diff -> diff state
├── components/SinceLastReport.tsx # NEW strip
├── components/FinalReportView.tsx # optional diff prop; mount the strip
└── app/page.tsx                  # pass the hook's diff through
```

The generate handler fetches the user's most recent prior report with the
request session **before** the run; the generator diffs the two payloads in
Python after `report_complete` and emits a `report_diff` SSE event. The diff
covers the valuation delta, per-asset sentiment flips, and the recommendation
set-diff. `report_diff` rides the generate EventSource (stream 1) only — the
resume leg (stream 2) doesn't emit it, so its parser is untouched.

---

## Deviations from the upgrade spec

| Area | Spec | V12 actually does | Why |
|---|---|---|---|
| Diff: violations | `violations_resolved` / `violations_new` | `recommendations_resolved` / `recommendations_new` (keyed "action asset") | Risk violations live in `risk_analysis` (graph state) and are NOT persisted on the report, so they can't be diffed from `raw_result`. Recommendations are their surfaced, persisted form. |
| Flip field names | `{asset, from, to}` | `{asset, previous, current}` | `from` is a Python keyword; `previous`/`current` avoid alias gymnastics and read clearly on both ends. |
| `v12` tag | tag on ship | Deferred until the live e2e smoke test passes | "No tag without a passing end-to-end check"; the chart render + two-report diff need the browser. |

---

## Explicitly deferred (build in noted version)

- **Live e2e confirmation + `v12` tag.** Check the /history line and the
  two-report diff strip, then `git tag v12`.
- **Persisting risk violations on the report.** If a true violation diff
  ("Resolved: AAPL concentration") is wanted, attach
  `risk_analysis["violations"]` to `FinalReport` (deterministic, like
  composition) in a later pass, then diff that instead of recommendations.
- **Richer trend chart.** Brush/zoom, a 24h-change overlay, or per-asset lines
  are natural follow-ups; V12a keeps it to a single total-value line.

---

## Patterns established — load-bearing for later versions

63. **Read-side time series from the archive.** A series endpoint derives points
    from `reports.raw_result` ordered by `generated_at` — no graph run, no LLM.
    Charts want ascending order (the history list wants descending); same data,
    two orderings.

64. **Boundary-computed diff + a new SSE event.** Fetch the prior report in the
    handler (request session), pass it into the generator, diff in pure Python,
    and emit after `report_complete`. A new SSE event = add it to the
    EventSource (stream 1) listeners AND the discriminated union; the resume
    parser (stream 2) only needs it if that leg emits it (it doesn't).

65. **Diff what's actually persisted.** Before designing a diff, check what's in
    `raw_result`. Violations weren't there, so the diff uses recommendations.
    Don't assume graph-state fields survive into the archived report.

66. **Shared component, optional prop.** `FinalReportView` gained an optional
    `diff`: the dashboard (live stream) shows the strip, history replay (no
    diff) doesn't — one component serving two contexts without a fork.

*(Patterns #1–#62 from V1–V11 remain in force. V9 will continue the counter when
it ships.)*

---

## Environment notes for the next Claude

- **`report_diff` is stream-1-only.** It follows `report_complete` on the
  generate EventSource; `useReportStream` stores it as `diff`. The resume leg
  (`fetch`+reader, stream 2) does not carry it.
- **Series ordering:** `/api/reports/series/{user_id}` is ascending;
  `/api/reports/history/{user_id}` is descending. Both read
  `portfolio_valuation` from `raw_result`.
- **The diff is best-effort-safe:** if the prior report's payload is missing
  fields, the helper guards (None delta, empty lists) rather than raising.

---

## V12 git history

```
feat(v12a): add report value time-series endpoint
feat(v12a): portfolio value trend chart on the history page
feat(v12b): compute and stream the since-last-report diff
feat(v12b): render the since-last-report change strip
docs(v12): add V12 implementation brief
(tag) v12  — pending live e2e smoke test
```

To reconstruct the V12 baseline at any point once tagged: `git checkout v12`.
