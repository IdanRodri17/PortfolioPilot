"""Unit tests for the deterministic risk_agent core (composition, P/L, the V21
value-weighted headline change, and risk violations). These functions carry the
report's numbers, so they're the highest-value things to lock down. All pure —
no network, LLM, or DB."""

import math

from app.graph.nodes.risk_agent import (
    risk_agent,
    _compute_composition,
    _compute_pnl,
    _check_violations,
)


def _md(price, change=0.0):
    return {"price": price, "change_24h_percent": change}


# ─── _compute_composition ───────────────────────────────────────────────


def test_composition_basic():
    total, comp = _compute_composition(
        {"AAPL": 10, "MSFT": 5}, {"AAPL": _md(200), "MSFT": _md(100)}
    )
    assert total == 2500
    assert comp["AAPL"] == 80.0
    assert comp["MSFT"] == 20.0
    assert round(sum(comp.values()), 6) == 100.0


def test_composition_excludes_unpriced():
    total, comp = _compute_composition({"AAPL": 10, "XXX": 5}, {"AAPL": _md(200)})
    assert total == 2000
    assert "XXX" not in comp


def test_composition_empty_when_no_prices():
    total, comp = _compute_composition({"AAPL": 10}, {})
    assert total == 0.0
    assert comp == {}


# ─── _compute_pnl (V20) ─────────────────────────────────────────────────


def test_pnl_us_holding():
    pos, totals = _compute_pnl({"AAPL": 10}, {"AAPL": 250}, {"AAPL": _md(300)})
    assert pos["AAPL"]["cost_basis_usd"] == 2500
    assert pos["AAPL"]["gain_loss_usd"] == 500
    assert pos["AAPL"]["gain_loss_pct"] == 20.0
    assert totals["total_gain_loss_usd"] == 500
    assert totals["total_gain_loss_pct"] == 20.0


def test_pnl_loss():
    pos, _ = _compute_pnl({"AAPL": 10}, {"AAPL": 300}, {"AAPL": _md(240)})
    assert pos["AAPL"]["gain_loss_usd"] == -600
    assert pos["AAPL"]["gain_loss_pct"] == -20.0


def test_pnl_no_cost_basis_returns_empty():
    pos, totals = _compute_pnl({"AAPL": 10}, {}, {"AAPL": _md(300)})
    assert pos == {}
    assert totals is None


def test_pnl_skips_nan_price():
    # NaN is truthy and NaN<=0 is False — the isfinite guard must catch it (V20.1).
    pos, totals = _compute_pnl({"AAPL": 10}, {"AAPL": 250}, {"AAPL": _md(math.nan)})
    assert pos == {}
    assert totals is None


def test_pnl_tase_converts_ils_to_usd(monkeypatch):
    # TASE buy price is native ILS; current price is already USD. With rate 3.0,
    # ₪90 buy -> $30 cost/share; current $33 -> +$3/share -> +10% (FX-neutral).
    monkeypatch.setattr("app.graph.nodes.risk_agent.usd_ils_rate", lambda: 3.0)
    pos, _ = _compute_pnl({"TEVA.TA": 100}, {"TEVA.TA": 90}, {"TEVA.TA": _md(33.0)})
    assert pos["TEVA.TA"]["cost_basis_usd"] == 3000.0
    assert pos["TEVA.TA"]["gain_loss_usd"] == 300.0
    assert pos["TEVA.TA"]["gain_loss_pct"] == 10.0


def test_pnl_partial_cost_basis():
    # Only AAPL has a buy price; totals cover only the cost-tracked subset.
    pos, totals = _compute_pnl(
        {"AAPL": 10, "MSFT": 5}, {"AAPL": 250}, {"AAPL": _md(300), "MSFT": _md(100)}
    )
    assert set(pos) == {"AAPL"}
    assert totals["total_cost_basis_usd"] == 2500


# ─── _check_violations ──────────────────────────────────────────────────

_THRESH = {
    "max_single_asset_pct": 25,
    "min_assets_recommended": 3,
    "max_crypto_pct": 20,
}


def test_violation_single_asset_cap():
    v = _check_violations({"AAPL": 80, "MSFT": 20}, 2, _THRESH, "balanced")
    assert any("AAPL" in s for s in v)


def test_violation_min_assets():
    v = _check_violations({"AAPL": 100}, 1, _THRESH, "balanced")
    assert any("diversification" in s.lower() for s in v)


def test_no_violations_when_balanced():
    comp = {"AAPL": 20, "MSFT": 20, "NVDA": 20, "TSLA": 20, "GOOGL": 20}
    v = _check_violations(comp, 5, _THRESH, "balanced")
    assert v == []


# ─── risk_agent node — deterministic headline valuation (V21) ───────────


def test_risk_agent_weighted_24h_change():
    state = {
        "portfolio": {"AAPL": 10, "MSFT": 5},
        "market_data": {"AAPL": _md(200, 2.0), "MSFT": _md(100, -1.0)},
        "risk_profile": "balanced",
    }
    out = risk_agent(state)["risk_analysis"]
    assert out["total_value_usd"] == 2500
    # value-weighted: (2000*2 + 500*-1) / 2500 = 1.4
    assert out["total_change_24h_percent"] == 1.4


def test_risk_agent_no_priced_assets():
    out = risk_agent(
        {"portfolio": {"AAPL": 10}, "market_data": {}, "risk_profile": "balanced"}
    )["risk_analysis"]
    assert out["total_value_usd"] == 0.0
    assert out["total_change_24h_percent"] == 0.0
    assert out["pnl_totals"] is None
