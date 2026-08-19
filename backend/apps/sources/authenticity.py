from enum import StrEnum


class SourceAuthenticity(StrEnum):
    REAL = "REAL"
    DERIVED = "DERIVED"
    SYNTHETIC = "SYNTHETIC"


class SourceCapability(StrEnum):
    DISCOVER = "DISCOVER"
    RESEARCH = "RESEARCH"
    ENRICH = "ENRICH"
    VERIFY = "VERIFY"
