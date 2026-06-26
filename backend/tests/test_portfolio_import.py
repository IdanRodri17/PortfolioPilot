"""Unit tests for V26 portfolio import — pure, no network/LLM.

CSV parsing, number cleaning, normalization, and symbol resolution are exercised
with injected fakes (lookup_fn / a faked LLM chain), matching the suite's
zero-I/O convention.
"""

from types import SimpleNamespace

import pytest

from app.services.portfolio_import import (
    MAX_HOLDINGS,
    _clean_number,
    normalize_rows,
    parse_csv,
    validate_holdings,
)
from app.tools.stock_data import StockDataError


# ─── _clean_number ───────────────────────────────────────────────────────────

def test_clean_number_currency_and_thousands():
    assert _clean_number("$1,234.50") == 1234.5
    assert _clean_number("₪42.50") == 42.5
    assert _clean_number("1,234") == 1234.0  # 3-digit lone comma -> thousands
    assert _clean_number("1,234,567") == 1234567.0


def test_clean_number_eu_decimal():
    assert _clean_number("1,5") == 1.5
    assert _clean_number("1,50") == 1.5
    assert _clean_number("1.234,56") == 1234.56


def test_clean_number_plain_and_junk():
    assert _clean_number("10") == 10.0
    assert _clean_number("12.5%") == 12.5
    assert _clean_number("") is None
    assert _clean_number("  ") is None
    assert _clean_number(None) is None
    assert _clean_number("N/A") is None


def test_clean_number_negatives():
    # Accounting-style and signed negatives keep their sign (so a negative qty
    # routes to needs_quantity instead of a plausible-looking positive holding).
    assert _clean_number("(150.00)") == -150.0
    assert _clean_number("(1,234.56)") == -1234.56
    assert _clean_number("-5") == -5.0
    assert _clean_number("5-") == -5.0


def test_clean_number_eu_sub_one_three_decimals():
    # "0,123" is a decimal, not a thousands group (a real thousands group is
    # never "0,xxx"). Regression for the 1000x mis-parse.
    assert _clean_number("0,123") == 0.123
    assert _clean_number("-0,123") == -0.123
    assert _clean_number("1,234") == 1234.0  # still thousands


# ─── parse_csv ───────────────────────────────────────────────────────────────

def test_parse_csv_fidelity_style_header():
    csv_text = (
        "Symbol,Description,Quantity,Last Price,Average Cost Basis\n"
        "AAPL,Apple Inc,10,190.00,150.00\n"
        "MSFT,Microsoft,5,420.00,300.00\n"
    )
    rows, errors, warnings = parse_csv(csv_text)
    assert errors == []
    assert warnings == []
    assert {r["symbol"] for r in rows} == {"AAPL", "MSFT"}
    aapl = next(r for r in rows if r["symbol"] == "AAPL")
    assert aapl["quantity"] == 10.0
    # "Last Price" must NOT be picked up as cost; only "Average Cost Basis".
    assert aapl["cost_basis"] == 150.0


def test_parse_csv_schwab_style_header():
    csv_text = "Symbol,Qty,Cost Basis\nTSLA,3,220.5\n"
    rows, _, _ = parse_csv(csv_text)
    assert rows[0]["symbol"] == "TSLA"
    assert rows[0]["quantity"] == 3.0
    assert rows[0]["cost_basis"] == 220.5


def test_parse_csv_positional_fallback_warns():
    rows, errors, warnings = parse_csv("AAPL,10,150\nBTC,0.5\n")
    assert len(rows) == 2
    assert rows[0]["symbol"] == "AAPL" and rows[0]["quantity"] == 10.0
    assert rows[1]["symbol"] == "BTC" and rows[1]["cost_basis"] is None
    assert any("No header row" in w for w in warnings)


def test_parse_csv_skips_blank_and_footer_rows():
    csv_text = (
        "Symbol,Quantity\n"
        "AAPL,10\n"
        "\n"
        "Total,10\n"
        "Cash,500\n"
        "MSFT,5\n"
    )
    rows, errors, _ = parse_csv(csv_text)
    assert {r["symbol"] for r in rows} == {"AAPL", "MSFT"}
    assert errors == []


def test_parse_csv_symbol_without_quantity_emits_none():
    rows, errors, _ = parse_csv("Symbol,Quantity\nAAPL,\n")
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["quantity"] is None
    assert errors == []  # not an error — preview flags it as needs_quantity


def test_parse_csv_row_without_symbol_is_error():
    rows, errors, _ = parse_csv("Symbol,Quantity\n,10\n")
    assert rows == []
    assert len(errors) == 1
    assert errors[0].line == 2
    assert "No symbol" in errors[0].reason


def test_parse_csv_semicolon_delimited():
    rows, _, _ = parse_csv("Symbol;Quantity;Cost\nAAPL;10;150\n")
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["quantity"] == 10.0
    assert rows[0]["cost_basis"] == 150.0


def test_parse_csv_strips_bom_on_positional_path():
    # UTF-8 BOM from an Excel/Windows export must not corrupt the first symbol.
    rows, errors, _ = parse_csv("﻿AAPL,10,150\n")
    assert errors == []
    assert rows[0]["symbol"] == "AAPL"


def test_parse_csv_total_cost_header_not_mapped_as_unit_cost():
    # A dollar TOTAL column must NOT become a per-unit buy price.
    rows, _, _ = parse_csv(
        "Symbol,Quantity,Last Price,Cost Basis Total\nAAPL,10,190,1500\n"
    )
    assert rows[0]["quantity"] == 10.0
    assert rows[0]["cost_basis"] is None


def test_parse_csv_prefers_per_unit_cost_over_total():
    # Fidelity-style: both "Average Cost Basis" (per-unit) and a total are present;
    # the per-unit column (first match) wins.
    rows, _, _ = parse_csv(
        "Symbol,Quantity,Average Cost Basis,Cost Basis Total\nAAPL,10,150,1500\n"
    )
    assert rows[0]["cost_basis"] == 150.0


# ─── normalize_rows ──────────────────────────────────────────────────────────

def test_normalize_uppercases_symbols():
    rows, errors, truncated = normalize_rows([{"symbol": "aapl", "quantity": 1}])
    assert rows[0]["symbol"] == "AAPL"
    assert errors == [] and truncated is False


def test_normalize_caps_at_max_holdings():
    many = [{"symbol": f"S{i}", "quantity": 1} for i in range(MAX_HOLDINGS + 5)]
    rows, errors, truncated = normalize_rows(many)
    assert len(rows) == MAX_HOLDINGS
    assert truncated is True
    assert len(errors) == 1 and "limited to" in errors[0].reason


# ─── validate_holdings (injected lookup, no network) ─────────────────────────

def _fake_lookup(found: dict, errors_for: set = frozenset()):
    def _f(symbol: str):
        if symbol in errors_for:
            raise StockDataError("provider down")
        return found.get(symbol)
    return _f


def test_validate_ok_unknown_unverified():
    rows = [
        {"symbol": "AAPL", "input_symbol": "AAPL", "quantity": 10},
        {"symbol": "NOPE", "input_symbol": "NOPE", "quantity": 1},
        {"symbol": "DOWN", "input_symbol": "DOWN", "quantity": 1},
    ]
    lookup = _fake_lookup(
        {"AAPL": {"name": "Apple Inc.", "price": 190.0, "currency": "USD"}},
        errors_for={"DOWN"},
    )
    out = validate_holdings(rows, lookup_fn=lookup)
    by = {r.symbol: r for r in out}
    assert by["AAPL"].status == "ok"
    assert by["AAPL"].name == "Apple Inc." and by["AAPL"].currency == "USD"
    assert by["NOPE"].status == "unknown"
    assert by["DOWN"].status == "unverified"


def test_validate_needs_quantity():
    rows = [{"symbol": "AAPL", "input_symbol": "AAPL", "quantity": None}]
    lookup = _fake_lookup({"AAPL": {"name": "Apple", "price": 1.0, "currency": "USD"}})
    out = validate_holdings(rows, lookup_fn=lookup)
    assert out[0].status == "needs_quantity"
    # still looked up so the preview can show the name
    assert out[0].name == "Apple"


def test_validate_duplicate_flagged():
    rows = [
        {"symbol": "AAPL", "input_symbol": "AAPL", "quantity": 10},
        {"symbol": "AAPL", "input_symbol": "AAPL", "quantity": 5},
    ]
    lookup = _fake_lookup({"AAPL": {"name": "Apple", "price": 1.0, "currency": "USD"}})
    out = validate_holdings(rows, lookup_fn=lookup)
    assert out[0].status == "ok"
    assert out[1].status == "duplicate"


def test_validate_tase_currency_and_cost_echoed():
    rows = [{"symbol": "TEVA.TA", "input_symbol": "TEVA.TA", "quantity": 100, "cost_basis": 42.5}]
    lookup = _fake_lookup(
        {"TEVA.TA": {"name": "Teva", "price": 38.0, "currency": "ILS"}}
    )
    out = validate_holdings(rows, lookup_fn=lookup)
    assert out[0].status == "ok"
    assert out[0].currency == "ILS"  # from lookup only
    assert out[0].cost_basis == 42.5  # echoed unchanged, no FX


# ─── nl_import (faked chain, no LLM) ─────────────────────────────────────────

def test_nl_parse_text_converges_on_shape(monkeypatch):
    import app.services.nl_import as nl

    fake = SimpleNamespace(
        holdings=[
            SimpleNamespace(symbol="AAPL", name_or_token="Apple", quantity=10, cost_basis=None),
            SimpleNamespace(symbol="BTC", name_or_token="Bitcoin", quantity=0.5, cost_basis=None),
            SimpleNamespace(symbol="TEVA.TA", name_or_token="Teva", quantity=1000, cost_basis=12.0),
        ]
    )
    monkeypatch.setattr(nl, "_get_chain", lambda: SimpleNamespace(invoke=lambda _: fake))

    rows = nl.parse_text("10 Apple, 0.5 BTC, 1000 TEVA bought at 12")
    by = {r["symbol"]: r for r in rows}
    assert by["AAPL"]["quantity"] == 10 and by["AAPL"]["input_symbol"] == "Apple"
    assert by["BTC"]["quantity"] == 0.5
    assert by["TEVA.TA"]["cost_basis"] == 12.0


def test_nl_hallucinated_ticker_becomes_unknown(monkeypatch):
    import app.services.nl_import as nl

    fake = SimpleNamespace(
        holdings=[SimpleNamespace(symbol="FAKE", name_or_token="Acme", quantity=1, cost_basis=None)]
    )
    monkeypatch.setattr(nl, "_get_chain", lambda: SimpleNamespace(invoke=lambda _: fake))

    rows = nl.parse_text("I own some Acme")
    # The LLM emitted a ticker; validation (not the LLM) decides it's unknown.
    out = validate_holdings(rows, lookup_fn=_fake_lookup({}))
    assert out[0].status == "unknown"


def test_nl_parse_failure_raises(monkeypatch):
    import app.services.nl_import as nl

    def _boom(_):
        raise RuntimeError("openai down")

    monkeypatch.setattr(nl, "_get_chain", lambda: SimpleNamespace(invoke=_boom))
    with pytest.raises(nl.NLParseError):
        nl.parse_text("anything")
