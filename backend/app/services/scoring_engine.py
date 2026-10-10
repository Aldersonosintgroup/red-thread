"""Weighted case irregularity score.

Weights (per spec): timeline 25%, entity match 35%, financial 20%,
contradictions 15%, legal 5%. Each sub-score is 0-100; the total is the
weighted sum, so it's also 0-100.
"""
from app.models.models import Case, Flag, FlagType, FlagSeverity

WEIGHTS = {
    "timeline": 0.25,
    "entity_match": 0.35,
    "financial": 0.20,
    "contradiction": 0.15,
    "legal": 0.05,
}

SEVERITY_POINTS = {
    FlagSeverity.CRITICAL: 50,
    FlagSeverity.HIGH: 30,
    FlagSeverity.MEDIUM: 18,
    FlagSeverity.LOW: 8,
}


def _severity_value(flag: Flag) -> FlagSeverity:
    return flag.severity if isinstance(flag.severity, FlagSeverity) else FlagSeverity(flag.severity)


def _flag_type_value(flag: Flag) -> FlagType:
    return flag.flag_type if isinstance(flag.flag_type, FlagType) else FlagType(flag.flag_type)


def _category_score(flags: list[Flag], flag_types: set[FlagType]) -> float:
    """Sum severity points for matching flags, cap at 100. No flags -> 0."""
    relevant = [f for f in flags if _flag_type_value(f) in flag_types]
    if not relevant:
        return 0.0
    total = sum(SEVERITY_POINTS[_severity_value(f)] for f in relevant)
    return min(100.0, float(total))


def compute_case_score(case: Case) -> dict:
    flags = list(case.flags)

    timeline_score = _category_score(
        flags, {FlagType.TIMELINE_IRREGULARITY, FlagType.PRE_BIRTH_PETITION}
    )
    entity_match_score = _category_score(flags, {FlagType.ENTITY_MATCH})
    financial_score = _category_score(flags, {FlagType.FINANCIAL_ANOMALY})
    contradiction_score = _category_score(flags, {FlagType.CONTRADICTION})
    legal_score = _category_score(flags, {FlagType.LEGAL_VIOLATION})

    total = (
        timeline_score * WEIGHTS["timeline"]
        + entity_match_score * WEIGHTS["entity_match"]
        + financial_score * WEIGHTS["financial"]
        + contradiction_score * WEIGHTS["contradiction"]
        + legal_score * WEIGHTS["legal"]
    )

    return {
        "timeline_score": round(timeline_score, 2),
        "entity_match_score": round(entity_match_score, 2),
        "financial_score": round(financial_score, 2),
        "contradiction_score": round(contradiction_score, 2),
        "legal_score": round(legal_score, 2),
        "total_score": round(total, 2),
    }
