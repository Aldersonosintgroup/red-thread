from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import Case, CaseScore, Flag, TimelineEvent
from app.schemas import schemas
from app.services.discrepancy import build_discrepancy_groups
from app.services.recompute import recompute_case
from app.services.timeline_rules import apply_cleanup, plan_cleanup

router = APIRouter(prefix="/api/cases/{case_id}", tags=["scoring"])


def _get_case(db: Session, case_id: str) -> Case:
    case = db.query(Case).filter(Case.id == case_id).first()
    if case is None:
        raise HTTPException(404, "Case not found")
    return case


@router.get("/score", response_model=schemas.CaseScoreOut)
def get_score(case_id: str, db: Session = Depends(get_db)):
    case = _get_case(db, case_id)
    score_row = db.query(CaseScore).filter(CaseScore.case_id == case_id).first()
    if score_row is None:
        recompute_case(db, case)
        score_row = db.query(CaseScore).filter(CaseScore.case_id == case_id).first()
    return score_row


@router.post("/score/recompute", response_model=schemas.CaseScoreOut)
def recompute_score(case_id: str, db: Session = Depends(get_db)):
    case = _get_case(db, case_id)
    recompute_case(db, case)
    return db.query(CaseScore).filter(CaseScore.case_id == case_id).first()


@router.get("/flags", response_model=list[schemas.FlagOut])
def get_flags(case_id: str, db: Session = Depends(get_db)):
    _get_case(db, case_id)
    return db.query(Flag).filter(Flag.case_id == case_id).all()


@router.get("/discrepancies", response_model=list[schemas.DiscrepancyGroup])
def get_discrepancies(case_id: str, db: Session = Depends(get_db)):
    case = _get_case(db, case_id)
    return build_discrepancy_groups(case)


@router.get("/timeline/cleanup")
def preview_timeline_cleanup(case_id: str, db: Session = Depends(get_db)):
    """What the cleanup would change, for the investigator to review first."""
    return plan_cleanup(_get_case(db, case_id))


@router.post("/timeline/cleanup")
def run_timeline_cleanup(case_id: str, payload: schemas.TimelineCleanupRequest, db: Session = Depends(get_db)):
    case = _get_case(db, case_id)
    result = apply_cleanup(db, case, redate=payload.redate, relabel=payload.relabel)
    recompute_case(db, case)
    return result


@router.post("/timeline/exclude")
def set_timeline_excluded(case_id: str, payload: schemas.TimelineExcludeRequest, db: Session = Depends(get_db)):
    case = _get_case(db, case_id)
    changed = (
        db.query(TimelineEvent)
        .filter(TimelineEvent.case_id == case_id, TimelineEvent.id.in_(payload.event_ids))
        .update({TimelineEvent.excluded: payload.excluded}, synchronize_session=False)
    )
    db.commit()
    db.expire_all()  # the bulk update bypassed the session's cached events
    recompute_case(db, case)
    return {"changed": changed}


@router.get("/timeline", response_model=list[schemas.TimelineEventOut])
def get_timeline(case_id: str, db: Session = Depends(get_db)):
    _get_case(db, case_id)
    return (
        db.query(TimelineEvent)
        .filter(TimelineEvent.case_id == case_id)
        .order_by(TimelineEvent.event_date)
        .all()
    )
