import pytest

from apps.knowledge.models import KnowledgeGraphLock
from apps.knowledge.tests.conftest import organizations, roles


__all__ = ["organizations", "roles"]


@pytest.fixture(autouse=True)
def ensure_graph_lock(db):
    """Restore migration-seeded singleton after preceding transactional flushes."""
    KnowledgeGraphLock.objects.get_or_create(
        pk=1,
        defaults={"name": "is_a_graph"},
    )
