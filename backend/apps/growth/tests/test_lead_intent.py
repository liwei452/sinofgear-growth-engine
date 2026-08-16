from apps.growth.lead_intent import intent_score_from_visits


def test_intent_score_accumulates_website_signals():
    paths = [
        "/replacement-gears/",
        "/reverse-engineering-gears/",
        "/quality/",
        "/products/spur-gears",
        "/products/helical-gears",
    ]
    score, breakdown = intent_score_from_visits(paths, email_clicked=True, sessions=2)
    assert breakdown["email_click"] == 5
    assert breakdown["return_visit"] == 8
    assert breakdown["multi_product"] == 5
    assert score == 5 + 8 + 5 + (8 + 10 + 5 + 5 + 5)


def test_intent_score_is_zero_without_signals():
    score, breakdown = intent_score_from_visits([], sessions=1)
    assert score == 0
    assert breakdown == {
        "email_click": 0,
        "page_signals": 0,
        "return_visit": 0,
        "multi_product": 0,
    }
