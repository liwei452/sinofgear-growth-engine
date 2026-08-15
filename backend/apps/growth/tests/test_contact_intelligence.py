from apps.growth.contact_intelligence import extract_team_contacts, infer_name_from_email


def test_infers_name_from_email():
    assert infer_name_from_email("john.smith@example.com") == "John Smith"
    assert infer_name_from_email("maintenance@example.com") == "Maintenance"


def test_handles_numeric_local_part():
    assert infer_name_from_email("info2024@example.com") == "Info"


def test_extracts_team_contact_with_role_hint():
    html = (
        "<h2>John Smith</h2><p>Procurement Manager</p>"
        "<a href='mailto:john.smith@example.com'>john.smith@example.com</a>"
    )
    contacts = extract_team_contacts(html, "https://abc.example/team")
    assert len(contacts) == 1
    assert contacts[0]["email"] == "john.smith@example.com"
    assert contacts[0]["name_hint"] == "John Smith"
    assert contacts[0]["role_hint"] == "procurement"
    assert contacts[0]["verification_status"] == "UNVERIFIED"
