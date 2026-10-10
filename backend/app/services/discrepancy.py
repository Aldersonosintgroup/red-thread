"""Discrepancy engine: side-by-side comparison of the same field (subject name,
birth date, etc.) as recorded across different committed documents."""
from app.models.models import Case
from app.services.date_parsing import parse_document_date
from app.services.dedup import normalize_name

FIELDS_TO_COMPARE = [
    ("subject_name", "names"),
    ("birth_date", "dates:birth"),
    ("decree_date", "dates:decree_issued"),
    ("petition_date", "dates:petition_filed"),
]


def _comparable(field_label: str, value: str) -> str:
    """Compare dates by the day they denote, not their wording — so
    "24/08/1983" and "1983-08-24" aren't reported as a contradiction."""
    if field_label.endswith("_date"):
        parsed = parse_document_date(value).value
        if parsed:
            return parsed.isoformat()
    return normalize_name(value)


def build_discrepancy_groups(case: Case) -> list[dict]:
    groups: list[dict] = []

    for field_label, source in FIELDS_TO_COMPARE:
        rows = []
        for document in case.documents:
            if not document.committed:
                continue  # only reviewed documents are part of the case
            extraction = document.edited_extraction or document.raw_extraction
            if not extraction:
                continue

            if source == "names":
                subject_name = (case.subject.full_name if case.subject else "").strip()
                if not subject_name:
                    continue
                for n in extraction.get("names", []):
                    name = n.get("name", "")
                    if name and normalize_name(name) == normalize_name(subject_name):
                        continue  # exact/normalized match to the known subject name, not a discrepancy
                for n in extraction.get("names", []):
                    role = (n.get("role") or "").lower()
                    if "subject" in role and n.get("name"):
                        rows.append({
                            "field": field_label,
                            "document_id": document.id,
                            "document_filename": document.filename,
                            "value": n["name"],
                        })
            else:
                _, label = source.split(":")
                for d in extraction.get("dates", []):
                    if (d.get("label") or "").lower() == label:
                        rows.append({
                            "field": field_label,
                            "document_id": document.id,
                            "document_filename": document.filename,
                            "value": d.get("date") or "",
                        })

        if len(rows) < 2:
            if rows:
                groups.append({"field": field_label, "rows": rows, "is_contradictory": False})
            continue

        distinct_values = {_comparable(field_label, r["value"]) for r in rows if r["value"]}
        groups.append({
            "field": field_label,
            "rows": rows,
            "is_contradictory": len(distinct_values) > 1,
        })

    return groups
