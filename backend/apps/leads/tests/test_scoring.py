import pytest

from apps.leads.scoring import EvidenceGates, ScoreDimensions, score_lead


def all_evidence_gates(**overrides):
    values = {
        "traceable_source": True,
        "explicit_need_or_company_match": True,
        "capability_evidence": True,
        "audited_run": True,
        "ontology_snapshot": True,
    }
    values.update(overrides)
    return EvidenceGates(**values)


def test_score_uses_approved_weights():
    result = score_lead(
        ScoreDimensions(
            intent=30,
            company_fit=20,
            specificity=18,
            capability_fit=15,
            recency=8,
        ),
        all_evidence_gates(),
    )

    assert result.total == 91
    assert result.band == "HIGH"
    assert result.high_value_eligible is True


@pytest.mark.parametrize(
    ("total", "expected_band"),
    [(100, "HIGH"), (80, "HIGH"), (79, "WATCH"), (60, "WATCH"),
     (59, "OBSERVE"), (40, "OBSERVE"), (39, "LOW"), (0, "LOW")],
)
def test_score_applies_exact_band_boundaries(total, expected_band):
    dimensions = ScoreDimensions(
        intent=min(total, 30),
        company_fit=min(max(total - 30, 0), 25),
        specificity=min(max(total - 55, 0), 20),
        capability_fit=min(max(total - 75, 0), 15),
        recency=min(max(total - 90, 0), 10),
    )

    result = score_lead(dimensions, all_evidence_gates())

    assert result.total == total
    assert result.band == expected_band


def test_high_numeric_score_without_traceable_evidence_is_not_high_value():
    result = score_lead(
        ScoreDimensions(30, 25, 20, 15, 10),
        all_evidence_gates(traceable_source=False),
    )

    assert result.total == 100
    assert result.band == "HIGH"
    assert result.high_value_eligible is False


@pytest.mark.parametrize(
    "missing_gate",
    [
        "traceable_source",
        "explicit_need_or_company_match",
        "capability_evidence",
        "audited_run",
        "ontology_snapshot",
    ],
)
def test_every_evidence_gate_is_required_for_high_value(missing_gate):
    result = score_lead(
        ScoreDimensions(30, 25, 20, 15, 10),
        all_evidence_gates(**{missing_gate: False}),
    )

    assert result.high_value_eligible is False


def test_score_rejects_truthy_non_boolean_evidence_gate():
    gates = all_evidence_gates()
    invalid = EvidenceGates(
        traceable_source="false",
        explicit_need_or_company_match=gates.explicit_need_or_company_match,
        capability_evidence=gates.capability_evidence,
        audited_run=gates.audited_run,
        ontology_snapshot=gates.ontology_snapshot,
    )

    with pytest.raises(ValueError, match=r"^traceable_source must be a boolean$"):
        score_lead(ScoreDimensions(30, 25, 20, 15, 10), invalid)


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "maximum"),
    [
        ("intent", -1, 30),
        ("intent", 31, 30),
        ("company_fit", -1, 25),
        ("company_fit", 26, 25),
        ("specificity", -1, 20),
        ("specificity", 21, 20),
        ("capability_fit", -1, 15),
        ("capability_fit", 16, 15),
        ("recency", -1, 10),
        ("recency", 11, 10),
    ],
)
def test_score_rejects_each_dimension_outside_its_inclusive_bound(
    field_name, invalid_value, maximum
):
    values = {
        "intent": 0,
        "company_fit": 0,
        "specificity": 0,
        "capability_fit": 0,
        "recency": 0,
    }
    values[field_name] = invalid_value

    with pytest.raises(ValueError, match=rf"^{field_name} must be between 0 and {maximum}$"):
        score_lead(ScoreDimensions(**values), all_evidence_gates())
