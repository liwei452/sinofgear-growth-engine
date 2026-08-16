from apps.growth.taxonomy import (
    classify_industry,
    classify_need,
    landing_page_path,
    landing_page_url,
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
