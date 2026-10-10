from types import SimpleNamespace

from app.services.discrepancy import build_discrepancy_groups


def _doc(doc_id, birth_date, committed=True):
    return SimpleNamespace(
        id=doc_id, filename=f"{doc_id}.jpg", edited_extraction=None, committed=committed,
        raw_extraction={"names": [], "dates": [{"label": "birth", "date": birth_date}]},
    )


def _birth_group(*dates):
    case = SimpleNamespace(subject=None, documents=[_doc(f"d{i}", d) for i, d in enumerate(dates)])
    return next(g for g in build_discrepancy_groups(case) if g["field"] == "birth_date")


def test_same_date_in_different_formats_is_not_a_contradiction():
    assert _birth_group("24/08/1983", "1983-08-24", "24 de agosto de 1983")["is_contradictory"] is False


def test_different_dates_are_still_a_contradiction():
    assert _birth_group("1983-08-24", "1983-08-25")["is_contradictory"] is True


def test_unreviewed_documents_are_not_compared():
    case = SimpleNamespace(subject=None, documents=[_doc("a", "1983-08-24"), _doc("b", "1983-08-25", committed=False)])
    group = next(g for g in build_discrepancy_groups(case) if g["field"] == "birth_date")
    assert len(group["rows"]) == 1 and group["is_contradictory"] is False
