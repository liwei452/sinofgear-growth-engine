from apps.growth.taxonomy import (
    classify_industry,
    classify_need,
    landing_page_path,
    landing_page_url,
    tracked_landing_url,
)


def test_classifies_industry_and_need():
    assert classify_industry("Mining Equipment Repair") == "mining"
    assert classify_industry("Cement machinery") == "cement"
    assert classify_need("replacement gear for gearbox rebuild") == "replacement"
    assert classify_need("reverse engineer from a broken sample") == "reverse_engineering"
    assert classify_need("OEM production of custom gears") == "oem_production"


def test_landing_page_maps_industry_and_need():
    assert landing_page_path("mining", "replacement") == "/industries/mining/replacement-gears/"
    assert landing_page_url("packaging", "oem_production") == (
        "https://sinfogear.com/industries/packaging/custom-gears/"
    )


def test_tracked_landing_url_includes_utm_and_lead_id():
    url = tracked_landing_url(
        "/industries/mining/replacement-gears/",
        "lead-123",
        source="google_maps",
        campaign="south_africa_mining",
    )
    assert url.startswith("https://sinfogear.com/industries/mining/replacement-gears/?")
    assert "utm_source=google_maps" in url
    assert "utm_campaign=south_africa_mining" in url
    assert "lead_id=lead-123" in url
