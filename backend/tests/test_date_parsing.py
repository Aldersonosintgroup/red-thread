from datetime import date

import pytest

from app.services.date_parsing import normalize_date_entries, normalize_date_entry, parse_document_date

TODAY = date(2026, 10, 9)


@pytest.mark.parametrize("raw, expected", [
    ("1983-08-24", date(1983, 8, 24)),
    ("1983-08-24T00:00:00", date(1983, 8, 24)),
    ("1983/08/24", date(1983, 8, 24)),
    ("24/08/1983", date(1983, 8, 24)),
    ("24-08-1983", date(1983, 8, 24)),
    ("24.08.1983", date(1983, 8, 24)),
    ("24 de agosto de 1983", date(1983, 8, 24)),
    ("24 de Agosto de 1983", date(1983, 8, 24)),
    ("24 AGOSTO 1983", date(1983, 8, 24)),
    ("24-AGO-1983", date(1983, 8, 24)),
    ("1º de diciembre de 1984", date(1984, 12, 1)),
    ("primero de mayo de 1986", date(1986, 5, 1)),
    ("veinticuatro de agosto de mil novecientos ochenta y tres", date(1983, 8, 24)),
    ("a veinticuatro días del mes de agosto de mil novecientos ochenta y tres", date(1983, 8, 24)),
    ("A LOS DIECISÉIS DÍAS DEL MES DE SETIEMBRE DEL AÑO MIL NOVECIENTOS OCHENTA Y CUATRO", date(1984, 9, 16)),
    ("treinta y uno de diciembre de mil novecientos setenta y nueve", date(1979, 12, 31)),
    ("August 24, 1983", date(1983, 8, 24)),
    ("August 24th, 1983", date(1983, 8, 24)),
    ("24 August 1983", date(1983, 8, 24)),
    ("Santiago, 24 de agosto de 1983.", date(1983, 8, 24)),
    ("fecha: 24/08/1983", date(1983, 8, 24)),
])
def test_parses_real_world_formats(raw, expected):
    assert parse_document_date(raw, TODAY).value == expected


def test_unambiguous_iso_and_day_first_carry_no_note():
    assert parse_document_date("1983-08-24", TODAY).note is None
    assert parse_document_date("24/08/1983", TODAY).note is None
    assert parse_document_date("24 de agosto de 1983", TODAY).note is None


def test_us_order_detected_when_day_first_impossible():
    result = parse_document_date("08/24/1983", TODAY)
    assert result.value == date(1983, 8, 24)
    assert "US order" in result.note


def test_ambiguous_numeric_date_is_flagged_not_silently_guessed():
    result = parse_document_date("03/04/1985", TODAY)
    assert result.value == date(1985, 4, 3)  # Chilean day/month default
    assert result.note and "Ambiguous" in result.note


def test_same_day_and_month_is_not_ambiguous():
    result = parse_document_date("05/05/1985", TODAY)
    assert result.value == date(1985, 5, 5)
    assert result.note is None


def test_unambiguous_two_digit_year_needs_no_warning():
    result = parse_document_date("24/08/83", TODAY)  # 2083 is in the future
    assert result.value == date(1983, 8, 24)
    assert result.note is None


def test_two_digit_year_that_could_be_either_century_is_noted():
    result = parse_document_date("24/08/05", TODAY)
    assert result.value == date(2005, 8, 24)
    assert "1905" in result.note


@pytest.mark.parametrize("raw", [
    "agosto de 1983",                # month/year only — never invent a day
    "1985",
    "illegible",
    "31/02/1985",                   # not a real calendar date
    "24 de agosto",                  # no year
    "24/08/1783",                   # implausible year
])
def test_incomplete_or_invalid_dates_return_none_with_a_note(raw):
    result = parse_document_date(raw, TODAY)
    assert result.value is None
    assert result.note


def test_empty_input_returns_none_without_note():
    assert parse_document_date(None, TODAY).value is None
    assert parse_document_date("", TODAY).note is None


def test_normalize_entry_keeps_original_wording():
    entry = normalize_date_entry({"label": "birth", "date": "24 de agosto de 1983"})
    assert entry == {"label": "birth", "date": "1983-08-24", "raw": "24 de agosto de 1983", "note": None}


def test_normalize_entry_drops_raw_when_already_iso():
    entry = normalize_date_entry({"label": "birth", "date": "1983-08-24"})
    assert entry["raw"] is None


def test_normalize_entry_unreadable_keeps_raw_and_explains():
    entry = normalize_date_entry({"label": "decree_issued", "date": "[illegible]"})
    assert entry["date"] is None
    assert entry["raw"] == "[illegible]"
    assert entry["note"]


def test_yearless_date_takes_year_from_document_date_with_note():
    entries = normalize_date_entries([
        {"label": "document_date", "date": "June 3, 1985"},
        {"label": "other", "date": "May 22nd"},
        {"label": "other", "date": "October"},
    ])
    assert entries[0]["date"] == "1985-06-03" and entries[0]["note"] is None
    assert entries[1]["date"] == "1985-05-22"
    assert "1985" in entries[1]["note"] and "Confirm" in entries[1]["note"]
    assert entries[2]["date"] is None  # month alone: still never invented


def test_yearless_date_left_empty_without_a_document_date():
    entries = normalize_date_entries([{"label": "other", "date": "May 22nd"}])
    assert entries[0]["date"] is None and entries[0]["note"]


# Real values from a re-read of a case file that the first parser missed.
@pytest.mark.parametrize("raw, expected", [
    ("21 6 85", date(1985, 6, 21)),
    ("28 5 85", date(1985, 5, 28)),
    ("21. 6 85", date(1985, 6, 21)),
    ("17 5 85", date(1985, 5, 17)),
    ("24 de 8 de 1983", date(1983, 8, 24)),
    ("13 de 5 de 1985", date(1985, 5, 13)),
])
def test_stamp_and_numeric_spanish_formats(raw, expected):
    assert parse_document_date(raw, TODAY).value == expected


@pytest.mark.parametrize("raw, year", [
    ("1985", 1985), ("the year 1985", 1985), ("año mil novecientos ochenta y cinco", 1985), ("1966", 1966),
])
def test_year_only_is_never_completed_but_explained(raw, year):
    result = parse_document_date(raw, TODAY)
    assert result.value is None and f"Only the year ({year})" in result.note


@pytest.mark.parametrize("raw, month, day, us_order", [
    ("30/5", 5, 30, False), ("6/14", 6, 14, True), ("8/24", 8, 24, True),
])
def test_day_month_without_year_is_partial(raw, month, day, us_order):
    result = parse_document_date(raw, TODAY)
    assert result.value is None and (result.month, result.day) == (month, day)
    assert ("US order" in result.note) == us_order


def test_month_and_two_digit_year():
    result = parse_document_date("4/77", TODAY)
    assert result.value is None and "April 1977" in result.note


def test_partial_date_takes_document_year_and_keeps_order_note():
    entries = normalize_date_entries([{"label": "document_date", "date": "June 3, 1985"},
                                      {"label": "other", "date": "6/14"}])
    assert entries[1]["date"] == "1985-06-14"
    assert "1985 was taken" in entries[1]["note"] and "US order" in entries[1]["note"]


@pytest.mark.parametrize("raw", ["15 5 8", "Santiago, 24 de", "24 de ... de 1985", "day of ________, 198"])
def test_truly_incomplete_values_stay_unread(raw):
    assert parse_document_date(raw, TODAY).value is None
