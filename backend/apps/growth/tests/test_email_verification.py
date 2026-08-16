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
