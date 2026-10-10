"""Timeline event classification and the reviewed timeline cleanup.

Extractions label dates freely ("child's birth", "fecha de nacimiento",
"minor_birth"), but the timeline flags only understand four event types.
Before this module, anything not labelled exactly "birth" etc. became
"other", so the birth-to-decree and pre-birth-petition checks silently never
saw the subject's birth. event_type_for() maps labels to types; the cleanup
re-applies it (and the date parser) to events committed before it existed.

Cleanup never deletes: it re-dates, re-labels, and lets the investigator
exclude noise (e.g. the issue date of certified copies), which keeps the
event on record but out of the timeline flags.
"""
import re
import unicodedata

from sqlalchemy.orm import Session

from app.models.models import Case, TimelineEvent
from app.services.date_parsing import parse_document_date

CANONICAL_TYPES = {"birth", "petition_filed", "decree_issued", "payment"}

# Checked in order; the first rule whose keywords appear in the label wins.
TYPE_RULES = [
    ("petition_filed", ("petition", "peticion", "solicitud", "demanda", "filing")),
    ("decree_issued", ("decree", "decreto", "sentencia", "resolucion", "court order", "fallo", "adoption granted")),
    ("payment", ("payment", "pago", "honorario", "fee", "deposit", "deposito")),
    ("birth", ("birth", "nacimiento", "born", "nacio", "dob")),
]

# A birth label naming someone other than the subject (a parent's birth, a
# sibling's) must not become the subject's birth event.
OTHER_PERSON_WORDS = ("mother", "father", "parent", "plaintiff", "madre", "padre", "demandante",
                      "sibling", "hermano", "hermana", "petitioner", "adoptive", "natural child", "foster")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower().replace("_", " ")


def event_type_for(label: str | None) -> str:
    folded = _fold(label).strip()
    exact = folded.replace(" ", "_")
    if exact in CANONICAL_TYPES:
        return exact
    for event_type, keywords in TYPE_RULES:
        if any(re.search(rf"\b{re.escape(k)}", folded) for k in keywords):
            if event_type == "birth" and any(w in folded for w in OTHER_PERSON_WORDS):
                return "other"
            return event_type
    return "other"


def _split_description(description: str | None) -> tuple[str, str]:
    """Timeline descriptions are written as "<label>: <date as written>[ (as
    written: "...")][, p. N]"; recover the label and the date text."""
    text = description or ""
    label, _, rest = text.partition(":")
    as_written = re.search(r'\(as written: "(.+?)"\)', rest)
    value = as_written.group(1) if as_written else re.sub(r",\s*p\.\s*\d+\s*$", "", rest).strip()
    return label.strip(), value


def plan_cleanup(case: Case) -> dict:
    redate, relabel = [], []
    for event in case.timeline_events:
        label, value = _split_description(event.description)
        if event.event_date is None and value:
            parsed = parse_document_date(value)
            if parsed.value:
                redate.append({"id": event.id, "description": event.description,
                               "new_date": parsed.value.isoformat(), "note": parsed.note})
        if event.event_type == "other":
            new_type = event_type_for(label)
            if new_type != "other":
                relabel.append({"id": event.id, "description": event.description,
                                "from_type": event.event_type, "to_type": new_type})

    groups: dict[tuple, int] = {}
    for event in case.timeline_events:
        key = (event.event_type, event.event_date.isoformat() if event.event_date else None)
        groups[key] = groups.get(key, 0) + 1
    duplicate_groups = [
        {"event_type": t, "event_date": d, "count": n}
        for (t, d), n in sorted(groups.items(), key=lambda kv: -kv[1]) if n > 1
    ]
    return {"redate": redate, "relabel": relabel, "duplicate_groups": duplicate_groups}


def apply_cleanup(db: Session, case: Case, redate: bool, relabel: bool) -> dict:
    plan = plan_cleanup(case)
    events = {e.id: e for e in case.timeline_events}
    from datetime import date

    redated = relabelled = 0
    if redate:
        for item in plan["redate"]:
            events[item["id"]].event_date = date.fromisoformat(item["new_date"])
            redated += 1
    if relabel:
        for item in plan["relabel"]:
            events[item["id"]].event_type = item["to_type"]
            relabelled += 1
    db.commit()
    return {"redated": redated, "relabelled": relabelled}
