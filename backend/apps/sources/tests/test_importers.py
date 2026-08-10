import json

import pytest
from django.core.exceptions import ValidationError

from apps.sources.importers import (
    import_result_from_reference,
    parse_import,
    prepare_import_reference,
)


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


@pytest.mark.parametrize(
    "payload",
    [
        b'\xef\xbb\xbfsource_url,original_text,author_name\r\nhttps://e.test/1,"Need, gears","Li, Wei"',
        '\ufeffsource_url,original_text,author_name\nhttps://e.test/1,"Need, gears","Li, Wei"',
    ],
)
def test_csv_accepts_one_utf8_bom_and_preserves_quoted_fields(payload):
    result = parse_import(payload, source_type="CSV")

    assert result.errors == []
    assert result.rows[0].original_text == "Need, gears"
    assert result.rows[0].author_name == "Li, Wei"


def test_csv_rejects_unknown_headers_without_retaining_the_header_value():
    result = parse_import(
        (
            "source_url,original_text,cookie,authorization,raw_headers\n"
            "https://e.test/1,Need gear,session=private,Bearer private,X-Secret"
        ),
        source_type="CSV",
    )

    assert result.rows == []
    assert result.errors == [
        {
            "row": 1,
            "code": "CSV_COLUMNS_UNEXPECTED",
            "recovery_action": "Use only supported CSV columns and re-import the file.",
        }
    ]
    assert "private" not in repr(result)


def test_csv_rejects_surplus_values_on_the_exact_source_row():
    result = parse_import(
        "source_url,original_text\nhttps://e.test/1,Need gear,secret-surplus",
        source_type="CSV",
    )

    assert result.rows == []
    assert result.errors == [
        {
            "row": 2,
            "code": "CSV_SURPLUS_VALUES",
            "recovery_action": "Remove values without matching CSV headers and re-import this row.",
        }
    ]
    assert "secret-surplus" not in repr(result)


def test_safe_reference_whitelists_json_rows_without_redacting_public_comment_text():
    raw_document = json.dumps(
        {
            "authorization": "Bearer outer-secret",
            "rows": [
                {
                    "source_url": "https://e.test/1",
                    "original_text": "The customer mentioned cookie dimensions.",
                    "cookie": "session=private",
                    "nested": {"authorization": "Bearer nested-secret"},
                    "raw_headers": {"X-Secret": "private"},
                }
            ],
        }
    )

    reference = prepare_import_reference(raw_document, source_type="JSON")

    assert set(reference) == {"schema", "source_type", "rows", "errors"}
    assert set(reference["rows"][0]) == {
        "platform",
        "source_url",
        "signal_type",
        "original_text",
        "author_name",
        "published_at",
        "screenshot_asset_id",
        "row_number",
    }
    assert reference["rows"][0]["original_text"] == (
        "The customer mentioned cookie dimensions."
    )
    persisted_shape = json.dumps(reference, sort_keys=True)
    assert "outer-secret" not in persisted_shape
    assert "nested-secret" not in persisted_shape
    assert "session=private" not in persisted_shape
    assert "X-Secret" not in persisted_shape
    assert raw_document not in persisted_shape


@pytest.mark.parametrize(
    ("source_type", "payload"),
    [
        ("URL", {"source_url": "https://e.test/url", "original_text": "URL"}),
        (
            "SCREENSHOT",
            {
                "source_url": "https://e.test/shot",
                "original_text": "Screenshot",
                "screenshot_asset_id": "00000000-0000-0000-0000-000000000001",
            },
        ),
        ("CSV", "source_url,original_text\nhttps://e.test/csv,CSV"),
        ("JSON", {"rows": [{"source_url": "https://e.test/json", "original_text": "JSON"}]}),
        ("PASTE", {"text": "https://e.test/paste\tPaste"}),
    ],
)
def test_all_prepared_modes_round_trip_their_canonical_source_type(source_type, payload):
    reference = prepare_import_reference(payload, source_type=source_type.lower())

    assert reference["source_type"] == source_type
    result = import_result_from_reference(reference, source_type=source_type)
    assert len(result.rows) == 1


@pytest.mark.parametrize("relabelled_type", ["URL", "CSV", "JSON"])
def test_prepared_paste_reference_cannot_be_parsed_as_another_source_type(
    relabelled_type,
):
    reference = prepare_import_reference(
        {"text": "https://e.test/paste\tPaste"}, source_type="PASTE"
    )

    with pytest.raises(ValidationError, match="source type"):
        import_result_from_reference(reference, source_type=relabelled_type)


def test_persisted_source_type_is_not_case_normalized_during_validation():
    reference = prepare_import_reference(
        {"text": "https://e.test/paste\tPaste"}, source_type="PASTE"
    )
    reference["source_type"] = "paste"

    with pytest.raises(ValidationError, match="source type"):
        import_result_from_reference(reference, source_type="PASTE")


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
