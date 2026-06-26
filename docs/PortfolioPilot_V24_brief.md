# PortfolioPilot V24 — Implementation Brief

> `docs/REVIEW.md` V24 — answer "am I beating the market?". The portfolio was
> analyzed in a vacuum; now it's compared to the S&P 500 and Nasdaq.

**Status:** Shipped (backend verified live; frontend tsc + eslint clean). Tag `v24`
pending the live browser check. Code on `main`.

**Headline:** the report hero now shows your 24h move **vs S&P 500 and Nasdaq**, and the
history chart overlays a **rebased S&P 500 line** so you can see your trajectory against
the market.

---

## What was built

```
backend/app/
├── schemas/report.py          # BenchmarkChange; PortfolioValuation.benchmark_24h
├── graph/state.py             # state["benchmark"]
├── graph/nodes/data_ingestion.py  # fetch SPY + QQQ 24h alongside holdings
├── graph/nodes/synthesizer.py # attach benchmark_24h to the valuation (deterministic)
└── api/reports.py             # series endpoint adds a rebased benchmark_usd per point

frontend/src/
├── lib/types.ts               # BenchmarkChange on valuation; benchmark_usd on series
├── components/FinalReportView.tsx  # hero "vs S&P 500 … · Nasdaq …" line
└── app/history/page.tsx       # second (dashed) line + legend on the value-trend chart
```

### How it works
- **Report (24h vs market):** `data_ingestion` fetches SPY (≈S&P 500) and QQQ (≈Nasdaq)
  24h change alongside the holdings; the synthesizer attaches them to
  `portfolio_valuation.benchmark_24h` (deterministic, persisted, shows in history/share).
  The hero renders e.g. *"▼ −3.5% past 24h … vs S&P 500 +0.1% · Nasdaq +0.8%"* — instantly
  showing out/under-performance.
- **History (trajectory vs market):** the series endpoint adds `benchmark_usd` per report
  date = `first_total × SPY_close(date) / SPY_close(first_date)` (via `price_on`, which
  falls back to the nearest prior close and never raises). So the overlay **starts at your
  starting value and tracks the S&P's % moves** — a true "you vs the market" line. Null
  points are skipped (`connectNulls`); the line + legend only render when data exists.

---

## Smoke test
- **Verified (backend, live):** the report payload carries `benchmark_24h` (S&P 500 +0.14%,
  Nasdaq +0.81% vs the portfolio's −3.53%); `price_on("SPY")` resolves for the overlay.
- **Pending (browser):** the hero "vs S&P 500 / Nasdaq" line; the dashed S&P line + legend
  on `/history` (needs ≥2 reports).

---

## Patterns established
95. **Benchmark by rebasing, not raw price.** To compare a portfolio's trajectory to an
    index, plot the index rebased to the portfolio's starting value — it reads as "the same
    money in the S&P" and the two lines are directly comparable.

*(Patterns #1–#94 from V1–V23 remain in force.)*

---

## V24 git history
```
feat(v24): benchmark vs S&P 500 / Nasdaq (report hero + history overlay)
docs(v24): add V24 implementation brief
(tag) v24 — pending live browser check
```
