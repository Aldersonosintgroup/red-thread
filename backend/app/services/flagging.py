"""Flagging rules: timeline irregularities, pre-birth petitions, financial
anomalies, and legal non-compliance references. Language throughout is
trauma-informed — "irregularity" / "anomaly", never "trafficking".
"""
import re
from datetime import date

from sqlalchemy.orm import Session

from app.models.models import Case, Document, Flag, FlagType, FlagSeverity, TimelineEvent

TIMELINE_DELTA_THRESHOLD_DAYS = 30

LEGAL_REFERENCES = {
    "decree 2465": "Decree 2465 (1979)",
    "decree 2.465": "Decree 2465 (1979)",
    "d.l. 2465": "Decree 2465 (1979)",
    "d.l. 2.465": "Decree 2465 (1979)",
    "decreto ley 2465": "Decree 2465 (1979)",
    "decreto ley 2.465": "Decree 2465 (1979)",
    "decreto ley n° 2465": "Decree 2465 (1979)",
    "decreto ley n° 2.465": "Decree 2465 (1979)",
    "dl 2465": "Decree 2465 (1979)",
    "dl 2.465": "Decree 2465 (1979)",
    "law 18703": "Law 18703 (1989)",
    "law 18.703": "Law 18703 (1989)",
    "ley 18703": "Law 18703 (1989)",
    "ley 18.703": "Law 18703 (1989)",
    "ley n° 18.703": "Law 18703 (1989)",
    "ley n° 18703": "Law 18703 (1989)",
}

FINANCIAL_ANOMALY_PHRASES = ["por adopcion", "por adopción"]


def clear_case_flags(db: Session, case_id: str) -> None:
    db.query(Flag).filter(Flag.case_id == case_id).delete()


def _add_flag(db: Session, case_id: str, flag_type: FlagType, severity: FlagSeverity,
              title: str, description: str, document_id: str | None = None,
              actor_id: str | None = None, legal_reference: str | None = None) -> None:
    db.add(Flag(
        case_id=case_id, flag_type=flag_type, severity=severity, title=title,
        description=description, related_document_id=document_id,
        related_actor_id=actor_id, legal_reference=legal_reference,
    ))


def evaluate_timeline_flags(db: Session, case: Case) -> None:
    events_by_type: dict[str, list[TimelineEvent]] = {}
    for event in case.timeline_events:
        if event.event_date is None or event.excluded:
            continue
        events_by_type.setdefault(event.event_type, []).append(event)

    # One event per distinct date: the same birth recorded by three
    # documents is one fact, and must raise one flag, not three (which also
    # inflated the score). The first document recording the date is cited.
    def first_per_date(events: list[TimelineEvent]) -> list[TimelineEvent]:
        unique: dict = {}
        for event in events:
            unique.setdefault(event.event_date, event)
        return list(unique.values())

    births = first_per_date(events_by_type.get("birth", []))
    decrees = first_per_date(events_by_type.get("decree_issued", []))
    petitions = first_per_date(events_by_type.get("petition_filed", []))

    for birth in births:
        for decree in decrees:
            delta = (decree.event_date - birth.event_date).days
            if 0 <= delta < TIMELINE_DELTA_THRESHOLD_DAYS:
                _add_flag(
                    db, case.id, FlagType.TIMELINE_IRREGULARITY, FlagSeverity.CRITICAL,
                    "Timeline Irregularity: Birth-to-Decree Interval Under 30 Days",
                    f"Only {delta} day(s) between recorded birth ({birth.event_date}) and "
                    f"decree issuance ({decree.event_date}).",
                    document_id=decree.source_document_id,
                )

        for petition in petitions:
            if petition.event_date < birth.event_date:
                _add_flag(
                    db, case.id, FlagType.PRE_BIRTH_PETITION, FlagSeverity.CRITICAL,
                    "Pre-Birth Petition Anomaly",
                    f"Petition filed ({petition.event_date}) before the recorded birth date "
                    f"({birth.event_date}).",
                    document_id=petition.source_document_id,
                )


def evaluate_financial_flags(db: Session, case: Case) -> None:
    for document in case.documents:
        if not document.committed:
            continue  # only reviewed documents are part of the case
        extraction = document.edited_extraction or document.raw_extraction
        if not extraction:
            continue

        notes = (extraction.get("raw_text_notes") or "").lower()
        has_phrase = any(phrase in notes for phrase in FINANCIAL_ANOMALY_PHRASES)

        transactions = extraction.get("financial_transactions") or []
        for txn in transactions:
            linked_case = txn.get("linked_case_number")
            is_minor_case_linked = bool(linked_case and linked_case != case.case_number
                                         and re.search(r"\d", linked_case))
            if has_phrase or is_minor_case_linked:
                _add_flag(
                    db, case.id, FlagType.FINANCIAL_ANOMALY, FlagSeverity.HIGH,
                    "Financial Anomaly",
                    f"Payment of {txn.get('amount') or 'unspecified amount'} "
                    f"{txn.get('currency') or ''} linked to case reference "
                    f"'{linked_case or 'n/a'}'. {txn.get('description') or ''}".strip(),
                    document_id=document.id,
                )
        if has_phrase and not transactions:
            _add_flag(
                db, case.id, FlagType.FINANCIAL_ANOMALY, FlagSeverity.HIGH,
                "Financial Anomaly",
                "Document text references payment tied to an adoption ('por adopción').",
                document_id=document.id,
            )


def evaluate_legal_flags(db: Session, case: Case) -> None:
    for document in case.documents:
        if not document.committed:
            continue  # only reviewed documents are part of the case
        extraction = document.edited_extraction or document.raw_extraction
        if not extraction:
            continue
        refs = extraction.get("legal_references") or []
        notes = (extraction.get("raw_text_notes") or "")
        haystack = " ".join(refs) + " " + notes
        haystack_lower = haystack.lower()

        for needle, label in LEGAL_REFERENCES.items():
            if needle in haystack_lower:
                _add_flag(
                    db, case.id, FlagType.LEGAL_VIOLATION, FlagSeverity.MEDIUM,
                    f"Legal Reference Flagged: {label}",
                    f"Document references {label}, relevant to adoption-process compliance "
                    f"review for this case.",
                    document_id=document.id,
                    legal_reference=label,
                )


def evaluate_entity_match_flags(db: Session, case: Case) -> None:
    for actor in case.actors:
        if actor.watchlist_match_id and actor.watchlist_match:
            entity = actor.watchlist_match
            severity = {
                "RED": FlagSeverity.CRITICAL,
                "ORANGE": FlagSeverity.HIGH,
                "YELLOW": FlagSeverity.MEDIUM,
            }.get(entity.category.value if hasattr(entity.category, "value") else entity.category,
                  FlagSeverity.LOW)
            _add_flag(
                db, case.id, FlagType.ENTITY_MATCH, severity,
                f"Watchlist Match: {actor.canonical_name}",
                f"Matches previously investigated entity '{entity.name}' "
                f"({entity.category.value if hasattr(entity.category, 'value') else entity.category} "
                f"tier) at {actor.watchlist_match_score:.0f}% confidence.",
                actor_id=actor.id,
            )


def evaluate_contradiction_flags(db: Session, case: Case, discrepancy_groups: list[dict]) -> None:
    for group in discrepancy_groups:
        if group.get("is_contradictory"):
            values = ", ".join(f"{r['value']} ({r['document_filename']})" for r in group["rows"])
            _add_flag(
                db, case.id, FlagType.CONTRADICTION, FlagSeverity.MEDIUM,
                f"Contradiction: {group['field']}",
                f"Conflicting values found across documents for '{group['field']}': {values}",
            )


KIND_LABEL = {"testimony": "Testimony", "finding": "Verified finding"}


def statement_flag_title(statement) -> str:
    text = " ".join(statement.statement.split())
    short = text if len(text) <= 90 else text[:87].rstrip() + "…"
    return f"{KIND_LABEL.get(statement.kind, 'Statement')}: {short}"


def statement_flag_description(statement) -> str:
    who = statement.source_name or "unnamed source"
    if statement.source_relationship:
        who += f" ({statement.source_relationship})"
    parts = [("Stated by " if statement.kind == "testimony" else "Verified by ") + who]
    if statement.statement_date:
        parts.append(f"on {statement.statement_date.isoformat()}")
    if statement.method:
        parts.append(f"via {statement.method}")
    detail = " ".join(parts) + "."
    if statement.kind == "testimony":
        basis = {"firsthand": "first-hand account", "secondhand": "second-hand account"}.get(statement.basis or "")
        detail += f" {statement.status.capitalize()}" + (f", {basis}" if basis else "") + "."
    if statement.relation == "contradicts" and statement.related_document_ids:
        detail += f" Contradicts {len(statement.related_document_ids)} document(s) in the case."
    elif statement.relation == "supports" and statement.related_document_ids:
        detail += f" Supports {len(statement.related_document_ids)} document(s) in the case."
    return detail + " Entered by the investigator."


def evaluate_statement_flags(db: Session, case: Case) -> None:
    """Flags the investigator chose to raise from testimony or findings."""
    existing_documents = {d.id for d in case.documents}
    existing_actors = {a.id for a in case.actors}
    for statement in case.statements:
        if not statement.flag_severity:
            continue
        # Linked documents or people may have been deleted or merged since.
        documents = [d for d in statement.related_document_ids or [] if d in existing_documents]
        actors = [a for a in statement.related_actor_ids or [] if a in existing_actors]
        _add_flag(
            db, case.id, FlagType.INVESTIGATOR_FINDING, FlagSeverity(statement.flag_severity),
            statement_flag_title(statement), statement_flag_description(statement),
            document_id=documents[0] if documents else None,
            actor_id=actors[0] if actors else None,
        )


def run_all_flag_evaluations(db: Session, case: Case, discrepancy_groups: list[dict]) -> None:
    clear_case_flags(db, case.id)
    evaluate_timeline_flags(db, case)
    evaluate_financial_flags(db, case)
    evaluate_legal_flags(db, case)
    evaluate_entity_match_flags(db, case)
    evaluate_contradiction_flags(db, case, discrepancy_groups)
    evaluate_statement_flags(db, case)
    db.commit()
