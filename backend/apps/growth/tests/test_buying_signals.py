from apps.growth.buying_signals import detect_buying_signals


def test_detects_industrial_buying_signals():
    text = "The mine is planning a crusher overhaul and gearbox rebuild, and hiring a maintenance engineer."
    signals = detect_buying_signals(text)
    types = {item["signal_type"] for item in signals}
    assert "CRUSHER_OVERHAUL" in types
    assert "GEARBOX_REBUILD" in types
    assert "HIRING_MAINTENANCE_ENGINEER" in types


def test_returns_empty_for_irrelevant_text():
    assert detect_buying_signals("Annual team dinner announcement") == []
