from pathlib import Path


def test_required_workspace_files_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    required = [
        root / "docker-compose.yml",
        root / ".env.example",
        root / "backend" / "pyproject.toml",
        root / "frontend" / "package.json",
    ]
    assert all(path.is_file() for path in required)
