"""Read endpoints for persisted report history (V5)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import Report

router = APIRouter()


@router.get(
    "/api/reports/history/{user_id}",
    summary="List a user's past reports (newest first)",
)
def list_reports(user_id: str, db: Session = Depends(get_db)) -> list[dict]:
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
