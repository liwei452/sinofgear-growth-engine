import pytest

from apps.growth.company_resolution import (
    match_company_by_importer,
    normalize_company_name,
    record_trade_company_match,
)
from apps.growth.models import TargetAccount
from apps.identity.models import Organization


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Company resolution", slug="company-resolution")


def test_normalizes_legal_suffixes():
    assert normalize_company_name("ABC Mining Services Pty Ltd") == "abc mining services"
    assert normalize_company_name("PT Mitra Engineering") == "pt mitra engineering"


def test_matches_importer_to_existing_company(organization):
    account = TargetAccount.objects.create(organization=organization, name="ABC Mining Services Pty Ltd", country="ZAF")
    matched, method, confidence = match_company_by_importer(
        organization, "ABC Mining Services", "ZAF",
    )
    assert matched == account
    assert method == "EXACT_NAME"
    assert confidence == 1.0


def test_records_trade_company_match(organization):
    account = TargetAccount.objects.create(organization=organization, name="ABC Mining Services", country="ZAF")
    match = record_trade_company_match(
        organization=organization,
        importer_name="ABC Mining Services",
        country_code="ZAF",
    )
    assert match.account_id == account.id
    assert match.method == "EXACT_NAME"
