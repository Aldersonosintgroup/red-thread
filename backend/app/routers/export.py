import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import Case, CaseScore
from app.services.json_export import build_case_json, _default
from app.services.pdf_export import build_case_pdf
from app.services.recompute import recompute_case

router = APIRouter(prefix="/api/cases/{case_id}/export", tags=["export"])


def _get_case_with_score(db: Session, case_id: str) -> tuple[Case, dict]:
    case = db.query(Case).filter(Case.id == case_id).first()
    if case is None:
        raise HTTPException(404, "Case not found")
    score_row = db.query(CaseScore).filter(CaseScore.case_id == case_id).first()
    if score_row is None:
        recompute_case(db, case)
        score_row = db.query(CaseScore).filter(CaseScore.case_id == case_id).first()
    score = {
        "timeline_score": score_row.timeline_score,
        "entity_match_score": score_row.entity_match_score,
        "financial_score": score_row.financial_score,
        "contradiction_score": score_row.contradiction_score,
        "legal_score": score_row.legal_score,
        "total_score": score_row.total_score,
    }
    return case, score


@router.get("/pdf")
def export_pdf(case_id: str, db: Session = Depends(get_db)):
    case, score = _get_case_with_score(db, case_id)
    try:
        pdf_bytes = build_case_pdf(case, score)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"PDF generation failed: {exc}") from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{case.case_number}_report.pdf"'},
    )


@router.get("/json")
def export_json(case_id: str, db: Session = Depends(get_db)):
    case, score = _get_case_with_score(db, case_id)
    data = build_case_json(case, score)
    body = json.dumps(data, default=_default, indent=2)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{case.case_number}_export.json"'},
    )
