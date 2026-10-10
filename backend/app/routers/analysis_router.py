from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import Case, CaseAnalysis
from app.services.case_analysis import AnalysisError, generate_analysis

router = APIRouter(prefix="/api/cases/{case_id}/analyses", tags=["analysis"])


class AnalysisRequest(BaseModel):
    language: str = "en"


def _out(a: CaseAnalysis, include_dossier: bool = False) -> dict:
    body = {
        "id": a.id, "created_at": a.created_at.isoformat() + "Z", "language": a.language, "model": a.model,
        "input_hash": a.input_hash, "document_count": a.document_count, "report": a.report,
        "citation_check": a.citation_check, "disclaimer": a.disclaimer,
    }
    if include_dossier:
        body["dossier"] = a.dossier
    return body


def _get_case(db: Session, case_id: str) -> Case:
    case = db.query(Case).filter(Case.id == case_id).first()
    if case is None:
        raise HTTPException(404, "Case not found")
    return case


@router.get("")
def list_analyses(case_id: str, db: Session = Depends(get_db)):
    _get_case(db, case_id)
    rows = db.query(CaseAnalysis).filter(CaseAnalysis.case_id == case_id).order_by(CaseAnalysis.created_at.desc()).all()
    return [_out(a) for a in rows]


@router.post("")
async def create_analysis(case_id: str, payload: AnalysisRequest, db: Session = Depends(get_db)):
    case = _get_case(db, case_id)
    try:
        result = await generate_analysis(case, payload.language)
    except AnalysisError as exc:
        raise HTTPException(400, str(exc)) from exc
    analysis = CaseAnalysis(case_id=case_id, **result)
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return _out(analysis)


@router.get("/{analysis_id}/record")
def get_analysis_record(case_id: str, analysis_id: str, db: Session = Depends(get_db)):
    """The exact case record the analysis was based on."""
    a = db.query(CaseAnalysis).filter(CaseAnalysis.id == analysis_id, CaseAnalysis.case_id == case_id).first()
    if a is None:
        raise HTTPException(404, "Analysis not found")
    return _out(a, include_dossier=True)


@router.delete("/{analysis_id}", status_code=204)
def delete_analysis(case_id: str, analysis_id: str, db: Session = Depends(get_db)):
    a = db.query(CaseAnalysis).filter(CaseAnalysis.id == analysis_id, CaseAnalysis.case_id == case_id).first()
    if a is None:
        raise HTTPException(404, "Analysis not found")
    db.delete(a)
    db.commit()
