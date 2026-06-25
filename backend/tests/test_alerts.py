"""Unit tests for the threshold-alert rule engine (V18) — pure evaluation +
cooldown logic, no network/DB."""

from datetime import datetime, timedelta, timezone

from app.delivery.alerts import _evaluate_rules, _on_cooldown


def _md(price, change=0.0):
    return {"price": price, "change_24h_percent": change}


def test_price_move_fires_above_threshold():
    alerts = _evaluate_rules(
        holdings={"AAPL": 10},
        market={"AAPL": _md(200, -7.0)},
        price_move_pct=5,
        portfolio_move_pct=None,
        concentration_pct=None,
    )
    assert any(a["key"] == "price:AAPL" for a in alerts)


def test_price_move_silent_below_threshold():
    alerts = _evaluate_rules(
        holdings={"AAPL": 10},
        market={"AAPL": _md(200, -2.0)},
        price_move_pct=5,
        portfolio_move_pct=None,
        concentration_pct=None,
    )
    assert alerts == []


def test_portfolio_move_weighted():
    alerts = _evaluate_rules(
        holdings={"AAPL": 10, "MSFT": 10},
        market={"AAPL": _md(100, 10.0), "MSFT": _md(100, 10.0)},
        price_move_pct=None,
        portfolio_move_pct=5,
        concentration_pct=None,
    )
    assert any(a["key"] == "portfolio:move" for a in alerts)


def test_concentration_fires():
    alerts = _evaluate_rules(
        holdings={"AAPL": 10, "MSFT": 1},
        market={"AAPL": _md(200), "MSFT": _md(100)},
        price_move_pct=None,
        portfolio_move_pct=None,
        concentration_pct=40,
    )
    assert any(a["key"] == "conc:AAPL" for a in alerts)


def test_no_rules_no_alerts():
    alerts = _evaluate_rules(
        holdings={"AAPL": 10},
        market={"AAPL": _md(200, 50.0)},
        price_move_pct=None,
        portfolio_move_pct=None,
        concentration_pct=None,
    )
    assert alerts == []


def test_on_cooldown():
    now = datetime.now(timezone.utc)
    state = {"price:AAPL": (now - timedelta(hours=2)).isoformat()}
    assert _on_cooldown(state, "price:AAPL", now, 12) is True  # within window
    assert _on_cooldown(state, "price:AAPL", now, 1) is False  # window passed
    assert _on_cooldown(state, "price:BTC", now, 12) is False  # never fired
