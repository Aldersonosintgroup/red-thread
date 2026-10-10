"""Testimony and verified findings: evidence that isn't a scanned document.

Each change re-runs the case's flags and score, since a statement can raise
an investigator flag."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import Actor, Case, Document, Statement
from app.schemas import schemas
from app.services.recompute import recompute_case

router = APIRouter(prefix="/api/cases/{case_id}/statements", tags=["statements"])


def _get_case(db: Session, case_id: str) -> Case:
    case = db.query(Case).filter(Case.id == case_id).first()
    if case is None:
        raise HTTPException(404, "Case not found")
    return case


def _clean(db: Session, case_id: str, payload: schemas.StatementIn) -> dict:
    """Drop links to documents or people that aren't in this case."""
    data = payload.model_dump()
    for field in ("statement", "source_name", "source_relationship", "method"):
        if isinstance(data[field], str):
            data[field] = data[field].strip() or None
    if not data["statement"]:
        raise HTTPException(422, "The statement can't be empty")
    doc_ids = {d for (d,) in db.query(Document.id).filter(Document.case_id == case_id)}
    actor_ids = {a for (a,) in db.query(Actor.id).filter(Actor.case_id == case_id)}
    data["related_document_ids"] = [d for d in dict.fromkeys(data["related_document_ids"]) if d in doc_ids]
    data["related_actor_ids"] = [a for a in dict.fromkeys(data["related_actor_ids"]) if a in actor_ids]
    if data["kind"] == "finding":
        data["basis"] = None  # first/second-hand applies to testimony only
    return data


@router.get("", response_model=list[schemas.StatementOut])
def list_statements(case_id: str, db: Session = Depends(get_db)):
    return _get_case(db, case_id).statements


@router.post("", response_model=schemas.StatementOut, status_code=201)
def create_statement(case_id: str, payload: schemas.StatementIn, db: Session = Depends(get_db)):
    case = _get_case(db, case_id)
    statement = Statement(case_id=case_id, **_clean(db, case_id, payload))
    db.add(statement)
    db.commit()
    recompute_case(db, case)
    db.refresh(statement)
    return statement


@router.put("/{statement_id}", response_model=schemas.StatementOut)
def update_statement(case_id: str, statement_id: str, payload: schemas.StatementIn, db: Session = Depends(get_db)):
    case = _get_case(db, case_id)
    statement = db.query(Statement).filter(Statement.id == statement_id, Statement.case_id == case_id).first()
    if statement is None:
        raise HTTPException(404, "Statement not found")
    for field, value in _clean(db, case_id, payload).items():
        setattr(statement, field, value)
    db.commit()
    recompute_case(db, case)
    db.refresh(statement)
    return statement


@router.delete("/{statement_id}", status_code=204)
def delete_statement(case_id: str, statement_id: str, db: Session = Depends(get_db)):
    case = _get_case(db, case_id)
    statement = db.query(Statement).filter(Statement.id == statement_id, Statement.case_id == case_id).first()
    if statement is None:
        raise HTTPException(404, "Statement not found")
    db.delete(statement)
    db.commit()
    recompute_case(db, case)
