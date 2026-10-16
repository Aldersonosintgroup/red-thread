from itertools import combinations, product
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import Actor, CrossCaseDecision
from app.services import correlation

router = APIRouter(prefix="/api/recurring-actors", tags=["recurring-actors"])


class DecisionRequest(BaseModel):
    actor_ids: list[str]
    # With `against`, the call applies to each actor_ids x against pair
    # ("this one is not those"); without it, to every pair within actor_ids.
    against: Optional[list[str]] = None
    decision: Literal["confirmed", "rejected", "clear"]


@router.get("")
def list_recurring_actors(db: Session = Depends(get_db)):
    return correlation.find_recurring_actors(db)


@router.get("/case/{case_id}")
def recurring_in_case(case_id: str, db: Session = Depends(get_db)):
    """For one case: which of its actors also appear in other cases."""
    out = {}
    for cluster in correlation.find_recurring_actors(db):
        others = len({m["case_id"] for m in cluster["members"] if m["case_id"] != case_id})
        for m in cluster["members"]:
            if m["case_id"] == case_id:
                out[m["actor_id"]] = {"other_cases": others, "tier": cluster["tier"]}
    return out


@router.post("/decisions")
def record_decision(payload: DecisionRequest, db: Session = Depends(get_db)):
    ids = set(payload.actor_ids) | set(payload.against or [])
    actors = {a.id: a for a in db.query(Actor).filter(Actor.id.in_(ids)).all()}
    if len(actors) != len(ids):
        raise HTTPException(404, "Actor not found")
    pairs = (product(payload.actor_ids, payload.against) if payload.against is not None
             else combinations(payload.actor_ids, 2))
    decision = None if payload.decision == "clear" else payload.decision
    changed = 0
    for a, b in pairs:
        if a != b and actors[a].case_id != actors[b].case_id:
            correlation.set_decision(db, actors[a], actors[b], decision)
            changed += 1
    db.commit()
    return {"pairs": changed}


@router.get("/separated")
def list_separated(db: Session = Depends(get_db)):
    return correlation.separated_pairs(db)


@router.delete("/separated/{decision_id}", status_code=204)
def undo_separation(decision_id: str, db: Session = Depends(get_db)):
    row = db.query(CrossCaseDecision).filter(CrossCaseDecision.id == decision_id).first()
    if row is None:
        raise HTTPException(404, "Decision not found")
    db.delete(row)
    db.commit()
    return None
