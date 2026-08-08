import re
import unicodedata


def normalize_alias(value: str, *, language: str) -> str:
    del language
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.casefold()
