import json
from pathlib import Path
from uuid import UUID

from apps.leads.schemas import lead_analysis_errors
from apps.leads.scoring import evaluate_public_signal


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "lead_evaluation.json"
EVIDENCE_ID = UUID("20000000-0000-4000-8000-000000000001")
ORGANIZATION_ID = UUID("20000000-0000-4000-8000-000000000002")
CATEGORIES = {
    "explicit_need",
    "vague_need",
    "ordinary_engagement",
    "advertisement",
    "recruitment",
    "job_seeker",
    "competitor_supplier_pitch",
    "academic_student",
    "company_page_without_comments",
}


def _fixtures():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _schema_output(result):
    return {
        "company_name": "",
        "company_domain": "",
        "country_hint": "",
        "need_summary_zh": result.normalized_text,
        "need_summary_en": result.normalized_text,
        "dimensions": {
            "intent": result.dimensions.intent,
            "company_fit": result.dimensions.company_fit,
            "specificity": result.dimensions.specificity,
            "capability_fit": result.dimensions.capability_fit,
            "recency": result.dimensions.recency,
        },
        "requirements": [],
        "capability_matches": [],
        "reasons": [
            {"text": result.evidence_spans[0], "evidence_ids": [str(EVIDENCE_ID)]}
        ],
        "confidence": {
            "intent": result.intent_confidence,
            "company_fit": result.company_match_confidence,
            "capability": result.capability_confidence,
        },
        "insufficient_evidence": not result.is_explicit_need,
    }


def _snapshot(text):
    return {
        "candidate": {"company_name": "", "company_domain": "", "country_hint": ""},
        "evidence": [{"id": str(EVIDENCE_ID), "original_text": text}],
        "ontology_snapshot": {"concept_versions": []},
        "capability_bindings": [],
    }


def test_evaluation_fixture_is_complete_bilingual_and_synthetic():
    rows = _fixtures()
    assert len(rows) >= 100
    assert {row["language"] for row in rows} == {"en", "zh"}
    assert {row["category"] for row in rows} == CATEGORIES
    assert len({row["id"] for row in rows}) == len(rows)
    assert all(
        set(row)
        == {
            "id",
            "language",
            "text",
            "category",
            "is_explicit_need",
            "expected_band",
            "company_match_confidence",
            "required_spans",
        }
        and isinstance(row["is_explicit_need"], bool)
        and row["expected_band"] in {"HIGH", "WATCH", "OBSERVE", "LOW"}
        and row["company_match_confidence"] in {"HIGH", "MEDIUM", "LOW"}
        and row["required_spans"]
        and all(
            span.casefold() in row["text"].casefold() for span in row["required_spans"]
        )
        and "@" not in row["text"]
        for row in rows
    )


def test_deterministic_lead_evaluation_meets_quality_gates():
    rows = _fixtures()
    predictions = []
    evidence_valid = []
    for row in rows:
        first = evaluate_public_signal(row["text"], language=row["language"])
        second = evaluate_public_signal(row["text"], language=row["language"])
        assert first == second
        assert first.score.band == row["expected_band"], row["id"]
        assert (
            first.company_match_confidence_class == row["company_match_confidence"]
        ), row["id"]
        predictions.append((row, first))
        output = _schema_output(first)
        evidence_valid.append(
            not lead_analysis_errors(output, snapshot=_snapshot(row["text"]))
            and all(
                any(
                    span.casefold() in cited.casefold()
                    for cited in first.evidence_spans
                )
                for span in row["required_spans"]
            )
        )

    positives = [item for item in predictions if item[0]["is_explicit_need"]]
    high_predictions = [item for item in predictions if item[1].score.band == "HIGH"]
    false_negatives = [
        row["id"] for row, result in positives if not result.is_explicit_need
    ]
    false_positives = [
        row["id"] for row, result in high_predictions if not row["is_explicit_need"]
    ]
    recall = 1 - (len(false_negatives) / len(positives))
    precision = 1 - (len(false_positives) / len(high_predictions))
    evidence_coverage = sum(evidence_valid) / len(evidence_valid)

    assert recall >= 0.90, f"recall={recall:.3f}; false negatives={false_negatives}"
    assert precision >= 0.80, (
        f"precision={precision:.3f}; false positives={false_positives}"
    )
    assert evidence_coverage == 1.00, f"evidence coverage={evidence_coverage:.3f}"
