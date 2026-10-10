from app.services.dedup import normalize_name
from rapidfuzz import fuzz


def score(a: str, b: str) -> float:
    return fuzz.token_set_ratio(normalize_name(a), normalize_name(b))


def test_reordered_name_scores_high():
    # Last-name-first (as on many official forms) vs natural order.
    assert score("RIVERA-SOTO, ANA LUCIA", "Ana Lucia Rivera-Soto") >= 90


def test_partial_name_missing_surname_scores_high():
    # One document captured the full name, another only a partial mention.
    assert score("Clara Fuentes", "Clara Fuentes Rojas") >= 85


def test_hyphenated_surname_matches_space_separated():
    assert score("Rivera-Soto", "Rivera Soto") >= 95


def test_genuinely_different_names_score_low():
    assert score("Clara Fuentes Rojas", "Pedro Alvarez Mena") < 50


def test_normalize_name_strips_punctuation_and_hyphens():
    assert normalize_name("Rivera-Soto, Ana.") == "RIVERA SOTO ANA"
