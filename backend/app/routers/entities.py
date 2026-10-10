import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.models.models import Case, Actor, ActorEdge, Document, Flag, WatchlistCategory, WatchlistEntity
from app.schemas import schemas
from app.services import dedup
from app.services.recompute import recompute_case

router = APIRouter(tags=["entities"])


def _get_case(db: Session, case_id: str) -> Case:
    case = db.query(Case).filter(Case.id == case_id).first()
    if case is None:
        raise HTTPException(404, "Case not found")
    return case


@router.get("/api/cases/{case_id}/actors", response_model=list[schemas.ActorOut])
def list_actors(case_id: str, db: Session = Depends(get_db)):
    _get_case(db, case_id)
    return db.query(Actor).filter(Actor.case_id == case_id).all()


@router.patch("/api/cases/{case_id}/actors/{actor_id}", response_model=schemas.ActorOut)
def update_actor(case_id: str, actor_id: str, payload: schemas.ActorUpdate, db: Session = Depends(get_db)):
    case = _get_case(db, case_id)
    actor = db.query(Actor).filter(Actor.id == actor_id, Actor.case_id == case_id).first()
    if actor is None:
        raise HTTPException(404, "Actor not found")

    if payload.canonical_name is not None:
        actor.canonical_name = payload.canonical_name
        watchlist_entity, score = dedup.match_watchlist(db, actor.canonical_name)
        actor.watchlist_match_id = watchlist_entity.id if watchlist_entity else None
        actor.watchlist_match_score = score if watchlist_entity else None
    if payload.role is not None:
        actor.role = payload.role
    if payload.notes is not None:
        actor.notes = payload.notes
    if payload.custom_color is not None:
        actor.custom_color = payload.custom_color or None

    db.commit()
    recompute_case(db, case)
    db.refresh(actor)
    return actor


@router.delete("/api/cases/{case_id}/actors/{actor_id}", status_code=204)
def delete_actor(case_id: str, actor_id: str, db: Session = Depends(get_db)):
    case = _get_case(db, case_id)
    actor = db.query(Actor).filter(Actor.id == actor_id, Actor.case_id == case_id).first()
    if actor is None:
        raise HTTPException(404, "Actor not found")
    if actor.is_subject:
        raise HTTPException(400, "Cannot delete the case subject")

    db.query(ActorEdge).filter(
        ActorEdge.case_id == case_id,
        (ActorEdge.source_actor_id == actor_id) | (ActorEdge.target_actor_id == actor_id),
    ).delete(synchronize_session=False)

    db.delete(actor)  # cascades to ActorMention rows
    db.commit()
    recompute_case(db, case)
    return None


@router.get("/api/cases/{case_id}/actors/{actor_id}/details")
def get_actor_details(case_id: str, actor_id: str, db: Session = Depends(get_db)):
    """Everything the reviewed record says about one actor: every committed
    document naming them (under any spelling, with their role there and the
    page), and the flags that concern them."""
    _get_case(db, case_id)
    actor = db.query(Actor).filter(Actor.id == actor_id, Actor.case_id == case_id).first()
    if actor is None:
        raise HTTPException(404, "Actor not found")

    known = [dedup.normalize_name(n) for n in [actor.canonical_name, *(actor.aliases or [])] if n]
    appearances = []
    documents = (
        db.query(Document)
        .filter(Document.case_id == case_id, Document.committed.is_(True))
        .order_by(Document.upload_order)
        .all()
    )
    for document in documents:
        extraction = document.edited_extraction or document.raw_extraction or {}
        for entry in extraction.get("names", []):
            name = entry.get("name") or ""
            normalized = dedup.normalize_name(name)
            if normalized and any(fuzz.token_set_ratio(normalized, k) >= settings.dedup_fuzzy_threshold for k in known):
                appearances.append({
                    "document_id": document.id, "filename": document.filename, "doc_type": extraction.get("doc_type"),
                    "name_as_written": name, "role": entry.get("role"), "page": entry.get("page"),
                })

    flags = db.query(Flag).filter(Flag.case_id == case_id, Flag.related_actor_id == actor_id).all()
    watch = actor.watchlist_match
    return {
        "actor": schemas.ActorOut.model_validate(actor),
        "watchlist": {"name": watch.name, "category": watch.category.value, "entity_type": watch.entity_type,
                      "notes": watch.notes, "score": actor.watchlist_match_score} if watch else None,
        "appearances": appearances,
        "flags": [schemas.FlagOut.model_validate(f) for f in flags],
    }


@router.get("/api/cases/{case_id}/actors/merge-suggestions", response_model=list[schemas.MergeSuggestion])
def get_merge_suggestions(case_id: str, db: Session = Depends(get_db)):
    """Candidate duplicate actor pairs for human review — never auto-applied."""
    _get_case(db, case_id)
    return dedup.find_merge_suggestions(db, case_id)


@router.post("/api/cases/{case_id}/actors/merge", response_model=schemas.ActorOut)
def merge_actors(case_id: str, payload: schemas.ActorMergeRequest, db: Session = Depends(get_db)):
    """Merge source actor into target actor: aliases combined, mentions/edges
    repointed, source deleted."""
    case = _get_case(db, case_id)
    source = db.query(Actor).filter(Actor.id == payload.source_actor_id, Actor.case_id == case_id).first()
    target = db.query(Actor).filter(Actor.id == payload.target_actor_id, Actor.case_id == case_id).first()
    if source is None or target is None:
        raise HTTPException(404, "Actor not found")
    if source.id == target.id:
        raise HTTPException(400, "Cannot merge an actor into itself")

    merged_aliases = set(target.aliases or []) | set(source.aliases or []) | {source.canonical_name}
    merged_aliases.discard(target.canonical_name)
    target.aliases = list(merged_aliases)
    if not target.role and source.role:
        target.role = source.role

    for mention in source.mentions:
        mention.actor_id = target.id

    for edge in db.query(ActorEdge).filter(ActorEdge.case_id == case_id).all():
        if edge.source_actor_id == source.id:
            edge.source_actor_id = target.id
        if edge.target_actor_id == source.id:
            edge.target_actor_id = target.id

    db.delete(source)
    db.commit()
    recompute_case(db, case)
    db.refresh(target)
    return target


@router.get("/api/cases/{case_id}/edges", response_model=list[schemas.EdgeOut])
def list_edges(case_id: str, db: Session = Depends(get_db)):
    _get_case(db, case_id)
    return db.query(ActorEdge).filter(ActorEdge.case_id == case_id).all()


# ---------- Watchlist (private, local, user-editable BOLO list) ----------

watchlist_router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@watchlist_router.get("", response_model=list[schemas.WatchlistEntityOut])
def list_watchlist(db: Session = Depends(get_db)):
    return db.query(WatchlistEntity).all()


@watchlist_router.post("", response_model=schemas.WatchlistEntityOut, status_code=201)
def create_watchlist_entity(payload: schemas.WatchlistEntityCreate, db: Session = Depends(get_db)):
    entity = WatchlistEntity(**payload.model_dump())
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


@watchlist_router.delete("/{entity_id}", status_code=204)
def delete_watchlist_entity(entity_id: str, db: Session = Depends(get_db)):
    entity = db.query(WatchlistEntity).filter(WatchlistEntity.id == entity_id).first()
    if entity is None:
        raise HTTPException(404, "Watchlist entity not found")
    db.delete(entity)
    db.commit()
    return None


WATCHLIST_EXPORT_FORMAT = "redthread-watchlist"


@watchlist_router.get("/export")
def export_watchlist(db: Session = Depends(get_db)):
    """The whole watchlist as a portable JSON file, so an investigator can
    move their own list between installs. Never bundled with the app."""
    entities = db.query(WatchlistEntity).order_by(WatchlistEntity.name).all()
    body = {
        "format": WATCHLIST_EXPORT_FORMAT,
        "version": 1,
        "entities": [
            {"name": e.name, "aliases": e.aliases or [], "category": e.category.value,
             "entity_type": e.entity_type, "notes": e.notes}
            for e in entities
        ],
    }
    return JSONResponse(body, headers={"Content-Disposition": 'attachment; filename="redthread_watchlist.json"'})


@watchlist_router.post("/import")
async def import_watchlist(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Merge a watchlist export into this install. Entries whose name
    already exists are skipped, never overwritten. Every case's actors are
    then re-matched so new entries flag existing cases too."""
    try:
        body = json.loads(await file.read())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "Not a valid watchlist file (not JSON)") from exc
    if not isinstance(body, dict) or body.get("format") != WATCHLIST_EXPORT_FORMAT:
        raise HTTPException(400, "Not a Red Thread watchlist export")

    existing = {dedup.normalize_name(e.name) for e in db.query(WatchlistEntity).all()}
    added, skipped, invalid = 0, 0, 0
    for item in body.get("entities", []):
        try:
            payload = schemas.WatchlistEntityCreate(**item)
            category = WatchlistCategory(payload.category)
        except (TypeError, ValueError):
            invalid += 1
            continue
        key = dedup.normalize_name(payload.name)
        if not key or key in existing:
            skipped += 1
            continue
        db.add(WatchlistEntity(name=payload.name, aliases=payload.aliases, category=category,
                               entity_type=payload.entity_type, notes=payload.notes))
        existing.add(key)
        added += 1
    db.commit()

    if added:
        for actor in db.query(Actor).all():
            entity, score = dedup.match_watchlist(db, actor.canonical_name)
            actor.watchlist_match_id = entity.id if entity else None
            actor.watchlist_match_score = score if entity else None
        db.commit()
        for case in db.query(Case).all():
            recompute_case(db, case)
    return {"added": added, "skipped_existing": skipped, "invalid": invalid}
