import pytest
from django.core.exceptions import ValidationError

from apps.tracking.services import build_canonical_url, normalize_slug


def test_normalize_slug_has_explicit_unicode_and_separator_policy():
    assert normalize_slug("  齿轮  Launch__2026  ") == "齿轮-launch-2026"
    assert normalize_slug("Ｇｅａｒ　SALE") == "gear-sale"


@pytest.mark.parametrize("value", ["", "---", "a" * 129, "gear/launch"])
def test_normalize_slug_rejects_blank_oversized_or_unsafe_values(value):
    with pytest.raises(ValidationError):
        normalize_slug(value)


def test_canonical_url_preserves_safe_query_and_fragment_with_stable_utm_order():
    assert build_canonical_url(
        "https://Example.COM/shop?z=2&a=1#details",
        source="linkedin",
        medium="social",
        campaign="gear launch",
        content="hero post",
        term="precision gear",
    ) == (
        "https://example.com/shop?a=1&z=2&utm_source=linkedin&utm_medium=social&"
        "utm_campaign=gear-launch&utm_content=hero-post&utm_term=precision-gear#details"
    )


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "https://user:secret@example.com/",
        "https://127.0.0.1/",
        "https://10.0.0.4/",
        "https://localhost/",
        "https://intranet/",
        "https://example.com/?UTM_Source=forged",
        "https://example.com/\nheader",
    ],
)
def test_canonical_url_rejects_unsafe_destinations_and_utm_conflicts(url):
    with pytest.raises(ValidationError):
        build_canonical_url(
            url, source="linkedin", medium="social", campaign="launch"
        )
