"""
guardrail node — validates the synthesizer's draft via cheap rule checks
plus an LLM-as-judge, and drives the Reflexion retry loop (V6).

Runs immediately after the synthesizer. Two layers:
    1. Rule checks (deterministic, free): catch the failure modes a judge
       is unreliable at — hallucinated tickers (an asset named in the
       report that isn't in the portfolio), a negative total valuation,
       and "guaranteed return"-style language. Fail-fast: if any rule
       trips we skip the (paid) judge call and feed the rule reasons back.
    2. LLM-as-judge (gpt-4o): only if the rules pass. Judges whether the
       report is grounded in the provided data and respects the risk
       profile, returning a structured {passed, feedback}.

The conditional edge route_after_guardrail (wired in builder.py) reads the
verdict + retry_count:
    passed                   -> memory_extractor (proceed)
    failed, budget left      -> synthesizer (retry with feedback)
    failed, budget exhausted -> memory_extractor (give up, ship best-effort)

Retry budget: retry_count is incremented on every guardrail entry and we
give up at >= _RETRY_BUDGET (3) — i.e. up to 2 regenerations (3 synthesizer
attempts). One integer knob.

Why gpt-4o (not -mini): judging grounding + risk-profile adherence is the
same class of task as synthesis; -mini under-detects subtle ungrounded
claims. Cost is bounded — the judge runs at most 3× per report, and only
when the cheap rules already passed.

Graceful degradation (pattern #22): the report is already produced by the
time we run, so a judge API blip must not trap the user in retries — on a
judge exception we pass through. On retry, the synthesizer prompt is
augmented with guardrail_feedback (Reflexion) — see synthesizer.
"""

import json
import logging
import os
from typing import List

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.graph.state import PortfolioState
from app.schemas.report import FinalReport

logger = logging.getLogger(__name__)

# Give up after this many guardrail evaluations (= 2 regenerations).
_RETRY_BUDGET = 3

# Overpromising language an honest wealth report should never contain.
# Matched case-insensitively against the narrative + recommendation rationales.
_BANNED_PHRASES = (
    "guaranteed return",
    "guaranteed returns",
    "guaranteed profit",
    "risk-free",
    "risk free",
    "can't lose",
    "cannot lose",
    "no risk",
    "sure thing",
)


class _GuardrailVerdict(BaseModel):
    """Structured-output schema for the LLM-as-judge call."""

    passed: bool = Field(
        description=(
            "True if the report is grounded in the provided data and respects "
            "the user's risk profile; False if it invents facts, ignores a "
            "flagged risk violation, or contradicts the data."
        )
    )
    feedback: str = Field(
        default="",
        description=(
            "When passed is False: a concise, specific list of what to fix, "
            "addressed to the report writer (e.g. 'AAPL is flagged at 37% over "
            "the 35% cap but no reduction is recommended'). When passed is "
            "True: a short confirmation; ignored downstream."
        ),
    )


SYSTEM_PROMPT = (
    "You are the validation layer of PortfolioPilot, an AI wealth manager. "
    "You receive a draft report produced by the synthesizer along with the "
    "data it was built from. Your job is to catch reports that are ungrounded "
    "or that ignore the user's risk profile — you are a strict reviewer, not "
    "a co-author. Pass a report only if: (a) every claim is supported by the "
    "provided market data, sentiment findings, and risk analysis (no invented "
    "prices, news, or events); (b) the rebalancing recommendations address the "
    "risk violations that were flagged, and do not recommend changes that "
    "would worsen a violation; (c) the narrative is internally consistent with "
    "the numbers. Be willing to pass a sound report — do not invent problems."
)

HUMAN_PROMPT = (
    "User risk profile: {profile_name}\n"
    "Risk profile guidance: {profile_description}\n\n"
    "Portfolio (symbol: quantity):\n{portfolio_block}\n\n"
    "Market data the report was built from:\n{market_data_block}\n\n"
    "Risk analysis (deterministic, from risk_agent):\n{risk_analysis_block}\n\n"
    "DRAFT REPORT under review:\n{draft_block}\n\n"
    "Evaluate the draft and return {{passed, feedback}}."
)

_prompt = ChatPromptTemplate.from_messages(
    [("system", SYSTEM_PROMPT), ("human", HUMAN_PROMPT)]
)
# gpt-4o per SRS §2 — judging grounding is a synthesis-class task.
_llm = ChatOpenAI(model="gpt-4o", temperature=0)
_chain = _prompt | _llm.with_structured_output(_GuardrailVerdict)


# ─── Rule checks (deterministic, free) ────────────────────────────────


def _rule_check(report: FinalReport, portfolio: dict) -> List[str]:
    """Return a list of human-readable rule failures (empty == clean)."""
    failures: List[str] = []
    held = set(portfolio.keys())

    referenced = {mi.asset for mi in report.market_insights}
    referenced |= {rec.asset for rec in report.rebalancing_recommendations}
    hallucinated = sorted(referenced - held)
    if hallucinated:
        failures.append(
            f"References assets not in the portfolio: {', '.join(hallucinated)}. "
            f"Only discuss held assets: {', '.join(sorted(held))}."
        )

    if report.portfolio_valuation.total_usd < 0:
        failures.append(
            f"Total portfolio value is negative "
            f"({report.portfolio_valuation.total_usd})."
        )

    haystack = " ".join(
        [report.summary_narrative]
        + [rec.rationale for rec in report.rebalancing_recommendations]
    ).lower()
    hits = sorted({p for p in _BANNED_PHRASES if p in haystack})
    if hits:
        failures.append(
            f"Contains overpromising language: {', '.join(hits)}. "
            f"Remove guarantees — investing carries risk."
        )

    return failures


def _format_portfolio_block(portfolio: dict) -> str:
    if not portfolio:
        return "(empty portfolio)"
    return ", ".join(f"{sym}: {qty}" for sym, qty in sorted(portfolio.items()))


# ─── Node + router ────────────────────────────────────────────────────


def guardrail(state: PortfolioState) -> dict:
    """Validate the draft report; emit {passed, feedback} + bump retry_count.

    Reads:
        final_report, portfolio, market_data, risk_analysis, risk_profile,
        retry_count.

    Returns:
        {"guardrail_passed": bool, "guardrail_feedback": str | None,
         "retry_count": int}
    """
    report: FinalReport = state["final_report"]
    portfolio = state["portfolio"]
    retry_count = state.get("retry_count", 0) + 1

    # Layer 1 — cheap deterministic rules. Fail-fast skips the paid judge.
    rule_failures = _rule_check(report, portfolio)
    if rule_failures:
        feedback = "Rule check failures:\n" + "\n".join(f"- {f}" for f in rule_failures)
        logger.info(
            "guardrail: FAIL (rules) attempt=%d — %s", retry_count, rule_failures
        )
        return {
            "guardrail_passed": False,
            "guardrail_feedback": feedback,
            "retry_count": retry_count,
        }

    # Demo aid: force ONE failure on the first evaluation so the retry loop
    # is observable end-to-end. Set GUARDRAIL_FORCE_FAIL=1 for the smoke
    # test, then unset. No effect in normal operation.
    if os.getenv("GUARDRAIL_FORCE_FAIL") == "1" and retry_count == 1:
        logger.info("guardrail: FORCED FAIL (demo) attempt=%d", retry_count)
        return {
            "guardrail_passed": False,
            "guardrail_feedback": (
                "Forced-failure demo: tighten the narrative's grounding to the "
                "provided market data and risk analysis."
            ),
            "retry_count": retry_count,
        }

    # Layer 2 — LLM-as-judge.
    try:
        verdict: _GuardrailVerdict = _chain.invoke(
            {
                "profile_name": state["risk_profile"],
                "profile_description": (state.get("risk_analysis") or {}).get(
                    "profile_description", ""
                ),
                "portfolio_block": _format_portfolio_block(portfolio),
                "market_data_block": json.dumps(state.get("market_data", {}), indent=2),
                "risk_analysis_block": json.dumps(
                    state.get("risk_analysis", {}), indent=2
                ),
                "draft_block": report.model_dump_json(indent=2),
            }
        )
    except Exception as exc:  # noqa: BLE001 — report exists; don't trap in retries
        logger.warning(
            "guardrail: judge call failed attempt=%d — %s; passing through",
            retry_count,
            exc,
        )
        return {
            "guardrail_passed": True,
            "guardrail_feedback": None,
            "retry_count": retry_count,
        }

    if verdict.passed:
        logger.info("guardrail: PASS attempt=%d", retry_count)
        return {
            "guardrail_passed": True,
            "guardrail_feedback": None,
            "retry_count": retry_count,
        }

    logger.info(
        "guardrail: FAIL (judge) attempt=%d — %s", retry_count, verdict.feedback
    )
    return {
        "guardrail_passed": False,
        "guardrail_feedback": verdict.feedback,
        "retry_count": retry_count,
    }


def route_after_guardrail(state: PortfolioState) -> str:
    """Conditional edge: retry the synthesizer with feedback, or proceed."""
    if state.get("guardrail_passed"):
        return "memory_extractor"
    if state.get("retry_count", 0) >= _RETRY_BUDGET:
        logger.info("guardrail: retry budget exhausted — proceeding best-effort")
        return "memory_extractor"
    return "synthesizer"
