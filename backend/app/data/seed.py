"""Sample data. Nothing here is real and nothing is loaded automatically: a
fresh install starts empty, and the fictional sample case below is created
only when the user asks for it (for demos and training).

Every name, date, amount, and case number in this module is invented. The
dates are arranged so the sample exercises every flag type.
"""
from datetime import date

from sqlalchemy.orm import Session

from app.models.models import Actor, Case, Document, DocumentStatus, Statement, Subject, WatchlistCategory, WatchlistEntity
from app.schemas.schemas import DocumentCommitRequest, ExtractionResult

SAMPLE_CASE_NUMBER = "SAMPLE-0001"
SAMPLE_NOTE = "Fictional sample entry for demonstration. Safe to delete."

SAMPLE_WATCHLIST = [
    ("Rodrigo Muestra Valdés", "RED", "Attorney"),
    ("Clínica Santa Ficción", "ORANGE", "Hospital"),
    ("Hope Bridge Placement Services", "YELLOW", "US Agency"),
]

SAMPLE_SUBJECT = {
    "full_name": "Lucía Fernanda Ejemplo Ramos",
    "aliases": ["Lucy Sampleton"],
    "date_of_birth": date(1984, 3, 12),
    "birth_place": "Valparaíso, Chile",
}

# (label shown in the documents list, extraction)
SAMPLE_DOCUMENTS = [
    ("Sample: birth record", {
        "doc_type": "birth_certificate",
        "names": [
            {"name": "Lucía Fernanda Ejemplo Ramos", "role": "Subject"},
            {"name": "Clínica Santa Ficción", "role": "Hospital"},
        ],
        "dates": [{"label": "birth", "date": "1984-03-12", "raw": "12 de marzo de 1984"}],
        "raw_text_notes": "Fictional birth record for the sample case.",
    }),
    ("Sample: adoption petition", {
        "doc_type": "petition",
        "names": [
            {"name": "Rodrigo Muestra Valdés", "role": "Attorney"},
            {"name": "Mark Sampleton", "role": "Petitioner"},
            {"name": "Ellen Sampleton", "role": "Petitioner"},
        ],
        # Filed three weeks before the recorded birth -> pre-birth petition flag.
        "dates": [{"label": "petition_filed", "date": "1984-02-20", "raw": "20 de febrero de 1984"}],
        "raw_text_notes": "Fictional petition, filed before the recorded birth.",
    }),
    ("Sample: court decree", {
        "doc_type": "decree",
        "names": [
            {"name": "Carmen Inventada Soto", "role": "Judge"},
            {"name": "Lucía Fernanda Ejemplo Ramos", "role": "Subject"},
        ],
        # 18 days after birth -> birth-to-decree interval flag.
        "dates": [{"label": "decree_issued", "date": "1984-03-30", "raw": "treinta de marzo de mil novecientos ochenta y cuatro"}],
        "legal_references": ["Decreto Ley 2.465"],
        "raw_text_notes": "Fictional decree granting the adoption.",
    }),
    ("Sample: payment receipt", {
        "doc_type": "payment_receipt",
        "names": [{"name": "Hope Bridge Placement Services", "role": "Agency"}],
        "dates": [{"label": "payment", "date": "1984-04-02", "raw": "April 2, 1984"}],
        "financial_transactions": [{
            "amount": "2500", "currency": "USD",
            "description": "honorarios por adopción", "linked_case_number": "M-1984-117",
        }],
        "raw_text_notes": "Fictional receipt referencing a payment por adopción.",
    }),
    ("Sample: second birth certificate", {
        "doc_type": "birth_certificate",
        "names": [{"name": "Lucía F. Ejemplo", "role": "Subject"}],
        # Disagrees with the first birth record by two days -> contradiction.
        "dates": [{"label": "birth", "date": "1984-03-14", "raw": "14/03/1984"}],
        "raw_text_notes": "Fictional second certificate with a different birth date.",
    }),
]


# (statement fields, linked document labels, linked actor names)
SAMPLE_STATEMENTS = [
    ({"kind": "testimony",
      "statement": "I knew at the time it wasn't a normal adoption. The lawyer told us to bring the fee in cash, "
                   "and that the paperwork would be 'arranged' before we arrived.",
      "source_name": "Ellen Sampleton", "source_relationship": "adoptive mother", "statement_date": date(2026, 1, 15),
      "method": "Recorded interview", "basis": "firsthand", "status": "unverified", "relation": "supports",
      "flag_severity": "HIGH"},
     ["Sample: payment receipt"], ["Rodrigo Muestra Valdés"]),
    ({"kind": "finding",
      "statement": "DNA testing shows the woman recorded as the mother on the birth record is not the biological "
                   "mother of the subject.",
      "source_name": "Investigator", "source_relationship": "lead investigator", "statement_date": date(2026, 3, 2),
      "method": "DNA test", "status": "verified", "relation": "contradicts", "flag_severity": "CRITICAL"},
     ["Sample: birth record"], []),
]


def _ensure_sample_watchlist(db: Session) -> None:
    existing = {e.name for e in db.query(WatchlistEntity).all()}
    for name, category, entity_type in SAMPLE_WATCHLIST:
        if name not in existing:
            db.add(WatchlistEntity(name=name, category=WatchlistCategory(category), entity_type=entity_type,
                                   aliases=[], notes=SAMPLE_NOTE, is_seed=True))
    db.commit()


def create_sample_case(db: Session) -> Case:
    """Create the fictional sample case (or return it if it already exists),
    committing its documents through the normal review pipeline so actors,
    timeline, watchlist matches, flags and score are all real outputs."""
    from app.routers.documents import commit_document  # avoid import cycle at module load

    case = db.query(Case).filter(Case.case_number == SAMPLE_CASE_NUMBER).first()
    if case:
        return case

    _ensure_sample_watchlist(db)
    case = Case(case_number=SAMPLE_CASE_NUMBER, title="Sample Case (fictional)", notes=SAMPLE_NOTE)
    db.add(case)
    db.flush()
    db.add(Subject(case_id=case.id, notes=SAMPLE_NOTE, **SAMPLE_SUBJECT))
    db.commit()

    for order, (label, extraction) in enumerate(SAMPLE_DOCUMENTS):
        document = Document(case_id=case.id, filename=label, filepath="", upload_order=order,
                            status=DocumentStatus.EXTRACTED)
        db.add(document)
        db.commit()
        commit_document(case.id, document.id,
                        DocumentCommitRequest(edited_extraction=ExtractionResult(**extraction)), db)

    db.refresh(case)
    doc_ids = {d.filename: d.id for d in case.documents}
    actor_ids = {a.canonical_name: a.id for a in db.query(Actor).filter(Actor.case_id == case.id)}
    for fields, doc_labels, actor_names in SAMPLE_STATEMENTS:
        db.add(Statement(case_id=case.id, **fields,
                         related_document_ids=[doc_ids[label] for label in doc_labels if label in doc_ids],
                         related_actor_ids=[actor_ids[name] for name in actor_names if name in actor_ids]))
    db.commit()
    from app.services.recompute import recompute_case
    recompute_case(db, case)
    db.refresh(case)
    return case
