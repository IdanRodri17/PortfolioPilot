"""Unit tests for the pure market-data helpers (symbol classification). These
gate the crypto/TASE routing that the whole pipeline depends on. No network."""

from app.tools.stock_data import is_tase, is_crypto


def test_is_tase():
    assert is_tase("TEVA.TA") is True
    assert is_tase("AAPL") is False
    assert is_tase("BTC") is False


def test_is_crypto():
    assert is_crypto("BTC") is True
    assert is_crypto("btc") is True  # normalized to upper
    assert is_crypto("AAPL") is False
    assert is_crypto("TEVA.TA") is False
