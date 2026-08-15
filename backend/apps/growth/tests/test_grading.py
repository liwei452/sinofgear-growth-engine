from apps.growth.grading import grade_candidate


def test_manufacturer_with_gear_term_scores_high():
    score, grade, breakdown = grade_candidate(
        primary_type="industrial_supplier",
        types=("industrial_supplier", "gearbox_repair_shop"),
        website="https://gearbox.example",
        country="VN",
    )
    assert grade in {"A", "B"}
    assert breakdown["gear_terms"]
    assert breakdown["website_signal"] == 15
    assert score >= 45


def test_unknown_company_scores_low():
    score, grade, _ = grade_candidate(
        primary_type="point_of_interest",
        types=("point_of_interest",),
        website="",
        country="US",
    )
    assert grade == "C"
    assert score < 45
