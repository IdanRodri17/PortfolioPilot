"""
data_ingestion node — fetches market data for every asset in the portfolio.

Versioning:
    V1: sequential, single asset, exceptions bubble.
    V2: sequential, multi-asset, per-asset try/except so one bad ticker
        does not kill the whole report.
    V3+: asyncio.gather over symbols for true parallel fetching.

The node stays thin: yfinance interaction lives in the tool wrapper.
This node orchestrates — iterate symbols, call the tool, catch failures.
"""

import logging

from app.graph.state import PortfolioState
from app.tools.stock_data import fetch_stock_data, StockDataError

logger = logging.getLogger(__name__)


def data_ingestion(state: PortfolioState) -> dict:
    """Populate market_data for every symbol in state["portfolio"].

    Reads:
        state["portfolio"] — {symbol: quantity}.

    Returns:
        {"market_data": {symbol: {"price": float, "change_24h_percent": float}}}

    Error handling:
        Per-symbol try/except. A failed fetch (invalid ticker, yfinance
        rate-limit, network blip) logs a warning and the symbol is
        omitted from market_data. The synthesizer detects the gap by
        comparing portfolio.keys() vs market_data.keys() and the prompt
        instructs it to flag the missing asset rather than hallucinate.

        Trade-off: silent omission with a downstream prompt-side flag is
        simpler than threading a data_errors field through State.
        V3 may revisit if richer error context (e.g., "rate-limited,
        retry later" vs "delisted") becomes useful.
    """
    market_data = {}
    for symbol in state["portfolio"].keys():
        try:
            market_data[symbol] = fetch_stock_data(symbol)
        except StockDataError as e:
            logger.warning("data_ingestion: skipping %s — %s", symbol, e)
            # Continue with remaining symbols; do not bubble.
    return {"market_data": market_data}
