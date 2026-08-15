def test_refresh_task_delegates_to_bounded_lifecycle_service(monkeypatch):
    captured = {}

    def fake_refresh(**kwargs):
        captured.update(kwargs)
        return {"examined": 2, "refreshed": 1, "reauthorization_required": 1, "failed": 0}

    monkeypatch.setattr("apps.jobs.tasks.refresh_due_credentials", fake_refresh)

    from apps.jobs.tasks import refresh_social_credentials

    result = refresh_social_credentials.run(organization_id="00000000-0000-4000-8000-000000000001")

    assert result["examined"] == 2
    assert captured["organization_id"] == "00000000-0000-4000-8000-000000000001"
    assert captured["limit"] == 100
