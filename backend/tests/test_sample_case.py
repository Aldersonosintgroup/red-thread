from app.core import config, database_lifecycle, db, vault
from app.data.seed import SAMPLE_CASE_NUMBER, create_sample_case
from app.models.models import Case, Flag, WatchlistEntity


def test_sample_case_is_fictional_and_exercises_every_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    vault.lock()
    database_lifecycle.open_database()
    session = db.SessionLocal()
    try:
        # A fresh install starts empty: no cases, no watchlist.
        assert session.query(Case).count() == 0
        assert session.query(WatchlistEntity).count() == 0

        case = create_sample_case(session)
        assert create_sample_case(session).id == case.id  # idempotent
        assert case.case_number == SAMPLE_CASE_NUMBER and "fictional" in case.title.lower()

        flag_types = {f.flag_type.value for f in session.query(Flag).filter(Flag.case_id == case.id)}
        assert flag_types == {
            "TIMELINE_IRREGULARITY", "PRE_BIRTH_PETITION_ANOMALY", "FINANCIAL_ANOMALY",
            "ENTITY_MATCH", "CONTRADICTION", "LEGAL_NON_COMPLIANCE", "INVESTIGATOR_FINDING",
        }
        assert sorted(s.kind for s in case.statements) == ["finding", "testimony"]
        assert all(s.related_document_ids for s in case.statements)
        assert all("Fictional" in e.notes for e in session.query(WatchlistEntity))
    finally:
        session.close()
        db.close_engine()
