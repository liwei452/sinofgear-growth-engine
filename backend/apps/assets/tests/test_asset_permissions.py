import pytest
from rest_framework.test import APIClient

from apps.identity.models import Role

from .conftest import create_member_client, png_bytes, upload_payload


@pytest.mark.django_db
def test_anonymous_users_cannot_list_assets() -> None:
    response = APIClient().get("/api/v1/assets")

    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("role_code", "expected_status"),
    [
        (Role.Code.ADMINISTRATOR, 201),
        (Role.Code.OPERATOR, 201),
        (Role.Code.REVIEWER, 403),
        (Role.Code.READ_ONLY, 403),
    ],
)
def test_only_asset_managers_can_upload(
    organizations, roles, role_code, expected_status
) -> None:
    own, _ = organizations
    _, client = create_member_client(
        organization=own,
        role=roles[role_code],
        username=f"upload-{role_code.lower()}",
    )

    response = client.post(
        "/api/v1/assets",
        upload_payload(content=png_bytes(role_code.encode())),
        format="multipart",
    )

    assert response.status_code == expected_status


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role_code",
    [
        Role.Code.ADMINISTRATOR,
        Role.Code.OPERATOR,
        Role.Code.REVIEWER,
        Role.Code.READ_ONLY,
    ],
)
def test_every_builtin_role_can_read_assets(organizations, roles, role_code) -> None:
    own, _ = organizations
    _, client = create_member_client(
        organization=own,
        role=roles[role_code],
        username=f"read-{role_code.lower()}",
    )

    response = client.get("/api/v1/assets")

    assert response.status_code == 200
