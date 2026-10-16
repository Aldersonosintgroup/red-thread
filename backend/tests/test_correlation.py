"""Cross-case recurring actors. All names are fictional."""
import pytest
from fastapi.testclient import TestClient

from app.core import config, database_lifecycle, db, vault
from app.main import app
from app.models.models import Actor, Case
from app.services.correlation import POSSIBLE, STRONG, compare_names, fold_tokens


def grade(a: str, b: str, same_role: bool = False):
    result = compare_names(fold_tokens(a), fold_tokens(b), same_role)
    return result[0] if result else None


def test_fold_ignores_accents_titles_and_particles():
    assert fold_tokens("Sra. Margarita de la Fictícia") == ("MARGARITA", "FICTICIA")


def test_surname_initial_matches_full_surname_strongly():
    assert grade("Sra. Margarita Ficticia L.", "Margarita Ficticia Lobos") == STRONG


def test_reordered_name_with_accents_is_strong():
    assert grade("FICTÍCIA LOBOS, MARGARITA", "Margarita Ficticia Lobos") == STRONG


def test_misspelled_surname_is_only_possible():
    assert grade("Margarita Fiticia Lobos", "Margarita Ficticia Lobos") == POSSIBLE


def test_two_token_name_needs_same_role_to_be_strong():
    assert grade("Margarita Ficticia", "Margarita Ficticia Lobos") == POSSIBLE
    assert grade("Margarita Ficticia", "Margarita Ficticia Lobos", same_role=True) == STRONG


def test_shared_first_name_or_single_surname_never_links():
    assert grade("Margarita Soto", "Margarita Ficticia Lobos") is None
    assert grade("Ficticia", "Margarita Ficticia Lobos") is None
    assert grade("Pedro Inventado Mena", "Margarita Ficticia Lobos") is None


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    vault.lock()
    database_lifecycle.open_database()
    session = db.SessionLocal()
    yield TestClient(app, base_url="http://127.0.0.1:8420"), session
    session.close()
    db.close_engine()


def _case(session, number, actors):
    case = Case(case_number=number, title=f"Fictional case {number}")
    session.add(case)
    session.flush()
    rows = [Actor(case_id=case.id, canonical_name=name, role=role) for name, role in actors]
    session.add_all(rows)
    session.commit()
    return case, rows


def test_recurring_actor_found_across_four_cases(client):
    api, session = client
    _case(session, "T-1", [("Margarita Ficticia Lobos", "Facilitator"), ("Clínica Santa Ficción", "Hospital")])
    _case(session, "T-2", [("Sra. Margarita Ficticia L.", "Payer")])
    _case(session, "T-3", [("MARGARITA FICTÍCIA LOBOS", "Facilitator")])
    _case(session, "T-4", [("Margarita Ficticia", "Facilitator"), ("Pedro Inventado Mena", "Notary")])
    _case(session, "T-5", [("Margarita Soto", "Witness")])

    clusters = api.get("/api/recurring-actors").json()
    assert len(clusters) == 1
    top = clusters[0]
    assert top["case_count"] == 4
    assert top["tier"] == STRONG
    assert {m["case_number"] for m in top["members"]} == {"T-1", "T-2", "T-3", "T-4"}
    assert {"Facilitator", "Payer"} <= set(top["roles"])


def test_confirm_and_separate_survive_actor_rebuild(client):
    api, session = client
    case_a, (a,) = _case(session, "T-1", [("Margarita Ficticia Lobos", "Facilitator")])
    _, (b,) = _case(session, "T-2", [("Margarita Fiticia Lobos", "Payer")])
    _, (c,) = _case(session, "T-3", [("Margarita Ficticia Lobos", "Facilitator")])

    [cluster] = api.get("/api/recurring-actors").json()
    assert cluster["case_count"] == 3

    api.post("/api/recurring-actors/decisions",
             json={"actor_ids": [b.id], "against": [a.id, c.id], "decision": "rejected"})
    [cluster] = api.get("/api/recurring-actors").json()
    assert {m["actor_id"] for m in cluster["members"]} == {a.id, c.id}

    api.post("/api/recurring-actors/decisions", json={"actor_ids": [a.id, c.id], "decision": "confirmed"})
    assert api.get("/api/recurring-actors").json()[0]["tier"] == "confirmed"

    # Re-read all deletes and recreates actors; decisions are keyed by name, so they stick.
    session.delete(a)
    session.add(Actor(case_id=case_a.id, canonical_name="Margarita Ficticia Lobos", role="Facilitator"))
    session.commit()
    [cluster] = api.get("/api/recurring-actors").json()
    assert cluster["tier"] == "confirmed" and len(cluster["members"]) == 2

    separated = api.get("/api/recurring-actors/separated").json()[0]
    api.delete(f"/api/recurring-actors/separated/{separated['id']}")
    assert api.get("/api/recurring-actors").json()[0]["case_count"] == 3
    assert len(api.get("/api/recurring-actors/separated").json()) == 1


def test_case_view_and_case_delete_cleans_decisions(client):
    api, session = client
    case_a, (a,) = _case(session, "T-1", [("Margarita Ficticia Lobos", "Facilitator")])
    _, (b,) = _case(session, "T-2", [("Margarita Ficticia Lobos", "Facilitator")])
    assert api.get(f"/api/recurring-actors/case/{case_a.id}").json()[a.id]["other_cases"] == 1

    api.post("/api/recurring-actors/decisions", json={"actor_ids": [a.id, b.id], "decision": "confirmed"})
    assert api.delete(f"/api/cases/{case_a.id}").status_code == 204
    assert api.get("/api/recurring-actors").json() == []
    from app.models.models import CrossCaseDecision
    assert session.query(CrossCaseDecision).count() == 0
