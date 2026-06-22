"""Read endpoints for persisted report history (V5), plus a grounded report
Q&A token stream (V14)."""

import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_openai import ChatOpenAI
from sqlalchemy.orm import Session

from app.api.deps import require_owner, require_user
from app.core.config import get_settings
from app.db.base import get_db
from app.db.models import Report
from app.schemas.report import AskRequest

router = APIRouter()


def _format_sse(event_type: str, data: dict) -> str:
    """One SSE message: an event line + a JSON data line + blank terminator."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# Grounded, low-temperature model for report Q&A. Streamed token-by-token — the
# deliberate counter-case to generate.py's no-token rule (which holds because
# structured output emits one JSON object; free prose streams fine).
_ask_llm = ChatOpenAI(model=get_settings().openai_model_synthesizer, temperature=0.1)

_ASK_SYSTEM = (
    "You are PortfolioPilot, answering a follow-up question about ONE specific "
    "portfolio report shown below. Answer ONLY from that report's contents. If "
    "the answer is not in the report, say so plainly. Never invent prices, news, "
    "holdings, sentiment, or recommendations that are not in the report. Keep the "
    "answer concise and educational — this is not financial advice."
)


@router.get(
    "/api/reports/history/{user_id}",
    summary="List a user's past reports (newest first)",
)
def list_reports(
    user_id: str,
    db: Session = Depends(get_db),
    _owner: str = Depends(require_owner),
) -> list[dict]:
    """Lightweight summaries (no full raw_result), newest first."""
    rows = (
        db.query(Report)
        .filter(Report.user_id == user_id)
        .order_by(Report.generated_at.desc())
        .all()
    )
    out = []
    for r in rows:
        val = (r.raw_result or {}).get("portfolio_valuation", {})
        out.append(
            {
                "report_id": r.id,
                "generated_at": r.generated_at.isoformat(),
                "confidence_flag": r.confidence_flag,
                "total_usd": val.get("total_usd"),
                "change_24h_percent": val.get("change_24h_percent"),
            }
        )
    return out


@router.get(
    "/api/reports/series/{user_id}",
    summary="Portfolio value over time, oldest first (V12a)",
)
def report_series(
    user_id: str,
    db: Session = Depends(get_db),
    _owner: str = Depends(require_owner),
) -> list[dict]:
    """Time-ordered value points for the history trend chart.

    Derived from each archived report's portfolio_valuation — no graph run, no
    LLM (pattern #7: read-side history lives at the boundary). Ordered oldest
    first so a line chart reads left-to-right; points with no total are skipped.
    An unknown user simply yields [].
    """
    rows = (
        db.query(Report)
        .filter(Report.user_id == user_id)
        .order_by(Report.generated_at.asc())
        .all()
    )
    series = []
    for r in rows:
        val = (r.raw_result or {}).get("portfolio_valuation", {})
        total = val.get("total_usd")
        if total is None:
            continue
        series.append(
            {
                "generated_at": r.generated_at.isoformat(),
                "total_usd": total,
                "change_24h_percent": val.get("change_24h_percent"),
            }
        )
    return series


@router.get("/api/reports/{report_id}", summary="Fetch one report verbatim")
def get_report(report_id: str, db: Session = Depends(get_db)) -> dict:
    """Replay a stored report from raw_result; 404 if unknown."""
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No report found with id '{report_id}'.",
        )
    return {
        "report_id": r.id,
        "user_id": r.user_id,
        "generated_at": r.generated_at.isoformat(),
        "confidence_flag": r.confidence_flag,
        "report": r.raw_result,
    }


async def _ask_stream(report: dict, question: str):
    """Stream the model's grounded answer as SSE token events, then done."""
    human = (
        "Here is the report (JSON):\n"
        f"{json.dumps(report, indent=2)}\n\n"
        f"Question: {question}"
    )
    try:
        async for chunk in _ask_llm.astream(
            [("system", _ASK_SYSTEM), ("human", human)]
        ):
            text = chunk.content
            if text:
                yield _format_sse("token", {"text": text})
    except Exception as exc:  # noqa: BLE001 — surface, don't swallow
        yield _format_sse("error", {"code": "ASK_ERROR", "message": str(exc)})
        return
    yield _format_sse("done", {})


@router.post(
    "/api/reports/{report_id}/ask",
    summary="Ask a grounded question about one archived report (SSE token stream)",
)
async def ask_report(
    report_id: str,
    payload: AskRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(require_user),
) -> StreamingResponse:
    """Answer a follow-up grounded strictly in one archived report (V14).

    No graph re-run: load raw_result, build a grounded prompt, and stream the
    model's reply token-by-token. POST (not GET) because the question rides in
    the body, so the client consumes it with fetch()+reader, not EventSource.

    Owner-only (V9): asking costs an LLM call, so unlike the read-only
    capability URL it requires the report's owner.
    """
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No report found with id '{report_id}'.",
        )
    if r.user_id != current_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only ask about your own report.",
        )
    return StreamingResponse(
        _ask_stream(r.raw_result, payload.question),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
