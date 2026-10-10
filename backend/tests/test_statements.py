import re

import pytest
from fastapi.testclient import TestClient

from app.core import config, database_lifecycle, db, vault
from app.data.seed import create_sample_case
from app.main import app
from app.services.case_analysis import build_dossier, check_citations


@pytest.fixture
def client_and_case(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    vault.lock()
    database_lifecycle.open_database()
    session = db.SessionLocal()
    case = create_sample_case(session)
    yield TestClient(app, base_url="http://127.0.0.1:8420"), session, case
    session.close()
    db.close_engine()


TESTIMONY = {
    "kind": "testimony",
    "statement": "She said she knew at the time the adoption was arranged through a black-market broker.",
    "source_name": "Ellen Sampleton",
    "source_relationship": "adoptive mother",
    "statement_date": "2026-01-15",
    "method": "recorded phone interview",
    "basis": "firsthand",
    "status": "unverified",
    "flag_severity": "HIGH",
}


def _first_doc_id(client, case_id):
    return client.get(f"/api/cases/{case_id}/documents").json()[0]["id"]


def test_testimony_raises_the_chosen_flag_without_changing_the_document_score(client_and_case):
    client, _, case = client_and_case
    score_before = client.get(f"/api/cases/{case.id}/score").json()["total_score"]

    created = client.post(f"/api/cases/{case.id}/statements", json=TESTIMONY)
    assert created.status_code == 201, created.text

    flags = client.get(f"/api/cases/{case.id}/flags").json()
    mine = [f for f in flags if f["flag_type"] == "INVESTIGATOR_FINDING" and f["title"].startswith("Testimony: She said")]
    assert len(mine) == 1 and mine[0]["severity"] == "HIGH"
    assert mine[0]["title"].startswith("Testimony: She said")
    assert "adoptive mother" in mine[0]["description"] and "recorded phone interview" in mine[0]["description"]
    assert client.get(f"/api/cases/{case.id}/score").json()["total_score"] == score_before


def test_finding_links_only_this_cases_documents_and_drops_testimony_basis(client_and_case):
    client, _, case = client_and_case
    doc_id = _first_doc_id(client, case.id)
    body = {"kind": "finding", "statement": "DNA test shows the woman named as mother is not the birth mother.",
            "source_name": "Investigator", "method": "DNA test", "status": "verified", "basis": "firsthand",
            "relation": "contradicts", "related_document_ids": [doc_id, "not-a-real-document"]}
    s = client.post(f"/api/cases/{case.id}/statements", json=body).json()
    assert s["related_document_ids"] == [doc_id]
    assert s["basis"] is None
    assert s["flag_severity"] is None
    assert not [f for f in client.get(f"/api/cases/{case.id}/flags").json() if "DNA test shows the woman named" in f["title"]]


def test_editing_and_deleting_update_the_flags(client_and_case):
    client, _, case = client_and_case
    s = client.post(f"/api/cases/{case.id}/statements", json=TESTIMONY).json()
    changed = {**TESTIMONY, "flag_severity": "CRITICAL", "status": "corroborated"}
    assert client.put(f"/api/cases/{case.id}/statements/{s['id']}", json=changed).json()["status"] == "corroborated"
    mine = lambda: [f["severity"] for f in client.get(f"/api/cases/{case.id}/flags").json()  # noqa: E731
                    if f["title"].startswith("Testimony: She said")]
    assert mine() == ["CRITICAL"]

    assert client.delete(f"/api/cases/{case.id}/statements/{s['id']}").status_code == 204
    assert s["id"] not in [x["id"] for x in client.get(f"/api/cases/{case.id}/statements").json()]
    assert mine() == []


def test_invalid_input_is_rejected(client_and_case):
    client, _, case = client_and_case
    assert client.post(f"/api/cases/{case.id}/statements", json={**TESTIMONY, "statement": "   "}).status_code == 422
    assert client.post(f"/api/cases/{case.id}/statements", json={**TESTIMONY, "kind": "rumor"}).status_code == 422
    assert client.post(f"/api/cases/{case.id}/statements", json={**TESTIMONY, "flag_severity": "HUGE"}).status_code == 422


def test_statements_reach_the_analysis_as_citable_and_labeled_evidence(client_and_case):
    client, session, case = client_and_case
    doc_id = _first_doc_id(client, case.id)
    client.post(f"/api/cases/{case.id}/statements", json=TESTIMONY)
    client.post(f"/api/cases/{case.id}/statements", json={
        "kind": "finding", "statement": "Registry check: no birth registered under the listed mother's name.",
        "source_name": "Investigator", "method": "civil registry search", "status": "verified",
        "relation": "contradicts", "related_document_ids": [doc_id]})
    session.expire_all()
    text, valid, _ = build_dossier(case)
    assert {"T1", "T2", "T3", "T4"} <= valid  # two from the sample case, two added here
    assert re.search(r"^\[T3\] TESTIMONY \| \"She said.*said by Ellen Sampleton \(adoptive mother\).*basis: firsthand", text, re.M)
    assert re.search(r"^\[T4\] VERIFIED FINDING \|.*how: civil registry search.*contradicts D1", text, re.M)
    report = {"established_facts": [{"statement": "x", "sources": ["T4", "T9"]}], "hypotheses": []}
    assert check_citations(report, valid)["removed_invalid_citations"] == 1


def test_statements_appear_in_both_exports(client_and_case):
    client, _, case = client_and_case
    client.post(f"/api/cases/{case.id}/statements", json=TESTIMONY)
    exported = client.get(f"/api/cases/{case.id}/export/json").json()
    assert any(x["statement"].startswith("She said") and x["source_relationship"] == "adoptive mother"
               for x in exported["statements"])
    pdf = client.get(f"/api/cases/{case.id}/export/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
