# PortfolioPilot V20 — Implementation Brief

> Appendix to `PortfolioPilot_SRS_dev.md`. Cost-basis P/L: record a buy price per
> holding and see each position's (and the total) gain/loss in % and money.

**Status:** Shipped (backend verified live end-to-end; frontend `tsc` + `eslint`
clean; hardened by an adversarial review). The `v20` tag is **pending the live
browser check**. Code on `main`.

**Headline:** the user enters an optional **buy price** for each holding; the app
then shows **gain/loss in both percent and money** — per holding and as a total —
computed deterministically (never via the LLM), in USD-canonical, and respecting
the ₪/$ display toggle.

---

## What was built

```
backend/app/
├── db/models.py            # Portfolio.cost_basis JSONB {symbol: buy_price}
├── db/light_migrations.py  # ADD COLUMN IF NOT EXISTS portfolios.cost_basis
├── schemas/portfolio.py    # cost_basis on request/response (+ buy price > 0)
├── api/portfolio.py        # round-trip cost_basis on upsert + GET
├── graph/state.py          # cost_basis input field
├── graph/nodes/risk_agent.py   # _compute_pnl: per-asset + total gain/loss (USD)
├── graph/nodes/synthesizer.py  # attach P/L to AssetAllocation + PortfolioValuation
├── schemas/report.py       # optional P/L fields (additive, backward-compatible)
├── api/generate.py + delivery/dispatcher.py  # thread cost_basis into initial_state
└── tools/stock_data.py     # thread-safe FX cache (lock)

frontend/src/
├── lib/types.ts            # cost_basis + optional P/L fields
├── app/portfolio/page.tsx  # optional buy-price input (currency-aware placeholder)
└── components/
    ├── FinalReportView.tsx # "return on cost" line in the value hero
    └── AllocationDonut.tsx # per-holding gain/loss % in the legend
```

---

## Key design decisions

- **Native-currency storage, USD-canonical compute.** Buy prices are stored in the
  symbol's *native* currency (what the editor shows and the user types — ₪ for
  TASE, $ otherwise), keeping the editor dead-simple. `risk_agent` converts TASE
  buy prices ₪→USD with `usd_ils_rate()` before comparing to the (already-USD)
  current price. Because both the buy and current price divide by the same rate,
  the **percentage is FX-independent** (the asset's own return) and the **money is
  current USD**.
- **In the graph, deterministically.** P/L lives where the composition is already
  computed (`risk_agent` → `synthesizer`), so it's part of the persisted report
  (history/share show it) and the V6 guardrail sees real numbers. The graph stays
  a pure function of its inputs — `cost_basis` is just another input dict.
- **Additive + optional everywhere.** New columns, schema fields, and TS types are
  all optional/None. Holdings without a buy price, and reports archived before
  V20, render unchanged. Cost basis is opt-in per holding.
- **Respects the ₪/$ toggle (V17).** Displayed P/L *money* converts via the live
  rate; percentages are currency-agnostic.

---

## Hardening (adversarial review — fixed before commit)

| Severity | Finding | Fix |
|---|---|---|
| **High** | "total return" misleading when only some holdings have a cost basis | relabel → **"return on cost"** (accurate for full or partial) |
| **Medium** | no positive-price guard in `_compute_pnl` (corrupt 0/neg price → nonsense) | `if current_usd <= 0: continue` |
| **Medium** | editor buy-price input didn't show the expected currency | currency-aware placeholder (`Buy price ($)` / `(₪)`) from the live lookup |
| **Low** | FX cache read-fetch-write unsynchronized (V20 calls it from the graph) | `threading.Lock` around the cache cycle |

---

## Smoke tests

- **Verified (backend, live):** migration added `portfolios.cost_basis`; the
  report payload carries correct per-holding P/L and totals — including the TASE
  ₪→USD conversion (TEVA ₪90 → ~$30 cost). The demo portfolio was seeded with buy
  prices so P/L shows immediately.
- **Pending (browser):**
  1. `/portfolio` → each holding has a **Buy price** field (placeholder shows the
     ticker's currency); enter some, **Save**.
  2. **Generate report** (dashboard or `/demo`) → the value hero shows a
     **"return on cost"** line (% + money), and each allocation-legend row shows
     that holding's **gain/loss %**.
  3. Toggle **₪** → the P/L money converts; the % stays.
  4. A holding with **no** buy price simply shows no P/L (nothing breaks).

---

## Patterns established

89. **Native-in, canonical-out money.** Store user-entered money in the unit the
    user thinks in (native currency), convert to the canonical base (USD) at
    compute time. The ratio (%) is conversion-independent; only the absolute is
    converted — so a return % is correct regardless of FX.

*(Patterns #1–#88 from V1–V19 remain in force.)*

---

## V20 git history

```
feat(v20): cost-basis P/L — enter a buy price, see each holding's gain/loss
docs(v20): add V20 implementation brief
(tag) v20  — pending live browser check
```

To reconstruct the V20 baseline once tagged: `git checkout v20`.
