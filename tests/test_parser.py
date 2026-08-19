from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from copilot_audit.parser import parse_blob

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("compressed", [False, True])
def test_parses_plain_and_gzip_despite_suffix(compressed: bool) -> None:
    content = (FIXTURES / "object.json").read_bytes()
    payload = gzip.compress(content) if compressed else content

    result = parse_blob(payload)

    assert len(result) == 1
    assert result[0].parse_status == "parsed"
    assert result[0].value is not None
    assert result[0].raw_content == content.decode()
    expected_encoding = "gzip+utf-8-json" if compressed else "utf-8-json"
    assert result[0].raw_encoding == expected_encoding


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [("object.json", 1), ("array.json", 2), ("events.jsonl", 2)],
)
def test_parses_supported_shapes(fixture: str, expected: int) -> None:
    assert len(parse_blob((FIXTURES / fixture).read_bytes())) == expected


def test_array_item_preserves_duplicate_fields_exactly() -> None:
    raw_item = '{"authorization":"synthetic-first","authorization":"synthetic-second"}'

    result = parse_blob(f"[ {raw_item} ]".encode())

    assert result[0].raw_content == raw_item
    assert result[0].raw_encoding == "utf-8-json-array-item"


def test_malformed_json_line_retains_raw_item() -> None:
    result = parse_blob(b'{"action":"ok"}\nnot-json\n{"action":"also-ok"}')

    assert [item.index for item in result] == [0, 1, 2]
    assert result[1].value is None
    assert result[1].parse_status == "invalid_json"
    assert result[1].raw_content == "not-json"
    assert result[1].raw_encoding == "utf-8-text-jsonl-record"


def test_invalid_gzip_is_not_treated_as_plain_text() -> None:
    result = parse_blob(b"\x1f\x8bnot-gzip")

    assert result[0].value is None
    assert result[0].parse_status == "invalid_gzip"
    assert result[0].raw_encoding == "base64-invalid-gzip"
    assert result[0].raw_content


def test_zlib_corruption_becomes_metadata_status() -> None:
    result = parse_blob(b"\x1f\x8b\x08\x00" + (b"x" * 50))

    assert result[0].value is None
    assert result[0].parse_status == "invalid_gzip"
    assert result[0].raw_encoding == "base64-invalid-gzip"


def test_jsonl_record_boundaries_and_raw_lines_are_preserved() -> None:
    payload = b'{"a":1}\n  { "b": 2 }  \nmalformed synthetic'

    result = parse_blob(payload)

    assert [item.index for item in result] == [0, 1, 2]
    assert [item.raw_content for item in result] == [
        '{"a":1}',
        '  { "b": 2 }  ',
        "malformed synthetic",
    ]


def test_invalid_utf8_is_retained_as_base64() -> None:
    result = parse_blob(b"\xff\xfe\xfd")

    assert result[0].parse_status == "invalid_utf8"
    assert result[0].raw_encoding == "base64"
    assert result[0].raw_content == "//79"
