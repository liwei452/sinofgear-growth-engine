from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .authenticity import SourceAuthenticity, SourceCapability


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SourceRecord:
    source: str
    capability: SourceCapability
    authenticity: SourceAuthenticity
    confidence: float
    evidence: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)
    usage_rights: str = ""
    observed_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.authenticity is SourceAuthenticity.SYNTHETIC:
            raise ValueError("SYNTHETIC records cannot be produced.")
