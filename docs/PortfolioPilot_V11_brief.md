# PortfolioPilot V11 — Implementation Brief

> Appendix to `PortfolioPilot_SRS_dev.md` and `PortfolioPilot_Upgrades_BuildSpec.md`.
> Captures what was built for V11 (a new `macro_context_agent` that analyzes
> sector concentration across the whole portfolio), what deviated from the
> upgrade spec, and what was deferred — so any subsequent Claude conversation
> picks up with full context.

**Status:** Shipped. Tagged `v11` on `main`. The live end-to-end smoke test
passed: a tech-heavy report showed the "Sector concentration" row in the live
feed, the concentration section (Technology dominant, "High" chip, breakdown bar
+ diversification score), and a narrative that named the tech concentration.

**Headline:** the graph gained its first genuinely new analyst since V3 — a
deterministic `macro_context_agent` that looks at the portfolio *as a whole* and
flags correlated sector concentration the per-asset sentiment agents can't see
("78% of your value is Technology — that's one sector bet, not diversification").
It fans out in parallel alongside `risk_agent`, feeds a verbatim block into the
synthesizer prompt, and attaches a deterministic sector breakdown +
diversification score to the report.

**Smoke tests — verified in the build session (static / offline):**

- **Prompt 5 (node, scratch, sectors injected):** a tech-heavy portfolio yields
  `dominant_sector=Technology`, `concentration="high"`, and the Herfindahl
  diversification score (e.g. 95/5 split → 0.095); a 4-sector even split →
  `concentration="low"`, score 0.75; a 50/30/20 split → `"moderate"`; an
  unpriced portfolio → `concentration="unknown"`, empty breakdown, no error.
  `get_sector` returns the sector, degrades unknown/failed lookups to
  "Uncategorized", and never raises.
- **Prompt 6 (graph):** the compiled graph's node set contains
  `macro_context_agent`; the topology validates (the conditional-edge target
  enumeration includes it). The running container logged a clean WatchFiles
  reload + `Application startup complete` after the edits.
- **Prompt 7 (schema + synthesizer, scratch):** `ReportBody` (LLM-bound) does
  NOT carry `sector_concentration`; `FinalReport` does. `_build_sector_concentration`
  produces a typed, ordered block; empty/unknown macro → `None`. The new
  `{macro_analysis_block}` prompt slot composes; the assembled report JSON
  round-trips and a pre-V11 report (no field) still deserializes (→ `None`).
- **Prompt 8 (frontend):** `npx tsc --noEmit` and `eslint` clean.

**Smoke tests — confirmed live (via the Docker stack):**

- Generate a report for a tech-heavy portfolio (the curated AAPL/MSFT/NVDA/
  GOOGL/TSLA tells this story): the live feed shows **"Sector concentration"**
  lighting up in parallel with the sentiment agents; the report shows a
  **Sector concentration** section (Technology dominant, a "High" chip, the
  breakdown bar, the diversification score), and the **narrative explicitly
  names the tech concentration**. A manually diversified portfolio flips the
  chip to "Low"/"Moderate".

---

## What was built

### Prompt 5 — the node + state + sector lookup

```
backend/app/
├── tools/stock_data.py             # + get_sector(symbol) (lru_cached, never raises)
├── graph/state.py                  # + macro_analysis (single writer, no reducer)
└── graph/nodes/macro_context_agent.py   # NEW deterministic node
```

`macro_context_agent` mirrors `risk_agent`, not `sentiment_agent`: one instance
over the whole portfolio, writing the single-writer `macro_analysis` field.
Because it is fanned out **in parallel** with `risk_agent`, it cannot read
`risk_analysis` (not computed yet) — so it computes its own value weights from
`portfolio` + `market_data`, buckets each asset's value by `get_sector(symbol)`,
and emits `{sector_breakdown, dominant_sector, concentration,
diversification_score, note}`. Concentration is `high` if the dominant sector
> 60% of value, `moderate` > 40%, else `low`; the diversification score is
`1 - Σ(sector_share²)` (Herfindahl). All deterministic; no LLM.

### Prompt 6 — graph wiring

```
backend/app/
├── graph/builder.py    # add_node + Send + conditional-edge target + join edge
└── api/generate.py     # + "macro_context_agent" in _STATUS_NODES
```

Four wiring points to add a parallel fan-out target: register the node, append
`Send("macro_context_agent", state)` in `fan_out_to_agents`, add it to the
`add_conditional_edges` enumeration (static validation needs the full list), and
add the `macro_context_agent → synthesizer` edge so the implicit barrier waits
for it. Adding the name to `_STATUS_NODES` surfaces it in the SSE feed.

### Prompt 7 — synthesizer + report schema

```
backend/app/
├── schemas/report.py               # + SectorAllocation, SectorConcentration;
│                                    #   FinalReport.sector_concentration (optional)
└── graph/nodes/synthesizer.py      # macro prompt block + post-LLM attach
```

`_format_macro_block` renders `macro_analysis` into a verbatim prompt block
(like the risk block); the prompt instructs the model to name the dominant
sector in the narrative and factor concentration into rebalancing rationale
**without inventing numbers**. After the LLM call, `_build_sector_concentration`
attaches the deterministic block to `FinalReport` (same post-LLM pattern as
V10a's `portfolio_composition`; on `FinalReport`, not `ReportBody`, so it never
enters the LLM schema).

### Prompt 8 — frontend concentration UI

```
frontend/src/
├── lib/types.ts                    # mirror SectorAllocation / SectorConcentration
├── components/FinalReportView.tsx  # NEW "Sector concentration" section
└── components/LiveStatusFeed.tsx   # label macro_context_agent
```

A stacked value-weighted breakdown bar + color-matched legend, a concentration
chip (rose=high, amber=moderate, emerald=low, slate=unknown), the agent's note,
and the diversification score, with the standing not-financial-advice line.
Palette stays in the slate/emerald language. Hidden when there are no sectors.

---

## Deviations from the upgrade spec

| Area | Spec | V11 actually does | Why |
|---|---|---|---|
| Macro input | Prompt 5 said "read … `risk_analysis["composition_pct"]`" | Reads `portfolio` + `market_data` and computes its OWN value weights | It runs in PARALLEL with `risk_agent` (BuildSpec's "fanned out alongside"), so `risk_analysis` isn't available yet. The BuildSpec body agrees ("reading portfolio + market_data"). |
| Concentration cutoffs | "flag any sector > 60%" | high > 60%, moderate > 40%, else low | Gives the UI three honest levels instead of a binary flag. |
| `get_sector` failure | "missing/failed → Uncategorized" | Caches "Uncategorized" on failure too (lru_cache) and never raises | Sectors are stable; a never-raising helper keeps one bad lookup from failing the branch. Contrast `lookup_symbol`, which re-raises so the validate endpoint can tell outage from typo. |
| Correlation signal | V11 stretch: 30-day return correlation | Sector bucketing only | The truer "these move together" signal needs one history call per symbol; deferred (see below). |
| `v11` tag | tag on ship | Deferred until the live e2e smoke test passes | "No tag without a passing end-to-end check." |

---

## Explicitly deferred (build in noted version)

- **Push the `v11` tag.** Created locally after the live smoke test passed;
  `git push origin v11` to publish it.
- **Real return correlation (V11.5 / V16).** A 30-day-returns correlation matrix
  via `yfinance` history is a truer concentration signal than sector buckets but
  costs one history call per symbol — gate it behind a follow-up if the sector
  heuristic proves too coarse.
- **Sector coverage for crypto / TASE.** `.info["sector"]` is equity-oriented;
  crypto and some TASE tickers fall to "Uncategorized" (ties into the V16
  Israeli-market / crypto item).
- **`.info` latency.** macro adds N `get_sector` `.info` calls per first report
  (cached after). If yfinance rate-limits bite, consider a bulk/sector cache or
  a static symbol→sector map for the common tickers.

---

## Patterns established — load-bearing for later versions

59. **Parallel sibling analyst (mirror risk_agent).** A new whole-portfolio
    analyst is a single-instance, single-writer node fanned out in parallel. It
    must NOT depend on a sibling's output (compute what you need from the shared
    inputs). Adding a fan-out target = four points: `add_node`, the `Send`, the
    `add_conditional_edges` enumeration, and the join edge into synthesizer —
    plus `_STATUS_NODES` (backend feed) and `labelFor` (frontend feed).

60. **Deterministic index, LLM narrates.** Concentration level + Herfindahl
    diversification score are computed in Python; the synthesizer only narrates
    them from a verbatim block. Same discipline as risk_agent's violations.

61. **Never-raise vs re-raise lookups.** `get_sector` degrades silently
    (Uncategorized) because the caller just wants a bucket; `lookup_symbol`
    re-raises because its caller must distinguish "typo" from "provider down".
    Choose the failure contract by what the caller needs to tell apart.

62. **Deterministic-block pattern generalizes (pattern #55).** A second
    post-LLM-attached field (`sector_concentration`) confirms the
    `ReportBody` → `FinalReport` split scales: add the model, make it optional
    with a safe default on `FinalReport`, build it in the node after the call.

*(Patterns #1–#58 from V1–V10 remain in force. V9 will continue the counter when
it ships.)*

---

## Environment notes for the next Claude

- **`macro_analysis` is a single-writer state field** ({sector_breakdown,
  dominant_sector, concentration, diversification_score, note}); it is NOT
  reducer-merged (it runs once, like `risk_analysis`).
- **`composition_pct` is still a `{symbol: pct}` dict** (V10a note). macro
  re-derives value weights itself rather than reading it (parallel execution).
- **Verifying the graph offline:** from `backend/`,
  `./.venv/Scripts/python.exe -c "import app.graph.builder as b; print(sorted(b.graph.get_graph().nodes))"`
  compiles the graph and lists nodes (no DB needed). Monkeypatch
  `app.graph.nodes.macro_context_agent.get_sector` to test the node offline.
- **Backend hot reload works in Docker** (watchfiles polling): editing files
  under `backend/app/` triggers a clean reload in `portfoliopilot-backend`.

---

## V11 git history

```
feat(v11): add deterministic macro_context_agent (sector concentration)
feat(v11): fan macro_context_agent into the graph and status feed
feat(v11): weave concentration into synthesis and attach to the report
feat(v11): render sector concentration breakdown in the report
docs(v11): add V11 implementation brief
(tag) v11
```

To reconstruct the V11 baseline at any point: `git checkout v11`.
