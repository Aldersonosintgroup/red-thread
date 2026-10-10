from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import Case, Subject
from app.schemas import schemas

router = APIRouter(prefix="/api/cases", tags=["cases"])


@router.get("", response_model=list[schemas.CaseSummary])
def list_cases(db: Session = Depends(get_db)):
    return db.query(Case).order_by(Case.updated_at.desc()).all()


@router.post("", response_model=schemas.CaseDetail, status_code=201)
def create_case(payload: schemas.CaseCreate, db: Session = Depends(get_db)):
    existing = db.query(Case).filter(Case.case_number == payload.case_number).first()
    if existing:
        raise HTTPException(409, f"Case number '{payload.case_number}' already exists")

    case = Case(case_number=payload.case_number, title=payload.title)
    db.add(case)
    db.flush()

    subject = Subject(
        case_id=case.id,
        full_name=payload.subject.full_name,
        aliases=payload.subject.aliases,
        date_of_birth=payload.subject.date_of_birth,
        birth_place=payload.subject.birth_place,
        notes=payload.subject.notes,
    )
    db.add(subject)
    db.commit()
    db.refresh(case)
    return case


@router.get("/{case_id}", response_model=schemas.CaseDetail)
def get_case(case_id: str, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if case is None:
        raise HTTPException(404, "Case not found")
    return case


@router.patch("/{case_id}", response_model=schemas.CaseDetail)
def update_case(case_id: str, payload: schemas.CaseUpdate, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if case is None:
        raise HTTPException(404, "Case not found")
    if payload.notes is not None:
        case.notes = payload.notes
    db.commit()
    db.refresh(case)
    return case


@router.delete("/{case_id}", status_code=204)
def delete_case(case_id: str, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if case is None:
        raise HTTPException(404, "Case not found")
    db.delete(case)
    db.commit()
    return None
