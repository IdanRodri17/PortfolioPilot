"""Unit tests for the V23 what-changed digest (pure deltas vs the last report)."""

from datetime import datetime, timezone

from app.delivery.change_digest import compute_change_digest


def _md(price, change=0.0):
    return {"price": price, "change_24h_percent": change}


_PREV = {
    "portfolio_valuation": {"total_usd": 1000.0},
    "portfolio_composition": [{"asset": "AAPL", "pct": 100}],
}
_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_value_delta_and_notable():
    d = compute_change_digest(
        holdings={"AAPL": 10},
        prev_report=_PREV,
        prev_generated_at=_AT,
        market={"AAPL": _md(110, 5.0)},
    )
    assert d["total_usd"] == 1100.0
    assert d["value_delta_usd"] == 100.0
    assert d["value_delta_pct"] == 10.0
    assert d["movers"][0]["symbol"] == "AAPL"
    assert d["top_now"] == {"symbol": "AAPL", "pct": 100.0}
    assert d["notable"] is True
    assert d["prev_date"] == "2026-01-01"


def test_quiet_day_not_notable():
    d = compute_change_digest(
        holdings={"AAPL": 10},
        prev_report=_PREV,
        prev_generated_at=_AT,
        market={"AAPL": _md(100.1, 0.1)},
    )
    assert d["notable"] is False  # ~0.01% value move, 0.1% holding move


def test_movers_sorted_by_abs_move():
    prev = {"portfolio_valuation": {"total_usd": 300.0}, "portfolio_composition": []}
    d = compute_change_digest(
        holdings={"A": 1, "B": 1, "C": 1},
        prev_report=prev,
        prev_generated_at=None,
        market={"A": _md(100, 1.0), "B": _md(100, -8.0), "C": _md(100, 3.0)},
    )
    assert [m["symbol"] for m in d["movers"]] == ["B", "C", "A"]
    assert d["prev_date"] is None
