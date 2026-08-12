from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "director-concurrency.yml"


def _workflow():
    return yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_director_concurrency_workflow_has_required_triggers_and_postgres_service():
    workflow = _workflow()
    triggers = workflow["on"]
    assert set(triggers) == {"workflow_dispatch", "push", "pull_request"}
    assert triggers["push"]["branches"] == ["feature/phase-b1-lead-intelligence"]
    assert triggers["pull_request"]["branches"] == [
        "feature/phase-b1-lead-intelligence"
    ]

    job = workflow["jobs"]["director-concurrency"]
    assert job["runs-on"] == "ubuntu-latest"
    postgres = job["services"]["postgres"]
    assert postgres["image"] == "postgres:16"
    assert postgres["ports"] == ["5432:5432"]
    assert "pg_isready" in postgres["options"]
    assert postgres["env"] == {
        "POSTGRES_DB": "director_test",
        "POSTGRES_USER": "director_test",
        "POSTGRES_PASSWORD": "director_test",
    }


def test_director_concurrency_workflow_installs_backend_and_runs_exact_pg_suite():
    workflow = _workflow()
    job = workflow["jobs"]["director-concurrency"]
    assert job["env"] == {
        "DIRECTOR_TEST_DATABASE_URL": (
            "postgresql://director_test:director_test@127.0.0.1:5432/director_test"
        ),
        "DJANGO_SETTINGS_MODULE": "config.postgres_test_settings",
    }
    steps = job["steps"]
    assert any(step.get("uses", "").startswith("actions/checkout@") for step in steps)
    assert any(step.get("uses", "").startswith("actions/setup-python@") for step in steps)

    commands = "\n".join(step.get("run", "") for step in steps)
    assert "python -m pip install -e \"./backend[dev]\"" in commands
    assert (
        "python -m pytest apps/director/tests/test_concurrency_postgres.py -q"
        in commands
    )
    test_step = next(step for step in steps if "pytest" in step.get("run", ""))
    assert test_step["working-directory"] == "backend"
