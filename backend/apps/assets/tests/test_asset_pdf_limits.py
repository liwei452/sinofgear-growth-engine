from types import SimpleNamespace

import pytest

from apps.assets.understanding import (
    AssetUnderstandingError,
    MAX_EXTRACTED_CHARS,
    MAX_PDF_PAGES,
    _extract_pdf,
)


class TextPage:
    def __init__(self, text: str):
        self.text = text

    def get_contents(self):
        return None

    def extract_text(self):
        return self.text


def test_pdf_page_count_is_rejected_before_text_extraction(monkeypatch) -> None:
    pages = [TextPage("safe") for _ in range(MAX_PDF_PAGES + 1)]
    monkeypatch.setattr(
        "apps.assets.understanding.PdfReader",
        lambda *_args, **_kwargs: SimpleNamespace(pages=pages),
    )

    with pytest.raises(AssetUnderstandingError, match="30 page"):
        _extract_pdf(b"bounded-test")


def test_pdf_extracted_text_is_truncated_at_total_character_limit(monkeypatch) -> None:
    pages = [TextPage("A" * 60_000), TextPage("B" * 60_000), TextPage("C" * 10)]
    monkeypatch.setattr(
        "apps.assets.understanding.PdfReader",
        lambda *_args, **_kwargs: SimpleNamespace(pages=pages),
    )

    extracted, warnings = _extract_pdf(b"bounded-test")

    assert sum(len(page.text) for page in extracted) == MAX_EXTRACTED_CHARS
    assert len(extracted) == 2
    assert warnings
