"""Recomputes a case's discrepancies, flags, and score together. Called after
any case-mutating action (document commit, actor merge/edit)."""
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.models import Case, CaseScore
from app.services.discrepancy import build_discrepancy_groups
from app.services.flagging import run_all_flag_evaluations
from app.services.scoring_engine import compute_case_score


def recompute_case(db: Session, case: Case) -> dict:
    db.refresh(case)
    discrepancy_groups = build_discrepancy_groups(case)
    run_all_flag_evaluations(db, case, discrepancy_groups)

    db.refresh(case)
    score_values = compute_case_score(case)

    score_row = db.query(CaseScore).filter(CaseScore.case_id == case.id).first()
    if score_row is None:
        score_row = CaseScore(case_id=case.id, **score_values)
        db.add(score_row)
    else:
        for key, value in score_values.items():
            setattr(score_row, key, value)
        score_row.computed_at = datetime.utcnow()
    db.commit()
    return score_values
