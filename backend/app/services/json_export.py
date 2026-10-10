from datetime import datetime, date

from app.models.models import Case


def _default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


def build_case_json(case: Case, score: dict) -> dict:
    return {
        "exported_at": datetime.utcnow().isoformat(),
        "case": {
            "id": case.id,
            "case_number": case.case_number,
            "title": case.title,
            "status": case.status,
            "created_at": case.created_at,
        },
        "subject": {
            "full_name": case.subject.full_name,
            "aliases": case.subject.aliases,
            "date_of_birth": case.subject.date_of_birth,
            "birth_place": case.subject.birth_place,
            "notes": case.subject.notes,
        } if case.subject else None,
        "actors": [
            {
                "id": a.id,
                "canonical_name": a.canonical_name,
                "aliases": a.aliases,
                "role": a.role,
                "is_subject": a.is_subject,
                "watchlist_match": {
                    "name": a.watchlist_match.name,
                    "category": a.watchlist_match.category.value if hasattr(a.watchlist_match.category, "value") else a.watchlist_match.category,
                } if a.watchlist_match else None,
                "watchlist_match_score": a.watchlist_match_score,
            }
            for a in case.actors
        ],
        "edges": [
            {
                "source_actor_id": e.source_actor_id,
                "target_actor_id": e.target_actor_id,
                "relationship_type": e.relationship_type,
            }
            for e in case.edges
        ],
        "statements": [
            {
                "id": s.id,
                "kind": s.kind,
                "statement": s.statement,
                "source_name": s.source_name,
                "source_relationship": s.source_relationship,
                "statement_date": s.statement_date,
                "method": s.method,
                "basis": s.basis,
                "status": s.status,
                "relation": s.relation,
                "related_document_ids": s.related_document_ids,
                "related_actor_ids": s.related_actor_ids,
                "flag_severity": s.flag_severity,
            }
            for s in case.statements
        ],
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "doc_type": d.doc_type,
                "status": d.status.value if hasattr(d.status, "value") else d.status,
                "committed": d.committed,
                "extraction": d.edited_extraction or d.raw_extraction,
            }
            for d in case.documents
        ],
        "timeline_events": [
            {
                "event_type": t.event_type,
                "event_date": t.event_date,
                "description": t.description,
            }
            for t in case.timeline_events
        ],
        "flags": [
            {
                "flag_type": f.flag_type.value if hasattr(f.flag_type, "value") else f.flag_type,
                "severity": f.severity.value if hasattr(f.severity, "value") else f.severity,
                "title": f.title,
                "description": f.description,
                "legal_reference": f.legal_reference,
            }
            for f in case.flags
        ],
        "score": score,
    }
