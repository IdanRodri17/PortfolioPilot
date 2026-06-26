# PortfolioPilot V26 — Implementation Brief

> `docs/REVIEW.md` V26 — kill the single highest-friction step in onboarding:
> entering a whole portfolio one holding at a time. Now you paste a CSV (or just
> describe your holdings in words) and review before saving.

**Status:** Shipped (backend verified live; 49 backend tests green; frontend tsc +
eslint clean). Tag `v26` pending the live browser check. Code on `main`.

**Headline:** a new **/portfolio/import** flow — **CSV / spreadsheet** (deterministic
parse) or **Describe in words** (one LLM call) → an editable **preview** with live
prices and per-row status → save by **adding to** or **replacing** your portfolio.

---

## What was built

```
backend/app/
├── schemas/import_portfolio.py     # ImportRequest (size caps), PreviewRow, ImportPreview
├── services/__init__.py            # NEW boundary-services package
├── services/portfolio_import.py    # parse_csv, _clean_number, normalize_rows, validate_holdings (pure)
├── services/nl_import.py           # one structured LLM call (lazy chain, timeout, retries off)
├── api/import_portfolio.py         # POST /api/portfolio/parse (dry-run, auth, rate-limit, off-loop)
└── main.py                         # wire the import router

frontend/src/
├── lib/types.ts                    # ImportMode/Request/PreviewRow/RowError/ImportPreview
├── lib/api.ts                      # parsePortfolioImport + getPortfolioOrNull (404-safe)
├── app/portfolio/import/page.tsx   # the 2-stage import flow (input → preview/edit → save)
└── app/portfolio/page.tsx          # "Import holdings" link next to "+ Add asset"
```

### How it works
- **One dry-run endpoint, two parsers.** `POST /api/portfolio/parse` takes
  `{mode: "csv"|"text", content}`. CSV is parsed **deterministically** (stdlib
  `csv.Sniffer` + an alias header map, positional fallback, `_clean_number` for
  `$`/`₪`/thousands/EU-decimals). Free text makes **exactly one** structured LLM
  call (`ChatOpenAI.with_structured_output`) that resolves names → tickers
  (Apple→AAPL, Teva→TEVA.TA) and is told **never to invent** a ticker.
- **Validity is decided once, by real data.** Both modes converge on a shared
  `validate_holdings` that re-checks **every** symbol via the existing
  `lookup_symbol` — so an LLM guess or a CSV typo surfaces as `unknown`, never a
  silent save. Status per row: `ok` / `unknown` (blocks) / `unverified` (soft-warn)
  / `needs_quantity` / `duplicate`, driving the editor's exact colors.
- **The parse never writes.** The only writer stays `POST /api/portfolio`. The
  preview hands rows to the same validation the manual editor uses, then saves —
  **Add to portfolio** (merge, default) or **Replace everything** — composed
  client-side into one full-replace upsert. No DB / schema / graph change.
- **Graph purity preserved:** all parsing lives in `app/services/`, never a graph
  node.

### Verified live
- CSV: `AAPL/BTC/TEVA.TA` → `ok` (TEVA.TA shows ₪99.57 from agorot→ILS, cost 42.5
  echoed), `NOTAREAL` → `unknown`, a `Total` footer silently skipped.
- Text: *"10 shares of Apple, half a Bitcoin, 1000 Teva bought at 12"* →
  AAPL (10), BTC (0.5), TEVA.TA (1000, buy 12) — names + quantities resolved.

---

## Adversarial review → fixes (before commit)

A multi-agent review (4 lenses → verify each finding) confirmed **13 real issues**;
all fixed and re-verified:

- **CRITICAL — merge could wipe holdings on a transient read failure.** The merge
  save fell back to "empty current" on *any* `getPortfolio` error (incl. a 5-min
  token blip), then full-replaced. Fixed with `getPortfolioOrNull` (null only on a
  true 404; rethrow otherwise) — a read failure now **aborts** the save.
- **HIGH — blocking lookups on the event loop.** `validate_holdings` (≤100 yfinance
  calls) ran in the async handler. Now `await asyncio.to_thread(...)`.
- **HIGH — stale cost basis on re-import.** Merging a held symbol with a new
  quantity but no buy price kept the old per-unit cost (corrupts P/L). Merge now
  treats the import's cost as authoritative-or-cleared per re-imported symbol.
- **MED** — UTF-8 BOM corrupted the first symbol on the no-header path (now
  stripped); a dollar **total** column (e.g. "Cost Basis Total") was mapped as a
  per-unit cost (now excluded, like bare "price"); duplicate rows blocked save with
  no button guard (now gated + a clear hint).
- **LOW** — accounting negatives `(150)` read as positive (now signed → flagged);
  EU `0,123` mis-read as 1000× (now decimal); LLM client given an explicit
  `timeout` + `max_retries=0` so a hung provider can't orphan the worker;
  per-user rate limit now covers **both** modes with stale-entry pruning; the NL
  unresolved-name hint and the 422 "Value error," prefix both cleaned up.

---

## Smoke test
1. **/portfolio** → an **Import holdings** button sits next to **+ Add asset**;
   click it for **/portfolio/import**.
2. **CSV paste:** `symbol,quantity,cost` / `AAPL,10,150` / `BTC,0.5` /
   `TEVA.TA,100,42.5` / `NOTAREAL,3` → **Preview import**. Expect AAPL/BTC/TEVA.TA
   green with name·price (TEVA.TA in ₪), NOTAREAL terracotta "couldn't find", and a
   "3 ready · 1 need a fix" banner.
3. **CSV upload:** pick a small `.csv` instead of pasting — same grid.
4. **Inline fix:** change NOTAREAL → MSFT; it re-validates green and Save unblocks.
5. **Describe in words:** switch tabs, paste *"10 Apple, 0.5 BTC, 1000 TEVA bought
   at 12"* → Preview. Names resolve to AAPL/BTC/TEVA.TA, all editable.
6. **Add to portfolio (merge):** with AAPL already held, "Add to my portfolio" →
   Save → **/portfolio** shows old + imported, AAPL's quantity updated.
7. **Replace everything:** re-import a small set with "Replace everything" → only
   the imported holdings remain.
8. **Bad input:** in text mode, paste gibberish → a friendly "couldn't read that —
   try CSV" message, no crash.

---

## Patterns established
97. **Import = parse (dry-run) → human preview → existing save.** Never let an
    importer be its own writer: parse to a reviewable preview, then route the save
    through the one battle-tested upsert so it inherits every validation. Validity
    is re-derived from real market data, never trusted from the parser or the LLM.
98. **LLM only where structure genuinely can't be inferred.** CSV is deterministic
    (instant, free, unit-testable with zero mocks); the LLM is reserved for free
    text. The model extracts + resolves names but never decides validity or
    currency.

*(Patterns #1–#96 from V1–V25 remain in force.)*

---

## V26 git history
```
feat(v26): portfolio import — paste a CSV or describe holdings in words
docs(v26): add V26 implementation brief
(tag) v26 — pending live browser check
```
