"""
sentiment_agent — per-symbol sentiment classification via Tavily + LLM.

Executed once per portfolio symbol via Send() fan-out (wired in V3 step 5).
Each invocation is independent: reads state["symbol"] (singular, populated
by the Send call), fetches recent news, classifies sentiment, returns a
single-item list to sentiment_findings.

The single-item-list return is load-bearing:
    sentiment_findings is declared Annotated[List[dict], add] in State.
    The `add` reducer is list concatenation. Each Send branch contributes
    one element; the reducer accumulates them. Returning a bare dict
    would TypeError at merge time (dict + list).

Versioning:
    V3: Tavily news + gpt-4o-mini classification.
    V4: same node, but emits intermediate progress events via the
        astream_events mechanism so the frontend can show "AAPL: searching
        news... classifying..." per branch.
    V5: enriched with long_term_memory context (the user's past sentiment
        about this asset) injected into the prompt.

Concurrency:
    Sync `def` — LangGraph dispatches sync Send-target nodes via the
    asyncio threadpool when the graph is awaited. For 5 symbols this is
    5 concurrent threadpool workers each doing one Tavily call + one
    OpenAI call. Total wall-clock is bounded by the slowest branch, not
    the sum. Switch to `async def` + AsyncTavily + ChatOpenAI.ainvoke
    if Tavily/OpenAI latency becomes the demo bottleneck.
"""

import logging
from typing import List, Literal

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.graph.state import PortfolioState
from app.schemas.report import MarketInsight
from app.tools.news_search import fetch_news, NewsSearchError

logger = logging.getLogger(__name__)


# ─── Internal schema for the LLM call ─────────────────────────────────
# We constrain the LLM to just sentiment + summary. The asset field is
# set programmatically below using the known symbol from State — never
# asking the LLM to repeat the ticker prevents "Apple Inc." or "Apple"
# showing up instead of "AAPL". Small reliability win for free.


class _SentimentClassification(BaseModel):
    sentiment: Literal["Positive", "Neutral", "Negative"] = Field(
        description=(
            "Overall market sentiment for this asset based on the news "
            "headlines and content provided."
        )
    )
    summary: str = Field(
        description=(
            "One to two sentence rationale grounded in specific signals "
            "from the news. Reference concrete events or headlines; avoid "
            "generic language like 'mixed sentiment' or 'market volatility'."
        )
    )


# ─── Prompt + chain (built once at module load) ───────────────────────

SYSTEM_PROMPT = (
    "You are a financial sentiment analyst. Given recent news about a "
    "single stock, classify the overall market sentiment as Positive, "
    "Neutral, or Negative, and write a brief grounded summary citing "
    "specific points from the news. Base your conclusion on the actual "
    "headlines and content provided — do not rely on prior knowledge of "
    "the company beyond what the news supports."
)

HUMAN_PROMPT = (
    "Stock symbol: {symbol}\n\n"
    "Recent news:\n"
    "{news_block}\n\n"
    "Classify sentiment and write a 1-2 sentence rationale grounded in "
    "the news above."
)

_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("human", HUMAN_PROMPT),
    ]
)

# gpt-4o-mini is the per-agent model per SRS §2: cheap enough to fan
# out to N symbols without burning credits, capable enough for a
# 5-snippet classification task.
_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3)

_chain = _prompt | _llm.with_structured_output(_SentimentClassification)


# ─── Helpers ──────────────────────────────────────────────────────────


def _format_news_block(news: List[dict]) -> str:
    """Render the news list as a numbered block for the LLM prompt.

    Each item: title on one line, truncated content on the next.
    Content is capped at ~200 chars because titles carry most of the
    signal and full content blows up the prompt without much benefit.
    """
    if not news:
        return "(no recent news available)"
    lines = []
    for i, item in enumerate(news, 1):
        title = item.get("title", "")
        content = item.get("content", "")
        if len(content) > 200:
            content = content[:200] + "..."
        lines.append(f"{i}. {title}\n   {content}")
    return "\n\n".join(lines)


def _degraded_insight(symbol: str, reason: str) -> dict:
    """Build a fallback MarketInsight when news retrieval fails.

    Returns the dict form (not the model) so the caller can drop it
    directly into the single-item list expected by the reducer.
    """
    return MarketInsight(
        asset=symbol,
        sentiment="Neutral",
        summary=(
            f"Recent news could not be retrieved for {symbol} ({reason}); "
            f"sentiment assessment is unavailable for this asset."
        ),
    ).model_dump()


# ─── Node ─────────────────────────────────────────────────────────────


def sentiment_agent(state: PortfolioState) -> dict:
    """Classify sentiment for one symbol via Tavily news + LLM.

    Reads:
        state["symbol"] — singular, populated by the Send() call in
            step 5. The node does no iteration over the portfolio.

    Returns:
        {"sentiment_findings": [insight_dict]}

        Single-item list. Step 1's reducer concatenates these across
        all parallel branches into the accumulated sentiment_findings.
    """
    symbol = state["symbol"]

    try:
        news = fetch_news(symbol, max_results=5)
    except NewsSearchError as e:
        logger.warning("sentiment_agent: news fetch failed for %s — %s", symbol, e)
        # Don't kill the branch — return a degraded insight so the
        # other parallel branches still produce a complete report.
        return {"sentiment_findings": [_degraded_insight(symbol, "news fetch failed")]}

    classification = _chain.invoke(
        {
            "symbol": symbol,
            "news_block": _format_news_block(news),
        }
    )

    insight = MarketInsight(
        asset=symbol,  # programmatic, not LLM-derived
        sentiment=classification.sentiment,
        summary=classification.summary,
    )

    # SINGLE-ITEM LIST — required by the reducer. See module docstring.
    return {"sentiment_findings": [insight.model_dump()]}
