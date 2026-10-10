"""Sequential document processing queue: one AI vision call at a time, with a
fixed delay between calls (simple local rate limiting), so a batch upload
doesn't hammer the model or exhaust the Ollama context."""
import asyncio
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core import vault
from app.core.db import SessionLocal
from app.models.models import Document, DocumentStatus
from app.services.pdf_pages import PdfReadError, prepare_image_for_vision, render_pdf_pages
from app.services.vision_extraction import extract_from_image, merge_page_results

logger = logging.getLogger("redthread.queue")

_queue: asyncio.Queue[str] = asyncio.Queue()
_worker_task: asyncio.Task | None = None
_busy = False


def is_busy() -> bool:
    """True while a document is being extracted or more are queued, so
    auto-lock never pulls the database out from under a running batch."""
    return _busy or not _queue.empty()


_queued_ids: set[str] = set()


def enqueue_document(document_id: str) -> None:
    if document_id in _queued_ids:
        return  # already waiting; never read the same document twice
    _queued_ids.add(document_id)
    _queue.put_nowait(document_id)


def resume_unfinished(db: Session) -> int:
    """Re-queue documents left pending or mid-read when the app last closed
    (a restart, an update, a crash), so they are never stuck."""
    unfinished = (
        db.query(Document)
        .filter(Document.status.in_([DocumentStatus.PENDING, DocumentStatus.PROCESSING]))
        .order_by(Document.upload_order)
        .all()
    )
    for document in unfinished:
        document.status = DocumentStatus.PENDING
    db.commit()
    for document in unfinished:
        enqueue_document(document.id)
    return len(unfinished)


async def _process_one(db: Session, document_id: str) -> None:
    document = db.query(Document).filter(Document.id == document_id).first()
    if document is None:
        logger.warning("Queued document %s no longer exists", document_id)
        return

    document.status = DocumentStatus.PROCESSING
    db.commit()

    try:
        result = await _extract_document(document.filepath)
        document.raw_extraction = result.model_dump()
        document.doc_type = result.doc_type
        document.status = DocumentStatus.EXTRACTED
        document.error_message = None
    except (OSError, PdfReadError) as exc:
        document.status = DocumentStatus.ERROR
        document.error_message = f"Could not read uploaded file: {exc}"
    except Exception as exc:  # noqa: BLE001 - extraction must never crash the queue
        logger.exception("Extraction failed for document %s", document_id)
        document.status = DocumentStatus.ERROR
        document.error_message = str(exc)
    finally:
        from datetime import datetime
        document.processed_at = datetime.utcnow()
        db.commit()


async def _extract_document(filepath: str):
    suffix = Path(filepath).suffix.lower()
    file_bytes = vault.read_evidence(filepath)
    if suffix == ".pdf":
        rendered = await asyncio.to_thread(
            render_pdf_pages, file_bytes, settings.pdf_max_pages, settings.pdf_render_dpi
        )
        page_results = []
        for index, page_image in enumerate(rendered.images):
            if index:
                await asyncio.sleep(settings.vision_call_delay_seconds)
            page_results.append(await extract_from_image(page_image, "image/jpeg"))
        return merge_page_results(page_results, rendered.total_pages)

    media_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(suffix, "image/jpeg")
    image_bytes, media_type = prepare_image_for_vision(file_bytes, media_type)
    return await extract_from_image(image_bytes, media_type)


async def _worker_loop() -> None:
    global _busy
    while True:
        document_id = await _queue.get()
        if vault.is_locked():
            # Locked mid-batch: hold the document until the next unlock.
            _queue.task_done()
            _queue.put_nowait(document_id)
            await asyncio.sleep(5)
            continue
        _queued_ids.discard(document_id)
        _busy = True
        db = SessionLocal()
        try:
            await _process_one(db, document_id)
        except Exception:  # noqa: BLE001 - the worker loop itself must never die
            logger.exception("Unhandled error processing document %s", document_id)
        finally:
            db.close()
            _queue.task_done()
            _busy = False
        await asyncio.sleep(settings.vision_call_delay_seconds)


def start_worker() -> None:
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.get_event_loop().create_task(_worker_loop())
