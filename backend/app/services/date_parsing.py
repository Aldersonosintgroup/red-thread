"""Date normalization for extracted document dates.

Case documents rarely say "1983-08-24". Chilean records say "24/08/1983",
"24 de agosto de 1983", or — in notarial and court language — spell the
whole date out: "a veinticuatro días del mes de agosto de mil novecientos
ochenta y tres". US agency paperwork uses MM/DD/YYYY and "August 24, 1983".

parse_document_date() turns all of these into a real date, and never
guesses silently: anything ambiguous or assumed comes back with a note the
reviewer sees next to the field. A date that can't be fully determined
(month/year only, unreadable) returns no value rather than an invented one.
"""
import re
import unicodedata
from dataclasses import dataclass
from datetime import date

MIN_YEAR = 1900

MONTHS = {
    # Spanish
    "enero": 1, "ene": 1,
    "febrero": 2, "feb": 2,
    "marzo": 3, "mar": 3,
    "abril": 4, "abr": 4,
    "mayo": 5, "may": 5,
    "junio": 6, "jun": 6,
    "julio": 7, "jul": 7,
    "agosto": 8, "ago": 8,
    "septiembre": 9, "setiembre": 9, "sept": 9, "sep": 9, "set": 9,
    "octubre": 10, "oct": 10,
    "noviembre": 11, "nov": 11,
    "diciembre": 12, "dic": 12,
    # English
    "january": 1, "jan": 1,
    "february": 2,
    "march": 3,
    "april": 4, "apr": 4,
    "june": 6,
    "july": 7,
    "august": 8, "aug": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12, "dec": 12,
}

NUMBER_WORDS = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "primero": 1, "primer": 1,
    "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13,
    "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17,
    "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiun": 21,
    "veintiuno": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24,
    "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28,
    "veintinueve": 29, "treinta": 30, "cuarenta": 40, "cincuenta": 50,
    "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90,
    "cien": 100, "ciento": 100, "doscientos": 200, "trescientos": 300,
    "cuatrocientos": 400, "quinientos": 500, "seiscientos": 600,
    "setecientos": 700, "ochocientos": 800, "novecientos": 900,
}

# Words that sit between the parts of a written-out date and carry no value:
# "a los veinticuatro días del mes de agosto del año ..."
FILLER_WORDS = {"a", "al", "los", "las", "el", "la", "dia", "dias", "del", "de",
                "mes", "ano", "the", "of", "day", "on", "en", "fecha"}

UNREADABLE_NOTE = "Could not read this date automatically. Check the document and enter it by hand."


@dataclass(frozen=True)
class ParsedDate:
    value: date | None
    note: str | None = None
    # Set when a day and month were read but no year ("May 22nd"), so the
    # caller can complete it from the document's own date, with a note.
    month: int | None = None
    day: int | None = None


def _fold(text: str) -> str:
    """Lowercase and strip accents, so 'Diciembre', 'diciembre' and
    'DICIEMBRE' — and 'año'/'ano', 'días'/'dias' — compare equal."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _words_to_number(words: list[str]) -> int | None:
    """'mil novecientos ochenta y tres' -> 1983; 'veinticuatro' -> 24."""
    total = 0
    current = 0
    seen = False
    for word in words:
        if word == "y":
            continue
        if word == "mil":
            total += (current or 1) * 1000
            current = 0
            seen = True
        elif word in NUMBER_WORDS:
            current += NUMBER_WORDS[word]
            seen = True
        else:
            return None
    return total + current if seen else None


def _is_number_token(token: str) -> bool:
    return token.isdigit() or token in NUMBER_WORDS or token in ("mil", "y")


def _strip_ordinal(token: str) -> str:
    # "27th", "1st", "1ro", "1o", "1°"
    match = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th|ro|o|er)?", token)
    return match.group(1) if match else token


def _expand_two_digit_year(yy: int, today: date) -> tuple[int, str | None]:
    """'85' can only be 1985 (2085 is in the future), so it needs no warning.
    Only years that could be either century ('05': 1905 or 2005) are noted."""
    if yy > today.year % 100:
        return 1900 + yy, None
    year = 2000 + yy
    return year, f"Two-digit year '{yy:02d}' read as {year}; it could also be {1900 + yy}."


def _build(year: int, month: int, day: int, today: date, note: str | None) -> ParsedDate:
    if not (MIN_YEAR <= year <= today.year + 1):
        return ParsedDate(None, f"Year {year} is outside the plausible range. Check the document.")
    try:
        return ParsedDate(date(year, month, day), note)
    except ValueError:
        return ParsedDate(None, f"{day:02d}/{month:02d}/{year} is not a real calendar date. Check the document.")


def _join_notes(*notes: str | None) -> str | None:
    present = [n for n in notes if n]
    return " ".join(present) if present else None


def _parse_numeric(text: str, today: date) -> ParsedDate | None:
    iso = re.search(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", text)
    if iso:
        return _build(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)), today, None)

    # Separators: / - . as usual, plus the forms stamps and Spanish
    # documents use: plain spaces ("21 6 85") and "de" ("24 de 8 de 1983").
    sep = r"(?:\s*[-/.]\s*|\s+de\s+|\s+)"
    m = re.search(rf"(?<!\d)(\d{{1,2}}){sep}(\d{{1,2}}){sep}(\d{{4}}|\d{{2}})(?!\d)", text)
    if not m:
        return _parse_day_month_only(text, today)
    a, b = int(m.group(1)), int(m.group(2))
    year_text = m.group(3)
    year, year_note = (int(year_text), None) if len(year_text) == 4 else _expand_two_digit_year(int(year_text), today)

    if a > 12 >= b:
        return _build(year, b, a, today, year_note)
    if b > 12 >= a:
        return _build(year, a, b, today, _join_notes(
            "Read as month/day (US order) because day/month is impossible.", year_note))
    order_note = None
    if a != b:
        order_note = (f"Ambiguous: read as day/month (Chilean order) = {a} {_month_name(b)}. "
                      f"If this is a US document it may be {b} {_month_name(a)}.")
    return _build(year, b, a, today, _join_notes(order_note, year_note))


def _parse_day_month_only(text: str, today: date) -> ParsedDate | None:
    """"30/5", "6/14": a day and month with no year. Returned as a partial
    (month, day) so the page's own date can supply the year, with a note.
    "4/77" is a month and a two-digit year instead."""
    m = re.fullmatch(r"\D*?(\d{1,2})\s*[-/.]\s*(\d{1,2})\D*", text)
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    no_year = "No year is written in this date. Check the document and enter it by hand."
    if b > 31 and 1 <= a <= 12:
        year, _ = _expand_two_digit_year(b, today)
        return ParsedDate(None, f"Only the month and year ({_month_name(a)} {year}) are given. "
                                f"Enter the full date by hand if the document shows it elsewhere.")
    if a > 12 >= b >= 1 and a <= 31:
        return ParsedDate(None, no_year, month=b, day=a)
    if b > 12 >= a >= 1 and b <= 31:
        return ParsedDate(None, _join_notes(no_year, "Read as month/day (US order) because day/month is impossible."),
                          month=a, day=b)
    if 1 <= a <= 12 and 1 <= b <= 12:
        note = None if a == b else (f"Ambiguous: read as day/month (Chilean order) = {a} {_month_name(b)}. "
                                    f"If this is a US document it may be {b} {_month_name(a)}.")
        return ParsedDate(None, _join_notes(no_year, note), month=b, day=a)
    return None


def _parse_year_only(text: str) -> ParsedDate | None:
    """"1985", "the year 1985", "año mil novecientos ochenta y cinco": a year
    with nothing else. Never turned into a full date."""
    digits = re.findall(r"\d+", text)
    year = None
    if len(digits) == 1 and len(digits[0]) == 4:
        year = int(digits[0])
    elif not digits:
        words = [t for t in re.findall(r"[a-z]+", text) if t not in FILLER_WORDS and t not in ("the", "year")]
        if words and all(_is_number_token(w) for w in words):
            year = _words_to_number(words)
    if year is None or not MIN_YEAR <= year <= 2100:
        return None
    return ParsedDate(None, f"Only the year ({year}) is given. Enter the full date by hand if the document "
                            f"shows it elsewhere.")


def _month_name(month: int) -> str:
    return date(2000, month, 1).strftime("%B")


def _parse_with_month_name(text: str, today: date) -> ParsedDate | None:
    tokens = [_strip_ordinal(t) for t in re.findall(r"\d+[a-z]*|[a-z]+", text)]
    month_index = next((i for i, t in enumerate(tokens) if t in MONTHS), None)
    if month_index is None:
        return None
    month = MONTHS[tokens[month_index]]

    # Day: number tokens immediately before the month, skipping filler words.
    day = None
    i = month_index - 1
    while i >= 0 and tokens[i] in FILLER_WORDS:
        i -= 1
    day_words: list[str] = []
    while i >= 0 and _is_number_token(tokens[i]):
        day_words.insert(0, tokens[i])
        i -= 1
    if len(day_words) == 1 and day_words[0].isdigit():
        day = int(day_words[0])
    elif day_words:
        day = _words_to_number(day_words)

    # Year (and the day too, for "August 24, 1983"): tokens after the month.
    after = [t for t in tokens[month_index + 1:] if t not in FILLER_WORDS]
    year = None
    year_note = None
    if day is None and after and after[0].isdigit() and len(after[0]) <= 2:
        day = int(after.pop(0))
    if after and after[0].isdigit():
        if len(after[0]) == 4:
            year = int(after[0])
        elif len(after[0]) == 2:
            year, year_note = _expand_two_digit_year(int(after[0]), today)
    elif after:
        year_words: list[str] = []
        for t in after:
            if not _is_number_token(t):
                break
            year_words.append(t)
        year = _words_to_number(year_words) if year_words else None

    if year is None:
        has_day = day is not None and 1 <= day <= 31
        return ParsedDate(None, "No year found in this date. Check the document and enter it by hand.",
                          month=month if has_day else None, day=day if has_day else None)
    if day is None or not 1 <= day <= 31:
        return ParsedDate(None, f"Only the month and year ({_month_name(month)} {year}) are given. "
                                f"Enter the full date by hand if the document shows it elsewhere.")
    return _build(year, month, day, today, year_note)


def parse_document_date(raw: str | None, today: date | None = None) -> ParsedDate:
    """Best-effort, never-invent parse of a date as written in a document."""
    if raw is None or not str(raw).strip():
        return ParsedDate(None)
    today = today or date.today()
    text = _fold(str(raw)).strip().rstrip(".")

    result = _parse_numeric(text, today)
    if result is not None:
        return result
    result = _parse_with_month_name(text, today)
    if result is not None:
        return result
    result = _parse_year_only(text)
    if result is not None:
        return result
    return ParsedDate(None, UNREADABLE_NOTE)


def normalize_date_entry(entry: dict) -> dict:
    """Normalize one extracted {"label", "date"} entry in place-safe fashion:
    'date' becomes ISO (or None), the original wording is kept in 'raw'
    whenever it differs, and any ambiguity/assumption goes in 'note'."""
    raw = entry.get("raw") or entry.get("date")
    parsed = parse_document_date(raw)
    iso = parsed.value.isoformat() if parsed.value else None
    normalized = dict(entry)
    normalized["date"] = iso
    normalized["raw"] = raw if raw and raw != iso else None
    normalized["note"] = parsed.note
    return normalized


def normalize_date_entries(entries: list[dict]) -> list[dict]:
    """Normalize every date read from one page. A date written without a year
    ("May 22nd") takes the year of the page's own date (a letter's date line)
    when there is one, with a note asking the reviewer to confirm it."""
    normalized = [normalize_date_entry(e) for e in entries]
    context_year = next(
        (int(e["date"][:4]) for e in normalized if e.get("label") == "document_date" and e.get("date")),
        None,
    )
    if context_year is None:
        return normalized

    for entry in normalized:
        if entry["date"] is not None:
            continue
        parsed = parse_document_date(entry.get("raw"))
        if parsed.month and parsed.day:
            try:
                entry["date"] = date(context_year, parsed.month, parsed.day).isoformat()
            except ValueError:
                continue
            order = next((part for part in ("Ambiguous", "Read as month/day") if part in (parsed.note or "")), None)
            order_note = parsed.note[parsed.note.index(order):] if order else None
            entry["note"] = _join_notes(
                f"No year is written here; {context_year} was taken from the document's own date. "
                f"Confirm against the page.", order_note)
    return normalized


def renormalize_unreviewed(db) -> int:
    """Re-interpret dates already read from documents not yet committed,
    using the original wording kept in each entry ("raw"), so improvements to
    this parser reach existing readings without reading the documents again.
    Reviewed (committed) documents are never changed."""
    from app.models.models import Document  # local import: models import nothing from here

    changed = 0
    for document in db.query(Document).filter(Document.committed.is_(False)).all():
        extraction = document.raw_extraction
        if not extraction or not extraction.get("dates"):
            continue
        dates = normalize_date_entries(extraction["dates"])
        if dates != extraction["dates"]:
            document.raw_extraction = {**extraction, "dates": dates}  # reassign so the JSON change is saved
            changed += 1
    if changed:
        db.commit()
    return changed
