from app.services.vision_extraction import _try_parse_json, _heuristic_fallback


def test_parse_clean_json():
    text = '{"doc_type": "petition", "names": [{"name": "Jane Doe", "role": "Petitioner"}], "dates": [], "financial_transactions": [], "legal_references": [], "raw_text_notes": null}'
    parsed = _try_parse_json(text)
    assert parsed is not None
    assert parsed["doc_type"] == "petition"
    assert parsed["names"][0]["name"] == "Jane Doe"


def test_parse_json_wrapped_in_markdown_fences():
    text = '```json\n{"doc_type": "decree", "names": [], "dates": [], "financial_transactions": [], "legal_references": []}\n```'
    parsed = _try_parse_json(text)
    assert parsed is not None
    assert parsed["doc_type"] == "decree"


def test_parse_json_with_surrounding_commentary():
    text = 'Sure, here is the JSON: {"doc_type": "other", "names": [], "dates": [], "financial_transactions": [], "legal_references": []} Let me know if you need more.'
    parsed = _try_parse_json(text)
    assert parsed is not None
    assert parsed["doc_type"] == "other"


def test_parse_invalid_json_returns_none():
    text = "I cannot read this document clearly, it appears blurry."
    assert _try_parse_json(text) is None


def test_parse_bare_json_array_returns_none():
    # A weak vision model can echo the prompt's example schema back as a
    # repeated array of objects instead of a single object. This must be
    # treated as a parse failure (and fall through to the heuristic
    # fallback), not crash with something like "'list' object has no
    # attribute 'get'" when downstream code calls parsed.get(...).
    text = (
        '[{"doc_type": "one of: petition, decree", "names": [{"name": "full name as written"}]}, '
        '{"doc_type": "one of: petition, decree", "names": [{"name": "full name as written"}]}]'
    )
    assert _try_parse_json(text) is None


def test_heuristic_fallback_never_crashes_on_garbage():
    result = _heuristic_fallback("###!!! unparseable nonsense 12345 @@@")
    assert result.parse_warning is not None


def test_heuristic_fallback_extracts_names_and_dates():
    text = "Petitioner John Smith filed on 1985-03-01. Judge Mary Jones presided. Decree 2465 referenced."
    result = _heuristic_fallback(text)
    names = [n.name for n in result.names]
    assert any("John Smith" in name for name in names)
    assert any("Mary Jones" in name for name in names)
    assert any(d["date"] == "1985-03-01" for d in result.dates)
    assert any("Decree" in ref for ref in result.legal_references)


def test_heuristic_fallback_empty_text_does_not_crash():
    result = _heuristic_fallback("")
    assert result.names == []
    assert result.dates == []
