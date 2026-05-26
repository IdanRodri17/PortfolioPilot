"""
data_ingestion node — fetches market data for every asset in the portfolio.

Versioning:
    V1: sequential calls to the yfinance wrapper (one stock).
    V2: still sequential, but loops over a real multi-asset portfolio.
    V3+: asyncio.gather over symbols for true parallel fetching.

The node stays thin: all yfinance interaction lives in the tool wrapper.
This node only orchestrates — pull symbols from state, call the tool,
return the partial state update.
"""

from app.graph.state import PortfolioState
from app.tools.stock_data import fetch_stock_data


def data_ingestion(state: PortfolioState) -> dict:
    """Populate market_data for every symbol in state["portfolio"].

    Reads:
        state["portfolio"] — {symbol: quantity}.

    Returns:
        {"market_data": {symbol: {"price": float, "change_24h_percent": float}}}

    Error handling:
        Tool exceptions propagate. V1 fails the whole run on any bad
        symbol (acceptable for one-asset smoke test). V3+ will switch
        to per-asset try/except so one failure doesn't kill the report.
    """
    market_data = {}
    for symbol in state["portfolio"].keys():
        market_data[symbol] = fetch_stock_data(symbol)
    return {"market_data": market_data}
