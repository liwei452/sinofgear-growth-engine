import json

import pytest
from django.core.exceptions import ValidationError

from apps.sources.importers import parse_import


@pytest.mark.parametrize(
    ("source_type", "payload", "expected_url", "expected_text"),
    [
        (
            "URL",
            {"source_url": "https://example.com/p/1", "original_text": "Need gear quote"},
            "https://example.com/p/1",
            "Need gear quote",
        ),
        (
            "SCREENSHOT",
            {
                "source_url": "https://example.com/p/2",
                "original_text": "200 pcs",
                "screenshot_asset_id": "00000000-0000-0000-0000-000000000001",
            },
            "https://example.com/p/2",
            "200 pcs",
        ),
        (
            "CSV",
            "source_url,original_text\nhttps://example.com/p/3,DIN 6",
            "https://example.com/p/3",
            "DIN 6",
        ),
        (
            "JSON",
            {"rows": [{"source_url": "https://example.com/p/4", "original_text": "Module 2"}]},
            "https://example.com/p/4",
            "Module 2",
        ),
        (
            "PASTE",
            {"text": "https://example.com/p/5\tNeed replacement gear"},
            "https://example.com/p/5",
            "Need replacement gear",
        ),
    ],
)
def test_parse_import_supports_every_guided_b1_mode(
    source_type, payload, expected_url, expected_text
):
    result = parse_import(payload, source_type=source_type)

    assert result.errors == []
    assert len(result.rows) == 1
    assert result.rows[0].source_url == expected_url
    assert result.rows[0].original_text == expected_text


def test_csv_preserves_valid_neighbors_and_reports_the_original_row_number():
    result = parse_import(
        "source_url,original_text\nhttps://e.test/1,Need gear\n,Missing URL",
        source_type="CSV",
    )

    assert [row.row_number for row in result.rows] == [2]
    assert result.rows[0].source_url == "https://e.test/1"
    assert result.errors == [
        {
            "row": 3,
            "code": "SOURCE_URL_REQUIRED",
            "recovery_action": "Provide a public source URL and re-import this row.",
        }
    ]


def test_json_bytes_are_strict_utf8_and_invalid_rows_do_not_discard_valid_rows():
    payload = json.dumps(
        {
            "rows": [
                {"source_url": "https://e.test/1", "original_text": "Need gear"},
                {"source_url": "javascript:alert(1)", "original_text": "Bad URL"},
            ]
        }
    ).encode("utf-8")

    result = parse_import(payload, source_type="JSON")

    assert [row.source_url for row in result.rows] == ["https://e.test/1"]
    assert result.errors[0]["row"] == 2
    assert result.errors[0]["code"] == "SOURCE_URL_INVALID"
    with pytest.raises(ValidationError, match="UTF-8"):
        parse_import(b"\xff", source_type="JSON")


def test_csv_formula_is_retained_as_inert_text():
    result = parse_import(
        'source_url,original_text\nhttps://e.test/1,"=1+1"', source_type="CSV"
    )

    assert result.rows[0].original_text == "=1+1"


def test_original_text_over_20_000_characters_is_a_row_error():
    result = parse_import(
        {"source_url": "https://e.test/1", "original_text": "x" * 20_001},
        source_type="URL",
    )

    assert result.rows == []
    assert result.errors[0]["code"] == "ORIGINAL_TEXT_TOO_LONG"


def test_more_than_10_000_rows_is_a_batch_error():
    payload = {
        "rows": [
            {"source_url": f"https://e.test/{index}", "original_text": "Need gear"}
            for index in range(10_001)
        ]
    }

    with pytest.raises(ValidationError) as error:
        parse_import(payload, source_type="JSON")

    assert error.value.error_dict["rows"][0].code == "BATCH_ROW_LIMIT_EXCEEDED"


@pytest.mark.parametrize("source_type", ["API", "UNKNOWN"])
def test_unsupported_or_out_of_scope_modes_are_rejected(source_type):
    with pytest.raises(ValidationError, match="Unsupported source type"):
        parse_import({}, source_type=source_type)
