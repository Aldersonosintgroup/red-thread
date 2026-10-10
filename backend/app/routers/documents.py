import io
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import UPLOAD_DIR
from app.core.vault import VaultError, read_evidence, write_evidence
from app.core.db import get_db
from app.models.models import (
    Case, Document, DocumentStatus, Actor, ActorEdge, TimelineEvent,
)
from app.schemas import schemas
from app.services import dedup
from app.services.date_parsing import parse_document_date
from app.services.timeline_rules import event_type_for
from app.services.image_dedup import compute_phash, find_duplicate_documents, find_exact_duplicate_clusters
from app.services.queue_processor import enqueue_document
from app.services.recompute import recompute_case

router = APIRouter(prefix="/api/cases/{case_id}/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}


def _get_case(db: Session, case_id: str) -> Case:
    case = db.query(Case).filter(Case.id == case_id).first()
    if case is None:
        raise HTTPException(404, "Case not found")
    return case


@router.post("", response_model=schemas.DocumentOut, status_code=201)
async def upload_document(case_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    case = _get_case(db, case_id)

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Allowed: JPG, PNG, PDF.")

    case_dir = UPLOAD_DIR / case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    existing_count = db.query(Document).filter(Document.case_id == case_id).count()
    dest_path = case_dir / f"{existing_count:04d}_{file.filename}"

    data = await file.read()
    try:
        write_evidence(dest_path, data)  # encrypted when encryption is on
    except OSError as exc:
        raise HTTPException(500, f"Could not save uploaded file: {exc}") from exc

    document = Document(
        case_id=case_id,
        filename=file.filename or dest_path.name,
        filepath=str(dest_path),
        upload_order=existing_count,
        status=DocumentStatus.PENDING,
        phash=compute_phash(data) if ext != ".pdf" else None,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    # PDFs are rendered page by page and each page read separately; see
    # queue_processor._extract_document.
    enqueue_document(document.id)
    return document


@router.post("/manual", response_model=schemas.DocumentOut, status_code=201)
def create_manual_document(case_id: str, payload: schemas.ManualDocumentCreate, db: Session = Depends(get_db)):
    """A case entry with no scanned source — e.g. a phone call, a public
    record, or anything the investigator knows and wants on file without a
    photographable document. Opens straight into the same editable review
    form as an AI extraction, just starting blank."""
    _get_case(db, case_id)
    label = payload.label.strip()
    if not label:
        raise HTTPException(400, "Label is required")

    existing_count = db.query(Document).filter(Document.case_id == case_id).count()
    document = Document(
        case_id=case_id,
        filename=label,
        filepath="",
        upload_order=existing_count,
        status=DocumentStatus.EXTRACTED,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


@router.post("/reread-all")
def reread_all_documents(case_id: str, db: Session = Depends(get_db)):
    """Start the case's analysis over without touching the evidence: every
    uploaded file is kept and read again from scratch; everything derived
    from earlier readings (actors except the subject, network links,
    timeline, flags) is cleared. Manual entries keep their content but go
    back to unreviewed so they can be committed again. The subject profile,
    case notes and the watchlist are untouched."""
    case = _get_case(db, case_id)

    db.query(TimelineEvent).filter(TimelineEvent.case_id == case_id).delete(synchronize_session=False)
    db.query(ActorEdge).filter(ActorEdge.case_id == case_id).delete(synchronize_session=False)
    for actor in db.query(Actor).filter(Actor.case_id == case_id, Actor.is_subject.is_(False)).all():
        db.delete(actor)  # cascades to its mention rows

    documents = db.query(Document).filter(Document.case_id == case_id).order_by(Document.upload_order).all()
    to_read = []
    for document in documents:
        document.committed = False
        if document.has_file:
            document.status = DocumentStatus.PENDING
            document.raw_extraction = None
            document.edited_extraction = None
            document.doc_type = None
            document.error_message = None
            to_read.append(document.id)
        else:
            document.status = DocumentStatus.EXTRACTED  # manual entry: content kept, needs re-commit
    db.commit()
    db.expire_all()
    recompute_case(db, case)

    for document_id in to_read:
        enqueue_document(document_id)
    return {"queued": len(to_read), "manual_entries_reopened": len(documents) - len(to_read)}


@router.get("", response_model=list[schemas.DocumentOut])
def list_documents(case_id: str, db: Session = Depends(get_db)):
    _get_case(db, case_id)
    return (
        db.query(Document)
        .filter(Document.case_id == case_id)
        .order_by(Document.upload_order)
        .all()
    )


@router.get("/duplicate-suggestions", response_model=list[schemas.DuplicateDocumentSuggestion])
def get_duplicate_suggestions(case_id: str, db: Session = Depends(get_db)):
    """Visually near-identical uploaded images (perceptual hash), for human
    review — e.g. two photos of the same physical page. Never auto-deleted."""
    _get_case(db, case_id)
    return find_duplicate_documents(db, case_id)


@router.post("/clean-exact-duplicates")
def clean_exact_duplicates(case_id: str, db: Session = Depends(get_db)):
    """Bulk-deletes pixel-identical re-uploads, keeping the earliest copy in
    each cluster. Unlike the reviewed duplicate-suggestions flow, this needs
    no per-pair confirmation — distance=0 means the images are identical."""
    case = _get_case(db, case_id)
    clusters = find_exact_duplicate_clusters(db, case_id)

    deleted_count = 0
    for cluster in clusters:
        for document in cluster[1:]:  # keep cluster[0], the earliest upload
            if document.committed:
                _retract_document_contributions(db, case_id, document.id)
            if document.filepath:
                try:
                    Path(document.filepath).unlink(missing_ok=True)
                except OSError:
                    pass
            db.delete(document)
            deleted_count += 1

    db.commit()
    if deleted_count:
        recompute_case(db, case)
    return {"deleted_count": deleted_count}


@router.get("/{document_id}", response_model=schemas.DocumentOut)
def get_document(case_id: str, document_id: str, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id, Document.case_id == case_id).first()
    if document is None:
        raise HTTPException(404, "Document not found")
    return document


@router.get("/{document_id}/file")
def get_document_file(case_id: str, document_id: str, db: Session = Depends(get_db)):
    """Serves the original uploaded image for preview — so extraction can be
    visually checked against the actual document."""
    document = db.query(Document).filter(Document.id == document_id, Document.case_id == case_id).first()
    if document is None:
        raise HTTPException(404, "Document not found")
    if not document.has_file:
        raise HTTPException(404, "This entry has no attached file (manual entry)")
    if not Path(document.filepath).exists():
        raise HTTPException(404, "File is missing on disk")
    try:
        data = read_evidence(document.filepath)
    except VaultError as exc:
        raise HTTPException(500, str(exc)) from exc
    media_type = mimetypes.guess_type(document.filepath)[0] or "application/octet-stream"
    # Decrypted evidence must not be cached to disk by the webview.
    return Response(content=data, media_type=media_type, headers={"Cache-Control": "no-store"})


def _retract_document_contributions(db: Session, case_id: str, document_id: str) -> None:
    """Undo what commit_document added to the case graph: timeline events and
    actor-edges sourced from this document. Actors this document touched
    (created, or added an alias to) are deliberately left alone — they're
    shared across documents with no per-document mention audit trail, so
    there's no way to safely retract just this document's slice of an
    actor's identity. Clean those up manually via actor delete/merge if the
    retracted document was their only source."""
    db.query(TimelineEvent).filter(
        TimelineEvent.case_id == case_id, TimelineEvent.source_document_id == document_id
    ).delete(synchronize_session=False)
    db.query(ActorEdge).filter(
        ActorEdge.case_id == case_id, ActorEdge.document_id == document_id
    ).delete(synchronize_session=False)


@router.post("/{document_id}/commit", response_model=schemas.DocumentOut)
def commit_document(
    case_id: str, document_id: str, payload: schemas.DocumentCommitRequest, db: Session = Depends(get_db)
):
    """Commit the (possibly user-edited) extraction into the case: creates/merges
    actors, timeline events, and edges to the subject."""
    case = _get_case(db, case_id)
    document = db.query(Document).filter(Document.id == document_id, Document.case_id == case_id).first()
    if document is None:
        raise HTTPException(404, "Document not found")

    extraction = payload.edited_extraction
    document.edited_extraction = extraction.model_dump()
    document.committed = True
    document.status = DocumentStatus.REVIEWED

    subject_actor = None
    if case.subject:
        subject_actor = (
            db.query(Actor)
            .filter(Actor.case_id == case_id, Actor.is_subject.is_(True))
            .first()
        )
        if subject_actor is None:
            subject_actor = Actor(
                case_id=case_id, canonical_name=case.subject.full_name,
                is_subject=True, role="Subject",
            )
            db.add(subject_actor)
            db.flush()

    for entry in extraction.names:
        if not entry.name.strip():
            continue
        match = dedup.find_matching_actor(db, case_id, entry.name)
        if match:
            dedup.merge_alias_into_actor(db, match, entry.name)
            actor = match
        else:
            actor = Actor(case_id=case_id, canonical_name=entry.name.strip(), role=entry.role)
            db.add(actor)
            db.flush()

        if entry.role and not actor.role:
            actor.role = entry.role

        watchlist_entity, score = dedup.match_watchlist(db, actor.canonical_name)
        if watchlist_entity:
            actor.watchlist_match_id = watchlist_entity.id
            actor.watchlist_match_score = score

        if subject_actor and actor.id != subject_actor.id:
            exists = (
                db.query(ActorEdge)
                .filter(
                    ActorEdge.case_id == case_id,
                    ActorEdge.source_actor_id == subject_actor.id,
                    ActorEdge.target_actor_id == actor.id,
                )
                .first()
            )
            if not exists:
                db.add(ActorEdge(
                    case_id=case_id, source_actor_id=subject_actor.id,
                    target_actor_id=actor.id, relationship_type="case_connection",
                    document_id=document.id,
                ))

    for d in extraction.dates:
        parsed = parse_document_date(d.get("date")).value
        label = (d.get("label") or "other").lower()
        event_type = event_type_for(label)
        description = f"{label}: {d.get('date') or 'date not entered'}"
        if d.get("raw"):
            description += f" (as written: \"{d['raw']}\")"
        if d.get("page"):
            description += f", p. {d['page']}"
        db.add(TimelineEvent(
            case_id=case_id, event_type=event_type, event_date=parsed,
            description=description, source_document_id=document.id,
        ))

    db.commit()
    recompute_case(db, case)
    db.refresh(document)
    return document


@router.post("/{document_id}/rotate", response_model=schemas.DocumentOut)
def rotate_document(case_id: str, document_id: str, degrees: int, db: Session = Depends(get_db)):
    """Physically rotates the source image (not just a display transform) so
    a sideways-photographed page is corrected before the AI reads it. Only
    allowed pre-commit — committed documents must be reopened via /uncommit
    first, since rotating after the fact would invalidate the extraction
    that was already reviewed against the old orientation."""
    _get_case(db, case_id)
    document = db.query(Document).filter(Document.id == document_id, Document.case_id == case_id).first()
    if document is None:
        raise HTTPException(404, "Document not found")
    if document.committed:
        raise HTTPException(400, "Reopen the document (Edit) before rotating it")
    if not document.has_file:
        raise HTTPException(400, "This entry has no attached file to rotate")
    if Path(document.filepath).suffix.lower() == ".pdf":
        raise HTTPException(400, "PDFs can't be rotated here. Rotate the pages in a PDF editor and re-upload.")
    if degrees % 90 != 0:
        raise HTTPException(400, "Rotation must be a multiple of 90 degrees")

    try:
        with Image.open(io.BytesIO(read_evidence(document.filepath))) as img:
            image_format = img.format or "PNG"
            rotated = img.rotate(-degrees, expand=True)  # PIL rotates counter-clockwise; negate for clockwise
            buffer = io.BytesIO()
            save_options = {"quality": 95} if image_format == "JPEG" else {}
            rotated.save(buffer, format=image_format, **save_options)
        rotated_bytes = buffer.getvalue()
        write_evidence(document.filepath, rotated_bytes)
    except (OSError, VaultError) as exc:
        raise HTTPException(500, f"Could not rotate image: {exc}") from exc

    document.rotation = (document.rotation + degrees) % 360
    document.phash = compute_phash(rotated_bytes)
    # The image changed — any prior extraction was read against the old
    # orientation, so re-run it rather than leave a stale/misleading result.
    document.status = DocumentStatus.PENDING
    document.raw_extraction = None
    document.edited_extraction = None
    db.commit()
    db.refresh(document)
    enqueue_document(document.id)
    return document


@router.post("/{document_id}/reextract", response_model=schemas.DocumentOut)
def reextract_document(case_id: str, document_id: str, db: Session = Depends(get_db)):
    """Run AI extraction again — after a provider outage, a settings change,
    or for PDFs uploaded before page-by-page extraction existed. Replaces the
    unreviewed extraction, so it's refused once the document is committed."""
    _get_case(db, case_id)
    document = db.query(Document).filter(Document.id == document_id, Document.case_id == case_id).first()
    if document is None:
        raise HTTPException(404, "Document not found")
    if document.committed:
        raise HTTPException(400, "Reopen the document (Edit) before re-running extraction")
    if not document.has_file:
        raise HTTPException(400, "Manual entries have no file to extract from")
    if document.status in (DocumentStatus.PENDING, DocumentStatus.PROCESSING):
        raise HTTPException(409, "Extraction is already queued for this document")

    document.status = DocumentStatus.PENDING
    document.error_message = None
    document.raw_extraction = None
    document.edited_extraction = None
    db.commit()
    db.refresh(document)
    enqueue_document(document.id)
    return document


@router.post("/{document_id}/uncommit", response_model=schemas.DocumentOut)
def uncommit_document(case_id: str, document_id: str, db: Session = Depends(get_db)):
    """Reopen a committed document for editing: retracts its timeline/edge
    contributions and returns it to the review panel. The extraction fields
    (as last edited) are kept, ready to correct and re-commit."""
    case = _get_case(db, case_id)
    document = db.query(Document).filter(Document.id == document_id, Document.case_id == case_id).first()
    if document is None:
        raise HTTPException(404, "Document not found")
    if not document.committed:
        raise HTTPException(400, "Document is not committed")

    _retract_document_contributions(db, case_id, document_id)
    document.committed = False
    document.status = DocumentStatus.EXTRACTED

    db.commit()
    recompute_case(db, case)
    db.refresh(document)
    return document


@router.delete("/{document_id}", status_code=204)
def delete_document(case_id: str, document_id: str, db: Session = Depends(get_db)):
    case = _get_case(db, case_id)
    document = db.query(Document).filter(Document.id == document_id, Document.case_id == case_id).first()
    if document is None:
        raise HTTPException(404, "Document not found")

    if document.committed:
        _retract_document_contributions(db, case_id, document_id)

    if document.filepath:
        try:
            Path(document.filepath).unlink(missing_ok=True)
        except OSError:
            pass  # file already gone or locked — don't block removing the record

    db.delete(document)
    db.commit()
    recompute_case(db, case)
    return None
