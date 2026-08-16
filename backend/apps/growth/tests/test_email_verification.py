from apps.growth.email_verification import verify_email


def test_rejects_invalid_syntax(monkeypatch):
    monkeypatch.setattr("socket.gethostbyname", lambda host: "1.2.3.4")
    assert verify_email("not-an-email")["status"] == "INVALID_SYNTAX"


def test_detects_resolvable_domain(monkeypatch):
    monkeypatch.setattr("socket.gethostbyname", lambda host: "1.2.3.4")
    result = verify_email("sales@example.com")
    assert result["status"] == "DOMAIN_RESOLVES"
    assert result["domain_resolves"] is True


def test_detects_unresolvable_domain(monkeypatch):
    def raise_error(_host):
        raise OSError("no address")

    monkeypatch.setattr("socket.gethostbyname", raise_error)
    result = verify_email("sales@does-not-exist.invalid")
    assert result["status"] == "DOMAIN_UNRESOLVABLE"


def fake_provider():
    class _FakeProvider:
        def verify(self, email):
            return {"email": email, "status": "FAKE_VERIFIED", "domain_resolves": True}

    return _FakeProvider()


def test_verify_email_uses_configured_provider(settings):
    settings.EMAIL_VERIFICATION_PROVIDER_FACTORY = (
        "apps.growth.tests.test_email_verification.fake_provider"
    )
    assert verify_email("a@b.com")["status"] == "FAKE_VERIFIED"
