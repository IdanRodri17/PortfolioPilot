"""
Tavily wrapper for recent news retrieval.

Single point of contact with the Tavily client. Nodes never import
the tavily SDK directly — they call fetch_news() defined here.

Why the wrapper (same rationale as stock_data.py):
    - Testability: this function is trivial to mock.
    - Replaceability: if Tavily is rate-limited or quality drops, the
      swap to NewsAPI or another provider stays contained to this file.
    - Error contract: Tavily can fail in several ways (network errors,
      rate limits, empty results). The wrapper normalizes them into
      one exception type.

Why the direct TavilyClient (not langchain_community's
TavilySearchResults Tool):
    LangChain Tool wrappers exist to make functions callable by an
    LLM's tool-use loop. We're not doing that — sentiment_agent calls
    this from Python code, not via tool-calling. Direct client keeps
    one less abstraction layer and avoids pulling langchain-community
    into the dep tree.

Consumed by:
    sentiment_agent (V3 step 3) — one call per portfolio symbol,
    feeding the LLM grounded news context for sentiment classification.

Concurrency note:
    The Tavily client is synchronous and blocks during the HTTP round-
    trip. V3's sentiment_agent runs once per Send() branch, and
    LangGraph runs Send branches concurrently — so 5 symbols will fire
    5 concurrent blocking Tavily calls via the asyncio threadpool.
    Acceptable at MVP scale. If Tavily latency becomes the bottleneck,
    wrap in asyncio.to_thread or switch to Tavily's async client.
"""

from typing import List

from tavily import TavilyClient

from app.core.config import get_settings


class NewsSearchError(Exception):
    """Raised when news search cannot retrieve usable results."""


# Singleton client — instantiated once at module load. The Tavily
# client is thread-safe; reusing it across requests avoids re-
# initializing session state per call. Same pattern as the compiled
# graph singleton in graph/builder.py.
_client = TavilyClient(api_key=get_settings().tavily_api_key)


def fetch_news(symbol: str, max_results: int = 5) -> List[dict]:
    """Fetch recent news snippets for a stock symbol.

    Args:
        symbol: Stock ticker, e.g. "AAPL".
        max_results: Maximum number of results to return. Tavily caps
            at 10; we use 5 to keep the downstream LLM prompt compact
            and credit usage modest.

    Returns:
        List of dicts shaped {"title": str, "content": str, "url": str}.
        Empty list if Tavily returns no results (rare but possible for
        obscure tickers); not raised as an error so the caller can
        decide whether absent news is fatal.

    Raises:
        NewsSearchError: on network failures or Tavily API errors.
    """
    query = f"latest {symbol} stock news"
    try:
        response = _client.search(
            query=query,
            topic="news",  # filters to news sources vs general web
            days=7,  # one-week recency window for 24h-context sentiment
            max_results=max_results,
            search_depth="basic",  # "advanced" costs more credits; basic is fine here
        )
    except Exception as e:
        raise NewsSearchError(f"Tavily search failed for '{symbol}': {e}") from e

    results = response.get("results", [])
    # Normalize to the minimal shape the sentiment_agent prompt needs.
    # The Tavily response also carries scores and a 'response_time' that
    # we deliberately drop — keep the contract narrow.
    return [
        {
            "title": r.get("title", ""),
            "content": r.get("content", ""),
            "url": r.get("url", ""),
        }
        for r in results
    ]
