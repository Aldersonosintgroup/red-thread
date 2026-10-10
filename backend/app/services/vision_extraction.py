"""Forensic document extraction: builds the prompt, calls the vision provider,
and parses the response into a normalized ExtractionResult — with a
regex-based fallback if the model doesn't return clean JSON.
"""
import json
import logging
import re

from collections import Counter

from app.schemas.schemas import ExtractionResult
from app.services.date_parsing import normalize_date_entries
from app.services.dedup import normalize_name
from app.services.ollama_client import run_vision_extraction, VisionProviderError

logger = logging.getLogger("redthread.extraction")

DATE_LABELS = ["birth", "petition_filed", "decree_issued", "payment", "document_date", "other"]
DOC_TYPES = ["petition", "decree", "birth_certificate", "payment_receipt", "correspondence",
             "medical_record", "immigration_record", "court_record", "other"]


def _nullable_string() -> dict:
    return {"anyOf": [{"type": "string"}, {"type": "null"}]}


# The shape every provider is asked for. Claude and Ollama are constrained
# to it at decode time, so their output always parses.
EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": {"type": "string", "enum": DOC_TYPES},
        "names": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "role": _nullable_string()},
                "required": ["name", "role"],
                "additionalProperties": False,
            },
        },
        "dates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string", "enum": DATE_LABELS}, "date": {"type": "string"}},
                "required": ["label", "date"],
                "additionalProperties": False,
            },
        },
        "financial_transactions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "amount": _nullable_string(),
                    "currency": _nullable_string(),
                    "description": _nullable_string(),
                    "linked_case_number": _nullable_string(),
                },
                "required": ["amount", "currency", "description", "linked_case_number"],
                "additionalProperties": False,
            },
        },
        "legal_references": {"type": "array", "items": {"type": "string"}},
        "raw_text_notes": _nullable_string(),
    },
    "required": ["doc_type", "names", "dates", "financial_transactions", "legal_references", "raw_text_notes"],
    "additionalProperties": False,
}

FORENSIC_PROMPT = """This is one scanned page from an adoption case file (Chile/United States, 1970s-1990s), being reviewed for a forensic investigation. Documents may be in Spanish or English, typewritten or handwritten. Report only what is visibly on the page. Never guess or fill in anything that isn't there; a reviewer checks every field against the page.

- doc_type: what kind of document this page is.
- names: every person and organization named on the page (people, judges, attorneys, hospitals, agencies, courts, government offices), spelled exactly as written. role is their role on this page (e.g. Judge, Attorney, Petitioner, Adoptive Parent, Birth Mother, Subject, Hospital, Agency, Recipient, Sender), or null if unclear. Do not list salutations ("Dear Sir"), titles on their own, places (countries, cities, streets), or generic words as names.
- dates: every date that is actually printed, typed, handwritten or stamped on this page, copied exactly as written: day-month-year in Spanish, numeric (day/month/year or month/day/year), English month names, or written out in words. Do not reformat, translate, or complete partial dates. If the page has no dates, return an empty list. label: birth (someone's birth), petition_filed, decree_issued (a decree or court order's issue date), payment, document_date (the date the page itself was written or issued, e.g. a letter's date), or other.
- financial_transactions: every payment, fee, or amount of money, with the amount and currency as written, what it was for, and any case or file number written near it (else null).
- legal_references: every law, decree, or statute number cited on the page (a "Ley", "Decreto", "Decreto Ley" or statute followed by its number), as written.
- raw_text_notes: one or two sentences in English on what this page is and anything notable that the fields above don't capture.

Respond with only the JSON object."""


def _try_parse_json(text: str) -> dict | None:
    text = text.strip()
    # Strip markdown code fences if the model added them anyway.
    text = re.sub(r"^```(?:json)?", "", text.strip())
    text = re.sub(r"```$", "", text.strip())
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    # Fallback: grab the largest {...} span and try again. A model that
    # returns a bare JSON array (or any non-object) isn't usable here either
    # — treat it the same as invalid JSON and fall through to the heuristic.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _heuristic_fallback(raw_text: str) -> ExtractionResult:
    """Last-resort extraction when JSON parsing fails entirely: never crash,
    always return something usable, and say so via parse_warning."""
    names = []
    for m in re.finditer(r"\b([A-Z][a-zÀ-ÿ]+(?:\s+[A-Z][a-zÀ-ÿ]+){1,3})\b", raw_text):
        candidate = m.group(1).strip()
        if len(candidate.split()) >= 2 and candidate not in [n["name"] for n in names]:
            names.append({"name": candidate, "role": None})

    dates = []
    for m in re.finditer(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\b", raw_text):
        dates.append({"label": "unlabeled", "date": m.group(1)})

    return ExtractionResult(
        doc_type="other",
        names=[{"name": n["name"], "role": n["role"]} for n in names[:20]],
        dates=dates[:20],
        financial_transactions=[],
        legal_references=re.findall(r"(Decree\s+\d+|Law\s+\d+)", raw_text, re.IGNORECASE),
        raw_text_notes=raw_text[:500],
        parse_warning="AI response was not valid JSON; used heuristic text-pattern fallback.",
    )


def _normalize_dates(result: ExtractionResult) -> ExtractionResult:
    """Turn every extracted date into ISO form (or None), keeping the
    original wording and any ambiguity note for the reviewer."""
    result.dates = normalize_date_entries(result.dates)
    return result


async def extract_from_image(image_bytes: bytes, media_type: str = "image/jpeg") -> ExtractionResult:
    return _normalize_dates(await _extract(image_bytes, media_type))


def merge_page_results(pages: list[ExtractionResult], total_pages: int | None = None) -> ExtractionResult:
    """Combine per-page extractions of a multi-page PDF into one result,
    tagging every name, date and payment with the page it came from so the
    reviewer can check each finding against the right page."""
    merged = ExtractionResult()
    seen_names: set[str] = set()
    seen_refs: set[str] = set()
    notes: list[str] = []
    warning_pages: dict[str, list[int]] = {}
    doc_types: Counter[str] = Counter()

    for page_number, page in enumerate(pages, start=1):
        if page.doc_type and page.doc_type != "other":
            doc_types[page.doc_type] += 1
        for entity in page.names:
            key = normalize_name(entity.name)
            if key and key not in seen_names:
                seen_names.add(key)
                merged.names.append(entity.model_copy(update={"page": page_number}))
        for d in page.dates:
            merged.dates.append({**d, "page": page_number})
        for txn in page.financial_transactions:
            merged.financial_transactions.append(txn.model_copy(update={"page": page_number}))
        for ref in page.legal_references:
            if ref.lower() not in seen_refs:
                seen_refs.add(ref.lower())
                merged.legal_references.append(ref)
        if page.raw_text_notes:
            notes.append(f"p.{page_number}: {page.raw_text_notes}")
        if page.parse_warning:
            warning_pages.setdefault(page.parse_warning, []).append(page_number)

    merged.doc_type = doc_types.most_common(1)[0][0] if doc_types else (pages[0].doc_type if pages else None)
    merged.raw_text_notes = "\n".join(notes) or None
    readers = list(dict.fromkeys(p.extracted_by for p in pages if p.extracted_by))
    merged.extracted_by = ", ".join(readers) or None
    # Group identical warnings ("AI extraction unavailable" on every page)
    # into one line instead of repeating them per page.
    warnings = [
        f"{'Page' if len(nums) == 1 else 'Pages'} {', '.join(map(str, nums))}: {text}"
        for text, nums in warning_pages.items()
    ]
    if total_pages is not None and total_pages > len(pages):
        warnings.insert(0, f"Only the first {len(pages)} of {total_pages} pages were read automatically. "
                           f"Enter anything from the remaining pages by hand.")
    merged.parse_warning = " ".join(warnings) or None
    return merged


async def _extract(image_bytes: bytes, media_type: str) -> ExtractionResult:
    try:
        provider_response = await run_vision_extraction(image_bytes, FORENSIC_PROMPT, media_type, EXTRACTION_SCHEMA)
    except VisionProviderError as exc:
        logger.error("Vision extraction failed entirely: %s", exc)
        return ExtractionResult(
            parse_warning=f"AI extraction unavailable: {exc}",
        )

    result = _to_result(provider_response.text)
    result.extracted_by = provider_response.extracted_by
    return result


def _to_result(raw_response: str) -> ExtractionResult:
    parsed = _try_parse_json(raw_response)
    if parsed is None:
        return _heuristic_fallback(raw_response)

    try:
        return ExtractionResult(
            doc_type=parsed.get("doc_type"),
            names=[
                {"name": n.get("name", ""), "role": n.get("role")}
                for n in parsed.get("names", []) if isinstance(n, dict) and n.get("name")
            ],
            dates=[
                {"label": d.get("label", "unlabeled"), "date": d.get("date")}
                for d in parsed.get("dates", []) if isinstance(d, dict)
            ],
            financial_transactions=[
                {
                    "amount": t.get("amount"),
                    "currency": t.get("currency"),
                    "description": t.get("description"),
                    "linked_case_number": t.get("linked_case_number"),
                }
                for t in parsed.get("financial_transactions", []) if isinstance(t, dict)
            ],
            legal_references=[r for r in parsed.get("legal_references", []) if isinstance(r, str)],
            raw_text_notes=parsed.get("raw_text_notes"),
        )
    except (TypeError, ValueError, AttributeError, KeyError) as exc:
        logger.warning("JSON parsed but shape was unexpected: %s", exc)
        return _heuristic_fallback(raw_response)
