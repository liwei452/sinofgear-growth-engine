from apps.common.security import scrub_secrets


def test_scrub_secrets_removes_deepseek_shaped_values_but_keeps_counts():
    secret = "sk-deepseek-secret-1234567890"
    cleaned = scrub_secrets({
        "message": secret,
        "nested": [f"Bearer {secret}", {"note": f"Authorization: Bearer {secret}"}],
        "input_tokens": 42,
    })
    assert secret not in str(cleaned)
    assert cleaned["input_tokens"] == 42
