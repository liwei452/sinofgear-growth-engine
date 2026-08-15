import pytest

from apps.growth.models import DiscoveryProfile, DiscoveryRun
from apps.identity.models import Organization


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Discovery models", slug="discovery-models")


def test_profile_is_unique_per_organization_and_has_safe_defaults(organization):
    profile = DiscoveryProfile.objects.create(organization=organization)

    assert profile.enabled is True
    assert profile.source_code == "TED"
    assert profile.result_limit == 20
    assert profile.cpv_codes == [
        "42140000", "42141000", "42141100", "42141200", "42141300",
        "42141400", "42141500", "42141600", "42141700", "42141800",
        "42142000", "42142100", "42142200",
    ]

    with pytest.raises(Exception):
        DiscoveryProfile.objects.create(organization=organization)


def test_discovery_run_history_cannot_be_deleted(organization):
    profile = DiscoveryProfile.objects.create(organization=organization)
    run = DiscoveryRun.objects.create(
        organization=organization,
        profile=profile,
        source_code="TED",
        trigger="MANUAL",
        status="RUNNING",
    )

    with pytest.raises(ValueError, match="cannot be deleted"):
        run.delete()
