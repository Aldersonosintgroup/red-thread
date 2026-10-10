"""Opening, converting and locking the case database as one unit, so the
engine, the vault key and the in-memory API keys always change together."""
import logging

from app.core import db, vault
from app.core.migrations import run_migrations

logger = logging.getLogger("redthread.lifecycle")


def open_database() -> None:
    """Open the engine and bring the schema up to date. For an encrypted
    database this only works once the vault is unlocked."""
    engine = db.open_engine()
    import app.models.models  # noqa: F401 - registers tables on Base

    db.Base.metadata.create_all(bind=engine)
    run_migrations(engine)

    from app.services.image_dedup import backfill_missing_phashes
    from app.services.queue_processor import resume_unfinished

    session = db.SessionLocal()
    try:
        backfill_missing_phashes(session)
        from app.services.date_parsing import renormalize_unreviewed

        renormalized = renormalize_unreviewed(session)
        if renormalized:
            logger.info("Re-interpreted dates in %d unreviewed document(s)", renormalized)
        resumed = resume_unfinished(session)
        if resumed:
            logger.info("Resumed reading %d unfinished document(s)", resumed)
    finally:
        session.close()


def convert_and_reopen() -> dict:
    """With the vault unlocked: finish converting any remaining plaintext
    data (idempotent, so it also completes an interrupted conversion), load
    the API keys from the vault, and reopen the encrypted database."""
    db.close_engine()
    vault.convert_database()
    files_encrypted = vault.convert_files()
    vault.convert_secrets()
    removed = vault.remove_plaintext_leftovers()
    vault.load_secrets_into_settings()
    open_database()
    if files_encrypted or removed:
        logger.info("Encrypted %d evidence files; removed plaintext copies: %s", files_encrypted, removed)
    return {"files_encrypted": files_encrypted, "removed_plaintext_copies": removed}


def lock() -> None:
    db.close_engine()
    vault.lock()
