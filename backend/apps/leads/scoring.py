from dataclasses import asdict, dataclass


WEIGHTS = {
    "intent": 30,
    "company_fit": 25,
    "specificity": 20,
    "capability_fit": 15,
    "recency": 10,
}


@dataclass(frozen=True, slots=True)
class ScoreDimensions:
    intent: int
    company_fit: int
    specificity: int
    capability_fit: int
    recency: int


@dataclass(frozen=True, slots=True)
class EvidenceGates:
    traceable_source: bool
    explicit_need_or_company_match: bool
    capability_evidence: bool
    audited_run: bool
    ontology_snapshot: bool


@dataclass(frozen=True, slots=True)
class ScoreResult:
    total: int
    band: str
    high_value_eligible: bool


def score_lead(dimensions: ScoreDimensions, gates: EvidenceGates) -> ScoreResult:
    values = asdict(dimensions)
    for name, value in values.items():
        maximum = WEIGHTS[name]
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
            raise ValueError(f"{name} must be between 0 and {maximum}")

    gate_values = asdict(gates)
    for name, value in gate_values.items():
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean")

    total = sum(values.values())
    band = (
        "HIGH"
        if total >= 80
        else "WATCH"
        if total >= 60
        else "OBSERVE"
        if total >= 40
        else "LOW"
    )
    return ScoreResult(
        total=total,
        band=band,
        high_value_eligible=band == "HIGH" and all(gate_values.values()),
    )
