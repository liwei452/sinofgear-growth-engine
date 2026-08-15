EVIDENCE_CITATION_KEYS = ("value", "confidence", "source", "evidence", "observed_at")


def citation(*, value, confidence, source, evidence, observed_at, **extra) -> dict:
    return {
        "value": value,
        "confidence": confidence,
        "source": source,
        "evidence": evidence,
        "observed_at": observed_at,
        **extra,
    }


def has_citation_keys(data) -> bool:
    return isinstance(data, dict) and all(key in data for key in EVIDENCE_CITATION_KEYS)
