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


def test_canonical_url_preserves_safe_unicode_as_stable_idna_utf8_uri():
    assert build_canonical_url(
        "https://例子.测试/齿轮?名称=精密#规格",
        source="领英",
        medium="社交",
        campaign="齿轮 发布",
    ) == (
        "https://xn--fsqu00a.xn--0zwm56d/%E9%BD%BF%E8%BD%AE?"
        "%E5%90%8D%E7%A7%B0=%E7%B2%BE%E5%AF%86&"
        "utm_source=%E9%A2%86%E8%8B%B1&utm_medium=%E7%A4%BE%E4%BA%A4&"
        "utm_campaign=%E9%BD%BF%E8%BD%AE-%E5%8F%91%E5%B8%83#%E8%A7%84%E6%A0%BC"
    )


def test_canonical_url_collapses_literal_and_encoded_nfc_nfd_equivalents():
    expected = (
        "https://example.com/caf%C3%A9?q=r%C3%A9sum%C3%A9&"
        "utm_source=linkedin&utm_medium=social&utm_campaign=launch#d%C3%A9tail"
    )
    destinations = [
        "https://example.com/café?q=résumé#détail",
        "https://example.com/cafe\u0301?q=re\u0301sume\u0301#de\u0301tail",
        "https://example.com/caf%C3%A9?q=r%C3%A9sum%C3%A9#d%C3%A9tail",
        "https://example.com/cafe%CC%81?q=re%CC%81sume%CC%81#de%CC%81tail",
    ]
    assert {
        build_canonical_url(
            destination, source="linkedin", medium="social", campaign="launch"
        )
        for destination in destinations
    } == {expected}


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
        "https://example.com/%00hidden",
        "https://example.com/path?next=%0D%0Aheader",
        "https://example.com/path#bad%7Ffragment",
        "https://example.com/%",
        "https://example.com/%GG",
        "https://example.com/%FF",
        "https://example.com/?q=%C3%28",
        "https://[2606:4700:4700::1111%25eth0]/",
    ],
)
def test_canonical_url_rejects_unsafe_destinations_and_utm_conflicts(url):
    with pytest.raises(ValidationError):
        build_canonical_url(
            url, source="linkedin", medium="social", campaign="launch"
        )
