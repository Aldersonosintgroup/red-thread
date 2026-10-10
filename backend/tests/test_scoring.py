from app.models.models import Case, Flag, FlagType, FlagSeverity
from app.services.scoring_engine import compute_case_score, WEIGHTS


def make_case(flags: list[Flag]) -> Case:
    case = Case(id="test-case")
    case.flags = flags
    return case


def test_no_flags_yields_zero_score():
    case = make_case([])
    score = compute_case_score(case)
    assert score["total_score"] == 0.0
    assert all(v == 0.0 for v in score.values())


def test_single_critical_timeline_flag():
    case = make_case([
        Flag(flag_type=FlagType.TIMELINE_IRREGULARITY, severity=FlagSeverity.CRITICAL,
             title="t", case_id="test-case"),
    ])
    score = compute_case_score(case)
    assert score["timeline_score"] == 50.0
    assert score["entity_match_score"] == 0.0
    expected_total = round(50.0 * WEIGHTS["timeline"], 2)
    assert score["total_score"] == expected_total


def test_category_score_caps_at_100():
    flags = [
        Flag(flag_type=FlagType.FINANCIAL_ANOMALY, severity=FlagSeverity.CRITICAL,
             title="t", case_id="test-case")
        for _ in range(5)
    ]
    case = make_case(flags)
    score = compute_case_score(case)
    assert score["financial_score"] == 100.0


def test_weights_sum_to_full_contribution():
    flags = [
        Flag(flag_type=FlagType.TIMELINE_IRREGULARITY, severity=FlagSeverity.CRITICAL, title="t", case_id="c"),
        Flag(flag_type=FlagType.ENTITY_MATCH, severity=FlagSeverity.CRITICAL, title="t", case_id="c"),
        Flag(flag_type=FlagType.FINANCIAL_ANOMALY, severity=FlagSeverity.CRITICAL, title="t", case_id="c"),
        Flag(flag_type=FlagType.CONTRADICTION, severity=FlagSeverity.CRITICAL, title="t", case_id="c"),
        Flag(flag_type=FlagType.LEGAL_VIOLATION, severity=FlagSeverity.CRITICAL, title="t", case_id="c"),
    ]
    case = make_case(flags)
    score = compute_case_score(case)
    # every category maxed at 50 (one CRITICAL flag each); total should equal 50 * sum(weights) = 50.0
    assert score["total_score"] == 50.0


def test_pre_birth_petition_counts_as_timeline_category():
    case = make_case([
        Flag(flag_type=FlagType.PRE_BIRTH_PETITION, severity=FlagSeverity.CRITICAL, title="t", case_id="c"),
    ])
    score = compute_case_score(case)
    assert score["timeline_score"] == 50.0


def test_severity_points_ordering():
    critical = make_case([Flag(flag_type=FlagType.LEGAL_VIOLATION, severity=FlagSeverity.CRITICAL, title="t", case_id="c")])
    low = make_case([Flag(flag_type=FlagType.LEGAL_VIOLATION, severity=FlagSeverity.LOW, title="t", case_id="c")])
    assert compute_case_score(critical)["legal_score"] > compute_case_score(low)["legal_score"]
