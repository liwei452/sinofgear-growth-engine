from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.e2e_paths import validate_e2e_paths


def test_e2e_paths_require_absolute_marked_root_inside_canonical_temp(tmp_path):
    temporary_root = tmp_path.resolve()
    valid_root = temporary_root / "sinofgear-phase-a-e2e-owned"
    valid_root.mkdir()

    validated = validate_e2e_paths(
        valid_root,
        valid_root / "phase-a.sqlite3",
        valid_root / "storage",
        temporary_root=temporary_root,
    )

    assert validated == (
        valid_root.resolve(),
        (valid_root / "phase-a.sqlite3").resolve(),
        (valid_root / "storage").resolve(),
    )
    invalid = [
        (Path("sinofgear-phase-a-e2e-relative"), Path("db.sqlite3"), Path("storage")),
        (
            Path("C:/Windows/sinofgear-phase-a-e2e-reviewer-repro"),
            Path("C:/Windows/sinofgear-phase-a-e2e-reviewer-repro/phase-a.sqlite3"),
            Path("C:/Windows/sinofgear-phase-a-e2e-reviewer-repro/storage"),
        ),
        (
            Path("/var/tmp/sinofgear-phase-a-e2e-arbitrary"),
            Path("/var/tmp/sinofgear-phase-a-e2e-arbitrary/phase-a.sqlite3"),
            Path("/var/tmp/sinofgear-phase-a-e2e-arbitrary/storage"),
        ),
        (temporary_root, temporary_root / "db.sqlite3", temporary_root / "storage"),
        (
            valid_root,
            temporary_root / "outside.sqlite3",
            valid_root / "storage",
        ),
        (
            valid_root,
            valid_root / "phase-a.sqlite3",
            temporary_root / "outside-storage",
        ),
    ]
    for root, database, storage in invalid:
        with pytest.raises(ImproperlyConfigured):
            validate_e2e_paths(root, database, storage, temporary_root=temporary_root)


def test_e2e_paths_reject_canonical_symlink_escape(tmp_path):
    temporary_root = tmp_path / "temp"
    temporary_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    marked_link = temporary_root / "sinofgear-phase-a-e2e-link"
    try:
        marked_link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(ImproperlyConfigured):
        validate_e2e_paths(
            marked_link,
            marked_link / "phase-a.sqlite3",
            marked_link / "storage",
            temporary_root=temporary_root,
        )
