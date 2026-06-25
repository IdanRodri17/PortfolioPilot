# PortfolioPilot V21 — Implementation Brief

> First item from `docs/REVIEW.md`: make the report's headline number trustworthy,
> and stand up the project's first automated tests.

**Status:** Shipped (verified live + unit-tested). Tag `v21` pending the usual live
browser check. Code on `main`.

**Headline:** the report's **Portfolio value** and **24h change** — the numbers a busy
user trusts most — are now computed deterministically in Python, not by the LLM. And
the codebase has a **test suite** for the first time.

---

## 1. Deterministic headline valuation

**Problem.** Everything in the report was deterministic *except* the hero figure: the
synthesizer prompt asked the LLM to "compute total_usd and the weighted 24h change," so
the most-trusted number rode on LLM arithmetic and could drift or disagree with the
(deterministic) donut total.

**Fix.**
- `risk_agent.py`: compute the **value-weighted 24h change** (`sum(value_i × change_i) /
  total`) and return `total_change_24h_percent` in `risk_analysis` (`0.0` in the no-data
  path). `total_value_usd` already existed.
- `synthesizer.py`: after assembling the report, **overwrite**
  `portfolio_valuation.total_usd` and `.change_24h_percent` with the deterministic values
  (same pattern as composition and the V20 P/L totals). The guardrail (which runs after)
  now validates real numbers.

**Verified:** a live report's `total_usd` equals the sum of `portfolio_composition[].value_usd`
(11196.07 ≈ 11196.06) and the 24h change is the weighted figure.

## 2. Test suite (the #1 industry-standard gap)

- Added `pytest` (+ `pytest.ini`, `backend/tests/`). **22 tests, all green.**
- `test_risk_agent.py` — composition (basic / unpriced-excluded / empty), P/L (US, loss,
  no-cost-basis, **NaN-price guard**, **TASE ₪→USD**, partial), violations (single-asset
  cap, min-assets, balanced), and the new deterministic weighted 24h change.
- `test_alerts.py` — `_evaluate_rules` (price/portfolio/concentration) + `_on_cooldown`.
- `test_stock_data.py` — `is_tase`, `is_crypto`.
- Run: from `backend/`, `./.venv/Scripts/python.exe -m pytest` (pure functions — no
  network/LLM/DB). Next: guardrail + `_is_due` tests, then wire into CI.

---

## Deviations / decisions

| Area | Choice | Why |
|---|---|---|
| LLM valuation fields | overwrite with deterministic values (don't remove from prompt) | minimal change; LLM still has context for the narrative |
| Tests location | `backend/tests/` run via local venv | container only mounts `backend/app`; pure tests need no env |
| Scope | deterministic valuation + pure-function tests | foundation first; broader coverage + CI come next |

## Patterns established

90. **Deterministic over LLM for every number.** Any figure a user acts on is computed in
    Python and attached to the report; the LLM writes prose, never arithmetic. The headline
    valuation joins composition, concentration, and P/L under this rule.
91. **Test the deterministic cores first.** The pure functions that produce money figures are
    the highest-value, lowest-friction things to lock down.

*(Patterns #1–#89 from V1–V20 remain in force.)*

---

## V21 git history
```
docs: add review backlog (REVIEW.md)
feat(v21): deterministic headline valuation + first test suite
docs(v21): add V21 implementation brief
(tag) v21 — pending live browser check
```
