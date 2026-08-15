from apps.growth.contact_intelligence import infer_name_from_email


def test_infers_name_from_email():
    assert infer_name_from_email("john.smith@example.com") == "John Smith"
    assert infer_name_from_email("maintenance@example.com") == "Maintenance"


def test_handles_numeric_local_part():
    assert infer_name_from_email("info2024@example.com") == "Info"
