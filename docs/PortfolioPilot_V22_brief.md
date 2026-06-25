# PortfolioPilot V22 — Implementation Brief

> `docs/REVIEW.md` V22 — the user's idea: surface popular stocks the user *doesn't*
> hold, so the dashboard becomes a reason to come back, not just an analysis tool.

**Status:** Shipped (backend verified live; frontend tsc + eslint clean). Tag `v22`
pending the live browser check. Code on `main`.

**Headline:** a **"Trending today"** card on the dashboard + demo shows popular US names
(biggest movers first) that aren't already in your portfolio, each with a one-click
**"+ Add"** that drops it into the editor.

---

## What was built

```
backend/app/
├── tools/stock_data.py   # fetch_trending_quotes() — one batched yfinance download
└── api/portfolio.py      # GET /api/trending (public, cached 15m, ranked by |24h move|)

frontend/src/
├── lib/types.ts          # TrendingStock
├── lib/api.ts            # getTrending()
├── components/TrendingStocks.tsx   # the card (fetches trending + excludes held)
├── app/page.tsx          # card on the dashboard (below the report)
├── app/demo/page.tsx     # card on the demo
└── app/portfolio/page.tsx# reads ?add=SYMBOL -> prepends an empty row
```

### Design decisions
- **Curated "popular" list, honestly labeled.** Rather than wire a paid social-trending
  API, V22 uses a curated set of widely-held US names and **ranks by the size of the day's
  move**, so the card surfaces real movers with no new API key. A live-trending source can
  swap in behind the same endpoint later (REVIEW notes the options).
- **One batched quote fetch.** `fetch_trending_quotes` uses a single `yf.download` for all
  symbols (not N per-symbol calls) — fast and rate-limit-friendly. NaN-safe (drops
  incomplete bars). Result cached process-wide for 15 min behind a lock (no stampede; an
  empty/failed fetch isn't cached).
- **Excludes held symbols.** The card best-effort fetches the user's portfolio and filters
  out anything already owned (the user asked for stocks *not* in the portfolio). Falls back
  to showing all if that fetch fails.
- **"+ Add" → editor prefill.** Links to `/portfolio?add=SYMBOL`; the editor reads the param
  (via `window.location.search`, no Suspense gymnastics) and prepends an empty row.

---

## Smoke test
- **Verified:** `GET /api/trending?limit=N` returns N popular names with live price + 24h
  change, ranked by biggest move; the card mounts with no errors; tsc + eslint clean.
- **Pending (browser):** see the card populate, excluded-holdings filtering, and "+ Add".

---

## Patterns established
92. **Batch external quotes when you need many at once** — one `yf.download` + a TTL cache
    beats N per-symbol calls for list widgets.
93. **Discovery surfaces are public + cached + per-user-filtered** — the data is public and
    cached once process-wide; personalization (exclude held) happens on top, client-side.

*(Patterns #1–#91 from V1–V21 remain in force.)*

---

## V22 git history
```
feat(v22): trending/popular stocks discovery card
docs(v22): add V22 implementation brief
(tag) v22 — pending live browser check
```
