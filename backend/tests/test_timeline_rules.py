import pytest

from app.core import config, database_lifecycle, db, vault
from app.data.seed import create_sample_case
from app.models.models import Flag, TimelineEvent
from app.services.recompute import recompute_case
from app.services.timeline_rules import apply_cleanup, event_type_for, plan_cleanup


@pytest.mark.parametrize("label, expected", [
    ("birth", "birth"),
    ("child's birth", "birth"),
    ("date of birth", "birth"),
    ("minor_birth", "birth"),
    ("Fecha de Nacimiento", "birth"),
    ("petition_filed", "petition_filed"),
    ("Solicitud de adopción", "petition_filed"),
    ("decree_issued", "decree_issued"),
    ("Sentencia", "decree_issued"),
    ("Resolución del tribunal", "decree_issued"),
    ("pago por adopción", "payment"),
    ("natural child born in foster care", "other"),   # someone else's birth
    ("mother's birth", "other"),
    ("document_date", "other"),
    ("unlabeled", "other"),
    ("female plaintiff university graduation", "other"),
])
def test_event_type_for(label, expected):
    assert event_type_for(label) == expected


@pytest.fixture
def sample_session(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    vault.lock()
    database_lifecycle.open_database()
    session = db.SessionLocal()
    yield session
    session.close()
    db.close_engine()


def test_cleanup_redates_relabels_and_restores_missed_flags(sample_session):
    case = create_sample_case(sample_session)
    sample_session.query(Flag).delete()
    # Simulate events committed by the old code: free-form birth label filed
    # as "other", and a date the old parser couldn't read.
    for e in case.timeline_events:
        if e.event_type == "birth":
            e.event_type = "other"
            e.description = "child's birth: 12 de marzo de 1984"
    case.timeline_events.append(TimelineEvent(case_id=case.id, event_type="other", event_date=None,
                                              description="unlabeled: 30/4/85"))
    sample_session.commit()
    recompute_case(sample_session, case)
    types = lambda: {f.flag_type.value for f in sample_session.query(Flag).filter(Flag.case_id == case.id)}
    assert "TIMELINE_IRREGULARITY" not in types()  # the bug: birth invisible to the check

    plan = plan_cleanup(case)
    assert any(r["new_date"] == "1985-04-30" for r in plan["redate"])
    assert all(r["to_type"] == "birth" for r in plan["relabel"]) and plan["relabel"]

    result = apply_cleanup(sample_session, case, redate=True, relabel=True)
    recompute_case(sample_session, case)
    assert result["relabelled"] == len(plan["relabel"]) and result["redated"] >= 1
    assert {"TIMELINE_IRREGULARITY", "PRE_BIRTH_PETITION_ANOMALY"} <= types()


def test_excluded_events_do_not_raise_flags(sample_session):
    case = create_sample_case(sample_session)
    for e in case.timeline_events:
        if e.event_type == "decree_issued":
            e.excluded = True
    sample_session.commit()
    recompute_case(sample_session, case)
    assert "TIMELINE_IRREGULARITY" not in {f.flag_type.value for f in sample_session.query(Flag).filter(Flag.case_id == case.id)}


def test_same_birth_recorded_by_several_documents_raises_one_flag(sample_session):
    case = create_sample_case(sample_session)
    birth = next(e for e in case.timeline_events if e.event_type == "birth" and str(e.event_date) == "1984-03-12")
    for _ in range(2):
        case.timeline_events.append(TimelineEvent(case_id=case.id, event_type="birth", event_date=birth.event_date,
                                                  description="birth: repeated in another document"))
    sample_session.commit()
    recompute_case(sample_session, case)
    gaps = [f for f in sample_session.query(Flag).filter(Flag.case_id == case.id)
            if f.flag_type.value == "TIMELINE_IRREGULARITY" and "1984-03-12" in f.description]
    assert len(gaps) == 1


def test_reread_all_clears_derived_data_and_keeps_evidence(sample_session, tmp_path, monkeypatch):
    from app.models.models import Actor, ActorEdge, Document, Subject, WatchlistEntity
    from app.routers import documents as documents_router

    case = create_sample_case(sample_session)
    scan = tmp_path / "scan.jpg"
    scan.write_bytes(b"evidence")
    doc = Document(case_id=case.id, filename="scan.jpg", filepath=str(scan), upload_order=99,
                   status="reviewed", committed=True, raw_extraction={"names": []})
    sample_session.add(doc)
    sample_session.commit()
    watchlist_before = sample_session.query(WatchlistEntity).count()
    queued = []
    monkeypatch.setattr(documents_router, "enqueue_document", queued.append)

    result = documents_router.reread_all_documents(case.id, sample_session)

    assert result == {"queued": 1, "manual_entries_reopened": 5}
    assert queued == [doc.id]
    assert sample_session.query(TimelineEvent).filter(TimelineEvent.case_id == case.id).count() == 0
    assert sample_session.query(ActorEdge).filter(ActorEdge.case_id == case.id).count() == 0
    assert [a.is_subject for a in sample_session.query(Actor).filter(Actor.case_id == case.id)] == [True]
    # Only flags the investigator raised from testimony/findings survive: those
    # statements are evidence entered by a person, kept like the scanned files.
    remaining = sample_session.query(Flag).filter(Flag.case_id == case.id).all()
    assert {f.flag_type.value for f in remaining} <= {"INVESTIGATOR_FINDING"}
    assert len(case.statements) == 2
    assert scan.read_bytes() == b"evidence"
    sample_session.refresh(doc)
    assert doc.status.value == "pending" and doc.raw_extraction is None and not doc.committed
    manual = sample_session.query(Document).filter(Document.case_id == case.id, Document.filepath == "").all()
    assert all(d.edited_extraction and not d.committed for d in manual)  # content kept, needs re-commit
    assert sample_session.query(Subject).filter(Subject.case_id == case.id).count() == 1
    assert sample_session.query(WatchlistEntity).count() == watchlist_before


def test_renormalize_updates_only_unreviewed_documents(sample_session):
    from app.models.models import Document
    from app.services.date_parsing import renormalize_unreviewed

    case = create_sample_case(sample_session)
    stale = {"dates": [{"label": "other", "date": None, "raw": "21 6 85", "note": "Could not read this date automatically.", "page": 2}]}
    open_doc = Document(case_id=case.id, filename="a.jpg", filepath="", upload_order=60, status="extracted",
                        committed=False, raw_extraction=stale)
    done_doc = Document(case_id=case.id, filename="b.jpg", filepath="", upload_order=61, status="reviewed",
                        committed=True, raw_extraction=stale)
    sample_session.add_all([open_doc, done_doc])
    sample_session.commit()

    assert renormalize_unreviewed(sample_session) == 1
    sample_session.refresh(open_doc)
    sample_session.refresh(done_doc)
    assert open_doc.raw_extraction["dates"][0]["date"] == "1985-06-21"
    assert open_doc.raw_extraction["dates"][0]["page"] == 2
    assert done_doc.raw_extraction["dates"][0]["date"] is None  # reviewed: untouched
    assert renormalize_unreviewed(sample_session) == 0  # idempotent


def test_actor_details_finds_every_spelling_in_reviewed_documents(sample_session):
    from app.models.models import Actor
    from app.routers.entities import get_actor_details

    case = create_sample_case(sample_session)
    subject = next(a for a in case.actors if a.is_subject)
    details = get_actor_details(case.id, subject.id, sample_session)
    written = {a["name_as_written"] for a in details["appearances"]}
    assert "Lucía Fernanda Ejemplo Ramos" in written and "Lucía F. Ejemplo" in written  # both spellings
    attorney = next(a for a in case.actors if a.canonical_name == "Rodrigo Muestra Valdés")
    details = get_actor_details(case.id, attorney.id, sample_session)
    assert details["watchlist"]["category"] == "RED"
    assert [a["role"] for a in details["appearances"]] == ["Attorney"]
    assert any(f.flag_type == "ENTITY_MATCH" for f in details["flags"])
