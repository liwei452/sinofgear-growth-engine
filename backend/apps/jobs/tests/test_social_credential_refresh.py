def test_refresh_task_delegates_to_bounded_lifecycle_service(monkeypatch):
    organization_id = "00000000-0000-4000-8000-000000000001"
    captured = {}

    def fake_refresh(**kwargs):
        captured.update(kwargs)
        return {"examined": 2, "refreshed": 1, "reauthorization_required": 1, "failed": 0}

    monkeypatch.setattr("apps.jobs.tasks.refresh_due_credentials", fake_refresh)
    def fake_coordinator(operation, *, limit):
        result = operation(__import__("uuid").UUID(organization_id), limit)
        return {"organizations": 1, "consumed": result.consumed, **result.counters}

    monkeypatch.setattr("apps.jobs.tasks.run_tenant_coordinator", fake_coordinator)

    from apps.jobs.tasks import refresh_social_credentials

    result = refresh_social_credentials.run()

    assert result["examined"] == 2
    assert str(captured["organization_id"]) == organization_id
    assert captured["limit"] == 100
