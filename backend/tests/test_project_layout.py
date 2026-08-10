from pathlib import Path

from django.apps import apps


def test_phase_b1_domain_apps_are_registered_with_stage_appropriate_urls() -> None:
    assert apps.get_app_config("sources").name == "apps.sources"
    assert apps.get_app_config("leads").name == "apps.leads"

    from apps.leads.urls import urlpatterns as lead_patterns
    from apps.sources.urls import urlpatterns as source_patterns

    assert lead_patterns == []
    assert [pattern.name for pattern in source_patterns] == [
        "monitoring-targets",
        "ingestion-batches",
        "source-contents",
        "source-signals",
        "source-evidences",
        "source-evidence-detail",
    ]


def test_required_workspace_files_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    required = [
        root / "docker-compose.yml",
        root / ".env.example",
        root / "backend" / "pyproject.toml",
        root / "frontend" / "package.json",
    ]
    assert all(path.is_file() for path in required)


def test_redis_uses_password_from_environment() -> None:
    root = Path(__file__).resolve().parents[2]
    environment = (root / ".env.example").read_text(encoding="utf-8")
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")

    assert "REDIS_PASSWORD=" in environment
    assert "REDIS_URL=redis://:sinofgear_redis_dev_password@redis:6379/0" in environment
    assert "redis-server --requirepass ${REDIS_PASSWORD}" in compose
