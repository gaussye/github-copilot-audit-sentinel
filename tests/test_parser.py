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


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [("object.json", 1), ("array.json", 2), ("events.jsonl", 2)],
)
def test_parses_supported_shapes(fixture: str, expected: int) -> None:
    assert len(parse_blob((FIXTURES / fixture).read_bytes())) == expected


def test_malformed_json_line_becomes_metadata_only_item() -> None:
    result = parse_blob(b'{"action":"ok"}\nnot-json\n{"action":"also-ok"}')

    assert [item.index for item in result] == [0, 1, 2]
    assert result[1].value is None
    assert result[1].parse_status == "invalid_json"


def test_invalid_gzip_is_not_treated_as_plain_text() -> None:
    result = parse_blob(b"\x1f\x8bnot-gzip")

    assert result[0].value is None
    assert result[0].parse_status == "invalid_gzip"


def test_zlib_corruption_becomes_metadata_status() -> None:
    result = parse_blob(b"\x1f\x8b\x08\x00" + (b"x" * 50))

    assert result[0].value is None
    assert result[0].parse_status == "invalid_gzip"
