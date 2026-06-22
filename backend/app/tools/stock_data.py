"""
yfinance wrapper for stock price retrieval.

Single point of contact with the yfinance library. Nodes never import
yfinance directly — they call functions defined here.

Why the wrapper:
    - Testability: this function is trivial to mock or call in isolation.
    - Replaceability: if yfinance is rate-limited (SRS section 12), the
      swap to Alpha Vantage or another provider stays contained to this file.
    - Error contract: yfinance has several failure modes (empty data on
      invalid tickers, exceptions on network issues, silent partials on
      rate limits). The wrapper normalizes them into one exception.

Concurrency note:
    yfinance is synchronous and blocks the event loop. V1 calls it directly
    (acceptable for a single-symbol demo). V2+ will wrap calls with
    asyncio.to_thread + asyncio.gather to parallelize multi-asset fetches.
"""

from functools import lru_cache

import yfinance as yf


class StockDataError(Exception):
    """Raised when stock price data cannot be retrieved for a symbol."""


def fetch_stock_data(symbol: str) -> dict:
    """Fetch latest price and 24h percent change for a single stock symbol.

    Args:
        symbol: Stock ticker, e.g., "AAPL". yfinance supports TASE
            tickers via the ".TA" suffix (e.g., "TEVA.TA").

    Returns:
        Dict with shape {"price": float, "change_24h_percent": float},
        matching the per-asset payload expected in
        PortfolioState.market_data.

    Raises:
        StockDataError: if no usable history is returned (invalid ticker,
            delisted, or yfinance rate-limited).
    """
    ticker = yf.Ticker(symbol)

    # period="5d" gives breathing room around weekends and US market
    # holidays — we always need at least two trading days for a 24h delta.
    history = ticker.history(period="5d")

    if history.empty or len(history) < 2:
        raise StockDataError(
            f"No usable price history for symbol '{symbol}'. "
            f"Check the ticker is valid and yfinance is not rate-limited."
        )

    latest_close = float(history["Close"].iloc[-1])
    previous_close = float(history["Close"].iloc[-2])
    change_24h_percent = ((latest_close - previous_close) / previous_close) * 100

    return {
        "price": round(latest_close, 2),
        "change_24h_percent": round(change_24h_percent, 2),
    }


@lru_cache(maxsize=512)
def _lookup_symbol_cached(symbol: str) -> dict | None:
    """Cached inner lookup; `symbol` must already be normalized.

    lru_cache memoizes both a hit (the result dict) and a clean miss (None),
    but does NOT cache exceptions — so a transient fetch failure is retried on
    the next call rather than being stuck.
    """
    ticker = yf.Ticker(symbol)
    try:
        # .info is the canonical source for the company name, but it is slow
        # and rate-limit-prone — which is exactly why this is cached.
        info = ticker.info
    except Exception as exc:  # network error, rate-limit, or yfinance internals
        raise StockDataError(f"Could not look up symbol '{symbol}': {exc}") from exc

    name = info.get("longName") or info.get("shortName")
    price = (
        info.get("regularMarketPrice")
        or info.get("currentPrice")
        or info.get("previousClose")
    )
    if not name or price is None:
        # yfinance returns a sparse/empty info dict for an unknown ticker.
        return None
    return {"name": name, "price": round(float(price), 2)}


def lookup_symbol(symbol: str) -> dict | None:
    """Validate a ticker and return its company name + latest price.

    Args:
        symbol: Stock ticker, e.g. "AAPL". Case/whitespace insensitive.

    Returns:
        {"name": str, "price": float} for a known ticker, or None for an
        unknown one.

    Raises:
        StockDataError: only on a real fetch failure (network error or
            rate-limit) — NOT for an unknown ticker, which returns None. This
            split lets callers distinguish "typo" (block save) from "provider
            down" (allow save with a soft warning).
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return None
    return _lookup_symbol_cached(symbol)


@lru_cache(maxsize=512)
def _get_sector_cached(symbol: str) -> str:
    """Cached inner sector lookup; `symbol` must already be normalized."""
    try:
        sector = yf.Ticker(symbol).info.get("sector")
    except Exception:  # network, rate-limit, or partial/empty .info dict
        return "Uncategorized"
    return sector or "Uncategorized"


def get_sector(symbol: str) -> str:
    """Return an asset's sector via yfinance `.info`, cached per symbol.

    Never raises: a missing sector, an unknown ticker, or any fetch failure all
    degrade to "Uncategorized" (same posture as a failed news fetch), so one
    bad lookup never fails the macro branch. `.info` is slow and
    rate-limit-prone, hence the cache.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return "Uncategorized"
    return _get_sector_cached(symbol)
