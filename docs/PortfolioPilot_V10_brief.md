# PortfolioPilot V10 — Implementation Brief

> Appendix to `PortfolioPilot_SRS_dev.md` and `PortfolioPilot_Upgrades_BuildSpec.md`.
> Captures what was built across V10 (V10a value-weighted allocation donut,
> V10b inline ticker validation), what deviated from the upgrade spec, and what
> was explicitly deferred — so any subsequent Claude conversation picks up with
> full context. (V9 — backend JWT — is intentionally sequenced later, just
> before the demo/share wave; see the Prelude note in the BuildSpec.)

**Status:** Shipped. Tagged `v10` on `main`. The live end-to-end smoke test
passed via the Docker stack: the portfolio editor's inline ticker validation
(name + price, blocked save on a typo, one request per settled symbol) and the
dashboard allocation donut (value-weighted slices, center total, legend) were
both confirmed in the browser.

**Headline:** the value-weighted composition `risk_agent` already computed —
previously discarded after every run — now rides on the report payload and
renders as a Recharts donut, and the portfolio editor validates each ticker
inline (company name + live price) before it can be saved. Two visible "this is
a product, not a demo" wins; the graph contract gained one deterministic field
and the synthesizer one post-LLM assembly step, nothing else changed shape.

**Smoke tests — verified in the build session (static / offline):**

- **V10a contract (pytest-style scratch):** `ReportBody` carries exactly the
  five LLM-authored fields and NOT `portfolio_composition`; `FinalReport`
  subclasses it and adds `portfolio_composition`. `_build_composition` returns
  slices sorted largest-first with `value_usd = round(pct/100 * total, 2)`,
  sums back to the total, yields `[]` for empty/missing composition, and the
  assembled `FinalReport` JSON round-trips (the archive/SSE shape). A pre-V10a
  report dict (no composition field) still deserializes, defaulting to `[]`.
- **V10a frontend:** `npx tsc --noEmit` and `eslint` clean; Recharts 3.8.1
  exports + `Pie` props verified against the installed package.
- **V10b backend (scratch, yfinance monkeypatched):** `lookup_symbol`
  normalizes case/whitespace, returns the name+price dict for a known ticker,
  `None` for an unknown one, raises `StockDataError` only on a real fetch
  failure (and `lru_cache` does not memoize that failure). The endpoint returns
  `{found:true,…}` / `{found:false,…}` (200) / `502` on `StockDataError`.
- **V10b frontend:** `npx tsc --noEmit` and `eslint` clean (incl. React 19's
  `react-hooks/refs` rule — the validations ref is synced in an effect, not
  during render).

**Smoke tests — confirmed live (via the Docker stack):**

- Generate a report on the dashboard for a user with a portfolio → the donut
  appears in the valuation section, slices sized by value (largest first),
  center shows the total $, legend rows read `SYMBOL pct% · $value`; the
  `report_complete` SSE payload contains `portfolio_composition`.
- In the editor, typing `AAPL` shows "Apple Inc. · $…"; `ZZZZ` shows
  "Couldn't find that ticker" + a red field + a blocked Save; the network tab
  shows one `/api/ticker/validate` call per settled symbol, not per keystroke;
  saving a valid portfolio still works.

---

## What was built

### V10a — Value-weighted allocation donut

```
backend/app/
├── schemas/report.py            # split FinalReport -> ReportBody (LLM-bound)
│                                 #   + FinalReport(ReportBody) adds
│                                 #   portfolio_composition; + AssetAllocation
└── graph/nodes/synthesizer.py   # bind chain to ReportBody; attach
                                 #   portfolio_composition deterministically
                                 #   via _build_composition(risk_analysis)

frontend/src/
├── lib/types.ts                 # mirror AssetAllocation; optional
│                                 #   portfolio_composition on FinalReport
├── components/AllocationDonut.tsx  # NEW: Recharts donut + legend + center total
└── components/FinalReportView.tsx  # mount the donut in the valuation section
```

**Deterministic, not LLM-emitted.** `risk_agent` returns
`risk_analysis["composition_pct"]` (a `{symbol: percent}` dict) and
`total_value_usd`. The synthesizer now binds the LLM to **`ReportBody`** (the
five authored fields), then builds `portfolio_composition` in Python —
`value_usd = round(pct/100 * total_value_usd, 2)`, sorted largest-first — and
returns `FinalReport(**body.model_dump(), portfolio_composition=…)`. The exact
percentages never enter the model's JSON schema, honoring the project rule.
Because composition lives on the report payload, the `reports.raw_result`
archive, `/history` replay, and (future) shareable reports inherit it for free.

**Shape note for downstream versions.** `composition_pct` is a **dict keyed by
symbol** (values 0–100, 2dp), not a list of objects, and `risk_analysis` has
**no per-asset USD** — only `total_value_usd`. That's why `value_usd` is derived
from the percentage rather than read directly.

**Donut rendering.** `AllocationDonut` is sized by `value_usd` (`dataKey`),
colored per slice via `<Cell>` in an emerald→slate ramp (no rainbow; amber
stays reserved for the in-flight feed), with a center-overlay total (= sum of
slices) and a color-matched legend that doubles as the slice labels
(`SYMBOL pct% · $value`). Empty composition renders an honest "no priced
holdings" state.

### V10b — Inline ticker validation

```
backend/app/
├── tools/stock_data.py          # + lookup_symbol() (lru_cached) + the
│                                 #   _lookup_symbol_cached inner
└── api/portfolio.py             # + GET /api/ticker/validate?symbol=...

frontend/src/
├── lib/api.ts                   # + validateTicker() + TickerValidation
└── app/portfolio/page.tsx       # debounced per-symbol inline validation
```

**Tri-state lookup contract.** `lookup_symbol` returns a `{name, price}` dict
(known), `None` (unknown ticker — a typo), or raises `StockDataError` (a real
fetch failure). The endpoint maps these to `{found:true,…}`, `{found:false,…}`
(HTTP 200), and HTTP 502 respectively, so the client can tell a typo apart from
a provider outage and degrade accordingly.

**Caching.** `@lru_cache(maxsize=512)` on the normalized symbol memoizes hits
and clean misses but not exceptions, so `.info` (slow, rate-limit-prone) is hit
at most once per symbol while transient failures stay retryable.

**Debounced editor.** Validation re-arms only when the *set* of normalized
symbols changes (a joined `symbolsKey`), not on quantity keystrokes; a 400ms
timer then validates only not-yet-seen symbols — one request per settled
symbol. Success shows "Name · $price"; a not-found shows an inline message, a
red field, and disables Save (so a typo can't be saved); a fetch failure shows
a soft, **non-blocking** "couldn't verify" (degrade, allow save). The latest
validations are read in the debounce via a ref synced in an effect.

---

## Deviations from the upgrade spec

| Area | Spec | V10 actually does | Why |
|---|---|---|---|
| Donut slice labels | "slice label `SYMBOL pct%`" via on-arc labels | A color-matched **legend** reading `SYMBOL pct% · $value` + hover tooltip; no on-arc text | Recharts 3.x changed the `label` render-prop geometry from the v2 examples and on-arc text clips in a fixed-height box that couldn't be visually verified offline. The legend is version-proof and more readable. |
| Donut center total | "centre shows total USD" | Center = **sum of the slices** (deterministic risk_agent basis), not `portfolio_valuation.total_usd` | Keeps the parts reconciling to the whole inside the chart. (The header still shows the report's stated total; the two can differ slightly because that one is LLM-computed — reconciling them is out of scope.) |
| Validate response when not found | "404-style `{found:false}`" | **HTTP 200** `{found:false}` | A 200 body is easier for the client to branch on; a thrown (non-OK) error is reserved for a real fetch failure (502), which is the meaningful distinction. |
| `v10` tag | tag on ship | **Deferred** until the live e2e smoke test passes | "No tag without a passing end-to-end check"; the live checks need the running stack + keys. |

---

## Explicitly deferred (build in noted version)

- **Push the `v10` tag.** Created locally after the live smoke test passed;
  `git push origin v10` to publish it.
- **Reconcile the two portfolio totals.** The valuation header uses the LLM's
  `portfolio_valuation.total_usd`; the donut center uses the deterministic
  risk_agent sum. A later pass could make the header authoritative-deterministic
  too (or note the distinction in the UI).
- **TASE / non-USD tickers in validation.** `lookup_symbol` returns whatever
  `.info` prices in; currency handling and `.TA` suffixes are untouched (ties
  into the V16 Israeli-market item).
- **Timing/PII:** `/api/ticker/validate` is unauthenticated by design (public
  market data only) — V9's guard should leave it open.

---

## Patterns established — load-bearing for later versions

55. **Two-layer report contract (`ReportBody` → `FinalReport`).** The LLM is
    bound to `ReportBody`; deterministic fields are attached to `FinalReport`
    after the call. New payload fields are optional with safe defaults so older
    archived `raw_result` JSON still deserializes and renders. This is the
    template for every future "computed-in-Python, shown-on-the-report" field
    (sector breakdown, diffs, advice grades).

56. **Tri-state external lookup + `lru_cache`.** A thin-wrapper lookup returns
    value / `None` (clean miss) / raises (real failure); `lru_cache` memoizes
    the first two but never the exception, so flaky upstreams stay retryable.
    Callers branch on the three states to degrade (block a typo, tolerate an
    outage).

57. **Recharts 3.x: verify the installed API, prefer controlled chrome.** Check
    the package's own types/exports rather than v2 examples; favor a legend you
    render over the churn-prone on-arc `label` render prop.

58. **React 19 refs rule.** Never assign `ref.current` during render
    (`react-hooks/refs` errors); sync it in a `useEffect`. Surfaced wiring a
    debounce that needs the latest state without re-arming on every change.

*(Patterns #1–#54 from V1–V8 remain in force. V9 will continue the counter when
it ships.)*

---

## Environment notes for the next Claude

- **Verifying backend logic without the stack:** the venv at
  `backend/.venv/Scripts/python.exe` runs scratch scripts from `backend/`
  (imports `app.*`; `backend/.env` is present so `get_settings()` loads).
  yfinance can be monkeypatched via `app.tools.stock_data.yf.Ticker` to test
  `lookup_symbol`/the endpoint offline. Delete scratch files after.
- **Frontend checks:** `npx tsc --noEmit` and `npx eslint <files>` from
  `frontend/` (node_modules present). React 19 + Next 16.2.6 enable newer
  hook lint rules (`react-hooks/refs`) not in older training data.
- **Recharts is 3.8.1** and already installed — no new chart dep.
- **`composition_pct` is a `{symbol: pct}` dict, not a list,** and there is no
  per-asset USD in `risk_analysis`. V11 (sector concentration) consumes the same
  dict + each symbol's sector.
- **The donut's deterministic basis** (risk_agent total) can differ slightly
  from the header's LLM total — expected, see deviations.

---

## V10 git history

```
feat(v10a): surface value-weighted composition on the report payload
feat(v10a): render value-weighted allocation donut on the dashboard
feat(v10b): add cached ticker validation endpoint
feat(v10b): inline ticker validation in the portfolio editor
docs(v10): add V10 implementation brief
(tag) v10
```

To reconstruct the V10 baseline at any point: `git checkout v10`.
