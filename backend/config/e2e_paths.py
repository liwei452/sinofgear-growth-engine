import tempfile
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


RUN_MARKER = "sinofgear-phase-a-e2e-"


def _absolute_path(value, *, label):
    path = Path(value)
    if not path.is_absolute():
        raise ImproperlyConfigured(f"Phase A E2E {label} must be an absolute path.")
    return path.resolve(strict=False)


def validate_e2e_paths(run_root, database_path, storage_root, *, temporary_root=None):
    temporary = _absolute_path(
        temporary_root if temporary_root is not None else tempfile.gettempdir(),
        label="temporary root",
    )
    root = _absolute_path(run_root, label="run root")
    database = _absolute_path(database_path, label="database")
    storage = _absolute_path(storage_root, label="storage root")

    if (
        root.parent != temporary
        or not root.name.startswith(RUN_MARKER)
        or root.name == RUN_MARKER
        or not root.is_dir()
    ):
        raise ImproperlyConfigured(
            "Phase A E2E run root must be an existing marked child of the OS temporary root."
        )
    if database.parent != root or database.name != "phase-a.sqlite3":
        raise ImproperlyConfigured(
            "Phase A E2E database must be the dedicated absolute file inside the run root."
        )
    if storage != root / "storage":
        raise ImproperlyConfigured(
            "Phase A E2E storage must be the dedicated absolute directory inside the run root."
        )
    return root, database, storage
