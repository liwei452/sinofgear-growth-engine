from django.db import migrations


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    direct = "organization_id = app_current_organization_id()"
    parent = (
        "app_current_organization_id() IS NOT NULL AND EXISTS ("
        "SELECT 1 FROM jobs_job parent WHERE parent.id = job_id "
        "AND parent.organization_id = app_current_organization_id())"
    )
    schema_editor.execute('ALTER TABLE "jobs_job" ENABLE ROW LEVEL SECURITY')
    schema_editor.execute('ALTER TABLE "jobs_job" FORCE ROW LEVEL SECURITY')
    schema_editor.execute(
        'CREATE POLICY "rls_jobs_job_tenant_all" ON "jobs_job" FOR ALL '
        f"USING ({direct}) WITH CHECK ({direct})"
    )
    schema_editor.execute('ALTER TABLE "jobs_jobattempt" ENABLE ROW LEVEL SECURITY')
    schema_editor.execute('ALTER TABLE "jobs_jobattempt" FORCE ROW LEVEL SECURITY')
    schema_editor.execute(
        'CREATE POLICY "rls_jobs_jobattempt_parent_select" ON "jobs_jobattempt" '
        f"FOR SELECT USING ({parent})"
    )
    schema_editor.execute(
        'CREATE POLICY "rls_jobs_jobattempt_parent_insert" ON "jobs_jobattempt" '
        f"FOR INSERT WITH CHECK ({parent})"
    )
    schema_editor.execute(
        'CREATE POLICY "rls_jobs_jobattempt_parent_update" ON "jobs_jobattempt" '
        f"FOR UPDATE USING ({parent}) WITH CHECK ({parent})"
    )
    schema_editor.execute(
        'CREATE POLICY "rls_jobs_jobattempt_parent_delete" ON "jobs_jobattempt" '
        f"FOR DELETE USING ({parent})"
    )


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for operation in ("select", "insert", "update", "delete"):
        schema_editor.execute(
            f'DROP POLICY IF EXISTS "rls_jobs_jobattempt_parent_{operation}" '
            'ON "jobs_jobattempt"'
        )
    schema_editor.execute('DROP POLICY IF EXISTS "rls_jobs_job_tenant_all" ON "jobs_job"')
    for table in ("jobs_job", "jobs_jobattempt"):
        schema_editor.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0005_alter_job_type"),
        ("knowledge", "0008_harden_knowledge_rls_context"),
    ]
    operations = [migrations.RunPython(enable_rls, disable_rls)]
