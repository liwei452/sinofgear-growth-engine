import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


CURRENT_LEAF_MIGRATIONS = {
    ("growth", "0050_email_verification_pipeline"),
    ("campaigns", "0004_contentbrief_knowledge_context_snapshot"),
    ("content", "0006_content_knowledge_context_snapshot"),
}
PREVIOUS_MIGRATIONS = {
    ("growth", "0048_alter_missionentitylink_entity_type"),
    ("campaigns", "0003_contentbrief_archived_at_contentbrief_archived_by_and_more"),
    ("content", "0005_mastercontent_archived_at_mastercontent_archived_by_and_more"),
}


def _latest_targets():
    executor = MigrationExecutor(connection)
    return executor.loader.graph.leaf_nodes()


@pytest.mark.django_db(transaction=True)
def test_agent_context_migrations_reverse_and_reapply_without_losing_rows(
    content_provenance,
):
    from apps.content.models import MasterContent, PlatformContent, content_writes
    from apps.growth.models import AgentRun, OutreachDraft, TargetAccount

    organization, actor, brief, _, run = content_provenance
    master = MasterContent.objects.get(ai_run=run)
    platform = brief.platform_links.select_related("platform").get().platform
    with content_writes():
        platform_content = PlatformContent.objects.create(
            organization=organization,
            master_content=master,
            master_version=master.version,
            platform=platform,
            payload={
                "title": "Migration marker",
                "body": "Migration marker body",
                "cta": "Review",
                "concept_codes": [],
                "platform_code": platform.code,
            },
            provenance={},
            status=PlatformContent.Status.DRAFT,
            created_by=actor,
        )
    account = TargetAccount.objects.create(
        organization=organization,
        name="Migration target",
        country="DE",
    )
    draft = OutreachDraft.objects.create(
        organization=organization,
        account=account,
        english_draft="Migration draft",
        chinese_explanation="Migration explanation",
    )
    agent_run = AgentRun.objects.create(
        organization=organization,
        idempotency_key="migration-agent-context",
        goal="migration round trip",
    )
    markers = {
        "growth.AgentRun": agent_run.id,
        "growth.OutreachDraft": draft.id,
        "campaigns.ContentBrief": brief.id,
        "content.MasterContent": master.id,
        "content.PlatformContent": platform_content.id,
    }
    latest = _latest_targets()
    assert CURRENT_LEAF_MIGRATIONS <= set(latest)
    previous = [target for target in latest if target not in CURRENT_LEAF_MIGRATIONS]
    previous.extend(sorted(PREVIOUS_MIGRATIONS))

    try:
        executor = MigrationExecutor(connection)
        executor.migrate(previous)
        old_apps = executor.loader.project_state(previous).apps
        for label, object_id in markers.items():
            app_label, model_name = label.split(".")
            model = old_apps.get_model(app_label, model_name)
            assert model.objects.filter(pk=object_id).exists()
            assert "knowledge_context_snapshot" not in {
                field.name for field in model._meta.get_fields()
            }

        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        current_apps = executor.loader.project_state(
            executor.loader.graph.leaf_nodes()
        ).apps
        for label, object_id in markers.items():
            app_label, model_name = label.split(".")
            model = current_apps.get_model(app_label, model_name)
            row = model.objects.get(pk=object_id)
            assert row.knowledge_context_snapshot_id is None
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
