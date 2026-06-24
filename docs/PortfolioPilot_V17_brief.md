# PortfolioPilot V17 — Implementation Brief

> Appendix to `PortfolioPilot_SRS_dev.md`. A small follow-on to V16: a
> user-selectable **base currency** for the report (USD ⇄ ₪).

**Status:** Shipped (code complete; FX endpoint verified live). The `v17` tag is
**pending the live browser check** (toggle the report to ₪ and watch the headline
+ donut convert). Code on `main`.

**Headline:** the report can now be displayed entirely in **shekels** (or back to
dollars) with a one-click toggle — so an Israeli investor reads their whole
portfolio in ₪. Report values stay USD-canonical; the toggle converts at the
display layer via a live FX rate, so percentages are untouched and nothing in the
stored data changes.

**Smoke tests:**
- Verified: `GET /api/fx/usd-ils` returns the rate live; `tsc` + `eslint` clean.
- Pending (browser): on a report, click **₪ ILS** → the headline, donut center,
  legend, and tooltip all switch to shekels (e.g. a $10,000 total shows ~₪37,000);
  the percentages are unchanged; the choice persists across reports/pages and to
  the public `/r/{id}` share page.

---

## What was built

```
backend/app/
├── tools/stock_data.py   # usd_ils_rate() public accessor (wraps the cached _ils_per_usd)
└── api/portfolio.py      # GET /api/fx/usd-ils (public) -> {ils_per_usd}

frontend/src/
├── lib/money.ts          # displayMoney(usdAmount, base, ilsPerUsd) + BaseCurrency
├── lib/useBaseCurrency.ts# NEW: localStorage-persisted USD/ILS choice
├── lib/api.ts            # getFxRate()
└── components/
    ├── FinalReportView.tsx  # the $ USD / ₪ ILS toggle; fetches the rate; headline in base
    └── AllocationDonut.tsx  # base + ilsPerUsd props; center/legend/tooltip in base
```

**Display-layer conversion.** The backend already aggregates everything to USD
(V16). `displayMoney` multiplies a USD amount by the live ILS rate when ₪ is
selected — the donut percentages (USD-derived) never change, only the rendered
amounts. The ₪ button is disabled until the rate loads, and falls back to USD if
the rate is unavailable.

---

## Deviations / decisions

| Area | Choice | Why |
|---|---|---|
| Conversion layer | **display-only** (frontend), not a stored base | report data stays USD-canonical; zero risk of corrupting totals/percentages; instant toggle |
| Persistence | **localStorage** (per browser) | no schema/auth change; the choice follows the user across pages incl. `/r` |
| Editor prices | unchanged (native ₪ for TASE per-share) | the toggle is for the *portfolio* base; per-share price stays in its native quote |
| `v17` tag | deferred | pending the live browser check |

---

## Patterns established

85. **Display-layer currency conversion.** Keep one canonical base in the data
    (USD) and convert only at render via a live rate + a persisted preference —
    correctness (percentages, stored totals) is never at the mercy of the toggle.

*(Patterns #1–#84 from V1–V16 remain in force.)*

---

## V17 git history

```
feat(v17): user-selectable base currency (USD / ₪) on the report
docs(v17): add V17 implementation brief
(tag) v17  — pending live browser check
```

To reconstruct the V17 baseline at any point once tagged: `git checkout v17`.
