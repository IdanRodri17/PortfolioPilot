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
