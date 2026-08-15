from apps.growth.evidence import citation, has_citation_keys


def test_citation_builds_standard_shape():
    item = citation(
        value="Mining Equipment Repair",
        confidence=87,
        source="https://abc.example/services",
        evidence="Gearbox rebuilding and crusher repair",
        observed_at="2026-08-16T00:00:00Z",
    )
    assert has_citation_keys(item)
    assert item["confidence"] == 87


def test_has_citation_keys_rejects_missing_fields():
    assert has_citation_keys({"value": "x"}) is False
