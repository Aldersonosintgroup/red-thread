"""Duplicate-image detection for uploaded documents: perceptual hashing
catches 'two photos of the same physical page' regardless of what the AI
extracted from either one — useful since extraction quality varies, but the
underlying image similarity doesn't."""
import io
from pathlib import Path

import imagehash
from PIL import Image
from sqlalchemy.orm import Session

from app.core.vault import read_evidence
from app.models.models import Document

# Hamming distance between 64-bit perceptual hashes. 0 = identical, <=8 is a
# well-established "almost certainly the same image" threshold for phash;
# human review still confirms before anything is deleted (except the
# distance=0 bulk-cleanup path below, which is unambiguous by construction).
DUPLICATE_MAX_DISTANCE = 8
MAX_SUGGESTIONS = 300


def compute_phash(source: str | bytes) -> str | None:
    """Perceptual hash of an evidence image, given its path or its bytes."""
    try:
        data = source if isinstance(source, bytes) else read_evidence(source)
        with Image.open(io.BytesIO(data)) as img:
            return str(imagehash.phash(img))
    except Exception:  # noqa: BLE001 - a bad/corrupt image must never block upload
        return None


def backfill_missing_phashes(db: Session) -> None:
    """One-time catch-up for documents uploaded before phash computation
    existed, so duplicate detection also covers them, not just new uploads."""
    missing = db.query(Document).filter(Document.phash.is_(None)).all()
    changed = False
    for document in missing:
        if not document.filepath or not Path(document.filepath).exists():
            continue
        phash = compute_phash(document.filepath)
        if phash:
            document.phash = phash
            changed = True
    if changed:
        db.commit()


def find_duplicate_documents(db: Session, case_id: str) -> list[dict]:
    documents = (
        db.query(Document)
        .filter(Document.case_id == case_id, Document.phash.isnot(None))
        .order_by(Document.upload_order)
        .all()
    )
    hashes = {d.id: imagehash.hex_to_hash(d.phash) for d in documents}

    suggestions = []
    for i, a in enumerate(documents):
        for b in documents[i + 1:]:
            distance = hashes[a.id] - hashes[b.id]
            if distance <= DUPLICATE_MAX_DISTANCE:
                suggestions.append({"document_a": a, "document_b": b, "distance": int(distance)})

    suggestions.sort(key=lambda s: s["distance"])
    return suggestions[:MAX_SUGGESTIONS]


def find_exact_duplicate_clusters(db: Session, case_id: str) -> list[list[Document]]:
    """Groups documents by identical phash (distance=0 — pixel-identical, not
    just similar). Unlike find_duplicate_documents, this needs no human
    judgment call per pair: same hash means the same image, full stop. Used
    for one-click bulk cleanup rather than a review queue."""
    documents = (
        db.query(Document)
        .filter(Document.case_id == case_id, Document.phash.isnot(None))
        .order_by(Document.upload_order)
        .all()
    )
    by_hash: dict[str, list[Document]] = {}
    for doc in documents:
        by_hash.setdefault(doc.phash, []).append(doc)
    return [group for group in by_hash.values() if len(group) > 1]
