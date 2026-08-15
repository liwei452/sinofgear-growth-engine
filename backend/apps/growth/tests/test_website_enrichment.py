import pytest

from apps.growth.models import DiscoveryCandidate
from apps.growth.website_enrichment import extract_website_facts, prepare_website_enrichment
from apps.identity.models import Organization


class FakeWebsiteTransport:
    def __init__(self, pages):
        self.pages = pages

    def fetch_html(self, url, *, timeout_seconds, max_bytes):
        return self.pages[url]


def test_extract_website_facts_finds_emails_contacts_and_gear_terms():
    html = """
    <html><head><title>ABC Gearbox Repair</title></head>
    <body>
      <p>We repair industrial gearboxes and supply helical gears.</p>
      <a href="/contact">Contact us</a>
      <a href="mailto:sales@abc.example">Email</a>
      <p>sales@abc.example | +84 28 5555 0100</p>
    </body></html>
    """
    facts = extract_website_facts(html, "https://abc.example/about")
    assert facts.title == "ABC Gearbox Repair"
    assert "sales@abc.example" in facts.emails
    assert "helical gear" in facts.gear_terms
    assert any(link.endswith("/contact") for link in facts.contact_links)


def test_extract_website_facts_is_tolerant_to_empty_html():
    facts = extract_website_facts("", "https://example.com")
    assert facts.title == ""
    assert facts.emails == ()
    assert facts.gear_terms == ()


@pytest.mark.django_db
def test_prepare_website_enrichment_persists_public_contacts():
    organization = Organization.objects.create(name="Web enrichment", slug="web-enrichment")
    candidate = DiscoveryCandidate.objects.create(
        organization=organization,
        company_name="ABC Gearbox Repair",
        country="Vietnam",
        website="https://abc.example",
        industry="gearbox repair",
        status=DiscoveryCandidate.Status.ACCEPTED,
        import_format="GOOGLE_MAPS",
        record_hash="web-test-hash",
    )
    transport = FakeWebsiteTransport({
        "https://abc.example": (
            "<title>ABC Gearbox Repair</title>"
            "<p>industrial gearbox repair and helical gears</p>"
            "<p>sales@abc.example</p>"
        ),
    })

    snapshot, created = prepare_website_enrichment(candidate, transport=transport)

    assert created is True
    assert snapshot.mode == "WEBSITE_PUBLIC"
    assert any(path.get("url") == "mailto:sales@abc.example" for path in snapshot.public_contact_paths)
    assert snapshot.uncertainties == []
