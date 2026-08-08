import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_openapi_schema_is_available() -> None:
    response = APIClient().get("/api/v1/schema")
    assert response.status_code == 200
    assert response.json()["openapi"].startswith("3.")
