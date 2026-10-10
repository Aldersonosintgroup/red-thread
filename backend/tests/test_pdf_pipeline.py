import asyncio
import io

import pytest
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from app.schemas.schemas import ExtractionResult
from app.services import queue_processor
from app.services.pdf_pages import (
    MAX_LONG_EDGE, PdfReadError, prepare_image_for_vision, render_pdf_pages,
)
from app.services.vision_extraction import merge_page_results


def _make_pdf(path, pages: int) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    for n in range(1, pages + 1):
        c.drawString(72, 700, f"Pagina {n}: Santiago, 24 de agosto de 1983")
        c.showPage()
    c.save()


def test_render_pdf_pages_returns_one_jpeg_per_page(tmp_path):
    pdf = tmp_path / "case.pdf"
    _make_pdf(pdf, 3)
    rendered = render_pdf_pages(str(pdf), max_pages=40, dpi=150)
    assert rendered.total_pages == 3
    assert len(rendered.images) == 3
    for jpeg in rendered.images:
        with Image.open(io.BytesIO(jpeg)) as img:
            assert img.format == "JPEG"
            assert max(img.size) <= MAX_LONG_EDGE


def test_render_pdf_respects_page_cap(tmp_path):
    pdf = tmp_path / "long.pdf"
    _make_pdf(pdf, 5)
    rendered = render_pdf_pages(str(pdf), max_pages=2, dpi=72)
    assert rendered.total_pages == 5
    assert len(rendered.images) == 2


def test_render_rejects_non_pdf(tmp_path):
    fake = tmp_path / "fake.pdf"
    fake.write_bytes(b"this is not a pdf")
    with pytest.raises(PdfReadError):
        render_pdf_pages(str(fake), max_pages=40, dpi=72)


def test_oversized_image_is_shrunk_but_small_image_untouched():
    big = io.BytesIO()
    Image.new("RGB", (4000, 3000), "white").save(big, format="PNG")
    out, media_type = prepare_image_for_vision(big.getvalue(), "image/png")
    assert media_type == "image/jpeg"
    with Image.open(io.BytesIO(out)) as img:
        assert max(img.size) == MAX_LONG_EDGE

    small = io.BytesIO()
    Image.new("RGB", (800, 600), "white").save(small, format="PNG")
    out, media_type = prepare_image_for_vision(small.getvalue(), "image/png")
    assert out == small.getvalue() and media_type == "image/png"


def test_merge_tags_pages_and_dedupes():
    p1 = ExtractionResult(
        doc_type="decree",
        names=[{"name": "Rosa Mendez Vargas", "role": "Judge"}],
        dates=[{"label": "decree_issued", "date": "1985-05-10", "raw": None, "note": None}],
        legal_references=["Decree 2465"],
        raw_text_notes="Decree page.",
    )
    p2 = ExtractionResult(
        doc_type="other",
        names=[{"name": "ROSA MENDEZ VARGAS", "role": None}, {"name": "Pedro Alvarez", "role": "Attorney"}],
        financial_transactions=[{"amount": "500", "currency": "USD"}],
        legal_references=["decree 2465"],
    )
    merged = merge_page_results([p1, p2], total_pages=2)
    assert merged.doc_type == "decree"
    assert [(n.name, n.page) for n in merged.names] == [("Rosa Mendez Vargas", 1), ("Pedro Alvarez", 2)]
    assert merged.dates[0]["page"] == 1
    assert merged.financial_transactions[0].page == 2
    assert merged.legal_references == ["Decree 2465"]
    assert merged.raw_text_notes == "p.1: Decree page."
    assert merged.parse_warning is None


def test_merge_warns_about_unread_pages_and_groups_repeated_warnings():
    failed = ExtractionResult(parse_warning="AI extraction unavailable: no key")
    merged = merge_page_results([failed, failed, failed], total_pages=10)
    assert "first 3 of 10 pages" in merged.parse_warning
    assert "Pages 1, 2, 3: AI extraction unavailable" in merged.parse_warning
    assert merged.parse_warning.count("AI extraction unavailable") == 1


def test_pdf_document_runs_every_page_through_extraction(tmp_path, monkeypatch):
    pdf = tmp_path / "case.pdf"
    _make_pdf(pdf, 3)
    calls = []

    async def fake_extract(image_bytes, media_type):
        calls.append(media_type)
        return ExtractionResult(dates=[{"label": "birth", "date": "1983-08-24", "raw": "24 de agosto de 1983", "note": None}])

    monkeypatch.setattr(queue_processor, "extract_from_image", fake_extract)
    monkeypatch.setattr(queue_processor.settings, "vision_call_delay_seconds", 0)
    result = asyncio.run(queue_processor._extract_document(str(pdf)))
    assert calls == ["image/jpeg"] * 3
    assert [d["page"] for d in result.dates] == [1, 2, 3]
