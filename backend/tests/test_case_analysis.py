import asyncio
import re

import pytest

from app.core import config, database_lifecycle, db, vault
from app.data.seed import create_sample_case
from app.models.models import Document
from app.services import case_analysis
from app.services.case_analysis import AnalysisError, build_dossier, check_citations, generate_analysis


@pytest.fixture
def sample_case(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    vault.lock()
    database_lifecycle.open_database()
    session = db.SessionLocal()
    case = create_sample_case(session)
    yield session, case
    session.close()
    db.close_engine()


def test_dossier_cites_everything_and_only_reviewed_documents(sample_case):
    session, case = sample_case
    session.add(Document(case_id=case.id, filename="unreviewed.jpg", filepath="", upload_order=50,
                         status="extracted", committed=False,
                         raw_extraction={"names": [{"name": "Unreviewed Person", "role": None}]}))
    session.commit()
    session.refresh(case)

    text, valid, count = build_dossier(case)
    assert count == 5  # the five committed sample documents
    assert "Unreviewed Person" not in text and "unreviewed.jpg" not in text
    for prefix in ("D", "E", "A", "F", "X", "T"):
        assert any(v.startswith(prefix) for v in valid), prefix
    assert set(re.findall(r"^\[([DEAFXT]\d+)\]", text, re.M)) == valid
    assert "Lucía Fernanda Ejemplo Ramos" in text and "RED tier" in text


def test_invented_citations_are_removed_and_flagged():
    report = {
        "established_facts": [
            {"statement": "real", "sources": ["D1", "[E2]"]},
            {"statement": "invented", "sources": ["D99"]},
        ],
        "hypotheses": [{"supporting_evidence": [{"statement": "s", "sources": ["F1", "Z7"]}],
                        "contradicting_evidence": []}],
    }
    result = check_citations(report, {"D1", "E2", "F1"})
    assert result == {"removed_invalid_citations": 2, "unsupported_statements": 1}
    assert report["established_facts"][0] == {"statement": "real", "sources": ["D1", "E2"], "unsupported": False}
    assert report["established_facts"][1]["unsupported"] is True
    assert report["hypotheses"][0]["supporting_evidence"][0]["sources"] == ["F1"]


def test_analysis_refuses_the_local_engine(sample_case, monkeypatch):
    _, case = sample_case
    monkeypatch.setattr(case_analysis.settings, "ai_provider", "ollama")
    with pytest.raises(AnalysisError, match="needs a cloud AI"):
        asyncio.run(generate_analysis(case, "en"))


def test_analysis_rejects_unknown_language(sample_case):
    _, case = sample_case
    with pytest.raises(AnalysisError, match="Language"):
        asyncio.run(generate_analysis(case, "fr"))
